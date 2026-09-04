"""Multi-tool-call policy tests for the Fast Agent loop (S9-05).

Covers:

- 2-READ batch success
- 4-READ batch success
- Execution order == model order
- Same READ tool called multiple times with different arguments
- 5-call rejection before execution
- Large batch (20) rejection before execution
- READ+WRITE rejection before execution
- WRITE+READ rejection before execution
- WRITE+WRITE rejection before execution
- READ+READ+WRITE rejection before execution
- Duplicate non-None call_id rejection
- Multiple None call_id permitted
- Inconsistent exposed-snapshot failure
- Single READ call unchanged
- Single WRITE+audit call unchanged
- Direct clarification unchanged
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from dnd_assistant.application.agent_context import AgentContext
from dnd_assistant.application.agent_loop import (
    AgentLoop,
    AgentOutcomeKind,
)
from dnd_assistant.application.fast_agent import AgentDecision
from dnd_assistant.errors import ModelError
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
    SideEffect,
    ToolDefinition,
)

_FAKE_WORLD_TICK = 12345


class StringInput(BaseModel):
    value: str


class ResultOutput(BaseModel):
    result: str


def read_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"read: {input_model.value}")


def write_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"write: {input_model.value}")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_context_with(
    *,
    user_input: str = "test",
) -> AgentContext:
    from dnd_assistant.application.agent_context import AgentContext as AC

    return AC(
        user_input=user_input,
        current_world_tick=_FAKE_WORLD_TICK,
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
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permission=permission,
        side_effects=[],
        allowed_session_modes=allowed_session_modes
        or [SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
    )


# ── Fakes ────────────────────────────────────────────────────────────────────


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


# ── Fixtures ─────────────────────────────────────────────────────────────────


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


# ── READ batch success tests ────────────────────────────────────────────────


class TestReadBatchSuccess:
    """Successful 2..4 READ-call batches."""

    def test_two_read_calls_succeed(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """2 READ calls: both execute, second model call, terminal outcome."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("read_tool", {"value": "first"})
        call_b = _make_tool_call("read_tool", {"value": "second"})
        first_response = _make_tool_response(
            content="Calling tools...",
            tool_calls=[call_a, call_b],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"done"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=read_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 2
        assert result.tool_executions[0].output.result == "read: first"
        assert result.tool_executions[1].output.result == "read: second"
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert result.outcome.message == "done"
        assert builder.build_call_count == 1

    def test_four_read_calls_succeed(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """4 READ calls: all execute, second model call, terminal outcome."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        calls = [_make_tool_call("read_tool", {"value": str(i)}) for i in range(4)]
        first_response = _make_tool_response(
            content="Calling tools...",
            tool_calls=calls,
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"all done"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=read_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 4
        for i in range(4):
            assert result.tool_executions[i].output.result == f"read: {i}"
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert result.outcome.message == "all done"

    def test_execution_order_equals_model_order(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Execution order matches model-provided call order."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("read_tool", {"value": "a"})
        call_b = _make_tool_call("read_tool", {"value": "b"})
        call_c = _make_tool_call("read_tool", {"value": "c"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b, call_c],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"ok"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=read_context)

        assert len(result.tool_executions) == 3
        assert result.tool_executions[0].tool_call.arguments == {"value": "a"}
        assert result.tool_executions[1].tool_call.arguments == {"value": "b"}
        assert result.tool_executions[2].tool_call.arguments == {"value": "c"}

    def test_same_tool_different_args(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Same READ tool called with different arguments."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)

        call_a = _make_tool_call("read_tool", {"value": "hello"})
        call_b = _make_tool_call("read_tool", {"value": "world"})
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=[call_a, call_b],
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"ok"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=read_context)

        assert len(result.tool_executions) == 2
        assert result.tool_executions[0].output.result == "read: hello"
        assert result.tool_executions[1].output.result == "read: world"


# ── Call-cap rejection tests ────────────────────────────────────────────────


class TestCallCapRejection:
    """5+ initial tool calls rejected before any execution."""

    def test_five_calls_rejected(self) -> None:
        """5 calls -> ModelError, zero execution, one model call."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        calls = [_make_tool_call("read_tool", {"x": str(i)}) for i in range(5)]
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling...",
                tool_calls=calls,
            )
        )
        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="Maximum 4 initial tool calls"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1

    def test_large_batch_rejected(self) -> None:
        """20 calls -> ModelError, zero execution, one model call."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        calls = [_make_tool_call("read_tool", {"x": str(i)}) for i in range(20)]
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling...",
                tool_calls=calls,
            )
        )
        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="Maximum 4 initial tool calls"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1


# ── WRITE-batch rejection tests ─────────────────────────────────────────────


class TestWriteBatchRejection:
    """Multi-call batches containing WRITE tools rejected before execution."""

    def _assert_rejected_before_execution(
        self, tool_calls: list[ToolCall], *, exposed: list[ToolPublicDefinition]
    ) -> None:
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling...",
                tool_calls=tool_calls,
            )
        )
        catalog = ToolRegistrySchema(tools=exposed)
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        # Use WRITE permission context so WRITE tools are exposed by FastAgent
        write_ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=AuditContext(
                operation_id="test",
                real_time=datetime.now(UTC),
                source="test",
            ),
        )
        with pytest.raises(ModelError, match="WRITE tools are not allowed"):
            loop.run("test", execution_context=write_ctx)

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1

    def test_read_plus_write_rejected(self) -> None:
        """READ + WRITE -> ModelError, zero execution."""
        calls = [
            _make_tool_call("read_tool", {"value": "x"}),
            _make_tool_call("write_tool", {"value": "y"}),
        ]
        exposed = [
            _make_tool_public("read_tool"),
            _make_tool_public("write_tool", permission=Permission.WRITE),
        ]
        self._assert_rejected_before_execution(calls, exposed=exposed)

    def test_write_plus_read_rejected(self) -> None:
        """WRITE + READ -> ModelError, zero execution."""
        calls = [
            _make_tool_call("write_tool", {"value": "y"}),
            _make_tool_call("read_tool", {"value": "x"}),
        ]
        exposed = [
            _make_tool_public("write_tool", permission=Permission.WRITE),
            _make_tool_public("read_tool"),
        ]
        self._assert_rejected_before_execution(calls, exposed=exposed)

    def test_write_plus_write_rejected(self) -> None:
        """WRITE + WRITE -> ModelError, zero execution."""
        calls = [
            _make_tool_call("write_tool", {"value": "a"}),
            _make_tool_call("write_tool", {"value": "b"}),
        ]
        exposed = [
            _make_tool_public("write_tool", permission=Permission.WRITE),
        ]
        self._assert_rejected_before_execution(calls, exposed=exposed)

    def test_read_read_write_rejected(self) -> None:
        """READ + READ + WRITE -> ModelError, zero execution."""
        calls = [
            _make_tool_call("read_tool", {"value": "a"}),
            _make_tool_call("read_tool", {"value": "b"}),
            _make_tool_call("write_tool", {"value": "c"}),
        ]
        exposed = [
            _make_tool_public("read_tool"),
            _make_tool_public("write_tool", permission=Permission.WRITE),
        ]
        self._assert_rejected_before_execution(calls, exposed=exposed)


# ── Call-ID policy tests ────────────────────────────────────────────────────


class TestCallIdPolicy:
    """Duplicate non-None call_id rejected; multiple None call_id permitted."""

    def test_duplicate_non_none_call_id_rejected(self) -> None:
        """Duplicate non-None call_id -> ModelError before execution."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        calls = [
            _make_tool_call("read_tool", {"value": "a"}, call_id="abc"),
            _make_tool_call("read_tool", {"value": "b"}, call_id="abc"),
        ]
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling...",
                tool_calls=calls,
            )
        )
        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="Duplicate non-None call_id"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1

    def test_multiple_none_call_id_permitted(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Multiple calls with call_id=None are permitted."""
        from dnd_assistant.application.agent_tool_execution import (
            AgentToolExecutionService,
        )

        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        calls = [
            _make_tool_call("read_tool", {"value": "a"}, call_id=None),
            _make_tool_call("read_tool", {"value": "b"}, call_id=None),
        ]
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=calls,
        )
        second_response = _make_tool_response(content='{"kind":"respond","message":"ok"}')

        gateway = _FakeModelGateway(first_response)
        gateway.chat_with_tools = _make_two_call_gateway(gateway, first_response, second_response)

        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=read_context)

        assert len(result.tool_executions) == 2
        assert result.outcome.kind is AgentOutcomeKind.RESPOND


# ── Exposed-snapshot inconsistency tests ────────────────────────────────────


class TestExposedSnapshotInconsistency:
    """Inconsistent exposed snapshot fails closed.

    Note: FastAgent.decide() already validates tool names against the
    exposure snapshot, so a tool not in the exposed list is caught before
    the loop's multi-call safety check.  This test documents that behavior.
    """

    def test_tool_not_in_exposed_snapshot(self) -> None:
        """Tool call name not in exposed_tools -> ModelError before execution."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        calls = [
            _make_tool_call("unknown_tool", {"value": "x"}),
            _make_tool_call("read_tool", {"value": "y"}),
        ]
        gateway = _FakeModelGateway(
            response=_make_tool_response(
                content="Calling...",
                tool_calls=calls,
            )
        )
        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        with pytest.raises(ModelError, match="not in the exposed-tool allowlist"):
            loop.run("test", execution_context=_make_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 1


# ── Single-call unchanged tests ─────────────────────────────────────────────


class TestSingleCallUnchanged:
    """Single READ/WRITE calls remain unchanged from S9-04."""

    def test_single_read_call_unchanged(
        self, registry: ToolRegistry, read_context: ExecutionContext
    ) -> None:
        """Single READ call: one execution, second model call, terminal."""
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

        read_public = _make_tool_public("read_tool")
        catalog = ToolRegistrySchema(tools=[read_public])
        tool_svc = AgentToolExecutionService(tool_executor=ToolExecutor(registry))

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=tool_svc,
        )
        result = loop.run("test", execution_context=read_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].output.result == "read: hello"
        assert result.outcome.kind is AgentOutcomeKind.RESPOND

    def test_single_write_with_audit_unchanged(
        self, registry: ToolRegistry, write_context: ExecutionContext
    ) -> None:
        """Single WRITE+audit call: one execution, second model call, terminal."""
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

        write_public = _make_tool_public(
            "write_tool",
            permission=Permission.WRITE,
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
        result = loop.run("test", execution_context=write_context)

        assert gateway.chat_with_tools_call_count == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].output.result == "write: world"
        assert result.outcome.kind is AgentOutcomeKind.RESPOND

    def test_direct_clarification_unchanged(self) -> None:
        """Direct clarify: zero executions, one model call, CLARIFY outcome."""
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(
            response=_make_tool_response(content='{"kind":"clarify","message":"Which one?"}')
        )
        catalog = ToolRegistrySchema(tools=[])
        fake_svc = _FakeToolExecutionService()

        loop = AgentLoop(
            context_builder=builder,
            model_gateway=gateway,
            tool_catalog=catalog,
            tool_execution_service=fake_svc,
        )
        result = loop.run("test", execution_context=_make_context())

        assert gateway.chat_with_tools_call_count == 1
        assert fake_svc.execute_call_count == 0
        assert result.tool_executions == ()
        assert result.outcome.kind is AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "Which one?"


# ── Helper: _FakeToolExecutionService ───────────────────────────────────────


class _FakeToolExecutionService:
    """Fake that records calls but does not validate exposed tools."""

    def __init__(self) -> None:
        self.execute_call_count: int = 0

    def execute(
        self,
        decision: AgentDecision,
        tool_call: ToolCall,
        *,
        execution_context: ExecutionContext,
    ) -> object:
        self.execute_call_count += 1
        return None
