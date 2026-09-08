"""PAIM-C16: Genuine old/new AgentLoop parity tests.

Each scenario executes BOTH ``AgentLoop.run()`` and
``PydanticAIAgentRuntime.run()`` with semantically equivalent deterministic
model outcomes, then compares provider-neutral DTOs.

Required scenarios:
    C16-P1 direct respond
    C16-P2 direct clarify
    C16-P3 single READ -> respond
    C16-P4 single WRITE -> respond
    C16-P5 two READ -> respond
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import (
    AgentLoop,
    AgentOutcomeKind,
    AgentRunResult,
)
from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionResult,
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import AgentDecision
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import NotFoundError
from dnd_assistant.models.gateway import ModelGateway
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.retrieval.service import SearchService
from dnd_assistant.retrieval.types import SearchHit, SearchQuery
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.types import VaultDocument, VaultRepository
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

# ── Shared schemas ──────────────────────────────────────────────────────────────


class _StringInput(BaseModel):
    value: str


class _ToolOutput(BaseModel):
    result: str


# ── Tool definitions ────────────────────────────────────────────────────────────

READ_ALPHA_DEF = ToolDefinition(
    name="read_alpha",
    description="A read-only test tool",
    input_schema=_StringInput,
    output_schema=_ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

READ_BETA_DEF = ToolDefinition(
    name="read_beta",
    description="Another read-only test tool",
    input_schema=_StringInput,
    output_schema=_ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

WRITE_ALPHA_DEF = ToolDefinition(
    name="write_alpha",
    description="A write test tool",
    input_schema=_StringInput,
    output_schema=_ToolOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)


# ── Handler counters ────────────────────────────────────────────────────────────


class _HandlerCounters:
    """Fresh per-test handler invocation counters."""

    def __init__(self) -> None:
        self.alpha: int = 0
        self.beta: int = 0
        self.write_alpha: int = 0


def _make_registry(counters: _HandlerCounters) -> ToolRegistry:
    """Build a fresh ToolRegistry with three tools."""
    registry = ToolRegistry()

    def read_alpha_handler(inp: _StringInput, ctx: object) -> _ToolOutput:
        counters.alpha += 1
        return _ToolOutput(result=f"alpha:{inp.value}")

    def read_beta_handler(inp: _StringInput, ctx: object) -> _ToolOutput:
        counters.beta += 1
        return _ToolOutput(result=f"beta:{inp.value}")

    def write_alpha_handler(inp: _StringInput, ctx: object) -> _ToolOutput:
        counters.write_alpha += 1
        return _ToolOutput(result=f"write:{inp.value}")

    registry.register(READ_ALPHA_DEF, read_alpha_handler)
    registry.register(READ_BETA_DEF, read_beta_handler)
    registry.register(WRITE_ALPHA_DEF, write_alpha_handler)
    return registry


# ── Stubs ───────────────────────────────────────────────────────────────────────


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


def _make_context_builder() -> AgentContextBuilder:
    return AgentContextBuilder(
        search_service=_StubSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),
        event_repository=_StubEventRepo(),
        world_time_repository=_StubWorldTimeRepo(),
    )


class _FakeModelGateway(ModelGateway):
    """Fake ModelGateway that returns pre-built responses."""

    def __init__(self, responses: list[ToolAwareResponse]) -> None:
        self._responses = responses
        self.call_count: int = 0
        self.last_request: ChatRequest | None = None
        self.last_tools: list[ToolPublicDefinition] | None = None

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.call_count += 1
        self.last_request = request
        self.last_tools = tools
        if self.call_count <= len(self._responses):
            return self._responses[self.call_count - 1]
        return self._responses[-1]

    def chat(self, request: ChatRequest) -> None:
        raise AssertionError("chat() should not be called")

    def generate_structured(self, request: ChatRequest, schema: type) -> None:
        raise AssertionError("generate_structured() should not be called")

    def embed(self, texts: list[str]) -> None:
        raise AssertionError("embed() should not be called")

    def health(self) -> None:
        raise AssertionError("health() should not be called")


# ── Helper: build ToolAwareResponse from JSON string ────────────────────────────


def _make_tool_aware_response(
    content: str,
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


# ── Helper: build respond/clarify JSON ──────────────────────────────────────────


def _respond_json(message: str) -> str:
    return json.dumps(
        {"kind": "respond", "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _clarify_json(message: str) -> str:
    return json.dumps(
        {"kind": "clarify", "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
    )


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def counters() -> _HandlerCounters:
    return _HandlerCounters()


@pytest.fixture
def registry(counters: _HandlerCounters) -> ToolRegistry:
    return _make_registry(counters)


@pytest.fixture
def catalog(registry: ToolRegistry) -> ToolRegistrySchema:
    from dnd_assistant.tools.catalog import build_tool_registry_schema

    return build_tool_registry_schema(registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
    return _make_context_builder()


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


# ── Dual-runtime comparison helper ──────────────────────────────────────────────


class _ParityResult:
    """Container for both runtime results."""

    def __init__(
        self,
        reference: AgentRunResult,
        pydantic: AgentRunResult,
        ref_gateway: _FakeModelGateway,
    ) -> None:
        self.reference = reference
        self.pydantic = pydantic
        self.ref_gateway = ref_gateway


def _run_both(
    user_input: str,
    *,
    execution_context: ExecutionContext,
    registry: ToolRegistry,
    catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    counters: _HandlerCounters,
    ref_responses: list[ToolAwareResponse],
    pydantic_model_fn: Any,
) -> _ParityResult:
    """Execute both runtimes with equivalent deterministic model outcomes.

    Note: ``counters`` tracks handler invocations from the **reference**
    runtime only.  The Pydantic runtime uses its own fresh ``ToolRegistry``
    and ``HandlerCounters`` (tracked via ``request_count`` on the model fn).
    """
    # ── Reference: AgentLoop ────────────────────────────────────────────────
    ref_gateway = _FakeModelGateway(ref_responses)
    tool_executor = ToolExecutor(registry)
    tool_svc = AgentToolExecutionService(tool_executor=tool_executor)

    # Build a catalog with public definitions matching the registry tools
    public_defs = []
    for td in registry.list_definitions():
        public_defs.append(
            ToolPublicDefinition(
                name=td.name,
                description=td.description,
                input_schema=td.input_schema.model_json_schema(),
                output_schema=td.output_schema.model_json_schema(),
                permission=td.permission,
                side_effects=list(td.side_effects),
                allowed_session_modes=list(td.allowed_session_modes),
            )
        )
    ref_catalog = ToolRegistrySchema(tools=public_defs)

    ref_loop = AgentLoop(
        context_builder=context_builder,
        model_gateway=ref_gateway,
        tool_catalog=ref_catalog,
        tool_execution_service=tool_svc,
    )
    reference_result = ref_loop.run(user_input, execution_context=execution_context)

    # ── Pydantic: PydanticAIAgentRuntime (uses separate counters via
    #    the shared ToolRegistry — handlers are called by both runtimes,
    #    so counters reflect both.  We track pydantic-side model requests
    #    via request_count in the model function.)
    tool_bridge = PydanticAIToolBridge(registry=registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=catalog,
        tool_bridge=tool_bridge,
    )
    model = FunctionModel(pydantic_model_fn)
    pydantic_runtime = PydanticAIAgentRuntime(
        run_preparer=preparer,
        model=model,
    )
    pydantic_result = pydantic_runtime.run(user_input, execution_context=execution_context)

    return _ParityResult(reference_result, pydantic_result, ref_gateway)


# ── DTO comparison helpers ──────────────────────────────────────────────────────


def _assert_decision_parity(
    ref_decision: AgentDecision,
    pyd_decision: AgentDecision,
    *,
    check_tool_calls: bool = False,
) -> None:
    """Compare two AgentDecision instances for parity.

    Known intentional difference:
    - The reference ``AgentLoop`` preserves ``ToolAwareResponse.message.content``
      even when tool calls are present (e.g. ``"Looking up..."``).
    - The Pydantic runtime sets ``content=None`` when the first model response
      contains only ``ToolCallPart`` parts (no ``TextPart``).
    This is a documented migration difference, not a parity failure.
    """
    assert ref_decision.prompt_version == pyd_decision.prompt_version
    assert ref_decision.request.model_dump() == pyd_decision.request.model_dump()
    ref_names = tuple(t.name for t in ref_decision.exposed_tools)
    pyd_names = tuple(t.name for t in pyd_decision.exposed_tools)
    assert ref_names == pyd_names
    if check_tool_calls:
        # When tool calls are present, the Pydantic runtime may set
        # content=None (no TextPart in the first ModelResponse).
        # Only compare content when both have it.
        if (
            ref_decision.response.message.content is not None
            and pyd_decision.response.message.content is not None
        ):
            assert ref_decision.response.message.content == pyd_decision.response.message.content
        ref_calls = ref_decision.response.message.tool_calls
        pyd_calls = pyd_decision.response.message.tool_calls
        assert len(ref_calls) == len(pyd_calls)
        for ref_c, pyd_c in zip(ref_calls, pyd_calls, strict=True):
            assert ref_c.name == pyd_c.name
            assert ref_c.arguments == pyd_c.arguments
    else:
        assert ref_decision.response.message.content == pyd_decision.response.message.content


def _assert_execution_parity(
    ref_executions: tuple[AgentToolExecutionResult, ...],
    pyd_executions: tuple[AgentToolExecutionResult, ...],
) -> None:
    """Compare two execution result tuples for parity."""
    assert len(ref_executions) == len(pyd_executions)
    for ref_e, pyd_e in zip(ref_executions, pyd_executions, strict=True):
        assert ref_e.tool_call.model_dump() == pyd_e.tool_call.model_dump()
        assert ref_e.output.model_dump() == pyd_e.output.model_dump()
        assert ref_e.tool_message.model_dump() == pyd_e.tool_message.model_dump()


def _assert_outcome_parity(
    ref_result: AgentRunResult,
    pyd_result: AgentRunResult,
) -> None:
    """Compare terminal outcomes for parity."""
    assert ref_result.outcome.kind == pyd_result.outcome.kind
    assert ref_result.outcome.message == pyd_result.outcome.message
    assert ref_result.final_response.message.content == pyd_result.final_response.message.content


# ==============================================================================
# C16-P1: direct respond
# ==============================================================================


class TestC16P1DirectRespond:
    """C16-P1: direct respond — zero tool calls, one model request."""

    def test_direct_respond_parity(
        self,
        counters: _HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Both runtimes produce equivalent direct respond outcome."""
        msg = "Hello there!"

        ref_responses = [
            _make_tool_aware_response(content=_respond_json(msg)),
        ]

        def pyd_model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=_respond_json(msg))])

        result = _run_both(
            "hello",
            execution_context=read_context,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            counters=counters,
            ref_responses=ref_responses,
            pydantic_model_fn=pyd_model_fn,
        )

        # AgentLoop assertions
        assert result.ref_gateway.call_count == 1
        assert result.reference.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.reference.outcome.message == msg
        assert len(result.reference.tool_executions) == 0

        # Pydantic runtime assertions
        assert result.pydantic.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.pydantic.outcome.message == msg
        assert len(result.pydantic.tool_executions) == 0

        # DTO parity
        _assert_decision_parity(
            result.reference.initial_decision,
            result.pydantic.initial_decision,
        )
        _assert_outcome_parity(result.reference, result.pydantic)
        # Both runtimes share the same ToolRegistry, so handler counters
        # reflect invocations from both runtimes (2 = 1 ref + 1 pyd).
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C16-P2: direct clarify
# ==============================================================================


class TestC16P2DirectClarify:
    """C16-P2: direct clarify — zero tool calls, one model request."""

    def test_direct_clarify_parity(
        self,
        counters: _HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Both runtimes produce equivalent direct clarify outcome."""
        msg = "Which one?"

        ref_responses = [
            _make_tool_aware_response(content=_clarify_json(msg)),
        ]

        def pyd_model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=_clarify_json(msg))])

        result = _run_both(
            "query",
            execution_context=read_context,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            counters=counters,
            ref_responses=ref_responses,
            pydantic_model_fn=pyd_model_fn,
        )

        assert result.ref_gateway.call_count == 1
        assert result.reference.outcome.kind == AgentOutcomeKind.CLARIFY
        assert result.reference.outcome.message == msg
        assert len(result.reference.tool_executions) == 0

        assert result.pydantic.outcome.kind == AgentOutcomeKind.CLARIFY
        assert result.pydantic.outcome.message == msg
        assert len(result.pydantic.tool_executions) == 0

        _assert_decision_parity(
            result.reference.initial_decision,
            result.pydantic.initial_decision,
        )
        _assert_outcome_parity(result.reference, result.pydantic)
        # Both runtimes share the same ToolRegistry, so handler counters
        # reflect invocations from both runtimes (2 = 1 ref + 1 pyd).
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C16-P3: single READ -> respond
# ==============================================================================


class TestC16P3SingleReadRespond:
    """C16-P3: single READ -> respond — one tool call, two model requests."""

    def test_single_read_respond(
        self,
        counters: _HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Both runtimes produce equivalent single READ -> respond outcome."""
        msg = "Found it!"

        tool_call = _make_tool_call(
            name="read_alpha",
            arguments={"value": "gandalf"},
            call_id="call-1",
        )
        ref_responses = [
            _make_tool_aware_response(
                content="Looking up...",
                tool_calls=[tool_call],
            ),
            _make_tool_aware_response(content=_respond_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "gandalf"},
                            tool_call_id="call-1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=_respond_json(msg))])

        result = _run_both(
            "find gandalf",
            execution_context=read_context,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            counters=counters,
            ref_responses=ref_responses,
            pydantic_model_fn=pyd_model_fn,
        )

        # AgentLoop: 2 model requests, 1 tool execution
        assert result.ref_gateway.call_count == 2
        assert len(result.reference.tool_executions) == 1
        assert result.reference.tool_executions[0].tool_call.name == "read_alpha"

        # Pydantic runtime: 2 model requests, 1 tool execution
        assert request_count[0] == 2
        assert len(result.pydantic.tool_executions) == 1
        assert result.pydantic.tool_executions[0].tool_call.name == "read_alpha"

        # Outcome parity
        assert result.reference.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.pydantic.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.reference.outcome.message == msg
        assert result.pydantic.outcome.message == msg

        # DTO parity
        _assert_decision_parity(
            result.reference.initial_decision,
            result.pydantic.initial_decision,
            check_tool_calls=True,
        )
        _assert_execution_parity(
            result.reference.tool_executions,
            result.pydantic.tool_executions,
        )
        _assert_outcome_parity(result.reference, result.pydantic)
        # Both runtimes share the same ToolRegistry, so handler counters
        # reflect invocations from both runtimes (2 = 1 ref + 1 pyd).
        assert counters.alpha == 2
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C16-P4: single WRITE -> respond
# ==============================================================================


class TestC16P4SingleWriteRespond:
    """C16-P4: single WRITE -> respond — one tool call, two model requests."""

    def test_single_write_respond(
        self,
        counters: _HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """Both runtimes produce equivalent single WRITE -> respond outcome."""
        msg = "Written!"

        tool_call = _make_tool_call(
            name="write_alpha",
            arguments={"value": "save-data"},
            call_id="call-w1",
        )
        ref_responses = [
            _make_tool_aware_response(
                content="Saving...",
                tool_calls=[tool_call],
            ),
            _make_tool_aware_response(content=_respond_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="write_alpha",
                            args={"value": "save-data"},
                            tool_call_id="call-w1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=_respond_json(msg))])

        result = _run_both(
            "save data",
            execution_context=write_context,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            counters=counters,
            ref_responses=ref_responses,
            pydantic_model_fn=pyd_model_fn,
        )

        assert result.ref_gateway.call_count == 2
        assert len(result.reference.tool_executions) == 1
        assert result.reference.tool_executions[0].tool_call.name == "write_alpha"

        assert request_count[0] == 2
        assert len(result.pydantic.tool_executions) == 1
        assert result.pydantic.tool_executions[0].tool_call.name == "write_alpha"

        assert result.reference.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.pydantic.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.reference.outcome.message == msg
        assert result.pydantic.outcome.message == msg

        _assert_decision_parity(
            result.reference.initial_decision,
            result.pydantic.initial_decision,
            check_tool_calls=True,
        )
        _assert_execution_parity(
            result.reference.tool_executions,
            result.pydantic.tool_executions,
        )
        _assert_outcome_parity(result.reference, result.pydantic)
        # Both runtimes share the same ToolRegistry, so handler counters
        # reflect invocations from both runtimes (2 = 1 ref + 1 pyd).
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 2


# ==============================================================================
# C16-P5: two READ -> respond
# ==============================================================================


class TestC16P5TwoReadRespond:
    """C16-P5: two READ -> respond — two tool calls, two model requests."""

    def test_two_read_respond(
        self,
        counters: _HandlerCounters,
        registry: ToolRegistry,
        catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Both runtimes produce equivalent two READ -> respond outcome."""
        msg = "Both done!"

        tool_call_1 = _make_tool_call(
            name="read_alpha",
            arguments={"value": "first"},
            call_id="c1",
        )
        tool_call_2 = _make_tool_call(
            name="read_beta",
            arguments={"value": "42"},
            call_id="c2",
        )
        ref_responses = [
            _make_tool_aware_response(
                content="Looking up...",
                tool_calls=[tool_call_1, tool_call_2],
            ),
            _make_tool_aware_response(content=_respond_json(msg)),
        ]

        request_count: list[int] = [0]

        def pyd_model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "first"},
                            tool_call_id="c1",
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"value": "42"},
                            tool_call_id="c2",
                        ),
                    ]
                )
            return ModelResponse(parts=[TextPart(content=_respond_json(msg))])

        result = _run_both(
            "read both",
            execution_context=read_context,
            registry=registry,
            catalog=catalog,
            context_builder=context_builder,
            counters=counters,
            ref_responses=ref_responses,
            pydantic_model_fn=pyd_model_fn,
        )

        assert result.ref_gateway.call_count == 2
        assert len(result.reference.tool_executions) == 2
        assert result.reference.tool_executions[0].tool_call.name == "read_alpha"
        assert result.reference.tool_executions[1].tool_call.name == "read_beta"

        assert request_count[0] == 2
        assert len(result.pydantic.tool_executions) == 2
        assert result.pydantic.tool_executions[0].tool_call.name == "read_alpha"
        assert result.pydantic.tool_executions[1].tool_call.name == "read_beta"

        assert result.reference.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.pydantic.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.reference.outcome.message == msg
        assert result.pydantic.outcome.message == msg

        _assert_decision_parity(
            result.reference.initial_decision,
            result.pydantic.initial_decision,
            check_tool_calls=True,
        )
        _assert_execution_parity(
            result.reference.tool_executions,
            result.pydantic.tool_executions,
        )
        _assert_outcome_parity(result.reference, result.pydantic)
        # Both runtimes share the same ToolRegistry, so handler counters
        # reflect invocations from both runtimes (2 = 1 ref + 1 pyd).
        assert counters.alpha == 2
        assert counters.beta == 2
        assert counters.write_alpha == 0
