"""TUI launch entry point (TUI-03).

Imported lazily by ``dnd_assistant.cli.main``'s ``dnd tui`` command so that a
normal CLI import does not load this package or Textual.
"""

from __future__ import annotations

from dnd_assistant.tui.app import DndTuiApp

__all__ = ["run"]


def run() -> None:
    """Run the production TUI shell in the current terminal."""
    DndTuiApp().run()
