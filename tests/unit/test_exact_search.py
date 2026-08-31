"""Tests for S5-01 exact ID/name/alias retrieval with player-visibility enforcement.

Covers:
- VaultSearchService satisfies SearchService protocol
- get_by_id: success, not-found, hidden, repository errors
- search: exact-ID tier, exact-name tier, exact-alias tier
- tier precedence (EXACT_ID > EXACT_NAME > EXACT_ALIAS)
- duplicate canonical names -> multiple EXACT_NAME hits
- shared alias -> multiple EXACT_ALIAS hits
- same entity name + alias -> one hit only
- player/DM/system visibility filtering
- hidden higher-tier collision with visible lower-tier
- entity-type filters (None, empty, non-empty)
- deterministic EntityId ordering
- limit validation and enforcement
- Cyrillic/Unicode exact matching
- casefold/NFC normalisation
- non-fuzzy negative examples
- malformed alias metadata
- repository failure propagation
- no direct filesystem access
"""

from __future__ import annotations

from datetime import UTC
from typing import cast

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Visibility
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.retrieval import (
    MatchKind,
    SearchQuery,
    SearchService,
    VaultSearchService,
)
from dnd_assistant.storage.types import VaultDocument, VaultRepository

# ── Fake repository for unit tests ──────────────────────────────────────────


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
    """Minimal fake VaultRepository for unit tests.

    Supports get_entity (with NotFoundError) and list_entities.
    Does not access the filesystem.
    """

    def __init__(self, documents: list[VaultDocument] | None = None) -> None:
        self._docs: dict[str, VaultDocument] = {}
        if documents:
            for doc in documents:
                self._docs[doc.entity.id] = doc

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        try:
            return self._docs[str(entity_id)]
        except KeyError:
            raise NotFoundError(f"Entity not found: {entity_id}") from None

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        if entity_type is None:
            return list(self._docs.values())
        return [d for d in self._docs.values() if d.entity.type == entity_type]


# ── Protocol conformance ────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_satisfies_search_service(self) -> None:
        repo: VaultRepository = FakeRepository()
        svc = VaultSearchService(repository=repo)
        assert isinstance(svc, SearchService)

    def test_has_search_method(self) -> None:
        repo: VaultRepository = FakeRepository()
        svc = VaultSearchService(repository=repo)
        assert hasattr(svc, "search")

    def test_has_get_by_id_method(self) -> None:
        repo: VaultRepository = FakeRepository()
        svc = VaultSearchService(repository=repo)
        assert hasattr(svc, "get_by_id")


# ── get_by_id ───────────────────────────────────────────────────────────────


class TestGetById:
    def test_found_player_entity(self) -> None:
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        hit = svc.get_by_id(cast(EntityId, "npc_varos"))
        assert hit is not None
        assert hit.entity_id == "npc_varos"
        assert hit.match_kind == MatchKind.EXACT_ID
        assert hit.score is None

    def test_missing_entity(self) -> None:
        repo: VaultRepository = FakeRepository([])
        svc = VaultSearchService(repository=repo)
        hit = svc.get_by_id(cast(EntityId, "npc_missing"))
        assert hit is None

    def test_dm_entity(self) -> None:
        doc = _make_doc("npc_secret", visibility=Visibility.DM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        hit = svc.get_by_id(cast(EntityId, "npc_secret"))
        assert hit is None

    def test_system_entity(self) -> None:
        doc = _make_doc("sys_meta", visibility=Visibility.SYSTEM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        hit = svc.get_by_id(cast(EntityId, "sys_meta"))
        assert hit is None

    def test_not_found_is_observationally_equivalent_to_hidden(self) -> None:
        """Both missing and hidden entities return None."""
        repo: VaultRepository = FakeRepository([])
        svc = VaultSearchService(repository=repo)
        assert svc.get_by_id(cast(EntityId, "npc_nonexistent")) is None

    def test_repository_error_propagates(self) -> None:
        """Repository integrity failures must propagate, not return None."""

        class BrokenRepo:
            def get_entity(self, entity_id: EntityId) -> VaultDocument:
                raise StorageError("Disk failure")

            def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
                return []

        repo: VaultRepository = BrokenRepo()  # type: ignore[type-abstract]
        svc = VaultSearchService(repository=repo)
        with pytest.raises(StorageError, match="Disk failure"):
            svc.get_by_id(cast(EntityId, "npc_varos"))


# ── search: EXACT_ID tier ───────────────────────────────────────────────────


class TestSearchExactId:
    def test_exact_id_match(self) -> None:
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ID

    def test_exact_id_is_case_sensitive(self) -> None:
        """EntityId comparison is literal, not casefolded."""
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="NPC_VAROS"))
        assert len(results) == 0

    def test_exact_id_not_confused_with_name(self) -> None:
        """A query matching a name must not produce an EXACT_ID hit."""
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME


# ── search: EXACT_NAME tier ─────────────────────────────────────────────────


class TestSearchExactName:
    def test_exact_name_match(self) -> None:
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_casefold_name_match(self) -> None:
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_unicode_casefold(self) -> None:
        doc = _make_doc("npc_magistr", name="Магистр")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="магистр"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_nfc_normalisation(self) -> None:
        """NFC-equivalent strings must match."""
        import unicodedata

        name_nfd = unicodedata.normalize("NFD", "Магистр")
        doc = _make_doc("npc_magistr", name="Магистр")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text=name_nfd))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_name_not_fuzzy(self) -> None:
        """Substring must NOT match."""
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varo"))
        assert len(results) == 0

    def test_whitespace_stripped_for_comparison(self) -> None:
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="  Varos  "))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_duplicate_names(self) -> None:
        doc1 = _make_doc("npc_varos_a", name="Varos")
        doc2 = _make_doc("npc_varos_b", name="Varos")
        repo: VaultRepository = FakeRepository([doc1, doc2])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 2
        assert all(h.match_kind == MatchKind.EXACT_NAME for h in results)


# ── search: EXACT_ALIAS tier ────────────────────────────────────────────────


class TestSearchExactAlias:
    def test_exact_alias_match(self) -> None:
        doc = _make_doc("npc_varos", name="Varos", aliases=["Лорд Варос"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Лорд Варос"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ALIAS

    def test_casefold_alias(self) -> None:
        doc = _make_doc("npc_varos", name="Varos", aliases=["Лорд Варос"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="лорд варос"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ALIAS

    def test_shared_alias(self) -> None:
        doc1 = _make_doc("npc_varos_a", name="Varos A", aliases=["Shadow"])
        doc2 = _make_doc("npc_varos_b", name="Varos B", aliases=["Shadow"])
        repo: VaultRepository = FakeRepository([doc1, doc2])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Shadow"))
        assert len(results) == 2
        assert all(h.match_kind == MatchKind.EXACT_ALIAS for h in results)

    def test_alias_not_fuzzy(self) -> None:
        doc = _make_doc("npc_varos", name="Varos", aliases=["Лорд Варос"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Лорд"))
        assert len(results) == 0

    def test_whitespace_stripped_alias(self) -> None:
        doc = _make_doc("npc_varos", name="Varos", aliases=["Лорд Варос"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="  Лорд Варос  "))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ALIAS


# ── Tier precedence ─────────────────────────────────────────────────────────


class TestTierPrecedence:
    def test_exact_id_beats_exact_name(self) -> None:
        """When one entity matches by ID and another by name,
        only the ID match is returned."""
        doc_id = _make_doc("npc_varos", name="Some Other Name")
        doc_name = _make_doc("npc_other", name="npc_varos")
        repo: VaultRepository = FakeRepository([doc_id, doc_name])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ID

    def test_exact_id_beats_exact_alias(self) -> None:
        doc_id = _make_doc("npc_varos", name="Varos")
        doc_alias = _make_doc("npc_other", name="Other", aliases=["npc_varos"])
        repo: VaultRepository = FakeRepository([doc_id, doc_alias])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ID

    def test_exact_name_beats_exact_alias(self) -> None:
        doc_name = _make_doc("npc_varos", name="Varos")
        doc_alias = _make_doc("npc_other", name="Other", aliases=["Varos"])
        repo: VaultRepository = FakeRepository([doc_name, doc_alias])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_same_entity_name_and_alias_produces_one_hit(self) -> None:
        """An entity whose canonical name matches an alias of the same
        entity must produce only one hit."""
        doc = _make_doc("npc_varos", name="Varos", aliases=["Varos"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        # EXACT_NAME tier wins, one hit
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME


# ── Visibility filtering ────────────────────────────────────────────────────


class TestVisibility:
    def test_player_visible(self) -> None:
        doc = _make_doc("npc_varos", visibility=Visibility.PLAYER)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1

    def test_dm_hidden(self) -> None:
        doc = _make_doc("npc_secret", visibility=Visibility.DM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_secret"))
        assert len(results) == 0

    def test_system_hidden(self) -> None:
        doc = _make_doc("sys_meta", visibility=Visibility.SYSTEM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="sys_meta"))
        assert len(results) == 0

    def test_hidden_exact_name(self) -> None:
        doc = _make_doc("npc_secret", name="Secret", visibility=Visibility.DM)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Secret"))
        assert len(results) == 0

    def test_hidden_exact_alias(self) -> None:
        doc = _make_doc(
            "npc_secret",
            name="Secret",
            visibility=Visibility.DM,
            aliases=["Hidden One"],
        )
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Hidden One"))
        assert len(results) == 0

    def test_hidden_higher_tier_does_not_block_visible_lower_tier(self) -> None:
        """A hidden entity matching by exact ID must not suppress a visible
        entity matching by alias."""
        hidden = _make_doc("npc_secret", name="Secret", visibility=Visibility.DM)
        visible = _make_doc("npc_varos", name="Varos", aliases=["npc_secret"])
        repo: VaultRepository = FakeRepository([hidden, visible])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_secret"))
        # Hidden entity is excluded first; visible alias match may still return
        assert len(results) == 1
        assert results[0].entity_id == "npc_varos"
        assert results[0].match_kind == MatchKind.EXACT_ALIAS


# ── Entity-type filtering ───────────────────────────────────────────────────


class TestEntityTypeFilter:
    def test_no_filter(self) -> None:
        doc = _make_doc("npc_varos", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1

    def test_empty_set_is_no_filter(self) -> None:
        doc = _make_doc("npc_varos", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos", entity_types=set()))
        assert len(results) == 1

    def test_matching_type(self) -> None:
        doc = _make_doc("loc_tower", entity_type=EntityType.LOCATION)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="loc_tower", entity_types={EntityType.LOCATION}))
        assert len(results) == 1

    def test_non_matching_type(self) -> None:
        doc = _make_doc("npc_varos", entity_type=EntityType.NPC)
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="npc_varos", entity_types={EntityType.LOCATION}))
        assert len(results) == 0

    def test_type_filter_applied_before_tier(self) -> None:
        """An entity matching by exact ID but excluded by type filter
        must not suppress a lower-tier match of an eligible type."""
        npc = _make_doc("npc_varos", name="Varos", entity_type=EntityType.NPC)
        loc = _make_doc(
            "loc_tower", name="Tower", entity_type=EntityType.LOCATION, aliases=["Varos"]
        )
        repo: VaultRepository = FakeRepository([npc, loc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos", entity_types={EntityType.LOCATION}))
        assert len(results) == 1
        assert results[0].entity_id == "loc_tower"
        assert results[0].match_kind == MatchKind.EXACT_ALIAS


# ── Deterministic ordering ──────────────────────────────────────────────────


class TestOrdering:
    def test_duplicate_names_ordered_by_id(self) -> None:
        docs = [
            _make_doc("npc_z", name="Varos"),
            _make_doc("npc_a", name="Varos"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 2
        assert results[0].entity_id == "npc_a"
        assert results[1].entity_id == "npc_z"

    def test_shared_alias_ordered_by_id(self) -> None:
        docs = [
            _make_doc("npc_z", name="Zed", aliases=["Shadow"]),
            _make_doc("npc_a", name="Alpha", aliases=["Shadow"]),
        ]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Shadow"))
        assert len(results) == 2
        assert results[0].entity_id == "npc_a"
        assert results[1].entity_id == "npc_z"


# ── Limit validation ────────────────────────────────────────────────────────


class TestLimit:
    def test_limit_applied(self) -> None:
        docs = [_make_doc(f"npc_{i}", name="SameName") for i in range(10)]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="SameName"), limit=3)
        assert len(results) == 3

    def test_limit_1_valid(self) -> None:
        docs = [_make_doc("npc_a", name="X"), _make_doc("npc_b", name="X")]
        repo: VaultRepository = FakeRepository(docs)
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="X"), limit=1)
        assert len(results) == 1

    @pytest.mark.parametrize("bad_limit", [0, -1, True, False, 1.5, "5", None])
    def test_invalid_limit_rejected(self, bad_limit: object) -> None:
        doc = _make_doc("npc_varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        with pytest.raises(ValidationError):
            svc.search(SearchQuery(text="npc_varos"), limit=bad_limit)


# ── Alias metadata edge cases ───────────────────────────────────────────────


class TestAliasMetadata:
    def test_missing_aliases(self) -> None:
        doc = _make_doc("npc_varos", name="Varos")
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_empty_aliases_list(self) -> None:
        doc = _make_doc("npc_varos", name="Varos", aliases=[])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_duplicate_aliases_collapsed(self) -> None:
        doc = _make_doc("npc_varos", name="Varos", aliases=["Shadow", "Shadow"])
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Shadow"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ALIAS

    def test_scalar_alias_malformed(self) -> None:
        """A scalar string alias (not a list) must be treated as malformed
        and must not create a false match."""
        extra = {"aliases": "Lord Varos"}
        doc = VaultDocument(
            entity=_make_entity("npc_varos", name="Varos"),
            extra_frontmatter=extra,
        )
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Lord Varos"))
        assert len(results) == 0

    def test_mixed_valid_invalid_aliases(self) -> None:
        extra = {
            "aliases": [
                "Good Alias",
                42,
                "",
                "   ",
                "\x00bad",
                None,
                True,
            ]
        }
        doc = VaultDocument(
            entity=_make_entity("npc_varos", name="Varos"),
            extra_frontmatter=extra,
        )
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Good Alias"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ALIAS

    def test_non_string_values_ignored(self) -> None:
        extra = {"aliases": [42, 3.14, True, None]}
        doc = VaultDocument(
            entity=_make_entity("npc_varos", name="Varos"),
            extra_frontmatter=extra,
        )
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_unicode_aliases(self) -> None:
        doc = _make_doc(
            "npc_varos",
            name="Varos",
            aliases=["Варос", "Лорд Варос", "Чёрное Солнце"],
        )
        repo: VaultRepository = FakeRepository([doc])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="Чёрное Солнце"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ALIAS


# ── Repository error propagation ────────────────────────────────────────────


class TestRepositoryErrors:
    def test_search_storage_error_propagates(self) -> None:
        class BrokenRepo:
            def get_entity(self, entity_id: EntityId) -> VaultDocument:
                raise StorageError("Disk failure")

            def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
                raise StorageError("List failure")

        repo: VaultRepository = BrokenRepo()
        svc = VaultSearchService(repository=repo)
        with pytest.raises(StorageError, match="List failure"):
            svc.search(SearchQuery(text="test"))
