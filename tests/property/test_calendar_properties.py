"""Hypothesis property-based tests for CalendarService (S4-04) — Part 1.

Properties P1-P8: date/tick round trips, epoch identity, arithmetic
invariants, adjacent ticks, year translation, holiday neutrality.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from dnd_assistant.domain import (
    CalendarDefinition,
    CalendarHoliday,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
    IntercalaryDay,
)

# =============================================================================
# Calendar strategy
# =============================================================================


@st.composite
def calendar_strategy(draw: st.DrawFn) -> CalendarDefinition:
    """Build a valid CalendarDefinition with bounded diversity."""
    num_months = draw(st.integers(min_value=1, max_value=6))
    month_names = [f"M{i}" for i in range(num_months)]
    month_lengths = draw(
        st.lists(
            st.integers(min_value=1, max_value=40),
            min_size=num_months,
            max_size=num_months,
        )
    )
    months = tuple(
        CalendarMonth(name=mname, days=mlen)
        for mname, mlen in zip(month_names, month_lengths, strict=True)
    )

    num_ic = draw(st.integers(min_value=0, max_value=6))
    ic_after = draw(
        st.lists(
            st.sampled_from(month_names),
            min_size=num_ic,
            max_size=num_ic,
        )
    )
    ic_names = [f"I{i}" for i in range(num_ic)]
    ics = tuple(
        IntercalaryDay(name=iname, after_month=am)
        for iname, am in zip(ic_names, ic_after, strict=True)
    )

    hours = draw(st.integers(min_value=1, max_value=30))
    minutes = draw(st.integers(min_value=1, max_value=120))

    # Draw a valid-by-construction epoch
    epoch_year = draw(st.integers(min_value=-10000, max_value=10000))
    epoch_hour = draw(st.integers(min_value=0, max_value=hours - 1))
    epoch_minute = draw(st.integers(min_value=0, max_value=minutes - 1))

    if ics and draw(st.booleans()):
        ic_name = draw(st.sampled_from(ic_names))
        epoch = GameDate(
            year=epoch_year,
            intercalary_day=ic_name,
            hour=epoch_hour,
            minute=epoch_minute,
        )
    else:
        month_name = draw(st.sampled_from(month_names))
        month_obj = next(m for m in months if m.name == month_name)
        epoch_day = draw(st.integers(min_value=1, max_value=month_obj.days))
        epoch = GameDate(
            year=epoch_year,
            month=month_name,
            day=epoch_day,
            hour=epoch_hour,
            minute=epoch_minute,
        )

    return CalendarDefinition(
        calendar_id="prop",
        months=months,
        intercalary_days=ics,
        hours_per_day=hours,
        minutes_per_hour=minutes,
        epoch=epoch,
    )


# =============================================================================
# Valid GameDate strategy (used via st.data())
# =============================================================================


def draw_valid_date(draw: st.DrawFn, cal: CalendarDefinition) -> GameDate:
    """Draw a GameDate valid for the given CalendarDefinition."""
    year = draw(st.integers(min_value=-10000, max_value=10000))
    hour = draw(st.integers(min_value=0, max_value=cal.hours_per_day - 1))
    minute = draw(st.integers(min_value=0, max_value=cal.minutes_per_hour - 1))

    if cal.intercalary_days and draw(st.booleans()):
        ic_name = draw(st.sampled_from([d.name for d in cal.intercalary_days]))
        return GameDate(year=year, intercalary_day=ic_name, hour=hour, minute=minute)
    else:
        month = draw(st.sampled_from([m.name for m in cal.months]))
        month_obj = next(m for m in cal.months if m.name == month)
        day = draw(st.integers(min_value=1, max_value=month_obj.days))
        return GameDate(year=year, month=month, day=day, hour=hour, minute=minute)


# =============================================================================
# P1: date -> tick -> date round trip
# =============================================================================


@given(data=st.data())
def test_p1_date_round_trip(data: st.DataObject) -> None:
    """tick_to_date(date_to_tick(date)) == date for every valid date."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    date = draw_valid_date(data.draw, cal)
    tick = svc.date_to_tick(date)
    restored = svc.tick_to_date(tick)
    assert restored == date


# =============================================================================
# P2: tick -> date -> tick round trip
# =============================================================================


@given(data=st.data(), t=st.integers(min_value=-(10**9), max_value=10**9))
def test_p2_tick_round_trip(data: st.DataObject, t: int) -> None:
    """date_to_tick(tick_to_date(tick)) == tick for signed ticks."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    date = svc.tick_to_date(t)
    restored = svc.date_to_tick(date)
    assert restored == t


# =============================================================================
# P3: epoch identity
# =============================================================================


@given(data=st.data())
def test_p3_epoch_identity(data: st.DataObject) -> None:
    """date_to_tick(epoch) == 0 and tick_to_date(0) == epoch."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    assert svc.date_to_tick(cal.epoch) == 0
    assert svc.tick_to_date(0) == cal.epoch


# =============================================================================
# P4: advance inverse
# =============================================================================


@given(
    data=st.data(),
    t=st.integers(min_value=-(10**9), max_value=10**9),
    d=st.integers(min_value=-(10**6), max_value=10**6),
)
def test_p4_advance_inverse(data: st.DataObject, t: int, d: int) -> None:
    """advance(advance(tick, delta), -delta) == tick."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    advanced = svc.advance_world_time(t, minutes=d)
    restored = svc.advance_world_time(advanced, minutes=-d)
    assert restored == t


# =============================================================================
# P5: time_until consistency
# =============================================================================


@given(
    data=st.data(),
    t=st.integers(min_value=-(10**9), max_value=10**9),
    d=st.integers(min_value=-(10**6), max_value=10**6),
)
def test_p5_time_until_forward(data: st.DataObject, t: int, d: int) -> None:
    """time_until(t, advance(t, d)) == d."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    advanced = svc.advance_world_time(t, minutes=d)
    assert svc.time_until(t, advanced) == d


@given(
    data=st.data(),
    t=st.integers(min_value=-(10**9), max_value=10**9),
    d=st.integers(min_value=-(10**6), max_value=10**6),
)
def test_p5b_time_until_reverse(data: st.DataObject, t: int, d: int) -> None:
    """time_until(advance(t, d), t) == -d."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    advanced = svc.advance_world_time(t, minutes=d)
    assert svc.time_until(advanced, t) == -d


@given(data=st.data(), t=st.integers(min_value=-(10**9), max_value=10**9))
def test_p5c_time_until_self(data: st.DataObject, t: int) -> None:
    """time_until(t, t) == 0."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    assert svc.time_until(t, t) == 0


# =============================================================================
# P6: adjacent tick invariant
# =============================================================================


@given(data=st.data(), t=st.integers(min_value=-(10**9), max_value=10**9 - 1))
def test_p6_adjacent_ticks(data: st.DataObject, t: int) -> None:
    """tick_to_date(t) and tick_to_date(t+1) differ by exactly 1 tick."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    d0 = svc.tick_to_date(t)
    d1 = svc.tick_to_date(t + 1)
    assert svc.date_to_tick(d1) - svc.date_to_tick(d0) == 1


# =============================================================================
# P7: one-year translation
# =============================================================================


@given(data=st.data())
def test_p7_one_year_translation(data: st.DataObject) -> None:
    """Same month/day, year+1 differs by days_per_year * minutes_per_day."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)
    days_per_year = sum(m.days for m in cal.months) + len(cal.intercalary_days)
    minutes_per_day = cal.hours_per_day * cal.minutes_per_hour
    expected = days_per_year * minutes_per_day

    date = draw_valid_date(data.draw, cal)
    assume(date.year < 10000)
    if date.intercalary_day is not None:
        d_plus = GameDate(
            year=date.year + 1,
            intercalary_day=date.intercalary_day,
            hour=date.hour,
            minute=date.minute,
        )
        d_minus = GameDate(
            year=date.year - 1,
            intercalary_day=date.intercalary_day,
            hour=date.hour,
            minute=date.minute,
        )
    else:
        d_plus = GameDate(
            year=date.year + 1,
            month=date.month,
            day=date.day,
            hour=date.hour,
            minute=date.minute,
        )
        d_minus = GameDate(
            year=date.year - 1,
            month=date.month,
            day=date.day,
            hour=date.hour,
            minute=date.minute,
        )
    assert svc.date_to_tick(d_plus) - svc.date_to_tick(date) == expected
    assert svc.date_to_tick(date) - svc.date_to_tick(d_minus) == expected


# =============================================================================
# P8: holidays do not affect elapsed time
# =============================================================================


@given(data=st.data(), t=st.integers(min_value=-(10**9), max_value=10**9))
def test_p8_holidays_no_effect_ticks(data: st.DataObject, t: int) -> None:
    """Adding valid holidays does not change tick_to_date."""
    cal = data.draw(calendar_strategy())
    svc_no_holiday = DeterministicCalendarService(cal)

    first_month = cal.months[0]
    holiday = CalendarHoliday(name="TestHoliday", month=first_month.name, day=1)
    cal_with_holiday = CalendarDefinition(
        calendar_id=cal.calendar_id,
        months=cal.months,
        intercalary_days=cal.intercalary_days,
        holidays=(holiday,),
        hours_per_day=cal.hours_per_day,
        minutes_per_hour=cal.minutes_per_hour,
        epoch=cal.epoch,
    )
    svc_with = DeterministicCalendarService(cal_with_holiday)
    assert svc_with.tick_to_date(t) == svc_no_holiday.tick_to_date(t)


@given(data=st.data())
def test_p8b_holidays_no_effect_dates(data: st.DataObject) -> None:
    """Adding valid holidays does not change date_to_tick."""
    cal = data.draw(calendar_strategy())
    svc_no_holiday = DeterministicCalendarService(cal)

    first_month = cal.months[0]
    holiday = CalendarHoliday(name="TestHoliday", month=first_month.name, day=1)
    cal_with_holiday = CalendarDefinition(
        calendar_id=cal.calendar_id,
        months=cal.months,
        intercalary_days=cal.intercalary_days,
        holidays=(holiday,),
        hours_per_day=cal.hours_per_day,
        minutes_per_hour=cal.minutes_per_hour,
        epoch=cal.epoch,
    )
    svc_with = DeterministicCalendarService(cal_with_holiday)

    date = draw_valid_date(data.draw, cal)
    assert svc_with.date_to_tick(date) == svc_no_holiday.date_to_tick(date)
