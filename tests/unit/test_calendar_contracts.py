"""Unit tests for S4-00 calendar domain contracts.

Covers WorldTick, CalendarMonth, IntercalaryDay, CalendarHoliday,
GameDate, CalendarDefinition, CalendarService Protocol, and Stage-2
compatibility.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import (
    CalendarDefinition,
    CalendarHoliday,
    CalendarMonth,
    CalendarService,
    GameDate,
    IntercalaryDay,
    Session,
    TemporalCertainty,
    TimelineEvent,
    WorldTick,
)
from dnd_assistant.domain.types import Visibility


@pytest.fixture(autouse=True)
def _restore_dnd_assistant_modules() -> Iterator[None]:
    """Restore dnd_assistant module identity after clean-import tests."""
    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "dnd_assistant" or name.startswith("dnd_assistant.")
    }
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "dnd_assistant" or name.startswith("dnd_assistant."):
                del sys.modules[name]
        sys.modules.update(original)


# =============================================================================
# WorldTick
# =============================================================================


class TestWorldTick:
    """WorldTick is a strict signed integer minute scalar."""

    @pytest.mark.parametrize("valid_tick", [0, 1, 15739200, -1, -100])
    def test_accepts_integers(self, valid_tick: int) -> None:
        assert valid_tick == valid_tick  # WorldTick is just int

    @pytest.mark.parametrize("invalid_value", [True, False])
    def test_rejects_bool(self, invalid_value: bool) -> None:
        with pytest.raises(ValidationError):
            _validate_world_tick_via_model(invalid_value)

    def test_rejects_str(self) -> None:
        with pytest.raises(ValidationError):
            _validate_world_tick_via_model("123")

    def test_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            _validate_world_tick_via_model(1.0)


def _validate_world_tick_via_model(value: object) -> None:
    """Use a minimal model to validate a WorldTick value."""
    from pydantic import BaseModel, Field

    class _TickModel(BaseModel):
        tick: WorldTick = Field(strict=True)

    _TickModel(tick=value)  # type: ignore[arg-type]


# =============================================================================
# CalendarMonth
# =============================================================================


class TestCalendarMonth:
    def test_valid(self) -> None:
        m = CalendarMonth(name="Hammer", days=30)
        assert m.name == "Hammer"
        assert m.days == 30

    def test_unicode(self) -> None:
        m = CalendarMonth(name="Первый Туман", days=29)
        assert m.name == "Первый Туман"

    def test_days_one(self) -> None:
        m = CalendarMonth(name="OneDay", days=1)
        assert m.days == 1

    def test_days_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="days must be >= 1"):
            CalendarMonth(name="Bad", days=0)

    def test_days_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="days must be >= 1"):
            CalendarMonth(name="Bad", days=-1)

    def test_days_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name="Bad", days=True)  # type: ignore[arg-type]

    def test_days_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name="Bad", days="30")  # type: ignore[arg-type]

    def test_name_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name="", days=30)

    def test_name_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name="  ", days=30)

    def test_name_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name=" Hammer", days=30)

    def test_name_trailing_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name="Hammer ", days=30)

    def test_name_non_printable_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name="Ham\x00mer", days=30)

    def test_name_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarMonth(name=True, days=30)  # type: ignore[arg-type]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalendarMonth(name="Hammer", days=30, unknown="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        m = CalendarMonth(name="Hammer", days=30)
        with pytest.raises(ValidationError):
            m.name = "Eleasis"  # type: ignore[misc]


# =============================================================================
# IntercalaryDay
# =============================================================================


class TestIntercalaryDay:
    def test_valid(self) -> None:
        d = IntercalaryDay(name="Midwinter", after_month="Hammer")
        assert d.name == "Midwinter"
        assert d.after_month == "Hammer"

    def test_unicode(self) -> None:
        d = IntercalaryDay(name="Праздник", after_month="Первый Туман")
        assert d.name == "Праздник"

    def test_name_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IntercalaryDay(name="", after_month="Hammer")

    def test_name_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IntercalaryDay(name="  ", after_month="Hammer")

    def test_after_month_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IntercalaryDay(name="Midwinter", after_month="")

    def test_after_month_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IntercalaryDay(name="Midwinter", after_month="  ")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            IntercalaryDay(name="Midwinter", after_month="Hammer", unknown="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        d = IntercalaryDay(name="Midwinter", after_month="Hammer")
        with pytest.raises(ValidationError):
            d.name = "Shieldmeet"  # type: ignore[misc]


# =============================================================================
# CalendarHoliday
# =============================================================================


class TestCalendarHoliday:
    def test_regular_holiday(self) -> None:
        h = CalendarHoliday(name="Midwinter", month="Hammer", day=1)
        assert h.name == "Midwinter"
        assert h.month == "Hammer"
        assert h.day == 1
        assert h.intercalary_day is None

    def test_intercalary_holiday(self) -> None:
        h = CalendarHoliday(name="Shieldmeet", intercalary_day="Shieldmeet")
        assert h.name == "Shieldmeet"
        assert h.month is None
        assert h.day is None
        assert h.intercalary_day == "Shieldmeet"

    def test_month_without_day_rejected(self) -> None:
        with pytest.raises(ValidationError, match="day is required when month is set"):
            CalendarHoliday(name="Bad", month="Hammer")

    def test_day_without_month_rejected(self) -> None:
        with pytest.raises(ValidationError, match="month is required when day is set"):
            CalendarHoliday(name="Bad", day=1)

    def test_both_forms_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not both be set"):
            CalendarHoliday(name="Bad", month="Hammer", day=1, intercalary_day="Shieldmeet")

    def test_no_form_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one target form required"):
            CalendarHoliday(name="Bad")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalendarHoliday(name="Test", month="Hammer", day=1, unknown="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        h = CalendarHoliday(name="Test", month="Hammer", day=1)
        with pytest.raises(ValidationError):
            h.name = "Changed"  # type: ignore[misc]


# =============================================================================
# GameDate
# =============================================================================


class TestGameDate:
    def test_regular_date(self) -> None:
        d = GameDate(year=1492, month="Hammer", day=1, hour=0, minute=0)
        assert d.year == 1492
        assert d.month == "Hammer"
        assert d.day == 1
        assert d.intercalary_day is None
        assert d.hour == 0
        assert d.minute == 0

    def test_intercalary_date(self) -> None:
        d = GameDate(year=1492, intercalary_day="Midwinter", hour=12, minute=30)
        assert d.year == 1492
        assert d.month is None
        assert d.day is None
        assert d.intercalary_day == "Midwinter"
        assert d.hour == 12
        assert d.minute == 30

    def test_year_zero_accepted(self) -> None:
        d = GameDate(year=0, month="Hammer", day=1)
        assert d.year == 0

    def test_year_negative_accepted(self) -> None:
        d = GameDate(year=-100, month="Hammer", day=1)
        assert d.year == -100

    def test_year_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GameDate(year=True, month="Hammer", day=1)  # type: ignore[arg-type]

    def test_missing_day_rejected(self) -> None:
        with pytest.raises(ValidationError, match="day is required when month is set"):
            GameDate(year=1492, month="Hammer")

    def test_month_without_day_rejected(self) -> None:
        with pytest.raises(ValidationError, match="day is required when month is set"):
            GameDate(year=1492, month="Hammer", day=None)

    def test_day_without_month_rejected(self) -> None:
        with pytest.raises(ValidationError, match="month is required when day is set"):
            GameDate(year=1492, day=1)

    def test_month_and_intercalary_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be combined"):
            GameDate(year=1492, month="Hammer", day=1, intercalary_day="Midwinter")

    def test_intercalary_and_day_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be combined"):
            GameDate(year=1492, intercalary_day="Midwinter", day=1)

    def test_negative_day_rejected(self) -> None:
        with pytest.raises(ValidationError, match="day must be >= 1"):
            GameDate(year=1492, month="Hammer", day=-1)

    def test_negative_hour_rejected(self) -> None:
        with pytest.raises(ValidationError, match="hour must be >= 0"):
            GameDate(year=1492, month="Hammer", day=1, hour=-1)

    def test_negative_minute_rejected(self) -> None:
        with pytest.raises(ValidationError, match="minute must be >= 0"):
            GameDate(year=1492, month="Hammer", day=1, minute=-1)

    def test_hour_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GameDate(year=1492, month="Hammer", day=1, hour=True)  # type: ignore[arg-type]

    def test_minute_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GameDate(year=1492, month="Hammer", day=1, minute=True)  # type: ignore[arg-type]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            GameDate(year=1492, month="Hammer", day=1, unknown="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        d = GameDate(year=1492, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            d.year = 1500  # type: ignore[misc]


# =============================================================================
# CalendarDefinition
# =============================================================================


class TestCalendarDefinition:
    _MINIMAL_MONTHS = (CalendarMonth(name="Hammer", days=30),)

    def test_minimal_one_month(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="Hammer", day=1),
            months=self._MINIMAL_MONTHS,
        )
        assert cal.schema_version == 1
        assert cal.calendar_id == "test"
        assert cal.hours_per_day == 24
        assert cal.minutes_per_hour == 60

    def test_different_month_lengths(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="A", day=1),
            months=(
                CalendarMonth(name="A", days=30),
                CalendarMonth(name="B", days=31),
                CalendarMonth(name="C", days=28),
            ),
        )
        assert len(cal.months) == 3

    def test_unicode_names(self) -> None:
        cal = CalendarDefinition(
            calendar_id="тест",
            epoch=GameDate(year=1, month="Первый", day=1),
            months=(CalendarMonth(name="Первый", days=30),),
        )
        assert cal.calendar_id == "тест"

    def test_intercalary_day(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="Hammer", day=1),
            months=self._MINIMAL_MONTHS,
            intercalary_days=(IntercalaryDay(name="Midwinter", after_month="Hammer"),),
        )
        assert len(cal.intercalary_days) == 1

    def test_holiday(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="Hammer", day=1),
            months=self._MINIMAL_MONTHS,
            holidays=(CalendarHoliday(name="New Year", month="Hammer", day=1),),
        )
        assert len(cal.holidays) == 1

    def test_custom_hours_per_day(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="Hammer", day=1),
            months=self._MINIMAL_MONTHS,
            hours_per_day=10,
        )
        assert cal.hours_per_day == 10

    def test_custom_minutes_per_hour(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="Hammer", day=1),
            months=self._MINIMAL_MONTHS,
            minutes_per_hour=100,
        )
        assert cal.minutes_per_hour == 100

    def test_duplicate_month_names_rejected(self) -> None:
        with pytest.raises(ValidationError, match="month names must be unique"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=(
                    CalendarMonth(name="Hammer", days=30),
                    CalendarMonth(name="Hammer", days=31),
                ),
            )

    def test_casefold_duplicate_month_names_rejected(self) -> None:
        with pytest.raises(ValidationError, match="month names must be unique"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=(
                    CalendarMonth(name="Hammer", days=30),
                    CalendarMonth(name="hammer", days=31),
                ),
            )

    def test_duplicate_intercalary_names_rejected(self) -> None:
        with pytest.raises(ValidationError, match="intercalary day names must be unique"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                intercalary_days=(
                    IntercalaryDay(name="Midwinter", after_month="Hammer"),
                    IntercalaryDay(name="Midwinter", after_month="Hammer"),
                ),
            )

    def test_month_intercalary_collision_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="month and intercalary day names must not collide"
        ):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                intercalary_days=(IntercalaryDay(name="Hammer", after_month="Hammer"),),
            )

    def test_unknown_after_month_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not match any declared month"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                intercalary_days=(IntercalaryDay(name="Midwinter", after_month="Nonexistent"),),
            )

    def test_invalid_epoch_month_rejected(self) -> None:
        with pytest.raises(ValidationError, match="epoch month.*does not match"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="BadMonth", day=1),
                months=self._MINIMAL_MONTHS,
            )

    def test_epoch_day_outside_month_rejected(self) -> None:
        with pytest.raises(ValidationError, match="epoch day.*exceeds month"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=31),
                months=self._MINIMAL_MONTHS,
            )

    def test_invalid_epoch_time_hour_rejected(self) -> None:
        with pytest.raises(ValidationError, match="epoch"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1, hour=24),
                months=self._MINIMAL_MONTHS,
                hours_per_day=24,
            )

    def test_invalid_epoch_time_minute_rejected(self) -> None:
        with pytest.raises(ValidationError, match="epoch"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1, minute=60),
                months=self._MINIMAL_MONTHS,
                minutes_per_hour=60,
            )

    def test_invalid_holiday_month_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Holiday month.*does not match"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                holidays=(CalendarHoliday(name="Bad", month="Nonexistent", day=1),),
            )

    def test_invalid_holiday_day_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Holiday day.*out of range"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                holidays=(CalendarHoliday(name="Bad", month="Hammer", day=31),),
            )

    def test_invalid_holiday_intercalary_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not match any declared intercalary day"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                holidays=(CalendarHoliday(name="Bad", intercalary_day="Nonexistent"),),
            )

    def test_empty_months_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one month"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=(),
            )

    def test_hours_per_day_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                hours_per_day=True,
            )

    def test_minutes_per_hour_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                minutes_per_hour=True,
            )

    def test_hours_per_day_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="hours_per_day must be >= 1"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                hours_per_day=0,
            )

    def test_minutes_per_hour_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="minutes_per_hour must be >= 1"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                minutes_per_hour=0,
            )

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalendarDefinition(
                calendar_id="test",
                epoch=GameDate(year=1, month="Hammer", day=1),
                months=self._MINIMAL_MONTHS,
                unknown="x",
            )

    def test_frozen(self) -> None:
        cal = CalendarDefinition(
            calendar_id="test",
            epoch=GameDate(year=1, month="Hammer", day=1),
            months=self._MINIMAL_MONTHS,
        )
        with pytest.raises(ValidationError):
            cal.calendar_id = "changed"


# =============================================================================
# CalendarService Protocol
# =============================================================================


class TestCalendarServiceProtocol:
    def test_is_protocol(self) -> None:
        assert isinstance(CalendarService, type)

    def test_runtime_checkable(self) -> None:
        """Protocol is decorated with @runtime_checkable."""
        import typing

        assert issubclass(CalendarService, typing.Protocol)

    def test_required_methods_exist(self) -> None:
        methods = [
            "date_to_tick",
            "tick_to_date",
            "advance_world_time",
            "time_until",
            "events_between",
            "events_near",
            "upcoming",
            "overdue_events",
            "time_until_event",
        ]
        for name in methods:
            assert hasattr(CalendarService, name), f"CalendarService missing {name}"

    def test_definition_property(self) -> None:
        assert hasattr(CalendarService, "definition")

    def test_event_query_methods_exist(self) -> None:
        s4_03 = [
            "events_between",
            "events_near",
            "upcoming",
            "overdue_events",
            "time_until_event",
        ]
        for name in s4_03:
            assert hasattr(CalendarService, name), f"CalendarService missing {name} in S4-03"


# =============================================================================
# Stage-2 compatibility
# =============================================================================


class TestStage2Compatibility:
    def test_session_world_tick_start_serializes_as_int(self) -> None:
        from datetime import UTC, datetime

        s = Session(
            id="S100",
            type="session",
            status="completed",
            real_started_at=datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC),
            world_tick_start=15739200,
            revision=1,
        )
        dumped = s.model_dump(mode="json")
        assert dumped["world_tick_start"] == 15739200
        assert isinstance(dumped["world_tick_start"], int)

    def test_session_world_tick_end_serializes_as_int(self) -> None:
        from datetime import UTC, datetime

        s = Session(
            id="S100",
            type="session",
            status="completed",
            real_started_at=datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC),
            real_finished_at=datetime(2026, 8, 27, 21, 20, 0, tzinfo=UTC),
            world_tick_start=15739200,
            world_tick_end=15741120,
            revision=1,
        )
        dumped = s.model_dump(mode="json")
        assert dumped["world_tick_end"] == 15741120
        assert isinstance(dumped["world_tick_end"], int)

    def test_session_negative_tick_still_accepted(self) -> None:
        from datetime import UTC, datetime

        s = Session(
            id="S100",
            type="session",
            status="completed",
            real_started_at=datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC),
            world_tick_start=-100,
            revision=1,
        )
        assert s.world_tick_start == -100

    def test_session_bool_tick_rejected(self) -> None:
        from datetime import UTC, datetime

        with pytest.raises(ValidationError):
            Session(
                id="S100",
                type="session",
                status="completed",
                real_started_at=datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC),
                world_tick_start=True,
                revision=1,
            )

    def test_session_string_tick_rejected(self) -> None:
        from datetime import UTC, datetime

        with pytest.raises(ValidationError):
            Session(
                id="S100",
                type="session",
                status="completed",
                real_started_at=datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC),
                world_tick_start="123",
                revision=1,
            )

    def test_timeline_event_world_tick_serializes_as_int(self) -> None:
        event = TimelineEvent(
            id="evt_001",
            type="timeline_event",
            name="Test Event",
            status="historical",
            certainty=TemporalCertainty.EXACT,
            importance="minor",
            world_tick=15739200,
            visibility=Visibility.PLAYER,
            revision=1,
        )
        dumped = event.model_dump(mode="json")
        assert dumped["world_tick"] == 15739200
        assert isinstance(dumped["world_tick"], int)

    def test_timeline_event_negative_tick_still_accepted(self) -> None:
        event = TimelineEvent(
            id="evt_001",
            type="timeline_event",
            name="Test Event",
            status="historical",
            certainty=TemporalCertainty.EXACT,
            importance="minor",
            world_tick=-100,
            visibility=Visibility.PLAYER,
            revision=1,
        )
        assert event.world_tick == -100

    def test_timeline_event_bool_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEvent(
                id="evt_001",
                type="timeline_event",
                name="Test Event",
                status="historical",
                certainty=TemporalCertainty.EXACT,
                importance="minor",
                world_tick=True,
                visibility=Visibility.PLAYER,
                revision=1,
            )

    def test_timeline_event_string_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEvent(
                id="evt_001",
                type="timeline_event",
                name="Test Event",
                status="historical",
                certainty=TemporalCertainty.EXACT,
                importance="minor",
                world_tick="123",
                visibility=Visibility.PLAYER,
                revision=1,
            )

    def test_timeline_event_tick_min_serializes_as_int(self) -> None:
        event = TimelineEvent(
            id="evt_001",
            type="timeline_event",
            name="Test Event",
            status="historical",
            certainty=TemporalCertainty.APPROXIMATE,
            importance="minor",
            world_tick=None,
            world_tick_min=15739000,
            world_tick_max=15740000,
            visibility=Visibility.PLAYER,
            revision=1,
        )
        dumped = event.model_dump(mode="json")
        assert dumped["world_tick_min"] == 15739000
        assert isinstance(dumped["world_tick_min"], int)

    def test_timeline_event_tick_max_serializes_as_int(self) -> None:
        event = TimelineEvent(
            id="evt_001",
            type="timeline_event",
            name="Test Event",
            status="historical",
            certainty=TemporalCertainty.RANGE,
            importance="minor",
            world_tick=None,
            world_tick_min=15739000,
            world_tick_max=15741000,
            visibility=Visibility.PLAYER,
            revision=1,
        )
        dumped = event.model_dump(mode="json")
        assert dumped["world_tick_max"] == 15741000
        assert isinstance(dumped["world_tick_max"], int)


# =============================================================================
# Import boundary
# =============================================================================


class TestImportBoundaries:
    def test_calendar_module_importable(self) -> None:
        import dnd_assistant.domain.calendar  # noqa: F401

    def test_calendar_no_storage_import(self) -> None:
        import importlib
        import sys

        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        importlib.import_module("dnd_assistant.domain.calendar")
        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.storage")}
        assert not mod_names, f"domain.calendar imported storage: {mod_names}"

    def test_calendar_no_models_import(self) -> None:
        import importlib
        import sys

        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        importlib.import_module("dnd_assistant.domain.calendar")
        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
        assert not mod_names, f"domain.calendar imported models: {mod_names}"
