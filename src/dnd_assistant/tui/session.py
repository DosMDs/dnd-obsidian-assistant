"""Session capability view (TUI-04).

Presentation only.  Deterministic session mutations flow through the injected
session capability (trusted ``SessionRuntimeService``) and are serialized with
other exclusive operations through the shared in-flight gate.  Recovery
preflight uses the trusted partition unchanged; blocking issues prevent the
mutation.  Read-only status refresh bypasses the gate (safe repository read).
"""

from __future__ import annotations

from functools import partial
from typing import cast

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static
from textual.worker import Worker, WorkerState

from dnd_assistant.domain.session import Session
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.tui.assistant import render_blocking_recovery
from dnd_assistant.tui.inflight import EXCLUSIVE_SESSION
from dnd_assistant.tui.services import SessionCapability, SessionOutcome
from dnd_assistant.tui.view import CapabilityView

__all__ = ["SessionView"]

_READ_GROUP = "session-read"
_EXTERNALLY_OWNED_HINT = (
    "Примечание: незавершённые операции ChangeSet не блокируют работу; "
    "проверьте `dnd changeset status`."
)


class SessionView(CapabilityView):
    """Player-facing session lifecycle view."""

    WORKER_OWNER = EXCLUSIVE_SESSION

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._session: SessionCapability | None = None
        self._has_active_session = False

    # ── Composition / wiring ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("Сессия", id="session-title")
        yield Static("Статус не загружен.", id="session-status")
        yield Input(placeholder="Текст заметки…", id="session-note-input")
        yield Input(placeholder="ID затронутых сущностей (через запятую)…", id="session-touched")
        with Horizontal(id="session-actions"):
            yield Button("Обновить", id="session-refresh")
            yield Button("Начать", id="session-start", variant="primary")
            yield Button("Заметка", id="session-note")
            yield Button("Завершить", id="session-end")
        yield Static("", id="session-output")
        yield Static("", id="session-hint")

    def set_capabilities(self, *, session: SessionCapability) -> None:
        self._session = session

    def on_configured(self) -> None:
        self._sync_controls()

    # ── Event → semantic dispatch convergence ───────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        mapping = {
            "session-refresh": "session.refresh",
            "session-start": "session.start",
            "session-note": "session.note",
            "session-end": "session.end",
        }
        command_id = mapping.get(button_id or "")
        if command_id is not None:
            self.host.run_semantic_command(command_id)

    # ── Command entry points ────────────────────────────────────────────────

    def refresh_status(self) -> None:
        """Read-only status refresh (not gated)."""
        if self._session is None:
            return
        self.run_worker(
            self._read_status,
            name="session.status",
            group=_READ_GROUP,
            thread=True,
            exit_on_error=False,
        )

    def start_session(self) -> None:
        self._start_exclusive(name="session.start", work=self._run_start)

    def add_note(self) -> None:
        text = self.query_one("#session-note-input", Input).value
        self._start_exclusive(name="session.note", work=partial(self._run_note, text))

    def end_session(self) -> None:
        raw = self.query_one("#session-touched", Input).value
        touched = _parse_touched_ids(raw)
        self._start_exclusive(name="session.end", work=partial(self._run_end, touched))

    # ── Workers (synchronous trusted work; no UI access) ────────────────────

    def _read_status(self) -> SessionOutcome:
        assert self._session is not None
        try:
            session = self._session.status()
        except DndAssistantError as exc:
            return SessionOutcome(ok=False, message=f"Ошибка: {exc}")
        if session is None:
            return SessionOutcome(ok=True, message="Активной сессии нет.", active_session=False)
        return SessionOutcome(ok=True, message=_render_session(session), active_session=True)

    def _run_start(self) -> SessionOutcome:
        blocked, hint = self._preflight()
        if blocked is not None:
            return blocked
        assert self._session is not None
        try:
            session = self._session.start()
        except DndAssistantError as exc:
            return _error_outcome(exc, hint)
        return SessionOutcome(
            ok=True,
            message=f"Сессия {session.id} начата.",
            hint=hint,
            active_session=True,
        )

    def _run_note(self, text: str) -> SessionOutcome:
        blocked, hint = self._preflight()
        if blocked is not None:
            return blocked
        assert self._session is not None
        try:
            event = self._session.note(text)
        except DndAssistantError as exc:
            return _error_outcome(exc, hint)
        return SessionOutcome(ok=True, message=_render_note(event), hint=hint, active_session=True)

    def _run_end(self, touched: tuple[str, ...]) -> SessionOutcome:
        blocked, hint = self._preflight()
        if blocked is not None:
            return blocked
        assert self._session is not None
        try:
            session = self._session.end(touched)
        except DndAssistantError as exc:
            return _error_outcome(exc, hint)
        return SessionOutcome(
            ok=True,
            message=_render_end(session, len(touched)),
            hint=hint,
            active_session=False,
        )

    def _preflight(self) -> tuple[SessionOutcome | None, str | None]:
        """Trusted recovery preflight: return (blocking_error, non-blocking_hint)."""
        assert self._session is not None
        try:
            partition = self._session.recovery_partition()
        except DndAssistantError as exc:
            return _error_outcome(exc, None), None
        if partition.blocking:
            return SessionOutcome(
                ok=False,
                message=render_blocking_recovery(partition),
            ), None
        hint = _EXTERNALLY_OWNED_HINT if partition.externally_owned else None
        return None, hint

    # ── Event-loop UI update ────────────────────────────────────────────────

    def _handle_result(self, result: object) -> None:
        outcome = cast(SessionOutcome, result)
        self.query_one("#session-output", Static).update(outcome.message)
        self.query_one("#session-hint", Static).update(outcome.hint or "")
        if outcome.active_session is not None:
            self._set_active_session(outcome.active_session)
        if outcome.ok:
            self.query_one("#session-note-input", Input).value = ""
            self.refresh_status()
        self._sync_controls()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        super().on_worker_state_changed(event)
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
            self._apply_status(cast(SessionOutcome, worker.result))
        elif event.state is WorkerState.ERROR and worker.error is not None:
            raise worker.error

    def _apply_status(self, outcome: SessionOutcome) -> None:
        self.query_one("#session-status", Static).update(outcome.message)
        if outcome.active_session is not None:
            self._set_active_session(outcome.active_session)
        self._sync_controls()

    def _set_active_session(self, active: bool) -> None:
        self._has_active_session = active
        self.host.set_active_session(active)

    # ── Presentation sync ───────────────────────────────────────────────────

    def _sync_controls(self) -> None:
        if self._host is None:
            return
        has = self._has_active_session
        self.query_one("#session-start", Button).disabled = self._busy or has
        self.query_one("#session-note", Button).disabled = self._busy or not has
        self.query_one("#session-end", Button).disabled = self._busy or not has


def _parse_touched_ids(raw: str) -> tuple[str, ...]:
    """Parse literal stable IDs (comma/whitespace separated); never infer."""
    tokens = raw.replace(",", " ").split()
    return tuple(token for token in tokens if token)


def _render_session(session: Session) -> str:
    return (
        f"Сессия {session.id}\n"
        f"  Статус: {session.status}\n"
        f"  Начало (реальное): {session.real_started_at.isoformat()}\n"
        f"  Начальный такт: {session.world_tick_start}\n"
        f"  Ревизия: {session.revision}"
    )


def _render_note(event: RawSessionEvent) -> str:
    return f"Заметка сохранена.\n  Тип: {event.type}\n  Такт: {event.world_tick}"


def _render_end(session: Session, touched_count: int) -> str:
    finished = session.real_finished_at
    finished_text = finished.isoformat() if finished is not None else "—"
    touch_line = f"\n  Затронуто сущностей: {touched_count}" if touched_count else ""
    return (
        f"Сессия {session.id} завершена.\n"
        f"  Статус: {session.status}\n"
        f"  Окончание (реальное): {finished_text}\n"
        f"  Конечный такт: {session.world_tick_end}\n"
        f"  Ревизия: {session.revision}" + touch_line
    )


def _error_outcome(exc: DndAssistantError, hint: str | None = None) -> SessionOutcome:
    return SessionOutcome(ok=False, message=f"Ошибка: {exc}", hint=hint)
