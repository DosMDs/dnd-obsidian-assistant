"""PAIM-07: Pydantic AI one-step FastAgent decision boundary — error/boundary tests.

All tests use ``FunctionModel`` for deterministic model responses and require
no real Ollama or network access.

This file covers boundary/error-path scenarios (P7-11 through P7-25).

Normal-path scenarios (P7-01 through P7-10) live in
``test_pydantic_ai_fast_agent.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

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
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolCall,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
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

# ==============================================================================
# Helpers
# ==============================================================================


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
def write_context_no_audit() -> ExecutionContext:
    return _make_context(
        permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
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
    """Create a ``PydanticAIFastAgent`` with the given model and preparer."""
    return PydanticAIFastAgent(
        run_preparer=preparer,
        model=model,
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


class TestP7_11UnknownTool:
    """P7-11: unknown tool raises ModelError, 1 request, 0 handlers."""

    def test_unknown_tool_raises_model_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Unknown tool name raises ModelError."""

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

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert req_counter[0] == 1

    def test_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Unknown tool causes zero handler calls."""

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

        model, _ = _make_function_model(_unknown_tool_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# P7-12 — Hidden live-registry tool
# ==============================================================================


class TestP7_12HiddenTool:
    """P7-12: hidden live-registry tool raises ModelError, 1 request, 0 handlers."""

    def test_hidden_tool_raises_model_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """A tool registered in the registry but hidden by READ authority."""

        def _hidden_tool_response(
            messages: list, info: object, counter: list[int]
        ) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_alpha",
                        args={"value": "x"},
                        tool_call_id="call_w",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_hidden_tool_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert req_counter[0] == 1

    def test_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Hidden tool causes zero handler calls."""

        def _hidden_tool_response(
            messages: list, info: object, counter: list[int]
        ) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_alpha",
                        args={"value": "x"},
                        tool_call_id="call_w",
                    ),
                ]
            )

        model, _ = _make_function_model(_hidden_tool_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert counters.write_alpha == 0


# ==============================================================================
# P7-13 — Duplicate explicit call ID
# ==============================================================================


class TestP7_13DuplicateCallId:
    """P7-13: duplicate explicit call ID raises ModelError, 1 request, 0 handlers."""

    def test_duplicate_call_id_raises_model_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Duplicate non-null tool_call_id raises ModelError."""

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

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert req_counter[0] == 1

    def test_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Duplicate call ID causes zero handler calls."""

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

        model, _ = _make_function_model(_dup_id_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# P7-14 — Schema-invalid but structurally valid dict args
# ==============================================================================


class TestP7_14SchemaInvalidDictArgs:
    """P7-14: schema-invalid dict args still produce a successful first decision."""

    def test_schema_invalid_dict_args_succeed(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Schema-invalid (missing required field) but structurally valid dict args."""

        def _tool_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_tool_response)
        agent = _make_pyd_agent(model, preparer)
        decision = agent.decide("test", execution_context=read_context)

        assert len(decision.response.message.tool_calls) == 1
        assert decision.response.message.tool_calls[0].arguments == {}
        assert req_counter[0] == 1

    def test_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Schema-invalid dict args cause zero handler calls."""

        def _tool_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, _ = _make_function_model(_tool_response)
        agent = _make_pyd_agent(model, preparer)
        agent.decide("test", execution_context=read_context)

        assert counters.alpha == 0


# ==============================================================================
# P7-15 — Malformed/non-object args
# ==============================================================================


class TestP7_15MalformedNonObjectArgs:
    """P7-15: malformed/non-object args raise ModelError, no retry."""

    def test_malformed_args_raises_model_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Malformed (non-object string) args raise ModelError."""

        def _malformed_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args="not-a-dict",
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_malformed_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert req_counter[0] == 1

    def test_zero_handler_calls_malformed(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Malformed args cause zero handler calls."""

        def _malformed_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args="not-a-dict",
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, _ = _make_function_model(_malformed_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert counters.alpha == 0


# ==============================================================================
# P7-16 — Non-finite JSON value
# ==============================================================================


class TestP7_16NonFiniteJsonValue:
    """P7-16: non-finite JSON value raises ModelError."""

    def test_nan_value_raises_model_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """NaN value in arguments raises ModelError."""

        def _nan_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": float("nan")},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_nan_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert req_counter[0] == 1

    def test_inf_value_raises_model_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Infinity value in arguments raises ModelError."""

        def _inf_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": float("inf")},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, req_counter = _make_function_model(_inf_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ModelError):
            agent.decide("test", execution_context=read_context)

        assert req_counter[0] == 1


# ==============================================================================
# P7-17 — Context/user validation failure
# ==============================================================================


class TestP7_17ContextValidationFailure:
    """P7-17: context/user validation failure raises project error, 0 model requests."""

    def test_empty_user_input_raises_validation_error(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Empty user input raises ValidationError before model request."""

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="ok")])

        model, req_counter = _make_function_model(_text_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ValidationError, match="user_input must not be empty"):
            agent.decide("", execution_context=read_context)

        assert req_counter[0] == 0

    def test_malformed_execution_context_raises_validation_error(
        self, preparer: DndAgentRunPreparer
    ) -> None:
        """Malformed ExecutionContext raises ValidationError before model request."""

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="ok")])

        model, req_counter = _make_function_model(_text_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ValidationError, match="execution_context must be an ExecutionContext"):
            agent.decide("test", execution_context=object())  # type: ignore[arg-type]

        assert req_counter[0] == 0


# ==============================================================================
# P7-18 — Malformed ExecutionContext (PAIM-C10 correction)
# ==============================================================================


class TestP7_18MalformedExecutionContext:
    """P7-18: malformed ExecutionContext raises ValidationError, 0 requests."""

    def test_malformed_ec_raises_validation_error(self, preparer: DndAgentRunPreparer) -> None:
        """Malformed ExecutionContext raises ValidationError, not TypeError."""

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="ok")])

        model, req_counter = _make_function_model(_text_response)
        agent = _make_pyd_agent(model, preparer)

        with pytest.raises(ValidationError, match="execution_context must be an ExecutionContext"):
            agent.decide("test", execution_context="not_an_ec")  # type: ignore[arg-type]

        assert req_counter[0] == 0


# ==============================================================================
# P7-19 — Policy untouched
# ==============================================================================


class TestP7_19PolicyUntouched:
    """P7-19: PAIM-07 does not consume DndAgentPolicy batch opportunity."""

    def test_policy_batch_still_admissible_after_decision(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """After decide(), policy.admit_tool_batch() still succeeds."""
        from pydantic_ai.messages import ToolCallPart as TCP

        captured: list[object] = []
        original_prepare = preparer.prepare

        def spy_prepare(user_input: str, *, execution_context: object) -> object:
            result = original_prepare(user_input, execution_context=execution_context)
            captured.append(result)
            return result

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        def _tool_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "x"},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, _ = _make_function_model(_tool_response)
        agent = _make_pyd_agent(model, preparer)
        agent.decide("test", execution_context=read_context)

        assert len(captured) == 1
        prepared_run = captured[0]

        call = TCP(
            tool_name="read_alpha",
            args={"value": "y"},
            tool_call_id="call_2",
        )
        admission = prepared_run.deps.policy.admit_tool_batch([call])  # type: ignore[union-attr]

        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_alpha"


# ==============================================================================
# P7-20 — Two-run exposure isolation
# ==============================================================================


class TestP7_20TwoRunIsolation:
    """P7-20: two runs have isolated tool exposure/state."""

    def test_two_runs_isolated_exposure(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        write_context: ExecutionContext,
    ) -> None:
        """Run A (READ) and run B (WRITE+audit) have different exposures."""

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="ok")])

        model, _ = _make_function_model(_text_response)
        agent = _make_pyd_agent(model, preparer)

        decision_a = agent.decide("test", execution_context=read_context)
        names_a = [t.name for t in decision_a.exposed_tools]
        assert "write_alpha" not in names_a

        decision_b = agent.decide("test", execution_context=write_context)
        names_b = [t.name for t in decision_b.exposed_tools]
        assert "write_alpha" in names_b

    def test_no_toolset_leakage(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Two runs with same instance do not leak toolset state."""

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="ok")])

        model, _ = _make_function_model(_text_response)
        agent = _make_pyd_agent(model, preparer)

        decision_a = agent.decide("query a", execution_context=read_context)
        decision_b = agent.decide("query b", execution_context=read_context)

        assert decision_a.prompt_version == decision_b.prompt_version
        assert len(decision_a.exposed_tools) == len(decision_b.exposed_tools)


# ==============================================================================

# P7-24 — Reference text parity
# ==============================================================================


class TestP7_24ReferenceTextParity:
    """P7-24: old/new observable DTO parity for text-only response."""

    def test_text_parity_with_fast_agent(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Compare AgentDecision DTOs between old FastAgent and PydanticAIFastAgent."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.models.gateway import ModelGateway
        from dnd_assistant.models.types import ToolAwareResponse as TAR

        class _FakeGateway(ModelGateway):
            def __init__(self) -> None:
                self.call_count = 0

            def chat_with_tools(
                self,
                request: ChatRequest,
                tools: list[ToolPublicDefinition],
            ) -> TAR:
                self.call_count += 1
                return TAR(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content="Hello from FastAgent",
                    ),
                )

        gateway = _FakeGateway()
        old_agent = FastAgent(
            context_builder=preparer._context_builder,
            model_gateway=gateway,
            tool_catalog=preparer._tool_catalog,
        )

        def _text_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="Hello from FastAgent")])

        model, _ = _make_function_model(_text_response)
        new_agent = _make_pyd_agent(model, preparer)

        old_decision = old_agent.decide("hello", execution_context=read_context)
        new_decision = new_agent.decide("hello", execution_context=read_context)

        assert old_decision.prompt_version == new_decision.prompt_version
        assert old_decision.request.model_dump() == new_decision.request.model_dump()
        assert old_decision.response.message.content == new_decision.response.message.content
        assert old_decision.response.message.tool_calls == new_decision.response.message.tool_calls
        assert len(old_decision.exposed_tools) == len(new_decision.exposed_tools)
        assert [t.name for t in old_decision.exposed_tools] == [
            t.name for t in new_decision.exposed_tools
        ]


# ==============================================================================
# P7-25 — Reference tool parity
# ==============================================================================


class TestP7_25ReferenceToolParity:
    """P7-25: old/new observable DTO parity for tool-only response."""

    def test_tool_parity_with_fast_agent(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Compare AgentDecision DTOs between old FastAgent and PydanticAIFastAgent."""
        from dnd_assistant.application.fast_agent import FastAgent
        from dnd_assistant.models.gateway import ModelGateway
        from dnd_assistant.models.types import ToolAwareResponse as TAR

        tool_call = ToolCall(
            name="read_alpha",
            arguments={"value": "gandalf"},
            call_id="call_1",
        )

        class _FakeGateway(ModelGateway):
            def __init__(self) -> None:
                self.call_count = 0

            def chat_with_tools(
                self,
                request: ChatRequest,
                tools: list[ToolPublicDefinition],
            ) -> TAR:
                self.call_count += 1
                return TAR(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        tool_calls=(tool_call,),
                    ),
                )

        gateway = _FakeGateway()
        old_agent = FastAgent(
            context_builder=preparer._context_builder,
            model_gateway=gateway,
            tool_catalog=preparer._tool_catalog,
        )

        def _tool_response(messages: list, info: object, counter: list[int]) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "gandalf"},
                        tool_call_id="call_1",
                    ),
                ]
            )

        model, _ = _make_function_model(_tool_response)
        new_agent = _make_pyd_agent(model, preparer)

        old_decision = old_agent.decide("hello", execution_context=read_context)
        new_decision = new_agent.decide("hello", execution_context=read_context)

        assert old_decision.prompt_version == new_decision.prompt_version
        assert old_decision.request.model_dump() == new_decision.request.model_dump()
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
        assert len(old_decision.exposed_tools) == len(new_decision.exposed_tools)
        assert [t.name for t in old_decision.exposed_tools] == [
            t.name for t in new_decision.exposed_tools
        ]


# ==============================================================================
# Constructor validation
# ==============================================================================


class TestConstructorValidation:
    """Constructor validation for PydanticAIFastAgent."""

    def test_malformed_run_preparer_raises_type_error(self, read_context: ExecutionContext) -> None:
        """Malformed run_preparer raises TypeError."""
        with pytest.raises(TypeError, match="run_preparer"):
            PydanticAIFastAgent(
                run_preparer=object(),  # type: ignore[arg-type]
                model=FunctionModel(
                    function=lambda m, i: ModelResponse(parts=[TextPart(content="ok")]),
                ),
            )

    def test_malformed_model_raises_type_error(self, preparer: DndAgentRunPreparer) -> None:
        """Malformed model raises TypeError."""
        with pytest.raises(TypeError, match="model"):
            PydanticAIFastAgent(
                run_preparer=preparer,
                model=object(),  # type: ignore[arg-type]
            )


# ==============================================================================
# Import boundary — fresh process
# ==============================================================================


class TestImportBoundary:
    """Fresh-process import boundary for pydantic_ai_fast_agent."""

    def test_fresh_import_does_not_load_forbidden_modules(self) -> None:
        """A fresh import must not eagerly load storage/retrieval/cli/executor."""
        import subprocess
        import sys

        code = """
import sys
import dnd_assistant.application.pydantic_ai_fast_agent

forbidden = [
    'dnd_assistant.models.ollama',
    'dnd_assistant.storage',
    'dnd_assistant.retrieval',
    'dnd_assistant.cli',
    'dnd_assistant.tools.executor',
]
loaded = [m for m in forbidden if m in sys.modules]
if loaded:
    print('FAIL:' + ','.join(loaded))
    sys.exit(1)

print('PASS')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Import isolation failed: stdout={result.stdout}, stderr={result.stderr}"
        )
        assert "PASS" in result.stdout
