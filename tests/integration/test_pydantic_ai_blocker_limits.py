"""PAIM-C04: Request-limit and retry-policy evidence.

Tests the whole-turn request budget and zero-retry policy using the
ExternalToolset + HandleDeferredToolCalls architecture.

All tests are deterministic and require no real Ollama or network access.

Shared test infrastructure is imported from tests.support.pydantic_ai_runtime.
"""

from __future__ import annotations

import pytest
from pydantic_ai import UnexpectedModelBehavior, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

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
    ToolOutput,
    make_agent,
    make_deferred_handler,
)

# ============================================================================
# Whole-turn model request limit — defense in depth
# ============================================================================


def test_request_limit_defense_in_depth() -> None:
    """UsageLimits(request_limit=2) allows model->tools->model cycle.

    With HandleDeferredToolCalls, the complete model->tools->model cycle
    stays inside one agent.run_sync(). UsageLimits(request_limit=2) allows
    exactly 2 model requests — no UsageLimitExceeded raised.

    Proves:
      - model requests == 2 with request_limit=2
      - no UsageLimitExceeded
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
    agent = make_agent(model, snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    registry = ToolRegistry()

    def alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        return ToolOutput(result=f"alpha:{inp.value}")

    registry.register(snapshot[0], alpha_handler)
    local_executor = ToolExecutor(registry)

    cap = make_deferred_handler(
        snapshot,
        local_executor,
        ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        ),
        handler_invocations=handler_invocations,
        executor_invocations=executor_invocations,
    )

    result = agent.run_sync("start", capabilities=[cap], usage_limits=UsageLimits(request_limit=2))

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
    agent = make_agent(model, snapshot)

    registry = ToolRegistry()

    def alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        return ToolOutput(result=f"alpha:{inp.value}")

    registry.register(snapshot[0], alpha_handler)
    local_executor = ToolExecutor(registry)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = make_deferred_handler(
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
    agent = make_agent(model, snapshot)

    handler_calls: list[int] = [0]

    registry = ToolRegistry()

    def alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
        handler_calls[0] += 1
        return ToolOutput(result=f"alpha:{inp.value}")

    registry.register(snapshot[0], alpha_handler)
    local_executor = ToolExecutor(registry)

    cap = make_deferred_handler(
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
