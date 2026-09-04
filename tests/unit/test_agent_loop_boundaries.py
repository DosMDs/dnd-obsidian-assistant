"""Bounded-loop regression tests for the Fast Agent loop (S9-04).

Covers:

- Initial 2+ tool calls -> ModelError, zero ToolExecutor, no second call
- Second response contains tool call -> ModelError, first tool executed once
- Second response multiple tool calls -> same bounded failure
- Malformed direct outcome -> ModelError, zero tools, one model call
- Malformed post-tool outcome -> ModelError, tool executed once, two calls
- Second model ModelError -> propagated, tool executed once, no retry
- Tool-execution failure propagation
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
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)


class StringInput(BaseModel):
    value: str


class ResultOutput(BaseModel):
    result: str


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
    """Matches AgentToolExecutionResult shape for loop compatibility."""

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
        # Build a result with tool_message so the loop can access it
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


class TestInitialMultiCall:
    """Initial 2+ tool calls -> ModelError, zero ToolExecutor, no second call."""

    def test_two_initial_tool_calls_raises_model_error(self) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        tool_call_a = _make_tool_call("read_tool", {"x": "a"})
        tool_call_b = _make_tool_call("read_tool", {"x": "b"})
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling tools...",
                tool_calls=[tool_call_a, tool_call_b],
            )
        )
        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService()
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="does not support multiple initial tool calls"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1

    def test_three_initial_tool_calls_raises_model_error(self) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        calls = [_make_tool_call("read_tool", {"x": str(i)}) for i in range(3)]
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling tools...",
                tool_calls=calls,
            )
        )
        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService()
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="does not support multiple initial tool calls"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1


class TestPostToolToolCall:
    """Second response contains tool call -> ModelError, first tool executed once."""

    def test_second_response_one_tool_call_fails_closed(self) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_tool_call = _make_tool_call("read_tool", {"value": "again"})
        second_response = _make_tool_response(
            content="More data needed...",
            tool_calls=[second_tool_call],
        )

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService(result=ResultOutput(result="done"))
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )

        with pytest.raises(ModelError, match="does not support post-tool tool calls"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 1
        assert gateway.chat_with_tools_call_count == 2

    def test_second_response_multi_tool_calls_fails_closed(self) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_tool_call_a = _make_tool_call("read_tool", {"value": "a"})
        second_tool_call_b = _make_tool_call("read_tool", {"value": "b"})
        second_response = _make_tool_response(
            content="More data...",
            tool_calls=[second_tool_call_a, second_tool_call_b],
        )

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService(result=ResultOutput(result="done"))
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )

        with pytest.raises(ModelError, match="does not support post-tool tool calls"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 1
        assert gateway.chat_with_tools_call_count == 2


class TestMalformedOutcome:
    """Malformed direct/post-tool outcome -> ModelError."""

    def test_malformed_direct_outcome(self) -> None:
        """Malformed direct outcome -> ModelError, zero tools, one model call."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(content="Just plain text, not JSON")
        )
        catalog = ToolRegistrySchema(tools=[])
        fake_svc = _FakeToolExecutionService()
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1

    def test_malformed_post_tool_outcome(self) -> None:
        """Malformed post-tool outcome -> ModelError, tool executed once, two calls."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(content="Plain text response")

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService(result=ResultOutput(result="done"))
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 1
        assert gateway.chat_with_tools_call_count == 2


class TestSecondModelFailure:
    """Second model ModelError -> propagated, tool executed once, no retry."""

    def test_second_model_error_propagated(self) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
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

        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService(result=ResultOutput(result="done"))
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="second model call failed"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 1
        assert gateway.chat_with_tools_call_count == 2


class TestToolExecutionFailure:
    """Tool-execution failures propagate, no second model call."""

    def test_tool_execution_validation_error_no_second_call(self) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )

        gateway = _FakeModelGateway(first_response)

        read_public = ToolPublicDefinition(
            name="read_tool",
            description="Tool read_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_public])
        # Fake service that raises on execute
        failing_svc = _FakeToolExecutionService(result=None)
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=failing_svc,
        )
        with pytest.raises(ValidationError, match="fake execution error"):
            loop.run("test", execution_context=_make_context())

        assert failing_svc.execute_call_count == 1
        assert gateway.chat_with_tools_call_count == 1
