"""PAIM-C04: Request-limit and retry-policy evidence.

Tests the whole-turn request budget and zero-retry policy using the
ExternalToolset + HandleDeferredToolCalls architecture.

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

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDefinition
from pydantic_ai.toolsets import ExternalToolset

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
# Helpers: translate project snapshot to Pydantic AI types
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


def _make_external_toolset(
    snapshot: tuple[ProjectToolDefinition, ...],
) -> ExternalToolset:
    """Build an ExternalToolset from the frozen project snapshot."""
    pyd_defs = _to_pyd_tool_defs(snapshot)
    return ExternalToolset(pyd_defs)


def _make_deferred_handler(
    snapshot: tuple[ProjectToolDefinition, ...],
    executor: ToolExecutor,
    context: ExecutionContext,
    *,
    handler_invocations: list[int] | None = None,
    executor_invocations: list[int] | None = None,
    reject_second_batch: bool = True,
) -> HandleDeferredToolCalls:
    """Create a HandleDeferredToolCalls capability with full Stage-9 safety."""
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


def _make_agent(
    model: FunctionModel,
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
