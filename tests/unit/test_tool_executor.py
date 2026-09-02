"""Tests for ToolExecutor: full execution pipeline, precondition enforcement,
error propagation, and zero-handler-invocation guarantees.

These tests use only local dummy schemas and handlers — no real campaign
Vault, no concrete tools, no model providers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

# ── Dummy schemas ────────────────────────────────────────────────────────────


class StringInput(BaseModel):
    value: str


class IntInput(BaseModel):
    number: int


class StringOutput(BaseModel):
    result: str


class IntOutput(BaseModel):
    result: int


# ── Handlers ─────────────────────────────────────────────────────────────────


def read_handler(input_model: StringInput, context: object) -> StringOutput:
    return StringOutput(result=f"read: {input_model.value}")


def write_handler(input_model: StringInput, context: object) -> StringOutput:
    return StringOutput(result=f"write: {input_model.value}")


def int_handler(input_model: IntInput, context: object) -> IntOutput:
    return IntOutput(result=input_model.number * 2)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def read_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="read_tool",
        description="A read-only test tool",
        input_schema=StringInput,
        output_schema=StringOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def write_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="write_tool",
        description="A write test tool",
        input_schema=StringInput,
        output_schema=StringOutput,
        permission=Permission.WRITE,
        side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
        allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
    )


@pytest.fixture
def session_only_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="session_only_tool",
        description="Only allowed during active session",
        input_schema=StringInput,
        output_schema=StringOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
    )


@pytest.fixture
def no_session_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="no_session_tool",
        description="Only allowed without active session",
        input_schema=StringInput,
        output_schema=StringOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
    )


@pytest.fixture
def registry(
    read_tool_def: ToolDefinition,
    write_tool_def: ToolDefinition,
    session_only_tool_def: ToolDefinition,
    no_session_tool_def: ToolDefinition,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_tool_def, read_handler)
    reg.register(write_tool_def, write_handler)
    reg.register(session_only_tool_def, read_handler)
    reg.register(no_session_tool_def, read_handler)
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime(2026, 9, 2, tzinfo=UTC),
            source="test",
        ),
    )


# ── Valid invocations ────────────────────────────────────────────────────────


class TestToolExecutorValid:
    def test_read_invocation(self, executor: ToolExecutor, read_context: ExecutionContext) -> None:
        result = executor.execute(
            "read_tool",
            input_data={"value": "hello"},
            context=read_context,
        )
        assert isinstance(result, StringOutput)
        assert result.result == "read: hello"

    def test_write_invocation(
        self, executor: ToolExecutor, write_context: ExecutionContext
    ) -> None:
        result = executor.execute(
            "write_tool",
            input_data={"value": "world"},
            context=write_context,
        )
        assert isinstance(result, StringOutput)
        assert result.result == "write: world"

    def test_write_authority_can_execute_read_tool(
        self, executor: ToolExecutor, write_context: ExecutionContext
    ) -> None:
        result = executor.execute(
            "read_tool",
            input_data={"value": "from_write"},
            context=write_context,
        )
        assert isinstance(result, StringOutput)
        assert result.result == "read: from_write"

    def test_output_validated_against_registered_schema(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        result = executor.execute(
            "read_tool",
            input_data={"value": "test"},
            context=read_context,
        )
        assert isinstance(result, StringOutput)


# ── Permission enforcement ───────────────────────────────────────────────────


class TestToolExecutorPermission:
    def test_read_authority_cannot_execute_write_tool(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        with pytest.raises(ConflictError, match="Permission denied"):
            executor.execute(
                "write_tool",
                input_data={"value": "x"},
                context=read_context,
            )


# ── Session mode enforcement ─────────────────────────────────────────────────


class TestToolExecutorSessionMode:
    def test_wrong_session_mode_denied(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        # no_session_tool requires NO_ACTIVE_SESSION, but context has ACTIVE_SESSION
        with pytest.raises(ConflictError, match="Session mode"):
            executor.execute(
                "no_session_tool",
                input_data={"value": "x"},
                context=read_context,
            )

    def test_session_only_tool_allowed_in_active_session(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        result = executor.execute(
            "session_only_tool",
            input_data={"value": "x"},
            context=read_context,
        )
        assert isinstance(result, StringOutput)


# ── Audit prerequisite ───────────────────────────────────────────────────────


class TestToolExecutorAudit:
    def test_write_without_audit_rejected(self, executor: ToolExecutor) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError, match="requires a non-None AuditContext"):
            executor.execute(
                "write_tool",
                input_data={"value": "x"},
                context=ctx,
            )


# ── Input validation ─────────────────────────────────────────────────────────


class TestToolExecutorInputValidation:
    def test_invalid_input_rejected(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "read_tool",
                input_data={"wrong_field": "x"},
                context=read_context,
            )

    def test_missing_required_field(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "read_tool",
                input_data={},
                context=read_context,
            )


# ── Unknown tool ─────────────────────────────────────────────────────────────


class TestToolExecutorUnknown:
    def test_unknown_tool_rejected(
        self, executor: ToolExecutor, read_context: ExecutionContext
    ) -> None:
        with pytest.raises(NotFoundError, match="Unknown tool"):
            executor.execute(
                "nonexistent_tool",
                input_data={"value": "x"},
                context=read_context,
            )


# ── Handler invocation guarantees ────────────────────────────────────────────


class TestToolExecutorHandlerInvocation:
    def test_handler_called_exactly_once_on_success(self, read_tool_def: ToolDefinition) -> None:
        call_count = 0

        def counting_handler(input_model: StringInput, context: object) -> StringOutput:
            nonlocal call_count
            call_count += 1
            return StringOutput(result="ok")

        reg = ToolRegistry()
        reg.register(read_tool_def, counting_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        exe.execute("read_tool", input_data={"value": "x"}, context=ctx)
        assert call_count == 1

    def test_handler_not_called_after_input_validation_failure(
        self, read_tool_def: ToolDefinition
    ) -> None:
        call_count = 0

        def counting_handler(input_model: StringInput, context: object) -> StringOutput:
            nonlocal call_count
            call_count += 1
            return StringOutput(result="ok")

        reg = ToolRegistry()
        reg.register(read_tool_def, counting_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError):
            exe.execute("read_tool", input_data={"wrong": "x"}, context=ctx)
        assert call_count == 0

    def test_handler_not_called_after_permission_failure(
        self, write_tool_def: ToolDefinition
    ) -> None:
        call_count = 0

        def counting_handler(input_model: StringInput, context: object) -> StringOutput:
            nonlocal call_count
            call_count += 1
            return StringOutput(result="ok")

        reg = ToolRegistry()
        reg.register(write_tool_def, counting_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ConflictError):
            exe.execute("write_tool", input_data={"value": "x"}, context=ctx)
        assert call_count == 0

    def test_handler_not_called_after_session_mode_failure(
        self, no_session_tool_def: ToolDefinition
    ) -> None:
        call_count = 0

        def counting_handler(input_model: StringInput, context: object) -> StringOutput:
            nonlocal call_count
            call_count += 1
            return StringOutput(result="ok")

        reg = ToolRegistry()
        reg.register(no_session_tool_def, counting_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ConflictError):
            exe.execute("no_session_tool", input_data={"value": "x"}, context=ctx)
        assert call_count == 0

    def test_handler_not_called_after_missing_write_audit(
        self, write_tool_def: ToolDefinition
    ) -> None:
        call_count = 0

        def counting_handler(input_model: StringInput, context: object) -> StringOutput:
            nonlocal call_count
            call_count += 1
            return StringOutput(result="ok")

        reg = ToolRegistry()
        reg.register(write_tool_def, counting_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError):
            exe.execute("write_tool", input_data={"value": "x"}, context=ctx)
        assert call_count == 0


# ── Output validation ────────────────────────────────────────────────────────


class TestToolExecutorOutputValidation:
    def test_invalid_handler_output_rejected(self, read_tool_def: ToolDefinition) -> None:
        def bad_handler(input_model: StringInput, context: object) -> object:
            return "not_a_pydantic_model"

        reg = ToolRegistry()
        reg.register(read_tool_def, bad_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError):
            exe.execute("read_tool", input_data={"value": "x"}, context=ctx)


# ── DndAssistantError propagation ────────────────────────────────────────────


class TestToolExecutorErrorPropagation:
    def test_handler_validation_error_propagates(self, read_tool_def: ToolDefinition) -> None:
        def failing_handler(input_model: StringInput, context: object) -> StringOutput:
            raise ValidationError("handler-level failure")

        reg = ToolRegistry()
        reg.register(read_tool_def, failing_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError, match="handler-level failure"):
            exe.execute("read_tool", input_data={"value": "x"}, context=ctx)

    def test_handler_conflict_error_propagates(self, read_tool_def: ToolDefinition) -> None:
        def failing_handler(input_model: StringInput, context: object) -> StringOutput:
            raise ConflictError("handler-level conflict")

        reg = ToolRegistry()
        reg.register(read_tool_def, failing_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(ConflictError, match="handler-level conflict"):
            exe.execute("read_tool", input_data={"value": "x"}, context=ctx)

    def test_handler_not_found_error_propagates(self, read_tool_def: ToolDefinition) -> None:
        def failing_handler(input_model: StringInput, context: object) -> StringOutput:
            raise NotFoundError("handler-level not found")

        reg = ToolRegistry()
        reg.register(read_tool_def, failing_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(NotFoundError, match="handler-level not found"):
            exe.execute("read_tool", input_data={"value": "x"}, context=ctx)

    def test_handler_runtime_error_propagates_unchanged(
        self, read_tool_def: ToolDefinition
    ) -> None:
        """A non-DndAssistantError from the handler must propagate unchanged."""

        def failing_handler(input_model: StringInput, context: object) -> StringOutput:
            raise RuntimeError("boom")

        reg = ToolRegistry()
        reg.register(read_tool_def, failing_handler)
        exe = ToolExecutor(reg)

        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        with pytest.raises(RuntimeError, match="boom"):
            exe.execute("read_tool", input_data={"value": "x"}, context=ctx)
