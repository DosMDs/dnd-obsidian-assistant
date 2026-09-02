"""ToolRegistry — registry of callable tools.

Responsibility
──────────────
Owns: tool definitions, tool metadata, tool lookup.
Must not own: tool execution logic, tool result handling.
Failure boundary: raises NotFoundError for unknown tools,
                  ConflictError for duplicate names,
                  ValidationError for invalid definitions/handlers.

Registry itself must not call handlers.
Registry has no filesystem access and no dependency on:
    storage, domain, models, retrieval, application, cli, ollama
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError
from dnd_assistant.tools.types import ToolBinding, ToolDefinition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dnd_assistant.tools.types import Handler


class ToolRegistry:
    """Registry for tool definitions and their callable handlers.

    Provides deterministic lookup and listing. Does not execute handlers.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, ToolBinding] = {}

    # ── Registration ─────────────────────────────────────────────────────

    def register(self, definition: ToolDefinition, handler: Handler) -> None:
        """Register a tool definition with its callable handler.

        Args:
            definition: The tool definition.
            handler: The callable handler.

        Raises:
            ValidationError: The definition is invalid or the handler is
                not callable.
            ConflictError: A tool with the same name is already registered.
        """
        if not isinstance(definition, ToolDefinition):
            raise ValidationError("definition must be a ToolDefinition instance")

        if not callable(handler):
            raise ValidationError("handler must be callable")

        if definition.name in self._bindings:
            raise ConflictError(f"Tool '{definition.name}' is already registered")

        self._bindings[definition.name] = ToolBinding(
            definition=definition,
            handler=handler,
        )

    # ── Lookup ───────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolBinding:
        """Look up a registered tool by name.

        Args:
            name: The tool name.

        Returns:
            The ``ToolBinding`` for the named tool.

        Raises:
            NotFoundError: No tool with the given name is registered.
        """
        binding = self._bindings.get(name)
        if binding is None:
            raise NotFoundError(f"Unknown tool: '{name}'")
        return binding

    def get_definition(self, name: str) -> ToolDefinition:
        """Look up a registered tool definition by name.

        Args:
            name: The tool name.

        Returns:
            The ``ToolDefinition`` for the named tool.

        Raises:
            NotFoundError: No tool with the given name is registered.
        """
        return self.get(name).definition

    # ── Listing ──────────────────────────────────────────────────────────

    def list_definitions(self) -> Sequence[ToolDefinition]:
        """Return all registered tool definitions in deterministic order.

        The order is sorted by tool name, independent of registration order.
        """
        return tuple(
            binding.definition
            for binding in sorted(
                self._bindings.values(),
                key=lambda b: b.definition.name,
            )
        )

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._bindings)
