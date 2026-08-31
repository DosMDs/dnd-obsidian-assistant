"""Deterministic intercalary hardening tests for S4-04.

Tests cross-month declaration-order correctness, same-month ordering
preservation, final-month intercalary days, minimal calendars, and
round-trip invariants.
"""

from __future__ import annotations

from dnd_assistant.domain import (
    CalendarDefinition,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
    IntercalaryDay,
)

# =============================================================================
# Regression: cross-month intercalary declaration order
# =============================================================================


class TestCrossMonthDeclarationOrder:
    """Intercalary days declared in non-chronological month order must still
    be placed chronologically by their after_month reference.

    Declaration order: Late Festival (after Second), Early Festival (after First)
    Chronological order: First -> Early Festival -> Second -> Late Festival
    """

    _MONTHS = (
        CalendarMonth(name="First", days=3),
        CalendarMonth(name="Second", days=3),
    )

    @staticmethod
    def _cal() -> CalendarDefinition:
        return CalendarDefinition(
            calendar_id="cross",
            months=TestCrossMonthDeclarationOrder._MONTHS,
            intercalary_days=(
                IntercalaryDay(name="Late Festival", after_month="Second"),
                IntercalaryDay(name="Early Festival", after_month="First"),
            ),
            epoch=GameDate(year=1, month="First", day=1),
        )

    def test_early_before_late(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        early = svc.date_to_tick(GameDate(year=1, intercalary_day="Early Festival"))
        late = svc.date_to_tick(GameDate(year=1, intercalary_day="Late Festival"))
        assert early < late

    def test_early_adjacent_after_first_month(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        first_end = svc.date_to_tick(GameDate(year=1, month="First", day=3, hour=23, minute=59))
        early = svc.date_to_tick(GameDate(year=1, intercalary_day="Early Festival"))
        assert early - first_end == 1

    def test_early_adjacent_before_second_month(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        early_end = svc.date_to_tick(
            GameDate(year=1, intercalary_day="Early Festival", hour=23, minute=59)
        )
        second_start = svc.date_to_tick(GameDate(year=1, month="Second", day=1))
        assert second_start - early_end == 1

    def test_late_adjacent_after_second_month(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        second_end = svc.date_to_tick(GameDate(year=1, month="Second", day=3, hour=23, minute=59))
        late = svc.date_to_tick(GameDate(year=1, intercalary_day="Late Festival"))
        assert late - second_end == 1

    def test_late_adjacent_before_next_year(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        late_end = svc.date_to_tick(
            GameDate(year=1, intercalary_day="Late Festival", hour=23, minute=59)
        )
        next_year = svc.date_to_tick(GameDate(year=2, month="First", day=1))
        assert next_year - late_end == 1

    def test_early_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=1, intercalary_day="Early Festival")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_late_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=1, intercalary_day="Late Festival")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_early_negative_year_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=-5, intercalary_day="Early Festival")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_late_negative_year_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=-5, intercalary_day="Late Festival")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d


# =============================================================================
# Same-month intercalary declaration order preservation
# =============================================================================


class TestSameMonthIntercalaryOrder:
    """Multiple intercalary days after the same month must preserve
    their declaration order in the chronological layout."""

    _MONTHS = (
        CalendarMonth(name="A", days=3),
        CalendarMonth(name="B", days=3),
    )

    @staticmethod
    def _cal() -> CalendarDefinition:
        return CalendarDefinition(
            calendar_id="same",
            months=TestSameMonthIntercalaryOrder._MONTHS,
            intercalary_days=(
                IntercalaryDay(name="I2", after_month="A"),
                IntercalaryDay(name="I0", after_month="A"),
                IntercalaryDay(name="I1", after_month="A"),
            ),
            epoch=GameDate(year=1, month="A", day=1),
        )

    def test_declaration_order_preserved(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        t2 = svc.date_to_tick(GameDate(year=1, intercalary_day="I2"))
        t0 = svc.date_to_tick(GameDate(year=1, intercalary_day="I0"))
        t1 = svc.date_to_tick(GameDate(year=1, intercalary_day="I1"))
        assert t2 < t0 < t1

    def test_i2_adjacent_after_a_end(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        a_end = svc.date_to_tick(GameDate(year=1, month="A", day=3, hour=23, minute=59))
        t2 = svc.date_to_tick(GameDate(year=1, intercalary_day="I2"))
        assert t2 - a_end == 1

    def test_i1_adjacent_before_b_start(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        t1_end = svc.date_to_tick(GameDate(year=1, intercalary_day="I1", hour=23, minute=59))
        b_start = svc.date_to_tick(GameDate(year=1, month="B", day=1))
        assert b_start - t1_end == 1

    def test_all_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        for name in ("I2", "I0", "I1"):
            d = GameDate(year=1, intercalary_day=name)
            assert svc.tick_to_date(svc.date_to_tick(d)) == d


# =============================================================================
# Intercalary days after the final month
# =============================================================================


class TestFinalMonthIntercalary:
    """Intercalary days after the last month must appear before the
    next year's first month day 1."""

    _MONTHS = (CalendarMonth(name="M", days=2),)

    @staticmethod
    def _cal() -> CalendarDefinition:
        return CalendarDefinition(
            calendar_id="final",
            months=TestFinalMonthIntercalary._MONTHS,
            intercalary_days=(IntercalaryDay(name="YearEnd", after_month="M"),),
            epoch=GameDate(year=1, month="M", day=1),
        )

    def test_after_final_month_day(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        m_end = svc.date_to_tick(GameDate(year=1, month="M", day=2, hour=23, minute=59))
        ic = svc.date_to_tick(GameDate(year=1, intercalary_day="YearEnd"))
        assert ic - m_end == 1

    def test_before_next_year(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        ic_end = svc.date_to_tick(GameDate(year=1, intercalary_day="YearEnd", hour=23, minute=59))
        next_year = svc.date_to_tick(GameDate(year=2, month="M", day=1))
        assert next_year - ic_end == 1

    def test_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=1, intercalary_day="YearEnd")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_negative_year_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=-3, intercalary_day="YearEnd")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_year_boundary_adjacent_ticks(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        last = svc.date_to_tick(GameDate(year=1, intercalary_day="YearEnd", hour=23, minute=59))
        first = svc.date_to_tick(GameDate(year=2, month="M", day=1))
        assert first - last == 1


# =============================================================================
# Minimal calendars
# =============================================================================


class TestMinimalCalendar:
    """1 month, 1 day, 1 hour/day, 1 minute/hour with various IC counts."""

    @staticmethod
    def _cal(ic_days: tuple[IntercalaryDay, ...] = ()) -> CalendarDefinition:
        return CalendarDefinition(
            calendar_id="min",
            months=(CalendarMonth(name="M", days=1),),
            intercalary_days=ic_days,
            hours_per_day=1,
            minutes_per_hour=1,
            epoch=GameDate(year=1, month="M", day=1),
        )

    def test_no_ic_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        d = GameDate(year=1, month="M", day=1)
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_no_ic_year_boundary(self) -> None:
        svc = DeterministicCalendarService(self._cal())
        last = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=0, minute=0))
        next_year = svc.date_to_tick(GameDate(year=2, month="M", day=1))
        assert next_year - last == 1

    def test_one_ic_round_trip(self) -> None:
        svc = DeterministicCalendarService(self._cal((IntercalaryDay(name="I", after_month="M"),)))
        d = GameDate(year=1, intercalary_day="I")
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_one_ic_adjacent(self) -> None:
        svc = DeterministicCalendarService(self._cal((IntercalaryDay(name="I", after_month="M"),)))
        m_end = svc.date_to_tick(GameDate(year=1, month="M", day=1, hour=0, minute=0))
        ic = svc.date_to_tick(GameDate(year=1, intercalary_day="I"))
        assert ic - m_end == 1
        ic_end = svc.date_to_tick(GameDate(year=1, intercalary_day="I", hour=0, minute=0))
        next_year = svc.date_to_tick(GameDate(year=2, month="M", day=1))
        assert next_year - ic_end == 1

    def test_multi_ic_same_month_ordering(self) -> None:
        svc = DeterministicCalendarService(
            self._cal(
                (
                    IntercalaryDay(name="I1", after_month="M"),
                    IntercalaryDay(name="I2", after_month="M"),
                    IntercalaryDay(name="I3", after_month="M"),
                )
            )
        )
        t1 = svc.date_to_tick(GameDate(year=1, intercalary_day="I1"))
        t2 = svc.date_to_tick(GameDate(year=1, intercalary_day="I2"))
        t3 = svc.date_to_tick(GameDate(year=1, intercalary_day="I3"))
        assert t1 < t2 < t3

    def test_multi_ic_round_trip(self) -> None:
        svc = DeterministicCalendarService(
            self._cal(
                (
                    IntercalaryDay(name="I1", after_month="M"),
                    IntercalaryDay(name="I2", after_month="M"),
                )
            )
        )
        for name in ("I1", "I2"):
            d = GameDate(year=1, intercalary_day=name)
            assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_negative_year_multi_ic(self) -> None:
        svc = DeterministicCalendarService(
            self._cal(
                (
                    IntercalaryDay(name="I1", after_month="M"),
                    IntercalaryDay(name="I2", after_month="M"),
                )
            )
        )
        for name in ("I1", "I2"):
            d = GameDate(year=-10, intercalary_day=name)
            assert svc.tick_to_date(svc.date_to_tick(d)) == d


# =============================================================================
# Extreme-but-reasonable calendars
# =============================================================================


class TestExtremeCalendars:
    """Very short months, large hours/minutes, many IC days."""

    def test_very_short_months(self) -> None:
        cal = CalendarDefinition(
            calendar_id="short",
            months=(
                CalendarMonth(name="A", days=1),
                CalendarMonth(name="B", days=2),
                CalendarMonth(name="C", days=1),
            ),
            epoch=GameDate(year=1, month="A", day=1),
        )
        svc = DeterministicCalendarService(cal)
        for y in (-5, 0, 1, 10):
            for m_name, m_days in [("A", 1), ("B", 2), ("C", 1)]:
                for d in range(1, m_days + 1):
                    date = GameDate(year=y, month=m_name, day=d)
                    assert svc.tick_to_date(svc.date_to_tick(date)) == date

    def test_large_hours_per_day(self) -> None:
        cal = CalendarDefinition(
            calendar_id="big",
            months=(CalendarMonth(name="M", days=2),),
            hours_per_day=100,
            minutes_per_hour=1,
            epoch=GameDate(year=1, month="M", day=1),
        )
        svc = DeterministicCalendarService(cal)
        d = GameDate(year=5, month="M", day=2, hour=99)
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_large_minutes_per_hour(self) -> None:
        cal = CalendarDefinition(
            calendar_id="big",
            months=(CalendarMonth(name="M", days=2),),
            hours_per_day=1,
            minutes_per_hour=120,
            epoch=GameDate(year=1, month="M", day=1),
        )
        svc = DeterministicCalendarService(cal)
        d = GameDate(year=5, month="M", day=2, minute=119)
        assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_many_intercalary_days(self) -> None:
        months = (CalendarMonth(name="M", days=2),)
        ics = tuple(IntercalaryDay(name=f"I{i}", after_month="M") for i in range(10))
        cal = CalendarDefinition(
            calendar_id="many",
            months=months,
            intercalary_days=ics,
            epoch=GameDate(year=1, month="M", day=1),
        )
        svc = DeterministicCalendarService(cal)
        for i in range(10):
            d = GameDate(year=1, intercalary_day=f"I{i}")
            assert svc.tick_to_date(svc.date_to_tick(d)) == d

    def test_many_ic_ordering(self) -> None:
        months = (CalendarMonth(name="M", days=1),)
        ics = tuple(IntercalaryDay(name=f"I{i}", after_month="M") for i in range(10))
        cal = CalendarDefinition(
            calendar_id="many",
            months=months,
            intercalary_days=ics,
            epoch=GameDate(year=1, month="M", day=1),
        )
        svc = DeterministicCalendarService(cal)
        for i in range(9):
            a = svc.date_to_tick(GameDate(year=1, intercalary_day=f"I{i}"))
            b = svc.date_to_tick(GameDate(year=1, intercalary_day=f"I{i + 1}"))
            assert a < b

    def test_many_ic_negative_year(self) -> None:
        months = (CalendarMonth(name="M", days=1),)
        ics = tuple(IntercalaryDay(name=f"I{i}", after_month="M") for i in range(5))
        cal = CalendarDefinition(
            calendar_id="many",
            months=months,
            intercalary_days=ics,
            epoch=GameDate(year=1, month="M", day=1),
        )
        svc = DeterministicCalendarService(cal)
        for i in range(5):
            d = GameDate(year=-100, intercalary_day=f"I{i}")
            assert svc.tick_to_date(svc.date_to_tick(d)) == d


# =============================================================================
# S4-C03: Deterministic epoch regression tests
# =============================================================================


class TestEpochRegressions:
    """Deterministic epoch regression tests for S4-C03.

    These supplement the Hypothesis property coverage by fixing important
    epoch classes that must not silently disappear from the strategy.
    """

    def test_signed_non_midnight_regular_epoch(self) -> None:
        """Epoch at year=-5, non-first month, non-day-1, non-midnight."""
        cal = CalendarDefinition(
            calendar_id="signed-epoch",
            months=(
                CalendarMonth(name="A", days=5),
                CalendarMonth(name="B", days=3),
            ),
            epoch=GameDate(year=-5, month="B", day=2, hour=13, minute=17),
        )
        svc = DeterministicCalendarService(cal)
        assert svc.date_to_tick(cal.epoch) == 0
        assert svc.tick_to_date(0) == cal.epoch

    def test_year_zero_epoch(self) -> None:
        """Epoch at year=0, regular date."""
        cal = CalendarDefinition(
            calendar_id="year-zero-epoch",
            months=(
                CalendarMonth(name="A", days=5),
                CalendarMonth(name="B", days=3),
            ),
            epoch=GameDate(year=0, month="A", day=3),
        )
        svc = DeterministicCalendarService(cal)
        assert svc.date_to_tick(cal.epoch) == 0
        assert svc.tick_to_date(0) == cal.epoch

    def test_intercalary_non_midnight_epoch(self) -> None:
        """Epoch at an intercalary day with cross-month declaration ordering,
        non-midnight time-of-day."""
        cal = CalendarDefinition(
            calendar_id="ic-epoch",
            months=(
                CalendarMonth(name="First", days=3),
                CalendarMonth(name="Second", days=3),
            ),
            intercalary_days=(
                IntercalaryDay(name="Late Festival", after_month="Second"),
                IntercalaryDay(name="Early Festival", after_month="First"),
            ),
            epoch=GameDate(year=42, intercalary_day="Early Festival", hour=7, minute=31),
        )
        svc = DeterministicCalendarService(cal)
        assert svc.date_to_tick(cal.epoch) == 0
        assert svc.tick_to_date(0) == cal.epoch
