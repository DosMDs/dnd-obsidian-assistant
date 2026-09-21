"""TUI-05 paste/multiline headless tests (direct ``Paste`` events).

``Paste`` is posted directly to the focused production widget.  This proves
presentation semantics only; real bracketed-paste emulator behavior is a
separate manual/terminal capability and is never claimed here.  No Ollama, no
network, no personal Vault.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from textual import events
from textual.widgets import Input, TextArea

from dnd_assistant.application.agent_contracts import AgentOutcomeKind, AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices
from dnd_assistant.tui.session import SessionView

_LAUNCH = TuiLaunchContext(
    vault_root=Path("vault"),
    config_path=Path("config.toml"),
    profile_name="test-agent",
    allow_agent_write=False,
)

_CYRILLIC_MULTILINE = "Первая строка\nВторая строка"


def _run(coro: Coroutine[Any, Any, None]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(coro)
    unresolved = [
        str(item.message)
        for item in caught
        if "was destroyed but it is pending" in str(item.message)
        or "was never awaited" in str(item.message)
    ]
    assert not unresolved, f"unresolved async lifecycle diagnostics: {unresolved}"


async def _drain(pilot: Any, predicate: Any) -> None:
    for _ in range(200):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError("condition not reached within pilot iterations")


async def _paste(pilot: Any, app: Any, text: str) -> None:
    """Deliver a paste the way the terminal driver does: to the App.

    ``App.on_event`` forwards an unforwarded ``Paste`` to the focused widget,
    exactly like a real bracketed-paste arrival.  Posting directly to a widget
    would bubble to the App and be re-forwarded (a test artifact).
    """
    app.post_message(events.Paste(text))
    await pilot.pause()


def _session_wired(app: DndTuiApp) -> bool:
    view = app._first(SessionView)
    return view is not None and view.is_configured


async def _open_session(app: DndTuiApp, pilot: Any) -> None:
    app.run_semantic_command("view.session")
    await _drain(
        pilot,
        lambda: app._current_context().context_id == "session" and _session_wired(app),
    )


class RecordingAssistant:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls.append((query, allow_agent_write))
        return AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")


class RecordingSession:
    def __init__(self, *, partition: RecoveryPartition | None = None) -> None:
        self.partition = partition or RecoveryPartition(blocking=(), externally_owned=())
        self.note_calls: list[str] = []
        self.end_calls: list[tuple[str, ...]] = []

    def recovery_partition(self) -> RecoveryPartition:
        return self.partition

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        raise AssertionError("paste test must not start a session")

    def note(self, text: str) -> RawSessionEvent:
        self.note_calls.append(text)
        return RawSessionEvent(
            event_id="evt_1",
            real_time=datetime.now(UTC),
            world_tick=1,
            type="note",
            extra_fields={"text": text},
        )

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        self.end_calls.append(tuple(touched_entity_ids))
        return Session(
            id="S001",
            type="session",
            status="completed",
            real_started_at=datetime.now(UTC),
            real_finished_at=datetime.now(UTC),
            world_tick_start=1,
            world_tick_end=2,
            processed=False,
            processed_model_profile=None,
            revision=2,
        )


class RecordingCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


def _services(assistant: RecordingAssistant, session: RecordingSession) -> TuiServices:
    return TuiServices(
        launch=_LAUNCH,
        assistant=assistant,
        session=session,
        campaign_state=RecordingCampaign(),
    )


class _HelpCountingApp(DndTuiApp):
    def __init__(self, services: TuiServices) -> None:
        super().__init__(services)
        self.help_calls = 0

    def show_help(self) -> None:
        self.help_calls += 1


# ── Assistant multiline paste ────────────────────────────────────────────────


class TestAssistantPaste:
    def test_multiline_cyrillic_paste_preserved_and_not_auto_submitted(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            session = RecordingSession()
            app = DndTuiApp(_services(assistant, session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.focus()
                await pilot.pause()
                await _paste(pilot, app, _CYRILLIC_MULTILINE)
                assert editor.text == _CYRILLIC_MULTILINE
                assert assistant.calls == [], "paste must not auto-submit"

                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert assistant.calls == [(_CYRILLIC_MULTILINE, False)]
                # RESPOND clears the editor.
                assert editor.text == ""

        _run(scenario())

    def test_pasted_question_mark_does_not_dispatch_help(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = _HelpCountingApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.focus()
                await pilot.pause()
                await _paste(pilot, app, "? что это\nещё строка")
                assert app.help_calls == 0
                assert "?" in editor.text

        _run(scenario())


# ── Session note single-line / multiline paste ───────────────────────────────


class TestSessionNotePaste:
    def test_single_line_cyrillic_paste_accepted(self) -> None:
        async def scenario() -> None:
            session = RecordingSession()
            app = DndTuiApp(_services(RecordingAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _open_session(app, pilot)
                note = app.screen.query_one("#session-note-input", Input)
                note.focus()
                await pilot.pause()
                await _paste(pilot, app, "Варос найден")
                assert note.value == "Варос найден"
                assert session.note_calls == []

        _run(scenario())

    def test_multiline_paste_rejected_without_mutation(self) -> None:
        async def scenario() -> None:
            session = RecordingSession()
            app = DndTuiApp(_services(RecordingAssistant(), session))
            notifications: list[str] = []
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _open_session(app, pilot)
                app.notify = lambda message, **kwargs: notifications.append(message)  # type: ignore[method-assign]
                note = app.screen.query_one("#session-note-input", Input)
                note.focus()
                await pilot.pause()
                await _paste(pilot, app, "первая\nвторая")
                assert note.value == "", "no silent first-line truncation"
                assert session.note_calls == []
                assert notifications, "expected a Russian warning"
                assert "одной строкой" in notifications[-1]

        _run(scenario())


# ── Touched-entity IDs multiline paste ───────────────────────────────────────


class TestTouchedIdsPaste:
    def test_multiline_paste_normalized_to_literal_tokens_in_order(self) -> None:
        async def scenario() -> None:
            session = RecordingSession()
            app = DndTuiApp(_services(RecordingAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _open_session(app, pilot)
                app.set_active_session(True)
                touched = app.screen.query_one("#session-touched", Input)
                touched.focus()
                await pilot.pause()
                await _paste(pilot, app, "npc-varos\r\nitem-001\nloc-grayford")
                assert touched.value == "npc-varos item-001 loc-grayford"

                app.run_semantic_command("session.end")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert session.end_calls == [("npc-varos", "item-001", "loc-grayford")]
                # Successful end clears the touched input.
                assert touched.value == ""

        _run(scenario())

    def test_single_line_paste_unchanged(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _open_session(app, pilot)
                touched = app.screen.query_one("#session-touched", Input)
                touched.focus()
                await pilot.pause()
                await _paste(pilot, app, "npc-varos, item-001")
                assert touched.value == "npc-varos, item-001"

        _run(scenario())
