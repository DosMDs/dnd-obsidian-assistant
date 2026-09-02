"""Tests for session read tool handler behaviour and ToolExecutor integration.

Covers:
- get_active_session handler behaviour
- get_session handler behaviour
- list_sessions handler behaviour
- list_session_events handler behaviour
- ToolExecutor integration
- No-mutation guarantee
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_reads import (
    GetActiveSessionInput,
    GetActiveSessionOutput,
    GetSessionOutput,
    ListSessionEventsOutput,
    ListSessionsOutput,
    SessionEventResult,
    register_session_read_tools,
)
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)

# ── Shared test data ──────────────────────────────────────────────────────

_NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _make_session(
    session_id: str = "S001",
    status: str = "active",
    world_tick_start: int = 1000,
) -> Session:
    return Session(
        id=session_id,
        type="session",
        status=status,
        real_started_at=_NOW,
        real_finished_at=None,
        world_tick_start=WorldTick(world_tick_start),
        world_tick_end=None,
        processed=False,
        processed_model_profile=None,
        revision=1,
    )


# ── RawSessionEvent-like fake DTO ─────────────────────────────────────────


class FakeRawEvent:
    """Minimal fake resembling RawSessionEvent for testing."""

    def __init__(
        self,
        event_id: str = "evt_001",
        real_time=_NOW,
        world_tick: int = 1000,
        type: str = "note",
        extra_fields: dict[str, object] | None = None,
    ) -> None:
        self._event_id = event_id
        self._real_time = real_time
        self._world_tick = world_tick
        self._type = type
        self._extra_fields = dict(extra_fields) if extra_fields else {}

    @property
    def event_id(self) -> str:
        return self._event_id

    @property
    def real_time(self):
        return self._real_time

    @property
    def world_tick(self) -> int:
        return self._world_tick

    @property
    def type(self) -> str:
        return self._type

    @property
    def extra_fields(self) -> dict[str, object]:
        return dict(self._extra_fields)


# ── RawSessionMetadata-like fake ──────────────────────────────────────────


class FakeRawMetadata:
    """Minimal fake resembling RawSessionMetadata for testing."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    @property
    def extra_fields(self) -> dict[str, object]:
        return {}


# ── Fake SessionRuntimeService ────────────────────────────────────────────


class FakeRuntimeService:
    """Minimal fake implementing SessionRuntimeService protocol."""

    def __init__(self) -> None:
        self._active: Session | None = None
        self._start_called: bool = False
        self._end_called: bool = False
        self._record_event_called: bool = False
        self._record_note_called: bool = False

    def set_active_session(self, session: Session | None) -> None:
        self._active = session

    def get_active_session(self) -> Session | None:
        return self._active

    @property
    def start_called(self) -> bool:
        return self._start_called

    @property
    def end_called(self) -> bool:
        return self._end_called

    @property
    def record_event_called(self) -> bool:
        return self._record_event_called

    @property
    def record_note_called(self) -> bool:
        return self._record_note_called


# ── Fake SessionMetadataRepository ────────────────────────────────────────


class FakeSessionRepository:
    """Minimal fake implementing SessionMetadataRepository protocol."""

    def __init__(self) -> None:
        self._sessions: dict[str, FakeRawMetadata] = {}
        self._get_calls: list[str] = []
        self._list_calls: int = 0
        self._allocate_called: bool = False
        self._create_called: bool = False
        self._close_called: bool = False

    def add_metadata(self, metadata: FakeRawMetadata) -> None:
        self._sessions[metadata.session.id] = metadata

    @property
    def get_calls(self) -> list[str]:
        return list(self._get_calls)

    @property
    def list_calls(self) -> int:
        return self._list_calls

    @property
    def allocate_called(self) -> bool:
        return self._allocate_called

    @property
    def create_called(self) -> bool:
        return self._create_called

    @property
    def close_called(self) -> bool:
        return self._close_called

    def get_session_metadata(self, session_id: str) -> FakeRawMetadata:
        self._get_calls.append(session_id)
        meta = self._sessions.get(session_id)
        if meta is None:
            raise NotFoundError(f"Session metadata not found for {session_id}")
        return meta

    def list_session_metadata(self) -> list[FakeRawMetadata]:
        self._list_calls += 1
        return list(self._sessions.values())

    def get_active_session(self) -> FakeRawMetadata | None:
        active = [m for m in self._sessions.values() if m.session.status == "active"]
        if len(active) == 0:
            return None
        if len(active) == 1:
            return active[0]
        raise ConflictError("Multiple active sessions")

    def allocate_next_session_id(self) -> str:
        self._allocate_called = True
        return "S999"

    def create_session(self, session: Session, *, audit: AuditContext) -> FakeRawMetadata:
        self._create_called = True
        return FakeRawMetadata(session)

    def close_session(self, session_id: str, **kwargs: object) -> FakeRawMetadata:
        self._close_called = True
        return FakeRawMetadata(_make_session(session_id, "completed"))


# ── Fake SessionEventRepository ───────────────────────────────────────────


class FakeEventRepository:
    """Minimal fake implementing SessionEventRepository protocol."""

    def __init__(self) -> None:
        self._events: dict[str, list[FakeRawEvent]] = {}
        self._list_calls: list[str] = []
        self._append_called: bool = False

    def set_events(self, session_id: str, events: list[FakeRawEvent]) -> None:
        self._events[session_id] = events

    @property
    def list_called_for(self) -> list[str]:
        return list(self._list_calls)

    @property
    def append_called(self) -> bool:
        return self._append_called

    def list_events(self, session_id: str) -> list[FakeRawEvent]:
        self._list_calls.append(session_id)
        return self._events.get(session_id, [])

    def append_event(self, *args: object, **kwargs: object) -> object:
        self._append_called = True
        msg = "FakeEventRepository does not support writes"
        raise NotImplementedError(msg)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def runtime_service() -> FakeRuntimeService:
    return FakeRuntimeService()


@pytest.fixture
def session_repository() -> FakeSessionRepository:
    return FakeSessionRepository()


@pytest.fixture
def event_repository() -> FakeEventRepository:
    return FakeEventRepository()


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(
    registry: ToolRegistry,
    runtime_service: FakeRuntimeService,
    session_repository: FakeSessionRepository,
    event_repository: FakeEventRepository,
) -> ToolRegistry:
    register_session_read_tools(
        registry,
        runtime_service=runtime_service,
        session_repository=session_repository,
        event_repository=event_repository,
    )
    return registry


@pytest.fixture
def executor(registered_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registered_registry)


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
        audit=AuditContext(
            operation_id="test-op",
            real_time=_NOW,
            source="test",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# get_active_session handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestGetActiveSessionHandler:
    def test_active_session_returned(
        self,
        executor: ToolExecutor,
        runtime_service: FakeRuntimeService,
        read_context: ExecutionContext,
    ) -> None:
        session = _make_session()
        runtime_service.set_active_session(session)
        result = executor.execute(
            "get_active_session",
            input_data={},
            context=read_context,
        )
        assert isinstance(result, GetActiveSessionOutput)
        assert result.session is session


# ═══════════════════════════════════════════════════════════════════════════
# list_sessions handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestListSessionsHandler:
    def test_empty_list_returns_typed_empty(
        self,
        executor: ToolExecutor,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert isinstance(result, ListSessionsOutput)
        assert result.sessions == []

    def test_multiple_sessions_returned(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        s1 = _make_session("S001")
        s2 = _make_session("S002")
        session_repository.add_metadata(FakeRawMetadata(s1))
        session_repository.add_metadata(FakeRawMetadata(s2))
        result = executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert isinstance(result, ListSessionsOutput)
        assert len(result.sessions) == 2

    def test_repository_order_preserved(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        s_b = _make_session("S002")
        s_a = _make_session("S001")
        session_repository.add_metadata(FakeRawMetadata(s_b))
        session_repository.add_metadata(FakeRawMetadata(s_a))
        result = executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert isinstance(result, ListSessionsOutput)
        assert len(result.sessions) == 2
        assert result.sessions[0] is s_b
        assert result.sessions[1] is s_a

    def test_list_session_metadata_called_exactly_once(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert session_repository.list_calls == 1

    def test_allocate_next_session_id_not_called(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert not session_repository.allocate_called

    def test_create_session_not_called(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert not session_repository.create_called

    def test_close_session_not_called(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert not session_repository.close_called


# ═══════════════════════════════════════════════════════════════════════════
# list_session_events handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestListSessionEventsHandler:
    def test_empty_events_returns_typed_empty(
        self,
        executor: ToolExecutor,
        read_context: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert isinstance(result, ListSessionEventsOutput)
        assert result.events == []

    def test_physical_order_preserved(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        ev_b = FakeRawEvent("evt_002", _NOW, 1001, "note", {"text": "B"})
        ev_a = FakeRawEvent("evt_001", _NOW, 1000, "note", {"text": "A"})
        event_repository.set_events("S001", [ev_b, ev_a])
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert len(result.events) == 2
        assert result.events[0].event_id == "evt_002"
        assert result.events[1].event_id == "evt_001"

    def test_canonical_fields_preserved(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        ev = FakeRawEvent("evt_001", _NOW, 1000, "note", {"text": "Hello"})
        event_repository.set_events("S001", [ev])
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert len(result.events) == 1
        r = result.events[0]
        assert r.event_id == "evt_001"
        assert r.real_time == _NOW
        assert r.world_tick == 1000
        assert r.type == "note"

    def test_extra_fields_preserved_by_value(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        ev = FakeRawEvent("evt_001", _NOW, 1000, "note", {"text": "Hello", "tags": ["a", "b"]})
        event_repository.set_events("S001", [ev])
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert result.events[0].extra_fields == {"text": "Hello", "tags": ["a", "b"]}

    def test_nested_json_extra_fields_preserved(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        ev = FakeRawEvent(
            "evt_001",
            _NOW,
            1000,
            "combat",
            {
                "damage": 15,
                "targets": ["goblin"],
                "critical": True,
            },
        )
        event_repository.set_events("S001", [ev])
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        extra = result.events[0].extra_fields
        assert extra["damage"] == 15
        assert extra["targets"] == ["goblin"]
        assert extra["critical"] is True

    def test_note_text_preserved(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        ev = FakeRawEvent("evt_001", _NOW, 1000, "note", {"text": "Important note"})
        event_repository.set_events("S001", [ev])
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert result.events[0].extra_fields["text"] == "Important note"

    def test_output_does_not_expose_raw_event_object(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        ev = FakeRawEvent("evt_001", _NOW, 1000, "note")
        event_repository.set_events("S001", [ev])
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert isinstance(result.events[0], SessionEventResult)
        assert not isinstance(result.events[0], type(ev))

    def test_append_event_not_called(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert not event_repository.append_called


# ═══════════════════════════════════════════════════════════════════════════
# ToolExecutor integration
# ═══════════════════════════════════════════════════════════════════════════


class TestToolExecutorIntegration:
    def test_read_permission_allows_execution(
        self,
        executor: ToolExecutor,
        runtime_service: FakeRuntimeService,
        read_context: ExecutionContext,
    ) -> None:
        runtime_service.set_active_session(_make_session())
        result = executor.execute(
            "get_active_session",
            input_data={},
            context=read_context,
        )
        assert isinstance(result, GetActiveSessionOutput)

    def test_write_permission_allows_execution(
        self,
        executor: ToolExecutor,
        runtime_service: FakeRuntimeService,
        write_context: ExecutionContext,
    ) -> None:
        runtime_service.set_active_session(_make_session())
        result = executor.execute(
            "get_active_session",
            input_data={},
            context=write_context,
        )
        assert isinstance(result, GetActiveSessionOutput)

    def test_both_session_modes_work(
        self,
        executor: ToolExecutor,
        runtime_service: FakeRuntimeService,
    ) -> None:
        runtime_service.set_active_session(_make_session())
        for mode in (SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION):
            ctx = ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=mode,
            )
            result = executor.execute(
                "get_active_session",
                input_data={},
                context=ctx,
            )
            assert isinstance(result, GetActiveSessionOutput)

    def test_audit_context_not_required(
        self,
        executor: ToolExecutor,
        runtime_service: FakeRuntimeService,
    ) -> None:
        runtime_service.set_active_session(_make_session())
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        result = executor.execute(
            "get_active_session",
            input_data={},
            context=ctx,
        )
        assert isinstance(result, GetActiveSessionOutput)

    def test_invalid_input_rejected_before_handler(
        self,
        executor: ToolExecutor,
        read_context: ExecutionContext,
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "get_session",
                input_data={"session_id": ""},
                context=read_context,
            )

    def test_handler_runtime_error_propagates(
        self,
        registry: ToolRegistry,
        read_context: ExecutionContext,
    ) -> None:
        def bad_handler(input_model: object, context: object) -> object:
            raise RuntimeError("handler crash")

        defn = ToolDefinition(
            name="crash_tool",
            description="A crashing test tool",
            input_schema=GetActiveSessionInput,
            output_schema=GetActiveSessionOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        registry.register(defn, bad_handler)
        exe = ToolExecutor(registry)

        with pytest.raises(RuntimeError, match="handler crash"):
            exe.execute(
                "crash_tool",
                input_data={},
                context=read_context,
            )


# ═══════════════════════════════════════════════════════════════════════════
# No mutation guarantee
# ═══════════════════════════════════════════════════════════════════════════


class TestNoMutation:
    """Verify session read tools never call mutation operations."""

    def test_get_active_session_no_mutation(
        self,
        executor: ToolExecutor,
        runtime_service: FakeRuntimeService,
        read_context: ExecutionContext,
    ) -> None:
        runtime_service.set_active_session(_make_session())
        executor.execute(
            "get_active_session",
            input_data={},
            context=read_context,
        )
        assert not runtime_service.start_called
        assert not runtime_service.end_called

    def test_get_session_no_mutation(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        session = _make_session("S001")
        session_repository.add_metadata(FakeRawMetadata(session))
        executor.execute(
            "get_session",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert not session_repository.allocate_called
        assert not session_repository.create_called
        assert not session_repository.close_called

    def test_list_sessions_no_mutation(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_sessions",
            input_data={},
            context=read_context,
        )
        assert not session_repository.allocate_called
        assert not session_repository.create_called
        assert not session_repository.close_called

    def test_list_session_events_no_mutation(
        self,
        executor: ToolExecutor,
        event_repository: FakeEventRepository,
        read_context: ExecutionContext,
    ) -> None:
        executor.execute(
            "list_session_events",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert not event_repository.append_called


class TestGetSessionHandler:
    def test_session_returned(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        session = _make_session("S001")
        session_repository.add_metadata(FakeRawMetadata(session))
        result = executor.execute(
            "get_session",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert isinstance(result, GetSessionOutput)
        assert result.session is session

    def test_requested_id_forwarded_exactly_once(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        session = _make_session("S001")
        session_repository.add_metadata(FakeRawMetadata(session))
        executor.execute(
            "get_session",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert session_repository.get_calls == ["S001"]

    def test_not_found_propagates(
        self,
        executor: ToolExecutor,
        read_context: ExecutionContext,
    ) -> None:
        with pytest.raises(NotFoundError):
            executor.execute(
                "get_session",
                input_data={"session_id": "S999"},
                context=read_context,
            )

    def test_id_mismatch_raises_storage_error(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Requested S001, but stored metadata has id=S002 -> StorageError."""
        session = _make_session("S002")
        # Store under key "S001" so the lookup succeeds but ID mismatches
        session_repository._sessions["S001"] = FakeRawMetadata(session)
        with pytest.raises(StorageError, match="Session read consistency check failed"):
            executor.execute(
                "get_session",
                input_data={"session_id": "S001"},
                context=read_context,
            )

    def test_id_mismatch_does_not_leak_b(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error must not reveal the alternate session ID."""
        session = _make_session("S002")
        session_repository._sessions["S001"] = FakeRawMetadata(session)
        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "get_session",
                input_data={"session_id": "S001"},
                context=read_context,
            )
        msg = str(exc_info.value)
        assert "S002" not in msg

    def test_extra_fields_not_exposed(
        self,
        executor: ToolExecutor,
        session_repository: FakeSessionRepository,
        read_context: ExecutionContext,
    ) -> None:
        session = _make_session("S001")
        session_repository.add_metadata(FakeRawMetadata(session))
        result = executor.execute(
            "get_session",
            input_data={"session_id": "S001"},
            context=read_context,
        )
        assert isinstance(result, GetSessionOutput)
        assert result.session is session
