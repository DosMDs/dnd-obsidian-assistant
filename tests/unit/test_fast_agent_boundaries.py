"""Boundary/edge-case tests for the one-step Fast Agent decision boundary (S9-02).

Covers:

- Tool argument boundary preservation
- Failure propagation (context builder, model error, invalid context)
- Determinism / non-mutation
- No forbidden behaviour (execution, second turn, CLI, storage)
- Fresh-process import isolation
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from dnd_assistant.application.agent_context import AgentContext
from dnd_assistant.application.fast_agent import AgentDecision, FastAgent
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode, SideEffect

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_tool(
    name: str,
    *,
    permission: Permission = Permission.READ,
    side_effects: list[SideEffect] | None = None,
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    """Build a ``ToolPublicDefinition`` with minimal boilerplate."""
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
    audit: object = None,
) -> ExecutionContext:
    """Build an ``ExecutionContext`` with minimal boilerplate."""
    return ExecutionContext(
        granted_permission=permission,
        session_mode=session_mode,
        audit=audit,
    )


def _make_context_with(
    *,
    user_input: str = "who is Gandalf?",
) -> AgentContext:
    """Build an ``AgentContext`` with the given values."""
    from dnd_assistant.application.agent_context import AgentContext as AC

    return AC(
        user_input=user_input,
        current_world_tick=12345,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
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


class _FakeAgentContextBuilderRaises:
    """Fake that raises on build."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.build_call_count: int = 0

    def build(self, user_input: str) -> AgentContext:
        self.build_call_count += 1
        raise self._exc


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
        raise AssertionError("chat() should not be called in S9-02")

    def generate_structured(self, request: ChatRequest, schema: type) -> None:
        raise AssertionError("generate_structured() should not be called in S9-02")

    def embed(self, texts: list[str]) -> None:
        raise AssertionError("embed() should not be called in S9-02")

    def health(self) -> None:
        raise AssertionError("health() should not be called in S9-02")


class _FakeModelGatewayRaises:
    """Fake that raises ``ModelError`` on ``chat_with_tools``."""

    def __init__(self) -> None:
        self.chat_with_tools_call_count: int = 0

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.chat_with_tools_call_count += 1
        raise ModelError("fake model failure")

    def chat(self, request: ChatRequest) -> None:
        raise AssertionError("chat() should not be called in S9-02")

    def generate_structured(self, request: ChatRequest, schema: type) -> None:
        raise AssertionError("generate_structured() should not be called in S9-02")

    def embed(self, texts: list[str]) -> None:
        raise AssertionError("embed() should not be called in S9-02")

    def health(self) -> None:
        raise AssertionError("health() should not be called in S9-02")


def _make_tool_response(
    *,
    content: str | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> ToolAwareResponse:
    """Build a ``ToolAwareResponse`` with the given content and tool calls."""
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
    """Build a ``ToolCall``."""
    return ToolCall(
        name=name,
        arguments=arguments or {},
        call_id=call_id,
    )


# ── Tool argument boundary tests ─────────────────────────────────────────────


class TestToolArgumentBoundary:
    """FastAgent does not mutate/coerce model arguments before S9-03."""

    @pytest.fixture
    def read_tool(self) -> ToolPublicDefinition:
        return _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )

    def _decide_with_args(
        self,
        arguments: dict[str, object],
        read_tool: ToolPublicDefinition,
    ) -> AgentDecision:
        catalog = ToolRegistrySchema(tools=[read_tool])
        tool_call = _make_tool_call(name="read_entity", arguments=arguments)
        response = _make_tool_response(tool_calls=[tool_call])
        gateway = _FakeModelGateway(response=response)
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        return agent.decide("test", execution_context=_make_context(permission=Permission.READ))

    def test_empty_dict(self, read_tool: ToolPublicDefinition) -> None:
        decision = self._decide_with_args({}, read_tool)
        assert decision.response.message.tool_calls[0].arguments == {}

    def test_zero_count(self, read_tool: ToolPublicDefinition) -> None:
        decision = self._decide_with_args({"count": 0}, read_tool)
        assert decision.response.message.tool_calls[0].arguments == {"count": 0}

    def test_false_flag(self, read_tool: ToolPublicDefinition) -> None:
        decision = self._decide_with_args({"flag": False}, read_tool)
        assert decision.response.message.tool_calls[0].arguments == {"flag": False}

    def test_none_value(self, read_tool: ToolPublicDefinition) -> None:
        decision = self._decide_with_args({"value": None}, read_tool)
        assert decision.response.message.tool_calls[0].arguments == {"value": None}

    def test_nested_list(self, read_tool: ToolPublicDefinition) -> None:
        decision = self._decide_with_args({"items": [1, {"k": "v"}]}, read_tool)
        assert decision.response.message.tool_calls[0].arguments == {"items": [1, {"k": "v"}]}

    def test_nested_dict(self, read_tool: ToolPublicDefinition) -> None:
        decision = self._decide_with_args(
            {"filter": {"type": "npc", "tags": ["wizard"]}}, read_tool
        )
        assert decision.response.message.tool_calls[0].arguments == {
            "filter": {"type": "npc", "tags": ["wizard"]},
        }


# ── Failure tests ────────────────────────────────────────────────────────────


class TestFailurePropagation:
    """Verify error propagation and zero model calls on pre-model failures."""

    def test_context_builder_validation_error_propagated(self) -> None:
        catalog = ToolRegistrySchema(tools=[])
        builder = _FakeAgentContextBuilderRaises(ValidationError("bad input"))
        gateway = _FakeModelGateway(response=_make_tool_response(content="ok"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        with pytest.raises(ValidationError, match="bad input"):
            agent.decide("test", execution_context=_make_context())
        assert gateway.chat_with_tools_call_count == 0

    def test_context_builder_storage_error_propagated(self) -> None:
        from dnd_assistant.errors import StorageError

        catalog = ToolRegistrySchema(tools=[])
        builder = _FakeAgentContextBuilderRaises(StorageError("storage failure"))
        gateway = _FakeModelGateway(response=_make_tool_response(content="ok"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        with pytest.raises(StorageError, match="storage failure"):
            agent.decide("test", execution_context=_make_context())
        assert gateway.chat_with_tools_call_count == 0

    def test_invalid_execution_context_type(self) -> None:
        catalog = ToolRegistrySchema(tools=[])
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(response=_make_tool_response(content="ok"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        with pytest.raises(TypeError, match="context must be an ExecutionContext"):
            agent.decide("test", execution_context="not_an_execution_context")  # type: ignore[arg-type]
        assert gateway.chat_with_tools_call_count == 0

    def test_model_error_propagated(self) -> None:
        catalog = ToolRegistrySchema(tools=[])
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGatewayRaises()
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        with pytest.raises(ModelError, match="fake model failure"):
            agent.decide("test", execution_context=_make_context())
        assert gateway.chat_with_tools_call_count == 1

    def test_out_of_allowlist_tool_no_second_model_call(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        tool_call = _make_tool_call(name="unknown_tool")
        response = _make_tool_response(tool_calls=[tool_call])
        gateway = _FakeModelGateway(response=response)
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        with pytest.raises(ModelError, match="unknown_tool"):
            agent.decide("test", execution_context=_make_context(permission=Permission.READ))
        assert gateway.chat_with_tools_call_count == 1


# ── Determinism / non-mutation tests ─────────────────────────────────────────


class TestDeterminism:
    """Verify identical inputs produce identical outputs."""

    def test_identical_inputs_produce_identical_decisions(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        response = _make_tool_response(content="Hello")
        ctx = _make_context_with(user_input="who is Gandalf?")

        def _run() -> AgentDecision:
            builder = _FakeAgentContextBuilder(ctx)
            gateway = _FakeModelGateway(response=response)
            agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
            return agent.decide(
                "who is Gandalf?", execution_context=_make_context(permission=Permission.READ)
            )

        d1 = _run()
        d2 = _run()
        assert d1.prompt_version == d2.prompt_version
        assert d1.request.model_dump() == d2.request.model_dump()
        assert d1.response.model_dump() == d2.response.model_dump()
        assert len(d1.exposed_tools) == len(d2.exposed_tools)
        assert d1.exposed_tools[0].name == d2.exposed_tools[0].name

    def test_source_context_unchanged(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        response = _make_tool_response(content="Hello")
        original = _make_context_with(user_input="test query")
        builder = _FakeAgentContextBuilder(original)
        gateway = _FakeModelGateway(response=response)
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        agent.decide("test query", execution_context=_make_context())
        assert builder._context.user_input == "test query"

    def test_decision_exposed_tools_is_tuple(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(response=_make_tool_response(content="Hello"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        decision = agent.decide("test", execution_context=_make_context())
        assert isinstance(decision.exposed_tools, tuple)

    def test_mutable_list_not_stored_as_decision_collection(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(response=_make_tool_response(content="Hello"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        decision = agent.decide("test", execution_context=_make_context())
        assert isinstance(decision.exposed_tools, tuple)
        assert len(decision.exposed_tools) > 0


# ── No forbidden behaviour tests ─────────────────────────────────────────────


class TestNoForbiddenBehavior:
    """Prove S9-02 performs no execution, no second turn, no storage, etc."""

    def test_no_tool_executor_import_in_module_scope(self) -> None:
        """Verify that importing fast_agent doesn't load ToolExecutor.

        Uses a fresh subprocess to avoid cross-test contamination.
        """
        code = textwrap.dedent("""\
            import sys
            import dnd_assistant.application.fast_agent
            forbidden = [
                "dnd_assistant.models.ollama",
                "dnd_assistant.tools.executor",
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

    def test_no_second_model_turn(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(response=_make_tool_response(content="Hello"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        agent.decide("test", execution_context=_make_context())
        assert gateway.chat_with_tools_call_count == 1

    def test_no_chat_generate_structured_embed_health_calls(self) -> None:
        read_tool = _make_tool(
            "read_entity",
            permission=Permission.READ,
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
        )
        catalog = ToolRegistrySchema(tools=[read_tool])
        ctx = _make_context_with()
        builder = _FakeAgentContextBuilder(ctx)
        gateway = _FakeModelGateway(response=_make_tool_response(content="Hello"))
        agent = FastAgent(context_builder=builder, model_gateway=gateway, tool_catalog=catalog)
        agent.decide("test", execution_context=_make_context())
        assert gateway.chat_with_tools_call_count == 1


# ── Fresh-process import test ────────────────────────────────────────────────


class TestFreshProcessImport:
    """Verify import isolation in a fresh subprocess."""

    def test_fresh_import_does_not_load_forbidden_modules(self) -> None:
        code = textwrap.dedent("""\
            import sys
            import dnd_assistant.application.fast_agent
            forbidden = [
                "dnd_assistant.models.ollama",
                "dnd_assistant.tools.executor",
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
