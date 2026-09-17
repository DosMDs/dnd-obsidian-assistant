"""Registry → Textual binding adapter (TUI-03).

The semantic registry is canonical for the stable ID, title, description and
default key aliases. This adapter translates that metadata into Textual
:class:`~textual.binding.Binding` objects. There is no duplicated handwritten
production ``BINDINGS`` table.

All registry-generated bindings are ordinary (``priority=False``). A printable
single-key global binding must never be priority, otherwise it would bypass
focused-widget focus protection.

Effective-key collision
-----------------------

Raw alias equality across overlapping scopes is rejected by the registry itself
(Textual-free). This adapter additionally rejects collisions **after Textual's
own key normalization** by building a framework :class:`BindingsMap` and
inspecting its effective keys. Textual's internal normalization table is not
duplicated here.
"""

from __future__ import annotations

from textual.binding import Binding, BindingsMap

from dnd_assistant.tui.commands import CommandRegistry, scopes_overlap

__all__ = [
    "CommandBindingError",
    "build_bindings",
    "semantic_action",
]


class CommandBindingError(ValueError):
    """Raised when registry bindings collide after Textual key normalization."""


def semantic_action(command_id: str) -> str:
    """Return the generic Textual action string for a semantic command id."""
    return f"semantic_dispatch({command_id!r})"


def build_bindings(registry: CommandRegistry) -> list[Binding]:
    """Build non-priority Textual bindings from registry metadata.

    Raises:
        CommandBindingError: two commands with overlapping scopes resolve to the
            same effective key after Textual normalization.
    """
    bindings = [
        Binding(
            ",".join(command.default_keys),
            semantic_action(command.id),
            command.title,
            id=command.id,
            tooltip=command.description,
            priority=False,
        )
        for command in registry.commands
        if command.default_keys
    ]
    _reject_effective_collisions(registry, bindings)
    return bindings


def _reject_effective_collisions(registry: CommandRegistry, bindings: list[Binding]) -> None:
    effective = BindingsMap(bindings)
    for key, key_bindings in effective.key_to_bindings.items():
        if len(key_bindings) < 2:
            continue
        for index, binding in enumerate(key_bindings):
            command = registry.get(binding.id) if binding.id is not None else None
            if command is None:
                continue
            for other in key_bindings[index + 1 :]:
                other_command = registry.get(other.id) if other.id is not None else None
                if other_command is None:
                    continue
                if scopes_overlap(command.scope, other_command.scope):
                    raise CommandBindingError(
                        f"effective key {key!r} is shared by overlapping commands "
                        f"{command.id!r} and {other_command.id!r} after Textual normalization"
                    )
