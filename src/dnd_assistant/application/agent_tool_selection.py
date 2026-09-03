"""Deterministic Fast-Agent tool exposure policy.

This module provides a single public function ``select_agent_tools`` that
filters a provider-neutral ``ToolRegistrySchema`` based on the current
trusted ``ExecutionContext``.

It is a **pre-model defence-in-depth** boundary.  The caller (future
FastAgent orchestration) uses this to determine which tools the model may
see.  ``ToolExecutor`` remains the authoritative execution boundary and
independently enforces permission, session-mode, and audit prerequisites.

This module belongs to ``application/`` because it coordinates accepted
Tool-Layer metadata into the model-orchestration boundary.

Runtime imports are deferred to avoid eagerly loading ``dnd_assistant.tools``
(whose ``__init__.py`` imports ``ToolExecutor``) at module-import time.

A fresh ``import dnd_assistant.application.agent_tool_selection`` must NOT
eagerly load any of:
    dnd_assistant.models
    dnd_assistant.models.ollama
    dnd_assistant.tools.executor
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext, Permission


def select_agent_tools(
    catalog: ToolRegistrySchema,
    *,
    context: ExecutionContext,
) -> list[ToolPublicDefinition]:
    """Filter a tool catalog to the subset eligible for model exposure.

    Eligibility is a deterministic intersection of:

    - **Permission**: ``READ`` authority exposes only ``READ`` tools.
      ``WRITE`` authority exposes both ``READ`` and ``WRITE`` tools.
    - **Session mode**: A tool is eligible only when
      ``context.session_mode`` is in its ``allowed_session_modes``.
    - **WRITE audit prerequisite**: A ``WRITE`` tool is eligible only when
      ``context.audit is not None`` (i.e. the trusted execution context
      can currently execute a write operation).

    The input catalog order is preserved in the returned list.

    Args:
        catalog: Provider-neutral public tool catalog.
        context: Trusted Python execution context.

    Returns:
        A new list of eligible ``ToolPublicDefinition`` values.
        May be empty.  Never ``None``.

    Raises:
        TypeError: If ``catalog`` is not a ``ToolRegistrySchema``.
        TypeError: If ``context`` is not an ``ExecutionContext``.
    """
    # Deferred runtime imports: importing from dnd_assistant.tools initialises
    # the package root, which eagerly loads ToolExecutor.  Keep these inside
    # the function body so that a fresh module import does not pull in the
    # entire Tool Layer at module scope.
    from dnd_assistant.tools.catalog import ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext, Permission

    if not isinstance(catalog, ToolRegistrySchema):
        raise TypeError("catalog must be a ToolRegistrySchema instance")
    if not isinstance(context, ExecutionContext):
        raise TypeError("context must be an ExecutionContext instance")

    result: list[ToolPublicDefinition] = []
    for tool in catalog.tools:
        if not _is_permission_eligible(tool, context, Permission):
            continue
        if context.session_mode not in tool.allowed_session_modes:
            continue
        if tool.permission == Permission.WRITE and context.audit is None:
            continue
        result.append(tool)

    return result


def _is_permission_eligible(
    tool: ToolPublicDefinition,
    context: ExecutionContext,
    permission_enum: type[Permission],
) -> bool:
    """Check whether ``tool`` is eligible based on granted permission.

    ``READ`` authority → only ``READ`` tools are eligible.
    ``WRITE`` authority → both ``READ`` and ``WRITE`` tools are eligible.
    Any other value → fail closed (no tool exposed).
    """
    if context.granted_permission == permission_enum.READ:
        return tool.permission == permission_enum.READ
    if context.granted_permission == permission_enum.WRITE:
        # WRITE authority includes READ authority
        return True
    # Unexpected/malformed permission value: fail closed.
    return False
