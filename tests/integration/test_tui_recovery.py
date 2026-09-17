"""TUI-05 error-recovery and input-preservation headless tests.

Uses the production app with deterministic fakes.  Proves expected errors keep
the app usable, preserve the exact input, and permit exactly one manual retry
with no automatic retry.  No Ollama, no network, no personal Vault.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from textual.widgets import Input, Static, TextArea

from dnd_assistant.application.agent_contracts import AgentOutcomeKind, AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import ModelError, StorageError, ValidationError
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices

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


def _session(status: str = "active") -> Session:
    finished = None if status == "active" else datetime.now(UTC)
    return Session(
        id="S001",
        type="session",
        status=status,
        real_started_at=datetime.now(UTC),
        real_finished_at=finished,
        world_tick_start=1,
        world_tick_end=None if status == "active" else 2,
        processed=False,
        processed_model_profile=None,
        revision=1,
    )


class ScriptedAssistant:
    def __init__(
        self, *, error: Exception | None = None, outcome: AgentTextOutcome | None = None
    ) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._error = error
        self._outcome = outcome or AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls.append((query, allow_agent_write))
        if self._error is not None:
            raise self._error
        return self._outcome


class ScriptedSession:
    def __init__(
        self,
        *,
        note_error: Exception | None = None,
        end_error: Exception | None = None,
    ) -> None:
        self._note_error = note_error
        self._end_error = end_error
        self.note_calls: list[str] = []
        self.end_calls: list[tuple[str, ...]] = []
        self.start_calls = 0

    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        self.start_calls += 1
        return _session()

    def note(self, text: str) -> RawSessionEvent:
        self.note_calls.append(text)
        if self._note_error is not None:
            raise self._note_error
        return RawSessionEvent(
            event_id="evt_1",
            real_time=datetime.now(UTC),
            world_tick=1,
            type="note",
            extra_fields={"text": text},
        )

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        self.end_calls.append(tuple(touched_entity_ids))
        if self._end_error is not None:
            raise self._end_error
        return _session("completed")


class RecordingCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


def _services(assistant: Any, session: Any) -> TuiServices:
    return TuiServices(
        launch=_LAUNCH,
        assistant=assistant,
        session=session,
        campaign_state=RecordingCampaign(),
    )


def _output(app: DndTuiApp, widget_id: str) -> str:
    return str(app.query_one(f"#{widget_id}", Static).content)


# ── Assistant expected error / retry / clear policy ──────────────────────────


class TestAssistantRecovery:
    def test_expected_error_retains_editor_and_manual_retry_once(self) -> None:
        async def scenario() -> None:
            assistant = ScriptedAssistant(error=ModelError("сбой модели"))
            app = DndTuiApp(_services(assistant, ScriptedSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.text = "Кто такой Варос?"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)

                assert "Ошибка модели: сбой модели" in _output(app, "assistant-output")
                assert editor.text == "Кто такой Варос?", "expected error must retain input"
                # No automatic retry.
                await pilot.pause()
                assert len(assistant.calls) == 1

                # Exactly one manual retry.
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert len(assistant.calls) == 2

        _run(scenario())

    def test_clarify_retains_editor_and_respond_clears(self) -> None:
        async def scenario() -> None:
            clarify = ScriptedAssistant(
                outcome=AgentTextOutcome(kind=AgentOutcomeKind.CLARIFY, message="Какой Варос?")
            )
            app = DndTuiApp(_services(clarify, ScriptedSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.text = "Варос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert editor.text == "Варос", "CLARIFY must retain the query"
                assert "Уточнение: Какой Варос?" in _output(app, "assistant-output")

        _run(scenario())

    def test_blocking_recovery_retains_editor(self) -> None:
        class BlockingSession(ScriptedSession):
            def recovery_partition(self) -> RecoveryPartition:
                from dnd_assistant.storage.session_recovery import RecoveryIssue

                return RecoveryPartition(
                    blocking=(RecoveryIssue("unresolved_audit_intent", operation_id="op-1"),),
                    externally_owned=(),
                )

        async def scenario() -> None:
            assistant = ScriptedAssistant()
            app = DndTuiApp(_services(assistant, BlockingSession()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.text = "запрос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert assistant.calls == []
                assert editor.text == "запрос"
                assert "повреждённое" in _output(app, "assistant-output")

        _run(scenario())


# ── Session note/touched expected error and clearing ─────────────────────────


class TestSessionRecovery:
    def test_note_validation_error_retains_input(self) -> None:
        async def scenario() -> None:
            session = ScriptedSession(note_error=ValidationError("недопустимый текст"))
            app = DndTuiApp(_services(ScriptedAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("view.session")
                await pilot.pause()
                app.set_active_session(True)
                note = app.query_one("#session-note-input", Input)
                note.value = "плохая заметка"
                app.run_semantic_command("session.note")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert "Ошибка проверки: недопустимый текст" in _output(app, "session-output")
                assert note.value == "плохая заметка"

        _run(scenario())

    def test_end_storage_error_retains_touched(self) -> None:
        async def scenario() -> None:
            session = ScriptedSession(end_error=StorageError("нет доступа"))
            app = DndTuiApp(_services(ScriptedAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("view.session")
                await pilot.pause()
                app.set_active_session(True)
                touched = app.query_one("#session-touched", Input)
                touched.value = "npc-varos, item-001"
                assert app.run_semantic_command("session.end") is DispatchResult.EXECUTED
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert "Ошибка хранилища: нет доступа" in _output(app, "session-output")
                assert touched.value == "npc-varos, item-001"

        _run(scenario())

    def test_successful_note_clears_only_note(self) -> None:
        async def scenario() -> None:
            session = ScriptedSession()
            app = DndTuiApp(_services(ScriptedAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("view.session")
                await pilot.pause()
                app.set_active_session(True)
                note = app.query_one("#session-note-input", Input)
                touched = app.query_one("#session-touched", Input)
                note.value = "заметка"
                touched.value = "npc-varos"
                app.run_semantic_command("session.note")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert note.value == ""
                assert touched.value == "npc-varos"

        _run(scenario())

    def test_successful_end_clears_only_touched(self) -> None:
        async def scenario() -> None:
            session = ScriptedSession()
            app = DndTuiApp(_services(ScriptedAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("view.session")
                await pilot.pause()
                app.set_active_session(True)
                note = app.query_one("#session-note-input", Input)
                touched = app.query_one("#session-touched", Input)
                note.value = "заметка"
                touched.value = "npc-varos"
                app.run_semantic_command("session.end")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert touched.value == ""
                assert note.value == "заметка"

        _run(scenario())

    def test_successful_start_clears_neither_input(self) -> None:
        async def scenario() -> None:
            session = ScriptedSession()
            app = DndTuiApp(_services(ScriptedAssistant(), session))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.run_semantic_command("view.session")
                await pilot.pause()
                app.set_active_session(False)
                note = app.query_one("#session-note-input", Input)
                touched = app.query_one("#session-touched", Input)
                note.value = "заметка"
                touched.value = "npc-varos"
                app.run_semantic_command("session.start")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert note.value == "заметка"
                assert touched.value == "npc-varos"

        _run(scenario())
