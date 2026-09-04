"""Validated Fast Agent tool execution boundary (S9-03).

This module owns exactly:

- turn-binding validation (call belongs to decision)
- exposed-tool allowlist defence-in-depth
- ToolExecutor invocation with preserved model arguments
- deterministic TOOL-result JSON serialisation
- provider-neutral TOOL ChatMessage construction

It does NOT own:

- model selection / context building / tool exposure policy
- input/output schema validation (those are ToolExecutor's responsibility)
- second model turn
- multi-call execution semantics
- retry / clarification / final response
- CLI
- Vault access
- retrieval
- calendar arithmetic
- Ollama transport

Importing this module must NOT eagerly load::

    dnd_assistant.models.ollama
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_core import PydanticSerializationError

from dnd_assistant.errors import ValidationError

if TYPE_CHECKING:
    from dnd_assistant.application.fast_agent import AgentDecision
    from dnd_assistant.models.types import ChatMessage, ToolCall
    from dnd_assistant.tools.executor import ToolExecutor
    from dnd_assistant.tools.types import BaseModel, ExecutionContext


# ── Public DTO ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentToolExecutionResult:
    """Result of executing one validated tool call.

    Attributes:
        tool_call: The exact ``ToolCall`` that was executed.
        output: The validated typed ``BaseModel`` returned by ``ToolExecutor``.
        tool_message: A provider-neutral ``ChatMessage`` with ``role=TOOL``
            containing the deterministic JSON-serialised output.
    """

    tool_call: ToolCall
    output: BaseModel
    tool_message: ChatMessage


# ── AgentToolExecutionService ───────────────────────────────────────────────────


class AgentToolExecutionService:
    """Per-call tool execution primitive for the Fast Agent.

    Validates that the supplied ``ToolCall`` belongs to the given
    ``AgentDecision`` and that its name is in the decision's turn-local
    exposure snapshot, then delegates to ``ToolExecutor`` for the
    trusted execution pipeline.
    """

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
    ) -> None:
        self._tool_executor = tool_executor

    def execute(
        self,
        decision: AgentDecision,
        tool_call: ToolCall,
        *,
        execution_context: ExecutionContext,
    ) -> AgentToolExecutionResult:
        """Execute one validated tool call.

        Args:
            decision: The ``AgentDecision`` that produced the tool call.
            tool_call: The exact ``ToolCall`` to execute (must be a member
                of the decision).
            execution_context: Trusted Python execution context.

        Returns:
            An ``AgentToolExecutionResult`` with the typed output and
            TOOL message.

        Raises:
            ValidationError: If the call is not a member of the decision,
                is not in the turn-local exposure snapshot, or the input
                objects are structurally malformed.
            NotFoundError: Propagated from ``ToolExecutor``.
            ConflictError: Propagated from ``ToolExecutor``.
            DndAssistantError: Propagated from ``ToolExecutor`` / handler.
            Exception: Any non-DndAssistantError from handler propagates
                unchanged.
        """
        # Deferred runtime imports: keep provider/tool/storage packages out
        # of module-import scope.
        from dnd_assistant.application.fast_agent import AgentDecision as AD
        from dnd_assistant.models.types import ToolCall as TC
        from dnd_assistant.tools.types import ExecutionContext as EC

        # 1. Reject malformed/non-AgentDecision input
        if not isinstance(decision, AD):
            raise ValidationError("decision must be an AgentDecision instance")

        # 2. Reject malformed/non-ToolCall input
        if not isinstance(tool_call, TC):
            raise ValidationError("tool_call must be a ToolCall instance")

        # 3. Reject malformed/non-ExecutionContext input
        if not isinstance(execution_context, EC):
            raise ValidationError("execution_context must be an ExecutionContext instance")

        # 4. Exact decision membership: the supplied ToolCall must be
        #    semantically equal to one of the decision's tool_calls.
        decision_calls = decision.response.message.tool_calls
        if not _tool_call_in(tool_call, decision_calls):
            raise ValidationError("ToolCall is not a member of the AgentDecision")

        # 5. Turn-local exposure snapshot defence-in-depth: the call name
        #    must exist in decision.exposed_tools.
        if not any(tool_call.name == t.name for t in decision.exposed_tools):
            raise ValidationError(
                f"Tool call '{tool_call.name}' is not in the exposed-tool allowlist for this turn"
            )

        # 6. Delegate to ToolExecutor with preserved model arguments.
        #    No application-level coercion, defaults, or filtering.
        output = self._tool_executor.execute(
            tool_call.name,
            input_data=tool_call.arguments,
            context=execution_context,
        )

        # 7. Deterministic TOOL-result JSON serialisation.
        tool_message = _build_tool_message(output, tool_call)

        # 8. Return frozen result.
        return AgentToolExecutionResult(
            tool_call=tool_call,
            output=output,
            tool_message=tool_message,
        )


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _tool_call_in(call: ToolCall, calls: tuple[ToolCall, ...]) -> bool:
    """Check if ``call`` is a strict member of ``calls``.

    Strict membership means:
    - same ``name``
    - same ``call_id`` (or both None)
    - same ``arguments`` using **recursive strict JSON value comparison**

    Python ``==`` conflates distinct JSON types (``0 == False``,
    ``1 == True``).  This comparator preserves exact JSON structural
    types recursively so that model-selected argument types cannot be
    silently substituted.

    Dict key order does NOT matter.  List order DOES matter.
    """
    for existing in calls:
        if (
            call.name == existing.name
            and call.call_id == existing.call_id
            and _json_args_equal(call.arguments, existing.arguments)
        ):
            return True
    return False


def _json_args_equal(left: object, right: object) -> bool:
    """Recursive strict JSON value comparison.

    Preserves exact JSON structural types:
    - ``0 != False``, ``1 != True``, ``1 != 1.0``
    - ``None`` matches only ``None``
    - ``bool`` matches only ``bool``
    - ``int`` matches only ``int``
    - ``float`` matches only ``float``
    - ``str`` matches only ``str``
    - ``list`` order matters
    - ``dict`` key order does NOT matter
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if len(left) != len(right):
            return False
        for k in left:
            if k not in right:
                return False
            if not _json_args_equal(left[k], right[k]):
                return False
        return True
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        return all(_json_args_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _build_tool_message(
    output: BaseModel,
    tool_call: ToolCall,
) -> ChatMessage:
    """Build a deterministic TOOL ``ChatMessage`` from a validated output.

    The output is serialised using Pydantic's ``model_dump(mode="json")``
    followed by deterministic ``json.dumps``.

    Args:
        output: The validated typed ``BaseModel`` from ``ToolExecutor``.
        tool_call: The original ``ToolCall`` (for name and call_id).

    Returns:
        A ``ChatMessage`` with ``role=TOOL``.

    Raises:
        ValidationError: If the validated output cannot be serialised to
            model-facing JSON.
    """
    from dnd_assistant.models.types import ChatMessage, MessageRole

    try:
        json_ready = output.model_dump(mode="json", by_alias=True)
    except PydanticSerializationError as exc:
        raise ValidationError(
            "Failed to serialise tool output to JSON",
            cause=exc,
        ) from exc

    try:
        content = json.dumps(
            json_ready,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError(
            "Failed to serialise tool output to JSON",
            cause=exc,
        ) from exc

    return ChatMessage(
        role=MessageRole.TOOL,
        content=content,
        tool_name=tool_call.name,
        tool_call_id=tool_call.call_id,
    )
