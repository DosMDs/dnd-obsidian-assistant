"""Unit tests for S2-04 TimelineEvent domain schema.

Covers TimelineEvent model construction, TemporalCertainty enum,
field-level validation, model-level temporal consistency rules,
serialisation and round-trip behaviour.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import TemporalCertainty, TimelineEvent
from dnd_assistant.domain.types import Visibility

# ── Helpers ─────────────────────────────────────────────────────────────────

_CANONICAL_KWARGS = {
    "id": "event_01JXYZ",
    "type": "timeline_event",
    "name": "Battle of Waterdeep",
    "status": "historical",
    "certainty": TemporalCertainty.EXACT,
    "importance": "major",
    "world_tick": 15739200,
    "world_tick_min": None,
    "world_tick_max": None,
    "location": "Waterdeep",
    "visibility": Visibility.PLAYER,
    "revision": 1,
}


def _make(**overrides: object) -> TimelineEvent:
    """Build a TimelineEvent from canonical kwargs with optional overrides."""
    return TimelineEvent(**{**_CANONICAL_KWARGS, **overrides})  # type: ignore[arg-type]


# ── TemporalCertainty enum ──────────────────────────────────────────────────


class TestTemporalCertainty:
    def test_all_valid_values(self) -> None:
        assert TemporalCertainty.EXACT.value == "exact"
        assert TemporalCertainty.APPROXIMATE.value == "approximate"
        assert TemporalCertainty.RANGE.value == "range"
        assert TemporalCertainty.UNKNOWN.value == "unknown"

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a valid TemporalCertainty"):
            TemporalCertainty("precise")

    def test_str_compatible(self) -> None:
        assert str(TemporalCertainty.EXACT) == "exact"


# ── Valid construction ──────────────────────────────────────────────────────


class TestValidConstruction:
    def test_canonical_exact_event(self) -> None:
        """Build the canonical exact-timing example."""
        event = _make()
        assert event.schema_version == 1
        assert event.id == "event_01JXYZ"
        assert event.type == "timeline_event"
        assert event.name == "Battle of Waterdeep"
        assert event.status == "historical"
        assert event.certainty == TemporalCertainty.EXACT
        assert event.importance == "major"
        assert event.world_tick == 15739200
        assert event.world_tick_min is None
        assert event.world_tick_max is None
        assert event.location == "Waterdeep"
        assert event.visibility == Visibility.PLAYER
        assert event.revision == 1

    def test_approximate_event(self) -> None:
        """Build an approximate-timing event."""
        event = _make(
            certainty=TemporalCertainty.APPROXIMATE,
            world_tick=None,
            world_tick_min=15739000,
            world_tick_max=15740000,
        )
        assert event.certainty == TemporalCertainty.APPROXIMATE
        assert event.world_tick is None
        assert event.world_tick_min == 15739000
        assert event.world_tick_max == 15740000

    def test_range_event(self) -> None:
        """Build a range-timing event."""
        event = _make(
            certainty=TemporalCertainty.RANGE,
            world_tick=None,
            world_tick_min=15739000,
            world_tick_max=15741000,
        )
        assert event.certainty == TemporalCertainty.RANGE
        assert event.world_tick is None
        assert event.world_tick_min == 15739000
        assert event.world_tick_max == 15741000

    def test_unknown_time_event(self) -> None:
        """Build an unknown-timing event."""
        event = _make(
            certainty=TemporalCertainty.UNKNOWN,
            world_tick=None,
            world_tick_min=None,
            world_tick_max=None,
        )
        assert event.certainty == TemporalCertainty.UNKNOWN
        assert event.world_tick is None
        assert event.world_tick_min is None
        assert event.world_tick_max is None

    def test_location_optional(self) -> None:
        """Location is optional and defaults to None."""
        event = _make(location=None)
        assert event.location is None

    def test_unicode_name(self) -> None:
        """Accept printable Unicode event names."""
        event = _make(
            name="\u0411\u0438\u0442\u0432\u0430 \u043f\u0440\u0438 \u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f\u0435"
        )
        assert (
            event.name
            == "\u0411\u0438\u0442\u0432\u0430 \u043f\u0440\u0438 \u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f\u0435"
        )

    def test_unicode_status(self) -> None:
        """Accept printable Unicode status values."""
        event = _make(status="\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e")
        assert event.status == "\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e"

    def test_unicode_importance(self) -> None:
        """Accept printable Unicode importance values."""
        event = _make(importance="\u0432\u0430\u0436\u043d\u043e\u0435")
        assert event.importance == "\u0432\u0430\u0436\u043d\u043e\u0435"

    def test_unicode_location(self) -> None:
        """Accept printable Unicode location values."""
        event = _make(location="\u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f")
        assert event.location == "\u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f"


# ── schema_version ──────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_default_is_one(self) -> None:
        event = _make()
        assert event.schema_version == 1

    def test_accepts_one(self) -> None:
        event = _make(schema_version=1)
        assert event.schema_version == 1

    def test_rejects_two(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=2)

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=0)

    def test_rejects_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version="1")  # type: ignore[arg-type]


# ── type discriminator ──────────────────────────────────────────────────────


class TestType:
    def test_accepts_timeline_event(self) -> None:
        event = _make(type="timeline_event")
        assert event.type == "timeline_event"

    def test_default_is_timeline_event(self) -> None:
        event = _make()
        assert event.type == "timeline_event"

    def test_rejects_other_values(self) -> None:
        with pytest.raises(ValidationError):
            _make(type="session")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make(type="")  # type: ignore[arg-type]

    def test_rejects_none(self) -> None:
        with pytest.raises(ValidationError):
            _make(type=None)  # type: ignore[arg-type]


# ── id (EntityId) ───────────────────────────────────────────────────────────


class TestId:
    def test_accepts_valid_entity_id(self) -> None:
        event = _make(id="event_abc_123")
        assert event.id == "event_abc_123"

    def test_accepts_unicode_id(self) -> None:
        event = _make(id="\u0441\u043e\u0431\u044b\u0442\u0438\u0435_01")
        assert event.id == "\u0441\u043e\u0431\u044b\u0442\u0438\u0435_01"

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


# ── name ────────────────────────────────────────────────────────────────────


class TestName:
    @pytest.mark.parametrize(
        "invalid_name",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            " Battle",
            "Battle ",
            " Battle ",
            "\tleading",
            "trailing\n",
        ],
    )
    def test_rejects_invalid_names(self, invalid_name: str) -> None:
        with pytest.raises(ValidationError):
            _make(name=invalid_name)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(name="Battle\x00of")

    def test_accepts_unicode(self) -> None:
        event = _make(
            name="\u0411\u0438\u0442\u0432\u0430 \u043f\u0440\u0438 \u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f\u0435"
        )
        assert (
            event.name
            == "\u0411\u0438\u0442\u0432\u0430 \u043f\u0440\u0438 \u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f\u0435"
        )

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(name=123)  # type: ignore[arg-type]


# ── status ──────────────────────────────────────────────────────────────────


class TestStatus:
    @pytest.mark.parametrize("valid_status", ["historical", "ongoing", "resolved", "prophecy"])
    def test_accepts_various_statuses(self, valid_status: str) -> None:
        event = _make(status=valid_status)
        assert event.status == valid_status

    @pytest.mark.parametrize(
        "invalid_status",
        [
            "",
            " ",
            " ongoing",
            "ongoing ",
            " ongoing ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_statuses(self, invalid_status: str) -> None:
        with pytest.raises(ValidationError):
            _make(status=invalid_status)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(status="histori\x00cal")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(status=1)  # type: ignore[arg-type]


# ── importance ──────────────────────────────────────────────────────────────


class TestImportance:
    @pytest.mark.parametrize("valid_importance", ["major", "minor", "background", "critical"])
    def test_accepts_various_importance(self, valid_importance: str) -> None:
        event = _make(importance=valid_importance)
        assert event.importance == valid_importance

    @pytest.mark.parametrize(
        "invalid_importance",
        [
            "",
            " ",
            " major",
            "major ",
            " major ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_importance(self, invalid_importance: str) -> None:
        with pytest.raises(ValidationError):
            _make(importance=invalid_importance)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(importance="majo\x00r")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(importance=1)  # type: ignore[arg-type]


# ── location ────────────────────────────────────────────────────────────────


class TestLocation:
    def test_accepts_valid_location(self) -> None:
        event = _make(location="Waterdeep")
        assert event.location == "Waterdeep"

    def test_accepts_none(self) -> None:
        event = _make(location=None)
        assert event.location is None

    def test_accepts_unicode(self) -> None:
        event = _make(location="\u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f")
        assert event.location == "\u0412\u0430\u0442\u0435\u0440\u0434\u0438\u043f"

    @pytest.mark.parametrize(
        "invalid_location",
        [
            "",
            " ",
            " Waterdeep",
            "Waterdeep ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_locations(self, invalid_location: str) -> None:
        with pytest.raises(ValidationError):
            _make(location=invalid_location)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(location="Water\x00deep")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(location=123)  # type: ignore[arg-type]


# ── visibility ──────────────────────────────────────────────────────────────


class TestVisibility:
    @pytest.mark.parametrize(
        "valid_visibility",
        [Visibility.PLAYER, Visibility.DM, Visibility.SYSTEM, "player", "dm", "system"],
    )
    def test_accepts_valid_values(self, valid_visibility: Visibility | str) -> None:
        event = _make(visibility=valid_visibility)
        assert event.visibility == Visibility(valid_visibility)

    @pytest.mark.parametrize("invalid_visibility", ["public", "secret", "", " "])
    def test_rejects_invalid_values(self, invalid_visibility: str) -> None:
        with pytest.raises(ValidationError):
            _make(visibility=invalid_visibility)


# ── revision ────────────────────────────────────────────────────────────────


class TestRevision:
    @pytest.mark.parametrize("valid_revision", [1, 2, 100, 999])
    def test_accepts_valid_revisions(self, valid_revision: int) -> None:
        event = _make(revision=valid_revision)
        assert event.revision == valid_revision

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


# ── Strict world_tick fields ────────────────────────────────────────────────


class TestStrictTicks:
    @pytest.mark.parametrize("valid_tick", [0, 1, 15739200, -1, -100])
    def test_accepts_valid_integers(self, valid_tick: int) -> None:
        event = _make(world_tick=valid_tick)
        assert event.world_tick == valid_tick

    @pytest.mark.parametrize("invalid_value", [True, False])
    def test_rejects_bool_as_tick(self, invalid_value: bool) -> None:
        with pytest.raises(ValidationError):
            _make(world_tick=invalid_value)

    def test_rejects_string_coercion_for_tick(self) -> None:
        with pytest.raises(ValidationError):
            _make(world_tick="123")  # type: ignore[arg-type]

    def test_rejects_float_for_tick(self) -> None:
        with pytest.raises(ValidationError):
            _make(world_tick=1.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_value", [True, False])
    def test_rejects_bool_as_tick_min(self, invalid_value: bool) -> None:
        with pytest.raises(ValidationError):
            _make(
                certainty=TemporalCertainty.APPROXIMATE,
                world_tick=None,
                world_tick_min=invalid_value,
                world_tick_max=100,
            )

    @pytest.mark.parametrize("invalid_value", [True, False])
    def test_rejects_bool_as_tick_max(self, invalid_value: bool) -> None:
        with pytest.raises(ValidationError):
            _make(
                certainty=TemporalCertainty.APPROXIMATE,
                world_tick=None,
                world_tick_min=0,
                world_tick_max=invalid_value,
            )


# ── Temporal consistency (certainty + tick combinations) ────────────────────


class TestTemporalConsistency:
    def test_exact_missing_world_tick(self) -> None:
        with pytest.raises(ValidationError, match="world_tick is required"):
            _make(certainty=TemporalCertainty.EXACT, world_tick=None)

    def test_exact_with_world_tick_min(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max must be None"):
            _make(certainty=TemporalCertainty.EXACT, world_tick_min=100)

    def test_exact_with_world_tick_max(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max must be None"):
            _make(certainty=TemporalCertainty.EXACT, world_tick_max=200)

    def test_exact_with_both_min_max(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max must be None"):
            _make(certainty=TemporalCertainty.EXACT, world_tick_min=100, world_tick_max=200)

    def test_approximate_with_world_tick(self) -> None:
        with pytest.raises(
            ValidationError, match="world_tick must be None when certainty is 'approximate'"
        ):
            _make(
                certainty=TemporalCertainty.APPROXIMATE,
                world_tick=100,
                world_tick_min=50,
                world_tick_max=200,
            )

    def test_approximate_missing_min(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max are required"):
            _make(
                certainty=TemporalCertainty.APPROXIMATE,
                world_tick=None,
                world_tick_min=None,
                world_tick_max=200,
            )

    def test_approximate_missing_max(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max are required"):
            _make(
                certainty=TemporalCertainty.APPROXIMATE,
                world_tick=None,
                world_tick_min=50,
                world_tick_max=None,
            )

    def test_approximate_min_gt_max(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min.*must not exceed"):
            _make(
                certainty=TemporalCertainty.APPROXIMATE,
                world_tick=None,
                world_tick_min=200,
                world_tick_max=100,
            )

    def test_range_with_world_tick(self) -> None:
        with pytest.raises(
            ValidationError, match="world_tick must be None when certainty is 'range'"
        ):
            _make(
                certainty=TemporalCertainty.RANGE,
                world_tick=100,
                world_tick_min=50,
                world_tick_max=200,
            )

    def test_range_missing_min(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max are required"):
            _make(
                certainty=TemporalCertainty.RANGE,
                world_tick=None,
                world_tick_min=None,
                world_tick_max=200,
            )

    def test_range_missing_max(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min and world_tick_max are required"):
            _make(
                certainty=TemporalCertainty.RANGE,
                world_tick=None,
                world_tick_min=50,
                world_tick_max=None,
            )

    def test_range_min_gt_max(self) -> None:
        with pytest.raises(ValidationError, match="world_tick_min.*must not exceed"):
            _make(
                certainty=TemporalCertainty.RANGE,
                world_tick=None,
                world_tick_min=200,
                world_tick_max=100,
            )

    def test_unknown_with_world_tick(self) -> None:
        with pytest.raises(ValidationError, match="must all be None when certainty is 'unknown'"):
            _make(
                certainty=TemporalCertainty.UNKNOWN,
                world_tick=100,
                world_tick_min=None,
                world_tick_max=None,
            )

    def test_unknown_with_world_tick_min(self) -> None:
        with pytest.raises(ValidationError, match="must all be None when certainty is 'unknown'"):
            _make(
                certainty=TemporalCertainty.UNKNOWN,
                world_tick=None,
                world_tick_min=100,
                world_tick_max=None,
            )

    def test_unknown_with_world_tick_max(self) -> None:
        with pytest.raises(ValidationError, match="must all be None when certainty is 'unknown'"):
            _make(
                certainty=TemporalCertainty.UNKNOWN,
                world_tick=None,
                world_tick_min=None,
                world_tick_max=100,
            )

    def test_approximate_min_eq_max(self) -> None:
        """min == max is valid for approximate (single estimated point)."""
        event = _make(
            certainty=TemporalCertainty.APPROXIMATE,
            world_tick=None,
            world_tick_min=100,
            world_tick_max=100,
        )
        assert event.world_tick_min == 100
        assert event.world_tick_max == 100

    def test_range_min_eq_max(self) -> None:
        """min == max is valid for range (zero-width range)."""
        event = _make(
            certainty=TemporalCertainty.RANGE,
            world_tick=None,
            world_tick_min=100,
            world_tick_max=100,
        )
        assert event.world_tick_min == 100
        assert event.world_tick_max == 100


# ── extra fields ────────────────────────────────────────────────────────────


class TestExtraFields:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            TimelineEvent(**_CANONICAL_KWARGS, unknown_field="test")  # type: ignore[call-arg]


# ── serialisation ───────────────────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_python(self) -> None:
        event = _make()
        dumped = event.model_dump()
        assert dumped["id"] == "event_01JXYZ"
        assert dumped["type"] == "timeline_event"
        assert dumped["name"] == "Battle of Waterdeep"
        assert dumped["status"] == "historical"
        assert dumped["certainty"] == "exact"
        assert dumped["importance"] == "major"
        assert dumped["world_tick"] == 15739200
        assert dumped["world_tick_min"] is None
        assert dumped["world_tick_max"] is None
        assert dumped["location"] == "Waterdeep"
        assert dumped["visibility"] == "player"
        assert dumped["revision"] == 1
        assert dumped["schema_version"] == 1

    def test_model_dump_json(self) -> None:
        event = _make()
        dumped = event.model_dump(mode="json")
        assert dumped["id"] == "event_01JXYZ"
        assert dumped["type"] == "timeline_event"
        assert dumped["name"] == "Battle of Waterdeep"
        assert dumped["status"] == "historical"
        assert dumped["certainty"] == "exact"
        assert dumped["importance"] == "major"
        assert dumped["world_tick"] == 15739200
        assert dumped["world_tick_min"] is None
        assert dumped["world_tick_max"] is None
        assert dumped["location"] == "Waterdeep"
        assert dumped["visibility"] == "player"
        assert dumped["revision"] == 1
        assert dumped["schema_version"] == 1

    def test_round_trip(self) -> None:
        event = _make()
        data = event.model_dump(mode="json")
        restored = TimelineEvent.model_validate(data)
        assert restored.id == event.id
        assert restored.type == event.type
        assert restored.name == event.name
        assert restored.status == event.status
        assert restored.certainty == event.certainty
        assert restored.importance == event.importance
        assert restored.world_tick == event.world_tick
        assert restored.world_tick_min == event.world_tick_min
        assert restored.world_tick_max == event.world_tick_max
        assert restored.location == event.location
        assert restored.visibility == event.visibility
        assert restored.revision == event.revision
        assert restored.schema_version == event.schema_version

    def test_approximate_round_trip(self) -> None:
        event = _make(
            certainty=TemporalCertainty.APPROXIMATE,
            world_tick=None,
            world_tick_min=15739000,
            world_tick_max=15740000,
        )
        data = event.model_dump(mode="json")
        restored = TimelineEvent.model_validate(data)
        assert restored.certainty == TemporalCertainty.APPROXIMATE
        assert restored.world_tick is None
        assert restored.world_tick_min == 15739000
        assert restored.world_tick_max == 15740000

    def test_range_round_trip(self) -> None:
        event = _make(
            certainty=TemporalCertainty.RANGE,
            world_tick=None,
            world_tick_min=15739000,
            world_tick_max=15741000,
        )
        data = event.model_dump(mode="json")
        restored = TimelineEvent.model_validate(data)
        assert restored.certainty == TemporalCertainty.RANGE
        assert restored.world_tick is None
        assert restored.world_tick_min == 15739000
        assert restored.world_tick_max == 15741000

    def test_unknown_round_trip(self) -> None:
        event = _make(
            certainty=TemporalCertainty.UNKNOWN,
            world_tick=None,
            world_tick_min=None,
            world_tick_max=None,
        )
        data = event.model_dump(mode="json")
        restored = TimelineEvent.model_validate(data)
        assert restored.certainty == TemporalCertainty.UNKNOWN
        assert restored.world_tick is None
        assert restored.world_tick_min is None
        assert restored.world_tick_max is None


# ── domain import smoke test ────────────────────────────────────────────────


def test_events_module_importable() -> None:
    """Verify the events module can be imported without pulling in upper layers."""
    import dnd_assistant.domain.events  # noqa: F401
