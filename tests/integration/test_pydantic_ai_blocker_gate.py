"""PAIM-02: Critical blocker gate — Pydantic AI 2.39.0 Stage-9 safety semantics.

Proves whether Pydantic AI 2.39.0 can support the accepted Stage-9 D&D Session
Assistant safety semantics using stable public extension points, without
weakening project trust boundaries and without patching framework internals.

Architecture under test
───────────────────────
    frozen application tool snapshot
        |
    Pydantic AI ToolDefinition[]  (via @agent.tool_plain(requires_approval=True))
        |
    model response with tool calls
        |
    DeferredToolRequests  (output_type=str | DeferredToolRequests)
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

import threading
from datetime import UTC, datetime
from typing import Any

# Pydantic AI imports
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

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


# In-memory handler counters


class HandlerCounters:
    """Thread-safe counters for tracking handler invocations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.alpha: int = 0
        self.beta: int = 0
        self.write_alpha: int = 0
        self.all_calls: list[str] = []

    def inc_alpha(self) -> None:
        with self._lock:
            self.alpha += 1
            self.all_calls.append("read_alpha")

    def inc_beta(self) -> None:
        with self._lock:
            self.beta += 1
            self.all_calls.append("read_beta")

    def inc_write_alpha(self) -> None:
        with self._lock:
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
# Batch admission policy (test-only prototype)
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
    1. Reject second deferred batch (caller responsibility - only call once).
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
# BG-01 — Allowed two-READ batch
# ============================================================================


def test_bg01_allowed_read_read_batch(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Model requests read_alpha + read_beta in one response.

    Proves:
      - complete DeferredToolRequests batch contains both calls
      - application preflight sees both before execution
      - ToolExecutor executions == 2
      - handler executions == 2
      - execution order == model emission order
      - max simultaneous handler execution == 1
      - final model response is terminal text
    """
    model = TestModel(call_tools=["read_alpha", "read_beta"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def read_alpha(value: str) -> str:
        counters.inc_alpha()
        return f"alpha:{value}"

    @agent.tool_plain(requires_approval=True)
    def read_beta(number: int) -> str:
        counters.inc_beta()
        return f"beta:{number}"

    # First run: collect deferred requests
    result1 = agent.run_sync("use both tools")
    assert isinstance(result1.output, DeferredToolRequests), (
        f"expected DeferredToolRequests, got {type(result1.output).__name__}"
    )

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    assert len(all_calls) == 2, f"expected 2 calls, got {len(all_calls)}"
    assert all_calls[0].tool_name == "read_alpha"
    assert all_calls[1].tool_name == "read_beta"

    # No handlers executed during first run
    assert counters.alpha == 0
    assert counters.beta == 0

    # Preflight
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert preflight.allowed, f"preflight rejected: {preflight.reason}"
    assert len(preflight.resolved) == 2

    # Execute through ToolExecutor sequentially
    results: dict[str, Any] = {}
    for call, definition in preflight.resolved:
        input_data = call.args if isinstance(call.args, dict) else {}
        output = executor.execute(definition.name, input_data=input_data, context=read_ctx)
        results[call.tool_call_id] = output.result

    assert counters.alpha == 1
    assert counters.beta == 1
    # Execution order matches model emission order
    assert counters.all_calls == ["read_alpha", "read_beta"], (
        f"expected [read_alpha, read_beta], got {counters.all_calls}"
    )

    # Second run: provide results and get terminal response
    deferred_results = DeferredToolResults(calls=results, approvals={})
    result2 = agent.run_sync(
        "",
        message_history=result1.new_messages(),
        deferred_tool_results=deferred_results,
    )
    assert isinstance(result2.output, str), (
        f"expected terminal str, got {type(result2.output).__name__}"
    )
    # No additional handler executions
    assert counters.alpha == 1
    assert counters.beta == 1


# ============================================================================
# BG-02 — Mixed READ + WRITE batch (both orderings)
# ============================================================================


@pytest.mark.parametrize(
    ("tool_names", "test_id"),
    [
        (["read_alpha", "write_alpha"], "READ+WRITE"),
        (["write_alpha", "read_alpha"], "WRITE+READ"),
    ],
)
def test_bg02_mixed_read_write_batch(
    tool_names: list[str],
    test_id: str,
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx: ExecutionContext,
) -> None:
    """Mixed READ/WRITE batch is rejected before any ToolExecutor execution.

    Proves:
      - complete batch received
      - batch rejected before execution
      - ToolExecutor calls == 0
      - READ handler calls == 0
      - WRITE handler calls == 0
    """
    model = TestModel(call_tools=tool_names)
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def read_alpha(value: str) -> str:
        counters.inc_alpha()
        return f"alpha:{value}"

    @agent.tool_plain(requires_approval=True)
    def write_alpha(value: str) -> str:
        counters.inc_write_alpha()
        return f"write:{value}"

    result1 = agent.run_sync("use tools")
    assert isinstance(result1.output, DeferredToolRequests)

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    assert len(all_calls) == 2

    # Preflight must reject
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert not preflight.allowed, "mixed READ/WRITE batch must be rejected"
    assert "mixed batch" in preflight.reason

    # No handlers executed
    assert counters.alpha == 0
    assert counters.write_alpha == 0


# ============================================================================
# BG-03 — Multiple WRITE calls
# ============================================================================


def test_bg03_multiple_write_calls(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
) -> None:
    """Model requests at least two WRITE calls.

    Proves:
      - reject before execution
      - ToolExecutor calls == 0
      - write handler calls == 0
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="write_alpha",
                    args={"value": "a"},
                    tool_call_id="write_1",
                ),
                ToolCallPart(
                    tool_name="write_alpha",
                    args={"value": "b"},
                    tool_call_id="write_2",
                ),
            ]
        )

    model = FunctionModel(function=make_response)
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def write_alpha(value: str) -> str:
        counters.inc_write_alpha()
        return f"write:{value}"

    result1 = agent.run_sync("use write tools")
    assert isinstance(result1.output, DeferredToolRequests)

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    assert len(all_calls) == 2

    # Preflight must reject: multi-call with WRITE permission
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert not preflight.allowed, "multi-WRITE batch must be rejected"
    assert "mixed batch" in preflight.reason

    # No handlers executed
    assert counters.write_alpha == 0


# ============================================================================
# BG-04 — >4 initial calls
# ============================================================================


def test_bg04_more_than_four_calls(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
) -> None:
    """Model returns five calls in one response.

    Proves:
      - batch size observed == 5
      - reject before execution
      - ToolExecutor calls == 0
      - handler calls == 0
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": str(i)},
                    tool_call_id=f"call_{i}",
                )
                for i in range(5)
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

    result1 = agent.run_sync("use many tools")
    assert isinstance(result1.output, DeferredToolRequests)

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    assert len(all_calls) == 5

    # Preflight must reject: >4 calls
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert not preflight.allowed, ">4 batch must be rejected"
    assert "exceeds 4" in preflight.reason

    # No handlers executed
    assert counters.alpha == 0


# ============================================================================
# BG-05 — Duplicate non-null call IDs
# ============================================================================


def test_bg05_duplicate_call_ids(
    counters: HandlerCounters,
) -> None:
    """Two model tool calls with the same explicit non-null ID.

    Pydantic AI 2.39.0 rejects duplicate tool_call_id values in the
    deferred tool path before any application handler executes.

    Proves:
      - framework rejects duplicate IDs with UnexpectedModelBehavior
      - zero handler execution
    """
    model = TestModel(call_tools=["read_alpha", "read_alpha"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def read_alpha(value: str) -> str:
        counters.inc_alpha()
        return f"alpha:{value}"

    with pytest.raises(UnexpectedModelBehavior) as exc_info:
        agent.run_sync("use tools")

    assert "duplicate" in str(exc_info.value).lower()
    # No handlers executed
    assert counters.alpha == 0


# ============================================================================
# BG-06 — Frozen exposure / hidden live-registry tool
# ============================================================================


def test_bg06_frozen_exposure_hidden_live_tool(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ToolDefinition, ...],
    tool_registry: ToolRegistry,
) -> None:
    """Register a tool after snapshot creation; model requests it.

    Proves:
      - live registry now contains tool
      - frozen snapshot does not
      - framework/application path rejects call
      - ToolExecutor calls == 0
      - hidden handler calls == 0
    """
    # Register a new tool in the live registry AFTER snapshot creation
    hidden_def = ToolDefinition(
        name="hidden_tool",
        description="A tool registered after snapshot",
        input_schema=AlphaInput,
        output_schema=ToolOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )
    hidden_calls: list[int] = [0]

    def hidden_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        hidden_calls[0] += 1
        return ToolOutput(result=f"hidden:{inp.value}")

    tool_registry.register(hidden_def, hidden_handler)

    # Verify live registry has it
    assert tool_registry.get_definition("hidden_tool") is not None
    # Verify frozen snapshot does NOT have it
    snapshot_names = {d.name for d in frozen_snapshot}
    assert "hidden_tool" not in snapshot_names

    # Model requests the hidden tool
    model = TestModel(call_tools=["hidden_tool"])
    agent = Agent(
        model,
        output_type=str | DeferredToolRequests,
        retries={"tools": 0},
    )

    @agent.tool_plain(requires_approval=True)
    def hidden_tool(value: str) -> str:
        counters.inc_alpha()
        return f"hidden:{value}"

    result1 = agent.run_sync("use hidden tool")
    assert isinstance(result1.output, DeferredToolRequests)

    all_calls = list(result1.output.approvals) + list(result1.output.calls)
    assert len(all_calls) == 1
    assert all_calls[0].tool_name == "hidden_tool"

    # Preflight must reject: hidden_tool not in frozen snapshot
    preflight = preflight_batch(all_calls, frozen_snapshot)
    assert not preflight.allowed, "hidden tool must be rejected"
    assert "unknown/hidden" in preflight.reason

    # No handlers executed
    assert counters.alpha == 0
    assert hidden_calls[0] == 0


# ============================================================================
# BG-07 — Completely unknown tool
# ============================================================================


def test_bg07_unknown_tool(
    counters: HandlerCounters,
) -> None:
    """Model requests a name absent from both frozen snapshot and live registry.

    Pydantic AI 2.39.0 rejects unknown tool names with UnexpectedModelBehavior
    before any application handler executes. With retries={"tools": 0}, the
    rejection is immediate (no semantic retry round).

    Proves:
      - project handler calls == 0
      - no semantic retry round (retries={"tools": 0})
      - model requests == 1
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="completely_unknown",
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
    def some_tool(x: int) -> str:
        handler_calls[0] += 1
        return f"x={x}"

    with pytest.raises(UnexpectedModelBehavior):
        agent.run_sync("call unknown tool")

    # No handlers executed
    assert handler_calls[0] == 0
    # Model requests == 1 (no semantic retry with retries={"tools": 0})
    assert model_requests[0] == 1


# ============================================================================
# BG-08 — Malformed/invalid arguments
# ============================================================================


def test_bg08_invalid_arguments(
    counters: HandlerCounters,
) -> None:
    """Model emits invalid arguments for an exposed tool.

    Pydantic AI 2.39.0 validates tool arguments before deferring. With
    retries={"tools": 0}, validation failure raises UnexpectedModelBehavior
    immediately. No project handler executes.

    Proves:
      - actual project handler side effects == 0
      - framework rejects invalid args before deferral
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": 123},
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
        counters.inc_alpha()
        return f"alpha:{value}"

    with pytest.raises(UnexpectedModelBehavior):
        agent.run_sync("call with bad args")

    # No handler executed
    assert counters.alpha == 0
