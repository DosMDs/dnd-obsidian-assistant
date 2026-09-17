"""TUI-04 assistant integration (headless, deterministic).

Uses the production ``DndTuiApp``/``AssistantView`` with deterministic fake
capabilities.  No Ollama, no network, no personal Vault.

Covers: per-submission WRITE snapshot, recovery preflight (blocking vs
externally-owned), CLARIFY/error rendering, worker-thread isolation, duplicate
submission protection, cross-capability in-flight exclusion and focus safety.
"""

from __future__ import annotations

import asyncio
import threading
import warnings
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from textual.widgets import Input, Static

from dnd_assistant.application.agent_contracts import AgentOutcomeKind, AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import ModelError
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_recovery import RecoveryIssue
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.assistant import AssistantView
from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices

_WAIT = 10.0


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


def _launch(*, allow_agent_write: bool = False) -> TuiLaunchContext:
    return TuiLaunchContext(
        vault_root=Path("vault"),
        config_path=Path("config.toml"),
        profile_name="test-agent",
        allow_agent_write=allow_agent_write,
    )


def _partition(
    *, blocking: tuple[RecoveryIssue, ...] = (), externally_owned: tuple[RecoveryIssue, ...] = ()
) -> RecoveryPartition:
    return RecoveryPartition(blocking=blocking, externally_owned=externally_owned)


class RecordingAssistant:
    def __init__(
        self,
        *,
        outcome: AgentTextOutcome | None = None,
        error: Exception | None = None,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.worker_threads: list[str] = []
        self._outcome = outcome or AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")
        self._error = error
        self._started = started
        self._release = release

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls.append((query, allow_agent_write))
        self.worker_threads.append(threading.current_thread().name)
        if self._started is not None and self._release is not None:
            self._started.set()
            self._release.wait(_WAIT)
        if self._error is not None:
            raise self._error
        return self._outcome


class RecordingSession:
    def __init__(self, *, partition: RecoveryPartition | None = None) -> None:
        self.partition = partition or _partition()
        self.recovery_calls = 0
        self.start_calls = 0
        self.note_calls: list[str] = []
        self.end_calls: list[tuple[str, ...]] = []

    def recovery_partition(self) -> RecoveryPartition:
        self.recovery_calls += 1
        return self.partition

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        self.start_calls += 1
        raise AssertionError("session.start must not be invoked in this scenario")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("session.note must not be invoked in this scenario")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("session.end must not be invoked in this scenario")


class RecordingCampaign:
    def __init__(self) -> None:
        self.inspect_calls = 0
        self.rebuild_calls = 0

    def inspect(self) -> PlayerCampaignStateView:
        self.inspect_calls += 1
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        self.rebuild_calls += 1
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


def _services(
    assistant: RecordingAssistant,
    session: RecordingSession,
    *,
    allow_agent_write: bool = False,
) -> TuiServices:
    return TuiServices(
        launch=_launch(allow_agent_write=allow_agent_write),
        assistant=assistant,
        session=session,
        campaign_state=RecordingCampaign(),
    )


def _output(app: DndTuiApp, widget_id: str) -> str:
    return str(app.query_one(f"#{widget_id}", Static).content)


async def _submit(app: DndTuiApp, pilot: Any, query: str = "Кто такой Варос?") -> None:
    app.query_one("#assistant-query", Input).value = query
    app.run_semantic_command("assistant.submit")
    await _drain(pilot, lambda: not app._gate.is_busy)


class TestReadSubmission:
    def test_read_submission_defaults_to_read(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            session = RecordingSession()
            app = DndTuiApp(_services(assistant, session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _submit(app, pilot)
                assert assistant.calls == [("Кто такой Варос?", False)]
                assert _output(app, "assistant-output") == "Ответ"
                assert app._gate.is_busy is False
            assert list(app.workers) == []

        _run(scenario())

    def test_clarify_is_rendered(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant(
                outcome=AgentTextOutcome(kind=AgentOutcomeKind.CLARIFY, message="Какого Вароса?")
            )
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _submit(app, pilot)
                assert _output(app, "assistant-output") == "Уточнение: Какого Вароса?"

        _run(scenario())


class TestWriteIntent:
    def test_write_requires_explicit_toggle(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant, RecordingSession(), allow_agent_write=True))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("assistant.toggle-write")
                await pilot.pause()
                await _submit(app, pilot)
                assert assistant.calls == [("Кто такой Варос?", True)]

        _run(scenario())

    def test_toggle_unavailable_without_ceiling(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("assistant.toggle-write")
                await pilot.pause()
                await _submit(app, pilot)
                assert assistant.calls == [("Кто такой Варос?", False)]

        _run(scenario())


class TestRecoveryPreflight:
    def test_blocking_recovery_prevents_model_run(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            session = RecordingSession(
                partition=_partition(
                    blocking=(RecoveryIssue("unresolved_audit_intent", operation_id="op-1"),)
                )
            )
            app = DndTuiApp(_services(assistant, session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _submit(app, pilot)
                assert assistant.calls == []
                assert session.recovery_calls >= 1
                assert "повреждённое" in _output(app, "assistant-output")

        _run(scenario())

    def test_externally_owned_is_non_blocking_hint(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            session = RecordingSession(
                partition=_partition(
                    externally_owned=(
                        RecoveryIssue("unresolved_audit_intent", operation_id="cs-1:0"),
                    )
                )
            )
            app = DndTuiApp(_services(assistant, session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _submit(app, pilot)
                assert len(assistant.calls) == 1
                assert "ChangeSet" in _output(app, "assistant-hint")

        _run(scenario())


class TestErrorRecovery:
    def test_expected_error_is_russian_and_app_stays_usable(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant(error=ModelError("сбой модели"))
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _submit(app, pilot)
                assert "Ошибка: сбой модели" in _output(app, "assistant-output")
                assert app._gate.is_busy is False
                # App remains usable: a second submission is accepted.
                await _submit(app, pilot)
                assert len(assistant.calls) == 2

        _run(scenario())

    def test_unexpected_error_remains_observable(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant(error=RuntimeError("unexpected-boom"))
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", Input).value = "q"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)

        with pytest.raises(RuntimeError, match="unexpected-boom"):
            _run(scenario())


class TestWorkerBoundary:
    def test_worker_runs_off_loop_and_ui_applies_on_loop(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                view = app.query_one(AssistantView)
                applied_threads: list[str] = []
                original = view._handle_result

                def spy(result: object) -> None:
                    applied_threads.append(threading.current_thread().name)
                    original(result)

                view._handle_result = spy  # type: ignore[method-assign]
                await _submit(app, pilot)
                assert assistant.worker_threads
                assert all(name != "MainThread" for name in assistant.worker_threads)
                assert applied_threads == ["MainThread"]

        _run(scenario())

    def test_duplicate_submit_while_busy_starts_one_worker(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            assistant = RecordingAssistant(started=started, release=release)
            app = DndTuiApp(_services(assistant, RecordingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", Input).value = "q"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)
                # Rapid duplicate activation while busy must not start a second run.
                app.run_semantic_command("assistant.submit")
                app.run_semantic_command("assistant.submit")
                await pilot.pause()
                assert len(assistant.calls) == 1
                release.set()
                await _drain(pilot, lambda: not app._gate.is_busy)

        _run(scenario())


class TestCrossCapabilityExclusion:
    def test_assistant_in_flight_blocks_session_and_campaign_rebuild(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()
            assistant = RecordingAssistant(started=started, release=release)
            session = RecordingSession()
            campaign = RecordingCampaign()
            services = TuiServices(
                launch=_launch(),
                assistant=assistant,
                session=session,
                campaign_state=campaign,
            )
            app = DndTuiApp(services)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", Input).value = "q"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, started.is_set)

                app.run_semantic_command("view.session")
                await pilot.pause()
                assert app.run_semantic_command("session.start") is not DispatchResult.EXECUTED
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert (
                    app.run_semantic_command("campaign-state.rebuild")
                    is not DispatchResult.EXECUTED
                )
                assert session.start_calls == 0
                assert campaign.rebuild_calls == 0

                release.set()
                await _drain(pilot, lambda: not app._gate.is_busy)

        _run(scenario())

    def test_session_mutation_in_flight_blocks_assistant(self) -> None:
        async def scenario() -> None:
            started = threading.Event()
            release = threading.Event()

            class BlockingSession(RecordingSession):
                def start(self) -> Session:
                    self.start_calls += 1
                    started.set()
                    release.wait(_WAIT)
                    return Session(
                        id="S001",
                        type="session",
                        status="active",
                        real_started_at=datetime.now(UTC),
                        real_finished_at=None,
                        world_tick_start=1,
                        world_tick_end=None,
                        processed=False,
                        processed_model_profile=None,
                        revision=1,
                    )

            assistant = RecordingAssistant()
            services = TuiServices(
                launch=_launch(),
                assistant=assistant,
                session=BlockingSession(),
                campaign_state=RecordingCampaign(),
            )
            app = DndTuiApp(services)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("view.session")
                await pilot.pause()
                assert app.run_semantic_command("session.start") is DispatchResult.EXECUTED
                await _drain(pilot, started.is_set)

                app.run_semantic_command("view.assistant")
                await pilot.pause()
                app.query_one("#assistant-query", Input).value = "q"
                assert app.run_semantic_command("assistant.submit") is not DispatchResult.EXECUTED
                assert assistant.calls == []

                release.set()
                await _drain(pilot, lambda: not app._gate.is_busy)

        _run(scenario())


class _HelpCountingApp(DndTuiApp):
    help_calls: ClassVar[int] = 0

    def show_help(self) -> None:
        type(self).help_calls += 1


class TestFocusSafety:
    def test_assistant_input_does_not_leak_printable_global_key(self) -> None:
        async def scenario() -> None:
            assistant = RecordingAssistant()
            app = _HelpCountingApp(_services(assistant, RecordingSession()))
            _HelpCountingApp.help_calls = 0
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                field = app.query_one("#assistant-query", Input)
                field.focus()
                await pilot.pause()
                await pilot.press("П", "р", "и", "в", "е", "т", "?")
                await pilot.pause()
                assert _HelpCountingApp.help_calls == 0
                assert "?" in field.value

        _run(scenario())
