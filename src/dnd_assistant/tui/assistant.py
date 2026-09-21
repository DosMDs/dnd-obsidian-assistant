"""Assistant capability view (TUI-04; workspace redesign TUI-UX-01).

Presentation only.  The workspace owns the ephemeral transcript and the
multiline prompt composer.  One immutable per-submission WRITE intent snapshot
is captured and all trusted work is delegated to the injected assistant/session
capabilities.  Before the agent is composed or run it performs the trusted
recovery partition preflight; a blocking partition returns a Russian error
outcome without any model composition or run.

Submission lifecycle (accepted-plan contract):

    validate (strip) -> acquire exclusive path -> append user entry
    -> clear composer -> run worker

The composer is cleared **only** when the submission was actually accepted for
execution, immediately before the worker starts.  It is never cleared again
when the asynchronous result arrives, so a new draft typed while the worker
runs survives completion.  A rejected (busy) or empty submission produces zero
assistant invocation and zero transcript entries.

Ephemeral prompt/response text is UI-only; it is never written to the Vault as
canonical data, and hidden reasoning is never rendered.
"""

from __future__ import annotations

from functools import partial
from typing import cast

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static, TextArea

from dnd_assistant.errors import DndAssistantError
from dnd_assistant.tui.errors import render_expected_error
from dnd_assistant.tui.inflight import EXCLUSIVE_ASSISTANT
from dnd_assistant.tui.services import (
    AssistantCapability,
    AssistantOutcome,
    AssistantOutcomeKind,
    SessionCapability,
)
from dnd_assistant.tui.transcript import TranscriptRole, TranscriptView
from dnd_assistant.tui.view import CapabilityView

__all__ = ["AssistantView", "render_blocking_recovery"]

_BLOCKING_HEADER = (
    "Обнаружено повреждённое или незавершённое состояние сессии.\n"
    "Требуется явное восстановление перед продолжением."
)
_EXTERNALLY_OWNED_HINT = (
    "Примечание: незавершённые операции ChangeSet не блокируют работу; "
    "проверьте `dnd changeset status`."
)

_RESULT_ROLE: dict[AssistantOutcomeKind, TranscriptRole] = {
    AssistantOutcomeKind.RESPOND: TranscriptRole.ASSISTANT,
    AssistantOutcomeKind.CLARIFY: TranscriptRole.CLARIFY,
    AssistantOutcomeKind.ERROR: TranscriptRole.ERROR,
}


def render_blocking_recovery(partition: object) -> str:
    """Render a short Russian blocking-recovery message from a trusted partition."""
    lines = [_BLOCKING_HEADER, "Проблемы:"]
    blocking = getattr(partition, "blocking", ())
    for issue in blocking:
        parts = [f"  [{issue.code}]"]
        if issue.session_id:
            parts.append(f"сессия={issue.session_id}")
        if issue.operation_id:
            parts.append(f"операция={issue.operation_id}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


class AssistantView(CapabilityView):
    """Player-facing assistant workspace: transcript plus prompt composer."""

    WORKER_OWNER = EXCLUSIVE_ASSISTANT

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._assistant: AssistantCapability | None = None
        self._session: SessionCapability | None = None
        self._write_intent = False

    # ── Composition / wiring ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TranscriptView(id="assistant-transcript")
        with Vertical(id="assistant-composer"):
            yield TextArea(id="assistant-query", soft_wrap=True, tab_behavior="focus")
            yield Static("", id="assistant-status")
            with Horizontal(id="assistant-actions"):
                yield Button("Отправить", id="assistant-submit", variant="primary")
                yield Button("Запись: выкл", id="assistant-toggle-write")
            yield Static("Режим: только чтение", id="assistant-mode")

    def set_capabilities(
        self,
        *,
        assistant: AssistantCapability,
        session: SessionCapability,
    ) -> None:
        self._assistant = assistant
        self._session = session
        self._sync_controls()

    def on_configured(self) -> None:
        self._sync_controls()

    # ── Event → semantic dispatch convergence ───────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "assistant-submit":
            self.host.run_semantic_command("assistant.submit")
        elif event.button.id == "assistant-toggle-write":
            self.host.run_semantic_command("assistant.toggle-write")

    # ── Command entry points ────────────────────────────────────────────────

    def toggle_write(self) -> None:
        """Toggle per-request agent WRITE intent (presentation state only)."""
        if not self.host.launch_context.allow_agent_write:
            self.host.notify_user(
                "Запись ассистента запрещена: запуск без --allow-write.",
            )
            return
        self._write_intent = not self._write_intent
        self._sync_mode()

    def submit_request(self) -> None:
        """Accept, capture, clear and run exactly one submission.

        Emptiness is checked with ``strip()``; the value passed to the trusted
        capability and shown as the user turn is the original ``TextArea`` text
        captured before clearing, never a stripped copy.
        """
        if self._assistant is None or self._session is None:
            return
        query = self.query_one("#assistant-query", TextArea).text
        if not query.strip():
            self.host.notify_user("Введите запрос.")
            return
        allow_agent_write = self._write_intent
        if not self._acquire_exclusive():
            return
        # The submission is accepted: record it and clear the composer now.
        self.query_one(TranscriptView).append(TranscriptRole.USER, query)
        self.query_one("#assistant-query", TextArea).clear()
        self.query_one("#assistant-status", Static).update("Выполняется…")
        self._sync_controls()
        self._start_worker(
            name="assistant.submit",
            work=partial(self._run_submission, query, allow_agent_write),
        )

    # ── Worker (synchronous trusted work; no UI access) ─────────────────────

    def _run_submission(self, query: str, allow_agent_write: bool) -> AssistantOutcome:
        assert self._session is not None
        assert self._assistant is not None

        try:
            partition = self._session.recovery_partition()
        except DndAssistantError as exc:
            return AssistantOutcome(
                kind=AssistantOutcomeKind.ERROR,
                message=render_expected_error(exc),
            )

        if partition.blocking:
            return AssistantOutcome(
                kind=AssistantOutcomeKind.ERROR,
                message=render_blocking_recovery(partition),
            )

        hint = _EXTERNALLY_OWNED_HINT if partition.externally_owned else None

        try:
            run_result = self._assistant.run(query, allow_agent_write=allow_agent_write)
        except DndAssistantError as exc:
            return AssistantOutcome(
                kind=AssistantOutcomeKind.ERROR,
                message=render_expected_error(exc),
                hint=hint,
            )

        return AssistantOutcome(
            kind=AssistantOutcomeKind(run_result.kind.value),
            message=run_result.message,
            hint=hint,
        )

    # ── Event-loop UI update ────────────────────────────────────────────────

    def _handle_result(self, result: object) -> None:
        outcome = cast(AssistantOutcome, result)
        transcript = self.query_one(TranscriptView)
        transcript.append(_RESULT_ROLE[outcome.kind], outcome.message)
        if outcome.hint:
            transcript.append(TranscriptRole.HINT, outcome.hint)
        self.query_one("#assistant-status", Static).update("")
        self._sync_controls()

    # ── Presentation sync ───────────────────────────────────────────────────

    def _sync_mode(self) -> None:
        mode = "запись" if self._write_intent else "только чтение"
        self.query_one("#assistant-mode", Static).update(f"Режим: {mode}")
        self.query_one("#assistant-toggle-write", Button).label = (
            "Запись: вкл" if self._write_intent else "Запись: выкл"
        )

    def _sync_controls(self) -> None:
        self._sync_mode()
        if self._host is None:
            return
        allowed = self.host.launch_context.allow_agent_write
        toggle = self.query_one("#assistant-toggle-write", Button)
        toggle.disabled = not allowed
        toggle.display = allowed
        submit = self.query_one("#assistant-submit", Button)
        submit.disabled = self._busy
