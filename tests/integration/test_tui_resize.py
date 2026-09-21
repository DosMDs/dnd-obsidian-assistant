"""TUI-05 responsive/narrow-layout headless tests (Textual 8.2.8).

Uses the production ``DndTuiApp``/``MainScreen`` with deterministic fake
capabilities.  ``Pilot.resize_terminal`` drives Textual's native breakpoint
classes; assertions are structural/semantic (mount/class/focus/content/scroll),
never pixel screenshots.  No Ollama, no network, no personal Vault.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Button, Static, TextArea

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
from dnd_assistant.tui.session import SessionView
from dnd_assistant.tui.transcript import TranscriptRole, TranscriptView

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


class _FakeAssistant:
    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        raise AssertionError("resize test must not run the assistant")


class _FakeSession:
    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        raise AssertionError("resize test must not mutate sessions")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("resize test must not mutate sessions")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("resize test must not mutate sessions")


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


async def _settle(pilot: Any, predicate: Any) -> None:
    for _ in range(100):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError("breakpoint condition not reached")


def _session_wired(app: DndTuiApp) -> bool:
    view = app._first(SessionView)
    return view is not None and view.is_configured


async def _open_session(app: DndTuiApp, pilot: Any) -> None:
    app.run_semantic_command("view.session")
    for _ in range(200):
        if app._current_context().context_id == "session" and _session_wired(app):
            return
        await pilot.pause()
    raise AssertionError("session screen did not open")


# ── Breakpoint threshold boundaries ──────────────────────────────────────────

WIDTH_CASES = [
    (59, "-w-tiny"),
    (60, "-w-narrow"),
    (79, "-w-narrow"),
    (80, "-w-baseline"),
    (99, "-w-baseline"),
    (100, "-w-reference"),
]

HEIGHT_CASES = [
    (11, "-h-tiny"),
    (12, "-h-short"),
    (19, "-h-short"),
    (20, "-h-baseline"),
    (29, "-h-baseline"),
    (30, "-h-reference"),
]

ALL_WIDTH_CLASSES = {"-w-tiny", "-w-narrow", "-w-baseline", "-w-reference"}
ALL_HEIGHT_CLASSES = {"-h-tiny", "-h-short", "-h-baseline", "-h-reference"}


class TestBreakpointThresholds:
    @pytest.mark.parametrize(("width", "expected"), WIDTH_CASES)
    def test_horizontal_threshold_class(self, width: int, expected: str) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.resize_terminal(width, 40)
                await _settle(pilot, lambda: app.screen.has_class(expected))
                present = {name for name in ALL_WIDTH_CLASSES if app.screen.has_class(name)}
                assert present == {expected}, (width, present)

        _run(scenario())

    @pytest.mark.parametrize(("height", "expected"), HEIGHT_CASES)
    def test_vertical_threshold_class(self, height: int, expected: str) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.resize_terminal(120, height)
                await _settle(pilot, lambda: app.screen.has_class(expected))
                present = {name for name in ALL_HEIGHT_CLASSES if app.screen.has_class(name)}
                assert present == {expected}, (height, present)

        _run(scenario())


# ── Minimum usable size semantic reachability ────────────────────────────────


class TestMinimumUsableSize:
    def test_60x20_semantic_reachability(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.resize_terminal(60, 20)
                await _settle(pilot, lambda: app.screen.has_class("-w-narrow"))

                assert app.is_running
                assert not app._gate.is_busy
                assert app._current_context().context_id == "assistant"

                editor = app.query_one("#assistant-query", TextArea)
                assert editor.display
                assert editor.focusable
                assert app.screen.has_class("-w-narrow")

                submit = app.query_one("#assistant-submit", Button)
                assert submit.display
                assert submit.disabled is False

                # The compact sidebar keeps its campaign controls and the
                # visible session affordance at the minimum usable width.
                for selector in (
                    "#sidebar-session-status",
                    "#sidebar-open-session",
                    "#campaign-state-reload",
                    "#campaign-state-rebuild",
                ):
                    assert app.screen.query_one(selector) is not None

                # The session screen keeps all lifecycle controls reachable.
                await _open_session(app, pilot)
                for selector in (
                    "#session-note-input",
                    "#session-touched",
                    "#session-refresh",
                    "#session-start",
                    "#session-note",
                    "#session-end",
                ):
                    assert app.screen.query_one(selector) is not None

                # Native vertical scrolling remains available on the screen.
                assert app.screen.styles.overflow_y == "auto"

        _run(scenario())

    def test_narrow_stacks_session_action_row(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _open_session(app, pilot)
                await pilot.resize_terminal(60, 20)
                await _settle(pilot, lambda: app.screen.has_class("-w-narrow"))
                actions = app.screen.query_one("#session-actions")
                assert "vertical" in repr(actions.styles.layout)
                assert all(button.display for button in actions.query(Button))

        _run(scenario())

    def test_below_minimum_remains_scrollable(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _open_session(app, pilot)
                await pilot.resize_terminal(55, 11)
                await _settle(pilot, lambda: app.screen.has_class("-w-tiny"))
                assert app.screen.has_class("-w-tiny")
                assert app.screen.has_class("-h-tiny")
                # Degraded but reachable: the screen scrolls to the content.
                assert app.screen.styles.overflow_y == "auto"
                assert "vertical" in repr(app.screen.query_one("#session-actions").styles.layout)

        _run(scenario())


# ── Resize round-trip retains content/focus/active tab ───────────────────────


class TestResizeRoundTrip:
    def test_reference_narrow_reference_retains_content_focus_tab(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                editor = app.query_one("#assistant-query", TextArea)
                editor.focus()
                editor.text = "Первая строка\nВторая строка"
                await pilot.pause()
                assert app._current_context().context_id == "assistant"

                await pilot.resize_terminal(60, 20)
                await _settle(pilot, lambda: app.screen.has_class("-w-narrow"))
                assert app.screen.has_class("-w-narrow")
                assert editor.text == "Первая строка\nВторая строка"
                assert app.focused is editor
                assert app._current_context().context_id == "assistant"

                await pilot.resize_terminal(100, 30)
                await _settle(pilot, lambda: app.screen.has_class("-w-reference"))
                assert app.screen.has_class("-w-reference")
                assert editor.text == "Первая строка\nВторая строка"
                assert app.focused is editor
                assert app._current_context().context_id == "assistant"

        _run(scenario())

    def test_resize_with_expected_error_visible(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one(TranscriptView).append(TranscriptRole.ERROR, "Ошибка модели: сбой")
                await pilot.resize_terminal(60, 20)
                await pilot.pause()
                entries = app.query_one(TranscriptView).entries
                assert [(entry.role, entry.text) for entry in entries] == [
                    (TranscriptRole.ERROR, "Ошибка модели: сбой")
                ]

        _run(scenario())

    def test_resize_with_campaign_state_visible(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                body_before = str(app.screen.query_one("#campaign-state-body", Static).content)
                await pilot.resize_terminal(60, 20)
                await pilot.pause()
                assert str(app.screen.query_one("#campaign-state-body", Static).content) == (
                    body_before
                )
                assert app.screen.query_one("#campaign-state-reload", Button).display

        _run(scenario())
