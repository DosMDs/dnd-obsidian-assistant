"""Unit tests for S2-02 Base Entity schema.

Covers Entity model construction, field-level validation, serialisation
and round-trip behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import Entity
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Visibility,
)

# ── Helpers ────────────────────────────────────────────────────────────────

_CANONICAL_KWARGS = {
    "id": "npc_01J123ABC",
    "type": EntityType.NPC,
    "name": "Elira Voss",
    "status": "active",
    "visibility": Visibility.PLAYER,
    "knowledge_status": KnowledgeStatus.CONFIRMED,
    "created_session": "S007",
    "last_seen_session": "S014",
    "created_at": datetime(2026, 8, 27, 18, 10, 0, tzinfo=UTC),
    "updated_at": datetime(2026, 8, 27, 19, 2, 0, tzinfo=UTC),
    "revision": 4,
    "tags": ["npc", "ally"],
}


def _make(**overrides: object) -> Entity:
    """Build an Entity from canonical kwargs with optional overrides."""
    return Entity(**{**_CANONICAL_KWARGS, **overrides})  # type: ignore[arg-type]


# ── Valid construction ─────────────────────────────────────────────────────


class TestValidConstruction:
    def test_canonical_entity(self) -> None:
        """Build the canonical example from the spec."""
        entity = _make()
        assert entity.id == "npc_01J123ABC"
        assert entity.type == EntityType.NPC
        assert entity.name == "Elira Voss"
        assert entity.status == "active"
        assert entity.visibility == Visibility.PLAYER
        assert entity.knowledge_status == KnowledgeStatus.CONFIRMED
        assert entity.created_session == "S007"
        assert entity.last_seen_session == "S014"
        assert entity.created_at == datetime(2026, 8, 27, 18, 10, 0, tzinfo=UTC)
        assert entity.updated_at == datetime(2026, 8, 27, 19, 2, 0, tzinfo=UTC)
        assert entity.revision == 4
        assert entity.tags == ["npc", "ally"]
        assert entity.schema_version == 1

    def test_entity_type_npc(self) -> None:
        entity = _make(type=EntityType.NPC)
        assert entity.type == EntityType.NPC

    def test_entity_type_location(self) -> None:
        entity = _make(type=EntityType.LOCATION)
        assert entity.type == EntityType.LOCATION

    def test_entity_type_quest(self) -> None:
        entity = _make(type=EntityType.QUEST)
        assert entity.type == EntityType.QUEST

    def test_entity_type_item(self) -> None:
        entity = _make(type=EntityType.ITEM)
        assert entity.type == EntityType.ITEM

    def test_unicode_name(self) -> None:
        entity = _make(name="Варос")
        assert entity.name == "Варос"

    def test_unicode_name_japanese(self) -> None:
        entity = _make(name="銀の鍵")
        assert entity.name == "銀の鍵"

    def test_unicode_tags(self) -> None:
        entity = _make(tags=["локация", "подземелье"])
        assert entity.tags == ["локация", "подземелье"]

    def test_empty_tags(self) -> None:
        entity = _make(tags=[])
        assert entity.tags == []

    def test_default_tags(self) -> None:
        entity = Entity(
            id="npc_01J123ABC",
            type=EntityType.NPC,
            name="Elira Voss",
            status="active",
            visibility=Visibility.PLAYER,
            knowledge_status=KnowledgeStatus.CONFIRMED,
            created_at=datetime(2026, 8, 27, 18, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 27, 19, 2, 0, tzinfo=UTC),
            revision=4,
        )
        assert entity.tags == []

    def test_session_refs_none(self) -> None:
        entity = _make(created_session=None, last_seen_session=None)
        assert entity.created_session is None
        assert entity.last_seen_session is None


# ── schema_version ─────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_default_is_one(self) -> None:
        entity = _make()
        assert entity.schema_version == 1

    def test_accepts_one(self) -> None:
        entity = _make(schema_version=1)
        assert entity.schema_version == 1

    def test_rejects_two(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=2)

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=0)

    def test_rejects_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version="1")  # type: ignore[arg-type]


# ── id (EntityId) ──────────────────────────────────────────────────────────


class TestId:
    def test_accepts_valid_entity_id(self) -> None:
        entity = _make(id="location_01JABC")
        assert entity.id == "location_01JABC"

    def test_accepts_unicode_id(self) -> None:
        entity = _make(id="локация_01")
        assert entity.id == "локация_01"

    def test_rejects_empty_id(self) -> None:
        with pytest.raises(ValidationError):
            _make(id="")

    def test_rejects_whitespace_id(self) -> None:
        with pytest.raises(ValidationError):
            _make(id=" ")

    def test_rejects_leading_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(id=" leading")

    def test_rejects_trailing_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(id="trailing ")


# ── name ───────────────────────────────────────────────────────────────────


class TestName:
    @pytest.mark.parametrize(
        "invalid_name",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            " Elira",
            "Elira ",
            " Elira ",
            "\tleading",
            "trailing\n",
        ],
    )
    def test_rejects_invalid_names(self, invalid_name: str) -> None:
        with pytest.raises(ValidationError):
            _make(name=invalid_name)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(name="Elira\x00Voss")

    def test_accepts_unicode(self) -> None:
        entity = _make(name="Варос")
        assert entity.name == "Варос"

    def test_accepts_japanese(self) -> None:
        entity = _make(name="銀の鍵")
        assert entity.name == "銀の鍵"

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(name=123)  # type: ignore[arg-type]


# ── status ─────────────────────────────────────────────────────────────────


class TestStatus:
    @pytest.mark.parametrize("valid_status", ["active", "alive", "completed", "unknown"])
    def test_accepts_various_statuses(self, valid_status: str) -> None:
        entity = _make(status=valid_status)
        assert entity.status == valid_status

    @pytest.mark.parametrize(
        "invalid_status",
        [
            "",
            " ",
            " active",
            "active ",
            " active ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_statuses(self, invalid_status: str) -> None:
        with pytest.raises(ValidationError):
            _make(status=invalid_status)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(status="activ\x00e")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(status=1)  # type: ignore[arg-type]


# ── visibility ─────────────────────────────────────────────────────────────


class TestVisibility:
    @pytest.mark.parametrize(
        "valid_visibility",
        [Visibility.PLAYER, Visibility.DM, Visibility.SYSTEM, "player", "dm", "system"],
    )
    def test_accepts_valid_values(self, valid_visibility: Visibility | str) -> None:
        entity = _make(visibility=valid_visibility)
        assert entity.visibility == Visibility(valid_visibility)

    @pytest.mark.parametrize("invalid_visibility", ["public", "secret", "", " "])
    def test_rejects_invalid_values(self, invalid_visibility: str) -> None:
        with pytest.raises(ValidationError):
            _make(visibility=invalid_visibility)


# ── knowledge_status ───────────────────────────────────────────────────────


class TestKnowledgeStatus:
    @pytest.mark.parametrize(
        "valid_ks",
        [
            KnowledgeStatus.CONFIRMED,
            KnowledgeStatus.REPORTED,
            KnowledgeStatus.RUMOR,
            KnowledgeStatus.INFERRED,
            KnowledgeStatus.UNKNOWN,
            "confirmed",
            "reported",
            "rumor",
            "inferred",
            "unknown",
        ],
    )
    def test_accepts_valid_values(self, valid_ks: KnowledgeStatus | str) -> None:
        entity = _make(knowledge_status=valid_ks)
        assert entity.knowledge_status == KnowledgeStatus(valid_ks)

    @pytest.mark.parametrize("invalid_ks", ["guessed", "certain", "", " "])
    def test_rejects_invalid_values(self, invalid_ks: str) -> None:
        with pytest.raises(ValidationError):
            _make(knowledge_status=invalid_ks)


# ── session references ─────────────────────────────────────────────────────


class TestSessionReferences:
    @pytest.mark.parametrize("valid_ref", ["S007", "S014", "session_abc", "1"])
    def test_accepts_valid_session_refs(self, valid_ref: str) -> None:
        entity = _make(created_session=valid_ref)
        assert entity.created_session == valid_ref

    def test_accepts_none(self) -> None:
        entity = _make(created_session=None)
        assert entity.created_session is None

    @pytest.mark.parametrize(
        "invalid_ref",
        [
            "",
            " ",
            " S007",
            "S007 ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_session_refs(self, invalid_ref: str) -> None:
        with pytest.raises(ValidationError):
            _make(created_session=invalid_ref)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(created_session="S00\x007")


# ── timestamps ─────────────────────────────────────────────────────────────


class TestTimestamps:
    def test_accepts_aware_datetime(self) -> None:
        dt = datetime(2026, 8, 27, 18, 10, 0, tzinfo=UTC)
        entity = _make(created_at=dt)
        assert entity.created_at == dt

    def test_accepts_iso_string(self) -> None:
        entity = _make(created_at="2026-08-27T18:10:00Z")
        assert entity.created_at == datetime(2026, 8, 27, 18, 10, 0, tzinfo=UTC)

    def test_accepts_other_timezone(self) -> None:
        entity = _make(created_at="2026-08-27T21:10:00+00:00")
        assert entity.created_at == datetime(2026, 8, 27, 21, 10, 0, tzinfo=UTC)

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            _make(created_at=datetime(2026, 8, 27, 18, 10, 0))

    def test_rejects_naive_iso_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(created_at="2026-08-27T18:10:00")


# ── revision ───────────────────────────────────────────────────────────────


class TestRevision:
    @pytest.mark.parametrize("valid_revision", [1, 2, 100, 999])
    def test_accepts_valid_revisions(self, valid_revision: int) -> None:
        entity = _make(revision=valid_revision)
        assert entity.revision == valid_revision

    @pytest.mark.parametrize("invalid_revision", [0, -1, -100])
    def test_rejects_non_positive_integers(self, invalid_revision: int) -> None:
        with pytest.raises(ValidationError):
            _make(revision=invalid_revision)

    @pytest.mark.parametrize("bool_value", [True, False])
    def test_rejects_bool(self, bool_value: bool) -> None:
        with pytest.raises(ValidationError):
            _make(revision=bool_value)

    def test_rejects_string_coercion(self) -> None:
        with pytest.raises(ValidationError):
            _make(revision="1")  # type: ignore[arg-type]

    def test_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            _make(revision=1.0)  # type: ignore[arg-type]


# ── tags ───────────────────────────────────────────────────────────────────


class TestTags:
    def test_default_empty(self) -> None:
        entity = Entity(
            id="npc_01J123ABC",
            type=EntityType.NPC,
            name="Elira Voss",
            status="active",
            visibility=Visibility.PLAYER,
            knowledge_status=KnowledgeStatus.CONFIRMED,
            created_at=datetime(2026, 8, 27, 18, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 27, 19, 2, 0, tzinfo=UTC),
            revision=4,
        )
        assert entity.tags == []

    def test_preserves_order(self) -> None:
        entity = _make(tags=["z", "a", "m"])
        assert entity.tags == ["z", "a", "m"]

    def test_does_not_deduplicate(self) -> None:
        entity = _make(tags=["npc", "npc"])
        assert entity.tags == ["npc", "npc"]

    def test_accepts_unicode(self) -> None:
        entity = _make(tags=["локация", "подземелье"])
        assert entity.tags == ["локация", "подземелье"]

    @pytest.mark.parametrize(
        "invalid_tag",
        [
            "",
            " ",
            " tag",
            "tag ",
            " tag ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_tags(self, invalid_tag: str) -> None:
        with pytest.raises(ValidationError):
            _make(tags=[invalid_tag])

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(tags=["npc\x00"])

    def test_rejects_non_string_tag(self) -> None:
        with pytest.raises(ValidationError):
            _make(tags=[123])  # type: ignore[list-item]


# ── extra fields ───────────────────────────────────────────────────────────


class TestExtraFields:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            Entity(  # type: ignore[call-arg]
                **_CANONICAL_KWARGS,
                current_location="Waterdeep",
            )


# ── serialisation ──────────────────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_python(self) -> None:
        entity = _make()
        dumped = entity.model_dump()
        assert dumped["id"] == "npc_01J123ABC"
        assert dumped["type"] == "npc"
        assert dumped["name"] == "Elira Voss"
        assert dumped["status"] == "active"
        assert dumped["visibility"] == "player"
        assert dumped["knowledge_status"] == "confirmed"
        assert dumped["created_session"] == "S007"
        assert dumped["last_seen_session"] == "S014"
        assert dumped["revision"] == 4
        assert dumped["tags"] == ["npc", "ally"]
        assert dumped["schema_version"] == 1
        assert isinstance(dumped["created_at"], datetime)
        assert isinstance(dumped["updated_at"], datetime)

    def test_model_dump_json(self) -> None:
        entity = _make()
        dumped = entity.model_dump(mode="json")
        assert dumped["id"] == "npc_01J123ABC"
        assert dumped["type"] == "npc"
        assert dumped["name"] == "Elira Voss"
        assert dumped["status"] == "active"
        assert dumped["visibility"] == "player"
        assert dumped["knowledge_status"] == "confirmed"
        assert dumped["created_session"] == "S007"
        assert dumped["last_seen_session"] == "S014"
        assert dumped["revision"] == 4
        assert dumped["tags"] == ["npc", "ally"]
        assert dumped["schema_version"] == 1
        assert isinstance(dumped["created_at"], str)
        assert isinstance(dumped["updated_at"], str)

    def test_round_trip(self) -> None:
        entity = _make()
        data = entity.model_dump(mode="json")
        restored = Entity.model_validate(data)
        assert restored.id == entity.id
        assert restored.name == entity.name
        assert restored.type == entity.type
        assert restored.status == entity.status
        assert restored.visibility == entity.visibility
        assert restored.knowledge_status == entity.knowledge_status
        assert restored.created_session == entity.created_session
        assert restored.last_seen_session == entity.last_seen_session
        assert restored.revision == entity.revision
        assert restored.tags == entity.tags
        assert restored.schema_version == entity.schema_version
        assert restored.created_at == entity.created_at
        assert restored.updated_at == entity.updated_at


# ── domain import smoke test ────────────────────────────────────────────────


def test_entity_module_importable() -> None:
    """Verify the entity module can be imported without pulling in upper layers."""
    import dnd_assistant.domain.entity  # noqa: F401
