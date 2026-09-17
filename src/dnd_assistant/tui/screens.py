"""Production TUI shell screen (TUI-03).

A minimal, stable host for later track tasks. It composes only shell chrome and
a placeholder body: it opens no Vault/model/session state.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

__all__ = ["ShellScreen"]


class ShellScreen(Screen[None]):
    """The default production shell screen."""

    CONTEXT_ID: ClassVar[str] = "shell"
    """Presentation context id used by screen/context command scope."""

    BINDINGS: ClassVar[list[BindingType]] = []
    """Screen-level bindings (none yet; registry commands are app-level)."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("D&D Session Assistant", id="shell-body")
        yield Footer()
