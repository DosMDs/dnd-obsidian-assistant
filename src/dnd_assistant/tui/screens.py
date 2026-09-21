"""Production TUI screens (TUI-03 shell, agent-workspace redesign TUI-UX-01).

Presentation-only.  :class:`MainScreen` is the persistent agent workspace: the
assistant transcript and composer on the left, the campaign sidebar on the
right.  :class:`SessionScreen` is a secondary, context-safe screen for the
session lifecycle; it is pushed through the semantic ``view.session`` command
and popped through ``view.assistant``.

The active screen's ``CONTEXT_ID`` is the semantic command context id, so
screen-scoped commands are offered only where they actually apply.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from dnd_assistant.tui.assistant import AssistantView
from dnd_assistant.tui.session import SessionView
from dnd_assistant.tui.sidebar import SidebarView

__all__ = ["MainScreen", "SessionScreen"]


class MainScreen(Screen[None]):
    """The default production screen: assistant workspace plus sidebar."""

    CONTEXT_ID: ClassVar[str] = "assistant"
    """Semantic command context of the main workspace."""

    AUTO_FOCUS: ClassVar[str | None] = "#assistant-query"
    """Focus the composer on launch (not a container)."""

    BINDINGS: ClassVar[list[BindingType]] = []
    """Screen-level bindings (none; registry commands are app-level)."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main-body"):
            yield AssistantView(id="assistant-view")
            yield SidebarView(id="campaign-sidebar")
        yield Footer()

    def on_mount(self) -> None:
        """Ask the app to wire capability views and run the startup refresh."""
        wire = getattr(self.app, "_wire_capability_views", None)
        if callable(wire):
            wire()
        startup = getattr(self.app, "_startup_refresh", None)
        if callable(startup):
            startup()


class SessionScreen(Screen[None]):
    """Secondary session lifecycle screen (semantic ``view.session``)."""

    CONTEXT_ID: ClassVar[str] = "session"
    """Semantic command context of the session screen."""

    AUTO_FOCUS: ClassVar[str | None] = "#session-note-input"
    """Focus the note input when the screen opens."""

    BINDINGS: ClassVar[list[BindingType]] = []
    """No screen-local bindings: ``escape``/``f2`` are registry aliases for the
    semantic ``view.assistant`` command, so return navigation keeps one path."""

    def compose(self) -> ComposeResult:
        # No Header here: the pushed screen replaces the main workspace; the
        # footer key hints are sufficient and avoid a redundant title bar.
        yield SessionView(id="session-view")
        yield Footer()

    def on_mount(self) -> None:
        """Wire the session view, then load the trusted status."""
        wire = getattr(self.app, "_wire_capability_views", None)
        if callable(wire):
            wire()
        self.query_one(SessionView).refresh_status()
