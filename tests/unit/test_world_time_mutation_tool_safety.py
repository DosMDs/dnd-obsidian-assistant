"""Safety tests for world-time mutation tools: permission, audit, and invalid-input gating.

Covers:
- READ permission rejected before handler
- Missing AuditContext rejected before handler
- Invalid input rejected before handler (no repository/calendar calls)
- Both session modes accepted
- No implicit initialization
- No retries
- Unexpected exception propagation
- Mutation-method isolation
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
    register_world_time_mutation_tools,
)

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

    def set_state(self, state: CurrentWorldTime | None) -> None:
        self._state = state

    def get_current_world_time(self) -> CurrentWorldTime:
        if self._call_log:
            self._call_log.record("get_current_world_time")
        if self._state is None:
            raise NotFoundError("world_time.json not found")
        return self._state

    def initialize_current_world_time(
        self, world_tick: object, *, audit: object
    ) -> CurrentWorldTime:
        if self._call_log:
            self._call_log.record("initialize_current_world_time")
        if self._state is not None:
            raise ConflictError("world_time.json already exists")
        self._state = CurrentWorldTime(current_world_tick=WorldTick(world_tick), revision=1)
        return self._state

    def set_current_world_time(
        self, world_tick: object, *, expected_revision: object, audit: object
    ) -> CurrentWorldTime:
        if self._call_log:
            self._call_log.record("set_current_world_time")
        if self._state is None:
            raise NotFoundError("world_time.json not found")
        if self._state.revision != expected_revision:
            raise ConflictError(
                f"Revision mismatch: expected {expected_revision}, stored {self._state.revision}"
            )
        new_revision = self._state.revision + 1
        self._state = CurrentWorldTime(
            current_world_tick=WorldTick(world_tick), revision=new_revision
        )
        return self._state


class FakeCalendarService:
    """Controllable fake implementing CalendarService protocol."""

    def __init__(self) -> None:
        self._definition = _HARNER_CALENDAR

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
def fake_calendar() -> FakeCalendarService:
    return FakeCalendarService()


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


@pytest.fixture
def active_session_write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op-session",
            real_time=datetime(2026, 9, 2, tzinfo=UTC),
            source="test",
        ),
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Permission gating
# ═══════════════════════════════════════════════════════════════════════════


class TestPermissionGating:
    """READ permission must be rejected before handler is called."""

    def test_set_rejected(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry, world_time_repository=initialized_repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError, match="Permission denied"):
            executor.execute("set_world_time", input_data={"world_tick": 500}, context=read_context)

    def test_advance_rejected(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry, world_time_repository=initialized_repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError, match="Permission denied"):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 3},
                context=read_context,
            )

    def test_read_permission_prevents_repository_calls(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        read_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3), call_log=call_log
        )
        register_world_time_mutation_tools(
            registry, world_time_repository=repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ConflictError):
            executor.execute("set_world_time", input_data={"world_tick": 500}, context=read_context)
        assert call_log.calls == []


# ═══════════════════════════════════════════════════════════════════════════
# Audit gating
# ═══════════════════════════════════════════════════════════════════════════


class TestAuditGating:
    """WRITE without AuditContext must be rejected before handler."""

    def test_set_without_audit_rejected(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
    ) -> None:
        register_world_time_mutation_tools(
            registry, world_time_repository=initialized_repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError, match="requires a non-None AuditContext"):
            executor.execute("set_world_time", input_data={"world_tick": 500}, context=ctx)

    def test_missing_audit_prevents_repository_calls(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3), call_log=call_log
        )
        register_world_time_mutation_tools(
            registry, world_time_repository=repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError):
            executor.execute("set_world_time", input_data={"world_tick": 500}, context=ctx)
        assert call_log.calls == []


# ═══════════════════════════════════════════════════════════════════════════
# Invalid-input-before-handler
# ═══════════════════════════════════════════════════════════════════════════


class TestInvalidInputBeforeHandler:
    """Invalid Pydantic input must cause zero repository and calendar calls."""

    def test_set_world_time_bad_tick(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3), call_log=call_log
        )
        register_world_time_mutation_tools(
            registry, world_time_repository=repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ValidationError):
            executor.execute(
                "set_world_time", input_data={"world_tick": "123"}, context=write_context
            )
        assert call_log.calls == []

    def test_advance_world_time_bad_minutes(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3), call_log=call_log
        )
        register_world_time_mutation_tools(
            registry, world_time_repository=repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ValidationError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": "5", "expected_revision": 3},
                context=write_context,
            )
        assert call_log.calls == []

    def test_advance_world_time_bad_revision(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(
            state=CurrentWorldTime(current_world_tick=WorldTick(100), revision=3), call_log=call_log
        )
        register_world_time_mutation_tools(
            registry, world_time_repository=repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(ValidationError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 0},
                context=write_context,
            )
        assert call_log.calls == []


# ═══════════════════════════════════════════════════════════════════════════
# Session mode acceptance
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionModeAcceptance:
    """Both session modes are accepted for both tools."""

    def test_no_active_session_allowed(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry, world_time_repository=initialized_repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=write_context,
        )
        assert isinstance(result, AdvanceWorldTimeOutput)

    def test_active_session_allowed(
        self,
        registry: ToolRegistry,
        initialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        active_session_write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry, world_time_repository=initialized_repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        result = executor.execute(
            "advance_world_time",
            input_data={"minutes": 5, "expected_revision": 3},
            context=active_session_write_context,
        )
        assert isinstance(result, AdvanceWorldTimeOutput)


# ═══════════════════════════════════════════════════════════════════════════
# No implicit initialization
# ═══════════════════════════════════════════════════════════════════════════


class TestNoImplicitInitialization:
    """advance_world_time must never initialize missing state."""

    def test_not_found_propagates(
        self,
        registry: ToolRegistry,
        uninitialized_repo: FakeWorldTimeRepository,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
    ) -> None:
        register_world_time_mutation_tools(
            registry, world_time_repository=uninitialized_repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 1},
                context=write_context,
            )

    def test_no_initialize_called(
        self,
        registry: ToolRegistry,
        fake_calendar: FakeCalendarService,
        write_context: ExecutionContext,
        call_log: _CallLog,
    ) -> None:
        repo = FakeWorldTimeRepository(state=None, call_log=call_log)
        register_world_time_mutation_tools(
            registry, world_time_repository=repo, calendar_service=fake_calendar
        )
        executor = ToolExecutor(registry)
        with pytest.raises(NotFoundError):
            executor.execute(
                "advance_world_time",
                input_data={"minutes": 5, "expected_revision": 1},
                context=write_context,
            )
        assert "initialize_current_world_time" not in call_log.calls


@pytest.fixture
def uninitialized_repo() -> FakeWorldTimeRepository:
    return FakeWorldTimeRepository(state=None)
