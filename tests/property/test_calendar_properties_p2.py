"""Hypothesis property-based tests for CalendarService (S4-04) — Part 2.

Properties P9-P12: intercalary order semantics, event query reference
models, and overdue conservative semantics.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from dnd_assistant.domain import (
    DeterministicCalendarService,
    GameDate,
    TemporalCertainty,
    TimelineEvent,
)
from dnd_assistant.domain.types import Visibility
from tests.property.test_calendar_properties import calendar_strategy

# =============================================================================
# Helper: build a TimelineEvent for property tests
# =============================================================================


def _make_event(event_id: str, start: int, end: int) -> TimelineEvent:
    """Build a range-certainty TimelineEvent from [start, end]."""
    return TimelineEvent(
        id=event_id,
        type="timeline_event",
        name=f"evt-{event_id}",
        status="historical",
        certainty=TemporalCertainty.RANGE,
        importance="minor",
        world_tick=None,
        world_tick_min=start,
        world_tick_max=end,
        visibility=Visibility.PLAYER,
        revision=1,
    )


# =============================================================================
# P9: intercalary declaration order semantics
# =============================================================================


@given(data=st.data())
def test_p9_intercalary_order(data: st.DataObject) -> None:
    """Two invariants for intercalary ordering.

    1. Same after_month: chronological order == declaration order.
    2. Different after_month: chronology follows month placement.
    """
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)

    # Same after_month: declaration order preserved
    by_month: dict[str, list[str]] = {}
    for ic in cal.intercalary_days:
        by_month.setdefault(ic.after_month, []).append(ic.name)

    for _month_name, ic_names in by_month.items():
        if len(ic_names) < 2:
            continue
        ticks = [svc.date_to_tick(GameDate(year=1, intercalary_day=n)) for n in ic_names]
        for i in range(len(ticks) - 1):
            assert ticks[i] < ticks[i + 1]

    # Cross-month: earlier after_month -> earlier tick
    month_order = [m.name for m in cal.months]
    for i in range(len(cal.intercalary_days)):
        for j in range(i + 1, len(cal.intercalary_days)):
            ic_a = cal.intercalary_days[i]
            ic_b = cal.intercalary_days[j]
            idx_a = month_order.index(ic_a.after_month)
            idx_b = month_order.index(ic_b.after_month)
            if idx_a == idx_b:
                continue
            tick_a = svc.date_to_tick(GameDate(year=1, intercalary_day=ic_a.name))
            tick_b = svc.date_to_tick(GameDate(year=1, intercalary_day=ic_b.name))
            if idx_a < idx_b:
                assert tick_a < tick_b
            else:
                assert tick_a > tick_b


# =============================================================================
# P10: query overlap reference model
# =============================================================================
# Uses st.data() to draw the calendar and then separate integer params


@given(
    data=st.data(),
    q_start=st.integers(min_value=-1000, max_value=1000),
    q_end=st.integers(min_value=-1000, max_value=1000),
)
def test_p10_events_between_reference(
    data: st.DataObject,
    q_start: int,
    q_end: int,
) -> None:
    """events_between matches a naive reference overlap implementation."""
    assume(q_start <= q_end)
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)

    intervals = data.draw(
        st.lists(
            st.tuples(
                st.integers(min_value=-1000, max_value=1000),
                st.integers(min_value=-1000, max_value=1000),
            ).map(lambda p: (min(p), max(p))),
            min_size=1,
            max_size=5,
        )
    )
    events = [_make_event(f"e{i}", s, e) for i, (s, e) in enumerate(intervals)]
    result = svc.events_between(events, q_start, q_end)
    expected_ids = set()
    for i, (s, e) in enumerate(intervals):
        if s <= q_end and e >= q_start:
            expected_ids.add(f"e{i}")
    result_ids = {ev.id for ev in result}
    assert result_ids == expected_ids


# =============================================================================
# P11: events_near distance reference model
# =============================================================================


@given(
    data=st.data(),
    radius=st.integers(min_value=0, max_value=500),
)
def test_p11_events_near_reference(data: st.DataObject, radius: int) -> None:
    """events_near matches naive distance calculation."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)

    intervals = data.draw(
        st.lists(
            st.tuples(
                st.integers(min_value=-1000, max_value=1000),
                st.integers(min_value=-1000, max_value=1000),
            ).map(lambda p: (min(p), max(p))),
            min_size=2,
            max_size=5,
        )
    )
    events = [_make_event(f"e{i}", s, e) for i, (s, e) in enumerate(intervals)]
    target = events[0]
    target_iv = intervals[0]

    result = svc.events_near(events[1:], target, radius=radius)

    expected_ids: set[str] = set()
    for i, (s, e) in enumerate(intervals[1:], start=1):
        if e < target_iv[0]:
            dist = target_iv[0] - e
        elif target_iv[1] < s:
            dist = s - target_iv[1]
        else:
            dist = 0
        if dist <= radius:
            expected_ids.add(f"e{i}")

    result_ids = {ev.id for ev in result}
    assert result_ids == expected_ids


# =============================================================================
# P12: overdue conservative semantics
# =============================================================================


@given(
    data=st.data(),
    current=st.integers(min_value=-1000, max_value=1000),
)
def test_p12_overdue_conservative(data: st.DataObject, current: int) -> None:
    """Overdue iff event_end < current_tick. Unknown events excluded."""
    cal = data.draw(calendar_strategy())
    svc = DeterministicCalendarService(cal)

    intervals = data.draw(
        st.lists(
            st.tuples(
                st.integers(min_value=-1000, max_value=1000),
                st.integers(min_value=-1000, max_value=1000),
            ).map(lambda p: (min(p), max(p))),
            min_size=1,
            max_size=5,
        )
    )
    events = [_make_event(f"e{i}", s, e) for i, (s, e) in enumerate(intervals)]
    result = svc.overdue_events(events, current)

    expected_ids: set[str] = set()
    for i, (_s, e) in enumerate(intervals):
        if e < current:
            expected_ids.add(f"e{i}")

    result_ids = {ev.id for ev in result}
    assert result_ids == expected_ids
