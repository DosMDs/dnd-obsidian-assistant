"""Tests for S5-02 fuzzy name retrieval with entity-type filtering and ranking.

Covers:
- basic fuzzy match on canonical name
- RapidFuzz score correctness
- deterministic ranking (score desc, EntityId asc)
- tie-breaking on equal scores
- exact-ID precedence over fuzzy
- exact-name precedence over fuzzy
- exact-alias precedence over fuzzy
- player/DM/system visibility filtering before fuzzy scoring
- entity-type filtering (None, empty, matching, non-matching)
- limit applied after ranking
- Unicode/casefold Cyrillic fuzzy examples
- non-fuzzy EntityId (typo in ID does not fuzzy-match)
- no fuzzy alias matching
- zero-score candidates omitted
- low positive score preserved (no confidence threshold)
- repository error propagation
"""

from __future__ import annotations

from datetime import UTC
from typing import cast

import pytest
from rapidfuzz import fuzz

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Visibility
from dnd_assistant.errors import StorageError
from dnd_assistant.retrieval import (
    MatchKind,
    SearchQuery,
    VaultSearchService,
)
from dnd_assistant.storage.types import VaultDocument, VaultRepository

# ── Fake repository (reused from test_exact_search.py pattern) ───────────────


def _make_entity(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
) -> Entity:
    from datetime import datetime

    return Entity(
        id=cast(EntityId, entity_id),
        type=entity_type,
        name=name,
        status="active",
        visibility=visibility,
        knowledge_status="confirmed",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        revision=1,
    )


def _make_doc(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
    aliases: list[str] | None = None,
) -> VaultDocument:
    extra: dict[str, object] = {}
    if aliases is not None:
        extra["aliases"] = aliases
    return VaultDocument(
        entity=_make_entity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            visibility=visibility,
        ),
        extra_frontmatter=extra,
        body="",
    )


class FakeRepository:
    """Minimal fake VaultRepository for unit tests."""

    def __init__(self, documents: list[VaultDocument] | None = None) -> None:
        self._docs: dict[str, VaultDocument] = {}
        if documents:
            for doc in documents:
                self._docs[doc.entity.id] = doc

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        from dnd_assistant.errors import NotFoundError

        try:
            return self._docs[str(entity_id)]
        except KeyError:
            raise NotFoundError(f"Entity not found: {entity_id}") from None

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        if entity_type is None:
            return list(self._docs.values())
        return [d for d in self._docs.values() if d.entity.type == entity_type]


# ── Normalisation helper ─────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Match the normalisation used in search.py."""
    import unicodedata

    return unicodedata.normalize("NFC", text.strip()).casefold()


# ── Basic fuzzy match ────────────────────────────────────────────────────────


class TestBasicFuzzyMatch:
    def test_fuzzy_name_match(self) -> None:
        """'Магистр Варо' fuzzy-matches 'Магистр Варос'."""
        doc = _make_doc("npc_varos", name="Магистр Варос")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.FUZZY_NAME
        assert results[0].score is not None
        assert results[0].score > 0.0

    def test_fuzzy_name_match_cyrillic(self) -> None:
        doc = _make_doc("npc_varos", name="Варос")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Варо"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.FUZZY_NAME
        assert results[0].score is not None and results[0].score > 0.0


# ── Score correctness ────────────────────────────────────────────────────────


class TestScoreCorrectness:
    def test_score_matches_fuzz_ratio(self) -> None:
        """SearchHit.score must equal fuzz.ratio(normalized_query, normalized_name)."""
        query = "Магистр Варо"
        name = "Магистр Варос"
        doc = _make_doc("npc_varos", name=name)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text=query))
        assert len(results) == 1
        expected = fuzz.ratio(_normalize(query), _normalize(name))
        assert results[0].score == pytest.approx(expected)

    def test_score_is_float(self) -> None:
        doc = _make_doc("npc_varos", name="Варос")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Варо"))
        assert len(results) == 1
        assert isinstance(results[0].score, float)


# ── Ranking ──────────────────────────────────────────────────────────────────


class TestRanking:
    def test_higher_score_first(self) -> None:
        docs = [
            _make_doc("npc_c", name="Советник Магистр"),
            _make_doc("npc_b", name="Магистр Варос"),
            _make_doc("npc_a", name="Магистр"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        # Use a partial query so no exact name matches, forcing fuzzy tier
        results = svc.search(SearchQuery(text="Маги"))
        assert len(results) >= 2
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_tie_break_by_entity_id(self) -> None:
        """Equal scores must be ordered by EntityId ascending."""
        docs = [
            _make_doc("npc_z", name="Варос"),
            _make_doc("npc_a", name="Варос"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Варо"))
        assert len(results) == 2
        assert results[0].entity_id == "npc_a"
        assert results[1].entity_id == "npc_z"
        assert results[0].score == results[1].score


# ── Exact-tier precedence ────────────────────────────────────────────────────


class TestExactPrecedence:
    def test_exact_id_suppresses_fuzzy(self) -> None:
        doc_id = _make_doc("npc_varos", name="Советник")
        doc_fuzzy = _make_doc("npc_other", name="npc_varos")
        repo: VaultRepository = FakeRepository([doc_id, doc_fuzzy])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ID

    def test_exact_name_suppresses_fuzzy(self) -> None:
        doc_name = _make_doc("npc_varos", name="Магистр Варос")
        doc_fuzzy = _make_doc("npc_other", name="Магистр")
        repo: VaultRepository = FakeRepository([doc_name, doc_fuzzy])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варос"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_alias_suppresses_fuzzy(self) -> None:
        doc_alias = _make_doc("npc_varos", name="Varos", aliases=["Магистр Варос"])
        doc_fuzzy = _make_doc("npc_other", name="Магистр")
        repo: VaultRepository = FakeRepository([doc_alias, doc_fuzzy])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варос"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ALIAS

    def test_exact_id_suppresses_fuzzy_high_score(self) -> None:
        doc_id = _make_doc("npc_varos", name="Unrelated Name")
        doc_high_fuzzy = _make_doc("npc_other", name="npc_varos")
        repo: VaultRepository = FakeRepository([doc_id, doc_high_fuzzy])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ID

    def test_exact_name_suppresses_fuzzy_high_score(self) -> None:
        doc_name = _make_doc("npc_varos", name="Магистр Варос")
        doc_fuzzy = _make_doc("npc_other", name="Магистр Варос Почти")
        repo: VaultRepository = FakeRepository([doc_name, doc_fuzzy])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варос"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_alias_suppresses_fuzzy_high_score(self) -> None:
        doc_alias = _make_doc("npc_varos", name="Varos", aliases=["Магистр Варос"])
        doc_fuzzy = _make_doc("npc_other", name="Магистр Варос Почти")
        repo: VaultRepository = FakeRepository([doc_alias, doc_fuzzy])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варос"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ALIAS


# ── Visibility filtering ─────────────────────────────────────────────────────


class TestVisibility:
    def test_player_visible_fuzzy(self) -> None:
        doc = _make_doc("npc_varos", name="Магистр Варос", visibility=Visibility.PLAYER)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо"))
        assert len(results) == 1

    def test_dm_hidden_not_in_fuzzy(self) -> None:
        doc = _make_doc("npc_secret", name="Магистр Варос", visibility=Visibility.DM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо"))
        assert len(results) == 0

    def test_system_hidden_not_in_fuzzy(self) -> None:
        doc = _make_doc("sys_meta", name="Магистр Варос", visibility=Visibility.SYSTEM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо"))
        assert len(results) == 0

    def test_hidden_high_score_does_not_affect_visible_ranking(self) -> None:
        hidden = _make_doc("npc_secret", name="Магистр Варос Тайный", visibility=Visibility.DM)
        visible = _make_doc("npc_visible", name="Магистр", visibility=Visibility.PLAYER)
        repo: VaultRepository = FakeRepository([hidden, visible])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_visible"


# ── Entity-type filtering ────────────────────────────────────────────────────


class TestEntityTypeFilter:
    def test_no_filter(self) -> None:
        doc = _make_doc("npc_varos", name="Магистр Варос", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо"))
        assert len(results) == 1

    def test_empty_set_is_no_filter(self) -> None:
        doc = _make_doc("npc_varos", name="Магистр Варос", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо", entity_types=set()))
        assert len(results) == 1

    def test_matching_type_filter(self) -> None:
        doc = _make_doc("npc_varos", name="Магистр Варос", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо", entity_types={EntityType.NPC}))
        assert len(results) == 1

    def test_non_matching_type_filter(self) -> None:
        doc = _make_doc("npc_varos", name="Магистр Варос", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо", entity_types={EntityType.LOCATION}))
        assert len(results) == 0

    def test_filtered_out_high_score_does_not_appear(self) -> None:
        npc = _make_doc("npc_varos", name="Магистр Варос", entity_type=EntityType.NPC)
        loc = _make_doc("loc_tower", name="Магистр Варос Башня", entity_type=EntityType.LOCATION)
        repo: VaultRepository = FakeRepository([npc, loc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо", entity_types={EntityType.LOCATION}))
        assert len(results) == 1
        assert results[0].entity_id == "loc_tower"


# ── Limit ────────────────────────────────────────────────────────────────────


class TestLimit:
    def test_limit_applied_after_ranking(self) -> None:
        docs = [_make_doc(f"npc_{i}", name="Разные Имена") for i in range(10)]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Разные"), limit=3)
        assert len(results) == 3

    def test_limit_does_not_affect_ranking_order(self) -> None:
        docs = [
            _make_doc("npc_c", name="Советник Магистр"),
            _make_doc("npc_b", name="Магистр Варос"),
            _make_doc("npc_a", name="Магистр"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        # Use a partial query so no exact name matches, forcing fuzzy tier
        results_all = svc.search(SearchQuery(text="Маги"), limit=10)
        results_limited = svc.search(SearchQuery(text="Маги"), limit=2)
        assert len(results_limited) == 2
        assert results_limited[0].entity_id == results_all[0].entity_id
        assert results_limited[1].entity_id == results_all[1].entity_id


# ── Unicode and casefold ─────────────────────────────────────────────────────


class TestUnicode:
    def test_cyrillic_fuzzy(self) -> None:
        doc = _make_doc("npc_magistr", name="Магистр")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="магистр"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_cyrillic_fuzzy_partial(self) -> None:
        doc = _make_doc("npc_magistr", name="Магистр")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Маги"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.FUZZY_NAME
        assert results[0].score is not None and results[0].score > 0.0

    def test_casefold_affects_fuzzy_score(self) -> None:
        doc = _make_doc("npc_magistr", name="Магистр")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results_upper = svc.search(SearchQuery(text="МАГИСТР"))
        results_lower = svc.search(SearchQuery(text="магистр"))
        assert len(results_upper) == 1
        assert len(results_lower) == 1
        assert results_upper[0].match_kind == MatchKind.EXACT_NAME
        assert results_lower[0].match_kind == MatchKind.EXACT_NAME


# ── Non-fuzzy EntityId ───────────────────────────────────────────────────────


class TestNonFuzzyEntityId:
    def test_typo_in_entity_id_does_not_fuzzy_match(self) -> None:
        """A typo in EntityId must not fuzzy-match the stable ID."""
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varo"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.FUZZY_NAME
        assert results[0].entity_id == "npc_varos"


# ── No fuzzy aliases ─────────────────────────────────────────────────────────


class TestNoFuzzyAlias:
    def test_near_match_to_alias_not_fuzzy(self) -> None:
        """A near-match to an alias must not produce a fuzzy result
        when the canonical name has zero similarity."""
        doc = _make_doc("npc_varos", name="Varos", aliases=["Магистр Варос"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Магистр Варо"))
        assert len(results) == 0


# ── Zero score ───────────────────────────────────────────────────────────────


class TestZeroScore:
    def test_completely_different_name_omitted(self) -> None:
        """A canonical name with fuzz.ratio(...) == 0.0 must be omitted."""
        doc = _make_doc("npc_varos", name="xxxxx")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        # Completely unrelated ASCII query with no character overlap
        results = svc.search(SearchQuery(text="zzzzz"))
        assert len(results) == 0


# ── Low positive score ───────────────────────────────────────────────────────


class TestLowPositiveScore:
    def test_low_positive_score_preserved(self) -> None:
        """A low but positive score must remain a candidate.
        This proves S5-02 does not prematurely introduce a resolver
        confidence threshold."""
        doc = _make_doc("npc_varos", name="Варос")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="В"))
        assert len(results) == 1
        assert results[0].score is not None
        assert 0.0 < results[0].score < 100.0


# ── Repository errors ────────────────────────────────────────────────────────


class TestRepositoryErrors:
    def test_storage_error_propagates(self) -> None:
        class BrokenRepo:
            def get_entity(self, entity_id: EntityId) -> VaultDocument:
                raise StorageError("Disk failure")

            def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
                raise StorageError("List failure")

        repo: VaultRepository = BrokenRepo()  # type: ignore[type-abstract]
        svc = VaultSearchService(repository=repo)
        with pytest.raises(StorageError, match="List failure"):
            svc.search(SearchQuery(text="test"))
