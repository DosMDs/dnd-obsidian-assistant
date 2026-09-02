"""Tests for entity mutation tool contracts: DTO validation and registration metadata.

Covers:
- Registration metadata (names, permission, side effects, session modes)
- PatchEntityInput validation
- PatchEntityOutput validation
- AppendEntityFactInput validation (including fact validation)
- AppendEntityFactOutput validation
- Registration API
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Revision, Visibility
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.tools.entity_mutations import (
    AppendEntityFactInput,
    AppendEntityFactOutput,
    PatchEntityInput,
    PatchEntityOutput,
    register_entity_mutation_tools,
)
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    Permission,
    SessionMode,
    SideEffect,
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

    def patch_entity(
        self,
        entity_id: str,
        patch: object,
        *,
        expected_revision: object,
        audit: object,
    ) -> object:
        return object()

    def append_entity_fact(
        self,
        entity_id: str,
        *,
        expected_revision: object,
        fact: str,
        audit: object,
    ) -> object:
        return object()


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(
    registry: ToolRegistry,
) -> ToolRegistry:
    register_entity_mutation_tools(
        registry,
        search_service=FakeSearchService(),
        repository=FakeRepository(),
    )
    return registry


# ═══════════════════════════════════════════════════════════════════════════
# Registration metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationMetadata:
    def test_patch_entity_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("patch_entity")
        assert definition.name == "patch_entity"

    def test_append_entity_fact_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("append_entity_fact")
        assert definition.name == "append_entity_fact"

    def test_both_have_write_permission(self, registered_registry: ToolRegistry) -> None:
        for name in ("patch_entity", "append_entity_fact"):
            definition = registered_registry.get_definition(name)
            assert definition.permission == Permission.WRITE

    def test_both_have_entity_mutation_side_effect(self, registered_registry: ToolRegistry) -> None:
        for name in ("patch_entity", "append_entity_fact"):
            definition = registered_registry.get_definition(name)
            assert definition.side_effects == frozenset({SideEffect.ENTITY_MUTATION})

    def test_both_allow_both_session_modes(self, registered_registry: ToolRegistry) -> None:
        expected = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
        for name in ("patch_entity", "append_entity_fact"):
            definition = registered_registry.get_definition(name)
            assert definition.allowed_session_modes == expected

    def test_patch_entity_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("patch_entity")
        assert definition.input_schema is PatchEntityInput
        assert definition.output_schema is PatchEntityOutput

    def test_append_entity_fact_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("append_entity_fact")
        assert definition.input_schema is AppendEntityFactInput
        assert definition.output_schema is AppendEntityFactOutput

    def test_deterministic_registry_listing(self, registered_registry: ToolRegistry) -> None:
        names = [d.name for d in registered_registry.list_definitions()]
        assert names == ["append_entity_fact", "patch_entity"]

    def test_registration_count(self, registered_registry: ToolRegistry) -> None:
        assert len(registered_registry) == 2


# ═══════════════════════════════════════════════════════════════════════════
# PatchEntityInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestPatchEntityInputValidation:
    def test_valid_input(self) -> None:
        patch = EntityPatch(name="New Name")
        inp = PatchEntityInput(
            entity_id="npc--gandalf",
            expected_revision=Revision(1),
            patch=patch,
        )
        assert inp.entity_id == "npc--gandalf"
        assert inp.expected_revision == 1
        assert inp.patch.name == "New Name"

    def test_entity_id_empty_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError, match="must not be empty"):
            PatchEntityInput(
                entity_id="",
                expected_revision=Revision(1),
                patch=patch,
            )

    def test_expected_revision_zero_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            PatchEntityInput(
                entity_id="npc--gandalf",
                expected_revision=0,  # type: ignore[arg-type]
                patch=patch,
            )

    def test_expected_revision_negative_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            PatchEntityInput(
                entity_id="npc--gandalf",
                expected_revision=-1,  # type: ignore[arg-type]
                patch=patch,
            )

    def test_expected_revision_bool_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError, match="valid integer"):
            PatchEntityInput(
                entity_id="npc--gandalf",
                expected_revision=True,  # type: ignore[arg-type]
                patch=patch,
            )

    def test_expected_revision_string_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError, match="valid integer"):
            PatchEntityInput(
                entity_id="npc--gandalf",
                expected_revision="1",  # type: ignore[arg-type]
                patch=patch,
            )

    def test_expected_revision_float_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError, match="valid integer"):
            PatchEntityInput(
                entity_id="npc--gandalf",
                expected_revision=1.0,  # type: ignore[arg-type]
                patch=patch,
            )

    def test_extra_fields_rejected(self) -> None:
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError):
            PatchEntityInput(  # type: ignore[call-arg]
                entity_id="npc--gandalf",
                expected_revision=Revision(1),
                patch=patch,
                unknown="x",
            )

    def test_free_text_name_rejected(self) -> None:
        """No free-text entity reference accepted."""
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError):
            PatchEntityInput(  # type: ignore[call-arg]
                name="Gandalf",
                entity_id="npc--gandalf",
                expected_revision=Revision(1),
                patch=patch,
            )

    def test_entity_name_field_rejected(self) -> None:
        """entity_name is not a valid field."""
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError):
            PatchEntityInput(  # type: ignore[call-arg]
                entity_name="Gandalf",
                entity_id="npc--gandalf",
                expected_revision=Revision(1),
                patch=patch,
            )

    def test_audit_field_rejected(self) -> None:
        """audit must not be accepted from model input."""
        patch = EntityPatch(name="New Name")
        with pytest.raises(ValidationError):
            PatchEntityInput(  # type: ignore[call-arg]
                entity_id="npc--gandalf",
                expected_revision=Revision(1),
                patch=patch,
                audit={"operation_id": "x"},
            )
