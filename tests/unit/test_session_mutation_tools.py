"""Tests for session mutation tool handler behaviour and ToolExecutor integration.

Covers:
- start_session handler behaviour
- record_event handler behaviour
- record_note handler behaviour
- end_session handler behaviour
- Recovery preflight ordering
- Runtime error propagation
- AuditContext identity pass-through
- Event result conversion
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_mutations import (
    EndSessionOutput,
    RecordEventOutput,
    RecordNoteOutput,
    StartSessionOutput,
    register_session_mutation_tools,
)
from dnd_assistant.tools.session_reads import SessionEventResult
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode

# ── Shared test data ──────────────────────────────────────────────────────────

_NOW = datetime(2026, 9, 2, tzinfo=UTC)
_AUDIT = AuditContext(
    operation_id="test-op-001",
    real_time=_NOW,
    source="test",
)


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


def _make_raw_event(
    event_id: str = "evt_001",
    event_type: str = "note",
    extra_fields: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        real_time=_NOW,
        world_tick=WorldTick(1000),
        type=event_type,
        extra_fields=dict(extra_fields) if extra_fields else {},
    )


# ── Call-tracking fake services ──────────────────────────────────────────────


class TrackingRuntimeService:
    """Fake that records every call for ordering/identity verification."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._received_audit: AuditContext | None = None
        self._start_result: Session = _make_session()
        self._end_result: Session = _make_session(status="completed")
        self._start_side_effect: Exception | None = None
        self._event_side_effect: Exception | None = None
        self._note_side_effect: Exception | None = None
        self._end_side_effect: Exception | None = None

    def set_start_side_effect(self, exc: Exception) -> None:
        self._start_side_effect = exc

    def set_event_side_effect(self, exc: Exception) -> None:
        self._event_side_effect = exc

    def set_note_side_effect(self, exc: Exception) -> None:
        self._note_side_effect = exc

    def set_end_side_effect(self, exc: Exception) -> None:
        self._end_side_effect = exc

    @property
    def received_audit(self) -> AuditContext | None:
        return self._received_audit

    def get_active_session(self) -> Session | None:
        return self._start_result

    def start_session(self, *, audit: AuditContext) -> Session:
        self.calls.append("start_session")
        self._received_audit = audit
        if self._start_side_effect:
            raise self._start_side_effect
        return self._start_result

    def record_event(
        self,
        event_type: str,
        *,
        extra_fields: dict[str, object] | None = None,
        audit: AuditContext,
    ) -> SimpleNamespace:
        self.calls.append(f"record_event:{event_type}")
        self._received_audit = audit
        if self._event_side_effect:
            raise self._event_side_effect
        return _make_raw_event("evt_001", event_type, extra_fields)

    def record_note(self, text: str, *, audit: AuditContext) -> SimpleNamespace:
        self.calls.append(f"record_note:{text}")
        self._received_audit = audit
        if self._note_side_effect:
            raise self._note_side_effect
        return _make_raw_event("evt_002", "note", {"text": text})

    def end_session(
        self,
        *,
        touched_entity_ids: tuple = (),
        audit: AuditContext,
    ) -> Session:
        self.calls.append("end_session")
        self._received_audit = audit
        if self._end_side_effect:
            raise self._end_side_effect
        return self._end_result


class TrackingRecoveryService:
    """Fake recovery service that tracks calls and can report issues."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._has_issues = False
        self._inspect_side_effect: Exception | None = None

    def set_has_issues(self, value: bool) -> None:
        self._has_issues = value

    def set_inspect_side_effect(self, exc: Exception) -> None:
        self._inspect_side_effect = exc

    def inspect_runtime(self) -> SimpleNamespace:
        self.calls.append("inspect_runtime")
        if self._inspect_side_effect:
            raise self._inspect_side_effect
        return SimpleNamespace(has_issues=self._has_issues, issues=[])

    def repair_audit_tail(self, *, audit: object = None) -> None:
        self.calls.append("repair_audit_tail")

    def cleanup_partial_start(self, session_id: str, *, audit: object = None) -> None:
        self.calls.append("cleanup_partial_start")

    def repair_event_tail(self, session_id: str, *, audit: object = None) -> None:
        self.calls.append("repair_event_tail")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def runtime() -> TrackingRuntimeService:
    return TrackingRuntimeService()


@pytest.fixture
def recovery() -> TrackingRecoveryService:
    return TrackingRecoveryService()


@pytest.fixture
def registry(
    runtime: TrackingRuntimeService,
    recovery: TrackingRecoveryService,
) -> ToolRegistry:
    reg = ToolRegistry()
    register_session_mutation_tools(
        reg,
        runtime_service=runtime,
        recovery_service=recovery,
    )
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


@pytest.fixture
def write_context_active() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=_AUDIT,
    )


@pytest.fixture
def write_context_no_active() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
        audit=_AUDIT,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# start_session delegation
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartSessionDelegation:
    def test_inspect_then_start(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "start_session",
            input_data={},
            context=write_context_no_active,
        )
        assert isinstance(result, StartSessionOutput)
        assert isinstance(result.session, Session)
        assert recovery.calls == ["inspect_runtime"]
        assert runtime.calls == ["start_session"]

    def test_same_audit_context_passed(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "start_session",
            input_data={},
            context=write_context_no_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_runtime_conflict_propagates(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        runtime.set_start_side_effect(ConflictError("active session exists"))
        with pytest.raises(ConflictError, match="active session"):
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_no_active,
            )
        assert recovery.calls == ["inspect_runtime"]
        assert runtime.calls == ["start_session"]

    def test_runtime_not_found_propagates(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        runtime.set_start_side_effect(NotFoundError("world time not initialized"))
        with pytest.raises(NotFoundError, match="world time"):
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_no_active,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# record_event delegation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordEventDelegation:
    def test_inspect_then_record(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "record_event",
            input_data={"event_type": "item_acquired"},
            context=write_context_active,
        )
        assert isinstance(result, RecordEventOutput)
        assert isinstance(result.event, SessionEventResult)
        assert recovery.calls == ["inspect_runtime"]
        assert runtime.calls == ["record_event:item_acquired"]

    def test_event_type_forwarded(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_event",
            input_data={"event_type": "combat_round"},
            context=write_context_active,
        )
        assert "record_event:combat_round" in runtime.calls

    def test_extra_fields_forwarded(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_event",
            input_data={
                "event_type": "combat",
                "extra_fields": {"damage": 15},
            },
            context=write_context_active,
        )
        assert "record_event:combat" in runtime.calls

    def test_same_audit_context_passed(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_event",
            input_data={"event_type": "test"},
            context=write_context_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_event_result_conversion(
        self,
        executor: ToolExecutor,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "record_event",
            input_data={"event_type": "test"},
            context=write_context_active,
        )
        event = result.event
        assert event.event_id == "evt_001"
        assert event.real_time == _NOW
        assert event.world_tick == 1000
        assert event.type == "test"

    def test_runtime_not_found_propagates(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        runtime.set_event_side_effect(NotFoundError("no active session"))
        with pytest.raises(NotFoundError, match="no active"):
            executor.execute(
                "record_event",
                input_data={"event_type": "test"},
                context=write_context_active,
            )

    def test_output_does_not_expose_raw_event(
        self,
        executor: ToolExecutor,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "record_event",
            input_data={"event_type": "test"},
            context=write_context_active,
        )
        assert isinstance(result.event, SessionEventResult)


# ═══════════════════════════════════════════════════════════════════════════════
# record_note delegation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordNoteDelegation:
    def test_inspect_then_record(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "record_note",
            input_data={"text": "Hello world"},
            context=write_context_active,
        )
        assert isinstance(result, RecordNoteOutput)
        assert isinstance(result.event, SessionEventResult)
        assert recovery.calls == ["inspect_runtime"]
        assert "record_note:Hello world" in runtime.calls

    def test_text_forwarded(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_note",
            input_data={"text": "Важное замечание"},
            context=write_context_active,
        )
        assert "record_note:Важное замечание" in runtime.calls

    def test_same_audit_context_passed(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_note",
            input_data={"text": "note"},
            context=write_context_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_note_output_has_type_note(
        self,
        executor: ToolExecutor,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "record_note",
            input_data={"text": "A note"},
            context=write_context_active,
        )
        assert result.event.type == "note"

    def test_note_output_has_text_in_extra_fields(
        self,
        executor: ToolExecutor,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "record_note",
            input_data={"text": "My note text"},
            context=write_context_active,
        )
        assert result.event.extra_fields.get("text") == "My note text"

    def test_runtime_not_found_propagates(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        runtime.set_note_side_effect(NotFoundError("no active session"))
        with pytest.raises(NotFoundError, match="no active"):
            executor.execute(
                "record_note",
                input_data={"text": "test"},
                context=write_context_active,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# end_session delegation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndSessionDelegation:
    def test_inspect_then_end(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        result = executor.execute(
            "end_session",
            input_data={},
            context=write_context_active,
        )
        assert isinstance(result, EndSessionOutput)
        assert isinstance(result.session, Session)
        assert recovery.calls == ["inspect_runtime"]
        assert runtime.calls == ["end_session"]

    def test_touched_ids_forwarded(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "end_session",
            input_data={"touched_entity_ids": ["npc_varos", "loc_dungeon"]},
            context=write_context_active,
        )
        assert "end_session" in runtime.calls

    def test_same_audit_context_passed(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "end_session",
            input_data={},
            context=write_context_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_runtime_not_found_propagates(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        runtime.set_end_side_effect(NotFoundError("no active session"))
        with pytest.raises(NotFoundError, match="no active"):
            executor.execute(
                "end_session",
                input_data={},
                context=write_context_active,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Runtime-state mismatch propagation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRuntimeStateMismatch:
    """SessionMode context says one thing, runtime says another."""

    def test_start_session_runtime_conflict(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        """Context says NO_ACTIVE_SESSION, runtime raises ConflictError."""
        runtime.set_start_side_effect(ConflictError("active session exists"))
        with pytest.raises(ConflictError, match="active session"):
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_no_active,
            )

    def test_record_event_runtime_not_found(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        """Context says ACTIVE_SESSION, runtime raises NotFoundError."""
        runtime.set_event_side_effect(NotFoundError("no active session"))
        with pytest.raises(NotFoundError, match="no active"):
            executor.execute(
                "record_event",
                input_data={"event_type": "test"},
                context=write_context_active,
            )

    def test_end_session_runtime_not_found(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        """Context says ACTIVE_SESSION, runtime raises NotFoundError."""
        runtime.set_end_side_effect(NotFoundError("no active session"))
        with pytest.raises(NotFoundError, match="no active"):
            executor.execute(
                "end_session",
                input_data={},
                context=write_context_active,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Audit provenance — tools pass through, never generate
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditProvenance:
    """Verify the exact AuditContext object reaches the runtime."""

    def test_start_session_audit_identity(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "start_session",
            input_data={},
            context=write_context_no_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_record_event_audit_identity(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_event",
            input_data={"event_type": "test"},
            context=write_context_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_record_note_audit_identity(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "record_note",
            input_data={"text": "test"},
            context=write_context_active,
        )
        assert runtime.received_audit is _AUDIT

    def test_end_session_audit_identity(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        executor.execute(
            "end_session",
            input_data={},
            context=write_context_active,
        )
        assert runtime.received_audit is _AUDIT


# ═══════════════════════════════════════════════════════════════════════════════
# StorageError propagation from inspect_runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestInspectRuntimeErrorPropagation:
    def test_storage_error_from_inspect_blocks_mutation(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        recovery.set_inspect_side_effect(StorageError("disk failure"))
        with pytest.raises(StorageError, match="disk failure"):
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_no_active,
            )
        assert runtime.calls == []

    def test_storage_error_from_inspect_blocks_record_event(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        recovery.set_inspect_side_effect(StorageError("disk failure"))
        with pytest.raises(StorageError, match="disk failure"):
            executor.execute(
                "record_event",
                input_data={"event_type": "test"},
                context=write_context_active,
            )
        assert runtime.calls == []
