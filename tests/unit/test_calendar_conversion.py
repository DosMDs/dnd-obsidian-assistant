"""Unit tests for S4-01 deterministic GameDate -> WorldTick conversion."""

from __future__ import annotations

import pytest

from dnd_assistant.domain import (
    CalendarDefinition,
    CalendarHoliday,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
    IntercalaryDay,
)

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


def _g() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="g", months=_3M, epoch=GameDate(year=1, month="First", day=1)
    )


def _v() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="v", months=_VAR, epoch=GameDate(year=1, month="A", day=1)
    )


def _ic() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="ic",
        months=_3M,
        intercalary_days=(IntercalaryDay(name="Festival", after_month="First"),),
        epoch=GameDate(year=1, month="First", day=1),
    )


def _mic() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="mic",
        months=_3M,
        intercalary_days=(
            IntercalaryDay(name="FestA", after_month="First"),
            IntercalaryDay(name="FestB", after_month="First"),
        ),
        epoch=GameDate(year=1, month="First", day=1),
    )


def _ct() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="ct",
        months=(CalendarMonth(name="M", days=10),),
        hours_per_day=10,
        minutes_per_hour=100,
        epoch=GameDate(year=1, month="M", day=1),
    )


# 1-2. Epoch <-> zero
class TestEpoch:
    def test_epoch_to_zero(self) -> None:
        assert (
            DeterministicCalendarService(_g()).date_to_tick(GameDate(year=1, month="First", day=1))
            == 0
        )

    def test_zero_to_epoch(self) -> None:
        assert DeterministicCalendarService(_g()).tick_to_date(0) == GameDate(
            year=1, month="First", day=1
        )

    def test_intercalary_epoch_to_zero(self) -> None:
        cal = CalendarDefinition(
            calendar_id="ice",
            months=_3M,
            intercalary_days=(IntercalaryDay(name="Festival", after_month="First"),),
            epoch=GameDate(year=1, intercalary_day="Festival"),
        )
        assert (
            DeterministicCalendarService(cal).date_to_tick(
                GameDate(year=1, intercalary_day="Festival")
            )
            == 0
        )

    def test_zero_to_intercalary_epoch(self) -> None:
        cal = CalendarDefinition(
            calendar_id="ice",
            months=_3M,
            intercalary_days=(IntercalaryDay(name="Festival", after_month="First"),),
            epoch=GameDate(year=1, intercalary_day="Festival"),
        )
        assert DeterministicCalendarService(cal).tick_to_date(0) == GameDate(
            year=1, intercalary_day="Festival"
        )


# 3. Non-midnight epoch
class TestNonMidnightEpoch:
    def test_non_midnight_epoch(self) -> None:
        cal = CalendarDefinition(
            calendar_id="nm",
            months=_3M,
            epoch=GameDate(year=1492, month="First", day=10, hour=13, minute=17),
        )
        svc = DeterministicCalendarService(cal)
        assert svc.date_to_tick(GameDate(year=1492, month="First", day=10, hour=13, minute=17)) == 0
        assert svc.tick_to_date(0) == GameDate(year=1492, month="First", day=10, hour=13, minute=17)

    def test_one_minute_before(self) -> None:
        cal = CalendarDefinition(
            calendar_id="nm",
            months=_3M,
            epoch=GameDate(year=1492, month="First", day=10, hour=13, minute=17),
        )
        assert (
            DeterministicCalendarService(cal).date_to_tick(
                GameDate(year=1492, month="First", day=10, hour=13, minute=16)
            )
            == -1
        )

    def test_one_minute_after(self) -> None:
        cal = CalendarDefinition(
            calendar_id="nm",
            months=_3M,
            epoch=GameDate(year=1492, month="First", day=10, hour=13, minute=17),
        )
        assert (
            DeterministicCalendarService(cal).date_to_tick(
                GameDate(year=1492, month="First", day=10, hour=13, minute=18)
            )
            == 1
        )


# 4-7. Minute, hour, day, month boundaries
class TestBoundaries:
    def test_one_minute_after_epoch(self) -> None:
        svc = DeterministicCalendarService(_g())
        assert svc.date_to_tick(GameDate(year=1, month="First", day=1, minute=1)) == 1

    def test_one_minute_before_epoch(self) -> None:
        svc = DeterministicCalendarService(_g())
        assert svc.date_to_tick(GameDate(year=0, month="Third", day=30, hour=23, minute=59)) == -1

    def test_adjacent_minutes(self) -> None:
        svc = DeterministicCalendarService(_g())
        t0 = svc.date_to_tick(GameDate(year=5, month="Second", day=15, hour=10, minute=0))
        t1 = svc.date_to_tick(GameDate(year=5, month="Second", day=15, hour=10, minute=1))
        assert t1 - t0 == 1

    def test_hour_boundary(self) -> None:
        svc = DeterministicCalendarService(_g())
        before = svc.date_to_tick(GameDate(year=1, month="First", day=1, hour=4, minute=59))
        after = svc.date_to_tick(GameDate(year=1, month="First", day=1, hour=5, minute=0))
        assert after - before == 1

    def test_day_boundary(self) -> None:
        svc = DeterministicCalendarService(_g())
        before = svc.date_to_tick(GameDate(year=1, month="First", day=1, hour=23, minute=59))
        after = svc.date_to_tick(GameDate(year=1, month="First", day=2))
        assert after - before == 1

    def test_month_boundary(self) -> None:
        svc = DeterministicCalendarService(_g())
        before = svc.date_to_tick(GameDate(year=1, month="First", day=30, hour=23, minute=59))
        after = svc.date_to_tick(GameDate(year=1, month="Second", day=1))
        assert after - before == 1


# 8. Variable month lengths
class TestVariableMonthLengths:
    def test_month_a_offsets(self) -> None:
        svc = DeterministicCalendarService(_v())
        assert svc.date_to_tick(GameDate(year=1, month="A", day=1)) == 0
        assert svc.date_to_tick(GameDate(year=1, month="A", day=3)) == 2 * 1440

    def test_month_b_offsets(self) -> None:
        svc = DeterministicCalendarService(_v())
        assert svc.date_to_tick(GameDate(year=1, month="B", day=1)) == 3 * 1440

    def test_month_c_offsets(self) -> None:
        svc = DeterministicCalendarService(_v())
        assert svc.date_to_tick(GameDate(year=1, month="C", day=1)) == 8 * 1440

    def test_variable_year_total(self) -> None:
        svc = DeterministicCalendarService(_v())
        end = svc.date_to_tick(GameDate(year=1, month="C", day=2, hour=23, minute=59))
        nxt = svc.date_to_tick(GameDate(year=2, month="A", day=1))
        assert nxt - end == 1


# 9-10. Intercalary
class TestIntercalary:
    def test_intercalary_date_to_tick(self) -> None:
        svc = DeterministicCalendarService(_ic())
        assert svc.date_to_tick(GameDate(year=1, intercalary_day="Festival")) == 30 * 1440

    def test_after_month_last_day(self) -> None:
        svc = DeterministicCalendarService(_ic())
        last = svc.date_to_tick(GameDate(year=1, month="First", day=30, hour=23, minute=59))
        fest = svc.date_to_tick(GameDate(year=1, intercalary_day="Festival"))
        assert fest - last == 1

    def test_before_next_month(self) -> None:
        svc = DeterministicCalendarService(_ic())
        fest = svc.date_to_tick(GameDate(year=1, intercalary_day="Festival", hour=23, minute=59))
        nxt = svc.date_to_tick(GameDate(year=1, month="Second", day=1))
        assert nxt - fest == 1

    def test_consumes_full_day(self) -> None:
        svc = DeterministicCalendarService(_ic())
        s = svc.date_to_tick(GameDate(year=1, intercalary_day="Festival"))
        e = svc.date_to_tick(GameDate(year=1, intercalary_day="Festival", hour=23, minute=59))
        assert e - s == 1439

    def test_declaration_order_preserved(self) -> None:
        svc = DeterministicCalendarService(_mic())
        a = svc.date_to_tick(GameDate(year=1, intercalary_day="FestA"))
        b = svc.date_to_tick(GameDate(year=1, intercalary_day="FestB"))
        assert b - a == 1440

    def test_after_last_day_before_first_ic(self) -> None:
        svc = DeterministicCalendarService(_mic())
        last = svc.date_to_tick(GameDate(year=1, month="First", day=30, hour=23, minute=59))
        a = svc.date_to_tick(GameDate(year=1, intercalary_day="FestA"))
        assert a - last == 1

    def test_after_last_ic_before_next_month(self) -> None:
        svc = DeterministicCalendarService(_mic())
        b_end = svc.date_to_tick(GameDate(year=1, intercalary_day="FestB", hour=23, minute=59))
        nxt = svc.date_to_tick(GameDate(year=1, month="Second", day=1))
        assert nxt - b_end == 1


# 11-12. Year boundaries
class TestYearBoundaries:
    def test_year_boundary(self) -> None:
        svc = DeterministicCalendarService(_g())
        end = svc.date_to_tick(GameDate(year=1, month="Third", day=30, hour=23, minute=59))
        nxt = svc.date_to_tick(GameDate(year=2, month="First", day=1))
        assert nxt - end == 1

    def test_year_neg1_to_0(self) -> None:
        svc = DeterministicCalendarService(_g())
        end = svc.date_to_tick(GameDate(year=-1, month="Third", day=30, hour=23, minute=59))
        nxt = svc.date_to_tick(GameDate(year=0, month="First", day=1))
        assert nxt - end == 1

    def test_year_0_to_1(self) -> None:
        svc = DeterministicCalendarService(_g())
        end = svc.date_to_tick(GameDate(year=0, month="Third", day=30, hour=23, minute=59))
        nxt = svc.date_to_tick(GameDate(year=1, month="First", day=1))
        assert nxt - end == 1


# 13-15. Negative years, negative ticks, positive ticks
class TestSignedValues:
    def test_negative_year_regular(self) -> None:
        assert (
            DeterministicCalendarService(_g()).date_to_tick(
                GameDate(year=-100, month="First", day=1)
            )
            < 0
        )

    def test_negative_year_intercalary(self) -> None:
        assert (
            DeterministicCalendarService(_ic()).date_to_tick(
                GameDate(year=-50, intercalary_day="Festival")
            )
            < 0
        )

    def test_negative_year_round_trip(self) -> None:
        svc = DeterministicCalendarService(_g())
        d = GameDate(year=-10, month="Second", day=15, hour=6, minute=30)
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    @pytest.mark.parametrize("tick", [-1, -100, -10000, -1000000])
    def test_negative_tick_round_trip(self, tick: int) -> None:
        svc = DeterministicCalendarService(_g())
        assert svc.date_to_tick(svc.tick_to_date(tick)) == tick

    @pytest.mark.parametrize("tick", [1, 100, 10000, 1000000])
    def test_positive_tick_round_trip(self, tick: int) -> None:
        svc = DeterministicCalendarService(_g())
        assert svc.date_to_tick(svc.tick_to_date(tick)) == tick


# 16-17. Custom time units
class TestCustomTimeUnits:
    def test_custom_hours_adjacent_minutes(self) -> None:
        svc = DeterministicCalendarService(_ct())
        t0 = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=5, minute=50))
        t1 = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=5, minute=51))
        assert t1 - t0 == 1

    def test_custom_hours_day_boundary(self) -> None:
        svc = DeterministicCalendarService(_ct())
        before = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=9, minute=99))
        after = svc.date_to_tick(GameDate(year=1, month="M", day=2))
        assert after - before == 1

    def test_custom_minutes_hour_boundary(self) -> None:
        svc = DeterministicCalendarService(_ct())
        before = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=4, minute=99))
        after = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=5, minute=0))
        assert after - before == 1


# 18-23. Validation rejection
class TestValidation:
    def test_unknown_month_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="month.*does not match"):
            svc.date_to_tick(GameDate(year=1, month="Nonexistent", day=1))

    def test_day_overflow_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="exceeds month"):
            svc.date_to_tick(GameDate(year=1, month="First", day=31))

    def test_hour_overflow_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="hour"):
            svc.date_to_tick(GameDate(year=1, month="First", day=1, hour=24))

    def test_minute_overflow_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="minute"):
            svc.date_to_tick(GameDate(year=1, month="First", day=1, minute=60))

    def test_custom_hour_overflow_rejected(self) -> None:
        svc = DeterministicCalendarService(_ct())
        with pytest.raises(ValueError, match="hour"):
            svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=10))

    def test_custom_minute_overflow_rejected(self) -> None:
        svc = DeterministicCalendarService(_ct())
        with pytest.raises(ValueError, match="minute"):
            svc.date_to_tick(GameDate(year=1, month="M", day=1, minute=100))

    def test_unknown_intercalary_rejected(self) -> None:
        svc = DeterministicCalendarService(_ic())
        with pytest.raises(ValueError, match="intercalary_day.*does not match"):
            svc.date_to_tick(GameDate(year=1, intercalary_day="DoesNotExist"))


# S4-C01. tick_to_date WorldTick validation regression
class TestTickToDateValidation:
    """tick_to_date must reject non-int WorldTick values before arithmetic."""

    def test_tick_to_date_true_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.tick_to_date(True)  # type: ignore[arg-type]

    def test_tick_to_date_false_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.tick_to_date(False)  # type: ignore[arg-type]

    def test_tick_to_date_str_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.tick_to_date("1")  # type: ignore[arg-type]

    def test_tick_to_date_float_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.tick_to_date(1.0)  # type: ignore[arg-type]

    def test_tick_to_date_none_rejected(self) -> None:
        svc = DeterministicCalendarService(_g())
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.tick_to_date(None)  # type: ignore[arg-type]

    def test_tick_to_date_zero_accepted(self) -> None:
        svc = DeterministicCalendarService(_g())
        result = svc.tick_to_date(0)
        assert result == GameDate(year=1, month="First", day=1)

    def test_tick_to_date_negative_accepted(self) -> None:
        svc = DeterministicCalendarService(_g())
        result = svc.tick_to_date(-1440)
        assert result == GameDate(year=0, month="Third", day=30)

    def test_tick_to_date_positive_accepted(self) -> None:
        svc = DeterministicCalendarService(_g())
        result = svc.tick_to_date(1440)
        assert result == GameDate(year=1, month="First", day=2)


# 24. Invalid intercalary epoch regression (S4-00 defect)
class TestInvalidIntercalaryEpochRegression:
    def test_invalid_intercalary_epoch_rejected(self) -> None:
        with pytest.raises(ValueError, match="intercalary_day.*does not match"):
            CalendarDefinition(
                calendar_id="test",
                months=_3M,
                intercalary_days=(),
                epoch=GameDate(year=1, intercalary_day="DoesNotExist"),
            )


# 25. Holidays do not affect ticks
class TestHolidays:
    def test_holidays_do_not_change_ticks(self) -> None:
        svc_no = DeterministicCalendarService(_g())
        t_no = svc_no.date_to_tick(GameDate(year=1, month="First", day=15))
        cal = CalendarDefinition(
            calendar_id="h",
            months=_3M,
            epoch=GameDate(year=1, month="First", day=1),
            holidays=(CalendarHoliday(name="H", month="First", day=15),),
        )
        t_yes = DeterministicCalendarService(cal).date_to_tick(
            GameDate(year=1, month="First", day=15)
        )
        assert t_no == t_yes


# 26. Date round trips
class TestDateRoundTrips:
    @pytest.mark.parametrize(
        "date",
        [
            GameDate(year=1, month="First", day=1),
            GameDate(year=1, month="Second", day=15, hour=12, minute=30),
            GameDate(year=1, intercalary_day="Festival"),
            GameDate(year=-5, month="Third", day=30, hour=6, minute=0),
            GameDate(year=0, month="First", day=1),
            GameDate(year=100, month="Second", day=1),
            GameDate(year=-1000, month="First", day=1),
        ],
    )
    def test_date_round_trip(self, date: GameDate) -> None:
        svc = DeterministicCalendarService(_ic())
        assert svc.tick_to_date(svc.date_to_tick(date)) == date


# 27. Large signed year/tick regression
class TestLargeValues:
    def test_large_positive_year(self) -> None:
        svc = DeterministicCalendarService(_g())
        d = GameDate(year=100000, month="First", day=1)
        tick = svc.date_to_tick(d)
        assert svc.tick_to_date(tick) == d

    def test_large_negative_year(self) -> None:
        svc = DeterministicCalendarService(_g())
        d = GameDate(year=-100000, month="First", day=1)
        tick = svc.date_to_tick(d)
        assert svc.tick_to_date(tick) == d

    def test_large_positive_tick(self) -> None:
        svc = DeterministicCalendarService(_g())
        tick = 10**12
        d = svc.tick_to_date(tick)
        assert svc.date_to_tick(d) == tick

    def test_large_negative_tick(self) -> None:
        svc = DeterministicCalendarService(_g())
        tick = -(10**12)
        d = svc.tick_to_date(tick)
        assert svc.date_to_tick(d) == tick


# 28. Import/boundary tests
class TestImportBoundaries:
    def test_module_importable(self) -> None:
        import dnd_assistant.domain.calendar  # noqa: F401

    def test_deterministic_service_exported(self) -> None:
        from dnd_assistant.domain import DeterministicCalendarService

        assert DeterministicCalendarService is not None

    def test_no_storage_import(self) -> None:
        import importlib
        import sys

        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        importlib.import_module("dnd_assistant.domain.calendar")
        mods = {m for m in sys.modules if m.startswith("dnd_assistant.storage")}
        assert not mods

    def test_no_models_import(self) -> None:
        import importlib
        import sys

        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        importlib.import_module("dnd_assistant.domain.calendar")
        mods = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
        assert not mods
