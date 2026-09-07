"""Pydantic AI tool bridge — ToolRegistry → ExternalToolset → ToolExecutor.

This is the first production Pydantic AI integration boundary.  It provides:

1. ``PydanticAIToolSnapshot`` — an immutable project-owned authority that
   stores canonical ``ToolDefinition`` values for one turn-local exposure.
   Each snapshot is bound to the bridge that created it via an opaque
   ``_owner_token``.
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
        ↓  bridge.to_external_toolset(snapshot)
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
from dataclasses import dataclass, field
from enum import StrEnum
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
    tools the model may see and call.

    Each snapshot is bound to the bridge that created it via an opaque
    ``_owner_token``.  A snapshot from one bridge cannot authorise execution
    or framework exposure through another bridge.

    .. note::

        Do **not** construct this class directly.  Use
        ``PydanticAIToolSnapshot._create()`` or the owning bridge's
        ``freeze()`` method.
    """

    definitions: tuple[ToolDefinition, ...]
    _owner_token: object = field(repr=False, compare=False)

    @staticmethod
    def _create(
        definitions: tuple[ToolDefinition, ...],
        owner_token: object,
    ) -> PydanticAIToolSnapshot:
        """Internal factory — create a snapshot bound to an owner token.

        This is the only way to construct a snapshot with a valid owner
        token.  The public dataclass-generated constructor requires an
        explicit ``_owner_token`` argument, which callers outside the
        bridge cannot supply without access to the bridge's private token.
        """
        return PydanticAIToolSnapshot(definitions=definitions, _owner_token=owner_token)

    @property
    def names(self) -> tuple[str, ...]:
        """Return tool names in frozen exposure order."""
        return tuple(d.name for d in self.definitions)


# ── Bridge ───────────────────────────────────────────────────────────────────


class PydanticAIToolBridge:
    """Application-layer bridge between ToolRegistry and Pydantic AI.

    Each bridge owns one private opaque ``_snapshot_owner_token``.  A
    snapshot created by one bridge cannot authorise execution or framework
    exposure through another bridge.

    Args:
        registry: The canonical ``ToolRegistry``.  All incoming public
            definitions are revalidated against this registry during
            ``freeze()``.

    Raises:
        TypeError: If ``registry`` is not a ``ToolRegistry`` instance.
    """

    def __init__(self, *, registry: ToolRegistry) -> None:
        from dnd_assistant.tools.registry import ToolRegistry as TR

        if not isinstance(registry, TR):
            raise TypeError("registry must be a ToolRegistry instance")
        self._registry = registry
        self._snapshot_owner_token: object = object()
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
            ``ToolDefinition`` instances, bound to this bridge's owner token.

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

            # 3. Resolve against canonical registry — catch only the expected
            #    project-level unknown-tool error.
            from dnd_assistant.errors import NotFoundError

            try:
                binding = self._registry.get(item.name)
            except NotFoundError as exc:
                raise ValidationError(
                    f"Tool '{item.name}' is not registered in the canonical ToolRegistry",
                    cause=exc,
                ) from exc

            canonical = binding.definition

            # 4. Verify metadata correspondence
            _verify_metadata_match(item, canonical, Permission, SessionMode, SideEffect)

            canonical_defs.append(canonical)

        return PydanticAIToolSnapshot._create(
            definitions=tuple(canonical_defs),
            owner_token=self._snapshot_owner_token,
        )

    # ── Framework translation ───────────────────────────────────────────────

    def to_external_toolset(
        self,
        snapshot: PydanticAIToolSnapshot,
    ) -> ExternalToolset:
        """Return a **fresh** schema-only ``ExternalToolset`` from a snapshot.

        Validates snapshot provenance first.  Each call creates a new
        framework object.  Mutating the returned toolset does not affect
        this snapshot or any future toolset.

        Args:
            snapshot: A ``PydanticAIToolSnapshot`` created by this bridge.

        Returns:
            A fresh schema-only ``ExternalToolset``.

        Raises:
            ValidationError: If the snapshot is not valid or not owned by
                this bridge.
        """
        self._validate_snapshot(snapshot)

        # Deferred import: Pydantic AI is an optional dependency for this
        # module and must not be eagerly loaded at module-import time.
        from pydantic_ai.tools import ToolDefinition as PydToolDef
        from pydantic_ai.toolsets import ExternalToolset

        pyd_defs: list[PydToolDef] = []
        for td in snapshot.definitions:
            pyd_defs.append(
                PydToolDef(
                    name=td.name,
                    description=td.description,
                    parameters_json_schema=td.input_schema.model_json_schema(),
                )
            )
        return ExternalToolset(pyd_defs)

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
            ValidationError: If the snapshot is invalid, the tool name is
                not in the snapshot, or the raw arguments cannot be parsed
                as a JSON object.
            NotFoundError: Propagated from ``ToolExecutor``.
            ConflictError: Propagated from ``ToolExecutor``.
            DndAssistantError: Propagated from ``ToolExecutor`` / handler.
            Exception: Any non-DndAssistantError from the handler propagates
                unchanged.
        """
        # 1. Validate snapshot provenance and structure
        self._validate_snapshot(snapshot)

        # 2. Validate execution context type
        from dnd_assistant.tools.types import ExecutionContext as EC

        if not isinstance(execution_context, EC):
            raise ValidationError("execution_context must be an ExecutionContext instance")

        # 3. Structural validation: tool_call must be a ToolCallPart
        from pydantic_ai.messages import ToolCallPart as TCP

        if not isinstance(tool_call, TCP):
            raise ValidationError(
                f"tool_call must be a ToolCallPart instance, got {type(tool_call).__name__}"
            )

        # 4. Validate tool name against frozen snapshot
        name = tool_call.tool_name
        if name not in snapshot.names:
            raise ValidationError(f"Tool '{name}' is not in the frozen exposure snapshot")

        # 5. Convert raw arguments — fail closed on malformed/non-object JSON
        try:
            raw_args = tool_call.args_as_dict(raise_if_invalid=True)
        except (ValueError, AssertionError) as exc:
            raise ValidationError(
                f"Failed to parse arguments for tool '{name}': {exc}",
                cause=exc,
            ) from exc

        # 6. Delegate to ToolExecutor (lazy-created, bound to same registry)
        executor = self._get_executor()
        output = executor.execute(
            name,
            input_data=raw_args,
            context=execution_context,
        )

        # 7. Return typed output unchanged
        return output

    # ── Snapshot validation ─────────────────────────────────────────────────

    def _validate_snapshot(self, snapshot: PydanticAIToolSnapshot) -> None:
        """Validate snapshot provenance and structural integrity.

        Proves:
        1. Correct runtime type.
        2. Owner token belongs to this bridge.
        3. No duplicate definitions/names.
        4. Every stored definition is still the exact canonical registered
           definition for this bridge's registry.

        Raises:
            ValidationError: On any validation failure.
        """
        # 1. Correct runtime type
        if not isinstance(snapshot, PydanticAIToolSnapshot):
            raise ValidationError("snapshot must be a PydanticAIToolSnapshot instance")

        # 2. Owner token belongs to this bridge
        if snapshot._owner_token is not self._snapshot_owner_token:
            raise ValidationError(
                "snapshot was created by a different bridge and cannot be used here"
            )

        # 3. No duplicate names
        seen: set[str] = set()
        for td in snapshot.definitions:
            if td.name in seen:
                raise ValidationError(f"Duplicate definition name in snapshot: '{td.name}'")
            seen.add(td.name)

        # 4. Every stored definition is still the exact canonical registered
        #    definition for this bridge's registry (identity check).
        from dnd_assistant.errors import NotFoundError as NFE

        for td in snapshot.definitions:
            try:
                binding = self._registry.get(td.name)
            except NFE as exc:
                raise ValidationError(
                    f"Snapshot definition '{td.name}' is no longer registered in the canonical registry",
                    cause=exc,
                ) from exc
            if binding.definition is not td:
                raise ValidationError(
                    f"Snapshot definition '{td.name}' is not the canonical registry object"
                )

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

    Uses strict ``type() is`` identity for enum comparisons to reject
    foreign or plain-string impostors.  Collection members are validated
    individually for exact enum type before semantic comparison.

    Raises:
        ValidationError: On any mismatch.
    """
    name = public.name

    # Permission — exact type check, then identity
    if type(public.permission) is not permission_enum:
        raise ValidationError(f"Tool '{name}': permission is not a valid Permission enum instance")
    if public.permission is not canonical.permission:
        raise ValidationError(
            f"Tool '{name}': permission mismatch "
            f"(public={public.permission!r}, canonical={canonical.permission!r})"
        )

    # Session modes — exact type for every member, then semantic comparison
    _verify_exact_enum_members(
        name,
        "allowed_session_modes",
        public.allowed_session_modes,
        canonical.allowed_session_modes,
        session_mode_enum,
    )

    # Side effects — exact type for every member, then semantic comparison
    _verify_exact_enum_members(
        name,
        "side_effects",
        public.side_effects,
        canonical.side_effects,
        side_effect_enum,
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


def _verify_exact_enum_members(
    tool_name: str,
    field_name: str,
    public_values: list[StrEnum],
    canonical_values: frozenset[StrEnum],
    expected_enum: type[StrEnum],
) -> None:
    """Verify that a collection of enum values has exact types and matches.

    Every member of ``public_values`` must:
    - Be the exact ``expected_enum`` type (``type() is``).
    - Be a member of the canonical set (``is`` identity).

    The collection must have the same cardinality as the canonical set with
    no duplicates.

    Raises:
        ValidationError: On any mismatch.
    """
    # Exact type for every member
    for v in public_values:
        if type(v) is not expected_enum:
            raise ValidationError(
                f"Tool '{tool_name}': {field_name} contains a value that is not "
                f"the expected enum type (got {type(v).__name__})"
            )

    # No duplicates
    seen: set[StrEnum] = set()
    for v in public_values:
        if v in seen:
            raise ValidationError(f"Tool '{tool_name}': duplicate value in {field_name}")
        seen.add(v)

    # Same cardinality as canonical
    if len(public_values) != len(canonical_values):
        raise ValidationError(
            f"Tool '{tool_name}': {field_name} cardinality mismatch "
            f"(public={len(public_values)}, canonical={len(canonical_values)})"
        )

    # Every public member is the identical canonical member
    for v in public_values:
        if v not in canonical_values:
            raise ValidationError(
                f"Tool '{tool_name}': {field_name} contains unexpected value '{v.value}'"
            )
