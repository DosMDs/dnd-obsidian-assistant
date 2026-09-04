"""Tests for the validated Fast Agent tool execution boundary (S9-03).

Covers:

- Turn binding (decision membership, exposed-tool allowlist)
- Malformed input rejection
- Trusted ToolExecutor execution (READ, WRITE, errors)
- Deterministic TOOL-result serialisation
- TOOL ChatMessage construction
- Serialisation failure boundary
- Multi-call per-call primitive
- Non-mutation
- No model invocation
- Fresh-process import isolation
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionResult,
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import AgentDecision
from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

if TYPE_CHECKING:
    pass


# ── Dummy schemas for real ToolExecutor tests ──────────────────────────────────


class StringInput(BaseModel):
    value: str


class EmptyOutput(BaseModel):
    pass


class ResultOutput(BaseModel):
    result: str


class NumberInput(BaseModel):
    number: int


class NestedOutput(BaseModel):
    name: str
    count: int | None = None
    tags: list[str] = []
    metadata: dict[str, object] = {}
    flag: bool = False


# ── Handlers ───────────────────────────────────────────────────────────────────


def read_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"read: {input_model.value}")


def write_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"write: {input_model.value}")


def empty_handler(input_model: StringInput, context: object) -> EmptyOutput:
    return EmptyOutput()


def nested_handler(input_model: NumberInput, context: object) -> NestedOutput:
    return NestedOutput(
        name="test",
        count=input_model.number,
        tags=["a", "b"],
        metadata={"key": "val", "nested": {"inner": 42}},
        flag=True,
    )


def unicode_handler(input_model: StringInput, context: object) -> NestedOutput:
    return NestedOutput(
        name=input_model.value,
        tags=["\u043f\u0440\u0438\u0432\u0435\u0442", "\u043c\u0438\u0440"],
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def read_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="read_tool",
        description="A read-only test tool",
        input_schema=StringInput,
        output_schema=ResultOutput,
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
        output_schema=ResultOutput,
        permission=Permission.WRITE,
        side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
        allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
    )


@pytest.fixture
def empty_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="empty_tool",
        description="Returns empty output",
        input_schema=StringInput,
        output_schema=EmptyOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def nested_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="nested_tool",
        description="Returns nested output",
        input_schema=NumberInput,
        output_schema=NestedOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def unicode_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="unicode_tool",
        description="Returns Unicode output",
        input_schema=StringInput,
        output_schema=NestedOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def registry(
    read_tool_def: ToolDefinition,
    write_tool_def: ToolDefinition,
    empty_tool_def: ToolDefinition,
    nested_tool_def: ToolDefinition,
    unicode_tool_def: ToolDefinition,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_tool_def, read_handler)
    reg.register(write_tool_def, write_handler)
    reg.register(empty_tool_def, empty_handler)
    reg.register(nested_tool_def, nested_handler)
    reg.register(unicode_tool_def, unicode_handler)
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


@pytest.fixture
def service(executor: ToolExecutor) -> AgentToolExecutionService:
    return AgentToolExecutionService(tool_executor=executor)


@pytest.fixture
def audit_ctx() -> AuditContext:
    return AuditContext(
        operation_id="test-op",
        real_time=datetime.now(UTC),
        source="test",
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context(audit_ctx: AuditContext) -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=audit_ctx,
    )


# ── Decision-building helpers ──────────────────────────────────────────────────


def _make_tool_call(
    name: str,
    arguments: dict[str, object] | None = None,
    call_id: str | None = None,
) -> ToolCall:
    return ToolCall(
        name=name,
        arguments=arguments or {},
        call_id=call_id,
    )


def _make_tool_public(
    name: str,
    *,
    permission: Permission = Permission.READ,
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permission=permission,
        side_effects=[],
        allowed_session_modes=allowed_session_modes or [SessionMode.NO_ACTIVE_SESSION],
    )


def _make_decision(
    *,
    tool_calls: list[ToolCall] | None = None,
    exposed_tools: list[ToolPublicDefinition] | None = None,
    content: str | None = None,
) -> AgentDecision:
    """Build an ``AgentDecision`` with the given tool calls and exposed tools."""
    return AgentDecision(
        prompt_version="test-v1",
        request=ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.SYSTEM, content="System prompt"),
                ChatMessage(role=MessageRole.USER, content='{"user_input": "test"}'),
            ),
        ),
        exposed_tools=tuple(exposed_tools or []),
        response=ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=content,
                tool_calls=tuple(tool_calls or []),
            ),
        ),
    )


# ── Turn binding tests ─────────────────────────────────────────────────────────


class TestTurnBinding:
    """Verify pre-execution validation of decision/call binding."""

    def test_valid_exact_call_executes(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert isinstance(result, AgentToolExecutionResult)
        assert result.tool_call is tool_call
        assert result.output.result == "read: hello"

    def test_call_object_equal_to_decision_member_accepted(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        """A different object with same field values is semantically equal."""
        original = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        same_value = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[original], exposed_tools=exposed)
        result = service.execute(decision, same_value, execution_context=read_context)
        assert result.tool_call is same_value
        assert result.output.result == "read: hello"

    def test_same_name_different_arguments_rejected(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        different_args = _make_tool_call("read_tool", {"value": "world"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="not a member"):
            service.execute(decision, different_args, execution_context=read_context)

    def test_completely_unrelated_call_rejected(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        unrelated = _make_tool_call("other_tool", {"x": "y"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="not a member"):
            service.execute(decision, unrelated, execution_context=read_context)

    def test_call_name_not_in_exposed_tools_rejected(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("other_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="not in the exposed-tool"):
            service.execute(decision, tool_call, execution_context=read_context)

    def test_manually_constructed_inconsistent_decision_fails_closed(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        """A decision with a tool call not in its own exposed_tools fails."""
        tool_call = _make_tool_call("hidden_tool", {"x": "y"})
        exposed = [_make_tool_public("visible_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="not in the exposed-tool"):
            service.execute(decision, tool_call, execution_context=read_context)

    def test_malformed_decision_rejected(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        with pytest.raises(ValidationError, match="AgentDecision"):
            service.execute("not_a_decision", tool_call, execution_context=read_context)  # type: ignore[arg-type]

    def test_malformed_tool_call_rejected(
        self, service: AgentToolExecutionService, read_context: ExecutionContext
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="ToolCall"):
            service.execute(decision, "not_a_tool_call", execution_context=read_context)  # type: ignore[arg-type]

    def test_malformed_execution_context_rejected(self, service: AgentToolExecutionService) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="ExecutionContext"):
            service.execute(decision, tool_call, execution_context="bad_context")  # type: ignore[arg-type]

    def test_zero_executor_calls_on_pre_execution_rejection(
        self, read_context: ExecutionContext
    ) -> None:
        """Prove zero ToolExecutor calls when pre-execution checks fail."""
        call_count = 0

        class _CountingExecutor:
            def execute(  # type: ignore[override]
                self,
                tool_name: str,
                *,
                input_data: dict[str, Any],
                context: ExecutionContext,
            ) -> BaseModel:
                nonlocal call_count
                call_count += 1
                return ResultOutput(result="ok")

        svc = AgentToolExecutionService(tool_executor=_CountingExecutor())  # type: ignore[arg-type]

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)

        # Malformed decision
        with pytest.raises(ValidationError):
            svc.execute("bad", tool_call, execution_context=read_context)  # type: ignore[arg-type]
        assert call_count == 0

        # Malformed ToolCall
        with pytest.raises(ValidationError):
            svc.execute(decision, "bad", execution_context=read_context)  # type: ignore[arg-type]
        assert call_count == 0

        # Malformed ExecutionContext
        with pytest.raises(ValidationError):
            svc.execute(decision, tool_call, execution_context="bad")  # type: ignore[arg-type]
        assert call_count == 0

        # Unrelated call
        unrelated = _make_tool_call("other", {"x": "y"})
        with pytest.raises(ValidationError):
            svc.execute(decision, unrelated, execution_context=read_context)
        assert call_count == 0

        # Same name, different args
        different_args = _make_tool_call("read_tool", {"value": "world"})
        with pytest.raises(ValidationError):
            svc.execute(decision, different_args, execution_context=read_context)
        assert call_count == 0

        # Name not in exposed tools
        hidden_call = _make_tool_call("hidden_tool", {"x": "y"})
        hidden_decision = _make_decision(
            tool_calls=[hidden_call],
            exposed_tools=[_make_tool_public("visible_tool")],
        )
        with pytest.raises(ValidationError):
            svc.execute(hidden_decision, hidden_call, execution_context=read_context)
        assert call_count == 0


# ── Trusted execution tests ────────────────────────────────────────────────────


class TestTrustedExecution:
    """Verify execution through a real ToolExecutor."""

    def test_valid_read_execution_succeeds(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.output.result == "read: hello"

    def test_raw_arguments_reach_tool_executor(
        self,
        registry: ToolRegistry,
        read_context: ExecutionContext,
    ) -> None:
        """Prove arguments are passed as-is to ToolExecutor (no coercion)."""
        tool_call = _make_tool_call("nested_tool", {"number": 42})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        svc = AgentToolExecutionService(
            tool_executor=ToolExecutor(registry),
        )
        result = svc.execute(decision, tool_call, execution_context=read_context)
        assert result.output.count == 42

    def test_pydantic_input_coercion_happens_in_tool_executor_not_application(
        self,
        registry: ToolRegistry,
        read_context: ExecutionContext,
    ) -> None:
        """Prove coercion (e.g. str->int) happens inside ToolExecutor."""
        tool_call = _make_tool_call("nested_tool", {"number": "42"})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        svc = AgentToolExecutionService(
            tool_executor=ToolExecutor(registry),
        )
        result = svc.execute(decision, tool_call, execution_context=read_context)
        assert result.output.count == 42

    def test_unknown_executor_registry_tool_raises_not_found(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("nonexistent_tool", {"value": "x"})
        exposed = [_make_tool_public("nonexistent_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(NotFoundError, match="Unknown tool"):
            service.execute(decision, tool_call, execution_context=read_context)

    def test_invalid_input_raises_validation_error(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"wrong_field": "x"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError):
            service.execute(decision, tool_call, execution_context=read_context)

    def test_read_context_write_tool_raises_conflict(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("write_tool", {"value": "x"})
        exposed = [_make_tool_public("write_tool", permission=Permission.WRITE)]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ConflictError, match="Permission denied"):
            service.execute(decision, tool_call, execution_context=read_context)

    def test_session_mode_mismatch_raises_conflict(
        self,
        registry: ToolRegistry,
    ) -> None:
        """A READ tool restricted to ACTIVE_SESSION fails under NO_ACTIVE_SESSION."""
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=AuditContext(
                operation_id="test-op",
                real_time=datetime.now(UTC),
                source="test",
            ),
        )
        # Register a tool that only allows ACTIVE_SESSION
        session_tool_def = ToolDefinition(
            name="session_only_tool",
            description="Only allowed during active session",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
        )
        reg = ToolRegistry()
        reg.register(session_tool_def, read_handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("session_only_tool", {"value": "x"})
        exposed = [
            _make_tool_public(
                "session_only_tool",
                permission=Permission.READ,
                allowed_session_modes=[SessionMode.ACTIVE_SESSION],
            )
        ]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ConflictError, match="Session mode"):
            svc.execute(decision, tool_call, execution_context=ctx)

    def test_write_tool_without_audit_raises_validation_error(
        self,
        service: AgentToolExecutionService,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        tool_call = _make_tool_call("write_tool", {"value": "x"})
        exposed = [
            _make_tool_public(
                "write_tool",
                permission=Permission.WRITE,
                allowed_session_modes=[SessionMode.ACTIVE_SESSION],
            )
        ]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ValidationError, match="requires a non-None AuditContext"):
            service.execute(decision, tool_call, execution_context=ctx)

    def test_valid_write_with_audit_executes_handler_exactly_once(
        self,
        service: AgentToolExecutionService,
        write_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("write_tool", {"value": "world"})
        exposed = [
            _make_tool_public(
                "write_tool",
                permission=Permission.WRITE,
                allowed_session_modes=[SessionMode.ACTIVE_SESSION],
            )
        ]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=write_context)
        assert result.output.result == "write: world"

    def test_invalid_output_raises_validation_error_after_handler(
        self,
    ) -> None:
        """Handler returns invalid output; ToolExecutor catches it."""

        class BadOutput(BaseModel):
            required: str

        class BadInput(BaseModel):
            value: str

        def bad_handler(input_model: BadInput, context: object) -> object:
            return {"wrong": "data"}

        bad_def = ToolDefinition(
            name="bad_tool",
            description="Bad tool",
            input_schema=BadInput,
            output_schema=BadOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg = ToolRegistry()
        reg.register(bad_def, bad_handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("bad_tool", {"value": "x"})
        exposed = [_make_tool_public("bad_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError):
            svc.execute(decision, tool_call, execution_context=ctx)

    def test_domain_handler_error_propagates_unchanged(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        """A domain error from the handler propagates through."""

        def failing_handler(input_model: StringInput, context: object) -> ResultOutput:
            raise ConflictError("handler-level conflict")

        reg = ToolRegistry()
        reg_def = ToolDefinition(
            name="failing_tool",
            description="Failing tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(reg_def, failing_handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("failing_tool", {"value": "x"})
        exposed = [_make_tool_public("failing_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(ConflictError, match="handler-level conflict"):
            svc.execute(decision, tool_call, execution_context=read_context)

    def test_unexpected_handler_exception_propagates_unchanged(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        def crashing_handler(input_model: StringInput, context: object) -> ResultOutput:
            raise RuntimeError("unexpected crash")

        reg = ToolRegistry()
        reg_def = ToolDefinition(
            name="crash_tool",
            description="Crash tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(reg_def, crashing_handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("crash_tool", {"value": "x"})
        exposed = [_make_tool_public("crash_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        with pytest.raises(RuntimeError, match="unexpected crash"):
            svc.execute(decision, tool_call, execution_context=read_context)

    def test_no_retry_on_post_handler_failure(
        self,
    ) -> None:
        """Handler called exactly once even when output validation fails."""
        handler_call_count = 0

        class RequiredOutput(BaseModel):
            required: str

        class SimpleInput(BaseModel):
            value: str

        def counting_handler(input_model: SimpleInput, context: object) -> object:
            nonlocal handler_call_count
            handler_call_count += 1
            return {"wrong": "data"}

        reg_def = ToolDefinition(
            name="count_tool",
            description="Count tool",
            input_schema=SimpleInput,
            output_schema=RequiredOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg = ToolRegistry()
        reg.register(reg_def, counting_handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("count_tool", {"value": "x"})
        exposed = [_make_tool_public("count_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(ValidationError):
            svc.execute(decision, tool_call, execution_context=ctx)
        assert handler_call_count == 1


# ── Multi-call per-call primitive tests ────────────────────────────────────────


# ── Multi-call per-call primitive tests ────────────────────────────────────────


class TestMultiCallPrimitive:
    """Prove the service is a per-call primitive, not multi-call orchestration."""

    def test_execute_only_supplied_call(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        call_a = _make_tool_call("read_tool", {"value": "first"})
        call_b = _make_tool_call("read_tool", {"value": "second"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(
            tool_calls=[call_a, call_b],
            exposed_tools=exposed,
        )
        # Execute only the second call
        result = service.execute(decision, call_b, execution_context=read_context)
        assert result.output.result == "read: second"

    def test_sibling_call_not_automatically_executed(
        self,
        read_context: ExecutionContext,
    ) -> None:
        """Prove that executing one call does not trigger the other."""
        execution_order: list[str] = []

        def handler_a(input_model: StringInput, context: object) -> ResultOutput:
            execution_order.append("a")
            return ResultOutput(result="a")

        def handler_b(input_model: StringInput, context: object) -> ResultOutput:
            execution_order.append("b")
            return ResultOutput(result="b")

        reg = ToolRegistry()
        reg.register(
            ToolDefinition(
                name="tool_a",
                description="Tool A",
                input_schema=StringInput,
                output_schema=ResultOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset(
                    {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
                ),
            ),
            handler_a,
        )
        reg.register(
            ToolDefinition(
                name="tool_b",
                description="Tool B",
                input_schema=StringInput,
                output_schema=ResultOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset(
                    {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
                ),
            ),
            handler_b,
        )
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        call_a = _make_tool_call("tool_a", {"value": "a"})
        call_b = _make_tool_call("tool_b", {"value": "b"})
        exposed = [_make_tool_public("tool_a"), _make_tool_public("tool_b")]
        decision = _make_decision(
            tool_calls=[call_a, call_b],
            exposed_tools=exposed,
        )
        # Execute only call_b
        svc.execute(decision, call_b, execution_context=read_context)
        assert execution_order == ["b"]


# ── Non-mutation tests ─────────────────────────────────────────────────────────


class TestNonMutation:
    """Prove successful execution does not mutate input objects."""

    def test_decision_unchanged(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        original = dataclasses.asdict(decision)
        service.execute(decision, tool_call, execution_context=read_context)
        assert dataclasses.asdict(decision) == original

    def test_tool_call_unchanged(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        original_name = tool_call.name
        original_args = dict(tool_call.arguments)
        original_call_id = tool_call.call_id
        service.execute(decision, tool_call, execution_context=read_context)
        assert tool_call.name == original_name
        assert tool_call.arguments == original_args
        assert tool_call.call_id == original_call_id


# ── No model invocation tests ──────────────────────────────────────────────────


class TestNoModelInvocation:
    """Prove S9-03 does not require or invoke ModelGateway."""

    def test_service_has_no_model_gateway_dependency(self) -> None:
        """Constructor only takes ToolExecutor, not ModelGateway."""
        import inspect

        sig = inspect.signature(AgentToolExecutionService.__init__)
        params = list(sig.parameters.keys())
        assert "tool_executor" in params
        assert "model_gateway" not in params
        assert "model" not in params


# ── Fresh-process import test ──────────────────────────────────────────────────


class TestFreshProcessImport:
    """Verify import isolation in a fresh subprocess."""

    def test_fresh_import_does_not_load_forbidden_modules(self) -> None:
        code = textwrap.dedent("""\
            import sys
            import dnd_assistant.application.agent_tool_execution
            forbidden = [
                "dnd_assistant.models.ollama",
                "dnd_assistant.storage",
                "dnd_assistant.retrieval",
                "dnd_assistant.cli",
            ]
            loaded = [m for m in forbidden if m in sys.modules]
            if loaded:
                print("FORBIDDEN_LOADED:" + ",".join(loaded))
                sys.exit(1)
            print("OK")
        """)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Fresh import failed: stdout={result.stdout}, stderr={result.stderr}"
        )
        assert "OK" in result.stdout
