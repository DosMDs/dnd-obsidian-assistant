"""Golden Vault integration tests for the retrieval + entity-resolution stack.

Tests the real concrete stack against a temporary copy of the Golden Vault
fixture:

    Golden Vault copy
        → ObsidianVaultRepository
        → SqliteFtsIndex
        → VaultSearchService
        → SearchEntityResolver

Every mutation test operates on a ``tmp_path`` copy of the committed
fixture at ``tests/fixtures/golden_test_vault/``.  The committed fixture
is never used as a writable index root.
"""

from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

import pytest
from rapidfuzz import fuzz

from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import StorageError
from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.retrieval.resolver import SearchEntityResolver
from dnd_assistant.retrieval.search import VaultSearchService
from dnd_assistant.retrieval.types import (
    Ambiguous,
    MatchKind,
    NotFound,
    Resolved,
    SearchQuery,
)
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

# ── Fixture source path ──────────────────────────────────────────────────────

_GOLDEN_SOURCE = Path(__file__).resolve().parent.parent / "fixtures" / "golden_test_vault"

# ── Expected MVP entity counts from the committed fixture ────────────────────

EXPECTED_MVP_COUNT = 23  # 10 NPC + 5 Location + 3 Quest + 5 Item
EXPECTED_PLAYER_VISIBLE_COUNT = 22  # 23 total minus 1 DM (npc_archivist_kell)


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def golden_vault_root(tmp_path: Path) -> Path:
    """Create a temporary writable copy of the Golden Vault fixture.

    All mutation tests operate on this copy.  The committed fixture at
    ``tests/fixtures/golden_test_vault/`` is never modified.
    """
    assert _GOLDEN_SOURCE.is_dir(), f"Golden Vault fixture not found: {_GOLDEN_SOURCE}"
    destination = tmp_path / "golden_test_vault"
    shutil.copytree(_GOLDEN_SOURCE, destination)
    return destination


@pytest.fixture
def audit_service(golden_vault_root: Path) -> AuditService:
    """Real AuditService pointing at the temporary Golden Vault copy."""
    audit_log = golden_vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(audit_log)


@pytest.fixture
def repo(golden_vault_root: Path, audit_service: AuditService) -> ObsidianVaultRepository:
    """Real ObsidianVaultRepository over the temporary Golden Vault copy."""
    return ObsidianVaultRepository(golden_vault_root, audit_service)


@pytest.fixture
def fts_index(golden_vault_root: Path) -> SqliteFtsIndex:
    """Real SqliteFtsIndex over the temporary Golden Vault copy."""
    return SqliteFtsIndex(golden_vault_root)


@pytest.fixture
def search_service(repo: ObsidianVaultRepository) -> VaultSearchService:
    """Real VaultSearchService without FTS (for exact/fuzzy tests)."""
    return VaultSearchService(repository=repo)


@pytest.fixture
def search_service_with_fts(
    repo: ObsidianVaultRepository, fts_index: SqliteFtsIndex
) -> VaultSearchService:
    """Real VaultSearchService with FTS (for FTS tier tests)."""
    return VaultSearchService(repository=repo, lexical_index=fts_index)


@pytest.fixture
def resolver(search_service: VaultSearchService) -> SearchEntityResolver:
    """Real SearchEntityResolver without FTS."""
    return SearchEntityResolver(search_service=search_service)


@pytest.fixture
def resolver_with_fts(
    search_service_with_fts: VaultSearchService,
) -> SearchEntityResolver:
    """Real SearchEntityResolver with FTS."""
    return SearchEntityResolver(search_service=search_service_with_fts)


@pytest.fixture
def rebuilt_index(repo: ObsidianVaultRepository, fts_index: SqliteFtsIndex) -> SqliteFtsIndex:
    """Rebuild the FTS index from the real repository."""
    documents = repo.list_entities()
    fts_index.rebuild(documents)
    return fts_index


# ═══════════════════════════════════════════════════════════════════════════════
# Baseline sanity
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenVaultBaseline:
    """Verify the Golden Vault fixture is parsed correctly by the real
    repository, and that the Golden fixture itself is not mutated."""

    def test_golden_source_is_unchanged(self) -> None:
        """The committed fixture must never be used as a writable index root."""
        assert _GOLDEN_SOURCE.is_dir()
        index_dir = _GOLDEN_SOURCE / "_system" / "indexes"
        db_files = list(index_dir.glob("*.sqlite3")) + list(index_dir.glob("*.sqlite"))
        assert not db_files, f"Generated DB found in committed fixture: {db_files}"

    def test_mvp_entity_count(self, repo: ObsidianVaultRepository) -> None:
        """All 23 MVP entities are discovered."""
        all_docs = repo.list_entities()
        assert len(all_docs) == EXPECTED_MVP_COUNT

    def test_player_visible_count(self, repo: ObsidianVaultRepository) -> None:
        """22 player-visible entities, 1 DM entity."""
        all_docs = repo.list_entities()
        player_docs = [d for d in all_docs if d.entity.visibility.value == "player"]
        dm_docs = [d for d in all_docs if d.entity.visibility.value == "dm"]
        assert len(player_docs) == EXPECTED_PLAYER_VISIBLE_COUNT
        assert len(dm_docs) == 1

    def test_dm_entity_present_in_repo(self, repo: ObsidianVaultRepository) -> None:
        """The DM entity is discoverable by the repository (it exists on disk)."""
        all_ids = {d.entity.id for d in repo.list_entities()}
        assert "npc_archivist_kell" in all_ids

    def test_entity_types_are_correct(self, repo: ObsidianVaultRepository) -> None:
        """Each entity has the expected EntityType."""
        docs = repo.list_entities()
        for doc in docs:
            if doc.entity.id.startswith("npc_"):
                assert doc.entity.type == EntityType.NPC, f"{doc.entity.id} is not NPC"
            elif doc.entity.id.startswith("loc_"):
                assert doc.entity.type == EntityType.LOCATION, f"{doc.entity.id} is not LOCATION"
            elif doc.entity.id.startswith("quest_"):
                assert doc.entity.type == EntityType.QUEST, f"{doc.entity.id} is not QUEST"
            elif doc.entity.id.startswith("item_"):
                assert doc.entity.type == EntityType.ITEM, f"{doc.entity.id} is not ITEM"

    def test_aliases_in_extra_frontmatter(self, repo: ObsidianVaultRepository) -> None:
        """Aliases are stored in extra_frontmatter, not on the Entity model."""
        varos = repo.get_entity("npc_varos")
        aliases = varos.extra_frontmatter.get("aliases")
        assert aliases is not None
        assert isinstance(aliases, list)
        assert "Варос" in aliases
        assert "Лорд Варос" in aliases
        assert "Магистр Варос" in aliases
        assert not hasattr(varos.entity, "aliases")

    def test_unicode_preserved(self, repo: ObsidianVaultRepository) -> None:
        """Cyrillic names are preserved correctly through the repository."""
        varos = repo.get_entity("npc_varos")
        assert varos.entity.name == "Магистр Варос"
        grayford = repo.get_entity("loc_grayford")
        assert grayford.entity.name == "Серый Брод"


# ═══════════════════════════════════════════════════════════════════════════════
# Exact retrieval (EXACT_ID / EXACT_NAME / EXACT_ALIAS)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenExactRetrieval:
    """Exact stable-ID, exact canonical-name, and exact alias retrieval
    through the real VaultSearchService."""

    def test_exact_id_npc_varos(self, search_service: VaultSearchService) -> None:
        """Exact stable ID ``npc_varos`` returns one EXACT_ID hit."""
        hits = search_service.search(SearchQuery(text="npc_varos"))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"
        assert hits[0].match_kind == MatchKind.EXACT_ID

    def test_exact_id_via_get_by_id(self, search_service: VaultSearchService) -> None:
        """get_by_id returns the correct SearchHit for a visible entity."""
        hit = search_service.get_by_id("npc_varos")
        assert hit is not None
        assert hit.entity_id == "npc_varos"
        assert hit.match_kind == MatchKind.EXACT_ID

    def test_get_by_id_missing_returns_none(self, search_service: VaultSearchService) -> None:
        """get_by_id for a non-existent ID returns None."""
        assert search_service.get_by_id("npc_nonexistent") is None

    def test_exact_name_magistr_varos(self, search_service: VaultSearchService) -> None:
        """Exact canonical name ``Магистр Варос`` returns one EXACT_NAME hit."""
        hits = search_service.search(SearchQuery(text="Магистр Варос"))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_name_with_whitespace(self, search_service: VaultSearchService) -> None:
        """Surrounding whitespace is normalised for exact-name matching."""
        hits = search_service.search(SearchQuery(text="  Магистр Варос  "))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_name_precedence_over_same_entity_alias(
        self, search_service: VaultSearchService
    ) -> None:
        """When the query matches both name and alias of the same entity,
        EXACT_NAME wins (higher precedence than EXACT_ALIAS).

        ``Магистр Варос`` is both the canonical name and an alias of
        npc_varos.  Result must be EXACT_NAME, not EXACT_ALIAS.
        """
        hits = search_service.search(SearchQuery(text="Магистр Варос"))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_name_vs_alias_different_entity(self, search_service: VaultSearchService) -> None:
        """EXACT_NAME for one entity beats EXACT_ALIAS for another.

        ``Варос Младший`` is the canonical name of npc_varos_junior.
        ``Варос`` is an alias of npc_varos.  Searching for ``Варос Младший``
        should match the name, not the alias.
        """
        hits = search_service.search(SearchQuery(text="Варос Младший"))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos_junior"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_alias_lord_varos(self, search_service: VaultSearchService) -> None:
        """Unique alias ``Лорд Варос`` resolves to npc_varos via EXACT_ALIAS."""
        hits = search_service.search(SearchQuery(text="Лорд Варос"))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"
        assert hits[0].match_kind == MatchKind.EXACT_ALIAS

    def test_exact_alias_grayford(self, search_service: VaultSearchService) -> None:
        """Location alias ``Грейфорд`` resolves to loc_grayford."""
        hits = search_service.search(SearchQuery(text="Грейфорд"))
        assert len(hits) == 1
        assert hits[0].entity_id == "loc_grayford"
        assert hits[0].match_kind == MatchKind.EXACT_ALIAS

    def test_exact_alias_english_grayford(self, search_service: VaultSearchService) -> None:
        """Location English alias ``Grayford`` resolves to loc_grayford."""
        hits = search_service.search(SearchQuery(text="Grayford"))
        assert len(hits) == 1
        assert hits[0].entity_id == "loc_grayford"
        assert hits[0].match_kind == MatchKind.EXACT_ALIAS

    def test_entity_type_filter_npc(self, search_service: VaultSearchService) -> None:
        """Entity-type filter for NPC returns only NPC results."""
        hits = search_service.search(SearchQuery(text="npc_varos", entity_types={EntityType.NPC}))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"

    def test_entity_type_filter_location(self, search_service: VaultSearchService) -> None:
        """Entity-type filter for LOCATION returns only location results."""
        hits = search_service.search(
            SearchQuery(text="Серый Брод", entity_types={EntityType.LOCATION})
        )
        assert len(hits) == 1
        assert hits[0].entity_id == "loc_grayford"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_entity_type_filter_quest(self, search_service: VaultSearchService) -> None:
        """Entity-type filter for QUEST returns only quest results."""
        hits = search_service.search(
            SearchQuery(text="Пропавший караван", entity_types={EntityType.QUEST})
        )
        assert len(hits) == 1
        assert hits[0].entity_id == "quest_missing_caravan"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_entity_type_filter_item(self, search_service: VaultSearchService) -> None:
        """Entity-type filter for ITEM returns only item results."""
        hits = search_service.search(
            SearchQuery(text="Серебряный ключ", entity_types={EntityType.ITEM})
        )
        assert len(hits) == 1
        assert hits[0].entity_id == "item_silver_key"
        assert hits[0].match_kind == MatchKind.EXACT_NAME


# ═══════════════════════════════════════════════════════════════════════════════
# Ambiguity — alias collision
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenAmbiguity:
    """Alias-collision and fuzzy-collision ambiguity through the real stack."""

    def test_alias_collision_varos_search(self, search_service: VaultSearchService) -> None:
        """Search for ``Варос`` returns 2 EXACT_ALIAS hits (npc_varos and
        npc_varos_junior both share this alias)."""
        hits = search_service.search(SearchQuery(text="Варос", entity_types={EntityType.NPC}))
        assert len(hits) == 2
        hit_ids = {h.entity_id for h in hits}
        assert hit_ids == {"npc_varos", "npc_varos_junior"}
        for h in hits:
            assert h.match_kind == MatchKind.EXACT_ALIAS
        # Deterministic ordering: EntityId ascending
        assert hits[0].entity_id < hits[1].entity_id

    def test_alias_collision_varos_resolver(self, resolver: SearchEntityResolver) -> None:
        """Resolver returns Ambiguous for the colliding alias ``Варос``.

        Candidate order from SearchService is preserved unchanged by the
        resolver.  The resolver does NOT reorder or rescore candidates.
        """
        outcome = resolver.resolve("Варос", entity_type=EntityType.NPC)
        assert isinstance(outcome, Ambiguous)
        # Assert exact candidate order (not set): EntityId ascending
        assert [c.entity_id for c in outcome.candidates] == [
            "npc_varos",
            "npc_varos_junior",
        ]
        for c in outcome.candidates:
            assert c.match_kind == MatchKind.EXACT_ALIAS

    def test_unique_alias_lord_varos_resolver(self, resolver: SearchEntityResolver) -> None:
        """Unique alias ``Лорд Варос`` resolves to npc_varos."""
        outcome = resolver.resolve("Лорд Варос", entity_type=EntityType.NPC)
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_ALIAS

    def test_unique_alias_magistr_varos_resolver(self, resolver: SearchEntityResolver) -> None:
        """Unique alias ``Магистр Варос`` resolves to npc_varos via
        EXACT_NAME (name takes precedence over alias)."""
        outcome = resolver.resolve("Магистр Варос", entity_type=EntityType.NPC)
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_NAME

    def test_not_found_resolver(self, resolver: SearchEntityResolver) -> None:
        """Resolver returns NotFound for a non-existent reference."""
        outcome = resolver.resolve("ZZZZZZZZ")
        assert isinstance(outcome, NotFound)


# ═══════════════════════════════════════════════════════════════════════════════
# Fuzzy retrieval
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenFuzzyRetrieval:
    """Fuzzy canonical-name retrieval through the real stack.

    The Golden Vault contains the fuzzy-near pair:
    - npc_ender: ``Маг Эндер``
    - npc_endrin: ``Эндрин``
    """

    def test_fuzzy_query_ender(self, search_service: VaultSearchService) -> None:
        """A partial query ``Эндр`` reaches the FUZZY_NAME tier.

        This query does NOT match any exact ID, exact name, or exact alias.
        """
        hits = search_service.search(SearchQuery(text="Эндр"))
        assert len(hits) >= 1
        for h in hits:
            assert h.match_kind == MatchKind.FUZZY_NAME
            assert h.score is not None
            assert h.score > 0.0
        # Both npc_ender and npc_endrin should appear
        hit_ids = {h.entity_id for h in hits}
        assert "npc_ender" in hit_ids
        assert "npc_endrin" in hit_ids

    def test_fuzzy_query_ender_resolver(self, resolver: SearchEntityResolver) -> None:
        """Fuzzy-only query resolves to Ambiguous (no auto-resolution for
        fuzzy matches)."""
        outcome = resolver.resolve("Эндр")
        assert isinstance(outcome, Ambiguous)

    def test_fuzzy_score_is_finite(self, search_service: VaultSearchService) -> None:
        """All fuzzy scores are finite floats."""
        hits = search_service.search(SearchQuery(text="Эндр"))
        for h in hits:
            assert h.match_kind == MatchKind.FUZZY_NAME
            import math

            assert math.isfinite(h.score)

    def test_fuzzy_ordering_score_desc_then_id(self, search_service: VaultSearchService) -> None:
        """Fuzzy results are ordered by score descending, then EntityId
        ascending."""
        hits = search_service.search(SearchQuery(text="Эндр"))
        fuzzy_hits = [h for h in hits if h.match_kind == MatchKind.FUZZY_NAME]
        for i in range(len(fuzzy_hits) - 1):
            if fuzzy_hits[i].score == fuzzy_hits[i + 1].score:
                assert fuzzy_hits[i].entity_id < fuzzy_hits[i + 1].entity_id
            else:
                assert fuzzy_hits[i].score > fuzzy_hits[i + 1].score

    def test_no_arbitrary_fuzzy_threshold(
        self, search_service: VaultSearchService, repo: ObsidianVaultRepository
    ) -> None:
        """No numeric fuzzy threshold is introduced.

        Every eligible PLAYER-visible canonical name with
        ``fuzz.ratio(normalised_query, normalised_name) > 0.0`` is
        returned.  No hidden confidence cutoff exists.

        The explicit ``limit=100`` ensures the Golden Vault size (22
        player-visible entities) does not truncate eligible candidates.
        """
        query = "Эндр"
        limit = 100

        # Independently compute expected fuzzy candidates from the real
        # repository using the same normalisation policy as the production
        # SearchService (strip → NFC → casefold).
        def _normalized(text: str) -> str:
            return unicodedata.normalize("NFC", text.strip()).casefold()

        normalized_query = _normalized(query)
        all_docs = repo.list_entities()
        expected: list[tuple[str, float]] = []
        for doc in all_docs:
            if doc.entity.visibility.value != "player":
                continue
            normalized_name = _normalized(doc.entity.name)
            score = fuzz.ratio(normalized_query, normalized_name)
            if score > 0.0:
                expected.append((doc.entity.id, float(score)))

        # Sort by score descending, then EntityId ascending
        expected.sort(key=lambda pair: (-pair[1], pair[0]))

        hits = search_service.search(SearchQuery(text=query), limit=limit)
        fuzzy_hits = [h for h in hits if h.match_kind == MatchKind.FUZZY_NAME]

        # 1. Every returned hit is FUZZY_NAME
        for h in fuzzy_hits:
            assert h.match_kind == MatchKind.FUZZY_NAME

        # 2. Actual EntityId sequence equals the independently computed
        #    expected sequence
        assert [h.entity_id for h in fuzzy_hits] == [eid for eid, _ in expected]

        # 3. Actual scores correspond to expected scores
        for h, (_, expected_score) in zip(fuzzy_hits, expected, strict=True):
            assert h.score == pytest.approx(expected_score)

        # 4. Every expected score is > 0
        for _, s in expected:
            assert s > 0.0

        # 5. No positive expected candidate is missing
        assert len(fuzzy_hits) == len(expected)

        # 6. No zero-score candidate is returned
        for h in fuzzy_hits:
            assert h.score is not None
            assert h.score > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Player-visibility safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenVisibility:
    """DM-visibility entities must never appear in player retrieval results."""

    def test_dm_exact_id_search(self, search_service: VaultSearchService) -> None:
        """Search for the DM entity's stable ID returns no EXACT_ID hit."""
        hits = search_service.search(SearchQuery(text="npc_archivist_kell"))
        hit_ids = {h.entity_id for h in hits}
        assert "npc_archivist_kell" not in hit_ids

    def test_dm_get_by_id_returns_none(self, search_service: VaultSearchService) -> None:
        """get_by_id for a DM entity returns None."""
        hit = search_service.get_by_id("npc_archivist_kell")
        assert hit is None

    def test_dm_resolver_never_returns_hidden(self, resolver: SearchEntityResolver) -> None:
        """Resolver must never return the DM entity."""
        outcome = resolver.resolve("npc_archivist_kell", entity_type=EntityType.NPC)
        if isinstance(outcome, Ambiguous):
            candidate_ids = {c.entity_id for c in outcome.candidates}
            assert "npc_archivist_kell" not in candidate_ids
        elif isinstance(outcome, Resolved):
            assert outcome.entity_id != "npc_archivist_kell"
        # NotFound is also acceptable — the important thing is the DM
        # entity never appears

    def test_dm_alias_not_searchable(self, search_service: VaultSearchService) -> None:
        """The DM entity's alias ``Келл`` must not appear in results."""
        hits = search_service.search(SearchQuery(text="Келл"))
        hit_ids = {h.entity_id for h in hits}
        assert "npc_archivist_kell" not in hit_ids


# ═══════════════════════════════════════════════════════════════════════════════
# FTS (Full-Text Search) integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenFts:
    """FTS tier through the real stack with a rebuilt index."""

    def test_rebuild_creates_index(self, rebuilt_index: SqliteFtsIndex) -> None:
        """Rebuild creates the SQLite DB at the expected path."""
        assert rebuilt_index.index_path.exists()
        assert rebuilt_index.index_path.suffix == ".sqlite3"

    def test_rebuild_index_freshness(
        self, repo: ObsidianVaultRepository, rebuilt_index: SqliteFtsIndex
    ) -> None:
        """Index is fresh immediately after rebuild."""
        rebuilt_index.verify_freshness(repo.list_entities())

    def test_dm_entity_absent_from_fts(
        self, repo: ObsidianVaultRepository, rebuilt_index: SqliteFtsIndex
    ) -> None:
        """The DM NPC must not appear in FTS results."""
        hits = rebuilt_index.search("Келл")
        hit_ids = {h.entity_id for h in hits}
        assert "npc_archivist_kell" not in hit_ids

    def test_fts_tier_reachable_through_search_service(
        self,
        repo: ObsidianVaultRepository,
        search_service_with_fts: VaultSearchService,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """FTS tier is reachable through VaultSearchService for a query
        that does not match higher tiers.

        The body of npc_varos contains ``S005`` in a History subsection.
        No entity has ``S005`` as its name, ID, or alias, so this query
        reaches the FTS tier.
        """
        hits = search_service_with_fts.search(SearchQuery(text="S005"))
        assert len(hits) >= 1
        for h in hits:
            assert h.match_kind == MatchKind.FTS
            assert h.score is not None
        hit_ids = {h.entity_id for h in hits}
        assert "npc_varos" in hit_ids

    def test_fts_scores_are_finite(
        self,
        search_service_with_fts: VaultSearchService,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """All FTS scores are finite floats."""
        hits = search_service_with_fts.search(SearchQuery(text="S005"))
        import math

        for h in hits:
            assert h.match_kind == MatchKind.FTS
            assert math.isfinite(h.score)

    def test_fts_resolver_ambiguous(
        self,
        resolver_with_fts: SearchEntityResolver,
        repo: ObsidianVaultRepository,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """FTS-only query resolves to Ambiguous (FTS relevance is not
        identity confidence)."""
        outcome = resolver_with_fts.resolve("S005")
        assert isinstance(outcome, Ambiguous)

    def test_fts_entity_type_filter(
        self,
        search_service_with_fts: VaultSearchService,
        repo: ObsidianVaultRepository,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """Entity-type filtering works for FTS results."""
        hits = search_service_with_fts.search(
            SearchQuery(text="S005", entity_types={EntityType.LOCATION})
        )
        for h in hits:
            assert h.match_kind == MatchKind.FTS
        hit_ids = {h.entity_id for h in hits}
        for eid in hit_ids:
            assert eid.startswith("loc_"), f"Non-location in FTS results: {eid}"


# ═══════════════════════════════════════════════════════════════════════════════
# Index freshness and staleness
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenFreshness:
    """Index freshness, staleness detection, and rebuild recovery."""

    def test_fresh_after_rebuild(
        self, repo: ObsidianVaultRepository, rebuilt_index: SqliteFtsIndex
    ) -> None:
        """Index is fresh immediately after rebuild."""
        rebuilt_index.verify_freshness(repo.list_entities())

    def test_dm_only_mutation_does_not_stale(
        self,
        golden_vault_root: Path,
        repo: ObsidianVaultRepository,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """Modifying only a DM entity's body does not stale the player
        fingerprint."""
        dm_path = golden_vault_root / "Characters" / "NPCs" / "10-npc_archivist_kell.md"
        original = dm_path.read_text(encoding="utf-8")
        modified = original.replace(
            "Этот NPC имеет `visibility: dm`",
            "Этот NPC имеет `visibility: dm` и был изменён",
        )
        dm_path.write_text(modified, encoding="utf-8")
        current_docs = repo.list_entities()
        rebuilt_index.verify_freshness(current_docs)

    def test_player_mutation_stales_index(
        self,
        golden_vault_root: Path,
        repo: ObsidianVaultRepository,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """Modifying a player-visible entity's body stales the index."""
        player_path = golden_vault_root / "Characters" / "NPCs" / "01-npc_varos.md"
        original = player_path.read_text(encoding="utf-8")
        modified = original.replace(
            "Городской магистрат Серого Брода.",
            "Городской магистрат Серого Брода. (изменено для теста)",
        )
        player_path.write_text(modified, encoding="utf-8")
        current_docs = repo.list_entities()
        with pytest.raises(StorageError):
            rebuilt_index.verify_freshness(current_docs)

    def test_rebuild_recovers_from_stale(
        self,
        golden_vault_root: Path,
        repo: ObsidianVaultRepository,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """Rebuild restores freshness after a player mutation."""
        player_path = golden_vault_root / "Characters" / "NPCs" / "01-npc_varos.md"
        original = player_path.read_text(encoding="utf-8")
        modified = original.replace(
            "Городской магистрат Серого Брода.",
            "Городской магистрат Серого Брода. (rebuild test)",
        )
        player_path.write_text(modified, encoding="utf-8")
        current_docs = repo.list_entities()
        rebuilt_index.rebuild(current_docs)
        rebuilt_index.verify_freshness(current_docs)

    def test_exact_search_works_with_stale_fts(
        self,
        golden_vault_root: Path,
        repo: ObsidianVaultRepository,
        search_service_with_fts: VaultSearchService,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """Exact-name search succeeds even when FTS is stale."""
        player_path = golden_vault_root / "Characters" / "NPCs" / "01-npc_varos.md"
        original = player_path.read_text(encoding="utf-8")
        modified = original.replace(
            "Городской магистрат Серого Брода.",
            "Городской магистрат Серого Брода. (stale test)",
        )
        player_path.write_text(modified, encoding="utf-8")
        repo.list_entities()
        hits = search_service_with_fts.search(SearchQuery(text="Магистр Варос"))
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_varos"
        assert hits[0].match_kind == MatchKind.EXACT_NAME

    def test_stale_fts_raises_storage_error(
        self,
        golden_vault_root: Path,
        repo: ObsidianVaultRepository,
        search_service_with_fts: VaultSearchService,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """A query that reaches the FTS tier after player source mutation
        propagates StorageError."""
        player_path = golden_vault_root / "Characters" / "NPCs" / "01-npc_varos.md"
        original = player_path.read_text(encoding="utf-8")
        modified = original.replace(
            "Городской магистрат Серого Брода.",
            "Городской магистрат Серого Брода. (stale error test)",
        )
        player_path.write_text(modified, encoding="utf-8")
        repo.list_entities()
        with pytest.raises(StorageError):
            search_service_with_fts.search(SearchQuery(text="S005"))

    def test_stale_fts_resolver_propagates_error(
        self,
        golden_vault_root: Path,
        repo: ObsidianVaultRepository,
        resolver_with_fts: SearchEntityResolver,
        rebuilt_index: SqliteFtsIndex,
    ) -> None:
        """Resolver propagates StorageError when FTS is stale."""
        player_path = golden_vault_root / "Characters" / "NPCs" / "01-npc_varos.md"
        original = player_path.read_text(encoding="utf-8")
        modified = original.replace(
            "Городской магистрат Серого Брода.",
            "Городской магистрат Серого Брода. (resolver stale test)",
        )
        player_path.write_text(modified, encoding="utf-8")
        repo.list_entities()
        with pytest.raises(StorageError):
            resolver_with_fts.resolve("S005")


# ═══════════════════════════════════════════════════════════════════════════════
# Resolver composition
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoldenResolverComposition:
    """End-to-end resolver behaviour through the real stack."""

    def test_resolve_exact_id(self, resolver: SearchEntityResolver) -> None:
        """Exact stable ID resolves to Resolved."""
        outcome = resolver.resolve("npc_varos")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_ID

    def test_resolve_exact_name(self, resolver: SearchEntityResolver) -> None:
        """Exact canonical name resolves to Resolved."""
        outcome = resolver.resolve("Магистр Варос")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_NAME

    def test_resolve_unique_alias(self, resolver: SearchEntityResolver) -> None:
        """Unique alias resolves to Resolved."""
        outcome = resolver.resolve("Лорд Варос")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_ALIAS

    def test_resolve_location_name(self, resolver: SearchEntityResolver) -> None:
        """Location canonical name resolves correctly."""
        outcome = resolver.resolve("Серый Брод")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "loc_grayford"
        assert outcome.match_kind == MatchKind.EXACT_NAME

    def test_resolve_quest_name(self, resolver: SearchEntityResolver) -> None:
        """Quest canonical name resolves correctly."""
        outcome = resolver.resolve("Пропавший караван")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "quest_missing_caravan"
        assert outcome.match_kind == MatchKind.EXACT_NAME

    def test_resolve_item_name(self, resolver: SearchEntityResolver) -> None:
        """Item canonical name resolves correctly."""
        outcome = resolver.resolve("Серебряный ключ")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "item_silver_key"
        assert outcome.match_kind == MatchKind.EXACT_NAME

    def test_resolve_with_entity_type_filter(self, resolver: SearchEntityResolver) -> None:
        """Entity-type filter is forwarded through the resolver."""
        outcome = resolver.resolve("Серый Брод", entity_type=EntityType.LOCATION)
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "loc_grayford"

    def test_resolve_wrong_type_does_not_return_wrong_type(
        self, resolver: SearchEntityResolver
    ) -> None:
        """Entity-type filter excludes non-matching types.  Fuzzy fallback
        may still produce candidates of the requested type, so the outcome
        may be Ambiguous — but no LOCATION entity should appear."""
        outcome = resolver.resolve("Серый Брод", entity_type=EntityType.NPC)
        if isinstance(outcome, Ambiguous):
            for c in outcome.candidates:
                assert c.entity_id.startswith("npc_"), (
                    f"Non-NPC in NPC-filtered results: {c.entity_id}"
                )

    def test_cyrillic_preserved_through_resolver(self, resolver: SearchEntityResolver) -> None:
        """Cyrillic names are preserved correctly through the resolver."""
        outcome = resolver.resolve("Магистр Варос")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        outcome = resolver.resolve("Серый Брод")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "loc_grayford"
        outcome = resolver.resolve("Серебряный ключ")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "item_silver_key"
