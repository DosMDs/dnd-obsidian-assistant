"""TUI-05 interaction/focus/quit/cancellation headless tests (Textual 8.2.8).

Uses the production app with deterministic fakes.  No Ollama, no network, no
personal Vault.
"""

from __future__ import annotations

import asyncio
import threading
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

from textual.widgets import Button, TextArea
from textual.worker import WorkerState

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
from dnd_assistant.tui.assistant import AssistantView
from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices

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


async def _settle_view(app: Any, pilot: Any, view_id: str, selector: str) -> None:
    """Wait until navigation fully settles on the exact context and widget.

    ``navigate_to`` schedules primary-control focus through
    ``call_after_refresh``; the Textual ``TabPane.Focused`` message then
    re-asserts ``TabbedContent.active``.  Waiting for both the expected context
    id and exact focused widget is deterministic and independent of a fixed
    ``pilot.pause()`` count.
    """
    target = app.query_one(selector)
    for _ in range(300):
        if app.focused is target and app._current_context().context_id == view_id:
            return
        await pilot.pause()
    raise AssertionError(f"view {view_id!r} did not settle on {selector}")


class RecordingAssistant:
    def __init__(
        self,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
        finished: threading.Event | None = None,
    ) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._started = started
        self._release = release
        self._finished = finished

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls.append((query, allow_agent_write))
        if self._started is not None and self._release is not None:
            self._started.set()
            self._release.wait(_WAIT)
            if self._finished is not None:
                self._finished.set()
        return AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")


class RecordingSession:
    def __init__(self) -> None:
        self.start_calls = 0

    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        self.start_calls += 1
        raise AssertionError("interaction test must not mutate sessions")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("interaction test must not mutate sessions")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("interaction test must not mutate sessions")


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


# ── Focus policy ─────────────────────────────────────────────────────────────


class TestFocusPolicy:
    def test_initial_focus_is_assistant_editor(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert app.focused is app.query_one("#assistant-query", TextArea)

        _run(scenario())

    def test_navigation_keys_focus_primary_control(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                await pilot.press("f3")
                await _settle_view(app, pilot, "session", "#session-note-input")
                assert app.focused is app.query_one("#session-note-input")

                await pilot.press("f4")
                await _settle_view(app, pilot, "campaign-state", "#campaign-state-reload")
                assert app.focused is app.query_one("#campaign-state-reload")

                await pilot.press("f2")
                await _settle_view(app, pilot, "assistant", "#assistant-query")
                assert app.focused is app.query_one("#assistant-query", TextArea)

        _run(scenario())

    def test_palette_navigation_focuses_primary_control(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.session")
                await _settle_view(app, pilot, "session", "#session-note-input")
                assert app.focused is app.query_one("#session-note-input")

        _run(scenario())

    def test_tab_moves_focus_out_of_editor(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.focus()
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                assert app.focused is not editor
                assert app.focused is not None
                assert isinstance(app.focused, Button | TextArea)

        _run(scenario())


# ── F5 best-effort alias ─────────────────────────────────────────────────────


class TestSubmitAlias:
    def test_f5_dispatches_assistant_submit_exactly_once(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.focus()
                editor.text = "вопрос"
                await pilot.pause()
                await pilot.press("f5")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert assistant.calls == [("вопрос", False)]

        _run(scenario())

    def test_enter_inserts_newline_without_submitting(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.focus()
                editor.text = ""
                await pilot.pause()
                await pilot.press("а", "enter", "б")
                await pilot.pause()
                assert editor.text == "а\nб"
                assert assistant.calls == [], "Enter must not submit the composer"
                assert not app._gate.is_busy

        _run(scenario())


# ── Runtime binding / palette quit-path audit ────────────────────────────────


class TestQuitPathAudit:
    def test_active_bindings_do_not_bypass_semantic_quit(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                active = app.active_bindings
                assert "ctrl+q" in active
                assert "semantic_dispatch('app.quit')" == active["ctrl+q"].binding.action
                for active_binding in active.values():
                    action = active_binding.binding.action
                    assert action not in {"quit", "help_quit", "suspend"}, action

        _run(scenario())

    def test_palette_has_no_framework_quit_entry(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                # Startup read/refresh workers hold the exclusive gate briefly;
                # wait until idle so the palette reflects the settled state.
                await _drain(pilot, lambda: not app._gate.is_busy)
                titles = {command.title for command in app.get_system_commands(app.screen)}
                assert "Quit" not in titles
                assert "Выход" in titles

        _run(scenario())


# ── Busy vs idle quit ────────────────────────────────────────────────────────


class TestQuitSemantics:
    def test_busy_semantic_quit_does_not_exit(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            assistant = RecordingAssistant(started=started, release=release, finished=finished)
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "q"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)

                assert app.run_semantic_command("app.quit") is not DispatchResult.EXECUTED
                assert app._exit is False
                assert app.is_running
                # Framework/system quit is not offered while busy either.
                titles = {command.title for command in app.get_system_commands(app.screen)}
                assert "Выход" not in titles

                release.set()
                assert await asyncio.to_thread(finished.wait, _WAIT)
                await _drain(pilot, lambda: not app._gate.is_busy)

        _run(scenario())

    def test_idle_semantic_quit_exits(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(RecordingAssistant(), RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                assert app.run_semantic_command("app.quit") is DispatchResult.EXECUTED
                assert app._exit is True

        _run(scenario())


# ── Failed-closed CANCELLED semantics ────────────────────────────────────────


class TestCancelledFailClosed:
    def test_cancelled_thread_worker_keeps_gate_held(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            assistant = RecordingAssistant(started=started, release=release, finished=finished)
            session = RecordingSession()
            app = DndTuiApp(_services(assistant, session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "q"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)
                assert app._gate.owner == "assistant"

                view = app.query_one(AssistantView)
                worker = next(w for w in app.workers if w.group == "assistant")
                worker.cancel()
                await _drain(pilot, lambda: worker.state is WorkerState.CANCELLED)

                # Fail closed: cancellation is not proof of completion.
                assert app._gate.owner == "assistant"
                assert app._gate.is_busy
                assert view.busy is True
                assert app.run_semantic_command("assistant.submit") is not DispatchResult.EXECUTED
                assert len(assistant.calls) == 1

                # The underlying callable still finishes; release for clean teardown.
                release.set()
                assert await asyncio.to_thread(finished.wait, _WAIT)
                await pilot.pause()

        _run(scenario())
