"""Shared Pydantic AI response/tool-call adapter for PAIM-07 and PAIM-08.

This module provides the single deterministic helper for adapting framework
``ToolCallPart`` values to project ``ToolCall`` DTOs, shared by both
``PydanticAIFastAgent`` (PAIM-07) and ``PydanticAIAgentRuntime`` (PAIM-08).

Architecture
────────────

::

    ToolCallPart (framework)
        │
        └── adapt_pydantic_tool_calls()
                │
                ├── 1. validate tool name against snapshot
                ├── 2. args_as_dict — fail closed on malformed/non-object JSON
                ├── 3. project ToolCall — rejects non-finite JSON values
                └── 4. return tuple[ToolCall, ...] in exact order

Failure:
    → project ModelError
    → original validation/parsing cause retained where applicable

No tool-specific input schema validation here — that remains in
``ToolExecutor``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd_assistant.errors import ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import ToolCallPart

    from dnd_assistant.models.types import ToolCall


def adapt_pydantic_tool_calls(
    calls: Sequence[ToolCallPart],
    *,
    snapshot_names: tuple[str, ...],
) -> tuple[ToolCall, ...]:
    """Adapt framework ``ToolCallPart`` values to project ``ToolCall`` DTOs.

    Preserves exact order, tool name, arguments, and ``tool_call_id``.

    Args:
        calls: The framework tool call parts to adapt.
        snapshot_names: The frozen snapshot tool names (for membership check).

    Returns:
        A tuple of project ``ToolCall`` instances in the original order.

    Raises:
        ModelError: If any tool name is not in the frozen snapshot, or if
            the arguments cannot be represented as a JSON object, or if
            the resulting ``ToolCall`` fails validation (e.g. non-finite
            JSON values).
    """
    from dnd_assistant.models.types import ToolCall as ProjectToolCall

    adapted: list[ProjectToolCall] = []

    for call in calls:
        # 1. Validate tool name against snapshot
        if call.tool_name not in snapshot_names:
            raise ModelError(
                f"Tool call '{call.tool_name}' is not in the frozen exposure "
                "snapshot. Unknown or hidden tools are not allowed."
            )

        # 2. Convert arguments — fail closed on malformed/non-object JSON
        try:
            args = call.args_as_dict(raise_if_invalid=True)
        except (ValueError, AssertionError) as exc:
            raise ModelError(
                f"Failed to parse arguments for tool '{call.tool_name}': {exc}",
                cause=exc,
            ) from exc

        # 3. Build project ToolCall (validates non-finite JSON values)
        try:
            project_call = ProjectToolCall(
                name=call.tool_name,
                arguments=args,
                call_id=call.tool_call_id,
            )
        except (ValueError, AssertionError) as exc:
            raise ModelError(
                f"Failed to construct ToolCall for '{call.tool_name}': {exc}",
                cause=exc,
            ) from exc

        adapted.append(project_call)

    return tuple(adapted)
