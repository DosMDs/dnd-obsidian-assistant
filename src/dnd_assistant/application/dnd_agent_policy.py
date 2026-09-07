"""Explicit D&D agent safety policy (PAIM-05).

This module owns the application-level batch-admission policy for Pydantic AI
deferred-tool orchestration.  It is the project-owned safety layer that sits
between the framework deferred-tool mechanism and ``ToolExecutor``.

Architecture
────────────

::

    Pydantic AI deferred batch (Sequence[ToolCallPart])
        ↓
    DndAgentPolicy.admit_tool_batch()
        ↓
    DndAgentBatchAdmission  (immutable, frozen)
        ↓
    future runtime adapter
        ↓
    PydanticAIToolBridge.execute()
        ↓
    ToolExecutor

The policy performs **zero** tool execution, **zero** argument parsing, and
**zero** model requests.  It produces only an immutable admission decision.

``ToolExecutor`` remains the final permission/session/audit authority.
"""

from __future__ import annotations

import collections.abc
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dnd_assistant.errors import ModelError, ValidationError

if TYPE_CHECKING:
    from pydantic_ai.messages import ToolCallPart

    from dnd_assistant.application.pydantic_ai_tool_bridge import (
        PydanticAIToolBridge,
        PydanticAIToolSnapshot,
    )
    from dnd_assistant.tools.types import ToolDefinition

# ── Central safety constants ──────────────────────────────────────────────────

MAX_TOOL_CALLS_PER_RUN: int = 4
"""Maximum number of initial tool calls accepted in one bounded run.

Must match ``AgentLoop.MAX_TOOL_CALLS_PER_RUN == 4``.
"""

MAX_MODEL_REQUESTS_PER_RUN: int = 2
"""Maximum model requests per run (policy contract for PAIM-08).

The policy itself does not count model requests — this constant is a contract
for later runtime integration.
"""

MAX_DEFERRED_TOOL_BATCHES_PER_RUN: int = 1
"""Maximum deferred tool batches per run.

Only one non-empty deferred tool batch is permitted.  A second batch is
rejected even if the first batch was itself rejected.
"""


# ── Immutable admission types ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AdmittedToolCall:
    """One admitted tool call within a batch.

    Attributes:
        position: Zero-based position in the original model batch order.
        tool_name: The canonical tool name.
        tool_call_id: The framework-assigned call ID (may be ``None``).
        definition: The canonical ``ToolDefinition`` from the frozen snapshot.
    """

    position: int
    tool_name: str
    tool_call_id: str | None
    definition: ToolDefinition


@dataclass(frozen=True, slots=True)
class DndAgentBatchAdmission:
    """Immutable result of a successful batch admission.

    Attributes:
        calls: Tuple of ``AdmittedToolCall`` values in exact model batch order.
    """

    calls: tuple[AdmittedToolCall, ...]


# ── Policy ────────────────────────────────────────────────────────────────────


class DndAgentPolicy:
    """Application-owned agent safety policy for one agent run.

    One instance represents one agent run.  It may contain minimal mutable
    run-local state (whether a deferred batch has already been observed).

    The policy operates only against a valid C08-issued
    ``PydanticAIToolSnapshot``.  It does **not** execute tools, parse tool
    arguments, or call ``ToolExecutor``.

    Args:
        tool_bridge: The ``PydanticAIToolBridge`` that issued the snapshot.
        snapshot: A valid C08-issued ``PydanticAIToolSnapshot``.

    Raises:
        ValidationError: If the snapshot is not valid for this bridge.
    """

    def __init__(
        self,
        *,
        tool_bridge: PydanticAIToolBridge,
        snapshot: PydanticAIToolSnapshot,
    ) -> None:
        # Validate snapshot at construction time.
        tool_bridge.validate_snapshot(snapshot)

        self._tool_bridge = tool_bridge
        self._snapshot = snapshot

        # Build a name→definition map from the frozen snapshot.
        self._def_map: dict[str, ToolDefinition] = {d.name: d for d in snapshot.definitions}

        # Run-local mutable state.
        self._batch_observed: bool = False

    # ── Public API ──────────────────────────────────────────────────────────

    def validate_binding(
        self,
        *,
        tool_bridge: PydanticAIToolBridge,
        snapshot: PydanticAIToolSnapshot,
    ) -> None:
        """Validate that this policy is bound to the exact bridge and snapshot.

        Required checks:
        - ``tool_bridge`` is the exact bridge used to construct this policy.
        - ``snapshot`` is the exact snapshot used to construct this policy.
        - ``tool_bridge.validate_snapshot(snapshot)`` succeeds.

        This method:
        - does **not** consume batch state;
        - does **not** inspect/parse tool calls;
        - does **not** execute anything.

        Args:
            tool_bridge: The bridge to validate against.
            snapshot: The snapshot to validate against.

        Raises:
            ValidationError: If the bridge or snapshot do not match this
                policy's construction-time arguments.
        """
        if tool_bridge is not self._tool_bridge:
            raise ValidationError("Policy was constructed with a different tool bridge")
        if snapshot is not self._snapshot:
            raise ValidationError("Policy was constructed with a different snapshot")
        tool_bridge.validate_snapshot(snapshot)

    def admit_tool_batch(
        self,
        tool_calls: Sequence[ToolCallPart],
    ) -> DndAgentBatchAdmission:
        """Admit or reject a complete deferred tool batch.

        Args:
            tool_calls: The complete deferred tool batch from the framework.

        Returns:
            An immutable ``DndAgentBatchAdmission`` with the admitted calls.

        Raises:
            ValidationError: If the input is structurally invalid (empty
                batch, wrong runtime types).
            ModelError: If the batch violates safety policy (too many calls,
                duplicate IDs, hidden/unknown names, multi-call WRITE, second
                batch).
        """
        # 1. Re-validate snapshot before every admission.
        self._tool_bridge.validate_snapshot(self._snapshot)

        # 2. Runtime Sequence check (PAIM-C09).
        #    Must be a real collections.abc.Sequence, not a generator,
        #    iterator, object() or other non-Sequence.
        if not isinstance(tool_calls, collections.abc.Sequence):
            raise ValidationError(
                f"Tool-call batch must be a Sequence, got {type(tool_calls).__name__}"
            )

        # 3. Freeze the complete batch into one immutable tuple (PAIM-C09).
        #    All subsequent preflight passes use this exact tuple, never
        #    re-reading the caller-owned mutable sequence.
        calls: tuple[ToolCallPart, ...] = tuple(tool_calls)

        # 4. Structural validation: non-empty tuple of ToolCallPart
        self._validate_batch_structure(calls)

        # 5. Second-batch rejection (before content admission — a rejected
        #    first batch still consumes the one batch opportunity).
        if self._batch_observed:
            raise ModelError(
                "A deferred tool batch has already been observed in this run. "
                "A second deferred tool batch is not allowed."
            )

        # Mark batch as observed immediately, before any content checks.
        # A rejected first batch still consumes the one batch opportunity.
        self._batch_observed = True

        # 6. Size check
        if len(calls) > MAX_TOOL_CALLS_PER_RUN:
            raise ModelError(
                f"Maximum {MAX_TOOL_CALLS_PER_RUN} tool calls per batch, got {len(calls)}"
            )

        # 7. Duplicate non-null call_id check
        self._reject_duplicate_call_ids(calls)

        # 8. Resolve each call against the frozen snapshot.
        resolved = self._resolve_calls(calls)

        # 9. Multi-call WRITE rejection
        if len(resolved) > 1:
            self._reject_multi_call_write(resolved)

        # 10. Build immutable admission result preserving exact model order.
        admitted = tuple(
            AdmittedToolCall(
                position=i,
                tool_name=tc.tool_name,
                tool_call_id=tc.tool_call_id,
                definition=definition,
            )
            for i, (tc, definition) in enumerate(resolved)
        )

        return DndAgentBatchAdmission(calls=admitted)

    # ── Internal validation helpers ─────────────────────────────────────────

    @staticmethod
    def _validate_batch_structure(calls: tuple[ToolCallPart, ...]) -> None:
        """Validate the structural shape of the tool-call batch.

        Args:
            calls: The frozen tuple snapshot of the batch (PAIM-C09).

        Raises:
            ValidationError: If the batch is empty or contains non-
                ``ToolCallPart`` entries.
        """
        from pydantic_ai.messages import ToolCallPart as TCP

        if not calls:
            raise ValidationError("Tool-call batch must not be empty")

        for i, item in enumerate(calls):
            if not isinstance(item, TCP):
                raise ValidationError(
                    f"Batch entry {i} must be a ToolCallPart instance, got {type(item).__name__}"
                )

    @staticmethod
    def _reject_duplicate_call_ids(calls: tuple[ToolCallPart, ...]) -> None:
        """Reject duplicate non-null ``tool_call_id`` values.

        Multiple ``None`` IDs are permitted.  Duplicate non-null IDs are
        ambiguous and fail closed.

        Args:
            calls: The frozen tuple snapshot of the batch (PAIM-C09).

        Raises:
            ModelError: If any non-null ``tool_call_id`` appears more than
                once in the batch.
        """
        seen: set[str] = set()
        for tc in calls:
            cid = tc.tool_call_id
            if cid is not None:
                if cid in seen:
                    raise ModelError(
                        f"Duplicate non-null tool_call_id '{cid}' in deferred tool batch"
                    )
                seen.add(cid)

    def _resolve_calls(
        self,
        calls: tuple[ToolCallPart, ...],
    ) -> list[tuple[ToolCallPart, ToolDefinition]]:
        """Resolve each call against the frozen snapshot.

        Args:
            calls: The frozen tuple snapshot of the batch (PAIM-C09).

        Returns:
            List of ``(ToolCallPart, ToolDefinition)`` tuples in batch order.

        Raises:
            ModelError: If any tool name is not in the frozen snapshot.
        """
        resolved: list[tuple[ToolCallPart, ToolDefinition]] = []
        for tc in calls:
            definition = self._def_map.get(tc.tool_name)
            if definition is None:
                raise ModelError(
                    f"Tool '{tc.tool_name}' is not in the frozen exposure "
                    "snapshot. Unknown or hidden tools are not allowed."
                )
            resolved.append((tc, definition))
        return resolved

    @staticmethod
    def _reject_multi_call_write(
        resolved: list[tuple[ToolCallPart, ToolDefinition]],
    ) -> None:
        """Reject a multi-call batch containing any WRITE tool.

        Every definition in a multi-call batch must have ``Permission.READ``.

        Raises:
            ModelError: If any definition does not have ``Permission.READ``.
        """
        from dnd_assistant.tools.types import Permission

        for tc, definition in resolved:
            if type(definition.permission) is not Permission:
                raise ModelError(
                    f"Tool '{tc.tool_name}' has malformed permission "
                    f"'{definition.permission}'. Cannot classify for "
                    "multi-call safety."
                )
            if definition.permission is not Permission.READ:
                raise ModelError(
                    "Multi-call batches containing WRITE tools are not "
                    f"allowed. Tool '{tc.tool_name}' has permission "
                    f"'{definition.permission.value}'."
                )
