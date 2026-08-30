"""Unit tests for S2-01 foundational domain types.

Covers EntityType, KnowledgeStatus, Visibility, Provenance, EntityId,
and Revision.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Provenance,
    Revision,
    Visibility,
)

# ── EntityType ────────────────────────────────────────────────────────────


class TestEntityType:
    def test_all_valid_values(self) -> None:
        assert EntityType.NPC.value == "npc"
        assert EntityType.LOCATION.value == "location"
        assert EntityType.QUEST.value == "quest"
        assert EntityType.ITEM.value == "item"

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a valid EntityType"):
            EntityType("pc")

    def test_str_compatible(self) -> None:
        assert str(EntityType.NPC) == "npc"

    def test_serialization(self) -> None:
        assert EntityType.NPC == "npc"


# ── KnowledgeStatus ───────────────────────────────────────────────────────


class TestKnowledgeStatus:
    def test_all_valid_values(self) -> None:
        assert KnowledgeStatus.CONFIRMED.value == "confirmed"
        assert KnowledgeStatus.REPORTED.value == "reported"
        assert KnowledgeStatus.RUMOR.value == "rumor"
        assert KnowledgeStatus.INFERRED.value == "inferred"
        assert KnowledgeStatus.UNKNOWN.value == "unknown"

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a valid KnowledgeStatus"):
            KnowledgeStatus("guessed")

    def test_str_compatible(self) -> None:
        assert str(KnowledgeStatus.CONFIRMED) == "confirmed"


# ── Visibility ────────────────────────────────────────────────────────────


class TestVisibility:
    def test_all_valid_values(self) -> None:
        assert Visibility.PLAYER.value == "player"
        assert Visibility.DM.value == "dm"
        assert Visibility.SYSTEM.value == "system"

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a valid Visibility"):
            Visibility("public")

    def test_str_compatible(self) -> None:
        assert str(Visibility.PLAYER) == "player"


# ── Provenance ────────────────────────────────────────────────────────────


class TestProvenance:
    def test_all_valid_values(self) -> None:
        assert Provenance.MANUAL.value == "manual"
        assert Provenance.SESSION.value == "session"
        assert Provenance.BOOTSTRAP.value == "bootstrap"
        assert Provenance.IMPORT.value == "import"
        assert Provenance.MODEL_INFERENCE.value == "model_inference"

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a valid Provenance"):
            Provenance("api")

    def test_str_compatible(self) -> None:
        assert str(Provenance.MANUAL) == "manual"


# ── EntityId ──────────────────────────────────────────────────────────────


class _EntityIdModel(BaseModel):
    id: EntityId


# TypeAdapter for direct validation without a model
_entity_id_adapter: TypeAdapter[str] = TypeAdapter(EntityId)


class TestEntityId:
    """EntityId validation tests.

    Policy: reject empty, whitespace-only, leading/trailing whitespace,
    and non-printable characters. Accept any non-empty printable string
    including printable Unicode.
    """

    @pytest.mark.parametrize(
        "valid_id",
        [
            "npc_01JXYZ",
            "location_01JABC",
            "quest_example",
            "item_sword_001",
            "a",
            "abc123",
            "npc-01",
            "entity.with.dots",
            "npc_Варос",
            "локация_01",
        ],
    )
    def test_accepts_valid_ids(self, valid_id: str) -> None:
        model = _EntityIdModel(id=valid_id)
        assert model.id == valid_id

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            "\r",
            " leading",
            "trailing ",
            " both ",
            "\tleading_tab",
            "trailing_newline\n",
        ],
    )
    def test_rejects_invalid_ids(self, invalid_id: str) -> None:
        with pytest.raises(ValidationError):
            _EntityIdModel(id=invalid_id)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _EntityIdModel(id=123)  # type: ignore[arg-type]

    def test_round_trip_serialization(self) -> None:
        model = _EntityIdModel(id="npc_01JXYZ")
        dumped = model.model_dump()
        assert dumped == {"id": "npc_01JXYZ"}

    def test_type_adapter_accepts_valid(self) -> None:
        result = _entity_id_adapter.validate_python("npc_01JXYZ")
        assert result == "npc_01JXYZ"

    def test_type_adapter_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            _entity_id_adapter.validate_python("")


# ── Revision ──────────────────────────────────────────────────────────────


class _RevisionModel(BaseModel):
    revision: Revision


_revision_adapter: TypeAdapter[int] = TypeAdapter(Revision)


class TestRevision:
    """Revision validation tests.

    Policy: integer >= 1, strict mode (no bool, no string coercion).
    """

    @pytest.mark.parametrize("valid_revision", [1, 2, 100, 999])
    def test_accepts_valid_revisions(self, valid_revision: int) -> None:
        model = _RevisionModel(revision=valid_revision)
        assert model.revision == valid_revision

    @pytest.mark.parametrize("invalid_revision", [0, -1, -100])
    def test_rejects_non_positive_integers(self, invalid_revision: int) -> None:
        with pytest.raises(ValidationError):
            _RevisionModel(revision=invalid_revision)

    @pytest.mark.parametrize("bool_value", [True, False])
    def test_rejects_bool(self, bool_value: bool) -> None:
        with pytest.raises(ValidationError):
            _RevisionModel(revision=bool_value)

    def test_rejects_string_coercion(self) -> None:
        with pytest.raises(ValidationError):
            _RevisionModel(revision="1")  # type: ignore[arg-type]

    def test_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            _RevisionModel(revision=1.0)  # type: ignore[arg-type]

    def test_round_trip_serialization(self) -> None:
        model = _RevisionModel(revision=42)
        dumped = model.model_dump()
        assert dumped == {"revision": 42}

    def test_type_adapter_accepts_valid(self) -> None:
        result = _revision_adapter.validate_python(5)
        assert result == 5

    def test_type_adapter_rejects_bool(self) -> None:
        with pytest.raises(ValidationError):
            _revision_adapter.validate_python(True)


# ── Domain import smoke test ──────────────────────────────────────────────


def test_domain_types_module_importable() -> None:
    """Verify the types module can be imported without pulling in upper layers."""
    import dnd_assistant.domain.types  # noqa: F401
