"""Tests for world-time read tool handler behaviour and ToolExecutor integration.

Covers:
- get_world_time handler behaviour (repository delegation, date derivation)
- world_tick_to_date handler behaviour (pure calendar conversion)
- game_date_to_world_tick handler behaviour (pure calendar conversion, ValidationError)
- time_between_world_ticks handler behaviour (pure calendar arithmetic)
- ToolExecutor integration (READ/WRITE authority, session modes, no audit)
- No-mutation guarantees (pure calendar tools do not access repository)
- Calendar round-trip integration regression
"""

from __future__ import annotations

from typing import Any

import pytest

from dnd_assistant.domain.calendar import (
    CalendarDefinition,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
    IntercalaryDay,
    WorldTick,
)
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)
from dnd_assistant.tools.world_time_reads import (
    GameDateToWorldTickOutput,
    GetWorldTimeOutput,
    TimeBetweenWorldTicksOutput,
    WorldTickToDateOutput,
    register_world_time_read_tools,
)

# ── Test calendar definition ──────────────────────────────────────────────

_HARNER_CALENDAR = CalendarDefinition(
    calendar_id="harner",
    epoch=GameDate(year=0, month="Hammer", day=1),
    months=(
        CalendarMonth(name="Hammer", days=30),
        CalendarMonth(name="Alturiak", days=30),
    ),
    intercalary_days=(IntercalaryDay(name="Midwinter", after_month="Hammer"),),
    hours_per_day=24,
    minutes_per_hour=60,
)


# ── Fake WorldTimeRepository ──────────────────────────────────────────────


class FakeWorldTimeRepository:
    """Controllable fake implementing WorldTimeRepository protocol."""

    def __init__(self, state: CurrentWorldTime | None = None) -> None:
        self._state = state
        self.get_called: bool = False
        self.initialize_called: bool = False
        self.set_called: bool = False

    def set_state(self, state: CurrentWorldTime | None) -> None:
        self._state = state

    def get_current_world_time(self) -> CurrentWorldTime:
        self.get_called = True
        if self._state is None:
            raise NotFoundError(
                "world_time.json not found \u2014 current world time has not been initialized"
            )
        return self._state

    def initialize_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
        self.initialize_called = True
        msg = "FakeWorldTimeRepository does not support initialize"
        raise NotImplementedError(msg)

    def set_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
        self.set_called = True
        msg = "FakeWorldTimeRepository does not support set"
        raise NotImplementedError(msg)


# ── Fake CalendarService for delegation tests ─────────────────────────────


class FakeCalendarService:
    """Controllable fake implementing CalendarService protocol."""

    def __init__(self) -> None:
        self._definition = _HARNER_CALENDAR
        self.last_tick: int | None = None
        self.last_date: GameDate | None = None
        self.last_start_tick: int | None = None
        self.last_end_tick: int | None = None

    @property
    def definition(self) -> CalendarDefinition:
        return self._definition

    def tick_to_date(self, tick: int) -> GameDate:
        self.last_tick = tick
        return GameDate(year=1, month="Hammer", day=15, hour=6, minute=0)

    def date_to_tick(self, date: GameDate) -> int:
        self.last_date = date
        return 5000

    def time_until(self, start_tick: int, end_tick: int) -> int:
        self.last_start_tick = start_tick
        self.last_end_tick = end_tick
        return int(end_tick - start_tick) + 42

    def advance_world_time(self, current_tick: int, *, minutes: int) -> int:
        return current_tick + minutes

    def events_between(self, events, start_tick, end_tick):
        return ()

    def events_near(self, events, event, *, radius):
        return ()

    def upcoming(self, events, current_tick, *, days):
        return ()

    def overdue_events(self, events, current_tick):
        return ()

    def time_until_event(self, current_tick, event):
        return None


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def fake_repo() -> FakeWorldTimeRepository:
    return FakeWorldTimeRepository(
        state=CurrentWorldTime(current_world_tick=WorldTick(1000), revision=3)
    )


@pytest.fixture
def fake_calendar() -> FakeCalendarService:
    return FakeCalendarService()


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
    )


@pytest.fixture
def registered_registry(
    registry: ToolRegistry,
    fake_repo: FakeWorldTimeRepository,
    fake_calendar: FakeCalendarService,
) -> ToolRegistry:
    register_world_time_read_tools(
        registry,
        world_time_repository=fake_repo,
        calendar_service=fake_calendar,
    )
    return registry


@pytest.fixture
def executor(registered_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registered_registry)


# ═══════════════════════════════════════════════════════════════════════════
# get_world_time behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestGetWorldTimeBehaviour:
    def test_returns_persisted_state(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute("get_world_time", input_data={}, context=read_context)
        assert isinstance(result, GetWorldTimeOutput)
        assert result.world_time.current_world_tick == 1000
        assert result.world_time.revision == 3
        assert result.calendar_id == "harner"

    def test_repository_get_called_once(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute("get_world_time", input_data={}, context=read_context)
        assert fake_repo.get_called

    def test_tick_forwarded_to_calendar(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute("get_world_time", input_data={}, context=read_context)
        assert fake_calendar.last_tick == 1000

    def test_derived_game_date_returned(
        self,
        executor: ToolExecutor,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute("get_world_time", input_data={}, context=read_context)
        assert result.game_date.month == "Hammer"
        assert result.game_date.day == 15

    def test_not_found_propagates(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        empty_repo = FakeWorldTimeRepository(state=None)
        register_world_time_read_tools(
            registry,
            world_time_repository=empty_repo,
            calendar_service=fake_calendar,
        )
        exec_ = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            exec_.execute("get_world_time", input_data={}, context=read_context)

    def test_no_fallback_to_tick_zero(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        empty_repo = FakeWorldTimeRepository(state=None)
        register_world_time_read_tools(
            registry,
            world_time_repository=empty_repo,
            calendar_service=fake_calendar,
        )
        exec_ = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            exec_.execute("get_world_time", input_data={}, context=read_context)

    def test_storage_error_propagates(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        class BrokenRepo:
            def get_current_world_time(self) -> CurrentWorldTime:
                raise StorageError("Disk failure")

            def initialize_current_world_time(self, *a: Any, **k: Any) -> Any:
                raise NotImplementedError

            def set_current_world_time(self, *a: Any, **k: Any) -> Any:
                raise NotImplementedError

        register_world_time_read_tools(
            registry,
            world_time_repository=BrokenRepo(),
            calendar_service=fake_calendar,
        )
        exec_ = ToolExecutor(registry)
        with pytest.raises(StorageError, match="Disk failure"):
            exec_.execute("get_world_time", input_data={}, context=read_context)

    def test_mutation_methods_not_called(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute("get_world_time", input_data={}, context=read_context)
        assert not fake_repo.initialize_called
        assert not fake_repo.set_called


# ═══════════════════════════════════════════════════════════════════════════
# world_tick_to_date behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestWorldTickToDateBehaviour:
    def test_delegates_to_calendar(
        self,
        executor: ToolExecutor,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "world_tick_to_date",
            input_data={"world_tick": 500},
            context=read_context,
        )
        assert isinstance(result, WorldTickToDateOutput)
        assert fake_calendar.last_tick == 500
        assert result.game_date.month == "Hammer"
        assert result.game_date.day == 15
        assert result.calendar_id == "harner"

    def test_repository_not_called(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "world_tick_to_date",
            input_data={"world_tick": 0},
            context=read_context,
        )
        assert not fake_repo.get_called
        assert not fake_repo.initialize_called
        assert not fake_repo.set_called


# ═══════════════════════════════════════════════════════════════════════════
# game_date_to_world_tick behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestGameDateToWorldTickBehaviour:
    def test_delegates_to_calendar(
        self,
        executor: ToolExecutor,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "game_date_to_world_tick",
            input_data={"game_date": {"year": 1, "month": "Hammer", "day": 1}},
            context=read_context,
        )
        assert isinstance(result, GameDateToWorldTickOutput)
        assert fake_calendar.last_date is not None
        assert fake_calendar.last_date.year == 1
        assert result.world_tick == 5000
        assert result.calendar_id == "harner"

    def test_repository_not_called(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "game_date_to_world_tick",
            input_data={"game_date": {"year": 0, "month": "Hammer", "day": 1}},
            context=read_context,
        )
        assert not fake_repo.get_called
        assert not fake_repo.initialize_called
        assert not fake_repo.set_called

    def test_definition_invalid_date_raises_validation_error(
        self,
        registry: ToolRegistry,
        read_context: ExecutionContext,
    ) -> None:
        """A structurally valid GameDate with an unknown month must raise ValidationError."""
        real_calendar = DeterministicCalendarService(_HARNER_CALENDAR)
        register_world_time_read_tools(
            registry,
            world_time_repository=FakeWorldTimeRepository(
                state=CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
            ),
            calendar_service=real_calendar,
        )
        exec_ = ToolExecutor(registry)
        with pytest.raises(ValidationError, match="month"):
            exec_.execute(
                "game_date_to_world_tick",
                input_data={"game_date": {"year": 1, "month": "FakeMonth", "day": 1}},
                context=read_context,
            )

    def test_unexpected_exception_propagates(
        self,
        registry: ToolRegistry,
        read_context: ExecutionContext,
    ) -> None:
        class BrokenCalendar:
            @property
            def definition(self):
                return _HARNER_CALENDAR

            def date_to_tick(self, date: GameDate) -> int:
                raise RuntimeError("internal error")

            def tick_to_date(self, tick: int) -> GameDate:
                return GameDate(year=0, month="Hammer", day=1)

            def time_until(self, start: int, end: int) -> int:
                return end - start

            def advance_world_time(self, current: int, *, minutes: int) -> int:
                return current + minutes

            def events_between(self, events, start, end):
                return ()

            def events_near(self, events, event, *, radius):
                return ()

            def upcoming(self, events, current, *, days):
                return ()

            def overdue_events(self, events, current):
                return ()

            def time_until_event(self, current, event):
                return None

        register_world_time_read_tools(
            registry,
            world_time_repository=FakeWorldTimeRepository(
                state=CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
            ),
            calendar_service=BrokenCalendar(),
        )
        exec_ = ToolExecutor(registry)
        with pytest.raises(RuntimeError, match="internal error"):
            exec_.execute(
                "game_date_to_world_tick",
                input_data={"game_date": {"year": 1, "month": "Hammer", "day": 1}},
                context=read_context,
            )


# ═══════════════════════════════════════════════════════════════════════════
# time_between_world_ticks behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeBetweenWorldTicksBehaviour:
    def test_positive_delta(
        self,
        executor: ToolExecutor,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "time_between_world_ticks",
            input_data={"start_tick": 100, "end_tick": 200},
            context=read_context,
        )
        assert isinstance(result, TimeBetweenWorldTicksOutput)
        assert fake_calendar.last_start_tick == 100
        assert fake_calendar.last_end_tick == 200
        assert result.minutes == 142

    def test_negative_delta(
        self,
        executor: ToolExecutor,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "time_between_world_ticks",
            input_data={"start_tick": 200, "end_tick": 100},
            context=read_context,
        )
        assert result.minutes == -58

    def test_zero_delta(
        self,
        executor: ToolExecutor,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "time_between_world_ticks",
            input_data={"start_tick": 100, "end_tick": 100},
            context=read_context,
        )
        assert result.minutes == 42

    def test_repository_not_called(
        self,
        executor: ToolExecutor,
        fake_repo: FakeWorldTimeRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "time_between_world_ticks",
            input_data={"start_tick": 0, "end_tick": 0},
            context=read_context,
        )
        assert not fake_repo.get_called
        assert not fake_repo.initialize_called
        assert not fake_repo.set_called


# ═══════════════════════════════════════════════════════════════════════════
# ToolExecutor integration
# ═══════════════════════════════════════════════════════════════════════════


class TestToolExecutorIntegration:
    def test_read_authority_allowed(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        result = executor.execute("get_world_time", input_data={}, context=read_context)
        assert isinstance(result, GetWorldTimeOutput)

    def test_write_authority_allowed(
        self, executor: ToolExecutor, write_context: ExecutionContext
    ) -> None:
        result = executor.execute("get_world_time", input_data={}, context=write_context)
        assert isinstance(result, GetWorldTimeOutput)

    def test_no_active_session_allowed(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        result = executor.execute("get_world_time", input_data={}, context=read_context)
        assert isinstance(result, GetWorldTimeOutput)

    def test_active_session_allowed(self, executor: ToolExecutor) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        result = executor.execute("get_world_time", input_data={}, context=ctx)
        assert isinstance(result, GetWorldTimeOutput)

    def test_no_audit_required(self, executor: ToolExecutor) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        result = executor.execute("get_world_time", input_data={}, context=ctx)
        assert isinstance(result, GetWorldTimeOutput)

    def test_invalid_input_prevents_handler_call(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "get_world_time",
                input_data={"world_tick": 100},
                context=read_context,
            )

    def test_all_four_tools_work_under_read(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        for tool_name in (
            "get_world_time",
            "world_tick_to_date",
            "game_date_to_world_tick",
            "time_between_world_ticks",
        ):
            if tool_name == "get_world_time":
                inp = {}
            elif tool_name == "world_tick_to_date":
                inp = {"world_tick": 0}
            elif tool_name == "game_date_to_world_tick":
                inp = {"game_date": {"year": 0, "month": "Hammer", "day": 1}}
            else:
                inp = {"start_tick": 0, "end_tick": 0}
            result = executor.execute(tool_name, input_data=inp, context=read_context)
            assert result is not None


# ═══════════════════════════════════════════════════════════════════════════
# Calendar round-trip integration regression
# ═══════════════════════════════════════════════════════════════════════════


class TestCalendarRoundTrip:
    """Tool-level deterministic round-trip with real DeterministicCalendarService."""

    @pytest.fixture
    def real_executor(self, registry: ToolRegistry) -> ToolExecutor:
        real_calendar = DeterministicCalendarService(_HARNER_CALENDAR)
        register_world_time_read_tools(
            registry,
            world_time_repository=FakeWorldTimeRepository(
                state=CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
            ),
            calendar_service=real_calendar,
        )
        return ToolExecutor(registry)

    def _round_trip(
        self,
        executor: ToolExecutor,
        game_date: dict[str, Any],
    ) -> GameDate:
        tick_result = executor.execute(
            "game_date_to_world_tick",
            input_data={"game_date": game_date},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        date_result = executor.execute(
            "world_tick_to_date",
            input_data={"world_tick": tick_result.world_tick},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        return date_result.game_date

    def test_regular_date_round_trip(self, real_executor: ToolExecutor) -> None:
        result = self._round_trip(
            real_executor, {"year": 5, "month": "Hammer", "day": 15, "hour": 6, "minute": 30}
        )
        assert result.year == 5
        assert result.month == "Hammer"
        assert result.day == 15
        assert result.hour == 6
        assert result.minute == 30

    def test_intercalary_date_round_trip(self, real_executor: ToolExecutor) -> None:
        result = self._round_trip(
            real_executor, {"year": 3, "intercalary_day": "Midwinter", "hour": 12, "minute": 0}
        )
        assert result.year == 3
        assert result.intercalary_day == "Midwinter"
        assert result.hour == 12
        assert result.minute == 0

    def test_epoch_round_trip(self, real_executor: ToolExecutor) -> None:
        result = self._round_trip(
            real_executor, {"year": 0, "month": "Hammer", "day": 1, "hour": 0, "minute": 0}
        )
        assert result.year == 0
        assert result.month == "Hammer"
        assert result.day == 1
        assert result.hour == 0
        assert result.minute == 0
