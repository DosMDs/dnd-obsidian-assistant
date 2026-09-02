"""Provider-neutral public registry schema and catalog builder.

This module provides a stable JSON-serializable view of a ``ToolRegistry``
for provider-neutral consumption.  It does NOT depend on:

    models, cli, storage, retrieval, application, ollama

The catalog builder works for any valid ``ToolRegistry``, not only the
MVP registry.
"""

from __future__ import annotations

from pydantic import BaseModel, JsonValue

from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import Permission, SessionMode, SideEffect


class ToolPublicDefinition(BaseModel):
    """Provider-neutral public view of a single tool definition.

    Exposes name, description, JSON Schema for input/output, permission,
    side effects, and allowed session modes.  No handler, callable,
    Python module path, or provider-specific shape is exposed.
    """

    name: str
    """Deterministic snake_case machine name."""

    description: str
    """Human-readable description."""

    input_schema: dict[str, JsonValue]
    """JSON Schema for validated input (from ``model_json_schema()``)."""

    output_schema: dict[str, JsonValue]
    """JSON Schema for validated output (from ``model_json_schema()``)."""

    permission: Permission
    """Execution authority level."""

    side_effects: list[SideEffect]
    """Machine-readable side-effect categories, sorted by enum value."""

    allowed_session_modes: list[SessionMode]
    """Session modes in which this tool may execute, sorted by enum value."""

    model_config = {"extra": "forbid", "frozen": True}


class ToolRegistrySchema(BaseModel):
    """Provider-neutral public catalog of all tools in a ``ToolRegistry``.

    The catalog is a snapshot of metadata.  Building it must not invoke
    tool handlers, mutate the registry, mutate Pydantic model classes,
    mutate repositories, or access the filesystem.
    """

    tools: list[ToolPublicDefinition]

    model_config = {"extra": "forbid", "frozen": True}


def build_tool_registry_schema(registry: ToolRegistry) -> ToolRegistrySchema:
    """Build a provider-neutral public catalog from a ``ToolRegistry``.

    Args:
        registry: A ``ToolRegistry`` instance.

    Returns:
        A ``ToolRegistrySchema`` containing deterministic metadata for
        every registered tool.

    Raises:
        TypeError: If ``registry`` is not a ``ToolRegistry`` or does
            not have the required ``list_definitions`` method.
    """
    if not hasattr(registry, "list_definitions"):
        raise TypeError("registry must be a ToolRegistry instance")

    definitions = registry.list_definitions()

    public_tools: list[ToolPublicDefinition] = []
    for defn in definitions:
        public_tools.append(
            ToolPublicDefinition(
                name=defn.name,
                description=defn.description,
                input_schema=defn.input_schema.model_json_schema(),
                output_schema=defn.output_schema.model_json_schema(),
                permission=defn.permission,
                side_effects=sorted(defn.side_effects, key=_side_effect_sort_key),
                allowed_session_modes=sorted(
                    defn.allowed_session_modes, key=_session_mode_sort_key
                ),
            )
        )

    return ToolRegistrySchema(tools=public_tools)


def _side_effect_sort_key(se: SideEffect) -> str:
    """Deterministic sort key for ``SideEffect`` enum values."""
    return se.value


def _session_mode_sort_key(sm: SessionMode) -> str:
    """Deterministic sort key for ``SessionMode`` enum values."""
    return sm.value
