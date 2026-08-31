"""Tests for Stage 5 retrieval-layer contracts (S5-00).

Covers:
- retrieval types import correctly from the public API
- public exports are intentional
- MatchKind values and ordering semantics
- SearchQuery construction and validation
- SearchHit construction and properties
- ResolutionOutcome types (Resolved, Ambiguous, NotFound)
- ResolutionOutcome is a correct union type
- SearchService protocol is structurally usable
- EntityResolver protocol is structurally usable
- validation rejects malformed values
- Unicode query/name data is supported
- no dependency from domain/storage back into retrieval
- no model/Ollama/tool/session-runtime dependency
- no SQLite/FTS implementation pulled into S5-00
"""

from __future__ import annotations

from typing import cast

import pytest

from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.retrieval import (
    Ambiguous,
    EntityResolver,
    MatchKind,
    NotFound,
    ResolutionOutcome,
    Resolved,
    SearchHit,
    SearchQuery,
    SearchService,
)


class TestImports:
    def test_retrieval_package_importable(self) -> None:
        import dnd_assistant.retrieval  # noqa: F401

    def test_all_types_imported(self) -> None:
        assert all(
            t is not None
            for t in [
                MatchKind,
                SearchQuery,
                SearchHit,
                Resolved,
                Ambiguous,
                NotFound,
                ResolutionOutcome,
                SearchService,
                EntityResolver,
            ]
        )


class TestPublicExports:
    def test_retrieval_all_exports(self) -> None:
        from dnd_assistant.retrieval import __all__ as retrieval_all

        expected = {
            "Ambiguous",
            "EntityResolver",
            "MatchKind",
            "NotFound",
            "Resolved",
            "ResolutionOutcome",
            "SearchHit",
            "SearchQuery",
            "SearchService",
        }
        assert set(retrieval_all) == expected


class TestMatchKind:
    def test_values(self) -> None:
        assert MatchKind.EXACT_ID.value == "exact_id"
        assert MatchKind.EXACT_NAME.value == "exact_name"
        assert MatchKind.EXACT_ALIAS.value == "exact_alias"
        assert MatchKind.FUZZY_NAME.value == "fuzzy_name"
        assert MatchKind.FTS.value == "fts"

    def test_all_members(self) -> None:
        assert set(MatchKind) == {
            MatchKind.EXACT_ID,
            MatchKind.EXACT_NAME,
            MatchKind.EXACT_ALIAS,
            MatchKind.FUZZY_NAME,
            MatchKind.FTS,
        }

    def test_precedence_order(self) -> None:
        assert list(MatchKind) == [
            MatchKind.EXACT_ID,
            MatchKind.EXACT_NAME,
            MatchKind.EXACT_ALIAS,
            MatchKind.FUZZY_NAME,
            MatchKind.FTS,
        ]

    def test_str_representation(self) -> None:
        assert str(MatchKind.EXACT_ID) == "exact_id"


class TestSearchQuery:
    def test_minimal_query(self) -> None:
        q = SearchQuery(text="Varos")
        assert q.text == "Varos"
        assert q.entity_types is None

    def test_with_entity_types(self) -> None:
        q = SearchQuery(text="lighthouse", entity_types={EntityType.LOCATION})
        assert q.entity_types == {EntityType.LOCATION}

    def test_empty_entity_types_set(self) -> None:
        q = SearchQuery(text="test", entity_types=set())
        assert q.entity_types == set()

    def test_unicode_query(self) -> None:
        q = SearchQuery(text="Chyornoe Solntse")
        assert q.text == "Chyornoe Solntse"

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text="test", unknown_field="x")  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "invalid_text",
        [
            "",
            "   ",
            "\t",
            "\n",
            " \n ",
        ],
    )
    def test_empty_or_whitespace_rejected(self, invalid_text: str) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text=invalid_text)

    @pytest.mark.parametrize(
        "invalid_text",
        [
            "test\x00",
            "test\x1f",
            "test\x7f",
            "\x00test",
        ],
    )
    def test_control_characters_rejected(self, invalid_text: str) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text=invalid_text)

    @pytest.mark.parametrize(
        "invalid_value",
        [
            True,
            False,
            42,
            3.14,
            None,
            ["test"],
            {"key": "value"},
        ],
    )
    def test_non_string_rejected(self, invalid_value: object) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchQuery(text=invalid_value)  # type: ignore[arg-type]


class TestSearchHit:
    def test_exact_id_hit(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.EXACT_ID,
        )
        assert hit.entity_id == "npc_varos"
        assert hit.match_kind == MatchKind.EXACT_ID
        assert hit.score is None

    def test_fuzzy_hit_with_score(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.FUZZY_NAME,
            score=85.5,
        )
        assert hit.score == 85.5

    def test_fts_hit_with_negative_score(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.FTS,
            score=-2.5,
        )
        assert hit.score == -2.5

    def test_zero_score_valid(self) -> None:
        hit = SearchHit(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.FTS,
            score=0.0,
        )
        assert hit.score == 0.0

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            SearchHit(
                entity_id=cast(EntityId, "x"),
                match_kind=MatchKind.EXACT_ID,
                unknown=True,  # type: ignore[call-arg]
            )


class TestResolved:
    def test_construction(self) -> None:
        result = Resolved(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.EXACT_NAME,
        )
        assert result.entity_id == "npc_varos"
        assert result.match_kind == MatchKind.EXACT_NAME

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            Resolved(
                entity_id=cast(EntityId, "x"),
                match_kind=MatchKind.EXACT_ID,
                extra=True,  # type: ignore[call-arg]
            )


class TestAmbiguous:
    def test_with_candidates(self) -> None:
        candidates = [
            SearchHit(entity_id=cast(EntityId, "npc_varos"), match_kind=MatchKind.EXACT_ALIAS),
            SearchHit(
                entity_id=cast(EntityId, "npc_varos_junior"), match_kind=MatchKind.EXACT_ALIAS
            ),
        ]
        result = Ambiguous(candidates=candidates)
        assert len(result.candidates) == 2

    def test_empty_candidates(self) -> None:
        result = Ambiguous(candidates=[])
        assert len(result.candidates) == 0

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            Ambiguous(candidates=[], extra=True)  # type: ignore[call-arg]


class TestNotFound:
    def test_construction(self) -> None:
        result = NotFound(query="unknown entity")
        assert result.query == "unknown entity"

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises((ValueError, DndAssistantError)):
            NotFound(query="x", extra=True)  # type: ignore[call-arg]


class TestResolutionOutcome:
    def test_resolved_is_outcome(self) -> None:
        outcome: ResolutionOutcome = Resolved(
            entity_id=cast(EntityId, "npc_varos"),
            match_kind=MatchKind.EXACT_NAME,
        )
        assert isinstance(outcome, Resolved)
        assert not isinstance(outcome, (Ambiguous, NotFound))

    def test_ambiguous_is_outcome(self) -> None:
        outcome: ResolutionOutcome = Ambiguous(candidates=[])
        assert isinstance(outcome, Ambiguous)
        assert not isinstance(outcome, (Resolved, NotFound))

    def test_not_found_is_outcome(self) -> None:
        outcome: ResolutionOutcome = NotFound(query="x")
        assert isinstance(outcome, NotFound)
        assert not isinstance(outcome, (Resolved, Ambiguous))

    def test_outcomes_are_mutually_exclusive(self) -> None:
        resolved = Resolved(entity_id=cast(EntityId, "x"), match_kind=MatchKind.EXACT_ID)
        ambiguous = Ambiguous(candidates=[])
        not_found = NotFound(query="x")
        assert not isinstance(resolved, (Ambiguous, NotFound))
        assert not isinstance(ambiguous, (Resolved, NotFound))
        assert not isinstance(not_found, (Resolved, Ambiguous))

    def test_resolution_outcome_is_union(self) -> None:
        from typing import get_args

        args = get_args(ResolutionOutcome)
        assert Resolved in args
        assert Ambiguous in args
        assert NotFound in args
        assert len(args) == 3


class TestSearchServiceProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(SearchService, "__instancecheck__")

    def test_protocol_has_required_methods(self) -> None:
        methods = {"search", "search_by_type", "get_by_id"}
        protocol_methods = {m for m in dir(SearchService) if not m.startswith("_")}
        assert methods.issubset(protocol_methods)

    def test_concrete_class_can_satisfy_protocol(self) -> None:
        class FakeSearchService:
            def search(self, query: SearchQuery, *, limit: int = 20) -> list[SearchHit]:
                return []

            def search_by_type(self, entity_type: EntityType) -> list[SearchHit]:
                return []

            def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
                return None

        assert isinstance(FakeSearchService(), SearchService)


class TestEntityResolverProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(EntityResolver, "__instancecheck__")

    def test_protocol_has_resolve_method(self) -> None:
        assert hasattr(EntityResolver, "resolve")

    def test_concrete_class_can_satisfy_protocol(self) -> None:
        class FakeResolver:
            def resolve(
                self, reference: str, *, entity_type: EntityType | None = None
            ) -> ResolutionOutcome:
                return NotFound(query=reference)

        assert isinstance(FakeResolver(), EntityResolver)


class TestBoundaries:
    """Verify architectural boundaries are preserved."""

    def test_retrieval_does_not_import_storage(self) -> None:
        import dnd_assistant.retrieval.service
        import dnd_assistant.retrieval.types

        mod_src = (
            dnd_assistant.retrieval.types.__name__ + "\n" + dnd_assistant.retrieval.service.__name__
        )
        assert "storage" not in mod_src

    def test_retrieval_does_not_import_models(self) -> None:
        import dnd_assistant.retrieval.service
        import dnd_assistant.retrieval.types

        mod_src = (
            dnd_assistant.retrieval.types.__name__ + "\n" + dnd_assistant.retrieval.service.__name__
        )
        assert "models" not in mod_src

    def test_retrieval_does_not_import_tools(self) -> None:
        import dnd_assistant.retrieval.service
        import dnd_assistant.retrieval.types

        mod_src = (
            dnd_assistant.retrieval.types.__name__ + "\n" + dnd_assistant.retrieval.service.__name__
        )
        assert "tools" not in mod_src

    def test_retrieval_does_not_import_session_runtime(self) -> None:
        import dnd_assistant.retrieval.service
        import dnd_assistant.retrieval.types

        mod_src = (
            dnd_assistant.retrieval.types.__name__ + "\n" + dnd_assistant.retrieval.service.__name__
        )
        assert "session" not in mod_src

    def test_no_sqlite_import_in_retrieval(self) -> None:
        import dnd_assistant.retrieval.service
        import dnd_assistant.retrieval.types

        mod_src = (
            dnd_assistant.retrieval.types.__name__ + "\n" + dnd_assistant.retrieval.service.__name__
        )
        assert "sqlite" not in mod_src.lower()

    def test_no_rapidfuzz_import_in_retrieval(self) -> None:
        import dnd_assistant.retrieval.service
        import dnd_assistant.retrieval.types

        mod_src = (
            dnd_assistant.retrieval.types.__name__ + "\n" + dnd_assistant.retrieval.service.__name__
        )
        assert "rapidfuzz" not in mod_src.lower()
