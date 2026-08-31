"""Unit tests for S4-02 calendar time arithmetic.

Covers advance_world_time and time_until in DeterministicCalendarService.
"""

from __future__ import annotations

import pytest

from dnd_assistant.domain import (
    CalendarDefinition,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
    IntercalaryDay,
)

# ── Shared calendar fixtures ────────────────────────────────────────────────

_3M = (
    CalendarMonth(name="First", days=30),
    CalendarMonth(name="Second", days=30),
    CalendarMonth(name="Third", days=30),
)
_VAR = (
    CalendarMonth(name="A", days=3),
    CalendarMonth(name="B", days=5),
    CalendarMonth(name="C", days=2),
)


def _g() -> DeterministicCalendarService:
    return DeterministicCalendarService(
        CalendarDefinition(
            calendar_id="g",
            months=_3M,
            epoch=GameDate(year=1, month="First", day=1),
        )
    )


def _ic() -> DeterministicCalendarService:
    return DeterministicCalendarService(
        CalendarDefinition(
            calendar_id="ic",
            months=_3M,
            intercalary_days=(IntercalaryDay(name="Festival", after_month="First"),),
            epoch=GameDate(year=1, month="First", day=1),
        )
    )


def _ct() -> DeterministicCalendarService:
    return DeterministicCalendarService(
        CalendarDefinition(
            calendar_id="ct",
            months=(CalendarMonth(name="M", days=10),),
            hours_per_day=10,
            minutes_per_hour=100,
            epoch=GameDate(year=1, month="M", day=1),
        )
    )


# =============================================================================
# Calendar-boundary integration tests
# Uses S4-01 conversion to verify arithmetic through calendar boundaries.
# =============================================================================


class TestBoundaryIntegration:
    """Advance by 1 minute across each calendar boundary and verify the
    resulting GameDate via tick_to_date."""

    def test_hour_boundary(self) -> None:
        svc = _g()
        before = GameDate(year=1, month="First", day=1, hour=4, minute=59)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, month="First", day=1, hour=5, minute=0)

    def test_day_boundary(self) -> None:
        svc = _g()
        before = GameDate(year=1, month="First", day=1, hour=23, minute=59)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, month="First", day=2)

    def test_month_boundary(self) -> None:
        svc = _g()
        before = GameDate(year=1, month="First", day=30, hour=23, minute=59)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, month="Second", day=1)

    def test_intercalary_entry(self) -> None:
        svc = _ic()
        before = GameDate(year=1, month="First", day=30, hour=23, minute=59)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, intercalary_day="Festival")

    def test_intercalary_exit(self) -> None:
        svc = _ic()
        before = GameDate(year=1, intercalary_day="Festival", hour=23, minute=59)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, month="Second", day=1)

    def test_year_boundary(self) -> None:
        svc = _g()
        before = GameDate(year=1, month="Third", day=30, hour=23, minute=59)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=2, month="First", day=1)

    def test_custom_clock_hour_boundary(self) -> None:
        svc = _ct()
        before = GameDate(year=1, month="M", day=1, hour=4, minute=99)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, month="M", day=1, hour=5, minute=0)

    def test_custom_clock_day_boundary(self) -> None:
        svc = _ct()
        before = GameDate(year=1, month="M", day=1, hour=9, minute=99)
        tick = svc.date_to_tick(before)
        after_tick = svc.advance_world_time(tick, minutes=1)
        after = svc.tick_to_date(after_tick)
        assert after == GameDate(year=1, month="M", day=2)


# =============================================================================
# Invalid-input tests
# =============================================================================


class TestAdvanceInvalidInput:
    def test_current_tick_bool_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.advance_world_time(True, minutes=10)  # type: ignore[arg-type]

    def test_current_tick_str_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.advance_world_time("100", minutes=10)  # type: ignore[arg-type]

    def test_current_tick_float_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.advance_world_time(100.0, minutes=10)  # type: ignore[arg-type]

    def test_minutes_bool_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="minutes must not be a bool"):
            svc.advance_world_time(100, minutes=True)  # type: ignore[arg-type]

    def test_minutes_str_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="minutes must be an int"):
            svc.advance_world_time(100, minutes="10")  # type: ignore[arg-type]

    def test_minutes_float_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="minutes must be an int"):
            svc.advance_world_time(100, minutes=10.0)  # type: ignore[arg-type]

    def test_minutes_none_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="minutes must be an int"):
            svc.advance_world_time(100, minutes=None)  # type: ignore[arg-type]


class TestTimeUntilInvalidInput:
    def test_start_tick_bool_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.time_until(True, 100)  # type: ignore[arg-type]

    def test_start_tick_str_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.time_until("100", 100)  # type: ignore[arg-type]

    def test_end_tick_bool_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.time_until(100, True)  # type: ignore[arg-type]

    def test_end_tick_str_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.time_until(100, "100")  # type: ignore[arg-type]

    def test_end_tick_float_rejected(self) -> None:
        svc = _g()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.time_until(100, 100.0)  # type: ignore[arg-type]


# =============================================================================
# Protocol compatibility
# =============================================================================


class TestProtocolCompatibility:
    def test_deterministic_service_is_calendar_service(self) -> None:
        from dnd_assistant.domain import CalendarService

        svc = _g()
        assert isinstance(svc, CalendarService), (
            "DeterministicCalendarService must satisfy CalendarService Protocol"
        )


# =============================================================================
# advance_world_time — positive, zero, negative
# =============================================================================


class TestAdvancePositive:
    def test_advance_positive(self) -> None:
        svc = _g()
        assert svc.advance_world_time(100, minutes=10) == 110

    def test_advance_zero(self) -> None:
        svc = _g()
        assert svc.advance_world_time(100, minutes=0) == 100

    def test_advance_negative(self) -> None:
        svc = _g()
        assert svc.advance_world_time(100, minutes=-10) == 90


class TestAdvanceNegativeCurrentTick:
    def test_negative_tick_positive_minutes(self) -> None:
        svc = _g()
        assert svc.advance_world_time(-100, minutes=10) == -90

    def test_negative_tick_negative_minutes(self) -> None:
        svc = _g()
        assert svc.advance_world_time(-100, minutes=-10) == -110


class TestAdvanceCrossZero:
    def test_neg1_plus_1_equals_0(self) -> None:
        svc = _g()
        assert svc.advance_world_time(-1, minutes=1) == 0

    def test_0_minus_1_equals_neg1(self) -> None:
        svc = _g()
        assert svc.advance_world_time(0, minutes=-1) == -1


class TestAdvanceLargeValues:
    def test_large_positive(self) -> None:
        svc = _g()
        result = svc.advance_world_time(10**12, minutes=10**12)
        assert result == 2 * 10**12

    def test_large_negative(self) -> None:
        svc = _g()
        result = svc.advance_world_time(-(10**12), minutes=-(10**12))
        assert result == -(2 * 10**12)

    def test_large_mixed(self) -> None:
        svc = _g()
        result = svc.advance_world_time(10**12, minutes=-(10**12))
        assert result == 0


# =============================================================================
# time_until — signed difference
# =============================================================================


class TestTimeUntilFuture:
    def test_future(self) -> None:
        svc = _g()
        assert svc.time_until(100, 110) == 10


class TestTimeUntilSame:
    def test_same(self) -> None:
        svc = _g()
        assert svc.time_until(100, 100) == 0


class TestTimeUntilPast:
    def test_past(self) -> None:
        svc = _g()
        assert svc.time_until(110, 100) == -10


class TestTimeUntilNegativeTicks:
    def test_both_negative_future(self) -> None:
        svc = _g()
        assert svc.time_until(-110, -100) == 10

    def test_both_negative_past(self) -> None:
        svc = _g()
        assert svc.time_until(-100, -110) == -10

    def test_cross_zero_positive(self) -> None:
        svc = _g()
        assert svc.time_until(-10, 10) == 20

    def test_cross_zero_negative(self) -> None:
        svc = _g()
        assert svc.time_until(10, -10) == -20


# =============================================================================
# Inverse arithmetic property — deterministic examples
# =============================================================================


class TestInverseArithmetic:
    @pytest.mark.parametrize(
        ("tick", "delta"),
        [
            (0, 10),
            (100, 50),
            (100, -50),
            (-100, 30),
            (-100, -30),
            (0, 0),
            (10**9, 10**9),
            (-(10**9), -(10**9)),
        ],
    )
    def test_advance_then_time_until_equals_delta(self, tick: int, delta: int) -> None:
        svc = _g()
        advanced = svc.advance_world_time(tick, minutes=delta)
        assert svc.time_until(tick, advanced) == delta

    @pytest.mark.parametrize(
        ("tick", "delta"),
        [
            (0, 10),
            (100, 50),
            (100, -50),
            (-100, 30),
            (-100, -30),
            (0, 0),
            (10**9, 10**9),
            (-(10**9), -(10**9)),
        ],
    )
    def test_reverse_advance_returns_to_original(self, tick: int, delta: int) -> None:
        svc = _g()
        advanced = svc.advance_world_time(tick, minutes=delta)
        assert svc.advance_world_time(advanced, minutes=-delta) == tick
