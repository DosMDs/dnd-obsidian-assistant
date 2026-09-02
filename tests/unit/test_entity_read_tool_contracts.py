"""Tests for entity read tool contracts: DTO validation and registration metadata.

Covers:
- Registration metadata (names, permission, side effects, session modes)
- SearchEntitiesInput validation
- SearchEntitiesOutput validation
- GetEntityInput validation
- GetEntityOutput validation
- Registration API
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Revision, Visibility
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.retrieval.types import MatchKind
from dnd_assistant.tools.entity_reads import (
    EntitySearchResult,
    GetEntityInput,
    GetEntityOutput,
    SearchEntitiesInput,
    SearchEntitiesOutput,
    register_entity_read_tools,
)
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    Permission,
    SessionMode,
)

# ── Shared test data ──────────────────────────────────────────────────────

_NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _make_entity(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
) -> Entity:
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status="active",
        visibility=visibility,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=_NOW,
        updated_at=_NOW,
        revision=Revision(1),
    )


# ── Fake implementations for registration tests ───────────────────────────


class FakeSearchService:
    """Minimal fake implementing SearchService protocol for registration tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, object] = {}

    def set_get_by_id(self, entity_id: str, hit: object) -> None:
        self._by_id[entity_id] = hit

    def search(self, query: object, *, limit: int = 20) -> list[object]:
        return []

    def get_by_id(self, entity_id: str) -> object:
        return self._by_id.get(entity_id)


class FakeRepository:
    """Minimal fake implementing VaultRepository protocol for registration tests."""

    def __init__(self) -> None:
        self._entities: dict[str, object] = {}

    def get_entity(self, entity_id: str) -> object:
        return self._entities.get(entity_id)

    def list_entities(self, entity_type: object = None) -> list[object]:
        return []


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(
    registry: ToolRegistry,
) -> ToolRegistry:
    register_entity_read_tools(
        registry,
        search_service=FakeSearchService(),
        repository=FakeRepository(),
    )
    return registry


# ═══════════════════════════════════════════════════════════════════════════
# Registration metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationMetadata:
    def test_search_entities_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("search_entities")
        assert definition.name == "search_entities"

    def test_get_entity_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_entity")
        assert definition.name == "get_entity"

    def test_both_have_read_permission(self, registered_registry: ToolRegistry) -> None:
        for name in ("search_entities", "get_entity"):
            definition = registered_registry.get_definition(name)
            assert definition.permission == Permission.READ

    def test_both_have_empty_side_effects(self, registered_registry: ToolRegistry) -> None:
        for name in ("search_entities", "get_entity"):
            definition = registered_registry.get_definition(name)
            assert definition.side_effects == frozenset()

    def test_both_allow_both_session_modes(self, registered_registry: ToolRegistry) -> None:
        expected = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
        for name in ("search_entities", "get_entity"):
            definition = registered_registry.get_definition(name)
            assert definition.allowed_session_modes == expected

    def test_search_entities_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("search_entities")
        assert definition.input_schema is SearchEntitiesInput
        assert definition.output_schema is SearchEntitiesOutput

    def test_get_entity_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_entity")
        assert definition.input_schema is GetEntityInput
        assert definition.output_schema is GetEntityOutput

    def test_deterministic_registry_listing(self, registered_registry: ToolRegistry) -> None:
        names = [d.name for d in registered_registry.list_definitions()]
        assert names == ["get_entity", "search_entities"]

    def test_registration_count(self, registered_registry: ToolRegistry) -> None:
        assert len(registered_registry) == 2


# ═══════════════════════════════════════════════════════════════════════════
# SearchEntitiesInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchEntitiesInputValidation:
    def test_valid_input(self) -> None:
        inp = SearchEntitiesInput(text="Gandalf", entity_types={EntityType.NPC}, limit=10)
        assert inp.text == "Gandalf"
        assert inp.entity_types == {EntityType.NPC}
        assert inp.limit == 10

    def test_valid_input_no_types(self) -> None:
        inp = SearchEntitiesInput(text="Gandalf")
        assert inp.text == "Gandalf"
        assert inp.entity_types is None
        assert inp.limit == 20

    def test_empty_text_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            SearchEntitiesInput(text="")

    def test_whitespace_text_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            SearchEntitiesInput(text="   ")

    def test_non_printable_text_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-printable"):
            SearchEntitiesInput(text="bad\x00text")

    def test_limit_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            SearchEntitiesInput(text="test", limit=0)

    def test_limit_bool_rejected(self) -> None:
        with pytest.raises(ValidationError, match="valid integer"):
            SearchEntitiesInput(text="test", limit=True)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SearchEntitiesInput(text="test", unknown="x")  # type: ignore[call-arg]

    def test_invalid_entity_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SearchEntitiesInput(text="test", entity_types={"invalid"})  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# SearchEntitiesOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchEntitiesOutputValidation:
    def test_empty_results(self) -> None:
        output = SearchEntitiesOutput(results=[])
        assert output.results == []

    def test_single_result(self) -> None:
        result = EntitySearchResult(
            entity_id="npc--gandalf",
            entity_type=EntityType.NPC,
            name="Gandalf",
            status="active",
            match_kind=MatchKind.EXACT_NAME,
            score=None,
        )
        output = SearchEntitiesOutput(results=[result])
        assert len(output.results) == 1
        assert output.results[0].entity_id == "npc--gandalf"

    def test_result_with_score(self) -> None:
        result = EntitySearchResult(
            entity_id="npc--gandalf",
            entity_type=EntityType.NPC,
            name="Gandalf",
            status="active",
            match_kind=MatchKind.FUZZY_NAME,
            score=85.5,
        )
        assert result.score == 85.5

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EntitySearchResult(  # type: ignore[call-arg]
                entity_id="npc--gandalf",
                entity_type=EntityType.NPC,
                name="Gandalf",
                status="active",
                match_kind=MatchKind.EXACT_NAME,
                unknown="x",
            )


# ═══════════════════════════════════════════════════════════════════════════
# GetEntityInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEntityInputValidation:
    def test_valid_input(self) -> None:
        inp = GetEntityInput(entity_id="npc--gandalf")
        assert inp.entity_id == "npc--gandalf"

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            GetEntityInput(entity_id="")

    def test_whitespace_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            GetEntityInput(entity_id="  ")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetEntityInput(entity_id="npc--gandalf", unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# GetEntityOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEntityOutputValidation:
    def test_valid_output(self) -> None:
        entity = _make_entity("npc--gandalf")
        output = GetEntityOutput(entity=entity, body="# Body")
        assert output.entity.id == "npc--gandalf"
        assert output.body == "# Body"

    def test_extra_fields_rejected(self) -> None:
        entity = _make_entity("npc--gandalf")
        with pytest.raises(ValidationError):
            GetEntityOutput(entity=entity, body="# Body", unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# Registration API
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationAPI:
    def test_register_with_invalid_registry_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ToolRegistry"):
            register_entity_read_tools(
                "not_a_registry",  # type: ignore[arg-type]
                search_service=FakeSearchService(),
                repository=FakeRepository(),
            )

    def test_duplicate_registration_rejected(
        self,
        registry: ToolRegistry,
    ) -> None:
        register_entity_read_tools(
            registry,
            search_service=FakeSearchService(),
            repository=FakeRepository(),
        )
        with pytest.raises(DndAssistantError, match="already registered"):
            register_entity_read_tools(
                registry,
                search_service=FakeSearchService(),
                repository=FakeRepository(),
            )
