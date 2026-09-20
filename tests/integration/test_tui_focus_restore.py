"""S14-08 focus-restore headless tests for the production TUI (Textual 8.2.8).

Proves that closing the command palette and closing the help panel restore the
*exact* previously focused widget (identity, not merely "some widget is
focused").  Uses the production ``DndTuiApp`` with deterministic capability
fakes; no Ollama, no network, no personal Vault.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any, cast

from textual.app import App
from textual.command import CommandPalette
from textual.widgets import Input, TextArea

from dnd_assistant.application.agent_contracts import AgentTextOutcome
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


def _palette_open(app: DndTuiApp) -> bool:
    return CommandPalette.is_open(cast("App[object]", app))


async def _drain(pilot: Any, predicate: Any) -> None:
    for _ in range(300):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError("condition not reached within pilot iterations")


class _FakeAssistant:
    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        raise AssertionError("focus-restore test must not run the assistant")


class _FakeSession:
    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        raise AssertionError("focus-restore test must not mutate sessions")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("focus-restore test must not mutate sessions")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("focus-restore test must not mutate sessions")


class _FakeCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.MISSING)

    def rebuild(self) -> PlayerCampaignStateView:
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


def _services() -> TuiServices:
    return TuiServices(
        launch=_LAUNCH,
        assistant=_FakeAssistant(),
        session=_FakeSession(),
        campaign_state=_FakeCampaign(),
    )


async def _focus_session_note(app: DndTuiApp, pilot: Any) -> Input:
    """Navigate to the session view and settle on its non-default primary widget."""
    await _drain(pilot, lambda: not app._gate.is_busy)
    app.run_semantic_command("view.session")
    note = app.query_one("#session-note-input", Input)
    await _drain(pilot, lambda: app.focused is note)
    return note


class TestFocusRestore:
    def test_command_palette_close_restores_exact_focus(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                note = await _focus_session_note(app, pilot)

                app.open_command_palette()
                await _drain(pilot, lambda: _palette_open(app))
                assert _palette_open(app)

                await pilot.press("escape")
                await _drain(
                    pilot,
                    lambda: not _palette_open(app) and app.focused is note,
                )
                assert _palette_open(app) is False
                assert app.focused is note

        _run(scenario())

    def test_rapid_successive_navigation_settles_on_last_view(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                # No settle between navigations: deferred focus callbacks for
                # earlier views must not re-activate a stale pane or blur the
                # final primary control.
                app.run_semantic_command("view.session")
                app.run_semantic_command("view.campaign-state")
                app.run_semantic_command("view.assistant")
                editor = app.query_one("#assistant-query", TextArea)
                await _drain(
                    pilot,
                    lambda: (
                        app._current_context().context_id == "assistant" and app.focused is editor
                    ),
                )
                assert app._current_context().context_id == "assistant"
                assert app.focused is editor

        _run(scenario())

    def test_navigation_does_not_steal_focus_within_active_pane(self) -> None:
        """A late navigation retry must not steal focus within the active pane.

        After navigation starts, focus may legitimately move to another control
        inside the newly requested pane before all deferred navigation focus
        retries have drained.  Navigation owns pane convergence, not focus: it
        must not pull focus back to the pane's configured primary control.
        """

        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.session")
                await pilot.pause()
                touched = app.query_one("#session-touched", Input)
                touched.focus()
                # Drain subsequent refresh cycles; navigation must not steal.
                for _ in range(10):
                    await pilot.pause()
                assert app._current_context().context_id == "session"
                assert app.focused is touched

        _run(scenario())

    def test_help_close_restores_exact_focus(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                note = await _focus_session_note(app, pilot)

                assert not app.screen.query("HelpPanel")
                app.show_help()
                await _drain(pilot, lambda: bool(app.screen.query("HelpPanel")))
                assert app.screen.query("HelpPanel")

                app.show_help()
                await _drain(
                    pilot,
                    lambda: not app.screen.query("HelpPanel") and app.focused is note,
                )
                assert not app.screen.query("HelpPanel")
                assert app.focused is note

        _run(scenario())
