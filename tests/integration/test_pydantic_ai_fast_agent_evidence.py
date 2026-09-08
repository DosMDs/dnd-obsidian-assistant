"""PAIM-C13: Close PAIM-07 runtime evidence gaps.

This file provides executable evidence for framework-visible tool exposure,
output-tool configuration, two-run isolation, snapshot/policy isolation,
reference parity, error cause mapping, TextPart concatenation, and
ThinkingPart hiding.

All tests use ``FunctionModel`` for deterministic model responses and require
no real Ollama or network access.

Architecture preserved (PAIM-07 contract):
- fresh ExternalToolset per decide()
- zero project tool execution
- zero policy admission
- zero second model request
- no HandleDeferredToolCalls
- no ToolExecutor
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.pydantic_ai_fast_agent import (
    PydanticAIFastAgent,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import ModelError
from dnd_assistant.models.types import ChatMessage, ChatRequest, MessageRole
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode
from tests.support.pydantic_ai_runtime import HandlerCounters, make_tool_registry

# ==============================================================================
# Helpers
# ==============================================================================


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


def _make_function_model(
    response_fn: object,
) -> tuple[FunctionModel, list[int]]:
    """Create a FunctionModel with a request counter.

    Returns:
        (model, request_counter) where request_counter[0] tracks model requests.
    """
    request_counter: list[int] = [0]

    def _respond(messages: list, agent_info: object) -> ModelResponse:
        request_counter[0] += 1
        return response_fn(messages, agent_info, request_counter)

    model = FunctionModel(function=_respond)
    return model, request_counter


def _assert_zero_handlers(counters: HandlerCounters) -> None:
    """Assert no project tool handlers have been called."""
    assert counters.alpha == 0
    assert counters.beta == 0
    assert counters.write_alpha == 0


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def counters() -> HandlerCounters:
    return HandlerCounters()


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
    return _make_context(permission=Permission.READ)


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


def _make_pyd_agent(
    model: FunctionModel,
    preparer: DndAgentRunPreparer,
) -> PydanticAIFastAgent:
    return PydanticAIFastAgent(
        run_preparer=preparer,
        model=model,
    )


# ==============================================================================
# C13-E01 — exact framework-visible tool order
# ==============================================================================


class TestC13E01ExactFrameworkVisibleToolOrder:
    """C13-E01: capture AgentInfo.function_tools and verify exact order."""

    def test_function_tools_order_matches_snapshot(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """AgentInfo.function_tools order matches snapshot names and decision exposure."""
        captured_agent_info: list[AgentInfo] = []
        captured_runs: list[object] = []

        original_prepare = preparer.prepare

        def spy_prepare(user_input: str, *, execution_context: object) -> object:
            result = original_prepare(user_input, execution_context=execution_context)
            captured_runs.append(result)
            return result

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        def _capture_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            assert isinstance(info, AgentInfo)
            captured_agent_info.append(info)
            return ModelResponse(parts=[TextPart(content="ok")])

        model, req_counter = _make_function_model(_capture_response)
        agent = _make_pyd_agent(model, preparer)
        decision = agent.decide("test", execution_context=read_context)

        assert len(captured_agent_info) == 1
        assert len(captured_runs) == 1
        agent_info = captured_agent_info[0]
        prepared = captured_runs[0]

        # Snapshot names from the exact captured PreparedDndAgentRun
        snapshot_names = prepared.deps.tool_snapshot.names

        # Framework-visible tool names
        framework_names = tuple(t.name for t in agent_info.function_tools)

        # Decision exposure names
        decision_names = tuple(t.name for t in decision.exposed_tools)

        # Three-way exact parity
        assert framework_names == snapshot_names
        assert framework_names == decision_names

        # Also prove identities for the same run
        assert prepared.exposed_tools == decision.exposed_tools

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E02 — no synthetic output tools
# ==============================================================================


class TestC13E02NoSyntheticOutputTools:
    """C13-E02: no synthetic output tools, plain text output only."""

    def test_no_output_tools_and_allow_text_output(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """AgentInfo has no output_tools and allow_text_output is True."""
        captured_agent_info: list[AgentInfo] = []

        def _capture_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            assert isinstance(info, AgentInfo)
            captured_agent_info.append(info)
            return ModelResponse(parts=[TextPart(content="ok")])

        model, req_counter = _make_function_model(_capture_response)
        agent = _make_pyd_agent(model, preparer)
        agent.decide("test", execution_context=read_context)

        assert len(captured_agent_info) == 1
        agent_info = captured_agent_info[0]

        # No synthetic output tools
        assert agent_info.output_tools == []

        # Plain text output is allowed (str | DeferredToolRequests)
        assert agent_info.allow_text_output is True

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E03 — model-visible two-run exposure isolation
# ==============================================================================


class TestC13E03TwoRunExposureIsolation:
    """C13-E03: two repeated decide() calls with different authorities."""

    def test_two_run_model_visible_exposure_isolation(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        write_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Run A (READ) and run B (WRITE+audit) have different model-visible tools.

        Uses one PydanticAIFastAgent instance and one FunctionModel for both
        decide() calls. Captures preparer spy for exact snapshot parity.
        """
        captured_infos: list[AgentInfo] = []
        captured_runs: list[object] = []

        original_prepare = preparer.prepare

        def spy_prepare(user_input: str, *, execution_context: object) -> object:
            result = original_prepare(user_input, execution_context=execution_context)
            captured_runs.append(result)
            return result

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        def _capture_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            assert isinstance(info, AgentInfo)
            captured_infos.append(info)
            return ModelResponse(parts=[TextPart(content="ok")])

        # One FunctionModel, one PydanticAIFastAgent
        model, req_counter = _make_function_model(_capture_response)
        agent = _make_pyd_agent(model, preparer)

        # Run A: READ authority
        decision_a = agent.decide("test a", execution_context=read_context)

        # Run B: WRITE + audit authority
        decision_b = agent.decide("test b", execution_context=write_context)

        # Total model requests == 2
        assert req_counter[0] == 2

        # Capture AgentInfo for both runs
        assert len(captured_infos) == 2
        assert len(captured_runs) == 2
        info_a = captured_infos[0]
        info_b = captured_infos[1]
        prepared_a = captured_runs[0]
        prepared_b = captured_runs[1]

        # Run A model-visible tools: read_alpha, read_beta
        names_a = tuple(t.name for t in info_a.function_tools)
        assert names_a == ("read_alpha", "read_beta")

        # Run B model-visible tools: read_alpha, read_beta, write_alpha
        names_b = tuple(t.name for t in info_b.function_tools)
        assert names_b == ("read_alpha", "read_beta", "write_alpha")

        # Run A data unchanged after run B (immutable copy captured before run B)
        assert names_a == ("read_alpha", "read_beta")

        # Decision exposure matches
        assert tuple(t.name for t in decision_a.exposed_tools) == names_a
        assert tuple(t.name for t in decision_b.exposed_tools) == names_b

        # Exact snapshot parity for both runs
        assert names_a == prepared_a.deps.tool_snapshot.names
        assert names_b == prepared_b.deps.tool_snapshot.names

        # Exposed tools identity for same run
        assert prepared_a.exposed_tools == decision_a.exposed_tools
        assert prepared_b.exposed_tools == decision_b.exposed_tools

        # 0 handlers
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E04 — snapshot/policy run isolation
# ==============================================================================


class TestC13E04SnapshotPolicyRunIsolation:
    """C13-E04: snapshot and policy identity isolation across runs."""

    def test_snapshot_and_policy_identity_isolation(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        write_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Each decide() produces distinct deps, snapshots, and policies."""
        from pydantic_ai.messages import ToolCallPart as TCP

        captured: list[object] = []
        original_prepare = preparer.prepare

        def spy_prepare(user_input: str, *, execution_context: object) -> object:
            result = original_prepare(user_input, execution_context=execution_context)
            captured.append(result)
            return result

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="ok")])

        model, req_counter = _make_function_model(_text_response)
        agent = _make_pyd_agent(model, preparer)

        # Run A
        agent.decide("test a", execution_context=read_context)
        # Run B
        agent.decide("test b", execution_context=write_context)

        assert len(captured) == 2
        run_a = captured[0]
        run_b = captured[1]

        # Distinct deps identity
        assert run_a.deps is not run_b.deps

        # Distinct snapshot identity
        assert run_a.deps.tool_snapshot is not run_b.deps.tool_snapshot

        # Distinct policy identity
        assert run_a.deps.policy is not run_b.deps.policy

        # Run B's policy still has its first batch opportunity
        call = TCP(
            tool_name="read_alpha",
            args={"value": "y"},
            tool_call_id="call_2",
        )
        admission = run_b.deps.policy.admit_tool_batch([call])
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_alpha"

        # 2 requests, 0 handlers
        assert req_counter[0] == 2
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E05 — reference parity: text + tool
# ==============================================================================


class TestC13E05ReferenceParityTextAndTool:
    """C13-E05: old/new parity for text + tool response."""

    def test_text_and_tool_parity(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Compare AgentDecision DTOs between old FastAgent and PydanticAIFastAgent."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.models.gateway import ModelGateway
        from dnd_assistant.models.types import ToolAwareResponse as TAR
        from dnd_assistant.models.types import ToolCall as TC

        class _FakeGateway(ModelGateway):
            def chat_with_tools(
                self,
                request: ChatRequest,
                tools: list[ToolPublicDefinition],
            ) -> TAR:
                return TAR(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content="Looking up Gandalf...",
                        tool_calls=(
                            TC(
                                name="read_alpha",
                                arguments={"value": "gandalf"},
                                call_id="call_1",
                            ),
                        ),
                    ),
                )

        gateway = _FakeGateway()
        old_agent = FastAgent(
            context_builder=preparer._context_builder,
            model_gateway=gateway,
            tool_catalog=preparer._tool_catalog,
        )

        def _mixed_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    TextPart(content="Looking up Gandalf..."),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "gandalf"},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_mixed_response)
        new_agent = _make_pyd_agent(model, preparer)

        old_decision = old_agent.decide("hello", execution_context=read_context)
        new_decision = new_agent.decide("hello", execution_context=read_context)

        # Compare prompt version
        assert old_decision.prompt_version == new_decision.prompt_version

        # Compare request
        assert old_decision.request.model_dump() == new_decision.request.model_dump()

        # Compare exposed tool names
        assert [t.name for t in old_decision.exposed_tools] == [
            t.name for t in new_decision.exposed_tools
        ]

        # Compare response content
        assert old_decision.response.message.content == new_decision.response.message.content

        # Compare tool calls
        assert len(old_decision.response.message.tool_calls) == len(
            new_decision.response.message.tool_calls
        )
        assert (
            old_decision.response.message.tool_calls[0].name
            == new_decision.response.message.tool_calls[0].name
        )
        assert (
            old_decision.response.message.tool_calls[0].arguments
            == new_decision.response.message.tool_calls[0].arguments
        )

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E06 — reference parity: multi READ
# ==============================================================================


class TestC13E06ReferenceParityMultiRead:
    """C13-E06: old/new parity for multi-READ response."""

    def test_multi_read_parity(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Compare AgentDecision DTOs for multi-READ between old and new."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.models.gateway import ModelGateway
        from dnd_assistant.models.types import ToolAwareResponse as TAR
        from dnd_assistant.models.types import ToolCall as TC

        class _FakeGateway(ModelGateway):
            def chat_with_tools(
                self,
                request: ChatRequest,
                tools: list[ToolPublicDefinition],
            ) -> TAR:
                return TAR(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        tool_calls=(
                            TC(
                                name="read_alpha",
                                arguments={"value": "first"},
                                call_id="call_a",
                            ),
                            TC(
                                name="read_beta",
                                arguments={"number": 42},
                                call_id="call_b",
                            ),
                        ),
                    ),
                )

        gateway = _FakeGateway()
        old_agent = FastAgent(
            context_builder=preparer._context_builder,
            model_gateway=gateway,
            tool_catalog=preparer._tool_catalog,
        )

        def _two_tool_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "first"},
                        tool_call_id="call_a",
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"number": 42},
                        tool_call_id="call_b",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_two_tool_response)
        new_agent = _make_pyd_agent(model, preparer)

        old_decision = old_agent.decide("read both", execution_context=read_context)
        new_decision = new_agent.decide("read both", execution_context=read_context)

        # Compare prompt version
        assert old_decision.prompt_version == new_decision.prompt_version

        # Compare request
        assert old_decision.request.model_dump() == new_decision.request.model_dump()

        # Compare exposed tool names
        assert [t.name for t in old_decision.exposed_tools] == [
            t.name for t in new_decision.exposed_tools
        ]

        # Compare tool-call count
        assert len(old_decision.response.message.tool_calls) == len(
            new_decision.response.message.tool_calls
        )
        assert len(new_decision.response.message.tool_calls) == 2

        # Compare each tool call
        for i in range(2):
            assert (
                old_decision.response.message.tool_calls[i].name
                == new_decision.response.message.tool_calls[i].name
            )
            assert (
                old_decision.response.message.tool_calls[i].arguments
                == new_decision.response.message.tool_calls[i].arguments
            )
            assert (
                old_decision.response.message.tool_calls[i].call_id
                == new_decision.response.message.tool_calls[i].call_id
            )

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E07 — exact unknown-tool cause mapping
# ==============================================================================


class TestC13E07UnknownToolCauseMapping:
    """C13-E07: unknown tool raises ModelError with exact framework cause."""

    def test_unknown_tool_model_error_with_cause(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Unknown tool produces ModelError with UnexpectedModelBehavior as exact cause."""

        def _unknown_tool_response(
            messages: list, info: object, counter: list[int]
        ) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="nonexistent_tool",
                        args={},
                        tool_call_id="call_x",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_unknown_tool_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError) as exc_info:
            agent.decide("test", execution_context=read_context)

        exc = exc_info.value

        # Project error type
        assert isinstance(exc, ModelError)

        # Exact public framework cause subtype
        assert exc.__cause__ is not None
        assert type(exc.__cause__) is UnexpectedModelBehavior

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E08 — duplicate-ID cause mapping
# ==============================================================================


class TestC13E08DuplicateIdCauseMapping:
    """C13-E08: duplicate tool_call_id raises ModelError with exact framework cause."""

    def test_duplicate_id_model_error_with_cause(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Duplicate non-null tool_call_id produces ModelError with UnexpectedModelBehavior as exact cause."""

        def _dup_id_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "a"},
                        tool_call_id="dup",
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"number": 1},
                        tool_call_id="dup",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_dup_id_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError) as exc_info:
            agent.decide("test", execution_context=read_context)

        exc = exc_info.value

        # Project error type
        assert isinstance(exc, ModelError)

        # Exact public framework cause subtype
        assert exc.__cause__ is not None
        assert type(exc.__cause__) is UnexpectedModelBehavior

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E09 — deterministic framework AgentRunError mapping
# ==============================================================================


class TestC13E09FrameworkRunErrorMapping:
    """C13-E09: framework AgentRunError maps to ModelError with cause."""

    def test_model_api_error_maps_to_model_error(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """A ModelAPIError from the model maps to ModelError with cause."""
        from pydantic_ai.models.function import FunctionModel as FM

        call_count: list[int] = [0]

        def _failing_function(messages: list, agent_info: object) -> ModelResponse:
            call_count[0] += 1
            raise ModelAPIError("test_model", "Simulated model failure")

        failing_model = FM(function=_failing_function)
        agent = _make_pyd_agent(failing_model, preparer)

        with pytest.raises(ModelError) as exc_info:
            agent.decide("test", execution_context=read_context)

        exc = exc_info.value

        # Project error type
        assert isinstance(exc, ModelError)

        # Framework cause retained
        assert exc.__cause__ is not None
        assert isinstance(exc.__cause__, ModelAPIError)
        assert "Simulated model failure" in str(exc.__cause__)

        # 1 request where a request actually began, 0 handlers
        assert call_count[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E10 — multiple TextPart concatenation rule
# ==============================================================================


class TestC13E10MultipleTextPartConcatenation:
    """C13-E10: multiple TextParts concatenated with space, tool calls preserved."""

    def test_multiple_text_parts_concatenated(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Multiple TextParts + ToolCallPart produce joined text + tool call."""

        def _multi_text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    TextPart(content="first"),
                    TextPart(content="second"),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "test"},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_multi_text_response)
        agent = _make_pyd_agent(model, preparer)
        decision = agent.decide("test", execution_context=read_context)

        # Text parts concatenated with space
        assert decision.response.message.content == "first second"

        # Tool call preserved
        assert len(decision.response.message.tool_calls) == 1
        assert decision.response.message.tool_calls[0].name == "read_alpha"
        assert decision.response.message.tool_calls[0].arguments == {"value": "test"}

        # Order preserved
        assert decision.response.message.tool_calls[0].call_id == "call_1"

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)


# ==============================================================================
# C13-E11 — ThinkingPart remains hidden
# ==============================================================================


class TestC13E11ThinkingPartRemainsHidden:
    """C13-E11: ThinkingPart content does not appear in assistant response."""

    def test_thinking_part_not_surfaced(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """ThinkingPart before TextPart + ToolCallPart is not surfaced."""

        def _thinking_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ThinkingPart(content="I should look up Gandalf..."),
                    TextPart(content="visible"),
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "gandalf"},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_thinking_response)
        agent = _make_pyd_agent(model, preparer)
        decision = agent.decide("who is Gandalf?", execution_context=read_context)

        # Only TextPart content is surfaced, not ThinkingPart
        assert decision.response.message.content == "visible"

        # Tool call preserved
        assert len(decision.response.message.tool_calls) == 1
        assert decision.response.message.tool_calls[0].name == "read_alpha"

        # 1 request, 0 handlers
        assert req_counter[0] == 1
        _assert_zero_handlers(counters)
