"""Safety tests for session mutation tools: permission/mode/audit gating, recovery preflight.

Covers:
- READ permission blocks all mutation tools before preflight
- Missing AuditContext blocks WRITE tools before preflight
- Wrong SessionMode blocks before preflight
- Recovery issues block mutation with generic error
- Recovery repair methods never called from tools
- No direct repository/audit/filesystem mutation in tools
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_mutations import register_session_mutation_tools
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode

# ── Shared test data ──────────────────────────────────────────────────────────

_NOW = datetime(2026, 9, 2, tzinfo=UTC)
_AUDIT = AuditContext(
    operation_id="test-op-001",
    real_time=_NOW,
    source="test",
)

_MUTATION_TOOLS = ("start_session", "record_event", "record_note", "end_session")


def _make_session() -> Session:
    return Session(
        id="S001",
        type="session",
        status="active",
        real_started_at=_NOW,
        real_finished_at=None,
        world_tick_start=WorldTick(1000),
        world_tick_end=None,
        processed=False,
        processed_model_profile=None,
        revision=1,
    )


# ── Tracking fakes ────────────────────────────────────────────────────────────


class TrackingRuntimeService:
    """Tracks calls to prove mutation is never invoked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_active_session(self) -> Session | None:
        return _make_session()

    def start_session(self, *, audit: object) -> Session:
        self.calls.append("start_session")
        return _make_session()

    def record_event(self, event_type: str, **kwargs: object) -> object:
        self.calls.append(f"record_event:{event_type}")
        return SimpleNamespace(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type=event_type,
            extra_fields={},
        )

    def record_note(self, text: str, **kwargs: object) -> object:
        self.calls.append(f"record_note:{text}")
        return SimpleNamespace(
            event_id="evt_002",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="note",
            extra_fields={"text": text},
        )

    def end_session(self, **kwargs: object) -> Session:
        self.calls.append("end_session")
        return _make_session()


class TrackingRecoveryService:
    """Tracks calls to prove preflight ordering and no auto-repair."""

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


# ── Context fixtures for gating tests ─────────────────────────────────────────


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.ACTIVE_SESSION,
    )


@pytest.fixture
def write_no_audit_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


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
# READ permission blocks all mutation tools before preflight
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadPermissionBlocksMutation:
    @pytest.mark.parametrize("tool_name", _MUTATION_TOOLS)
    def test_read_permission_rejected(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        read_context: ExecutionContext,
        tool_name: str,
    ) -> None:
        input_data: dict[str, object] = {}
        if tool_name == "record_event":
            input_data = {"event_type": "test"}
        elif tool_name == "record_note":
            input_data = {"text": "test"}
        elif tool_name == "end_session":
            input_data = {}

        with pytest.raises(ConflictError, match="Permission denied"):
            executor.execute(
                tool_name,
                input_data=input_data,
                context=read_context,
            )
        assert recovery.calls == [], f"{tool_name}: inspect should not be called"
        assert runtime.calls == [], f"{tool_name}: runtime should not be called"


# ═══════════════════════════════════════════════════════════════════════════════
# Missing AuditContext blocks WRITE tools before preflight
# ═══════════════════════════════════════════════════════════════════════════════


class TestMissingAuditBlocksMutation:
    @pytest.mark.parametrize(
        "tool_name, mode",
        [
            ("start_session", SessionMode.NO_ACTIVE_SESSION),
            ("record_event", SessionMode.ACTIVE_SESSION),
            ("record_note", SessionMode.ACTIVE_SESSION),
            ("end_session", SessionMode.ACTIVE_SESSION),
        ],
    )
    def test_missing_audit_rejected(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        tool_name: str,
        mode: SessionMode,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=mode,
            audit=None,
        )
        input_data: dict[str, object] = {}
        if tool_name == "record_event":
            input_data = {"event_type": "test"}
        elif tool_name == "record_note":
            input_data = {"text": "test"}

        with pytest.raises(ValidationError, match="AuditContext"):
            executor.execute(
                tool_name,
                input_data=input_data,
                context=ctx,
            )
        assert recovery.calls == [], f"{tool_name}: inspect should not be called"
        assert runtime.calls == [], f"{tool_name}: runtime should not be called"


# ═══════════════════════════════════════════════════════════════════════════════
# Wrong SessionMode blocks before preflight
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrongSessionModeBlocksMutation:
    def test_start_session_with_active_rejected(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_active: ExecutionContext,
    ) -> None:
        with pytest.raises(ConflictError, match="Session mode"):
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_active,
            )
        assert recovery.calls == []
        assert runtime.calls == []

    @pytest.mark.parametrize("tool_name", ("record_event", "record_note", "end_session"))
    def test_active_tool_with_no_active_rejected(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
        tool_name: str,
    ) -> None:
        input_data: dict[str, object] = {}
        if tool_name == "record_event":
            input_data = {"event_type": "test"}
        elif tool_name == "record_note":
            input_data = {"text": "test"}

        with pytest.raises(ConflictError, match="Session mode"):
            executor.execute(
                tool_name,
                input_data=input_data,
                context=write_context_no_active,
            )
        assert recovery.calls == []
        assert runtime.calls == []


# ═══════════════════════════════════════════════════════════════════════════════
# Recovery issues block mutation — generic error, no auto-repair
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecoveryIssuesBlockMutation:
    @pytest.fixture
    def recovery_with_issues(self, recovery: TrackingRecoveryService) -> TrackingRecoveryService:
        recovery.set_has_issues(True)
        return recovery

    @pytest.mark.parametrize("tool_name", _MUTATION_TOOLS)
    def test_recovery_issues_block(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery_with_issues: TrackingRecoveryService,
        tool_name: str,
    ) -> None:
        input_data: dict[str, object] = {}
        ctx: ExecutionContext
        if tool_name == "start_session":
            ctx = ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=_AUDIT,
            )
        else:
            ctx = ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.ACTIVE_SESSION,
                audit=_AUDIT,
            )
            if tool_name == "record_event":
                input_data = {"event_type": "test"}
            elif tool_name == "record_note":
                input_data = {"text": "test"}

        with pytest.raises(ConflictError) as exc_info:
            executor.execute(
                tool_name,
                input_data=input_data,
                context=ctx,
            )
        msg = str(exc_info.value)
        assert "requires explicit recovery" in msg
        assert runtime.calls == [], f"{tool_name}: runtime mutation should not be called"

    def test_error_does_not_contain_issue_details(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        recovery.set_has_issues(True)
        with pytest.raises(ConflictError) as exc_info:
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_no_active,
            )
        msg = str(exc_info.value)
        assert "session_id" not in msg
        assert "operation_id" not in msg
        assert "detail" not in msg
        assert "S001" not in msg
        assert "\\" not in msg
        assert "/" not in msg

    def test_repair_methods_never_called(
        self,
        executor: ToolExecutor,
        runtime: TrackingRuntimeService,
        recovery: TrackingRecoveryService,
        write_context_no_active: ExecutionContext,
    ) -> None:
        recovery.set_has_issues(True)
        with pytest.raises(ConflictError):
            executor.execute(
                "start_session",
                input_data={},
                context=write_context_no_active,
            )
        assert "repair_audit_tail" not in recovery.calls
        assert "cleanup_partial_start" not in recovery.calls
        assert "repair_event_tail" not in recovery.calls


# ═══════════════════════════════════════════════════════════════════════════════
# Recovery preflight ordering — inspect before runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestPreflightOrdering:
    def test_clean_preflight_before_start(
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
        assert recovery.calls == ["inspect_runtime"]
        assert runtime.calls == ["start_session"]

    def test_clean_preflight_before_record_event(
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
        assert recovery.calls == ["inspect_runtime"]
        assert "record_event" in runtime.calls[0]

    def test_clean_preflight_before_record_note(
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
        assert recovery.calls == ["inspect_runtime"]

    def test_clean_preflight_before_end(
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
        assert recovery.calls == ["inspect_runtime"]
        assert runtime.calls == ["end_session"]


# ═══════════════════════════════════════════════════════════════════════════════
# No direct repository/audit/filesystem mutation in tools
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoDirectMutation:
    """Prove tools delegate everything to runtime, never reach repositories directly."""

    def test_no_repository_imports_in_production(self) -> None:
        """Verify session_mutations does not import storage repository modules."""
        import dnd_assistant.tools.session_mutations as mod

        mod_src = str(mod.__file__ or "")
        with open(mod_src, encoding="utf-8") as f:
            source = f.read()
        # Should not import storage repository modules
        assert "SessionMetadataRepository" not in source or "TYPE_CHECKING" in source
        assert "SessionEventRepository" not in source or "TYPE_CHECKING" in source
        assert "WorldTimeRepository" not in source or "TYPE_CHECKING" in source
        assert "AuditService" not in source
