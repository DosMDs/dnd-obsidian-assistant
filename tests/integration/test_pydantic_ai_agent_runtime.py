"""PAIM-08: Pydantic AI bounded agent runtime — core acceptance tests.

All tests use ``FunctionModel`` for deterministic model responses and require
no real Ollama or network access.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import (
    AgentContext,
    AgentContextBuilder,
)
from dnd_assistant.application.agent_loop import (
    AgentOutcomeKind,
    AgentRunResult,
)
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.models.types import (
    MessageRole,
)
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
)
from tests.support.pydantic_ai_runtime import (
    HandlerCounters,
    make_handler_counters,
    make_tool_registry,
)

# ==============================================================================
# Constants
# ==============================================================================

_FAKE_WORLD_TICK = 12345

# ==============================================================================
# Helpers
# ==============================================================================


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
    audit: AuditContext | None = None,
) -> ExecutionContext:
    """Build an ``ExecutionContext`` with minimal boilerplate."""
    return ExecutionContext(
        granted_permission=permission,
        session_mode=session_mode,
        audit=audit,
    )


def _make_function_model(
    response_fn: Any,
) -> FunctionModel:
    """Create a ``FunctionModel`` from a response-producing callback.

    The callback receives ``(messages, agent_info)`` and returns a
    ``ModelResponse``.
    """
    return FunctionModel(response_fn)


def _make_respond_response(content: str) -> ModelResponse:
    """Create a ``ModelResponse`` with a single ``TextPart`` containing
    a respond-kind JSON."""
    payload = json.dumps(
        {"kind": "respond", "message": content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ModelResponse(parts=[TextPart(content=payload)])


def _make_clarify_response(content: str) -> ModelResponse:
    """Create a ``ModelResponse`` with a single ``TextPart`` containing
    a clarify-kind JSON."""
    payload = json.dumps(
        {"kind": "clarify", "message": content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ModelResponse(parts=[TextPart(content=payload)])


def _make_tool_call_response(
    tool_name: str,
    *,
    tool_call_id: str | None = None,
    args: dict[str, Any] | None = None,
    text: str | None = None,
) -> ModelResponse:
    """Create a ``ModelResponse`` with a ``ToolCallPart`` and optional text."""
    parts: list[Any] = []
    if text is not None:
        parts.append(TextPart(content=text))
    parts.append(
        ToolCallPart(
            tool_name=tool_name,
            args=args or {"x": 42},
            tool_call_id=tool_call_id,
        )
    )
    return ModelResponse(parts=parts)


def _make_runtime(
    model: Model,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
) -> PydanticAIAgentRuntime:
    """Create a ``PydanticAIAgentRuntime`` with the given components."""
    tool_bridge = PydanticAIToolBridge(registry=tool_registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=tool_catalog,
        tool_bridge=tool_bridge,
    )
    return PydanticAIAgentRuntime(
        run_preparer=preparer,
        model=model,
    )


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def counters() -> HandlerCounters:
    return make_handler_counters()


@pytest.fixture
def tool_registry(counters: HandlerCounters) -> ToolRegistry:
    return make_tool_registry(counters)


@pytest.fixture
def tool_catalog(tool_registry: ToolRegistry) -> ToolRegistrySchema:
    from dnd_assistant.tools.catalog import build_tool_registry_schema

    return build_tool_registry_schema(tool_registry)


@pytest.fixture
def tool_bridge(tool_registry: ToolRegistry) -> PydanticAIToolBridge:
    return PydanticAIToolBridge(registry=tool_registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
    """Return a minimal AgentContextBuilder that returns a fixed context."""
    from dnd_assistant.errors import NotFoundError
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.retrieval.types import SearchHit, SearchQuery
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.session_metadata import RawSessionMetadata
    from dnd_assistant.storage.types import VaultDocument, VaultRepository

    class _StubSearchService(SearchService):
        def search(self, query: SearchQuery, *, limit: int = 5) -> Sequence[SearchHit]:
            return []

    class _StubVaultRepository(VaultRepository):
        def get_entity(self, entity_id: str) -> VaultDocument:
            raise ValueError("unexpected call")

    class _StubSessionRepo:
        def get_active_session(self) -> RawSessionMetadata | None:
            return None

    class _StubEventRepo:
        def list_events(self, session_id: str) -> list[RawSessionEvent]:
            return []

    class _StubWorldTimeRepo:
        def get_current_world_time(self) -> None:
            raise NotFoundError("no world time")

    return AgentContextBuilder(
        search_service=_StubSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),  # type: ignore[arg-type]
        event_repository=_StubEventRepo(),  # type: ignore[arg-type]
        world_time_repository=_StubWorldTimeRepo(),  # type: ignore[arg-type]
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return _make_context(
        permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return _make_context(
        permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


@pytest.fixture
def write_context_no_audit() -> ExecutionContext:
    return _make_context(
        permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


# ==============================================================================
# P8-01: Direct respond path
# ==============================================================================


class TestP801DirectRespond:
    """P8-01: Direct respond — one model request, zero tools, respond outcome."""

    def test_direct_respond(
        self,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns direct respond JSON — runtime returns AgentRunResult."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_respond_response("Hello, world!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test input", execution_context=read_context)

        assert isinstance(result, AgentRunResult)
        assert request_count[0] == 1
        assert result.tool_executions == ()
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Hello, world!"
        assert result.initial_decision.prompt_version == PROMPT_VERSION
        assert result.final_response is result.initial_decision.response


# ==============================================================================
# P8-02: Direct clarify path
# ==============================================================================


class TestP802DirectClarify:
    """P8-02: Direct clarify — one model request, zero tools, clarify outcome."""

    def test_direct_clarify(
        self,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns direct clarify JSON — runtime returns AgentRunResult."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_clarify_response("What do you mean?")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test input", execution_context=read_context)

        assert isinstance(result, AgentRunResult)
        assert request_count[0] == 1
        assert result.tool_executions == ()
        assert result.outcome.kind == AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "What do you mean?"


# ==============================================================================
# P8-03: Single READ → respond
# ==============================================================================


class TestP803SingleReadRespond:
    """P8-03: Single READ tool call → respond outcome."""

    def test_single_read_respond(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model calls one READ tool, runtime executes it, model responds."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-1",
                    args={"value": "hello"},
                    text="Looking up...",
                )
            return _make_respond_response("Found it!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("find something", execution_context=read_context)

        assert isinstance(result, AgentRunResult)
        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_call.name == "read_alpha"
        assert result.tool_executions[0].output.result == "alpha:hello"
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Found it!"
        # First response text preserved
        assert result.initial_decision.response.message.content == "Looking up..."
        assert len(result.initial_decision.response.message.tool_calls) == 1
        # Handler was invoked exactly once
        assert counters.alpha == 1


# ==============================================================================
# P8-04: Single READ → clarify
# ==============================================================================


class TestP804SingleReadClarify:
    """P8-04: Single READ tool call → clarify outcome."""

    def test_single_read_clarify(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model calls one READ tool, runtime executes it, model clarifies."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-1",
                    args={"value": "test"},
                )
            return _make_clarify_response("Which one?")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("query", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert result.outcome.kind == AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "Which one?"
        assert counters.alpha == 1


# ==============================================================================
# P8-05: Single WRITE → respond
# ==============================================================================


class TestP805SingleWriteRespond:
    """P8-05: Single WRITE tool call → respond outcome."""

    def test_single_write_respond(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """Model calls one WRITE tool, runtime executes it through bridge."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "write_alpha",
                    tool_call_id="call-w1",
                    args={"value": "save"},
                )
            return _make_respond_response("Written!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("save data", execution_context=write_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_call.name == "write_alpha"
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Written!"
        assert counters.write_alpha == 1


# ==============================================================================
# P8-06: 2 READ sequential
# ==============================================================================


class TestP806TwoReadSequential:
    """P8-06: Two READ tool calls executed sequentially."""

    def test_two_read_sequential(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model calls two READ tools, both execute in order, model responds."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "first"},
                            tool_call_id="call-a",
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 42},
                            tool_call_id="call-b",
                        ),
                    ]
                )
            return _make_respond_response("Both done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("read both", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 2
        assert result.tool_executions[0].tool_call.name == "read_alpha"
        assert result.tool_executions[0].output.result == "alpha:first"
        assert result.tool_executions[1].tool_call.name == "read_beta"
        assert result.tool_executions[1].output.result == "beta:42"
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Both done!"
        assert counters.alpha == 1
        assert counters.beta == 1


# ==============================================================================
# P8-07: 4 READ maximum
# ==============================================================================


class TestP807FourReadMaximum:
    """P8-07: Four READ tool calls — exact maximum batch."""

    def test_four_read_maximum(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model calls four READ tools, all execute in order, model responds."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 1}, tool_call_id="c2"),
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "b"}, tool_call_id="c3"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 2}, tool_call_id="c4"),
                    ]
                )
            return _make_respond_response("All four done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("read all", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 4
        assert result.tool_executions[0].tool_call.name == "read_alpha"
        assert result.tool_executions[0].output.result == "alpha:a"
        assert result.tool_executions[1].tool_call.name == "read_beta"
        assert result.tool_executions[1].output.result == "beta:1"
        assert result.tool_executions[2].tool_call.name == "read_alpha"
        assert result.tool_executions[2].output.result == "alpha:b"
        assert result.tool_executions[3].tool_call.name == "read_beta"
        assert result.tool_executions[3].output.result == "beta:2"
        assert result.outcome.message == "All four done!"
        assert counters.alpha == 2
        assert counters.beta == 2


# ==============================================================================
# P8-08: Repeated same READ with distinct IDs
# ==============================================================================


class TestP808RepeatedSameRead:
    """P8-08: Repeated same READ tool with distinct call IDs."""

    def test_repeated_same_read(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model calls same READ tool twice with distinct IDs — both execute."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "x"}, tool_call_id="c1"
                        ),
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "y"}, tool_call_id="c2"
                        ),
                    ]
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("read twice", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 2
        assert result.tool_executions[0].output.result == "alpha:x"
        assert result.tool_executions[1].output.result == "alpha:y"
        assert counters.alpha == 2


# ==============================================================================
# P8-09: Exact deterministic tool-result replay
# ==============================================================================


class TestP809DeterministicToolResultReplay:
    """P8-09: Tool results are replayed as deterministic TOOL JSON."""

    def test_tool_result_replay(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Tool result JSON matches expected deterministic format."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-r1",
                    args={"value": "replay"},
                )
            return _make_respond_response("Replayed!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test replay", execution_context=read_context)

        assert len(result.tool_executions) == 1
        execution = result.tool_executions[0]
        # Tool message has deterministic JSON content
        assert execution.tool_message.role == MessageRole.TOOL
        assert execution.tool_message.tool_name == "read_alpha"
        assert execution.tool_message.tool_call_id == "call-r1"
        assert '"result":"alpha:replay"' in execution.tool_message.content
        assert execution.tool_message.content == json.dumps(
            {"result": "alpha:replay"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


# ==============================================================================
# P8-10: Same exposure on both model requests
# ==============================================================================


class TestP810SameExposureOnBothRequests:
    """P8-10: Same exposure snapshot is used on request #1 and #2."""

    def test_same_exposure(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Both model requests see the same tool exposure."""
        request_count: list[int] = [0]
        captured_agent_info: list[Any] = []

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            captured_agent_info.append(agent_info)
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-e1",
                    args={"value": "exposure"},
                )
            return _make_respond_response("Same!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        runtime.run("test exposure", execution_context=read_context)

        assert request_count[0] == 2
        assert len(captured_agent_info) == 2
        # Both requests see the same function tools
        info_1 = captured_agent_info[0]
        info_2 = captured_agent_info[1]
        assert info_1.function_tools == info_2.function_tools


# ==============================================================================
# P8-11: Context preparation exactly once
# ==============================================================================


class TestP811ContextPreparationOnce:
    """P8-11: Context preparation happens exactly once per run."""

    def test_preparation_once(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        read_context: ExecutionContext,
    ) -> None:
        """AgentContextBuilder.build() is called exactly once."""
        build_count: list[int] = [0]

        class CountingContextBuilder(AgentContextBuilder):
            def __init__(self) -> None:
                # Pass stub dependencies to parent
                from dnd_assistant.errors import NotFoundError
                from dnd_assistant.retrieval.service import SearchService
                from dnd_assistant.retrieval.types import SearchHit, SearchQuery
                from dnd_assistant.storage.session_events import RawSessionEvent
                from dnd_assistant.storage.session_metadata import RawSessionMetadata
                from dnd_assistant.storage.types import VaultDocument, VaultRepository

                class _StubSearchService(SearchService):
                    def search(self, query: SearchQuery, *, limit: int = 5) -> Sequence[SearchHit]:
                        return []

                class _StubVaultRepository(VaultRepository):
                    def get_entity(self, entity_id: str) -> VaultDocument:
                        raise ValueError("unexpected call")

                class _StubSessionRepo:
                    def get_active_session(self) -> RawSessionMetadata | None:
                        return None

                class _StubEventRepo:
                    def list_events(self, session_id: str) -> list[RawSessionEvent]:
                        return []

                class _StubWorldTimeRepo:
                    def get_current_world_time(self) -> None:
                        raise NotFoundError("no world time")

                super().__init__(
                    search_service=_StubSearchService(),
                    vault_repository=_StubVaultRepository(),
                    session_repository=_StubSessionRepo(),  # type: ignore[arg-type]
                    event_repository=_StubEventRepo(),  # type: ignore[arg-type]
                    world_time_repository=_StubWorldTimeRepo(),  # type: ignore[arg-type]
                )

            def build(self, user_input: str) -> AgentContext:
                build_count[0] += 1
                return AgentContext(
                    user_input=user_input,
                    current_world_tick=_FAKE_WORLD_TICK,
                    active_session=None,
                    relevant_entities=(),
                    recent_events=(),
                )

        context_builder = CountingContextBuilder()
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-p1",
                    args={"value": "once"},
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        runtime.run("test once", execution_context=read_context)

        assert request_count[0] == 2
        assert build_count[0] == 1


# ==============================================================================
# P8-12: Same framework run continuation
# ==============================================================================


class TestP812SameFrameworkRun:
    """P8-12: Tool path uses one single Pydantic AI run."""

    def test_same_run_identity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """The same Pydantic AI run is used for both model requests."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-rid",
                    args={"value": "same"},
                )
            return _make_respond_response("Same run!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test run id", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
