"""Failure-policy tests for the Fast Agent loop (S9-05).

Covers:

- READ batch stop-on-first-failure
- Unexpected execution exception propagation
- Second-model failure after batch, no retry
- Terminal validation failure after batch, no retry
- Post-tool additional-call hard bound
- No third model call
- No second tool round
- Immutability of input objects
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel

from dnd_assistant.application.agent_context import AgentContext
from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.fast_agent import AgentDecision
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)


class StringInput(BaseModel):
    value: str


class ResultOutput(BaseModel):
    result: str


def read_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"read: {input_model.value}")


def _make_context_with(
    *,
    user_input: str = "test",
) -> AgentContext:
    from dnd_assistant.application.agent_context import AgentContext as AC

    return AC(
        user_input=user_input,
        current_world_tick=12345,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
    )


def _make_context(
    *,
    permission: Permission = Permission.READ,
    session_mode: SessionMode = SessionMode.NO_ACTIVE_SESSION,
    audit: AuditContext | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        granted_permission=permission,
        session_mode=session_mode,
        audit=audit,
    )


def _make_tool_response(
    *,
    content: str | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> ToolAwareResponse:
    return ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tuple(tool_calls or []),
        ),
    )


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
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permission=permission,
        side_effects=[],
        allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
    )


class _FakeAgentContextBuilder:
    def __init__(self, context: AgentContext) -> None:
        self._context = context
        self.build_call_count: int = 0

    def build(self, user_input: str) -> AgentContext:
        self.build_call_count += 1
        return self._context


class _FakeModelGateway:
    def __init__(self, response: ToolAwareResponse | None = None) -> None:
        self._response = response
        self.chat_with_tools_call_count: int = 0
        self.last_request: ChatRequest | None = None
        self.last_tools: list[ToolPublicDefinition] | None = None

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.chat_with_tools_call_count += 1
        self.last_request = request
        self.last_tools = tools
        if self._response is None:
            raise ModelError("fake model error")
        return self._response

    def chat(self, request: ChatRequest) -> None:
        raise AssertionError("chat() should not be called")

    def generate_structured(self, request: ChatRequest, schema: type) -> None:
        raise AssertionError("generate_structured() should not be called")

    def embed(self, texts: list[str]) -> None:
        raise AssertionError("embed() should not be called")

    def health(self) -> None:
        raise AssertionError("health() should not be called")


@dataclass(frozen=True, slots=True)
class _FakeToolExecutionResult:
    tool_call: Any
    output: Any
    tool_message: Any


class _FakeToolExecutionService:
    def __init__(self, result: object = None) -> None:
        self._result = result
        self.execute_call_count: int = 0
        self.last_decision: AgentDecision | None = None
        self.last_tool_call: ToolCall | None = None

    def execute(
        self,
        decision: AgentDecision,
        tool_call: ToolCall,
        *,
        execution_context: ExecutionContext,
    ) -> object:
        self.execute_call_count += 1
        self.last_decision = decision
        self.last_tool_call = tool_call
        self.last_context = execution_context
        if self._result is None:
            raise ValidationError("fake execution error")
        from dnd_assistant.models.types import ChatMessage as CM
        from dnd_assistant.models.types import MessageRole as MR

        tool_msg = CM(
            role=MR.TOOL,
            content='{"result":"ok"}',
            tool_name=tool_call.name,
            tool_call_id=tool_call.call_id,
        )
        return _FakeToolExecutionResult(
            tool_call=tool_call,
            output=self._result,
            tool_message=tool_msg,
        )


def _make_two_call_gateway(
    fake: _FakeModelGateway,
    first: ToolAwareResponse,
    second: ToolAwareResponse,
) -> Any:
    call_no: int = 0

    def two_call(
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        nonlocal call_no
        call_no += 1
        fake.chat_with_tools_call_count = call_no
        fake.last_request = request
        fake.last_tools = tools
        if call_no == 1:
            return first
        return second

    return two_call


# ── Stop-on-first-failure tests ─────────────────────────────────────────────


class TestStopOnFirstFailure:
    """READ batch stops on first execution failure."""

    def test_stop_on_first_failure_propagates(self) -> None:
        """call 0 succeeds, call 1 fails -> ValidationError, no second model."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()
        call_count: int = 0

        def handler(input_model: StringInput, context: object) -> ResultOutput:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ResultOutput(result="ok")
            raise ValidationError("simulated failure on call " + str(call_count))

        fail_def = ToolDefinition(
            name="fail_tool",
            description="Tool that fails",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(fail_def, handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("fail_tool", {"value": "first"})
        call_b = _make_tool_call("fail_tool", {"value": "second"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )

        gateway = _FakeModelGateway(first_response)

        fail_public = _make_tool_public("fail_tool")
        catalog = ToolRegistrySchema(tools=[fail_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        with pytest.raises(ValidationError, match="simulated failure on call 2"):
            loop.run("test", execution_context=_make_context())

        # Only one model call (no second call after failure)
        assert gateway.chat_with_tools_call_count == 1

    def test_unexpected_exception_propagates(self) -> None:
        """Unexpected RuntimeError from execution propagates unchanged."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()

        def crash_handler(input_model: StringInput, context: object) -> ResultOutput:
            raise RuntimeError("unexpected crash")

        crash_def = ToolDefinition(
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
        reg.register(crash_def, crash_handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("crash_tool", {"value": "x"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[tool_call],
        )

        gateway = _FakeModelGateway(first_response)

        crash_public = _make_tool_public("crash_tool")
        catalog = ToolRegistrySchema(tools=[crash_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        with pytest.raises(RuntimeError, match="unexpected crash"):
            loop.run("test", execution_context=_make_context())

        assert gateway.chat_with_tools_call_count == 1


# ── Second-model failure tests ──────────────────────────────────────────────


class TestSecondModelFailure:
    """Second model call fails after successful batch, no retry."""

    def test_second_model_error_no_retry(self) -> None:
        """All READ calls succeed, second model fails -> ModelError, no retry."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()

        def handler(input_model: StringInput, context: object) -> ResultOutput:
            return ResultOutput(result="ok")

        ok_def = ToolDefinition(
            name="ok_tool",
            description="OK tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(ok_def, handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("ok_tool", {"value": "a"})
        call_b = _make_tool_call("ok_tool", {"value": "b"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )

        gateway = _FakeModelGateway(first_response)

        def second_call_fails(
            request: ChatRequest,
            tools: list[ToolPublicDefinition],
        ) -> ToolAwareResponse:
            gateway.chat_with_tools_call_count += 1
            gateway.last_request = request
            gateway.last_tools = tools
            if gateway.chat_with_tools_call_count == 1:
                return first_response
            raise ModelError("second model call failed")

        gateway.chat_with_tools = second_call_fails

        ok_public = _make_tool_public("ok_tool")
        catalog = ToolRegistrySchema(tools=[ok_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        with pytest.raises(ModelError, match="second model call failed"):
            loop.run("test", execution_context=_make_context())

        # Two model calls attempted, no retry
        assert gateway.chat_with_tools_call_count == 2


# ── Terminal validation failure tests ───────────────────────────────────────


class TestTerminalValidationFailure:
    """Terminal validation fails after successful batch, no retry."""

    def test_terminal_validation_failure_no_retry(self) -> None:
        """All READ calls succeed, terminal validation fails -> ModelError."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()

        def handler(input_model: StringInput, context: object) -> ResultOutput:
            return ResultOutput(result="ok")

        ok_def = ToolDefinition(
            name="ok_tool",
            description="OK tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(ok_def, handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("ok_tool", {"value": "a"})
        call_b = _make_tool_call("ok_tool", {"value": "b"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )
        second_response = _make_tool_response(content="Not valid JSON")

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        ok_public = _make_tool_public("ok_tool")
        catalog = ToolRegistrySchema(tools=[ok_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        with pytest.raises(ModelError):
            loop.run("test", execution_context=_make_context())

        # Two model calls, no retry
        assert gateway.chat_with_tools_call_count == 2


# ── No second tool round tests ──────────────────────────────────────────────


class TestNoSecondToolRound:
    """Second response with tool calls rejected after batch."""

    def test_post_batch_tool_call_rejected(self) -> None:
        """Second response has tool calls -> ModelError, no execution."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()

        def handler(input_model: StringInput, context: object) -> ResultOutput:
            return ResultOutput(result="ok")

        ok_def = ToolDefinition(
            name="ok_tool",
            description="OK tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(ok_def, handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("ok_tool", {"value": "a"})
        call_b = _make_tool_call("ok_tool", {"value": "b"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )
        second_tool_call = _make_tool_call("ok_tool", {"value": "c"})
        second_response = _make_tool_response(
            content="Still need data...",
            tool_calls=[second_tool_call],
        )

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        ok_public = _make_tool_public("ok_tool")
        catalog = ToolRegistrySchema(tools=[ok_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        with pytest.raises(ModelError, match="does not support post-tool tool calls"):
            loop.run("test", execution_context=_make_context())

        # Two model calls, no third call, no second tool round
        assert gateway.chat_with_tools_call_count == 2


# ── Immutability tests ──────────────────────────────────────────────────────


class TestImmutability:
    """Input objects unchanged after successful or rejected multi-call run."""

    def test_initial_decision_unchanged_after_batch(self) -> None:
        """AgentDecision unchanged after successful 2-READ batch."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()

        def handler(input_model: StringInput, context: object) -> ResultOutput:
            return ResultOutput(result="ok")

        ok_def = ToolDefinition(
            name="ok_tool",
            description="OK tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(ok_def, handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("ok_tool", {"value": "a"})
        call_b = _make_tool_call("ok_tool", {"value": "b"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"done"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        ok_public = _make_tool_public("ok_tool")
        catalog = ToolRegistrySchema(tools=[ok_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=_make_context())

        # Initial decision unchanged
        assert len(result.initial_decision.request.messages) == 2
        assert result.initial_decision.request.messages[0].role is MessageRole.SYSTEM
        assert result.initial_decision.request.messages[1].role is MessageRole.USER
        assert len(result.initial_decision.response.message.tool_calls) == 2
        assert len(result.initial_decision.exposed_tools) == 1
        assert result.initial_decision.exposed_tools[0].name == "ok_tool"

    def test_tool_calls_unchanged_after_batch(self) -> None:
        """ToolCall objects unchanged after successful 2-READ batch."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        reg = ToolRegistry()

        def handler(input_model: StringInput, context: object) -> ResultOutput:
            return ResultOutput(result="ok")

        ok_def = ToolDefinition(
            name="ok_tool",
            description="OK tool",
            input_schema=StringInput,
            output_schema=ResultOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg.register(ok_def, handler)
        exe = ToolExecutor(reg)

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("ok_tool", {"value": "a"})
        call_b = _make_tool_call("ok_tool", {"value": "b"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"done"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        ok_public = _make_tool_public("ok_tool")
        catalog = ToolRegistrySchema(tools=[ok_public])
        tool_svc = AgentToolExecutionService(tool_executor=exe)

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        loop.run("test", execution_context=_make_context())

        # Original ToolCall objects unchanged
        assert call_a.name == "ok_tool"
        assert call_a.arguments == {"value": "a"}
        assert call_b.name == "ok_tool"
        assert call_b.arguments == {"value": "b"}
