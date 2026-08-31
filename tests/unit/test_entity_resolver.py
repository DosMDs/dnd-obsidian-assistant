"""Tests for the deterministic ``SearchEntityResolver`` (S5-04).

Uses a fake ``SearchService`` to avoid requiring a real Vault, SQLite,
or RapidFuzz.  All tests are pure unit tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.errors import StorageError
from dnd_assistant.errors import ValidationError as DndValidationError
from dnd_assistant.retrieval import (
    Ambiguous,
    EntityResolver,
    MatchKind,
    NotFound,
    Resolved,
    SearchEntityResolver,
    SearchHit,
    SearchQuery,
)

# ── Fake SearchService ──────────────────────────────────────────────────────


class FakeSearchService:
    """A fake ``SearchService`` that returns preconfigured results.

    The fake records the last query and limit for assertion in tests.
    """

    def __init__(self, hits: Sequence[SearchHit] | None = None) -> None:
        self.hits = list(hits) if hits is not None else []
        self.last_query: SearchQuery | None = None
        self.last_limit: int | None = None

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        self.last_query = query
        self.last_limit = limit
        return self.hits

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        return None


# ── Test helpers ────────────────────────────────────────────────────────────


def _make_hit(
    entity_id: str,
    match_kind: MatchKind,
    score: float | None = None,
) -> SearchHit:
    return SearchHit(
        entity_id=cast(EntityId, entity_id),
        match_kind=match_kind,
        score=score,
    )


# ── Protocol conformance ────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_is_entity_resolver(self) -> None:
        fake = FakeSearchService()
        resolver = SearchEntityResolver(fake)
        assert isinstance(resolver, EntityResolver)


# ── Resolved ────────────────────────────────────────────────────────────────


class TestResolved:
    def test_single_exact_id_resolved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.EXACT_ID)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("npc_varos")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_ID

    def test_single_exact_name_resolved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.EXACT_NAME)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варос")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_NAME

    def test_single_exact_alias_resolved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.EXACT_ALIAS)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Тёмный Властелин")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "npc_varos"
        assert outcome.match_kind == MatchKind.EXACT_ALIAS

    def test_resolved_entity_id_preserved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("loc_black_tower", MatchKind.EXACT_NAME)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Black Tower")
        assert isinstance(outcome, Resolved)
        assert outcome.entity_id == "loc_black_tower"

    def test_resolved_match_kind_preserved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("item_sword", MatchKind.EXACT_ID)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("item_sword")
        assert isinstance(outcome, Resolved)
        assert outcome.match_kind == MatchKind.EXACT_ID


# -- Ambiguous exact -------------------------------------------------------


class TestAmbiguousExact:
    def test_two_exact_name_candidates(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_varos", MatchKind.EXACT_NAME),
                _make_hit("npc_varos_junior", MatchKind.EXACT_NAME),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варос")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 2

    def test_two_exact_alias_candidates(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_a", MatchKind.EXACT_ALIAS),
                _make_hit("npc_b", MatchKind.EXACT_ALIAS),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Тень")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 2

    def test_multiple_candidates_not_silently_reduced(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_a", MatchKind.EXACT_NAME),
                _make_hit("npc_b", MatchKind.EXACT_NAME),
                _make_hit("npc_c", MatchKind.EXACT_NAME),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Имя")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 3

    def test_deterministic_order_preserved(self) -> None:
        hits = [
            _make_hit("npc_c", MatchKind.EXACT_NAME),
            _make_hit("npc_a", MatchKind.EXACT_NAME),
            _make_hit("npc_b", MatchKind.EXACT_NAME),
        ]
        fake = FakeSearchService(hits=hits)
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Имя")
        assert isinstance(outcome, Ambiguous)
        assert [c.entity_id for c in outcome.candidates] == ["npc_c", "npc_a", "npc_b"]


# -- Fuzzy -----------------------------------------------------------------


class TestFuzzy:
    def test_single_fuzzy_candidate_ambiguous(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.FUZZY_NAME, score=85.5)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варосc")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 1

    def test_high_fuzzy_score_still_ambiguous(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.FUZZY_NAME, score=99.9)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варос")
        assert isinstance(outcome, Ambiguous)

    def test_multiple_fuzzy_candidates_ambiguous(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_varos", MatchKind.FUZZY_NAME, score=85.5),
                _make_hit("npc_varos_junior", MatchKind.FUZZY_NAME, score=72.0),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варосc")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 2

    def test_fuzzy_scores_preserved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.FUZZY_NAME, score=85.5)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варосc")
        assert isinstance(outcome, Ambiguous)
        assert outcome.candidates[0].score == 85.5

    def test_no_numeric_fuzzy_threshold(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.FUZZY_NAME, score=99.9)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Варос")
        assert isinstance(outcome, Ambiguous)


# -- FTS -------------------------------------------------------------------


class TestFts:
    def test_single_fts_candidate_ambiguous(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.FTS, score=-2.5)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Varos")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 1

    def test_multiple_fts_candidates_ambiguous(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_varos", MatchKind.FTS, score=-2.5),
                _make_hit("loc_varos_keep", MatchKind.FTS, score=-1.0),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("varos")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 2

    def test_fts_score_preserved(self) -> None:
        fake = FakeSearchService(hits=[_make_hit("npc_varos", MatchKind.FTS, score=-2.5)])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Varos")
        assert isinstance(outcome, Ambiguous)
        assert outcome.candidates[0].score == -2.5


# -- NotFound ---------------------------------------------------------------


class TestNotFound:
    def test_zero_candidates_not_found(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("NonExistentEntity")
        assert isinstance(outcome, NotFound)
        assert outcome.query == "NonExistentEntity"

    def test_original_query_preserved(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("  Варос  ")
        assert isinstance(outcome, NotFound)
        assert outcome.query == "  Варос  "


# -- Entity type forwarding -------------------------------------------------


class TestEntityTypeForwarding:
    def test_entity_type_none(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        resolver.resolve("test", entity_type=None)
        assert fake.last_query is not None
        assert fake.last_query.entity_types is None

    def test_entity_type_npc(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        resolver.resolve("test", entity_type=EntityType.NPC)
        assert fake.last_query is not None
        assert fake.last_query.entity_types == {EntityType.NPC}

    def test_entity_type_location(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        resolver.resolve("test", entity_type=EntityType.LOCATION)
        assert fake.last_query is not None
        assert fake.last_query.entity_types == {EntityType.LOCATION}

    def test_entity_type_quest(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        resolver.resolve("test", entity_type=EntityType.QUEST)
        assert fake.last_query is not None
        assert fake.last_query.entity_types == {EntityType.QUEST}

    def test_entity_type_item(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        resolver.resolve("test", entity_type=EntityType.ITEM)
        assert fake.last_query is not None
        assert fake.last_query.entity_types == {EntityType.ITEM}


# -- Validation -------------------------------------------------------------


class TestValidation:
    def test_empty_string_rejected(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError):
            resolver.resolve("")

    def test_whitespace_only_rejected(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError):
            resolver.resolve("   ")

    def test_newline_rejected(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError):
            resolver.resolve("\n")

    def test_control_characters_rejected(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError):
            resolver.resolve("test\x00")

    def test_non_printable_rejected(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError):
            resolver.resolve("test\x1f")

    def test_invalid_reference_does_not_call_search(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError):
            resolver.resolve("")
        assert fake.last_query is None

    @pytest.mark.parametrize(
        "invalid_ref",
        [
            "",
            "   ",
            "\n",
            "test\x00",
            "test\x1f",
        ],
    )
    def test_validation_cause_is_pydantic_validation_error(self, invalid_ref: str) -> None:
        """Prove that invalid input raises DndValidationError whose
        __cause__ is the original PydanticValidationError."""
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        with pytest.raises(DndValidationError) as exc_info:
            resolver.resolve(invalid_ref)
        assert isinstance(exc_info.value.__cause__, PydanticValidationError)
        # SearchService.search must not be called for invalid input
        assert fake.last_query is None


# -- Error propagation ------------------------------------------------------


class TestErrorPropagation:
    def test_storage_error_propagates(self) -> None:
        class BrokenSearchService:
            def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
                raise StorageError("index corrupted")

            def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
                return None

        resolver = SearchEntityResolver(BrokenSearchService())
        with pytest.raises(StorageError, match="index corrupted"):
            resolver.resolve("test")

    def test_validation_error_from_search_propagates(self) -> None:
        class StrictSearchService:
            def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
                raise DndValidationError("query too long")

            def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
                return None

        resolver = SearchEntityResolver(StrictSearchService())
        with pytest.raises(DndValidationError, match="query too long"):
            resolver.resolve("test")


# -- Safety -----------------------------------------------------------------


class TestSafety:
    def test_ambiguous_does_not_raise_ambiguous_entity_error(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_a", MatchKind.EXACT_NAME),
                _make_hit("npc_b", MatchKind.EXACT_NAME),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Имя")
        assert isinstance(outcome, Ambiguous)

    def test_no_direct_vault_storage_dependency(self) -> None:
        import ast
        import importlib

        mod = importlib.import_module("dnd_assistant.retrieval.resolver")
        assert mod.__file__ is not None
        with open(mod.__file__, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "storage" in alias.name:
                        pytest.fail(f"resolver.py imports storage: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and "storage" in node.module:
                    pytest.fail(f"resolver.py imports storage: {node.module}")
                for alias in node.names:
                    if "storage" in alias.name:
                        pytest.fail(f"resolver.py imports storage: {alias.name}")


# -- Mixed/malformed search results -----------------------------------------


class TestMixedCandidates:
    def test_mixed_match_kinds_ambiguous(self) -> None:
        fake = FakeSearchService(
            hits=[
                _make_hit("npc_a", MatchKind.EXACT_NAME),
                _make_hit("npc_b", MatchKind.FUZZY_NAME, score=80.0),
            ]
        )
        resolver = SearchEntityResolver(fake)
        outcome = resolver.resolve("Name")
        assert isinstance(outcome, Ambiguous)
        assert len(outcome.candidates) == 2


# -- Candidate limit --------------------------------------------------------


class TestCandidateLimit:
    def test_internal_limit_greater_than_one(self) -> None:
        fake = FakeSearchService(hits=[])
        resolver = SearchEntityResolver(fake)
        resolver.resolve("test")
        assert fake.last_limit is not None
        assert fake.last_limit >= 2
