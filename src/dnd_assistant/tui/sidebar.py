"""Persistent campaign sidebar (TUI-UX-01).

Presentation only.  The sidebar exposes currently available, already-accepted
PLAYER-safe information without the user leaving the assistant workspace:

- launch profile / agent-write mode;
- the current session summary from the trusted ``SessionCapability.status()``
  read;
- the Campaign-State panel (exact trusted status + PLAYER-projected
  recently-touched references) supplied by the nested
  :class:`~dnd_assistant.tui.campaign_state.CampaignStateView`.

It invents no campaign semantics: no current location, no active quest, no
importance and no party objective are inferred from ``recently_touched`` order
or any other proxy.  The sidebar owns no canonical state; it re-reads the
existing trusted capabilities and only renders their results.

Session status convergence is presentation-level coordination: the
``SessionScreen`` performs the trusted mutations; the sidebar re-reads
``SessionCapability.status()`` when the main workspace becomes visible again.
No second source of truth and no duplicated domain logic are introduced.
"""

from __future__ import annotations

from typing import Any, cast

from textual.app import ComposeResult
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from dnd_assistant.domain.session import Session
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.tui.campaign_state import CampaignStateView
from dnd_assistant.tui.errors import render_expected_error
from dnd_assistant.tui.services import SessionCapability, SessionOutcome
from dnd_assistant.tui.view import CapabilityView

__all__ = ["SidebarView", "render_session_summary"]

_READ_GROUP = "sidebar-session-read"


def render_session_summary(session: Session) -> str:
    """Render a compact PLAYER-safe session summary for the sidebar."""
    return (
        f"Сессия {session.id}\n"
        f"  Статус: {session.status}\n"
        f"  Начальный такт: {session.world_tick_start}"
    )


class SidebarView(CapabilityView):
    """Persistent right-hand campaign/session sidebar.

    The sidebar only starts an ungated, independent session-status read (see
    :meth:`refresh_session`); it never acquires the exclusive in-flight gate
    (the nested ``CampaignStateView`` owns Campaign-State exclusivity).  Its
    worker-state handler is therefore overridden for the read group and
    ``WORKER_OWNER`` is intentionally empty (never passed to the gate).
    """

    WORKER_OWNER = ""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session: SessionCapability | None = None

    # ── Composition / wiring ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("Кампания", id="sidebar-title")
        yield Static("", id="sidebar-profile")
        yield Static("Сессия", id="sidebar-section-session")
        yield Static("Статус сессии не загружен.", id="sidebar-session-status")
        yield Button("Открыть сессию…", id="sidebar-open-session")
        yield CampaignStateView(id="campaign-state-view")

    def set_capabilities(self, *, session: SessionCapability) -> None:
        self._session = session

    def on_configured(self) -> None:
        self._sync_profile()

    # ── Event → semantic dispatch convergence ───────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sidebar-open-session":
            self.host.run_semantic_command("view.session")

    # ── Session status refresh (independent read, not gated) ────────────────

    def refresh_session(self) -> None:
        """Re-read the trusted session status and update the summary."""
        if self._session is None or self._host is None:
            return
        self.run_worker(
            self._read_session,
            name="sidebar.session.status",
            group=_READ_GROUP,
            thread=True,
            exit_on_error=False,
        )

    def _read_session(self) -> SessionOutcome:
        assert self._session is not None
        try:
            session = self._session.status()
        except DndAssistantError as exc:
            return SessionOutcome(ok=False, message=render_expected_error(exc))
        if session is None:
            return SessionOutcome(ok=True, message="Активной сессии нет.", active_session=False)
        return SessionOutcome(ok=True, message=render_session_summary(session), active_session=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != _READ_GROUP:
            return
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        if event.state is WorkerState.SUCCESS:
            self._apply_session(cast(SessionOutcome, worker.result))
        elif event.state is WorkerState.ERROR and worker.error is not None:
            raise worker.error

    def _apply_session(self, outcome: SessionOutcome) -> None:
        self.query_one("#sidebar-session-status", Static).update(outcome.message)
        if outcome.active_session is not None:
            self.host.set_active_session(outcome.active_session)

    # ── Presentation sync ───────────────────────────────────────────────────

    def _sync_profile(self) -> None:
        if self._host is None:
            return
        launch = self.host.launch_context
        mode = "запись" if launch.allow_agent_write else "только чтение"
        self.query_one("#sidebar-profile", Static).update(
            f"Профиль: {launch.profile_name}\nРежим агента: {mode}"
        )
