"""Production TUI main screen (TUI-03 shell evolved in TUI-04).

Presentation-only.  The screen hosts the three primary capability views in a
native Textual ``TabbedContent`` so navigation introduces no deep screen stack
and no custom navigation framework.  The active pane id is the semantic
command context id.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, TabbedContent, TabPane

from dnd_assistant.tui.assistant import AssistantView
from dnd_assistant.tui.campaign_state import CampaignStateView
from dnd_assistant.tui.session import SessionView

__all__ = ["MainScreen"]


class MainScreen(Screen[None]):
    """The default production screen with the three primary views."""

    CONTEXT_ID: ClassVar[str] = "assistant"
    """Fallback context id when no tab is active yet."""

    BINDINGS: ClassVar[list[BindingType]] = []
    """Screen-level bindings (none; registry commands are app-level)."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(id="primary-tabs", initial="assistant"):
            with TabPane("Ассистент", id="assistant"):
                yield AssistantView(id="assistant-view")
            with TabPane("Сессия", id="session"):
                yield SessionView(id="session-view")
            with TabPane("Состояние кампании", id="campaign-state"):
                yield CampaignStateView(id="campaign-state-view")
        yield Footer()

    def on_mount(self) -> None:
        """Ask the app to wire capability views once they are mounted."""
        wire = getattr(self.app, "_wire_capability_views", None)
        if callable(wire):
            wire()

    def current_context_id(self) -> str:
        """Return the active primary-view context id."""
        return self.query_one(TabbedContent).active or self.CONTEXT_ID
