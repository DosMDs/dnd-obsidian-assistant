"""Core orchestration tests for the bounded Fast Agent loop (S9-04).

Covers:

- Direct respond path (one model call, zero tools)
- Direct clarify path (one model call, zero tools)
- Single-tool path (model -> ToolExecutor -> model)
- Exact follow-up request history
- Exact exposed-tool snapshot reuse
- ContextBuilder call count
- Real ToolExecutor execution (READ, WRITE+audit, WRITE without audit)
- WRITE safety regression
- Direct clarification must not mutate
- Prompt-v2 assertions
- Terminal outcome schema tests
- Import boundary
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.agent_context import AgentContext
from dnd_assistant.application.agent_loop import (
    AgentLoop,
    AgentOutcomeKind,
    AgentTextOutcome,
    _parse_agent_outcome,
)
from dnd_assistant.application.fast_agent import AgentDecision, FastAgent
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION, SYSTEM_PROMPT
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

_FAKE_WORLD_TICK = 12345


class StringInput(BaseModel):
    value: str


class ResultOutput(BaseModel):
    result: str


class EmptyOutput(BaseModel):
    pass


def read_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"read: {input_model.value}")


def write_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"write: {input_model.value}")


def _make_tool(
    name: str,
    *,
    permission: Permission = Permission.READ,
    side_effects: list[SideEffect] | None = None,
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        permission=permission,
        side_effects=side_effects or [],
        allowed_session_modes=allowed_session_modes or [SessionMode.NO_ACTIVE_SESSION],
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


def _make_context_with(
    *,
    user_input: str = "who is Gandalf?",
) -> AgentContext:
    from dnd_assistant.application.agent_context import AgentContext as AC

    return AC(
        user_input=user_input,
        current_world_tick=_FAKE_WORLD_TICK,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
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


# ── Fakes ──────────────────────────────────────────────────────────────────────


class _FakeAgentContextBuilder:
    """Fake ``AgentContextBuilder`` that returns a pre-built context."""

    def __init__(self, context: AgentContext) -> None:
        self._context = context
        self.build_call_count: int = 0

    def build(self, user_input: str) -> AgentContext:
        self.build_call_count += 1
        return self._context


class _FakeModelGateway:
    """Fake ``ModelGateway`` that records calls and returns pre-built responses."""

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


class _FakeToolExecutionService:
    """Fake ``AgentToolExecutionService`` that records calls."""

    def __init__(self, result: object = None) -> None:
        self._result = result
        self.execute_call_count: int = 0
        self.last_decision: AgentDecision | None = None
        self.last_tool_call: ToolCall | None = None
        self.last_context: ExecutionContext | None = None

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
        return self._result


# ── Two-call gateway helper ────────────────────────────────────────────────────


def _make_two_call_gateway(
    fake: _FakeModelGateway,
    first: ToolAwareResponse,
    second: ToolAwareResponse,
) -> Any:
    """Replace chat_with_tools to return first on call 1, second on call 2."""
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
def registry(
    read_tool_def: ToolDefinition,
    write_tool_def: ToolDefinition,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_tool_def, read_handler)
    reg.register(write_tool_def, write_handler)
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


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


# ── Direct-path tests ─────────────────────────────────────────────────────────


class TestDirectPath:
    """Direct respond/clarify path: one model call, zero tools."""

    def test_respond_json_one_model_call_zero_tools(self) -> None:
        """respond JSON -> one model call, zero tools, RESPOND outcome."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content='{"kind":"respond","message":"Gandalf is a wizard"}'
            )
        )
        catalog = ToolRegistrySchema(tools=[])
        fake_svc = _FakeToolExecutionService()
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        result = loop.run("who is Gandalf?", execution_context=_make_context())

        assert gateway.chat_with_tools_call_count == 1
        assert fake_svc.execute_call_count == 0
        assert result.tool_executions == ()
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Gandalf is a wizard"
        assert builder.build_call_count == 1

    def test_clarify_json_one_model_call_zero_tools(self) -> None:
        """clarify JSON -> one model call, zero tools, CLARIFY outcome."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content='{"kind":"clarify","message":"Which Varos do you mean?"}'
            )
        )
        catalog = ToolRegistrySchema(tools=[])
        fake_svc = _FakeToolExecutionService()
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        result = loop.run("tell me about Varos", execution_context=_make_context())

        assert gateway.chat_with_tools_call_count == 1
        assert fake_svc.execute_call_count == 0
        assert result.tool_executions == ()
        assert result.outcome.kind is AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "Which Varos do you mean?"
        assert builder.build_call_count == 1


# ── Single-tool path tests ─────────────────────────────────────────────────────


class TestSingleToolPath:
    """Single-tool path: model -> ToolExecutor -> model."""

    def test_tool_then_respond(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """First model requests one tool -> executed -> second response parsed."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(
            content='{"kind":"respond","message":"Found: read: hello"}'
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
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("lookup hello", execution_context=read_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].output.result == "read: hello"
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Found: read: hello"
        assert builder.build_call_count == 1

    def test_tool_then_clarify(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Tool -> clarify path."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(
            content='{"kind":"clarify","message":"Which record do you mean?"}'
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
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("lookup hello", execution_context=read_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].output.result == "read: hello"
        assert result.outcome.kind is AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "Which record do you mean?"
        assert builder.build_call_count == 1


# ── Follow-up request tests ────────────────────────────────────────────────────


class TestFollowUpRequest:
    """Exact follow-up request history and exposed-tool snapshot."""

    def test_exact_follow_up_history(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Assert the actual follow-up request tuple is value-equal."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"ok"}')

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
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("lookup hello", execution_context=read_context)

        assert gateway.last_request is not None
        msgs = gateway.last_request.messages
        assert len(msgs) == 4
        assert msgs[0].role is MessageRole.SYSTEM
        assert msgs[1].role is MessageRole.USER
        assert msgs[2].role is MessageRole.ASSISTANT
        assert msgs[3].role is MessageRole.TOOL
        expected = ChatRequest(
            messages=(
                *result.initial_decision.request.messages,
                result.initial_decision.response.message,
                result.tool_executions[0].tool_message,
            )
        )
        assert gateway.last_request == expected

    def test_exact_exposed_tool_snapshot_reuse(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Second model call receives the exact same exposed-tool snapshot."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"ok"}')

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
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("lookup hello", execution_context=read_context)

        assert gateway.last_tools is not None
        first_names = [t.name for t in result.initial_decision.exposed_tools]
        second_names = [t.name for t in gateway.last_tools]
        assert first_names == second_names

    def test_original_request_response_unchanged(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Original initial request and response are unchanged after loop."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        first_response = _make_tool_response(
            content="Looking up...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"ok"}')

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
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("lookup hello", execution_context=read_context)

        assert len(result.initial_decision.request.messages) == 2
        assert result.initial_decision.request.messages[0].role is MessageRole.SYSTEM
        assert result.initial_decision.request.messages[1].role is MessageRole.USER
        assert result.initial_decision.response.message.content == "Looking up..."
        assert len(result.initial_decision.response.message.tool_calls) == 1
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_call.name == "read_tool"


# ── WRITE safety tests ─────────────────────────────────────────────────────────


class TestWriteSafety:
    """WRITE tool loop and audit prerequisite."""

    def test_write_tool_with_audit_executes_once(
        self, registry: ToolRegistry, write_context: ExecutionContext
    ) -> None:
        """WRITE tool with audit: handler executes once, TOOL result replayed."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("write_tool", {"value": "world"})
        first_response = _make_tool_response(
            content="Writing...",
            tool_calls=[tool_call],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"written"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        write_public = ToolPublicDefinition(
            name="write_tool",
            description="Tool write_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.WRITE,
            side_effects=[SideEffect.ENTITY_MUTATION],
            allowed_session_modes=[SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[write_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("write world", execution_context=write_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].output.result == "write: world"
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert result.outcome.message == "written"

    def test_write_tool_without_audit_fails(self) -> None:
        """WRITE tool without audit: FastAgent hides WRITE tools, ModelError raised."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        tool_call = _make_tool_call("write_tool", {"value": "world"})
        first_response = _make_tool_response(
            content="Writing...",
            tool_calls=[tool_call],
        )

        gateway = _FakeModelGateway(first_response)

        write_public = ToolPublicDefinition(
            name="write_tool",
            description="Tool write_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.WRITE,
            side_effects=[SideEffect.ENTITY_MUTATION],
            allowed_session_modes=[SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[write_public])
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        no_audit_ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=None,
        )
        with pytest.raises(ModelError, match="not in the exposed-tool allowlist"):
            loop.run("write world", execution_context=no_audit_ctx)

        # Model called once, no tool execution (tool was hidden by exposure policy)
        assert gateway.chat_with_tools_call_count == 1
        assert fake_svc.execute_call_count == 0


# ── Clarification safety tests ─────────────────────────────────────────────────


class TestClarificationSafety:
    """Direct clarification must not mutate."""

    def test_clarify_with_write_authority_zero_mutation(self) -> None:
        """Clarify with WRITE authority/tools exposed: zero ToolExecutor calls."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(content='{"kind":"clarify","message":"Which target?"}')
        )
        write_public = ToolPublicDefinition(
            name="write_tool",
            description="Tool write_tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.WRITE,
            side_effects=[SideEffect.ENTITY_MUTATION],
            allowed_session_modes=[SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[write_public])
        fake_svc = _FakeToolExecutionService()
        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        write_ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=AuditContext(
                operation_id="test",
                real_time=datetime.now(UTC),
                source="test",
            ),
        )
        result = loop.run("write something", execution_context=write_ctx)

        assert result.outcome.kind is AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "Which target?"
        assert fake_svc.execute_call_count == 0
        assert result.tool_executions == ()


# ── Prompt-v2 tests ────────────────────────────────────────────────────────────


class TestPromptV2:
    """Verify agent-v2 prompt properties."""

    def test_prompt_version_is_agent_v2(self) -> None:
        assert PROMPT_VERSION == "agent-v2"

    def test_system_prompt_contains_campaign_context_is_data(self) -> None:
        assert "reference DATA" in SYSTEM_PROMPT

    def test_system_prompt_forbids_invented_ids(self) -> None:
        assert "Never invent" in SYSTEM_PROMPT

    def test_system_prompt_requires_clarification(self) -> None:
        assert "clarifying question" in SYSTEM_PROMPT

    def test_system_prompt_requires_terminal_json(self) -> None:
        assert '{"kind":"respond"' in SYSTEM_PROMPT
        assert '{"kind":"clarify"' in SYSTEM_PROMPT

    def test_system_prompt_says_native_tool_mechanism(self) -> None:
        assert "native tool-calling mechanism" in SYSTEM_PROMPT

    def test_system_prompt_forbids_claiming_success_before_result(self) -> None:
        assert "Never claim" in SYSTEM_PROMPT

    def test_system_prompt_instructs_terminal_after_tool_result(self) -> None:
        assert "After a tool result" in SYSTEM_PROMPT

    def test_active_fast_agent_uses_agent_v2(self) -> None:
        """FastAgent's active prompt is agent-v2."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(content='{"kind":"respond","message":"ok"}')
        )
        agent = FastAgent(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=ToolRegistrySchema(tools=[]),
        )
        decision = agent.decide("test", execution_context=_make_context())
        assert decision.prompt_version == "agent-v2"


# ── Terminal outcome schema tests ──────────────────────────────────────────────


class TestTerminalOutcomeSchema:
    """AgentTextOutcome validation and _parse_agent_outcome."""

    def test_respond_normal_message(self) -> None:
        outcome = AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Hello")
        assert outcome.kind is AgentOutcomeKind.RESPOND
        assert outcome.message == "Hello"

    def test_clarify_normal_message(self) -> None:
        outcome = AgentTextOutcome(kind=AgentOutcomeKind.CLARIFY, message="Which one?")
        assert outcome.kind is AgentOutcomeKind.CLARIFY
        assert outcome.message == "Which one?"

    def test_unicode_message(self) -> None:
        outcome = AgentTextOutcome(
            kind=AgentOutcomeKind.RESPOND,
            message="\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444",
        )
        assert outcome.message == "\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444"

    def test_empty_message_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="")

    def test_whitespace_only_message_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="   ")

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome.model_validate({"kind": "unknown", "message": "x"})

    def test_missing_kind_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome.model_validate({"message": "x"})

    def test_missing_message_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome.model_validate({"kind": "respond"})

    def test_extra_field_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome.model_validate({"kind": "respond", "message": "x", "extra": 1})

    def test_parse_respond(self) -> None:
        response = _make_tool_response(content='{"kind":"respond","message":"Hello"}')
        outcome = _parse_agent_outcome(response)
        assert outcome.kind is AgentOutcomeKind.RESPOND
        assert outcome.message == "Hello"

    def test_parse_clarify(self) -> None:
        response = _make_tool_response(content='{"kind":"clarify","message":"Which?"}')
        outcome = _parse_agent_outcome(response)
        assert outcome.kind is AgentOutcomeKind.CLARIFY
        assert outcome.message == "Which?"

    def test_parse_plain_text_raises_model_error(self) -> None:
        response = _make_tool_response(content="Just some plain text")
        with pytest.raises(ModelError):
            _parse_agent_outcome(response)

    def test_parse_empty_content_raises_model_error(self) -> None:
        msg = ChatMessage.model_construct(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(),
        )
        response = ToolAwareResponse.model_construct(message=msg)
        with pytest.raises(ModelError):
            _parse_agent_outcome(response)

    def test_parse_json_array_raises_model_error(self) -> None:
        response = _make_tool_response(content="[1, 2, 3]")
        with pytest.raises(ModelError):
            _parse_agent_outcome(response)

    def test_parse_empty_json_object_raises_model_error(self) -> None:
        response = _make_tool_response(content="{}")
        with pytest.raises(ModelError):
            _parse_agent_outcome(response)

    def test_parse_with_tool_calls_raises_model_error(self) -> None:
        tool_call = _make_tool_call("read_tool", {"x": "y"})
        response = _make_tool_response(
            content='{"kind":"respond","message":"x"}',
            tool_calls=[tool_call],
        )
        with pytest.raises(ModelError, match="tool calls"):
            _parse_agent_outcome(response)


# ── Import boundary tests ──────────────────────────────────────────────────────


class TestImportBoundary:
    """Fresh import must not eagerly load forbidden modules."""

    def test_fresh_import_does_not_load_forbidden_modules(self) -> None:
        import subprocess
        import sys
        import textwrap

        code = textwrap.dedent("""\
            import sys
            import dnd_assistant.application.agent_loop
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
