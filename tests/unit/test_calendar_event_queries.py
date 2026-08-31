"""Unit tests for S4-03 TimelineEvent calendar queries.

Covers events_between, events_near, upcoming, overdue_events,
time_until_event, interval helpers, strict input validation,
deterministic ordering, and protocol compatibility.
"""

from __future__ import annotations

import pytest

from dnd_assistant.domain import (
    CalendarDefinition,
    CalendarMonth,
    CalendarService,
    DeterministicCalendarService,
    GameDate,
    TemporalCertainty,
    TimelineEvent,
)
from dnd_assistant.domain.types import Visibility

# ── Helpers ─────────────────────────────────────────────────────────────────


def _svc() -> DeterministicCalendarService:
    """Default 24hx60m calendar service."""
    return DeterministicCalendarService(
        CalendarDefinition(
            calendar_id="test",
            months=(CalendarMonth(name="M", days=30),),
            epoch=GameDate(year=1, month="M", day=1),
        )
    )


def _custom_svc() -> DeterministicCalendarService:
    """Custom 10hx100m calendar service for upcoming tests."""
    return DeterministicCalendarService(
        CalendarDefinition(
            calendar_id="custom",
            months=(CalendarMonth(name="M", days=30),),
            epoch=GameDate(year=1, month="M", day=1),
            hours_per_day=10,
            minutes_per_hour=100,
        )
    )


def _exact(
    eid: str,
    tick: int,
    *,
    status: str = "historical",
    importance: str = "minor",
) -> TimelineEvent:
    return TimelineEvent(
        id=eid,
        type="timeline_event",
        name=eid,
        status=status,
        certainty=TemporalCertainty.EXACT,
        importance=importance,
        world_tick=tick,
        visibility=Visibility.PLAYER,
        revision=1,
    )


def _approx(
    eid: str,
    tick_min: int,
    tick_max: int,
    *,
    status: str = "historical",
    importance: str = "minor",
) -> TimelineEvent:
    return TimelineEvent(
        id=eid,
        type="timeline_event",
        name=eid,
        status=status,
        certainty=TemporalCertainty.APPROXIMATE,
        importance=importance,
        world_tick=None,
        world_tick_min=tick_min,
        world_tick_max=tick_max,
        visibility=Visibility.PLAYER,
        revision=1,
    )


def _range(
    eid: str,
    tick_min: int,
    tick_max: int,
    *,
    status: str = "historical",
    importance: str = "minor",
) -> TimelineEvent:
    return TimelineEvent(
        id=eid,
        type="timeline_event",
        name=eid,
        status=status,
        certainty=TemporalCertainty.RANGE,
        importance=importance,
        world_tick=None,
        world_tick_min=tick_min,
        world_tick_max=tick_max,
        visibility=Visibility.PLAYER,
        revision=1,
    )


def _unknown(
    eid: str,
    *,
    status: str = "historical",
    importance: str = "minor",
) -> TimelineEvent:
    return TimelineEvent(
        id=eid,
        type="timeline_event",
        name=eid,
        status=status,
        certainty=TemporalCertainty.UNKNOWN,
        importance=importance,
        world_tick=None,
        world_tick_min=None,
        world_tick_max=None,
        visibility=Visibility.PLAYER,
        revision=1,
    )


# =============================================================================
# Event interval normalization
# =============================================================================


class TestEventInterval:
    def test_exact_interval(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        result = svc.time_until_event(50, ev)
        assert result == (50, 50)

    def test_approximate_interval(self) -> None:
        svc = _svc()
        ev = _approx("e1", 100, 200)
        result = svc.time_until_event(50, ev)
        assert result == (50, 150)

    def test_range_interval(self) -> None:
        svc = _svc()
        ev = _range("e1", 100, 200)
        result = svc.time_until_event(50, ev)
        assert result == (50, 150)

    def test_unknown_interval(self) -> None:
        svc = _svc()
        ev = _unknown("e1")
        assert svc.time_until_event(50, ev) is None


# =============================================================================
# events_between -- exact
# =============================================================================


class TestEventsBetweenExact:
    def test_inside(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_before(self) -> None:
        svc = _svc()
        ev = _exact("e1", 30)
        result = svc.events_between([ev], 50, 150)
        assert result == ()

    def test_after(self) -> None:
        svc = _svc()
        ev = _exact("e1", 200)
        result = svc.events_between([ev], 50, 150)
        assert result == ()

    def test_exactly_start(self) -> None:
        svc = _svc()
        ev = _exact("e1", 50)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_exactly_end(self) -> None:
        svc = _svc()
        ev = _exact("e1", 150)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)


# =============================================================================
# events_between -- approximate/range overlap
# =============================================================================


class TestEventsBetweenApproxRange:
    def test_fully_inside(self) -> None:
        svc = _svc()
        ev = _approx("e1", 80, 120)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_overlap_left(self) -> None:
        svc = _svc()
        ev = _approx("e1", 30, 80)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_overlap_right(self) -> None:
        svc = _svc()
        ev = _approx("e1", 120, 200)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_contains_whole_query(self) -> None:
        svc = _svc()
        ev = _approx("e1", 30, 200)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_touch_start_boundary(self) -> None:
        svc = _svc()
        ev = _range("e1", 30, 50)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_touch_end_boundary(self) -> None:
        svc = _svc()
        ev = _range("e1", 150, 200)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)

    def test_fully_before(self) -> None:
        svc = _svc()
        ev = _approx("e1", 10, 40)
        result = svc.events_between([ev], 50, 150)
        assert result == ()

    def test_fully_after(self) -> None:
        svc = _svc()
        ev = _approx("e1", 200, 250)
        result = svc.events_between([ev], 50, 150)
        assert result == ()

    def test_range_same_as_approx(self) -> None:
        svc = _svc()
        ev = _range("e1", 80, 120)
        result = svc.events_between([ev], 50, 150)
        assert result == (ev,)


# =============================================================================
# events_between -- unknown
# =============================================================================


class TestEventsBetweenUnknown:
    def test_unknown_excluded(self) -> None:
        svc = _svc()
        ev = _unknown("e1")
        result = svc.events_between([ev], 0, 1000)
        assert result == ()


# =============================================================================
# events_between -- invalid query
# =============================================================================


class TestEventsBetweenInvalid:
    def test_start_gt_end_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="start_tick.*must not exceed"):
            svc.events_between([], 200, 100)

    @pytest.mark.parametrize("bad", [True, False])
    def test_start_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.events_between([], bad, 100)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [True, False])
    def test_end_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.events_between([], 0, bad)  # type: ignore[arg-type]

    def test_start_str_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.events_between([], "0", 100)  # type: ignore[arg-type]

    def test_end_float_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.events_between([], 0, 100.0)  # type: ignore[arg-type]

    def test_none_start_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.events_between([], None, 100)  # type: ignore[arg-type]


# =============================================================================
# events_between deterministic ordering
# =============================================================================


class TestEventsBetweenOrdering:
    def test_ordering_by_start_then_end_then_id(self) -> None:
        svc = _svc()
        ev_a = _exact("a", 100)
        ev_b = _exact("b", 100)
        ev_c = _exact("c", 200)
        ev_d = _approx("d", 50, 150)
        result = svc.events_between([ev_c, ev_a, ev_d, ev_b], 0, 300)
        assert result == (ev_d, ev_a, ev_b, ev_c)
        assert [e.id for e in result] == ["d", "a", "b", "c"]


# =============================================================================
# events_near
# =============================================================================


class TestEventsNear:
    def test_exact_exact_distance(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        nearby = _exact("nearby", 110)
        far = _exact("far", 200)
        result = svc.events_near([nearby, far], target, radius=15)
        assert result == (nearby,)

    def test_exact_range_distance(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        nearby = _range("nearby", 115, 130)
        result = svc.events_near([nearby], target, radius=15)
        assert result == (nearby,)

    def test_range_range_distance(self) -> None:
        svc = _svc()
        target = _range("target", 100, 120)
        nearby = _range("nearby", 130, 150)
        result = svc.events_near([nearby], target, radius=10)
        assert result == (nearby,)

    def test_overlap_distance_zero(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        overlap = _approx("overlap", 90, 110)
        result = svc.events_near([overlap], target, radius=0)
        assert result == (overlap,)

    def test_touching_intervals_included(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        touching = _exact("touching", 115)
        result = svc.events_near([touching], target, radius=15)
        assert result == (touching,)

    def test_distance_exactly_radius_included(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        edge = _exact("edge", 115)
        result = svc.events_near([edge], target, radius=15)
        assert result == (edge,)

    def test_distance_radius_plus_one_excluded(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        far = _exact("far", 116)
        result = svc.events_near([far], target, radius=15)
        assert result == ()

    def test_both_before_and_after(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        before = _exact("before", 90)
        after = _exact("after", 110)
        result = svc.events_near([before, after], target, radius=10)
        assert result == (before, after)


# =============================================================================
# events_near target exclusion
# =============================================================================


class TestEventsNearTargetExclusion:
    def test_same_id_excluded(self) -> None:
        svc = _svc()
        target = _exact("same", 100)
        result = svc.events_near([target], target, radius=100)
        assert result == ()

    def test_different_id_same_tick_included(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        other = _exact("other", 100)
        result = svc.events_near([other], target, radius=0)
        assert result == (other,)


# =============================================================================
# events_near unknown behavior
# =============================================================================


class TestEventsNearUnknown:
    def test_unknown_candidate_excluded(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        unknown = _unknown("unknown")
        result = svc.events_near([unknown], target, radius=100)
        assert result == ()

    def test_unknown_target_raises(self) -> None:
        svc = _svc()
        target = _unknown("target")
        with pytest.raises(ValueError, match="unknown temporal certainty"):
            svc.events_near([], target, radius=10)


# =============================================================================
# events_near radius validation
# =============================================================================


class TestEventsNearRadiusValidation:
    def test_radius_zero_accepted(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        result = svc.events_near([], target, radius=0)
        assert result == ()

    def test_radius_positive_accepted(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        result = svc.events_near([], target, radius=10)
        assert result == ()

    def test_radius_negative_rejected(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        with pytest.raises(ValueError, match="radius must be >= 0"):
            svc.events_near([], target, radius=-1)

    @pytest.mark.parametrize("bad", [True, False])
    def test_radius_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        target = _exact("target", 100)
        with pytest.raises(ValueError, match="radius must not be a bool"):
            svc.events_near([], target, radius=bad)  # type: ignore[arg-type]

    def test_radius_str_rejected(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        with pytest.raises(ValueError, match="radius must be an int"):
            svc.events_near([], target, radius="10")  # type: ignore[arg-type]

    def test_radius_float_rejected(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        with pytest.raises(ValueError, match="radius must be an int"):
            svc.events_near([], target, radius=10.0)  # type: ignore[arg-type]

    def test_radius_none_rejected(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        with pytest.raises(ValueError, match="radius must be an int"):
            svc.events_near([], target, radius=None)  # type: ignore[arg-type]


# =============================================================================
# events_near ordering
# =============================================================================


class TestEventsNearOrdering:
    def test_ordering_by_distance_then_start_then_end_then_id(self) -> None:
        svc = _svc()
        target = _exact("target", 100)
        ev_d1 = _exact("d1", 105)
        ev_d2 = _exact("d2", 105)
        ev_d3 = _exact("d3", 110)
        ev_d4 = _approx("d4", 95, 105)
        result = svc.events_near([ev_d1, ev_d3, ev_d4, ev_d2], target, radius=20)
        assert [e.id for e in result] == ["d4", "d1", "d2", "d3"]


# =============================================================================
# upcoming
# =============================================================================


class TestUpcoming:
    def test_event_at_current_tick_included(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        result = svc.upcoming([ev], 100, days=1)
        assert result == (ev,)

    def test_event_inside_window(self) -> None:
        svc = _svc()
        ev = _exact("e1", 500)
        result = svc.upcoming([ev], 100, days=1)
        assert result == (ev,)

    def test_event_exactly_at_end(self) -> None:
        svc = _svc()
        ev = _exact("e1", 1540)
        result = svc.upcoming([ev], 100, days=1)
        assert result == (ev,)

    def test_event_immediately_after_end(self) -> None:
        svc = _svc()
        ev = _exact("e1", 1541)
        result = svc.upcoming([ev], 100, days=1)
        assert result == ()

    def test_event_before_current(self) -> None:
        svc = _svc()
        ev = _exact("e1", 50)
        result = svc.upcoming([ev], 100, days=1)
        assert result == ()

    def test_interval_straddling_current(self) -> None:
        svc = _svc()
        ev = _approx("e1", 80, 120)
        result = svc.upcoming([ev], 100, days=1)
        assert result == (ev,)

    def test_interval_overlapping_window_end(self) -> None:
        svc = _svc()
        ev = _approx("e1", 1500, 1600)
        result = svc.upcoming([ev], 100, days=1)
        assert result == (ev,)

    def test_unknown_excluded(self) -> None:
        svc = _svc()
        ev = _unknown("e1")
        result = svc.upcoming([ev], 100, days=1)
        assert result == ()


# =============================================================================
# custom calendar upcoming
# =============================================================================


class TestUpcomingCustomCalendar:
    def test_custom_day_conversion(self) -> None:
        svc = _custom_svc()
        ev = _exact("e1", 1000)
        result = svc.upcoming([ev], 0, days=1)
        assert result == (ev,)

    def test_custom_day_boundary(self) -> None:
        svc = _custom_svc()
        ev = _exact("e1", 1001)
        result = svc.upcoming([ev], 0, days=1)
        assert result == ()


# =============================================================================
# upcoming days validation
# =============================================================================


class TestUpcomingDaysValidation:
    def test_days_zero_accepted(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        result = svc.upcoming([ev], 100, days=0)
        assert result == (ev,)

    def test_days_positive_accepted(self) -> None:
        svc = _svc()
        result = svc.upcoming([], 100, days=5)
        assert result == ()

    def test_days_negative_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="days must be >= 0"):
            svc.upcoming([], 100, days=-1)

    @pytest.mark.parametrize("bad", [True, False])
    def test_days_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="days must not be a bool"):
            svc.upcoming([], 100, days=bad)  # type: ignore[arg-type]

    def test_days_str_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="days must be an int"):
            svc.upcoming([], 100, days="1")  # type: ignore[arg-type]

    def test_days_float_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="days must be an int"):
            svc.upcoming([], 100, days=1.0)  # type: ignore[arg-type]

    def test_days_none_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="days must be an int"):
            svc.upcoming([], 100, days=None)  # type: ignore[arg-type]


# =============================================================================
# overdue_events -- exact
# =============================================================================


class TestOverdueExact:
    def test_event_before_current_overdue(self) -> None:
        svc = _svc()
        ev = _exact("e1", 50)
        result = svc.overdue_events([ev], 100)
        assert result == (ev,)

    def test_event_at_current_not_overdue(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        result = svc.overdue_events([ev], 100)
        assert result == ()

    def test_event_after_current_not_overdue(self) -> None:
        svc = _svc()
        ev = _exact("e1", 150)
        result = svc.overdue_events([ev], 100)
        assert result == ()


# =============================================================================
# overdue_events -- approximate/range
# =============================================================================


class TestOverdueApproxRange:
    def test_max_before_current_overdue(self) -> None:
        svc = _svc()
        ev = _approx("e1", 30, 80)
        result = svc.overdue_events([ev], 100)
        assert result == (ev,)

    def test_straddling_current_not_overdue(self) -> None:
        svc = _svc()
        ev = _approx("e1", 80, 120)
        result = svc.overdue_events([ev], 100)
        assert result == ()

    def test_min_equal_current_not_overdue(self) -> None:
        svc = _svc()
        ev = _range("e1", 100, 150)
        result = svc.overdue_events([ev], 100)
        assert result == ()

    def test_min_after_current_not_overdue(self) -> None:
        svc = _svc()
        ev = _range("e1", 120, 180)
        result = svc.overdue_events([ev], 100)
        assert result == ()

    def test_unknown_excluded(self) -> None:
        svc = _svc()
        ev = _unknown("e1")
        result = svc.overdue_events([ev], 100)
        assert result == ()


# =============================================================================
# overdue_events ordering
# =============================================================================


class TestOverdueOrdering:
    def test_ordering_by_end_then_start_then_id(self) -> None:
        svc = _svc()
        ev_a = _exact("a", 30)
        ev_b = _exact("b", 30)
        ev_c = _exact("c", 60)
        ev_d = _approx("d", 10, 50)
        result = svc.overdue_events([ev_c, ev_a, ev_d, ev_b], 100)
        assert [e.id for e in result] == ["d", "a", "b", "c"]


# =============================================================================
# time_until_event -- exact
# =============================================================================


class TestTimeUntilEventExact:
    def test_future_positive(self) -> None:
        svc = _svc()
        ev = _exact("e1", 110)
        result = svc.time_until_event(100, ev)
        assert result == (10, 10)

    def test_now_zero(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        result = svc.time_until_event(100, ev)
        assert result == (0, 0)

    def test_past_negative(self) -> None:
        svc = _svc()
        ev = _exact("e1", 90)
        result = svc.time_until_event(100, ev)
        assert result == (-10, -10)


# =============================================================================
# time_until_event -- approximate/range
# =============================================================================


class TestTimeUntilEventApproxRange:
    def test_entirely_future(self) -> None:
        svc = _svc()
        ev = _approx("e1", 150, 200)
        result = svc.time_until_event(100, ev)
        assert result == (50, 100)

    def test_entirely_past(self) -> None:
        svc = _svc()
        ev = _approx("e1", 30, 80)
        result = svc.time_until_event(100, ev)
        assert result == (-70, -20)

    def test_straddles_current(self) -> None:
        svc = _svc()
        ev = _range("e1", 80, 120)
        result = svc.time_until_event(100, ev)
        assert result == (-20, 20)

    def test_degenerate_min_eq_max(self) -> None:
        svc = _svc()
        ev = _range("e1", 150, 150)
        result = svc.time_until_event(100, ev)
        assert result == (50, 50)


# =============================================================================
# time_until_event -- unknown
# =============================================================================


class TestTimeUntilEventUnknown:
    def test_unknown_returns_none(self) -> None:
        svc = _svc()
        ev = _unknown("e1")
        assert svc.time_until_event(100, ev) is None


# =============================================================================
# strict current tick validation
# =============================================================================


class TestStrictCurrentTickValidation:
    @pytest.mark.parametrize("bad", [True, False])
    def test_upcoming_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.upcoming([], bad, days=1)  # type: ignore[arg-type]

    def test_upcoming_str_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.upcoming([], "100", days=1)  # type: ignore[arg-type]

    def test_upcoming_float_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.upcoming([], 100.0, days=1)  # type: ignore[arg-type]

    def test_upcoming_none_rejected(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must be an int"):
            svc.upcoming([], None, days=1)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [True, False])
    def test_overdue_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.overdue_events([], bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [True, False])
    def test_time_until_bool_rejected(self, bad: bool) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        with pytest.raises(ValueError, match="WorldTick must not be a bool"):
            svc.time_until_event(bad, ev)  # type: ignore[arg-type]


# =============================================================================
# status independence
# =============================================================================


class TestStatusIndependence:
    def test_temporal_queries_ignore_status_strings(self) -> None:
        svc = _svc()
        ev_pending = _exact("e1", 50, status="pending")
        ev_resolved = _exact("e2", 50, status="resolved")
        ev_historical = _exact("e3", 50, status="historical")
        result = svc.overdue_events([ev_pending, ev_resolved, ev_historical], 100)
        assert len(result) == 3


# =============================================================================
# input immutability
# =============================================================================


class TestInputImmutability:
    def test_events_not_modified_by_queries(self) -> None:
        svc = _svc()
        ev = _exact("e1", 100)
        events = [ev]
        _ = svc.events_between(events, 0, 200)
        _ = svc.events_near(events, ev, radius=10)
        _ = svc.upcoming(events, 50, days=1)
        _ = svc.overdue_events(events, 200)
        assert events == [ev]
        assert ev.world_tick == 100


# =============================================================================
# Protocol compatibility
# =============================================================================


class TestProtocolCompatibility:
    def test_isinstance_calendar_service(self) -> None:
        svc = _svc()
        assert isinstance(svc, CalendarService)
