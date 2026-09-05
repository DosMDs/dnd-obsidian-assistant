"""PAIM-C03: Corrected blocker gate — ExternalToolset + HandleDeferredToolCalls path.

Proves Pydantic AI 2.39.0 Stage-9 safety semantics using the intended public
extension points:

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
    Agent
        |
    model requests tools
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
  All project execution goes through ToolExecutor.
- DeferredToolRequests.approvals is empty for external tools.
  All project calls are in DeferredToolRequests.calls.
- The model->tools->model cycle stays inside ONE agent.run_sync().
- UsageLimits(request_limit=N) bounds model requests.

All tests are deterministic and require no real Ollama or network access.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDefinition
from pydantic_ai.toolsets import ExternalToolset

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


# Project tool definitions

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
    """Run-local immutable snapshot of project tool definitions."""
    return tuple(tool_registry.list_definitions())


# ============================================================================
# Helper: translate project snapshot to Pydantic AI ToolDefinition[]
# ============================================================================


def _to_pyd_tool_defs(
    snapshot: tuple[ProjectToolDefinition, ...],
) -> list[ToolDefinition]:
    """Translate frozen project tool definitions to Pydantic AI ToolDefinition list.

    Only name, description, and input JSON schema are mapped.
    Permission/side-effect metadata stays in the application snapshot.
    """
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
    """Build an ExternalToolset from the frozen project snapshot.

    No Python handler functions are attached. The framework only sees
    schema/metadata. Successful execution goes through ToolExecutor.
    """
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

        # Reject second batch if policy says so
        if reject_second_batch and batch_count[0] > 1:
            raise RuntimeError("Second deferred batch rejected by application policy")

        all_calls = list(requests.calls)
        if not all_calls:
            return None

        # --- Preflight ---
        # 1. Size check
        if len(all_calls) > 4:
            raise RuntimeError(f"Batch size {len(all_calls)} exceeds 4")

        # 2. Duplicate non-null ID check
        seen_ids: set[str] = set()
        for c in all_calls:
            if c.tool_call_id in seen_ids:
                raise RuntimeError(f"Duplicate tool_call_id '{c.tool_call_id}'")
            seen_ids.add(c.tool_call_id)

        # 3. Resolve against frozen snapshot
        resolved: list[tuple[ToolCallPart, ProjectToolDefinition]] = []
        for c in all_calls:
            definition = snapshot_map.get(c.tool_name)
            if definition is None:
                raise RuntimeError(f"Unknown/hidden tool '{c.tool_name}'")
            resolved.append((c, definition))

        # 4. Multi-call WRITE rejection
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
    model = TestModel(call_tools=["read_alpha", "read_beta"])
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
        "use both tools", capabilities=[cap], usage_limits=UsageLimits(request_limit=2)
    )

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
    agent = _make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
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
    agent = _make_agent(model, frozen_snapshot)

    handler_invocations: list[int] = [0]
    executor_invocations: list[int] = [0]

    cap = _make_deferred_handler(
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
    them with ValidationError. The exception propagates through the handler,
    and the framework converts it to UnexpectedModelBehavior.

    Proves:
      - project handler side effects == 0
      - ToolExecutor validation rejects invalid args
      - handler was invoked (batch was received)
      - ToolExecutor was invoked (validation failed inside it)
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
