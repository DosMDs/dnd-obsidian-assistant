"""Shared test infrastructure for Pydantic AI blocker-gate tests.

Extracts duplicated test helpers from the three blocker-gate modules into
a single opt-in support module.  All state is fresh per call — no module-level
mutable objects are shared across tests.

Exported helpers
────────────────

Schemas (immutable, safe to reuse):
    AlphaInput, BetaInput, ToolOutput

Canonical tool definitions (immutable, safe to reuse):
    READ_ALPHA_DEF, READ_BETA_DEF, WRITE_ALPHA_DEF

Helper functions:
    make_handler_counters() -> HandlerCounters
    make_tool_registry(counters) -> ToolRegistry
    make_tool_executor(registry) -> ToolExecutor
    make_read_context() -> ExecutionContext
    make_write_context() -> ExecutionContext
    make_write_context_no_audit() -> ExecutionContext
    make_frozen_snapshot(registry) -> tuple[ProjectToolDefinition, ...]
    to_pyd_tool_defs(snapshot) -> list[ToolDefinition]
    make_external_toolset(snapshot) -> ExternalToolset
    make_deferred_handler(snapshot, executor, context, ...) -> HandleDeferredToolCalls
    make_agent(model, snapshot) -> Agent

This module is test-only and must not be imported by src/dnd_assistant/.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDefinition
from pydantic_ai.toolsets import ExternalToolset

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
# Immutable schema classes — safe to reuse across tests
# ============================================================================


class AlphaInput(BaseModel):
    value: str


class BetaInput(BaseModel):
    number: int


class ToolOutput(BaseModel):
    result: str


# ============================================================================
# Immutable canonical tool definitions — safe to reuse across tests
# ============================================================================


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
# HandlerCounters — fresh per test
# ============================================================================


class HandlerCounters:
    """Thread-safe counters for tracking handler invocations.

    Each test must create a fresh instance — do not share across tests.
    """

    def __init__(self) -> None:
        import threading

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


# ============================================================================
# Builder functions — each call returns fresh objects
# ============================================================================


def make_handler_counters() -> HandlerCounters:
    """Create a fresh HandlerCounters instance."""
    return HandlerCounters()


def make_tool_registry(counters: HandlerCounters) -> ToolRegistry:
    """Build a fresh ToolRegistry with three tools and in-memory handlers."""
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


def make_tool_executor(tool_registry: ToolRegistry) -> ToolExecutor:
    """Create a fresh ToolExecutor from a registry."""
    return ToolExecutor(tool_registry)


def make_read_context() -> ExecutionContext:
    """Create a READ-only ExecutionContext."""
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


def make_write_context() -> ExecutionContext:
    """Create a WRITE ExecutionContext with valid audit context."""
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
    """Create a WRITE ExecutionContext with audit=None."""
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


def make_frozen_snapshot(
    tool_registry: ToolRegistry,
) -> tuple[ProjectToolDefinition, ...]:
    """Run-local immutable snapshot of project tool definitions."""
    return tuple(tool_registry.list_definitions())


# ============================================================================
# Pydantic AI translation helpers
# ============================================================================


def to_pyd_tool_defs(
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


def make_external_toolset(
    snapshot: tuple[ProjectToolDefinition, ...],
) -> ExternalToolset:
    """Build an ExternalToolset from the frozen project snapshot.

    No Python handler functions are attached. The framework only sees
    schema/metadata. Successful execution goes through ToolExecutor.
    """
    pyd_defs = to_pyd_tool_defs(snapshot)
    return ExternalToolset(pyd_defs)


def make_deferred_handler(
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

    All counters and mutable state are fresh per call (closure-scoped).
    No module-level mutable state is shared.
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
            if c.tool_call_id is not None:
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


def make_agent(
    model: TestModel | FunctionModel,
    snapshot: tuple[ProjectToolDefinition, ...],
) -> Agent:
    """Create a Pydantic AI Agent with ExternalToolset from project snapshot.

    No @agent.tool or @agent.tool_plain decorators are used.
    All project execution goes through ToolExecutor.
    """
    agent = Agent(model, output_type=str, retries={"tools": 0})
    toolset = make_external_toolset(snapshot)

    @agent.toolset
    def _toolset_factory(ctx: RunContext) -> ExternalToolset:
        return toolset

    return agent
