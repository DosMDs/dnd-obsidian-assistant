"""Pydantic AI run dependencies — context/dependencies integration (PAIM-06).

This module provides the project-owned dependency bundle and preparation
boundary for Pydantic AI agent runs.  It composes already accepted
application components into an immutable run-local dependency container.

Architecture
────────────

::

    DndAgentRunPreparer.prepare(user_input, execution_context=...)
        │
        ├── 1. validate ExecutionContext runtime type
        ├── 2. AgentContextBuilder.build(user_input)
        ├── 3. select_agent_tools(tool_catalog, context=execution_context)
        ├── 4. PydanticAIToolBridge.freeze(selected)
        ├── 5. construct fresh DndAgentPolicy
        ├── 6. construct DndAgentDeps
        └── 7. return PreparedDndAgentRun

The preparation is **read-only** — zero tool handlers, zero model calls,
zero framework objects.

Ownership
─────────

Owned here:
    DndAgentDeps — frozen run-local dependency bundle.
    PreparedDndAgentRun — prepared run with deps and exposed tool defs.
    DndAgentRunPreparer — deterministic preparation orchestration.

Owned elsewhere (unchanged):
    AgentContextBuilder — sole campaign-context preparation boundary.
    select_agent_tools — deterministic tool exposure policy.
    PydanticAIToolBridge — bridge, snapshot, execution adapter.
    DndAgentPolicy — batch-admission policy.

This module must not import from:
    dnd_assistant.models, dnd_assistant.models.ollama, dnd_assistant.storage,
    dnd_assistant.retrieval, dnd_assistant.cli.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd_assistant.application.agent_context import AgentContext, AgentContextBuilder
    from dnd_assistant.application.dnd_agent_policy import DndAgentPolicy
    from dnd_assistant.application.pydantic_ai_tool_bridge import (
        PydanticAIToolBridge,
        PydanticAIToolSnapshot,
    )
    from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext


# ── Run dependency bundle ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True, eq=False)
class DndAgentDeps:
    """Frozen run-local dependency bundle for one Pydantic AI agent run.

    This is a **capability container**, not a serialisable DTO.  It bundles
    the prepared application data and trusted adapters that project callbacks
    need during a framework run.

    ``eq=False`` ensures identity semantics — two independently prepared runs
    with equivalent visible data are not equal.

    .. important::

        ``DndAgentDeps`` is **frozen** at the top level only.  The contained
        ``DndAgentPolicy`` has intentionally mutable run-local state
        (``_batch_observed``).  This is by design.

    Fields:
        agent_context: Immutable application-prepared campaign context.
        execution_context: Trusted Python execution context for this run.
        tool_bridge: The ``PydanticAIToolBridge`` that issued the snapshot.
        tool_snapshot: The issued immutable tool snapshot for this run.
        policy: One fresh ``DndAgentPolicy`` bound to this run's snapshot.
    """

    agent_context: AgentContext
    execution_context: ExecutionContext
    tool_bridge: PydanticAIToolBridge
    tool_snapshot: PydanticAIToolSnapshot
    policy: DndAgentPolicy

    def __post_init__(self) -> None:
        """Validate that the policy is bound to the exact snapshot in this bundle."""
        # Deferred import to avoid eager loading of DndAgentPolicy at module scope.
        from dnd_assistant.application.dnd_agent_policy import DndAgentPolicy as DAP

        if not isinstance(self.policy, DAP):
            raise TypeError("policy must be a DndAgentPolicy instance")


# ── Prepared run ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True, eq=False)
class PreparedDndAgentRun:
    """Result of a successful preparation — deps and exposed tool definitions.

    ``eq=False`` ensures identity semantics — each prepared run is distinct.

    Fields:
        deps: The ``DndAgentDeps`` bundle for this run.
        exposed_tools: Tuple of ``ToolPublicDefinition`` values in exposure
            order.  Retained for later PAIM-07 observable-contract parity.
            These are **not** execution authority — the ``tool_snapshot`` inside
            ``deps`` is the authoritative source.
    """

    deps: DndAgentDeps
    exposed_tools: tuple[ToolPublicDefinition, ...]


# ── Preparer ───────────────────────────────────────────────────────────────────


class DndAgentRunPreparer:
    """Deterministic pre-model preparation for one Pydantic AI agent run.

    Composes already accepted application components into an immutable
    ``PreparedDndAgentRun``.  Performs zero tool execution and zero model
    calls.

    Args:
        context_builder: The ``AgentContextBuilder`` for campaign-context
            preparation.
        tool_catalog: The ``ToolRegistrySchema`` for tool exposure selection.
        tool_bridge: The ``PydanticAIToolBridge`` for snapshot creation.

    Raises:
        TypeError: If any constructor argument has a malformed runtime type.
    """

    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        tool_catalog: ToolRegistrySchema,
        tool_bridge: PydanticAIToolBridge,
    ) -> None:
        # Deferred runtime imports: keep tool/storage/retrieval packages out
        # of module-import scope.
        from dnd_assistant.application.agent_context import AgentContextBuilder as ACB
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge as PTB,
        )
        from dnd_assistant.tools.catalog import ToolRegistrySchema as TRS

        if not isinstance(context_builder, ACB):
            raise TypeError(
                f"context_builder must be an AgentContextBuilder instance, "
                f"got {type(context_builder).__name__}"
            )
        if not isinstance(tool_catalog, TRS):
            raise TypeError(
                f"tool_catalog must be a ToolRegistrySchema instance, "
                f"got {type(tool_catalog).__name__}"
            )
        if not isinstance(tool_bridge, PTB):
            raise TypeError(
                f"tool_bridge must be a PydanticAIToolBridge instance, "
                f"got {type(tool_bridge).__name__}"
            )

        self._context_builder = context_builder
        self._tool_catalog = tool_catalog
        self._tool_bridge = tool_bridge

    def prepare(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> PreparedDndAgentRun:
        """Prepare one Pydantic AI agent run.

        Deterministic ordered flow:

        1. Validate ``execution_context`` runtime type.
        2. Build ``AgentContext`` via ``AgentContextBuilder.build()``.
        3. Select eligible tools via ``select_agent_tools()``.
        4. Freeze selected exposure through ``PydanticAIToolBridge.freeze()``.
        5. Construct one fresh ``DndAgentPolicy`` for this run.
        6. Construct ``DndAgentDeps``.
        7. Return ``PreparedDndAgentRun``.

        Args:
            user_input: The validated user query string.
            execution_context: Trusted Python execution context for tool
                exposure filtering.

        Returns:
            An immutable ``PreparedDndAgentRun``.

        Raises:
            ValidationError: If ``execution_context`` is malformed or
                ``user_input`` is invalid (propagated from
                ``AgentContextBuilder``).
            TypeError: If ``execution_context`` is not an
                ``ExecutionContext`` instance (raised before any context
                reads).
        """
        # Deferred runtime imports: keep provider/tool/storage packages out
        # of module-import scope.
        from dnd_assistant.application.agent_tool_selection import select_agent_tools
        from dnd_assistant.application.dnd_agent_policy import DndAgentPolicy
        from dnd_assistant.tools.types import ExecutionContext as EC

        # 1. Validate ExecutionContext runtime type (fail before context reads)
        if not isinstance(execution_context, EC):
            raise TypeError(
                f"execution_context must be an ExecutionContext instance, "
                f"got {type(execution_context).__name__}"
            )

        # 2. Build AgentContext (validates user_input internally)
        agent_context = self._context_builder.build(user_input)

        # 3. Select eligible tools
        selected = select_agent_tools(
            self._tool_catalog,
            context=execution_context,
        )
        exposed_tools = tuple(selected)

        # 4. Freeze selected exposure through bridge
        tool_snapshot = self._tool_bridge.freeze(exposed_tools)

        # 5. Construct one fresh DndAgentPolicy for this run
        policy = DndAgentPolicy(
            tool_bridge=self._tool_bridge,
            snapshot=tool_snapshot,
        )

        # 6. Construct DndAgentDeps
        deps = DndAgentDeps(
            agent_context=agent_context,
            execution_context=execution_context,
            tool_bridge=self._tool_bridge,
            tool_snapshot=tool_snapshot,
            policy=policy,
        )

        # 7. Return PreparedDndAgentRun
        return PreparedDndAgentRun(
            deps=deps,
            exposed_tools=exposed_tools,
        )
