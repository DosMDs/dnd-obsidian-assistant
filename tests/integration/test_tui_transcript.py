"""Transcript presentation-only regressions (TUI-UX-01).

The transcript is ephemeral presentation state: it carries only accepted turns
and their terminal outcomes, never hidden reasoning, and it treats untrusted
model text as plain text (no Rich markup interpretation).
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

from textual.widgets import TextArea

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
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices
from dnd_assistant.tui.transcript import (
    TranscriptEntry,
    TranscriptRole,
    TranscriptView,
    _render_entries,
)

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


class ScriptedAssistant:
    def __init__(self, outcome: AgentTextOutcome | None = None, error: Exception | None = None):
        self._outcome = outcome or AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")
        self._error = error
        self.calls = 0

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._outcome


class ScriptedSession:
    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        raise AssertionError("transcript test must not mutate sessions")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("transcript test must not mutate sessions")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("transcript test must not mutate sessions")


class RecordingCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


def _app(assistant: ScriptedAssistant) -> DndTuiApp:
    return DndTuiApp(
        TuiServices(
            launch=_LAUNCH,
            assistant=assistant,
            session=ScriptedSession(),
            campaign_state=RecordingCampaign(),
        )
    )


def _entries(app: DndTuiApp) -> tuple[TranscriptEntry, ...]:
    return app.query_one(TranscriptView).entries


class TestTranscriptContent:
    def test_successful_turn_appends_user_then_assistant(self) -> None:
        async def scenario() -> None:
            app = _app(ScriptedAssistant())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "вопрос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert [(e.role, e.text) for e in _entries(app)] == [
                    (TranscriptRole.USER, "вопрос"),
                    (TranscriptRole.ASSISTANT, "Ответ"),
                ]

        _run(scenario())

    def test_clarify_role_appended(self) -> None:
        async def scenario() -> None:
            app = _app(
                ScriptedAssistant(
                    outcome=AgentTextOutcome(kind=AgentOutcomeKind.CLARIFY, message="Какой Варос?")
                )
            )
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "Варос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert _entries(app)[1].role is TranscriptRole.CLARIFY
                assert _entries(app)[1].text == "Какой Варос?"

        _run(scenario())

    def test_error_role_appended_on_expected_error(self) -> None:
        async def scenario() -> None:
            app = _app(ScriptedAssistant(error=ModelError("сбой модели")))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "вопрос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert _entries(app)[1].role is TranscriptRole.ERROR
                assert "сбой модели" in _entries(app)[1].text

        _run(scenario())

    def test_empty_submission_appends_nothing(self) -> None:
        async def scenario() -> None:
            app = _app(ScriptedAssistant())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "   "
                app.run_semantic_command("assistant.submit")
                await pilot.pause()
                assert _entries(app) == ()

        _run(scenario())


class TestPlainTextSafety:
    def test_untrusted_markup_is_not_interpreted(self) -> None:
        """Rich markup in model text must remain literal text."""
        raw = "[bold red]секрет[/bold red] [link=http://x]y[/link]"
        rendered = _render_entries(
            (
                TranscriptEntry(TranscriptRole.USER, "Вы:"),
                TranscriptEntry(TranscriptRole.ASSISTANT, raw),
            )
        )
        # Rendering must not raise and the literal markup must survive verbatim.
        assert raw in rendered.plain
        assert "секрет" in rendered.plain

    def test_transcript_render_does_not_crash_on_bracket_text(self) -> None:
        async def scenario() -> None:
            app = _app(
                ScriptedAssistant(
                    outcome=AgentTextOutcome(
                        kind=AgentOutcomeKind.RESPOND, message="[unclosed markup слово"
                    )
                )
            )
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#assistant-query", TextArea).text = "вопрос"
                app.run_semantic_command("assistant.submit")
                await _drain(pilot, lambda: not app._gate.is_busy)
                assert _entries(app)[1].text == "[unclosed markup слово"

        _run(scenario())
