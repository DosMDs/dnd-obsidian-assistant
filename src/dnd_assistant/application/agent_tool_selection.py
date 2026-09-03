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

Imports are restricted to:
    dnd_assistant.tools.catalog
    dnd_assistant.tools.types

It must NOT import:
    dnd_assistant.models
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.domain
    dnd_assistant.cli
    ToolExecutor
    ToolRegistry
    Ollama
    httpx
"""

from __future__ import annotations

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
    if not isinstance(catalog, ToolRegistrySchema):
        raise TypeError("catalog must be a ToolRegistrySchema instance")
    if not isinstance(context, ExecutionContext):
        raise TypeError("context must be an ExecutionContext instance")

    result: list[ToolPublicDefinition] = []
    for tool in catalog.tools:
        if not _is_permission_eligible(tool, context):
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
) -> bool:
    """Check whether ``tool`` is eligible based on granted permission.

    ``READ`` authority → only ``READ`` tools are eligible.
    ``WRITE`` authority → both ``READ`` and ``WRITE`` tools are eligible.
    """
    if context.granted_permission == Permission.READ:
        return tool.permission == Permission.READ
    # WRITE authority includes READ authority
    return True
