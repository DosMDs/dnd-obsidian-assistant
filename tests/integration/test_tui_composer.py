"""Composer interaction contract regressions (TUI-UX-01).

Literal, headless evidence for the accepted correction contract:

    Enter       -> newline, zero assistant invocation
    Ctrl+Enter  -> assistant.submit exactly once, no newline
    Send button -> assistant.submit exactly once
    all routes   converge on one semantic `assistant.submit` path

    empty/whitespace  -> zero invocation, zero user transcript entry
    busy rejection    -> zero invocation, zero phantom user entry, composer kept
    accepted submit   -> user entry appended, composer cleared immediately
    result completion -> composer is NOT cleared again (a new draft survives)
    original text     -> exact unstripped query is passed and displayed
"""

from __future__ import annotations

import asyncio
import threading
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

from textual.widgets import Button, TextArea

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
from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices
from dnd_assistant.tui.transcript import TranscriptRole, TranscriptView

_WAIT = 10.0

_LAUNCH = TuiLaunchContext(
    vault_root=Path("vault"),
    config_path=Path("config.toml"),
    profile_name="test-agent",
    allow_agent_write=False,
)


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
    for _ in range(300):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError("condition not reached within pilot iterations")


class RecordingAssistant:
    def __init__(
        self,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._started = started
        self._release = release

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls.append((query, allow_agent_write))
        if self._started is not None and self._release is not None:
            self._started.set()
            self._release.wait(_WAIT)
        return AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")


class RecordingSession:
    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        raise AssertionError("composer test must not mutate sessions")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("composer test must not mutate sessions")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("composer test must not mutate sessions")


class RecordingCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


def _services(assistant: RecordingAssistant) -> TuiServices:
    return TuiServices(
        launch=_LAUNCH,
        assistant=assistant,
        session=RecordingSession(),
        campaign_state=RecordingCampaign(),
    )


def _editor(app: DndTuiApp) -> TextArea:
    return app.query_one("#assistant-query", TextArea)


def _user_entries(app: DndTuiApp) -> list[str]:
    return [
        entry.text
        for entry in app.query_one(TranscriptView).entries
        if entry.role is TranscriptRole.USER
    ]


class TestKeyboardAndButtonRoutes:
    def test_enter_inserts_newline_without_submitting(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                editor.focus()
                editor.text = ""
                await pilot.press("а", "enter", "б")
                await pilot.pause()
                assert editor.text == "а\nб"
                assert assistant.calls == []
                assert not app._gate.is_busy

        _run(scenario())

    def test_ctrl_enter_submits_exactly_once_without_newline(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                editor.focus()
                editor.text = "вопрос"
                await pilot.pause()
                await pilot.press("ctrl+enter")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert assistant.calls == [("вопрос", False)]
                assert editor.text == "", "Ctrl+Enter must not leave a newline"
                assert _user_entries(app) == ["вопрос"]

        _run(scenario())

    def test_send_button_submits_exactly_once(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                editor.text = "вопрос"
                await pilot.pause()
                await pilot.click("#assistant-submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert assistant.calls == [("вопрос", False)]
                assert _user_entries(app) == ["вопрос"]

        _run(scenario())

    def test_all_routes_reach_one_semantic_command(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                seen: list[str] = []
                original = app._dispatcher.dispatch

                def spy(command_id: str) -> DispatchResult:
                    seen.append(command_id)
                    return original(command_id)

                app._dispatcher.dispatch = spy  # type: ignore[method-assign]

                editor = _editor(app)
                editor.focus()
                editor.text = "раз"
                await pilot.press("ctrl+enter")
                await _drain(pilot, lambda: not app._gate.is_busy)
                editor.text = "два"
                await pilot.click("#assistant-submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert seen == ["assistant.submit", "assistant.submit"]
                assert [call[0] for call in assistant.calls] == ["раз", "два"]

        _run(scenario())


class TestEmptyAndOriginalText:
    def test_empty_and_whitespace_do_not_submit_or_record(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                for value in ("", "   ", "\n\t "):
                    editor.text = value
                    app.run_semantic_command("assistant.submit")
                    await pilot.pause()
                assert assistant.calls == []
                assert _user_entries(app) == []
                assert not app._gate.is_busy

        _run(scenario())

    def test_original_unstripped_text_is_passed_and_displayed(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant))
            query = "  Варос?\n вторая строка  "
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                editor.text = query
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert assistant.calls == [(query, False)]
                assert _user_entries(app) == [query]

        _run(scenario())


class TestBusyAndLifecycle:
    def test_busy_submit_rejected_without_phantom_entry_and_keeps_draft(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            assistant = RecordingAssistant(started=started, release=release)
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                editor.text = "первый"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)

                # A new draft typed during the worker must not be lost by a
                # rejected duplicate submission.
                editor.text = "второй черновик"
                assert app.run_semantic_command("assistant.submit") is not DispatchResult.EXECUTED
                await pilot.pause()
                assert len(assistant.calls) == 1
                assert _user_entries(app) == ["первый"]
                assert editor.text == "второй черновик"

                release.set()
                await _drain(pilot, lambda: not app._gate.is_busy)
                # Completion must not clear the draft either.
                assert editor.text == "второй черновик"

        _run(scenario())

    def test_composer_clears_immediately_on_acceptance(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            assistant = RecordingAssistant(started=started, release=release)
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = _editor(app)
                editor.text = "запрос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)
                # Cleared before the result arrives.
                assert editor.text == ""
                assert _user_entries(app) == ["запрос"]

                # A new draft typed while busy survives completion.
                editor.text = "новый черновик"
                release.set()
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert editor.text == "новый черновик"

        _run(scenario())

    def test_send_button_disabled_while_busy(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            assistant = RecordingAssistant(started=started, release=release)
            app = DndTuiApp(_services(assistant))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                _editor(app).text = "запрос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)
                assert app.query_one("#assistant-submit", Button).disabled is True
                release.set()
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert app.query_one("#assistant-submit", Button).disabled is False

        _run(scenario())
