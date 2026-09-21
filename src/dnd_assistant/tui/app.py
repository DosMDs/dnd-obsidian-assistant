"""Production Textual app (TUI-03 shell, agent-workspace redesign TUI-UX-01).

Presentation-only: the app owns no canonical semantics and no write policy.
It owns the immutable launch context, the shared in-flight gate and one
semantic dispatcher.  Domain-facing command handlers are thin delegations to
the capability views; capability work, worker hosting and UI updates stay in
those views.

Navigation model
----------------

There is one persistent main workspace (:class:`MainScreen`,
``CONTEXT_ID="assistant"``) and one secondary :class:`SessionScreen`
(``CONTEXT_ID="session"``).  ``view.session`` opens the session screen and
``view.assistant`` returns to the main workspace; both are idempotent and
cannot stack duplicate screens.  Screen-scoped commands resolve against the
active screen's context, so commands that belong to the main workspace (the
assistant composer and the visible campaign sidebar) are never offered from
the session screen.

Command palette ownership
-------------------------

``ENABLE_COMMAND_PALETTE`` is disabled so Textual does not auto-install a
``priority=True`` ``ctrl+p`` binding.  ``ctrl+p`` is instead a registry-owned
ordinary alias for the ``app.command-palette`` semantic command, which pushes
Textual's :class:`~textual.command.CommandPalette`.  This keeps physical keys
as replaceable aliases and keeps a single dispatch path.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import Any, ClassVar, TypeVar, cast

from textual.app import App, SystemCommand
from textual.binding import BindingType
from textual.command import CommandPalette
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import TextArea

from dnd_assistant.tui.assistant import AssistantView
from dnd_assistant.tui.bindings import build_bindings
from dnd_assistant.tui.campaign_state import CampaignStateView
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
from dnd_assistant.tui.inflight import InFlightGate
from dnd_assistant.tui.screens import MainScreen, SessionScreen
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices
from dnd_assistant.tui.session import SessionView
from dnd_assistant.tui.sidebar import SidebarView
from dnd_assistant.tui.styles import RESPONSIVE_CSS
from dnd_assistant.tui.view import CapabilityView

__all__ = ["DndTuiApp", "DEFAULT_BINDINGS"]


DEFAULT_BINDINGS: list[BindingType] = list(build_bindings(DEFAULT_REGISTRY))

_ViewT = TypeVar("_ViewT", bound=CapabilityView)

_MAX_FOCUS_ATTEMPTS = 10
"""Bounded refresh retries while a requested screen becomes displayable."""


class DndTuiApp(App[None]):
    """The production D&D Session Assistant TUI."""

    TITLE = "D&D Session Assistant"

    CSS: ClassVar[str] = RESPONSIVE_CSS
    """Responsive presentation styles (packaged with the module, no asset)."""

    HORIZONTAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] | None = [
        (0, "-w-tiny"),
        (60, "-w-narrow"),
        (80, "-w-baseline"),
        (100, "-w-reference"),
    ]
    """Ascending minimum-width classes applied to the active Screen.

    Contract: reference 100x30, baseline 80x24, minimum usable 60x20; below
    that the layout is a degraded scrollable form and is not claimed usable.
    """

    VERTICAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] | None = [
        (0, "-h-tiny"),
        (12, "-h-short"),
        (20, "-h-baseline"),
        (30, "-h-reference"),
    ]
    """Ascending minimum-height classes applied to the active Screen."""

    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False
    """The palette is opened by the registry-owned ``app.command-palette``."""

    SEMANTIC_REGISTRY: ClassVar[CommandRegistry] = DEFAULT_REGISTRY
    """Semantic command registry backing this app class."""

    BINDINGS: ClassVar[list[BindingType]] = DEFAULT_BINDINGS
    """Registry-derived bindings (never hand-maintained)."""

    DEFAULT_SCREEN: ClassVar[type[Screen[None]]] = MainScreen
    """The screen class mounted as the initial shell."""

    def __init__(self, services: TuiServices) -> None:
        super().__init__()
        self._services = services
        self._gate = InFlightGate()
        self._has_active_session = False
        self._startup_refreshed = False
        self._dispatcher = SemanticDispatcher(self.SEMANTIC_REGISTRY, self, self._current_context)

    # ── Lifecycle / wiring ──────────────────────────────────────────────────

    def get_default_screen(self) -> Screen[None]:
        """Mount the production main screen as the initial screen."""
        return self.DEFAULT_SCREEN(id="shell")

    def on_mount(self) -> None:
        """Wire capability views and perform the one-time startup refresh."""
        self._wire_capability_views()
        self._startup_refresh()

    def _startup_refresh(self) -> None:
        """Perform the one-time sidebar/campaign refresh once mounted.

        The real terminal/screen subtree may not be queryable during
        ``App.on_mount`` on every Textual build, so the main screen also calls
        this after its own mount; the guard keeps it exactly-once.
        """
        if self._startup_refreshed:
            return
        if not self._query_all(CampaignStateView):
            return
        self._startup_refreshed = True
        self._refresh_sidebar()

    def _query_all(self, view_type: type[_ViewT]) -> list[_ViewT]:
        """Query every mounted screen for a view type.

        ``App.query`` only walks the default screen's DOM, so pushed screens
        (the session screen) are queried through ``screen_stack`` explicitly.
        """
        found: list[_ViewT] = []
        for screen in self.screen_stack:
            found.extend(screen.query(view_type))
        return found

    def _wire_capability_views(self) -> None:
        """Idempotently wire every currently mounted capability view.

        Called for the main workspace and again when the session screen mounts;
        already-configured views are left untouched.
        """
        for view in self._query_all(CapabilityView):
            if not view.is_configured:
                view.configure(host=self, gate=self._gate)
        for assistant_view in self._query_all(AssistantView):
            assistant_view.set_capabilities(
                assistant=self._services.assistant,
                session=self._services.session,
            )
        for session_view in self._query_all(SessionView):
            session_view.set_capabilities(session=self._services.session)
        for sidebar_view in self._query_all(SidebarView):
            sidebar_view.set_capabilities(session=self._services.session)
        for campaign_view in self._query_all(CampaignStateView):
            campaign_view.set_capabilities(campaign_state=self._services.campaign_state)
        self.refresh_command_state()

    def _refresh_sidebar(self) -> None:
        """Re-read the trusted session status and campaign state for the sidebar."""
        for sidebar_view in self._query_all(SidebarView):
            sidebar_view.refresh_session()
        for campaign_view in self._query_all(CampaignStateView):
            campaign_view.reload()

    # ── TuiHost surface ─────────────────────────────────────────────────────

    @property
    def launch_context(self) -> TuiLaunchContext:
        """The immutable launch context."""
        return self._services.launch

    def acquire_exclusive(self, owner: str) -> bool:
        return self._gate.acquire(owner)

    def release_exclusive(self, owner: str) -> None:
        self._gate.release(owner)

    def set_active_session(self, active: bool) -> None:
        self._has_active_session = active
        self.refresh_command_state()

    def refresh_command_state(self) -> None:
        """Re-evaluate Textual action state from presentation predicates."""
        self.refresh_bindings()

    def notify_user(self, message: str, *, severity: str = "warning") -> None:
        self.notify(message, severity=severity)  # type: ignore[arg-type]

    # ── Command context ─────────────────────────────────────────────────────

    def _current_context(self) -> CommandContext:
        return self._context_for(self.screen)

    def _context_for(self, screen: Screen[Any] | None) -> CommandContext:
        context_id = ""
        if screen is not None:
            context_id = str(getattr(screen, "CONTEXT_ID", ""))
        return CommandContext(
            context_id=context_id,
            busy_owner=self._gate.owner,
            has_active_session=self._has_active_session,
            write_intent_available=self._services.launch.allow_agent_write,
        )

    # ── CommandHost implementation ──────────────────────────────────────────

    def quit_app(self) -> None:
        """Request shutdown unless trusted work is in flight."""
        if self._gate.is_busy:
            self.notify_user("Операция выполняется. Дождитесь завершения.")
            return
        self.exit()

    def open_command_palette(self) -> None:
        """Open Textual's command palette once."""
        if not CommandPalette.is_open(cast("App[object]", self)):
            self.push_screen(CommandPalette(id="--command-palette"))

    def show_help(self) -> None:
        """Toggle the key/help panel (show when hidden, hide when open).

        The panel never takes focus, so hiding it leaves the previously focused
        widget intact.  Toggling is presentation-only and keeps the accepted
        ``app.help`` semantic command as the single discoverable surface.
        """
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def navigate_to(self, view_id: str) -> None:
        """Navigate by stable semantic view id (idempotent, context-safe)."""
        if view_id == "session":
            self._open_session()
        elif view_id == "assistant":
            self._return_to_assistant()
        # Unknown/removed ids are ignored (no dead navigation).

    def _open_session(self) -> None:
        """Push the session screen once; repeated dispatch is a no-op."""
        if isinstance(self.screen, SessionScreen):
            return
        self.push_screen(SessionScreen(id="session-screen"))
        self.refresh_command_state()

    def _return_to_assistant(self) -> None:
        """Return to the main workspace, converged and focused.

        The sidebar is re-read only when a secondary screen was actually
        popped; focusing the composer on the already-active workspace (for
        example the global ``escape``/``f2`` alias) must not trigger a campaign
        reload.
        """
        popped = isinstance(self.screen, SessionScreen)
        if popped:
            self.pop_screen()
        self.refresh_command_state()
        self.call_after_refresh(self._focus_assistant, 0)
        if popped:
            self.call_after_refresh(self._converge_sidebar)

    def _focus_assistant(self, attempt: int) -> None:
        """Focus the composer once the main workspace is displayable."""
        try:
            target = self.screen.query_one("#assistant-query", TextArea)
        except NoMatches:
            return
        if getattr(target, "focusable", False) and target.display:
            target.focus()
            if self.focused is target:
                return
        if attempt < _MAX_FOCUS_ATTEMPTS:
            self.call_after_refresh(self._focus_assistant, attempt + 1)

    def _converge_sidebar(self) -> None:
        """Re-read sidebar data after returning from the session screen."""
        self._refresh_sidebar()

    def assistant_submit(self) -> None:
        view = self._first(AssistantView)
        if view is not None:
            view.submit_request()

    def assistant_toggle_write(self) -> None:
        view = self._first(AssistantView)
        if view is not None:
            view.toggle_write()

    def session_refresh(self) -> None:
        view = self._first(SessionView)
        if view is not None:
            view.refresh_status()

    def session_start(self) -> None:
        view = self._first(SessionView)
        if view is not None:
            view.start_session()

    def session_note(self) -> None:
        view = self._first(SessionView)
        if view is not None:
            view.add_note()

    def session_end(self) -> None:
        view = self._first(SessionView)
        if view is not None:
            view.end_session()

    def campaign_state_reload(self) -> None:
        view = self._first(CampaignStateView)
        if view is not None:
            view.reload()

    def campaign_state_rebuild(self) -> None:
        view = self._first(CampaignStateView)
        if view is not None:
            view.rebuild()

    def _first(self, view_type: type[_ViewT]) -> _ViewT | None:
        matches = self._query_all(view_type)
        return matches[0] if matches else None

    # ── Semantic dispatch integration ───────────────────────────────────────

    @property
    def semantic_registry(self) -> CommandRegistry:
        """The single class-level semantic registry authority for this app class.

        Bindings (``BINDINGS``) and the dispatcher/palette both resolve against
        this one registry; there is no instance-level registry override.
        """
        return self._dispatcher.registry

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
        context = self._context_for(screen)
        for command in self._dispatcher.palette_commands(context):
            yield SystemCommand(
                command.title,
                command.description,
                partial(self.run_semantic_command, command.id),
            )
