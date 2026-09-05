"""PAIM-C03: Corrected blocker execution — ExternalToolset + HandleDeferredToolCalls.

Tests BG-09 through BG-12 plus missing-ID behavior using the intended
public extension points.

All tests are deterministic and require no real Ollama or network access.

Shared test infrastructure is imported from tests.support.pydantic_ai_runtime.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import RunContext, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from dnd_assistant.errors import ConflictError
from dnd_assistant.errors import ValidationError as ProjectValidationError
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
)
from dnd_assistant.tools.types import (
    ToolDefinition as ProjectToolDefinition,
)
from tests.support.pydantic_ai_runtime import (
    HandlerCounters,
    make_agent,
    make_deferred_handler,
    make_frozen_snapshot,
    make_handler_counters,
    make_read_context,
    make_tool_executor,
    make_tool_registry,
    make_write_context,
    make_write_context_no_audit,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def counters() -> HandlerCounters:
    return make_handler_counters()


@pytest.fixture
def tool_registry(counters: HandlerCounters) -> ToolRegistry:
    return make_tool_registry(counters)


@pytest.fixture
def executor(tool_registry: ToolRegistry) -> ToolExecutor:
    return make_tool_executor(tool_registry)


@pytest.fixture
def read_ctx() -> ExecutionContext:
    return make_read_context()


@pytest.fixture
def write_ctx() -> ExecutionContext:
    return make_write_context()


@pytest.fixture
def write_ctx_no_audit() -> ExecutionContext:
    return make_write_context_no_audit()


@pytest.fixture
def frozen_snapshot(
    tool_registry: ToolRegistry,
) -> tuple[ProjectToolDefinition, ...]:
    return make_frozen_snapshot(tool_registry)


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
      - model requests == 2 (model -> tools -> model)
      - HandleDeferredToolCalls handler invokes ToolExecutor exactly once
      - project READ handler executes exactly once
      - result returns to model
      - terminal second model response
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        if model_requests[0] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "bg09"},
                        tool_call_id="call_bg09",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="read accepted")])

    model = FunctionModel(function=make_response)
    agent = make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = make_deferred_handler(
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

    # Model requests == 2
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"
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
# BG-10 — Single WRITE through ToolExecutor
# ============================================================================


def test_bg10_single_write_through_executor(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx: ExecutionContext,
) -> None:
    """One valid WRITE call with proper permission, session mode, and audit.

    Uses ExternalToolset + HandleDeferredToolCalls + ToolExecutor.
    No @agent.tool or @agent.tool_plain decorator exists — all execution
    goes through ToolExecutor.

    Proves:
      - model requests == 2 (model -> tools -> model)
      - deferred handler invocations == 1
      - ToolExecutor invocations == 1
      - WRITE project handler invocations == 1
      - terminal result is produced
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        if model_requests[0] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_alpha",
                        args={"value": "bg10"},
                        tool_call_id="write_bg10",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="write accepted")])

    model = FunctionModel(function=make_response)
    agent = make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = make_deferred_handler(
        frozen_snapshot,
        executor,
        write_ctx,
        counters=counters,
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    result = agent.run_sync(
        "use write_alpha", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
    )

    # Model requests == 2 (model -> tools -> model)
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"
    # Handler invocations == 1
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # ToolExecutor invocations == 1
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    # WRITE project handler invocations == 1
    assert counters.write_alpha == 1, f"expected 1 write_alpha call, got {counters.write_alpha}"
    # Terminal result is a string
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
    agent = make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = make_deferred_handler(
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
    agent = make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = make_deferred_handler(
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
    agent = make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = make_deferred_handler(
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
# Missing tool-call ID behavior
# ============================================================================


def test_missing_tool_call_ids(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Model emits ToolCallParts without explicit tool_call_id.

    Pydantic AI 2.39.0 auto-assigns unique IDs when tool_call_id is omitted
    from the constructor. When explicitly set to None, None is preserved.

    This test proves:
      - IDs omitted from model response: framework auto-assigns non-empty IDs
      - IDs reaching deferred handler are non-empty and unique
      - Application preflight accepts the batch (no duplicate-ID rejection)
      - Batch completes through ToolExecutor
    """
    # Use FunctionModel that emits ToolCallParts WITHOUT explicit tool_call_id
    model_requests: list[int] = [0]
    observed_ids: list[str | None] = []

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        if model_requests[0] == 1:
            return ModelResponse(
                parts=[
                    # No tool_call_id supplied — framework auto-assigns
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "first"},
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"number": 42},
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    model = FunctionModel(function=make_response)
    agent = make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    # Capture IDs inside the deferred handler before execution
    def capturing_handler(
        snapshot: tuple[ProjectToolDefinition, ...],
        executor: ToolExecutor,
        context: ExecutionContext,
        *,
        counters: HandlerCounters | None = None,
        handler_invocations: list[int] | None = None,
        executor_invocations: list[int] | None = None,
    ) -> HandleDeferredToolCalls:
        snapshot_map: dict[str, ProjectToolDefinition] = {d.name: d for d in snapshot}
        batch_count: list[int] = [0]

        def _handler(ctx: RunContext, requests: DeferredToolRequests) -> DeferredToolResults | None:
            nonlocal batch_count
            batch_count[0] += 1

            if handler_invocations is not None:
                handler_invocations[0] += 1

            all_calls = list(requests.calls)
            if not all_calls:
                return None

            # Capture IDs
            for c in all_calls:
                observed_ids.append(c.tool_call_id)

            # --- Preflight ---
            seen_ids: set[str] = set()
            for c in all_calls:
                if c.tool_call_id is not None:
                    if c.tool_call_id in seen_ids:
                        raise RuntimeError(f"Duplicate tool_call_id '{c.tool_call_id}'")
                    seen_ids.add(c.tool_call_id)

            resolved: list[tuple[ToolCallPart, ProjectToolDefinition]] = []
            for c in all_calls:
                definition = snapshot_map.get(c.tool_name)
                if definition is None:
                    raise RuntimeError(f"Unknown/hidden tool '{c.tool_name}'")
                resolved.append((c, definition))

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

    cap = capturing_handler(
        frozen_snapshot,
        executor,
        read_ctx,
        counters=counters,
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    result = agent.run_sync(
        "use tools without ids", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
    )

    # Model requests == 2
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"
    # Handler was invoked once
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # Two IDs were captured
    assert len(observed_ids) == 2, f"expected 2 observed IDs, got {len(observed_ids)}"
    # Both IDs are non-empty strings
    for i, oid in enumerate(observed_ids):
        assert isinstance(oid, str) and len(oid) > 0, (
            f"observed_id[{i}] is not a non-empty string: {oid!r}"
        )
    # IDs are unique
    assert observed_ids[0] != observed_ids[1], (
        f"expected unique IDs, got {observed_ids[0]} == {observed_ids[1]}"
    )
    # No None reached the handler
    assert all(oid is not None for oid in observed_ids), (
        f"None ID observed in handler: {observed_ids}"
    )
    # ToolExecutor was invoked for both calls
    assert executor_invocations[0] == 2, (
        f"expected 2 executor invocations, got {executor_invocations[0]}"
    )
    # Both handlers executed
    assert counters.alpha == 1, f"expected 1 alpha call, got {counters.alpha}"
    assert counters.beta == 1, f"expected 1 beta call, got {counters.beta}"
    # Terminal result
    assert isinstance(result.output, str), (
        f"expected str output, got {type(result.output).__name__}"
    )
