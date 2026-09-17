"""Single semantic command dispatcher (TUI-03).

Both physical-key bindings and command-palette selections resolve to a stable
semantic command ID and pass through exactly one :class:`SemanticDispatcher`,
which invokes exactly one registered handler.

This module is deliberately Textual-free: the dispatcher only evaluates
``scope`` / ``applicable`` / ``enabled`` presentation predicates and invokes the
handler. It contains no authorization or write policy. Handler exceptions are
not caught; they propagate so later track tasks can present and debug them.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from dnd_assistant.tui.commands import (
    CommandContext,
    CommandHost,
    CommandRegistry,
    SemanticCommand,
)

__all__ = [
    "CommandAvailability",
    "DispatchResult",
    "SemanticDispatcher",
]


class CommandAvailability(Enum):
    """Presentation availability of a semantic command."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    INAPPLICABLE = "inapplicable"
    UNKNOWN = "unknown"


class DispatchResult(Enum):
    """Outcome of a dispatch attempt."""

    EXECUTED = "executed"
    DISABLED = "disabled"
    INAPPLICABLE = "inapplicable"
    UNKNOWN_COMMAND = "unknown_command"


_AVAILABILITY_TO_RESULT = {
    CommandAvailability.DISABLED: DispatchResult.DISABLED,
    CommandAvailability.INAPPLICABLE: DispatchResult.INAPPLICABLE,
    CommandAvailability.UNKNOWN: DispatchResult.UNKNOWN_COMMAND,
}


class SemanticDispatcher:
    """Evaluate and dispatch semantic commands through one execution path."""

    def __init__(
        self,
        registry: CommandRegistry,
        host: CommandHost,
        context_provider: Callable[[], CommandContext],
    ) -> None:
        self._registry = registry
        self._host = host
        self._context_provider = context_provider

    @property
    def registry(self) -> CommandRegistry:
        """The registry this dispatcher resolves commands against."""
        return self._registry

    def evaluate(self, command_id: str) -> CommandAvailability:
        """Return the presentation availability of a command."""
        command = self._registry.get(command_id)
        if command is None:
            return CommandAvailability.UNKNOWN

        context = self._context_provider()
        scope = command.scope
        if scope.context_id is not None and scope.context_id != context.context_id:
            return CommandAvailability.INAPPLICABLE
        if command.applicable is not None and not command.applicable(context):
            return CommandAvailability.INAPPLICABLE
        if command.enabled is not None and not command.enabled(context):
            return CommandAvailability.DISABLED
        return CommandAvailability.ENABLED

    def dispatch(self, command_id: str) -> DispatchResult:
        """Invoke the command handler exactly once iff it is enabled.

        Unknown, disabled and inapplicable commands execute zero handlers.
        """
        command = self._registry.get(command_id)
        if command is None:
            return DispatchResult.UNKNOWN_COMMAND

        availability = self.evaluate(command_id)
        if availability is not CommandAvailability.ENABLED:
            return _AVAILABILITY_TO_RESULT[availability]

        command.handler(self._host)
        return DispatchResult.EXECUTED

    def palette_commands(self, context: CommandContext) -> tuple[SemanticCommand, ...]:
        """Return palette-eligible commands for an explicit context.

        ``palette=False``, context-inapplicable and disabled commands are
        omitted.
        """
        eligible: list[SemanticCommand] = []
        for command in self._registry.commands:
            if not command.palette:
                continue
            scope = command.scope
            if scope.context_id is not None and scope.context_id != context.context_id:
                continue
            if command.applicable is not None and not command.applicable(context):
                continue
            if command.enabled is not None and not command.enabled(context):
                continue
            eligible.append(command)
        return tuple(eligible)
