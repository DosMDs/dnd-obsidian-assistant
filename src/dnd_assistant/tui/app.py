"""Production Textual app (TUI-03 shell, extended in TUI-04).

Presentation-only: the app owns no canonical semantics and no write policy.
It owns the immutable launch context, the shared in-flight gate and one
semantic dispatcher.  Domain-facing command handlers are thin delegations to
the capability views; capability work, worker hosting and UI updates stay in
those views.

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
from textual.widgets import TabbedContent

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
from dnd_assistant.tui.screens import MainScreen
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices
from dnd_assistant.tui.session import SessionView
from dnd_assistant.tui.styles import RESPONSIVE_CSS
from dnd_assistant.tui.view import CapabilityView

__all__ = ["DndTuiApp", "DEFAULT_BINDINGS"]


DEFAULT_BINDINGS: list[BindingType] = list(build_bindings(DEFAULT_REGISTRY))

_ViewT = TypeVar("_ViewT", bound=CapabilityView)

_PRIMARY_FOCUS: dict[str, str] = {
    "assistant": "#assistant-query",
    "session": "#session-note-input",
    "campaign-state": "#campaign-state-reload",
}
"""Post-navigation focus target per primary view context id."""

_MAX_FOCUS_ATTEMPTS = 10
"""Bounded refresh retries while a requested pane becomes displayable."""


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
        self._wired = False
        self._nav_generation = 0
        self._dispatcher = SemanticDispatcher(self.SEMANTIC_REGISTRY, self, self._current_context)

    # ── Lifecycle / wiring ──────────────────────────────────────────────────

    def get_default_screen(self) -> Screen[None]:
        """Mount the production main screen as the initial screen."""
        return self.DEFAULT_SCREEN(id="shell")

    def on_mount(self) -> None:
        """Wire capability views after the initial screen is mounted."""
        self._wire_capability_views()

    def _wire_capability_views(self) -> None:
        if self._wired:
            return
        views = list(self.query(CapabilityView))
        if not views:
            return
        self._wired = True
        for view in views:
            view.configure(host=self, gate=self._gate)
        for assistant_view in self.query(AssistantView):
            assistant_view.set_capabilities(
                assistant=self._services.assistant,
                session=self._services.session,
            )
        for session_view in self.query(SessionView):
            session_view.set_capabilities(session=self._services.session)
        for campaign_view in self.query(CampaignStateView):
            campaign_view.set_capabilities(campaign_state=self._services.campaign_state)
        self.refresh_command_state()
        for session_view in self.query(SessionView):
            session_view.refresh_status()
        for campaign_view in self.query(CampaignStateView):
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
            resolver = getattr(screen, "current_context_id", None)
            if callable(resolver):
                context_id = str(resolver())
            else:
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
        """Switch the primary view by stable id and focus its primary control.

        Focus is scheduled after the next refresh because Textual may defer the
        active-pane display change; the target is then proven by headless tests.
        """
        tabs = next(iter(self.query(TabbedContent)), None)
        if tabs is None:
            return
        self._nav_generation += 1
        generation = self._nav_generation
        tabs.active = view_id
        self.refresh_command_state()
        self.call_after_refresh(self._focus_primary_view, view_id, generation)

    def _focus_primary_view(self, view_id: str, generation: int, attempt: int = 0) -> None:
        """Focus the primary control of the latest requested view.

        Navigation schedules this through ``call_after_refresh``.  Textual may
        deliver a late ``TabPane.Focused`` message for an earlier pane, which
        re-activates that stale pane and can hide the requested pane before its
        control is displayed.  A monotonically increasing generation makes the
        last navigation authoritative: stale callbacks cannot re-activate an
        abandoned pane, the requested pane is re-asserted, and focus is retried
        across refreshes until the control is displayed.  No sleeps or timers
        are used; convergence is driven by the refresh cycle.
        """
        if generation != self._nav_generation:
            return
        tabs = next(iter(self.query(TabbedContent)), None)
        if tabs is None:
            return
        if tabs.active != view_id:
            # Re-assert against a stale pane activation event.
            tabs.active = view_id
        selector = _PRIMARY_FOCUS.get(view_id)
        if selector is None:
            return
        try:
            target = self.query_one(selector)
        except NoMatches:
            return
        if getattr(target, "focusable", False) and target.display:
            target.focus()
            if self.focused is target:
                return
        if attempt < _MAX_FOCUS_ATTEMPTS:
            self.call_after_refresh(self._focus_primary_view, view_id, generation, attempt + 1)

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
        matches = list(self.query(view_type))
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
