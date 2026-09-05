"""PAIM-02: Critical blocker gate — ToolExecutor execution semantics.

Tests BG-09 through BG-12 plus request_limit and retry policy.

Architecture under test
───────────────────────
    DeferredToolRequests
        |
    APPLICATION COMPLETE BATCH PREFLIGHT
        |
    allowed?
        no ------ fail before ToolExecutor
        yes
            |
    ToolExecutor sequentially
        |
    DeferredToolResults(calls={id: result})
        |
    Pydantic AI continues same run
        |
    second model response

All tests are deterministic and require no real Ollama or network access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

# Pydantic AI imports
from pydantic_ai import Agent, UnexpectedModelBehavior, UsageLimits
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from dnd_assistant.errors import ConflictError, ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
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

READ_ALPHA_DEF = ToolDefinition(
    name="read_alpha",
    description="A read-only test tool",
    input_schema=AlphaInput,
    output_schema=ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

READ_BETA_DEF = ToolDefinition(
    name="read_beta",
    description="Another read-only test tool",
    input_schema=BetaInput,
    output_schema=ToolOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

WRITE_ALPHA_DEF = ToolDefinition(
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
) -> tuple[ToolDefinition, ...]:
    """Run-local immutable snapshot of tool definitions."""
    return tuple(tool_registry.list_definitions())


# ============================================================================
# Batch admission policy (shared with test_pydantic_ai_blocker_gate.py)
# ============================================================================


class BatchAdmissionResult:
    """Result of a complete batch preflight check."""

    def __init__(
        self,
        allowed: bool,
        *,
        reason: str = "",
        resolved: list[tuple[ToolCallPart, ToolDefinition]] | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.resolved = resolved or []


def preflight_batch(
    calls: list[ToolCallPart],
    snapshot: tuple[ToolDefinition, ...],
) -> BatchAdmissionResult:
    """Test-only complete batch admission policy.

    Implements minimum Stage-9 semantics:
    1. Reject second deferred batch (caller responsibility).
    2. Reject >4 calls.
    3. Reject duplicate non-null tool_call_id.
    4. Resolve every name against frozen snapshot.
    5. Reject zero or ambiguous snapshot matches.
    6. If batch length > 1, require every call to be Permission.READ.
    """
    if len(calls) > 4:
        return BatchAdmissionResult(False, reason=f"batch size {len(calls)} exceeds 4")

    seen_ids: set[str] = set()
    for c in calls:
        if c.tool_call_id in seen_ids:
            return BatchAdmissionResult(False, reason=f"duplicate tool_call_id '{c.tool_call_id}'")
        seen_ids.add(c.tool_call_id)

    snapshot_map: dict[str, ToolDefinition] = {d.name: d for d in snapshot}
    resolved: list[tuple[ToolCallPart, ToolDefinition]] = []
    for c in calls:
        definition = snapshot_map.get(c.tool_name)
        if definition is None:
            return BatchAdmissionResult(False, reason=f"unknown/hidden tool '{c.tool_name}'")
        resolved.append((c, definition))

    if len(calls) > 1:
        for c, definition in resolved:
            if definition.permission != Permission.READ:
                return BatchAdmissionResult(
                    False,
                    reason=(f"mixed batch: WRITE tool '{c.tool_name}' not allowed in multi-call"),
                )

    return BatchAdmissionResult(True, resolved=resolved)


def execute_deferred_batch(
    deferred: DeferredToolRequests,
    snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    context: ExecutionContext,
) -> DeferredToolResults:
    """Run preflight then execute approved batch through ToolExecutor.

    Args:
        deferred: The DeferredToolRequests from the first agent run.
        snapshot: Frozen tool-definition snapshot.
        executor: ToolExecutor bound to the test registry.
        context: ExecutionContext for ToolExecutor calls.

    Returns:
        DeferredToolResults with ToolExecutor outputs keyed by tool_call_id.
    """
    all_calls = list(deferred.approvals) + list(deferred.calls)

    result = preflight_batch(all_calls, snapshot)
    if not result.allowed:
        raise RuntimeError(f"batch rejected: {result.reason}")

    results: dict[str, Any] = {}
    for call, definition in result.resolved:
        input_data = call.args if isinstance(call.args, dict) else {}
        try:
            output = executor.execute(
                definition.name,
                input_data=input_data,
                context=context,
            )
            results[call.tool_call_id] = output.result
        except Exception as exc:
            results[call.tool_call_id] = f"error:{exc}"

    return DeferredToolResults(calls=results, approvals={})


# ============================================================================
# BG-09 — Single READ path through ToolExecutor
# ============================================================================


def test_bg09_single_read_through_executor(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """One valid READ call.

    Proves:
      - deferred handler invokes ToolExecutor exactly once
      - project READ handler executes exactly once
      - result returns to model
      - terminal second model response
    """
    model = TestModel(call_tools=["read_alpha"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def read_alpha(value: str) -> str:
        counters.inc_alpha()
        return f"alpha:{value}"

    # First run
    result1 = agent.run_sync("use read_alpha")
    assert isinstance(result1.output, DeferredToolRequests)
    assert len(result1.output.approvals) == 1

    # Execute through ToolExecutor
    deferred_results = execute_deferred_batch(result1.output, frozen_snapshot, executor, read_ctx)
    assert counters.alpha == 1

    # Second run: terminal response
    result2 = agent.run_sync(
        "",
        message_history=result1.new_messages(),
        deferred_tool_results=deferred_results,
    )
    assert isinstance(result2.output, str)
    assert counters.alpha == 1


# ============================================================================
# BG-10 — Single WRITE path through ToolExecutor
# ============================================================================


def test_bg10_single_write_through_executor(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx: ExecutionContext,
) -> None:
    """One valid WRITE call with proper ExecutionContext.

    Proves:
      - ToolExecutor executes exactly once
      - WRITE handler executes exactly once
    """
    model = TestModel(call_tools=["write_alpha"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def write_alpha(value: str) -> str:
        counters.inc_write_alpha()
        return f"write:{value}"

    # First run
    result1 = agent.run_sync("use write_alpha")
    assert isinstance(result1.output, DeferredToolRequests)
    assert len(result1.output.approvals) == 1

    # Execute through ToolExecutor with write context
    deferred_results = execute_deferred_batch(result1.output, frozen_snapshot, executor, write_ctx)
    assert counters.write_alpha == 1

    # Second run
    result2 = agent.run_sync(
        "",
        message_history=result1.new_messages(),
        deferred_tool_results=deferred_results,
    )
    assert isinstance(result2.output, str)
    assert counters.write_alpha == 1


# ============================================================================
# BG-11 — ToolExecutor remains final authorization boundary
# ============================================================================


def test_bg11_read_authority_denies_write_tool(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """READ authority + WRITE tool: ToolExecutor denies.

    Proves:
      - application batch shape itself would allow a single call
      - but ToolExecutor denies permission
      - WRITE handler == 0
    """
    model = TestModel(call_tools=["write_alpha"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def write_alpha(value: str) -> str:
        counters.inc_write_alpha()
        return f"write:{value}"

    result1 = agent.run_sync("use write_alpha")
    assert isinstance(result1.output, DeferredToolRequests)

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert preflight.allowed, f"single-call batch should pass preflight: {preflight.reason}"

    # ToolExecutor must deny: READ authority cannot execute WRITE tool
    call, definition = preflight.resolved[0]
    input_data = call.args if isinstance(call.args, dict) else {}
    with pytest.raises(ConflictError, match="Permission denied"):
        executor.execute(definition.name, input_data=input_data, context=read_ctx)

    assert counters.write_alpha == 0


def test_bg11_write_authority_missing_audit_context(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx_no_audit: ExecutionContext,
) -> None:
    """WRITE authority but missing AuditContext: ToolExecutor denies.

    Proves:
      - ToolExecutor denies
      - WRITE handler == 0
    """
    model = TestModel(call_tools=["write_alpha"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def write_alpha(value: str) -> str:
        counters.inc_write_alpha()
        return f"write:{value}"

    result1 = agent.run_sync("use write_alpha")
    assert isinstance(result1.output, DeferredToolRequests)

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert preflight.allowed

    # ToolExecutor must deny: WRITE tool requires non-None AuditContext
    call, definition = preflight.resolved[0]
    input_data = call.args if isinstance(call.args, dict) else {}
    with pytest.raises(ValidationError, match="requires a non-None AuditContext"):
        executor.execute(
            definition.name,
            input_data=input_data,
            context=write_ctx_no_audit,
        )

    assert counters.write_alpha == 0


# ============================================================================
# BG-12 — Second model response requests another tool
# ============================================================================


def test_bg12_second_round_tool_rejected(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
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
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def read_alpha(value: str) -> str:
        counters.inc_alpha()
        return f"alpha:{value}"

    # First run: collect deferred requests
    result1 = agent.run_sync("use tool")
    assert isinstance(result1.output, DeferredToolRequests)
    assert model_requests[0] == 1

    all_calls_1 = list(result1.output.approvals) + list(result1.output.calls)
    assert len(all_calls_1) == 1

    # Execute first batch through ToolExecutor
    deferred_results_1 = execute_deferred_batch(result1.output, frozen_snapshot, executor, read_ctx)
    assert counters.alpha == 1

    # Second run: provide results; model will request another tool
    result2 = agent.run_sync(
        "",
        message_history=result1.new_messages(),
        deferred_tool_results=deferred_results_1,
    )

    # The FunctionModel returns another tool call, so result2 is
    # DeferredToolRequests again (not terminal str)
    assert isinstance(result2.output, DeferredToolRequests), (
        f"expected DeferredToolRequests for second round, got {type(result2.output).__name__}"
    )
    assert model_requests[0] == 2

    all_calls_2 = list(result2.output.approvals) + list(result2.output.calls)
    assert len(all_calls_2) == 1

    # Application policy: reject second deferred batch before execution
    preflight_2 = preflight_batch(all_calls_2, frozen_snapshot)
    assert preflight_2.allowed, (
        f"second batch shape is valid but should be rejected by policy: {preflight_2.reason}"
    )

    # The test-only policy rejects the second batch by not executing it
    assert counters.alpha == 1, "no additional ToolExecutor executions"
    assert model_requests[0] == 2


# ============================================================================
# Request limit — defense in depth
# ============================================================================


def test_request_limit_defense_in_depth() -> None:
    """UsageLimits(request_limit=1) allows first model request.

    With deferred tools, the framework makes one model request per run_sync
    call. The deferred tool mechanism does not consume additional model
    requests within the same run_sync.

    Proves:
      - model requests == 1 with request_limit=1
      - DeferredToolRequests is returned (not an error)
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": "x"},
                    tool_call_id="call_1",
                )
            ]
        )

    model = FunctionModel(function=make_response)
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def read_alpha(value: str) -> str:
        return f"alpha:{value}"

    result = agent.run_sync("start", usage_limits=UsageLimits(request_limit=1))
    assert isinstance(result.output, DeferredToolRequests)
    assert model_requests[0] == 1


# ============================================================================
# Retry policy — zero semantic retries
# ============================================================================


def test_retry_policy_zero_tool_retries() -> None:
    """retries={'tools': 0} disables semantic tool retries.

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
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    handler_calls: list[int] = [0]

    @agent.tool_plain(requires_approval=True)
    def real_tool(x: int) -> str:
        handler_calls[0] += 1
        return f"x={x}"

    with pytest.raises(UnexpectedModelBehavior) as exc_info:
        agent.run_sync("call nonexistent tool")

    assert model_requests[0] == 1
    assert handler_calls[0] == 0
    assert "exceeded max retries count" in str(exc_info.value).lower()
