"""Tests for world-time mutation tool handler behaviour.

Covers:
- set_world_time initialize path (expected_revision=None)
- set_world_time update path (expected_revision=N)
- advance_world_time read/calculate/update flow
- advance_world_time signed-minute behaviour
- advance_world_time concurrency safety
- Calendar validation failure
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.calendar import (
    CalendarDefinition,
    CalendarMonth,
    GameDate,
    IntercalaryDay,
    WorldTick,
)
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode
from dnd_assistant.tools.world_time_mutations import (
    AdvanceWorldTimeOutput,
    SetWorldTimeOutput,
    register_world_time_mutation_tools,
)

# ── Test calendar definition ──────────────────────────────────────────────
_HARNER_CALENDAR = CalendarDefinition(
    calendar_id="harner",
    epoch=GameDate(year=0, month="Hammer", day=1),
    months=(CalendarMonth(name="Hammer", days=30), CalendarMonth(name="Alturiak", days=30)),
    intercalary_days=(IntercalaryDay(name="Midwinter", after_month="Hammer"),),
    hours_per_day=24,
    minutes_per_hour=60,
)


class _CallLog:
    """Shared call-log for cross-service ordering assertions."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, name: str) -> None:
        self.calls.append(name)


class FakeWorldTimeRepository:
    """Controllable fake implementing WorldTimeRepository protocol with call logging."""

    def __init__(
        self,
        state: CurrentWorldTime | None = None,
        call_log: _CallLog | None = None,
    ) -> None:
        self._state = state
        self._call_log = call_log
        self.last_world_tick: object = None
        self.last_expected_revision: object = None
        self.last_audit: object = None

    def get_current_world_time(self) -> CurrentWorldTime:
        if self._call_log:
            self._call_log.record("get_current_world_time")
        if self._state is None:
            raise NotFoundError(
                "world_time.json not found \u2014 current world time has not been initialized"
            )
        return self._state

    def initialize_current_world_time(
        self, world_tick: object, *, audit: object
    ) -> CurrentWorldTime:
        if self._call_log:
            self._call_log.record("initialize_current_world_time")
        self.last_world_tick = world_tick
        self.last_audit = audit
        if self._state is not None:
            raise ConflictError("world_time.json already exists")
        self._state = CurrentWorldTime(
            current_world_tick=WorldTick(world_tick),
            revision=1,
        )
        return self._state

    def set_current_world_time(
        self, world_tick: object, *, expected_revision: object, audit: object
    ) -> CurrentWorldTime:
        if self._call_log:
            self._call_log.record("set_current_world_time")
        self.last_world_tick = world_tick
        self.last_expected_revision = expected_revision
        self.last_audit = audit
        if self._state is None:
            raise NotFoundError("world_time.json not found")
        if self._state.revision != expected_revision:
            raise ConflictError(
                f"Revision mismatch: expected {expected_revision}, stored {self._state.revision}"
            )
        new_revision = self._state.revision + 1
        self._state = CurrentWorldTime(
            current_world_tick=WorldTick(world_tick),
            revision=new_revision,
        )
        return self._state


# ── Fake CalendarService for delegation tests ─────────────────────────────


class FakeCalendarService:
    """Controllable fake implementing CalendarService protocol with call logging."""

    def __init__(self, call_log: _CallLog | None = None) -> None:
        self._definition = _HARNER_CALENDAR
        self._call_log = call_log
        self.last_current_tick: int | None = None
        self.last_minutes: int | None = None

    @property
    def definition(self) -> CalendarDefinition:
        return self._definition

    def tick_to_date(self, tick: int) -> GameDate:
        return GameDate(year=1, month="Hammer", day=15, hour=6, minute=0)

    def date_to_tick(self, date: GameDate) -> int:
        return 0

    def time_until(self, start_tick: int, end_tick: int) -> int:
        return int(end_tick - start_tick)

    def advance_world_time(self, current_tick: int, *, minutes: int) -> int:
        if self._call_log:
            self._call_log.record("advance_world_time")
        self.last_current_tick = current_tick
        self.last_minutes = minutes
        # Return a distinctive value to prove handler uses CalendarService result
        return current_tick + minutes + 42

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
def call_log() -> _CallLog:
    return _CallLog()


@pytest.fixture
def initialized_repo() -> FakeWorldTimeRepository:
    return FakeWorldTimeRepository(
        state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
    )


@pytest.fixture
def uninitialized_repo() -> FakeWorldTimeRepository:
    return FakeWorldTimeRepository(state=None)


@pytest.fixture
def fake_calendar(call_log: _CallLog) -> FakeCalendarService:
    return FakeCalendarService(call_log=call_log)


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime(2026, 9, 2, tzinfo=UTC),
            source="test",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# set_world_time — initialize path (expected_revision=None)
# ═══════════════════════════════════════════════════════════════════════════


class TestSetWorldTimeInitialize:
    """expected_revision=None -> initialize_current_world_time called exactly once."""

    def test_initialize_called(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=uninitialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "set_world_time",
            input_data={"world_tick": 500},
            context=write_context,
        )
        assert isinstance(result, SetWorldTimeOutput)
        assert result.world_time.current_world_tick == 500
        assert result.world_time.revision == 1

    def test_initialize_uses_initialize_method(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None, call_log=call_log)
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 500},
            context=write_context,
        )
        assert call_log.calls == ["initialize_current_world_time"]

    def test_initialize_does_not_call_set_or_get(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None, call_log=call_log)
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 500},
            context=write_context,
        )
        assert "set_current_world_time" not in call_log.calls
        assert "get_current_world_time" not in call_log.calls

    def test_initialize_world_tick_forwarded(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None)
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 999},
            context=write_context,
        )
        assert repo.last_world_tick == 999

    def test_initialize_audit_forwarded(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None)
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 500},
            context=write_context,
        )
        assert repo.last_audit is write_context.audit

    def test_initialize_derived_date_uses_persisted_tick(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None)
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "set_world_time",
            input_data={"world_tick": 500},
            context=write_context,
        )
        assert result.game_date.month == "Hammer"
        assert result.game_date.day == 15
        assert result.calendar_id == "harner"

    def test_initialize_existing_state_raises_conflict(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError):
            executor.execute(
                "set_world_time",
                input_data={"world_tick": 500},
                context=write_context,
            )


# ═══════════════════════════════════════════════════════════════════════════
# set_world_time — update path (expected_revision=N)
# ═══════════════════════════════════════════════════════════════════════════


class TestSetWorldTimeUpdate:
    """expected_revision=N -> set_current_world_time called exactly once."""

    def test_update_called(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "set_world_time",
            input_data={"world_tick": 200, "expected_revision": 3},
            context=write_context,
        )
        assert isinstance(result, SetWorldTimeOutput)
        assert result.world_time.current_world_tick == 200
        assert result.world_time.revision == 4

    def test_update_uses_set_method(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
            call_log=call_log,
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 200, "expected_revision": 3},
            context=write_context,
        )
        assert call_log.calls == ["set_current_world_time"]

    def test_update_does_not_call_initialize_or_get(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
            call_log=call_log,
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 200, "expected_revision": 3},
            context=write_context,
        )
        assert "initialize_current_world_time" not in call_log.calls
        assert "get_current_world_time" not in call_log.calls

    def test_update_world_tick_forwarded(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 777, "expected_revision": 3},
            context=write_context,
        )
        assert repo.last_world_tick == 777

    def test_update_expected_revision_forwarded(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 200, "expected_revision": 3},
            context=write_context,
        )
        assert repo.last_expected_revision == 3

    def test_update_audit_forwarded(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "set_world_time",
            input_data={"world_tick": 200, "expected_revision": 3},
            context=write_context,
        )
        assert repo.last_audit is write_context.audit

    def test_update_missing_state_raises_not_found(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=uninitialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            executor.execute(
                "set_world_time",
                input_data={"world_tick": 500, "expected_revision": 1},
                context=write_context,
            )

    def test_update_stale_revision_raises_conflict(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError):
            executor.execute(
                "set_world_time",
                input_data={"world_tick": 200, "expected_revision": 2},
                context=write_context,
            )

    def test_update_derived_date_uses_persisted_tick(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "set_world_time",
            input_data={"world_tick": 200, "expected_revision": 3},
            context=write_context,
        )
        assert result.game_date.month == "Hammer"
        assert result.game_date.day == 15
        assert result.calendar_id == "harner"


# ═══════════════════════════════════════════════════════════════════════════
# advance_world_time — behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestAdvanceWorldTimeBehaviour:
    """Prove read/calculate/update flow with cross-service ordering."""

    def test_full_flow_correct_ordering(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
            call_log=call_log,
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=write_context,
        )
        assert call_log.calls == [
            "get_current_world_time",
            "advance_world_time",
            "set_current_world_time",
        ]

    def test_current_tick_forwarded_to_calendar(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=write_context,
        )
        assert fake_calendar.last_current_tick == 100
        assert fake_calendar.last_minutes == 5

    def test_calendar_result_used_for_repository(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        """Prove handler uses CalendarService result, not current+minutes."""
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=write_context,
        )
        # FakeCalendarService returns current_tick + minutes + 42 = 147
        # If handler naively did current+minutes, it would be 105
        assert repo.last_world_tick == 147

    def test_caller_expected_revision_forwarded(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=8),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 7},
                context=write_context,
            )
        # Must pass caller-supplied 7, not current.revision (8) — the
        # ConflictError proves the caller revision was forwarded.
        assert repo.last_expected_revision == 7

    def test_audit_forwarded(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=write_context,
        )
        assert repo.last_audit is write_context.audit

    def test_persisted_state_drives_output(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=write_context,
        )
        assert isinstance(result, AdvanceWorldTimeOutput)
        # FakeCalendarService returns 147, repo persists it at revision 4
        assert result.world_time.current_world_tick == 147
        assert result.world_time.revision == 4
        assert result.game_date.month == "Hammer"
        assert result.game_date.day == 15
        assert result.calendar_id == "harner"


# ═══════════════════════════════════════════════════════════════════════════
# advance_world_time — signed minutes
# ═══════════════════════════════════════════════════════════════════════════


class TestAdvanceSignedMinutes:
    """Positive, negative, and zero minutes are all accepted."""

    def test_positive_minutes(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "advance_world_time",
            input_data={"minutes": 10, "expected_revision": 3},
            context=write_context,
        )
        assert result.world_time.current_world_tick == 152  # 100 + 10 + 42

    def test_negative_minutes(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "advance_world_time",
            input_data={"minutes": -10, "expected_revision": 3},
            context=write_context,
        )
        assert result.world_time.current_world_tick == 132  # 100 + (-10) + 42

    def test_zero_minutes(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3),
        )
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "advance_world_time",
            input_data={"minutes": 0, "expected_revision": 3},
            context=write_context,
        )
        assert result.world_time.current_world_tick == 142  # 100 + 0 + 42


# ═══════════════════════════════════════════════════════════════════════════
# advance_world_time — concurrency safety
# ═══════════════════════════════════════════════════════════════════════════


class TestAdvanceConcurrencySafety:
    """Missing state, stale revision, and no implicit initialization."""

    def test_missing_state_raises_not_found(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=uninitialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 1},
                context=write_context,
            )

    def test_stale_revision_raises_conflict(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 2},
                context=write_context,
            )

    def test_no_implicit_initialization(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None, call_log=call_log)
        register_world_time_mutation_tools(
            registry,
            world_time_repository=repo,
            calendar_service=fake_calendar,
        )
        executor = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 1},
                context=write_context,
            )
        assert "initialize_current_world_time" not in call_log.calls


# ═══════════════════════════════════════════════════════════════════════════
# Calendar validation failure
# ═══════════════════════════════════════════════════════════════════════════


class TestCalendarValidationFailure:
    """CalendarService ValueError is translated to ValidationError."""

    def test_advance_value_error_translated(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        write_context: ExecutionContext,
    ) -> None:
        class BrokenCalendar:
            @property
            def definition(self):
                return _HARNER_CALENDAR

            def advance_world_time(self, current_tick: int, *, minutes: int) -> int:
                raise ValueError("Invalid time arithmetic")

            def tick_to_date(self, tick: int) -> GameDate:
                return GameDate(year=0, month="Hammer", day=1)

            def date_to_tick(self, date: GameDate) -> int:
                return 0

            def time_until(self, start: int, end: int) -> int:
                return end - start

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

        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=BrokenCalendar(),
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ValidationError, match="Invalid time arithmetic"):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 3},
                context=write_context,
            )

    def test_advance_runtime_error_propagates(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        write_context: ExecutionContext,
    ) -> None:
        class ExplodingCalendar:
            @property
            def definition(self):
                return _HARNER_CALENDAR

            def advance_world_time(self, current_tick: int, *, minutes: int) -> int:
                raise RuntimeError("internal explosion")

            def tick_to_date(self, tick: int) -> GameDate:
                return GameDate(year=0, month="Hammer", day=1)

            def date_to_tick(self, date: GameDate) -> int:
                return 0

            def time_until(self, start: int, end: int) -> int:
                return end - start

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

        register_world_time_mutation_tools(
            registry,
            world_time_repository=initialized_repo,
            calendar_service=ExplodingCalendar(),
        )
        executor = ToolExecutor(registry)
        with pytest.raises(RuntimeError, match="internal explosion"):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 3},
                context=write_context,
            )
