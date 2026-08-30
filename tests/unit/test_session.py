"""Unit tests for S2-03 Session domain schema.

Covers Session model construction, field-level validation, serialisation,
round-trip behaviour, and boundary checks.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import Session

# ── Helpers ────────────────────────────────────────────────────────────────

_CANONICAL_KWARGS = {
    "id": "S014",
    "type": "session",
    "status": "completed",
    "real_started_at": datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC),
    "real_finished_at": datetime(2026, 8, 27, 21, 20, 0, tzinfo=UTC),
    "world_tick_start": 15739200,
    "world_tick_end": 15741120,
    "processed": True,
    "processed_model_profile": "post_session",
    "revision": 2,
}


def _make(**overrides: object) -> Session:
    """Build a Session from canonical kwargs with optional overrides."""
    return Session(**{**_CANONICAL_KWARGS, **overrides})  # type: ignore[arg-type]


# ── Valid construction ─────────────────────────────────────────────────────


class TestValidConstruction:
    """Verify the canonical completed session from the spec."""

    def test_canonical_session(self) -> None:
        """Build the canonical example from the spec (YAML equivalent)."""
        session = _make()
        assert session.schema_version == 1
        assert session.id == "S014"
        assert session.type == "session"
        assert session.status == "completed"
        assert session.real_started_at == datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)
        assert session.real_finished_at == datetime(2026, 8, 27, 21, 20, 0, tzinfo=UTC)
        assert session.world_tick_start == 15739200
        assert session.world_tick_end == 15741120
        assert session.processed is True
        assert session.processed_model_profile == "post_session"
        assert session.revision == 2

    def test_canonical_from_iso_strings(self) -> None:
        """Build the canonical example using ISO-8601 strings for timestamps."""
        session = Session(
            id="S014",
            type="session",
            status="completed",
            real_started_at="2026-08-27T17:00:00Z",
            real_finished_at="2026-08-27T21:20:00Z",
            world_tick_start=15739200,
            world_tick_end=15741120,
            processed=True,
            processed_model_profile="post_session",
            revision=2,
        )
        assert session.real_started_at == datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)
        assert session.real_finished_at == datetime(2026, 8, 27, 21, 20, 0, tzinfo=UTC)

    def test_unicode_id(self) -> None:
        """Accept printable Unicode session IDs."""
        session = _make(id="\u0421\u0435\u0441\u0441\u0438\u044f_01")
        assert session.id == "\u0421\u0435\u0441\u0441\u0438\u044f_01"

    def test_unicode_status(self) -> None:
        """Accept printable Unicode status values."""
        session = _make(status="\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430")
        assert session.status == "\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430"

    def test_unicode_processed_model_profile(self) -> None:
        """Accept printable Unicode model profile values."""
        session = _make(
            processed_model_profile="\u043f\u043e\u0441\u0442\u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430"
        )
        assert (
            session.processed_model_profile
            == "\u043f\u043e\u0441\u0442\u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430"
        )


# ── schema_version ─────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_default_is_one(self) -> None:
        session = _make()
        assert session.schema_version == 1

    def test_accepts_one(self) -> None:
        session = _make(schema_version=1)
        assert session.schema_version == 1

    def test_rejects_two(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=2)

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=0)

    def test_rejects_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version="1")  # type: ignore[arg-type]


# ── id ─────────────────────────────────────────────────────────────────────


class TestId:
    @pytest.mark.parametrize(
        "valid_id",
        [
            "S014",
            "session_test",
            "\u0421\u0435\u0441\u0441\u0438\u044f_01",
            "a",
            "abc123",
            "session-01",
            "id.with.dots",
        ],
    )
    def test_accepts_valid_ids(self, valid_id: str) -> None:
        session = _make(id=valid_id)
        assert session.id == valid_id

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            "\r",
            " S014",
            "S014 ",
            " S014 ",
            "\tleading",
            "trailing\n",
        ],
    )
    def test_rejects_invalid_ids(self, invalid_id: str) -> None:
        with pytest.raises(ValidationError):
            _make(id=invalid_id)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(id="S00\x007")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(id=123)  # type: ignore[arg-type]


# ── type ───────────────────────────────────────────────────────────────────


class TestType:
    def test_accepts_session(self) -> None:
        session = _make(type="session")
        assert session.type == "session"

    def test_default_is_session(self) -> None:
        session = _make()
        assert session.type == "session"

    def test_rejects_other_values(self) -> None:
        with pytest.raises(ValidationError):
            _make(type="npc")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make(type="")  # type: ignore[arg-type]

    def test_rejects_none(self) -> None:
        with pytest.raises(ValidationError):
            _make(type=None)  # type: ignore[arg-type]


# ── status ─────────────────────────────────────────────────────────────────


class TestStatus:
    @pytest.mark.parametrize("valid_status", ["completed", "active", "planned", "cancelled"])
    def test_accepts_various_statuses(self, valid_status: str) -> None:
        session = _make(status=valid_status)
        assert session.status == valid_status

    def test_accepts_unicode_status(self) -> None:
        session = _make(status="\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430")
        assert session.status == "\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430"

    @pytest.mark.parametrize(
        "invalid_status",
        [
            "",
            " ",
            " completed",
            "completed ",
            " completed ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_statuses(self, invalid_status: str) -> None:
        with pytest.raises(ValidationError):
            _make(status=invalid_status)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(status="comple\x00ted")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(status=1)  # type: ignore[arg-type]


# ── timestamps ─────────────────────────────────────────────────────────────


class TestTimestamps:
    def test_accepts_aware_datetime(self) -> None:
        dt = datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)
        session = _make(real_started_at=dt)
        assert session.real_started_at == dt

    def test_accepts_iso_string(self) -> None:
        session = _make(real_started_at="2026-08-27T17:00:00Z")
        assert session.real_started_at == datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)

    def test_accepts_other_timezone(self) -> None:
        session = _make(real_started_at="2026-08-27T20:00:00+03:00")
        assert session.real_started_at == datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            _make(real_started_at=datetime(2026, 8, 27, 17, 0, 0))

    def test_rejects_naive_iso_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(real_started_at="2026-08-27T17:00:00")

    def test_real_finished_at_allows_none(self) -> None:
        session = _make(real_finished_at=None)
        assert session.real_finished_at is None

    def test_real_finished_at_omitted(self) -> None:
        """Omitting real_finished_at defaults to None."""
        session = Session(
            id="S015",
            type="session",
            status="active",
            real_started_at="2026-08-28T18:00:00Z",
            world_tick_start=15742000,
            revision=1,
        )
        assert session.real_finished_at is None


# ── world ticks ────────────────────────────────────────────────────────────


class TestWorldTicks:
    @pytest.mark.parametrize("valid_tick", [0, 1, 15739200, -1, -100])
    def test_accepts_valid_integers(self, valid_tick: int) -> None:
        session = _make(world_tick_start=valid_tick)
        assert session.world_tick_start == valid_tick

    @pytest.mark.parametrize("invalid_value", [True, False])
    def test_rejects_bool(self, invalid_value: bool) -> None:
        with pytest.raises(ValidationError):
            _make(world_tick_start=invalid_value)

    def test_rejects_string_coercion(self) -> None:
        with pytest.raises(ValidationError):
            _make(world_tick_start="123")  # type: ignore[arg-type]

    def test_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            _make(world_tick_start=1.0)  # type: ignore[arg-type]

    def test_world_tick_end_allows_none(self) -> None:
        session = _make(world_tick_end=None)
        assert session.world_tick_end is None

    def test_world_tick_end_omitted(self) -> None:
        session = Session(
            id="S015",
            type="session",
            status="active",
            real_started_at="2026-08-28T18:00:00Z",
            world_tick_start=15742000,
            revision=1,
        )
        assert session.world_tick_end is None


# ── processed ──────────────────────────────────────────────────────────────


class TestProcessed:
    def test_default_is_false(self) -> None:
        session = Session(
            id="S015",
            type="session",
            status="active",
            real_started_at="2026-08-28T18:00:00Z",
            world_tick_start=15742000,
            revision=1,
        )
        assert session.processed is False

    def test_accepts_true(self) -> None:
        session = _make(processed=True)
        assert session.processed is True

    def test_accepts_false(self) -> None:
        session = _make(processed=False)
        assert session.processed is False

    def test_rejects_string_true(self) -> None:
        with pytest.raises(ValidationError):
            _make(processed="true")  # type: ignore[arg-type]

    def test_rejects_string_false(self) -> None:
        with pytest.raises(ValidationError):
            _make(processed="false")  # type: ignore[arg-type]

    def test_rejects_integer_one(self) -> None:
        with pytest.raises(ValidationError):
            _make(processed=1)  # type: ignore[arg-type]

    def test_rejects_integer_zero(self) -> None:
        with pytest.raises(ValidationError):
            _make(processed=0)  # type: ignore[arg-type]


# ── processed_model_profile ────────────────────────────────────────────────


class TestProcessedModelProfile:
    def test_default_is_none(self) -> None:
        session = Session(
            id="S015",
            type="session",
            status="active",
            real_started_at="2026-08-28T18:00:00Z",
            world_tick_start=15742000,
            revision=1,
        )
        assert session.processed_model_profile is None

    def test_accepts_post_session(self) -> None:
        session = _make(processed_model_profile="post_session")
        assert session.processed_model_profile == "post_session"

    def test_accepts_unicode(self) -> None:
        session = _make(
            processed_model_profile="\u043f\u043e\u0441\u0442\u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430"
        )
        assert (
            session.processed_model_profile
            == "\u043f\u043e\u0441\u0442\u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430"
        )

    def test_accepts_none(self) -> None:
        session = _make(processed_model_profile=None)
        assert session.processed_model_profile is None

    @pytest.mark.parametrize(
        "invalid_value",
        [
            "",
            " ",
            " profile",
            "profile ",
            " profile ",
            "\t",
            "\n",
        ],
    )
    def test_rejects_invalid_values(self, invalid_value: str) -> None:
        with pytest.raises(ValidationError):
            _make(processed_model_profile=invalid_value)

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(processed_model_profile="post_\x00session")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(processed_model_profile=123)  # type: ignore[arg-type]


# ── revision ───────────────────────────────────────────────────────────────


class TestRevision:
    @pytest.mark.parametrize("valid_revision", [1, 2, 100, 999])
    def test_accepts_valid_revisions(self, valid_revision: int) -> None:
        session = _make(revision=valid_revision)
        assert session.revision == valid_revision

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


# ── extra fields ───────────────────────────────────────────────────────────


class TestExtraFields:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            Session(  # type: ignore[call-arg]
                **_CANONICAL_KWARGS,
                unknown_field="test",
            )


# ── serialisation ──────────────────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_python(self) -> None:
        session = _make()
        dumped = session.model_dump()
        assert dumped["id"] == "S014"
        assert dumped["type"] == "session"
        assert dumped["status"] == "completed"
        assert dumped["world_tick_start"] == 15739200
        assert dumped["world_tick_end"] == 15741120
        assert dumped["processed"] is True
        assert dumped["processed_model_profile"] == "post_session"
        assert dumped["revision"] == 2
        assert dumped["schema_version"] == 1
        assert isinstance(dumped["real_started_at"], datetime)
        assert isinstance(dumped["real_finished_at"], datetime)

    def test_model_dump_json(self) -> None:
        session = _make()
        dumped = session.model_dump(mode="json")
        assert dumped["id"] == "S014"
        assert dumped["type"] == "session"
        assert dumped["status"] == "completed"
        assert dumped["world_tick_start"] == 15739200
        assert dumped["world_tick_end"] == 15741120
        assert dumped["processed"] is True
        assert dumped["processed_model_profile"] == "post_session"
        assert dumped["revision"] == 2
        assert dumped["schema_version"] == 1
        assert isinstance(dumped["real_started_at"], str)
        assert isinstance(dumped["real_finished_at"], str)

    def test_round_trip(self) -> None:
        session = _make()
        data = session.model_dump(mode="json")
        restored = Session.model_validate(data)
        assert restored.id == session.id
        assert restored.type == session.type
        assert restored.status == session.status
        assert restored.real_started_at == session.real_started_at
        assert restored.real_finished_at == session.real_finished_at
        assert restored.world_tick_start == session.world_tick_start
        assert restored.world_tick_end == session.world_tick_end
        assert restored.processed == session.processed
        assert restored.processed_model_profile == session.processed_model_profile
        assert restored.revision == session.revision
        assert restored.schema_version == session.schema_version


# ── domain import smoke test ────────────────────────────────────────────────


def test_session_module_importable() -> None:
    """Verify the session module can be imported without pulling in upper layers."""
    import dnd_assistant.domain.session  # noqa: F401
