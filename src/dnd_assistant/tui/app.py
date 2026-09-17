"""Production Textual app shell (TUI-03).

Presentation-only: the app owns no canonical semantics and no write policy.
Registry metadata feeds bindings, the command palette and footer hints; every
command resolves through one :class:`SemanticDispatcher`.

Command palette ownership
-------------------------

``ENABLE_COMMAND_PALETTE`` is disabled so Textual does not auto-install a
``priority=True`` ``ctrl+p`` binding. ``ctrl+p`` is instead a registry-owned
ordinary alias for the ``app.command-palette`` semantic command, which pushes
Textual's :class:`~textual.command.CommandPalette`. This keeps physical keys as
replaceable aliases and keeps a single dispatch path.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import ClassVar, cast

from textual.app import App, SystemCommand
from textual.binding import BindingType
from textual.command import CommandPalette
from textual.screen import Screen

from dnd_assistant.tui.bindings import build_bindings
from dnd_assistant.tui.commands import (
    DEFAULT_REGISTRY,
    CommandContext,
    CommandRegistry,
)
from dnd_assistant.tui.dispatch import (
    CommandAvailability,
    DispatchResult,
    SemanticDispatcher,
)
from dnd_assistant.tui.screens import ShellScreen

__all__ = ["DndTuiApp", "DEFAULT_BINDINGS"]


DEFAULT_BINDINGS: list[BindingType] = list(build_bindings(DEFAULT_REGISTRY))


class DndTuiApp(App[None]):
    """The production D&D Session Assistant TUI shell."""

    TITLE = "D&D Session Assistant"

    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False
    """The palette is opened by the registry-owned ``app.command-palette``."""

    SEMANTIC_REGISTRY: ClassVar[CommandRegistry] = DEFAULT_REGISTRY
    """Semantic command registry backing this app class."""

    BINDINGS: ClassVar[list[BindingType]] = DEFAULT_BINDINGS
    """Registry-derived bindings (never hand-maintained)."""

    DEFAULT_SCREEN: ClassVar[type[Screen[None]]] = ShellScreen
    """The screen class mounted as the initial shell."""

    def __init__(self, registry: CommandRegistry | None = None) -> None:
        super().__init__()
        self._semantic_registry = registry if registry is not None else self.SEMANTIC_REGISTRY
        self._dispatcher = SemanticDispatcher(self._semantic_registry, self, self._current_context)

    # ── Lifecycle / shell ───────────────────────────────────────────────────

    def get_default_screen(self) -> Screen[None]:
        """Mount the production shell screen as the initial screen."""
        return self.DEFAULT_SCREEN(id="shell")

    def _current_context(self) -> CommandContext:
        screen_stack = self.screen_stack
        screen = screen_stack[-1] if screen_stack else None
        context_id = getattr(screen, "CONTEXT_ID", "") if screen is not None else ""
        return CommandContext(context_id=context_id)

    # ── CommandHost implementation ──────────────────────────────────────────

    def quit_app(self) -> None:
        """Request application shutdown."""
        self.exit()

    def open_command_palette(self) -> None:
        """Open Textual's command palette once."""
        if not CommandPalette.is_open(cast("App[object]", self)):
            self.push_screen(CommandPalette(id="--command-palette"))

    def show_help(self) -> None:
        """Show the key/help panel."""
        self.action_show_help_panel()

    # ── Semantic dispatch integration ───────────────────────────────────────

    def run_semantic_command(self, command_id: str) -> DispatchResult:
        """Dispatch a semantic command through the single dispatcher."""
        return self._dispatcher.dispatch(command_id)

    def action_semantic_dispatch(self, command_id: str) -> None:
        """Generic Textual action used by every registry-derived binding."""
        self.run_semantic_command(command_id)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Map presentation predicates onto Textual action state.

        ``True`` enabled+visible, ``None`` disabled+visible (dimmed),
        ``False`` hidden. This is presentation guidance, not authorization.
        """
        if action == "semantic_dispatch" and parameters:
            availability = self._dispatcher.evaluate(str(parameters[0]))
            if availability is CommandAvailability.ENABLED:
                return True
            if availability is CommandAvailability.DISABLED:
                return None
            return False
        return super().check_action(action, parameters)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Yield registry-derived command palette entries for a calling screen."""
        context = CommandContext(context_id=getattr(screen, "CONTEXT_ID", ""))
        for command in self._dispatcher.palette_commands(context):
            yield SystemCommand(
                command.title,
                command.description,
                partial(self.run_semantic_command, command.id),
            )
