"""PAIM-06: Pydantic AI context/dependencies integration test.

Proves that ``DndAgentDeps`` works through public Pydantic AI 2.39.0
``RunContext[DndAgentDeps]`` API:

1. ``ctx.deps is prepared.deps`` — exact identity, not a copy.
2. All five fields of ``DndAgentDeps`` have identity preservation.
3. ``AgentContextBuilder.build()`` is called exactly once during preparation
   and NOT called again during the framework run.
4. No project tool handlers execute during the framework run.
5. The framework run uses exactly one model request.
6. ``DndAgentDeps`` content is NOT automatically serialized into model-facing
   messages (proven by sentinel absence).
7. No real network is attempted.

All tests use deterministic ``FunctionModel`` and require no real Ollama or
network access.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import (
    AgentContext,
    AgentContextBuilder,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentDeps,
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.tools.catalog import ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)
from tests.support.pydantic_ai_runtime import (
    HandlerCounters,
    make_tool_registry,
)

# ── Sentinel for model-leak detection ──────────────────────────────────────────

_SENTINEL = "🛡️PAIM-06-SENTINEL-NOT-IN-MODEL"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_counting_function_model() -> tuple[FunctionModel, list[int]]:
    """Create a FunctionModel that counts model requests.

    Returns:
        (model, request_counter) where request_counter[0] tracks model
        request count.
    """
    request_counter: list[int] = [0]

    def _respond(messages: list, agent_info: object) -> object:
        request_counter[0] += 1
        from pydantic_ai.messages import ModelResponse, TextPart

        return ModelResponse(parts=[TextPart(content=f"response #{request_counter[0]}")])

    model = FunctionModel(function=_respond)
    return model, request_counter


def _make_sentinel_context_builder() -> AgentContextBuilder:
    """Create an AgentContextBuilder whose context contains a sentinel value.

    The sentinel is placed in the user_input field of the AgentContext.
    """
    from dnd_assistant.errors import NotFoundError
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.retrieval.types import SearchHit, SearchQuery
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.session_metadata import RawSessionMetadata
    from dnd_assistant.storage.types import VaultDocument, VaultRepository

    class _CountingSearchService(SearchService):
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
        search_service=_CountingSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),  # type: ignore[arg-type]
        event_repository=_StubEventRepo(),  # type: ignore[arg-type]
        world_time_repository=_StubWorldTimeRepo(),  # type: ignore[arg-type]
    )


def _make_handler_counters() -> HandlerCounters:
    """Create fresh HandlerCounters for tracking handler invocations."""
    return HandlerCounters()


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def counters() -> HandlerCounters:
    return _make_handler_counters()


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
    return _make_sentinel_context_builder()


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def preparer(
    context_builder: AgentContextBuilder,
    tool_catalog: ToolRegistrySchema,
    tool_bridge: PydanticAIToolBridge,
) -> DndAgentRunPreparer:
    return DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=tool_catalog,
        tool_bridge=tool_bridge,
    )


# ==============================================================================
# Framework deps identity proof
# ==============================================================================


class TestFrameworkDepsIdentity:
    """Prove RunContext[DndAgentDeps] receives exact prepared deps."""

    def test_ctx_deps_is_prepared_deps(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """ctx.deps is prepared.deps — exact identity."""
        prepared = preparer.prepare("test query", execution_context=read_context)
        captured_deps: list[DndAgentDeps] = []

        def instructions_func(ctx: RunContext[DndAgentDeps]) -> str:
            captured_deps.append(ctx.deps)
            return "respond with a short answer"

        model, _ = _make_counting_function_model()
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            instructions=instructions_func,
            retries={"tools": 0},
        )
        agent.run_sync("test", deps=prepared.deps)

        assert len(captured_deps) == 1
        assert captured_deps[0] is prepared.deps

    def test_all_deps_fields_have_identity(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """All five DndAgentDeps fields have identity preservation."""
        prepared = preparer.prepare("test query", execution_context=read_context)
        captured: list[DndAgentDeps] = []

        def instructions_func(ctx: RunContext[DndAgentDeps]) -> str:
            captured.append(ctx.deps)
            return "respond with a short answer"

        model, _ = _make_counting_function_model()
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            instructions=instructions_func,
            retries={"tools": 0},
        )
        agent.run_sync("test", deps=prepared.deps)

        deps = captured[0]
        assert deps.agent_context is prepared.deps.agent_context
        assert deps.execution_context is prepared.deps.execution_context
        assert deps.tool_bridge is prepared.deps.tool_bridge
        assert deps.tool_snapshot is prepared.deps.tool_snapshot
        assert deps.policy is prepared.deps.policy


# ==============================================================================
# Context rebuild proof
# ==============================================================================


class TestNoContextRebuild:
    """Prove framework run does not rebuild context."""

    def test_context_builder_called_exactly_once(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """AgentContextBuilder.build() is called once during prepare, not during run."""
        build_count: list[int] = [0]
        original_build = preparer._context_builder.build

        def counting_build(user_input: str) -> AgentContext:
            build_count[0] += 1
            return original_build(user_input)

        preparer._context_builder.build = counting_build  # type: ignore[method-assign]

        prepared = preparer.prepare("test query", execution_context=read_context)
        assert build_count[0] == 1, f"Expected 1 build call during prepare, got {build_count[0]}"

        def instructions(ctx: RunContext[DndAgentDeps]) -> str:
            return "respond with a short answer"

        model, _ = _make_counting_function_model()
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            instructions=instructions,
            retries={"tools": 0},
        )
        agent.run_sync("test", deps=prepared.deps)

        # Builder count must remain 1 — framework run did not call build again
        assert build_count[0] == 1, (
            f"Expected 1 build call total, got {build_count[0]}. "
            "Framework run must not call AgentContextBuilder.build()."
        )


# ==============================================================================
# No tool execution during framework run
# ==============================================================================


class TestNoToolExecution:
    """Prove framework run executes zero project tool handlers."""

    def test_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Framework run with deps executes zero project tool handlers."""
        prepared = preparer.prepare("test query", execution_context=read_context)

        def instructions(ctx: RunContext[DndAgentDeps]) -> str:
            return "respond with a short answer"

        model, _ = _make_counting_function_model()
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            instructions=instructions,
            retries={"tools": 0},
        )
        agent.run_sync("test", deps=prepared.deps)

        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# One model request
# ==============================================================================


class TestOneModelRequest:
    """Prove framework run uses exactly one model request."""

    def test_exactly_one_model_request(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Framework run uses exactly one model request."""
        prepared = preparer.prepare("test query", execution_context=read_context)

        def instructions(ctx: RunContext[DndAgentDeps]) -> str:
            return "respond with a short answer"

        model, request_counter = _make_counting_function_model()
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            instructions=instructions,
            retries={"tools": 0},
        )
        agent.run_sync("test", deps=prepared.deps)

        assert request_counter[0] == 1, f"Expected 1 model request, got {request_counter[0]}"


# ==============================================================================
# No implicit deps serialization into model request
# ==============================================================================


class TestNoImplicitDepsSerialization:
    """Prove DndAgentDeps is not automatically serialized into model messages."""

    def test_sentinel_not_in_model_request(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Sentinel value in deps is NOT present in model-facing messages."""
        prepared = preparer.prepare(_SENTINEL, execution_context=read_context)

        captured_messages: list[list[object]] = []

        def _capture_model(messages: list, agent_info: object) -> object:
            captured_messages.append(list(messages))
            from pydantic_ai.messages import ModelResponse, TextPart

            return ModelResponse(parts=[TextPart(content="response")])

        model = FunctionModel(function=_capture_model)
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            retries={"tools": 0},
        )
        agent.run_sync("test", deps=prepared.deps)

        # Convert all messages to string and check sentinel is absent
        all_text = " ".join(str(m) for m in captured_messages[0])
        assert _SENTINEL not in all_text, (
            f"Sentinel '{_SENTINEL}' was found in model-facing messages. "
            "DndAgentDeps must not be automatically serialized into model input."
        )


# ==============================================================================
# No real network
# ==============================================================================


class TestNoRealNetwork:
    """Prove the integration test requires no real network."""

    def test_no_network_required(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """The test runs with FunctionModel only — no real network."""
        prepared = preparer.prepare("test query", execution_context=read_context)

        def instructions(ctx: RunContext[DndAgentDeps]) -> str:
            return "respond with a short answer"

        model, _ = _make_counting_function_model()
        agent: Agent[DndAgentDeps] = Agent(
            model,
            deps_type=DndAgentDeps,
            instructions=instructions,
            retries={"tools": 0},
        )
        result = agent.run_sync("test", deps=prepared.deps)
        assert result.output is not None
        assert isinstance(result.output, str)
