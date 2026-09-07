"""Pydantic AI tool bridge — ToolRegistry → ExternalToolset → ToolExecutor.

This is the first production Pydantic AI integration boundary.  It provides:

1. ``PydanticAIToolSnapshot`` — an immutable project-owned authority that
   stores canonical ``ToolDefinition`` values for one turn-local exposure.
2. ``PydanticAIToolBridge`` — the application-layer bridge that:
   - validates incoming ``ToolPublicDefinition`` against the canonical
     ``ToolRegistry`` (``freeze()``);
   - generates a fresh schema-only ``ExternalToolset`` from the project
     snapshot (``to_external_toolset()``);
   - executes a single ``ToolCallPart`` through ``ToolExecutor``
     (``execute()``).

Architecture
────────────

::

    ToolRegistry
        ↓  build_tool_registry_schema()
    ToolRegistrySchema
        ↓  select_agent_tools()
    Sequence[ToolPublicDefinition]   ← already-selected turn-local exposure
        ↓  bridge.freeze()
    PydanticAIToolSnapshot           ← immutable project authority
        ↓  snapshot.to_external_toolset()
    ExternalToolset                  ← fresh schema-only framework view
        ↓
    Pydantic AI model loop
        ↓  ToolCallPart
    bridge.execute(snapshot, call, execution_context=...)
        ↓
    ToolExecutor.execute()
        ↓
    validated BaseModel output

Ownership
─────────

Project-owned (unchanged):
    ToolRegistry, ToolDefinition, ToolPublicDefinition, permission metadata,
    side effects, session modes, ToolExecutor, ExecutionContext.

Pydantic AI-owned (in this module):
    ExternalToolset, ToolDefinition (framework), ToolCallPart.

This module must not import from:
    dnd_assistant.storage, dnd_assistant.domain, dnd_assistant.retrieval,
    dnd_assistant.cli, dnd_assistant.models.ollama, ollama.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from dnd_assistant.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.toolsets import ExternalToolset

    from dnd_assistant.tools.catalog import ToolPublicDefinition
    from dnd_assistant.tools.executor import ToolExecutor
    from dnd_assistant.tools.registry import ToolRegistry
    from dnd_assistant.tools.types import (
        ExecutionContext,
        Permission,
        SessionMode,
        SideEffect,
        ToolDefinition,
    )

# ── Public types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PydanticAIToolSnapshot:
    """Immutable project-owned authority for one turn-local tool exposure.

    Stores canonical ``ToolDefinition`` instances validated against the
    ``ToolRegistry``.  This is the authoritative source of truth for what
    tools the model may see and call.  The ``ExternalToolset`` generated
    from this snapshot is a derived framework view — mutating the framework
    object does not change project authority.
    """

    definitions: tuple[ToolDefinition, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """Return the sorted names of all tools in the snapshot."""
        return tuple(d.name for d in self.definitions)

    def to_external_toolset(self) -> ExternalToolset:
        """Return a **fresh** schema-only ``ExternalToolset``.

        Each call creates a new framework object.  Mutating the returned
        toolset does not affect this snapshot or any future toolset.
        """
        # Deferred import: Pydantic AI is an optional dependency for this
        # module and must not be eagerly loaded at module-import time.
        from pydantic_ai.tools import ToolDefinition as PydToolDef
        from pydantic_ai.toolsets import ExternalToolset

        pyd_defs: list[PydToolDef] = []
        for td in self.definitions:
            pyd_defs.append(
                PydToolDef(
                    name=td.name,
                    description=td.description,
                    parameters_json_schema=td.input_schema.model_json_schema(),
                )
            )
        return ExternalToolset(pyd_defs)


# ── Bridge ───────────────────────────────────────────────────────────────────


class PydanticAIToolBridge:
    """Application-layer bridge between ToolRegistry and Pydantic AI.

    Args:
        registry: The canonical ``ToolRegistry``.  All incoming public
            definitions are revalidated against this registry during
            ``freeze()``.
    """

    def __init__(self, *, registry: ToolRegistry) -> None:
        self._registry = registry
        self._executor: ToolExecutor | None = None

    # ── Freeze (snapshot creation) ──────────────────────────────────────────

    def freeze(
        self,
        exposed_tools: Sequence[ToolPublicDefinition],
    ) -> PydanticAIToolSnapshot:
        """Validate and freeze a turn-local exposure snapshot.

        Args:
            exposed_tools: Already-selected turn-local tool exposure
                (normally produced by ``select_agent_tools()``).

        Returns:
            An immutable ``PydanticAIToolSnapshot`` containing canonical
            ``ToolDefinition`` instances.

        Raises:
            ValidationError: If any tool is malformed, duplicated, unknown,
                or has metadata that does not match the canonical registry.
        """
        # Deferred imports to avoid eager loading of tool types at module
        # scope.
        from dnd_assistant.tools.catalog import ToolPublicDefinition as PubDef
        from dnd_assistant.tools.types import Permission, SessionMode, SideEffect

        # 1. Validate each input item is a real ToolPublicDefinition
        seen_names: set[str] = set()
        canonical_defs: list[ToolDefinition] = []

        for item in exposed_tools:
            if not isinstance(item, PubDef):
                raise ValidationError("Each exposed tool must be a ToolPublicDefinition instance")

            # 2. Reject duplicate names
            if item.name in seen_names:
                raise ValidationError(f"Duplicate tool name in exposure: '{item.name}'")
            seen_names.add(item.name)

            # 3. Resolve against canonical registry
            try:
                binding = self._registry.get(item.name)
            except Exception as exc:
                raise ValidationError(
                    f"Tool '{item.name}' is not registered in the canonical ToolRegistry",
                    cause=exc,
                ) from exc

            canonical = binding.definition

            # 4. Verify metadata correspondence
            _verify_metadata_match(item, canonical, Permission, SessionMode, SideEffect)

            canonical_defs.append(canonical)

        return PydanticAIToolSnapshot(definitions=tuple(canonical_defs))

    # ── Execute (per-call adapter) ──────────────────────────────────────────

    def execute(
        self,
        snapshot: PydanticAIToolSnapshot,
        tool_call: ToolCallPart,
        *,
        execution_context: ExecutionContext,
    ) -> BaseModel:
        """Execute a single Pydantic AI tool call through ``ToolExecutor``.

        Args:
            snapshot: The frozen project snapshot that authorised this call.
            tool_call: The Pydantic AI ``ToolCallPart`` from the model.
            execution_context: Trusted Python execution context.

        Returns:
            The validated typed ``BaseModel`` output from ``ToolExecutor``.

        Raises:
            ValidationError: If the tool name is not in the snapshot, or
                the raw arguments cannot be parsed as a JSON object.
            NotFoundError: Propagated from ``ToolExecutor``.
            ConflictError: Propagated from ``ToolExecutor``.
            DndAssistantError: Propagated from ``ToolExecutor`` / handler.
            Exception: Any non-DndAssistantError from the handler propagates
                unchanged.
        """
        # 1. Validate snapshot type
        if not isinstance(snapshot, PydanticAIToolSnapshot):
            raise ValidationError("snapshot must be a PydanticAIToolSnapshot instance")

        # 2. Validate execution context type
        from dnd_assistant.tools.types import ExecutionContext as EC

        if not isinstance(execution_context, EC):
            raise ValidationError("execution_context must be an ExecutionContext instance")

        # 3. Validate tool name against frozen snapshot
        name = tool_call.tool_name
        if name not in snapshot.names:
            raise ValidationError(f"Tool '{name}' is not in the frozen exposure snapshot")

        # 4. Convert raw arguments — fail closed on malformed/non-object JSON
        try:
            raw_args = tool_call.args_as_dict(raise_if_invalid=True)
        except (ValueError, AssertionError) as exc:
            raise ValidationError(
                f"Failed to parse arguments for tool '{name}': {exc}",
                cause=exc,
            ) from exc

        # 5. Delegate to ToolExecutor (lazy-created, bound to same registry)
        executor = self._get_executor()
        output = executor.execute(
            name,
            input_data=raw_args,
            context=execution_context,
        )

        # 6. Return typed output unchanged
        return output

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_executor(self) -> ToolExecutor:
        """Return a ``ToolExecutor`` bound to the bridge's canonical registry.

        Created lazily so that the bridge can be constructed without eagerly
        importing ``ToolExecutor`` at module scope.
        """
        if self._executor is None:
            from dnd_assistant.tools.executor import ToolExecutor

            self._executor = ToolExecutor(self._registry)
        return self._executor


# ── Metadata verification ────────────────────────────────────────────────────


def _verify_metadata_match(
    public: ToolPublicDefinition,
    canonical: ToolDefinition,
    permission_enum: type[Permission],
    session_mode_enum: type[SessionMode],
    side_effect_enum: type[SideEffect],
) -> None:
    """Verify that a public definition matches its canonical counterpart.

    Uses strict ``is`` identity for enum comparisons to reject foreign or
    plain-string impostors.

    Raises:
        ValidationError: On any mismatch.
    """
    name = public.name

    # Permission
    if not isinstance(public.permission, permission_enum):
        raise ValidationError(f"Tool '{name}': permission is not a valid Permission enum instance")
    if public.permission is not canonical.permission:
        raise ValidationError(
            f"Tool '{name}': permission mismatch "
            f"(public={public.permission!r}, canonical={canonical.permission!r})"
        )

    # Session modes — compare sets of identity
    public_modes_set = set(public.allowed_session_modes)
    canonical_modes_set = set(canonical.allowed_session_modes)
    if public_modes_set != canonical_modes_set:
        raise ValidationError(
            f"Tool '{name}': allowed_session_modes mismatch "
            f"(public={sorted(m.value for m in public_modes_set)}, "
            f"canonical={sorted(m.value for m in canonical_modes_set)})"
        )

    # Side effects — compare sets of identity
    public_effects_set = set(public.side_effects)
    canonical_effects_set = set(canonical.side_effects)
    if public_effects_set != canonical_effects_set:
        raise ValidationError(
            f"Tool '{name}': side_effects mismatch "
            f"(public={sorted(e.value for e in public_effects_set)}, "
            f"canonical={sorted(e.value for e in canonical_effects_set)})"
        )

    # Description
    if public.description != canonical.description:
        raise ValidationError(f"Tool '{name}': description mismatch")

    # Input schema — use deterministic JSON comparison
    public_schema = _normalize_json_schema(public.input_schema)
    canonical_schema = _normalize_json_schema(canonical.input_schema.model_json_schema())
    if public_schema != canonical_schema:
        raise ValidationError(f"Tool '{name}': input_schema mismatch")

    # Output schema
    public_output = _normalize_json_schema(public.output_schema)
    canonical_output = _normalize_json_schema(canonical.output_schema.model_json_schema())
    if public_output != canonical_output:
        raise ValidationError(f"Tool '{name}': output_schema mismatch")


def _normalize_json_schema(schema: dict[str, Any]) -> str:
    """Deterministic JSON serialisation for schema comparison.

    Uses ``sort_keys=True`` and no extra whitespace so that structurally
    identical schemas produce the same string regardless of key ordering.
    """
    return json.dumps(
        schema,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
