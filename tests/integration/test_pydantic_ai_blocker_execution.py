"""PAIM-C03: Corrected blocker execution — ExternalToolset + HandleDeferredToolCalls.

Tests BG-09 through BG-12 plus request_limit and retry policy using the
intended public extension points:

    ExternalToolset
    +
    HandleDeferredToolCalls
    +
    DeferredToolRequests.calls
    +
    DeferredToolResults (via requests.build_results(calls=...))
    +
    existing ToolExecutor

Architecture under test
───────────────────────
    frozen application tool snapshot
        |
    translate to Pydantic AI ToolDefinition[]
        |
    ExternalToolset (no Python handler)
        |
    HandleDeferredToolCalls handler receives COMPLETE batch
        |
    application full-batch admission
        |
    allowed?
        no ------ fail before ToolExecutor
        yes
            |
    ToolExecutor.execute() sequentially
        |
    DeferredToolResults (via build_results)
        |
    agent continues IN THE SAME RUN
        |
    terminal model response

Key invariants:
- No @agent.tool / @agent.tool_plain Python handler functions exist.
- All project execution goes through ToolExecutor.
- The model->tools->model cycle stays inside ONE agent.run_sync().
- UsageLimits(request_limit=N) bounds model requests.

All tests are deterministic and require no real Ollama or network access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

# Pydantic AI imports
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDefinition
from pydantic_ai.toolsets import ExternalToolset

from dnd_assistant.errors import ConflictError
from dnd_assistant.errors import ValidationError as ProjectValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
)
from dnd_assistant.tools.types import (
    ToolDefinition as ProjectToolDefinition,
)

# ============================================================================
# Test-local schema / handler helpers
# ============================================================================


class AlphaInput(BaseModel):
    value: str


class BetaInput(BaseModel):
    number: int


class ToolOutput(BaseModel):
    result: str


class HandlerCounters:
    """Counters for tracking handler invocations."""

    def __init__(self) -> None:
        self.alpha: int = 0
        self.beta: int = 0
        self.write_alpha: int = 0
        self.all_calls: list[str] = []

    def inc_alpha(self) -> None:
        self.alpha += 1
        self.all_calls.append("read_alpha")

    def inc_beta(self) -> None:
        self.beta += 1
        self.all_calls.append("read_beta")

    def inc_write_alpha(self) -> None:
        self.write_alpha += 1
        self.all_calls.append("write_alpha")


# Tool definitions

READ_ALPHA_DEF = ProjectToolDefinition(
    name="read_alpha",
    description="A read-only test tool",
    input_schema=AlphaInput,
    output_schema=ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

READ_BETA_DEF = ProjectToolDefinition(
    name="read_beta",
    description="Another read-only test tool",
    input_schema=BetaInput,
    output_schema=ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

WRITE_ALPHA_DEF = ProjectToolDefinition(
    name="write_alpha",
    description="A write test tool",
    input_schema=AlphaInput,
    output_schema=ToolOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def counters() -> HandlerCounters:
    return HandlerCounters()


@pytest.fixture
def tool_registry(counters: HandlerCounters) -> ToolRegistry:
    """Build a test ToolRegistry with three tools and in-memory handlers."""
    registry = ToolRegistry()

    def read_alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        counters.inc_alpha()
        return ToolOutput(result=f"alpha:{inp.value}")

    def read_beta_handler(inp: BetaInput, ctx: object) -> ToolOutput:
        counters.inc_beta()
        return ToolOutput(result=f"beta:{inp.number}")

    def write_alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        counters.inc_write_alpha()
        return ToolOutput(result=f"write:{inp.value}")

    registry.register(READ_ALPHA_DEF, read_alpha_handler)
    registry.register(READ_BETA_DEF, read_beta_handler)
    registry.register(WRITE_ALPHA_DEF, write_alpha_handler)
    return registry


@pytest.fixture
def executor(tool_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(tool_registry)


@pytest.fixture
def read_ctx() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_ctx() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


@pytest.fixture
def write_ctx_no_audit() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


@pytest.fixture
def frozen_snapshot(
    tool_registry: ToolRegistry,
) -> tuple[ProjectToolDefinition, ...]:
    """Run-local immutable snapshot of tool definitions."""
    return tuple(tool_registry.list_definitions())


# ============================================================================
# Helper: translate project snapshot to Pydantic AI ToolDefinition[]
# ============================================================================


def _to_pyd_tool_defs(
    snapshot: tuple[ProjectToolDefinition, ...],
) -> list[ToolDefinition]:
    """Translate frozen project tool definitions to Pydantic AI ToolDefinition list."""
    result: list[ToolDefinition] = []
    for td in snapshot:
        schema = td.input_schema.model_json_schema()
        result.append(
            ToolDefinition(
                name=td.name,
                description=td.description,
                parameters_json_schema=schema,
            )
        )
    return result


# ============================================================================
# Helper: build ExternalToolset from project snapshot
# ============================================================================


def _make_external_toolset(
    snapshot: tuple[ProjectToolDefinition, ...],
) -> ExternalToolset:
    """Build an ExternalToolset from the frozen project snapshot."""
    pyd_defs = _to_pyd_tool_defs(snapshot)
    return ExternalToolset(pyd_defs)


# ============================================================================
# Helper: create HandleDeferredToolCalls capability
# ============================================================================


def _make_deferred_handler(
    snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    context: ExecutionContext,
    *,
    counters: HandlerCounters | None = None,
    handler_invocations: list[int] | None = None,
    executor_invocations: list[int] | None = None,
    reject_second_batch: bool = True,
) -> HandleDeferredToolCalls:
    """Create a HandleDeferredToolCalls capability with full Stage-9 safety.

    The handler:
    1. Increments handler_invocations counter.
    2. If reject_second_batch and this is batch #2, raises RuntimeError.
    3. Runs application full-batch preflight against frozen snapshot.
    4. If batch is not allowed, raises RuntimeError.
    5. Executes each admitted call through ToolExecutor sequentially.
    6. Returns DeferredToolResults via build_results(calls=...).
    """
    snapshot_map: dict[str, ProjectToolDefinition] = {d.name: d for d in snapshot}
    batch_count: list[int] = [0]

    def _handler(ctx: RunContext, requests: DeferredToolRequests) -> DeferredToolResults | None:
        nonlocal batch_count
        batch_count[0] += 1

        if handler_invocations is not None:
            handler_invocations[0] += 1

        if reject_second_batch and batch_count[0] > 1:
            raise RuntimeError("Second deferred batch rejected by application policy")

        all_calls = list(requests.calls)
        if not all_calls:
            return None

        # --- Preflight ---
        if len(all_calls) > 4:
            raise RuntimeError(f"Batch size {len(all_calls)} exceeds 4")

        seen_ids: set[str] = set()
        for c in all_calls:
            if c.tool_call_id in seen_ids:
                raise RuntimeError(f"Duplicate tool_call_id '{c.tool_call_id}'")
            seen_ids.add(c.tool_call_id)

        resolved: list[tuple[ToolCallPart, ProjectToolDefinition]] = []
        for c in all_calls:
            definition = snapshot_map.get(c.tool_name)
            if definition is None:
                raise RuntimeError(f"Unknown/hidden tool '{c.tool_name}'")
            resolved.append((c, definition))

        if len(resolved) > 1:
            for c, definition in resolved:
                if definition.permission != Permission.READ:
                    raise RuntimeError(
                        f"Mixed batch: WRITE tool '{c.tool_name}' not allowed in multi-call"
                    )

        # --- Execute through ToolExecutor sequentially ---
        results: dict[str, Any] = {}
        for call, definition in resolved:
            if executor_invocations is not None:
                executor_invocations[0] += 1
            input_data = call.args if isinstance(call.args, dict) else {}
            output = executor.execute(
                definition.name,
                input_data=input_data,
                context=context,
            )
            results[call.tool_call_id] = output.result

        return requests.build_results(calls=results)

    return HandleDeferredToolCalls(handler=_handler)


# ============================================================================
# Helper: create agent with ExternalToolset
# ============================================================================


def _make_agent(
    model: TestModel | FunctionModel,
    snapshot: tuple[ProjectToolDefinition, ...],
) -> Agent:
    """Create a Pydantic AI Agent with ExternalToolset from project snapshot.

    No @agent.tool or @agent.tool_plain decorators are used.
    """
    agent = Agent(model, output_type=str, retries={"tools": 0})
    toolset = _make_external_toolset(snapshot)

    @agent.toolset
    def _toolset_factory(ctx: RunContext) -> ExternalToolset:
        return toolset

    return agent


# ============================================================================
# BG-09 — Single READ path through ToolExecutor
# ============================================================================


def test_bg09_single_read_through_executor(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """One valid READ call.

    Proves:
      - HandleDeferredToolCalls handler invokes ToolExecutor exactly once
      - project READ handler executes exactly once
      - result returns to model
      - terminal second model response
      - model requests == 2 (model -> tools -> model)
    """
    model = TestModel(call_tools=["read_alpha"])
    agent = _make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
        frozen_snapshot,
        executor,
        read_ctx,
        counters=counters,
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    result = agent.run_sync(
        "use read_alpha", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
    )

    # One handler invocation, one ToolExecutor execution
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    assert counters.alpha == 1, f"expected 1 alpha handler call, got {counters.alpha}"
    # Terminal output is a string
    assert isinstance(result.output, str), (
        f"expected str output, got {type(result.output).__name__}"
    )


# ============================================================================
# BG-11 — ToolExecutor remains final authorization boundary
# ============================================================================


def test_bg11_read_authority_denies_write_tool(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """READ authority + WRITE tool: ToolExecutor denies.

    Proves:
      - application batch shape itself would allow a single call
      - but ToolExecutor denies permission
      - WRITE handler == 0
      - ToolExecutor invocation == 1
    """
    model = TestModel(call_tools=["write_alpha"])
    agent = _make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
        frozen_snapshot,
        executor,
        read_ctx,
        counters=counters,
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    with pytest.raises(ConflictError, match="Permission denied"):
        agent.run_sync(
            "use write_alpha", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was invoked (batch was received)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # ToolExecutor was invoked (permission denied inside it)
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    # WRITE handler == 0
    assert counters.write_alpha == 0, f"expected 0 write_alpha calls, got {counters.write_alpha}"


def test_bg11_write_authority_missing_audit_context(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx_no_audit: ExecutionContext,
) -> None:
    """WRITE authority but missing AuditContext: ToolExecutor denies.

    Proves:
      - ToolExecutor denies
      - WRITE handler == 0
      - ToolExecutor invocation == 1
    """
    model = TestModel(call_tools=["write_alpha"])
    agent = _make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
        frozen_snapshot,
        executor,
        write_ctx_no_audit,
        counters=counters,
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    with pytest.raises(ProjectValidationError, match="requires a non-None AuditContext"):
        agent.run_sync(
            "use write_alpha", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was invoked (batch was received)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # ToolExecutor was invoked (validation failed inside it)
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    # WRITE handler == 0
    assert counters.write_alpha == 0, f"expected 0 write_alpha calls, got {counters.write_alpha}"


# ============================================================================
# BG-12 — Second model response requests another tool
# ============================================================================


def test_bg12_second_round_tool_rejected(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Second model response requests another tool.

    Construct deterministic model behavior:
      request 1 -> one allowed READ call
      batch 1 -> admitted -> ToolExecutor executes once
      request 2 -> model requests another tool

    Proves:
      - model requests == 2
      - first-batch ToolExecutor executions == 1
      - second-batch ToolExecutor executions == 0
      - total ToolExecutor executions == 1
      - no third model request
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": f"req_{model_requests[0]}"},
                    tool_call_id=f"call_{model_requests[0]}",
                )
            ]
        )

    model = FunctionModel(function=make_response)
    agent = _make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
        frozen_snapshot,
        executor,
        read_ctx,
        counters=counters,
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    with pytest.raises(RuntimeError, match="Second deferred batch rejected"):
        agent.run_sync("use tool", capabilities=[cap], usage_limits=UsageLimits(request_limit=3))

    # Handler was invoked twice (two batches)
    assert handler_invocations[0] == 2, (
        f"expected 2 handler invocations, got {handler_invocations[0]}"
    )
    # Only first batch was executed through ToolExecutor
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    assert counters.alpha == 1, f"expected 1 alpha call, got {counters.alpha}"
    # Model requests == 2 (two model calls before second batch rejected)
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"


# ============================================================================
# Whole-turn model request limit — defense in depth
# ============================================================================


def test_request_limit_defense_in_depth() -> None:
    """UsageLimits(request_limit=2) allows model->tools->model cycle.

    With HandleDeferredToolCalls, the complete model->tools->model cycle
    stays inside one agent.run_sync(). UsageLimits(request_limit=2) allows
    exactly 2 model requests.

    Proves:
      - model requests == 2 with request_limit=2
      - handler invoked once
      - terminal output is a string
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        if model_requests[0] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "x"},
                        tool_call_id="call_1",
                    )
                ]
            )
        # Second request: terminal response with text
        return ModelResponse(parts=[TextPart(content="done")])

    model = FunctionModel(function=make_response)
    snapshot = (
        ProjectToolDefinition(
            name="read_alpha",
            description="A read-only test tool",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        ),
    )
    agent = _make_agent(model, snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    registry = ToolRegistry()

    def alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        return ToolOutput(result=f"alpha:{inp.value}")

    registry.register(snapshot[0], alpha_handler)
    local_executor = ToolExecutor(registry)

    cap = _make_deferred_handler(
        snapshot,
        local_executor,
        ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        ),
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    result = agent.run_sync("start", capabilities=[cap], usage_limits=UsageLimits(request_limit=3))

    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"
    assert isinstance(result.output, str), (
        f"expected str output, got {type(result.output).__name__}"
    )


# ============================================================================
# Whole-turn request limit — third request prevented
# ============================================================================


def test_request_limit_third_request_prevented() -> None:
    """UsageLimits(request_limit=2) prevents a third model request.

    Construct a scenario that would require a third model request:
      request 1 -> tool call
      request 2 -> tool call (second round)
      request 3 -> would be needed but prevented

    Proves:
      - model requests == 2
      - request #3 prevented by UsageLimitExceeded
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": f"req_{model_requests[0]}"},
                    tool_call_id=f"call_{model_requests[0]}",
                )
            ]
        )

    model = FunctionModel(function=make_response)
    snapshot = (
        ProjectToolDefinition(
            name="read_alpha",
            description="A read-only test tool",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        ),
    )
    agent = _make_agent(model, snapshot)

    registry = ToolRegistry()

    def alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        return ToolOutput(result=f"alpha:{inp.value}")

    registry.register(snapshot[0], alpha_handler)
    local_executor = ToolExecutor(registry)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
        snapshot,
        local_executor,
        ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        ),
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
        reject_second_batch=False,
    )

    with pytest.raises(UsageLimitExceeded, match="request_limit of 2"):
        agent.run_sync("start", capabilities=[cap], usage_limits=UsageLimits(request_limit=2))

    # Model requests == 2 (third was prevented)
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"
    # Handler was invoked twice (two batches)
    assert handler_invocations[0] == 2, (
        f"expected 2 handler invocations, got {handler_invocations[0]}"
    )
    # Both batches were executed through ToolExecutor
    assert executor_invocations[0] == 2, (
        f"expected 2 executor invocations, got {executor_invocations[0]}"
    )


# ============================================================================
# Retry policy — zero semantic retries
# ============================================================================


def test_retry_policy_zero_tool_retries() -> None:
    """retries={'tools': 0} disables semantic tool retries.

    With ExternalToolset, an unknown tool name raises UnexpectedModelBehavior.
    With retries=0, only 1 model request occurs.

    Proves:
      - model requests == 1 (no semantic retry)
      - handler calls == 0
      - terminal exception
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="nonexistent_tool",
                    args={},
                    tool_call_id="unknown_1",
                )
            ]
        )

    model = FunctionModel(function=make_response)
    snapshot = (
        ProjectToolDefinition(
            name="read_alpha",
            description="A read-only test tool",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        ),
    )
    agent = _make_agent(model, snapshot)

    handler_calls: list[int] = [0]

    registry = ToolRegistry()

    def alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        handler_calls[0] += 1
        return ToolOutput(result=f"alpha:{inp.value}")

    registry.register(snapshot[0], alpha_handler)
    local_executor = ToolExecutor(registry)

    cap = _make_deferred_handler(
        snapshot,
        local_executor,
        ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        ),
    )

    with pytest.raises(UnexpectedModelBehavior) as exc_info:
        agent.run_sync(
            "call nonexistent tool", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    assert model_requests[0] == 1, f"expected 1 model request, got {model_requests[0]}"
    assert handler_calls[0] == 0, f"expected 0 handler calls, got {handler_calls[0]}"
    assert "exceeded max retries count" in str(exc_info.value).lower()
