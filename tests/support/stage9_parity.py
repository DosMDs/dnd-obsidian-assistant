"""Test-only scenario harness for PAIM-11 Stage-9 behavioral parity.

This module provides a shared dual-runtime scenario harness that executes
both ``AgentLoop.run()`` and ``PydanticAIAgentRuntime.run()`` with
deterministic model outcomes and compares provider-neutral DTOs.

Every scenario defined here is a logical model behavior that is adapted
separately for each runtime.

This module is test-only and must not be imported by src/dnd_assistant/.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse
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
from dnd_assistant.errors import ModelError, NotFoundError
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


class _IntInput(BaseModel):
    number: int


class ToolOutput(BaseModel):
    result: str


_ToolOutput = ToolOutput


# ── Tool definitions ────────────────────────────────────────────────────────────

READ_ALPHA_DEF = ToolDefinition(
    name="read_alpha",
    description="A read-only test tool",
    input_schema=_StringInput,
    output_schema=_ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset(
        {
            SessionMode.NO_ACTIVE_SESSION,
            SessionMode.ACTIVE_SESSION,
        }
    ),
)

READ_BETA_DEF = ToolDefinition(
    name="read_beta",
    description="Another read-only test tool",
    input_schema=_IntInput,
    output_schema=_ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset(
        {
            SessionMode.NO_ACTIVE_SESSION,
            SessionMode.ACTIVE_SESSION,
        }
    ),
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


class HandlerCounters:
    """Fresh per-test handler invocation counters."""

    def __init__(self) -> None:
        self.alpha: int = 0
        self.beta: int = 0
        self.write_alpha: int = 0


def make_registry(counters: HandlerCounters) -> ToolRegistry:
    """Build a fresh ToolRegistry with three tools."""
    registry = ToolRegistry()

    def read_alpha_handler(inp: _StringInput, ctx: object) -> _ToolOutput:
        counters.alpha += 1
        return _ToolOutput(result=f"alpha:{inp.value}")

    def read_beta_handler(inp: _IntInput, ctx: object) -> _ToolOutput:
        counters.beta += 1
        return _ToolOutput(result=f"beta:{inp.number}")

    def write_alpha_handler(inp: _StringInput, ctx: object) -> _ToolOutput:
        counters.write_alpha += 1
        return _ToolOutput(result=f"write:{inp.value}")

    registry.register(READ_ALPHA_DEF, read_alpha_handler)
    registry.register(READ_BETA_DEF, read_beta_handler)
    registry.register(WRITE_ALPHA_DEF, write_alpha_handler)
    return registry


def make_registry_with_hidden(
    counters: HandlerCounters,
    hidden_name: str = "hidden_tool",
) -> tuple[ToolRegistry, ToolDefinition]:
    """Build a ToolRegistry with an extra hidden tool for exposure tests."""
    registry = make_registry(counters)

    hidden_def = ToolDefinition(
        name=hidden_name,
        description="A hidden test tool",
        input_schema=_StringInput,
        output_schema=_ToolOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {
                SessionMode.NO_ACTIVE_SESSION,
                SessionMode.ACTIVE_SESSION,
            }
        ),
    )

    def hidden_handler(inp: _StringInput, ctx: object) -> _ToolOutput:
        counters.alpha += 1
        return _ToolOutput(result=f"hidden:{inp.value}")

    registry.register(hidden_def, hidden_handler)
    return registry, hidden_def


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


def make_context_builder() -> AgentContextBuilder:
    return AgentContextBuilder(
        search_service=_StubSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),
        event_repository=_StubEventRepo(),
        world_time_repository=_StubWorldTimeRepo(),
    )


# ── Fake ModelGateway for reference runtime ────────────────────────────────────


class _FakeModelGateway(ModelGateway):
    """Fake ModelGateway that returns pre-built responses.

    Supports scripted failures: set ``fail_on_request`` to a 1-based request
    number; that request will raise the specified exception instead of
    returning a response.

    Records every ``tools`` argument in ``exposed_tool_lists`` for
    model-visible exposure verification.
    """

    def __init__(
        self,
        responses: list[ToolAwareResponse],
        *,
        fail_on_request: int | None = None,
        fail_exc: Exception | None = None,
    ) -> None:
        self._responses = responses
        self.call_count: int = 0
        self._fail_on_request = fail_on_request
        self._fail_exc = fail_exc or ModelError("simulated model failure")
        self.exposed_tool_lists: list[list[ToolPublicDefinition]] = []

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.call_count += 1
        self.exposed_tool_lists.append(tools)
        if self._fail_on_request is not None and self.call_count == self._fail_on_request:
            raise self._fail_exc
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


class _CountingToolExecutor:
    """Wraps a real ToolExecutor and counts execute() attempts."""

    def __init__(self, executor: ToolExecutor) -> None:
        self._inner = executor
        self.execute_count: int = 0

    def execute(
        self,
        tool_name: str,
        *,
        input_data: dict[str, Any],
        context: ExecutionContext,
    ) -> BaseModel:
        self.execute_count += 1
        return self._inner.execute(tool_name, input_data=input_data, context=context)


# ── Helper: build ToolAwareResponse / ToolCall ──────────────────────────────────


def make_tool_aware_response(
    content: str | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> ToolAwareResponse:
    """Build a ToolAwareResponse.

    For tool-only responses (no assistant text), pass ``content=None``.
    For responses with assistant text, pass the text string.
    """
    return ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tuple(tool_calls or []),
        ),
    )


def make_tool_call(
    name: str,
    arguments: dict[str, object] | None = None,
    call_id: str | None = None,
) -> ToolCall:
    return ToolCall(
        name=name,
        arguments=arguments or {},
        call_id=call_id,
    )


def respond_json(message: str) -> str:
    return json.dumps(
        {"kind": "respond", "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def clarify_json(message: str) -> str:
    return json.dumps(
        {"kind": "clarify", "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
    )


# ── Execution contexts ─────────────────────────────────────────────────────────


def make_read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


def make_write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


def make_write_context_no_audit() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


def make_wrong_session_mode_context() -> ExecutionContext:
    """WRITE permission + NO_ACTIVE_SESSION + valid audit.

    write_alpha requires ACTIVE_SESSION, so it is hidden solely because
    of session mode.
    """
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


# ── Catalog builder ────────────────────────────────────────────────────────────


def build_catalog(registry: ToolRegistry) -> ToolRegistrySchema:
    from dnd_assistant.tools.catalog import build_tool_registry_schema

    return build_tool_registry_schema(registry)


# ── Scenario definition ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stage9Scenario:
    """One logical model-behavior scenario for dual-runtime parity testing.

    Attributes:
        user_input: The user query string.
        execution_context: The execution context for tool exposure.
        ref_responses: List of ToolAwareResponse values for the reference runtime.
        pyd_model_fn: A FunctionModel-compatible callback for the Pydantic runtime.
        expected_outcome_kind: Expected AgentOutcomeKind.
        expected_outcome_message: Expected outcome message text.
        expected_model_requests_ref: Expected model request count (reference).
        expected_model_requests_pyd: Expected model request count (Pydantic).
        expected_tool_executions: Expected number of tool executions.
        expected_handler_counts: Expected handler counts (alpha, beta, write).
        expect_failure: If True, expect ModelError from both runtimes.
    """

    user_input: str
    execution_context: ExecutionContext
    ref_responses: list[ToolAwareResponse]
    pyd_model_fn: Any
    expected_outcome_kind: AgentOutcomeKind | None = None
    expected_outcome_message: str | None = None
    expected_model_requests_ref: int = 1
    expected_model_requests_pyd: int = 1
    expected_tool_executions: int = 0
    expected_handler_counts: tuple[int, int, int] = (0, 0, 0)
    expect_failure: bool = False


@dataclass(frozen=True)
class DualRuntimeObservation:
    """Normalized observation from both runtimes for one scenario.

    Attributes:
        reference: The AgentRunResult from AgentLoop.run(), or None on failure.
        pydantic: The AgentRunResult from PydanticAIAgentRuntime.run(), or None.
        ref_model_requests: Model requests made by the reference runtime.
        pyd_model_requests: Model requests made by the Pydantic runtime.
        ref_handler_counts: Handler counts from the reference runtime.
        pyd_handler_counts: Handler counts from the Pydantic runtime.
        ref_executor_attempts: ToolExecutor.execute() calls (reference).
        pyd_executor_attempts: ToolExecutor.execute() calls (Pydantic bridge).
        ref_error: Exception raised by reference runtime, or None.
        pyd_error: Exception raised by Pydantic runtime, or None.
        ref_gateway: The _FakeModelGateway used (for call count inspection).
    """

    reference: AgentRunResult | None
    pydantic: AgentRunResult | None
    ref_model_requests: int
    pyd_model_requests: int
    ref_handler_counts: tuple[int, int, int]
    pyd_handler_counts: tuple[int, int, int]
    ref_executor_attempts: int = 0
    pyd_executor_attempts: int = 0
    ref_error: Exception | None = None
    pyd_error: Exception | None = None
    ref_gateway: _FakeModelGateway | None = None
    ref_exposed_tool_lists: list[list[ToolPublicDefinition]] | None = None
    pyd_exposed_tool_lists: list[list[Any]] | None = None


# ── Internal helpers ────────────────────────────────────────────────────────────


def _side_effect_sort_key(se: Any) -> str:
    return se.value if hasattr(se, "value") else str(se)


def _session_mode_sort_key(sm: Any) -> str:
    return sm.value if hasattr(sm, "value") else str(sm)


def _build_public_defs(registry: ToolRegistry) -> list[ToolPublicDefinition]:
    """Build ToolPublicDefinition list from a ToolRegistry for the reference runtime.

    Uses sorted() for side_effects and allowed_session_modes to match
    the deterministic ordering produced by build_tool_registry_schema.
    """
    public_defs = []
    for td in registry.list_definitions():
        public_defs.append(
            ToolPublicDefinition(
                name=td.name,
                description=td.description,
                input_schema=td.input_schema.model_json_schema(),
                output_schema=td.output_schema.model_json_schema(),
                permission=td.permission,
                side_effects=sorted(td.side_effects, key=_side_effect_sort_key),
                allowed_session_modes=sorted(td.allowed_session_modes, key=_session_mode_sort_key),
            )
        )
    return public_defs


def _copy_registry(
    source: ToolRegistry,
    dest: ToolRegistry,
    counters: HandlerCounters,
) -> None:
    """Copy tool definitions and handlers from source to dest registry."""
    for td in source.list_definitions():
        if td.name == "read_alpha":

            def handler(inp: _StringInput, ctx: object) -> _ToolOutput:
                counters.alpha += 1
                return _ToolOutput(result=f"alpha:{inp.value}")
        elif td.name == "read_beta":

            def handler(inp: _IntInput, ctx: object) -> _ToolOutput:
                counters.beta += 1
                return _ToolOutput(result=f"beta:{inp.number}")
        elif td.name == "write_alpha":

            def handler(inp: _StringInput, ctx: object) -> _ToolOutput:
                counters.write_alpha += 1
                return _ToolOutput(result=f"write:{inp.value}")
        else:

            def handler(inp: _StringInput, ctx: object) -> _ToolOutput:
                counters.alpha += 1
                return _ToolOutput(result=f"other:{inp.value}")

        dest.register(td, handler)


# ── Dual-runtime execution ─────────────────────────────────────────────────────


def run_scenario(
    scenario: Stage9Scenario,
    *,
    registry: ToolRegistry,
    catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    ref_counters: HandlerCounters,
    pyd_counters: HandlerCounters,
) -> DualRuntimeObservation:
    """Execute both runtimes for a given scenario and return normalized observations.

    Args:
        scenario: The scenario to execute.
        registry: Shared ToolRegistry (both runtimes use the same handlers).
        catalog: ToolRegistrySchema for the Pydantic preparer.
        context_builder: AgentContextBuilder for both runtimes.
        ref_counters: Handler counters for the reference runtime.
        pyd_counters: Handler counters for the Pydantic runtime.

    Returns:
        A DualRuntimeObservation with normalized results from both runtimes.
    """
    # ── Reference: AgentLoop ────────────────────────────────────────────────
    ref_gateway = _FakeModelGateway(scenario.ref_responses)
    tool_executor = ToolExecutor(registry)
    counting_executor = _CountingToolExecutor(tool_executor)
    tool_svc = AgentToolExecutionService(tool_executor=counting_executor)

    public_defs = _build_public_defs(registry)
    ref_catalog = ToolRegistrySchema(tools=public_defs)

    ref_loop = AgentLoop(
        context_builder=context_builder,
        model_gateway=ref_gateway,
        tool_catalog=ref_catalog,
        tool_execution_service=tool_svc,
    )

    ref_error: Exception | None = None
    reference_result: AgentRunResult | None = None
    try:
        reference_result = ref_loop.run(
            scenario.user_input,
            execution_context=scenario.execution_context,
        )
    except Exception as exc:
        ref_error = exc

    ref_model_requests = ref_gateway.call_count
    ref_executor_attempts = counting_executor.execute_count

    # ── Pydantic: PydanticAIAgentRuntime ────────────────────────────────────
    pyd_error: Exception | None = None
    pydantic_result: AgentRunResult | None = None

    pyd_registry = ToolRegistry()
    _copy_registry(registry, pyd_registry, pyd_counters)

    tool_bridge = PydanticAIToolBridge(registry=pyd_registry)
    pyd_executor = ToolExecutor(pyd_registry)
    pyd_counting_executor = _CountingToolExecutor(pyd_executor)
    # Monkey-patch the bridge's lazy executor to use our counting wrapper.
    # The bridge creates its executor lazily; we set it directly.
    object.__setattr__(tool_bridge, "_executor", pyd_counting_executor)

    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=catalog,
        tool_bridge=tool_bridge,
    )

    pyd_request_count: list[int] = [0]
    pyd_exposed_tool_lists: list[list[Any]] = []

    def counting_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
        pyd_request_count[0] += 1
        pyd_exposed_tool_lists.append(list(getattr(agent_info, "function_tools", [])))
        return scenario.pyd_model_fn(messages, agent_info)

    counting_model = FunctionModel(counting_fn)
    pydantic_runtime = PydanticAIAgentRuntime(
        run_preparer=preparer,
        model=counting_model,
    )

    try:
        pydantic_result = pydantic_runtime.run(
            scenario.user_input,
            execution_context=scenario.execution_context,
        )
    except Exception as exc:
        pyd_error = exc

    pyd_model_requests = pyd_request_count[0]
    pyd_executor_attempts = pyd_counting_executor.execute_count

    return DualRuntimeObservation(
        reference=reference_result,
        pydantic=pydantic_result,
        ref_model_requests=ref_model_requests,
        pyd_model_requests=pyd_model_requests,
        ref_handler_counts=(
            ref_counters.alpha,
            ref_counters.beta,
            ref_counters.write_alpha,
        ),
        pyd_handler_counts=(
            pyd_counters.alpha,
            pyd_counters.beta,
            pyd_counters.write_alpha,
        ),
        ref_executor_attempts=ref_executor_attempts,
        pyd_executor_attempts=pyd_executor_attempts,
        ref_error=ref_error,
        pyd_error=pyd_error,
        ref_gateway=ref_gateway,
        ref_exposed_tool_lists=ref_gateway.exposed_tool_lists,
        pyd_exposed_tool_lists=pyd_exposed_tool_lists,
    )


# ── Assertion helpers ──────────────────────────────────────────────────────────


def assert_decision_parity(
    ref_decision: AgentDecision,
    pyd_decision: AgentDecision,
    *,
    check_tool_calls: bool = False,
) -> None:
    """Compare two AgentDecision instances for parity.

    Compares:
    - prompt_version
    - initial ChatRequest model_dump (full provider-neutral DTO)
    - full ToolPublicDefinition values (name, description, input_schema,
      output_schema, permission, side_effects, allowed_session_modes)
    - tool call names, IDs, arguments, order
    - initial assistant response content (when both sides have content)
    """
    assert ref_decision.prompt_version == pyd_decision.prompt_version
    assert ref_decision.request.model_dump() == pyd_decision.request.model_dump()

    # Full ToolPublicDefinition comparison (not just names)
    assert len(ref_decision.exposed_tools) == len(pyd_decision.exposed_tools)
    for ref_t, pyd_t in zip(ref_decision.exposed_tools, pyd_decision.exposed_tools, strict=True):
        assert ref_t.name == pyd_t.name
        assert ref_t.description == pyd_t.description
        assert ref_t.input_schema == pyd_t.input_schema
        assert ref_t.output_schema == pyd_t.output_schema
        assert ref_t.permission == pyd_t.permission
        assert ref_t.side_effects == pyd_t.side_effects
        assert ref_t.allowed_session_modes == pyd_t.allowed_session_modes

    if check_tool_calls:
        assert ref_decision.response.message.content == pyd_decision.response.message.content, (
            f"Content mismatch: ref={ref_decision.response.message.content!r} "
            f"pyd={pyd_decision.response.message.content!r}"
        )
        ref_calls = ref_decision.response.message.tool_calls
        pyd_calls = pyd_decision.response.message.tool_calls
        assert len(ref_calls) == len(pyd_calls)
        for ref_c, pyd_c in zip(ref_calls, pyd_calls, strict=True):
            assert ref_c.name == pyd_c.name
            assert ref_c.arguments == pyd_c.arguments
            # call_id parity: both None or both equal
            if ref_c.call_id is not None and pyd_c.call_id is not None:
                assert ref_c.call_id == pyd_c.call_id
    else:
        assert ref_decision.response.message.content == pyd_decision.response.message.content


def assert_execution_parity(
    ref_executions: tuple[AgentToolExecutionResult, ...],
    pyd_executions: tuple[AgentToolExecutionResult, ...],
) -> None:
    """Compare two execution result tuples for parity."""
    assert len(ref_executions) == len(pyd_executions)
    for ref_e, pyd_e in zip(ref_executions, pyd_executions, strict=True):
        assert ref_e.tool_call.model_dump() == pyd_e.tool_call.model_dump()
        assert ref_e.output.model_dump() == pyd_e.output.model_dump()
        assert ref_e.tool_message.model_dump() == pyd_e.tool_message.model_dump()


def assert_outcome_parity(
    ref_result: AgentRunResult,
    pyd_result: AgentRunResult,
) -> None:
    """Compare terminal outcomes for parity."""
    assert ref_result.outcome.kind == pyd_result.outcome.kind
    assert ref_result.outcome.message == pyd_result.outcome.message
    assert ref_result.final_response.message.content == pyd_result.final_response.message.content


def assert_parity(
    obs: DualRuntimeObservation,
    *,
    expected_outcome_kind: AgentOutcomeKind | None = None,
    expected_outcome_message: str | None = None,
    expected_model_requests_ref: int = 1,
    expected_model_requests_pyd: int = 1,
    expected_tool_executions: int = 0,
    expected_handler_counts: tuple[int, int, int] = (0, 0, 0),
    expected_executor_attempts: int | None = None,
    expect_failure: bool = False,
    check_tool_calls: bool = False,
    expected_ref_error_type: type[Exception] | tuple[type[Exception], ...] | None = None,
    expected_pyd_error_type: type[Exception] | tuple[type[Exception], ...] | None = None,
) -> None:
    """Assert full parity between reference and Pydantic runtime observations.

    When ``expect_failure=True``, this helper verifies:
    - Both runtimes raised an exception.
    - Both runtimes produced no result.
    - Error types match expectations (when specified).
    - Model request counts match expectations.
    - Executor/bridge attempt counts match expectations.
    - Handler counts match expectations (zero for pre-execution failures).
    - No forbidden WRITE handler effects.
    """
    if expect_failure:
        assert obs.ref_error is not None, "Expected reference runtime to raise"
        assert obs.pyd_error is not None, "Expected Pydantic runtime to raise"
        assert obs.reference is None
        assert obs.pydantic is None

        # Error type assertions
        if expected_ref_error_type is not None:
            assert isinstance(obs.ref_error, expected_ref_error_type), (
                f"Reference error type: {type(obs.ref_error).__name__} "
                f"not in {expected_ref_error_type}"
            )
        if expected_pyd_error_type is not None:
            assert isinstance(obs.pyd_error, expected_pyd_error_type), (
                f"Pydantic error type: {type(obs.pyd_error).__name__} "
                f"not in {expected_pyd_error_type}"
            )

        # Model request counts
        assert obs.ref_model_requests == expected_model_requests_ref, (
            f"Reference model requests: {obs.ref_model_requests} != {expected_model_requests_ref}"
        )
        assert obs.pyd_model_requests == expected_model_requests_pyd, (
            f"Pydantic model requests: {obs.pyd_model_requests} != {expected_model_requests_pyd}"
        )

        # Executor/bridge attempt counts
        if expected_executor_attempts is not None:
            assert obs.ref_executor_attempts == expected_executor_attempts, (
                f"Reference executor attempts: {obs.ref_executor_attempts} != {expected_executor_attempts}"
            )
            assert obs.pyd_executor_attempts == expected_executor_attempts, (
                f"Pydantic executor attempts: {obs.pyd_executor_attempts} != {expected_executor_attempts}"
            )

        # Handler counts
        assert obs.ref_handler_counts == expected_handler_counts, (
            f"Reference handler counts: {obs.ref_handler_counts} != {expected_handler_counts}"
        )
        assert obs.pyd_handler_counts == expected_handler_counts, (
            f"Pydantic handler counts: {obs.pyd_handler_counts} != {expected_handler_counts}"
        )

        # No forbidden WRITE effects
        assert obs.ref_handler_counts[2] == 0, "Reference WRITE handler invoked during failure"
        assert obs.pyd_handler_counts[2] == 0, "Pydantic WRITE handler invoked during failure"

        return

    assert obs.ref_error is None, f"Reference runtime raised: {obs.ref_error}"
    assert obs.pyd_error is None, f"Pydantic runtime raised: {obs.pyd_error}"
    assert obs.reference is not None
    assert obs.pydantic is not None

    # Model request counts
    assert obs.ref_model_requests == expected_model_requests_ref, (
        f"Reference model requests: {obs.ref_model_requests} != {expected_model_requests_ref}"
    )
    assert obs.pyd_model_requests == expected_model_requests_pyd, (
        f"Pydantic model requests: {obs.pyd_model_requests} != {expected_model_requests_pyd}"
    )

    # Tool execution counts (results captured in AgentRunResult)
    assert len(obs.reference.tool_executions) == expected_tool_executions
    assert len(obs.pydantic.tool_executions) == expected_tool_executions

    # Executor attempt counts
    if expected_executor_attempts is not None:
        assert obs.ref_executor_attempts == expected_executor_attempts, (
            f"Reference executor attempts: {obs.ref_executor_attempts} != {expected_executor_attempts}"
        )
        assert obs.pyd_executor_attempts == expected_executor_attempts, (
            f"Pydantic executor attempts: {obs.pyd_executor_attempts} != {expected_executor_attempts}"
        )

    # Handler counts
    assert obs.ref_handler_counts == expected_handler_counts
    assert obs.pyd_handler_counts == expected_handler_counts

    # DTO parity
    assert_decision_parity(
        obs.reference.initial_decision,
        obs.pydantic.initial_decision,
        check_tool_calls=check_tool_calls,
    )
    if expected_tool_executions > 0:
        assert_execution_parity(
            obs.reference.tool_executions,
            obs.pydantic.tool_executions,
        )
    assert_outcome_parity(obs.reference, obs.pydantic)

    # Outcome kind/message
    if expected_outcome_kind is not None:
        assert obs.reference.outcome.kind == expected_outcome_kind
        assert obs.pydantic.outcome.kind == expected_outcome_kind
    if expected_outcome_message is not None:
        assert obs.reference.outcome.message == expected_outcome_message
        assert obs.pydantic.outcome.message == expected_outcome_message


def assert_model_visible_tool_parity(
    obs: DualRuntimeObservation,
    *,
    expected_names: tuple[str, ...],
    expected_requests: int,
) -> None:
    """Assert literal model-visible tool exposure parity.

    Inspects the actual tool lists given to the model on each request:
    - Reference: ``ModelGateway.chat_with_tools(..., tools=...)``
    - Candidate: ``agent_info.function_tools`` from ``FunctionModel`` callback

    Compares tool count, name, order, description, and input JSON schema
    for every corresponding model request.
    """
    # Reference: _FakeModelGateway.exposed_tool_lists
    assert obs.ref_exposed_tool_lists is not None
    assert len(obs.ref_exposed_tool_lists) == expected_requests
    for req_idx, tools in enumerate(obs.ref_exposed_tool_lists):
        ref_names = tuple(t.name for t in tools)
        assert ref_names == expected_names, (
            f"Reference request #{req_idx + 1} tool names: {ref_names} != {expected_names}"
        )

    # Candidate: agent_info.function_tools from FunctionModel callback
    assert obs.pyd_exposed_tool_lists is not None
    assert len(obs.pyd_exposed_tool_lists) == expected_requests
    for req_idx, tools in enumerate(obs.pyd_exposed_tool_lists):
        pyd_names = tuple(t.name for t in tools)
        assert pyd_names == expected_names, (
            f"Pydantic request #{req_idx + 1} tool names: {pyd_names} != {expected_names}"
        )

    # Cross-reference: for each request, compare tool metadata
    for req_idx in range(expected_requests):
        ref_tools = obs.ref_exposed_tool_lists[req_idx]
        pyd_tools = obs.pyd_exposed_tool_lists[req_idx]
        assert len(ref_tools) == len(pyd_tools)
        for ref_t, pyd_t in zip(ref_tools, pyd_tools, strict=True):
            assert ref_t.name == pyd_t.name
            assert ref_t.description == pyd_t.description
            # Compare input JSON schema between ToolPublicDefinition and
            # pydantic_ai ToolDefinition.parameters_json_schema
            assert ref_t.input_schema == pyd_t.parameters_json_schema, (
                f"Tool {ref_t.name}: input schema mismatch"
            )
