"""PAIM-C03: Corrected blocker gate — ExternalToolset + HandleDeferredToolCalls path.

Proves Pydantic AI 2.39.0 Stage-9 safety semantics using the intended public
extension points.

All tests are deterministic and require no real Ollama or network access.

Shared test infrastructure is imported from tests.support.pydantic_ai_runtime.
"""

from __future__ import annotations

import pytest
from pydantic_ai import UnexpectedModelBehavior, UsageLimits
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from dnd_assistant.errors import ValidationError as ProjectValidationError
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)
from dnd_assistant.tools.types import (
    ToolDefinition as ProjectToolDefinition,
)
from tests.support.pydantic_ai_runtime import (
    AlphaInput,
    HandlerCounters,
    ToolOutput,
    make_agent,
    make_deferred_handler,
    make_frozen_snapshot,
    make_handler_counters,
    make_read_context,
    make_tool_executor,
    make_tool_registry,
    make_write_context,
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
def frozen_snapshot(
    tool_registry: ToolRegistry,
) -> tuple[ProjectToolDefinition, ...]:
    return make_frozen_snapshot(tool_registry)


# ============================================================================
# BG-01 — Allowed two-READ batch
# ============================================================================


def test_bg01_allowed_read_read_batch(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Model requests read_alpha + read_beta in one response.

    Proves:
      - HandleDeferredToolCalls handler receives complete batch (1 invocation)
      - application preflight sees both before execution
      - ToolExecutor executions == 2
      - project handler executions == 2
      - execution order == model emission order
      - final model response is terminal text
      - model requests == 2 (model -> tools -> model)
      - no @agent.tool Python handler exists
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        if model_requests[0] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "a"},
                        tool_call_id="call_1",
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"number": 42},
                        tool_call_id="call_2",
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="done")])

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
        "use both tools", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
    )

    # Model requests == 2 (model -> tools -> model)
    assert model_requests[0] == 2, f"expected 2 model requests, got {model_requests[0]}"
    # Handler invocations == 1 (complete batch received once)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    assert executor_invocations[0] == 2, (
        f"expected 2 executor invocations, got {executor_invocations[0]}"
    )
    assert counters.alpha == 1, f"expected 1 alpha handler call, got {counters.alpha}"
    assert counters.beta == 1, f"expected 1 beta handler call, got {counters.beta}"
    # Execution order matches model emission order
    assert counters.all_calls == ["read_alpha", "read_beta"], (
        f"expected [read_alpha, read_beta], got {counters.all_calls}"
    )
    # Terminal output is a string
    assert isinstance(result.output, str), (
        f"expected str output, got {type(result.output).__name__}"
    )


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
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx: ExecutionContext,
) -> None:
    """Mixed READ/WRITE batch is rejected before any ToolExecutor execution.

    Proves:
      - complete batch received by handler
      - batch rejected before execution
      - ToolExecutor calls == 0
      - READ handler calls == 0
      - WRITE handler calls == 0
    """
    model = TestModel(call_tools=tool_names)
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

    with pytest.raises(RuntimeError, match="Mixed batch"):
        agent.run_sync("use tools", capabilities=[cap], usage_limits=UsageLimits(request_limit=2))

    # Handler was invoked (batch was received)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # No ToolExecutor executions
    assert executor_invocations[0] == 0, (
        f"expected 0 executor invocations, got {executor_invocations[0]}"
    )
    # No project handlers executed
    assert counters.alpha == 0, f"expected 0 alpha calls, got {counters.alpha}"
    assert counters.write_alpha == 0, f"expected 0 write_alpha calls, got {counters.write_alpha}"


# ============================================================================
# BG-03 — Multiple WRITE calls
# ============================================================================


def test_bg03_multiple_write_calls(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    write_ctx: ExecutionContext,
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

    with pytest.raises(RuntimeError, match="Mixed batch"):
        agent.run_sync(
            "use write tools", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was invoked (batch was received)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # No ToolExecutor executions
    assert executor_invocations[0] == 0, (
        f"expected 0 executor invocations, got {executor_invocations[0]}"
    )
    # No project handlers executed
    assert counters.write_alpha == 0, f"expected 0 write_alpha calls, got {counters.write_alpha}"


# ============================================================================
# BG-04 — >4 initial calls
# ============================================================================


def test_bg04_more_than_four_calls(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
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

    with pytest.raises(RuntimeError, match="exceeds 4"):
        agent.run_sync(
            "use many tools", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was invoked (batch was received)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # No ToolExecutor executions
    assert executor_invocations[0] == 0, (
        f"expected 0 executor invocations, got {executor_invocations[0]}"
    )
    # No project handlers executed
    assert counters.alpha == 0, f"expected 0 alpha calls, got {counters.alpha}"


# ============================================================================
# BG-05 — Duplicate non-null call IDs
# ============================================================================


def test_bg05_duplicate_call_ids(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Two model tool calls with the same explicit non-null ID.

    Pydantic AI 2.39.0 rejects duplicate tool_call_id values before
    deferred handler execution.

    Proves:
      - framework rejects duplicate IDs with UnexpectedModelBehavior
      - zero handler execution
    """
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": "a"},
                    tool_call_id="same_id",
                ),
                ToolCallPart(
                    tool_name="read_alpha",
                    args={"value": "b"},
                    tool_call_id="same_id",
                ),
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

    with pytest.raises(UnexpectedModelBehavior, match="duplicate"):
        agent.run_sync("use tools", capabilities=[cap], usage_limits=UsageLimits(request_limit=2))

    # Handler was NOT invoked (framework rejected before deferral)
    assert handler_invocations[0] == 0, (
        f"expected 0 handler invocations, got {handler_invocations[0]}"
    )
    # No ToolExecutor executions
    assert executor_invocations[0] == 0, (
        f"expected 0 executor invocations, got {executor_invocations[0]}"
    )
    # No project handlers executed
    assert counters.alpha == 0, f"expected 0 alpha calls, got {counters.alpha}"


# ============================================================================
# BG-06 — Frozen exposure / hidden live-registry tool
# ============================================================================


def test_bg06_frozen_exposure_hidden_live_tool(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    tool_registry: ToolRegistry,
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Register a tool after snapshot creation; model requests it.

    Pydantic AI 2.39.0 rejects unknown external tool names before the
    deferred handler executes. The tool name is absent from the ExternalToolset
    definitions, so the framework raises UnexpectedModelBehavior.

    Proves:
      - live registry now contains tool
      - frozen snapshot does not
      - framework rejects call before deferred handler
      - ToolExecutor calls == 0
      - hidden handler calls == 0
    """
    # Register a new tool in the live registry AFTER snapshot creation
    hidden_def = ProjectToolDefinition(
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

    # Use FunctionModel to request hidden_tool
    model_requests: list[int] = [0]

    def make_response(messages: list, agent_info: object) -> ModelResponse:
        model_requests[0] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="hidden_tool",
                    args={"value": "x"},
                    tool_call_id="call_1",
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

    with pytest.raises(UnexpectedModelBehavior, match="exceeded max retries count"):
        agent.run_sync(
            "use hidden tool", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was NOT invoked (framework rejected before deferral)
    assert handler_invocations[0] == 0, (
        f"expected 0 handler invocations, got {handler_invocations[0]}"
    )
    # No ToolExecutor executions
    assert executor_invocations[0] == 0, (
        f"expected 0 executor invocations, got {executor_invocations[0]}"
    )
    # No project handlers executed
    assert counters.alpha == 0, f"expected 0 alpha calls, got {counters.alpha}"
    assert hidden_calls[0] == 0, f"expected 0 hidden handler calls, got {hidden_calls[0]}"


# ============================================================================
# BG-07 — Completely unknown tool
# ============================================================================


def test_bg07_unknown_tool(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
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

    with pytest.raises(UnexpectedModelBehavior, match="exceeded max retries count"):
        agent.run_sync(
            "call unknown tool", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was NOT invoked (framework rejected before deferral)
    assert handler_invocations[0] == 0, (
        f"expected 0 handler invocations, got {handler_invocations[0]}"
    )
    # No ToolExecutor executions
    assert executor_invocations[0] == 0, (
        f"expected 0 executor invocations, got {executor_invocations[0]}"
    )
    # No project handlers executed
    assert counters.alpha == 0, f"expected 0 alpha calls, got {counters.alpha}"
    # Model requests == 1 (no semantic retry with retries={"tools": 0})
    assert model_requests[0] == 1, f"expected 1 model request, got {model_requests[0]}"


# ============================================================================
# BG-08 — Malformed/invalid arguments
# ============================================================================


def test_bg08_invalid_arguments(
    counters: HandlerCounters,
    frozen_snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    read_ctx: ExecutionContext,
) -> None:
    """Model emits invalid arguments for an exposed tool.

    With ExternalToolset, the framework does not validate tool arguments
    against the Pydantic schema. Invalid args reach the deferred handler.
    The handler passes them to ToolExecutor, which validates and rejects
    them with ProjectValidationError. The exception propagates directly
    through the handler — the framework does not convert it.

    Proves:
      - deferred handler receives batch (handler_invocations == 1)
      - ToolExecutor invoked (executor_invocations == 1)
      - project input validation fails
      - project handler NOT invoked (counters.alpha == 0)
      - ProjectValidationError propagates directly
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

    with pytest.raises(ProjectValidationError, match="Input should be a valid string"):
        agent.run_sync(
            "call with bad args", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
        )

    # Handler was invoked (batch was received)
    assert handler_invocations[0] == 1, (
        f"expected 1 handler invocation, got {handler_invocations[0]}"
    )
    # ToolExecutor was invoked (validation failed inside it)
    assert executor_invocations[0] == 1, (
        f"expected 1 executor invocation, got {executor_invocations[0]}"
    )
    # No project handlers executed (ToolExecutor rejected before handler)
    assert counters.alpha == 0, f"expected 0 alpha calls, got {counters.alpha}"
