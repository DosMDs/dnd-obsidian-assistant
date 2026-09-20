"""S14-08 primary-view render-geometry regression (Textual 8.2.8).

Proves that after navigation each primary capability view and its primary
input / control / action are actually laid out with a positive visible region.

DOM presence or ``display`` alone is not render evidence: Textual 8.2.8
defaults ``TabbedContent`` / ``ContentSwitcher`` / ``TabPane`` to
``height: auto``, which collapsed the active pane body to zero height.  The
children then reported non-zero regions but were clipped, so a real terminal
showed an empty body.  These assertions therefore require positive width and
height on the laid-out widgets.  No screenshots are used.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Button, Input, Static, TextArea

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

SIZES: list[tuple[int, int]] = [(100, 30), (80, 24), (60, 20)]

# Primary control (settle target) is the second selector in each list.
VIEW_CHECKS: dict[str, list[str]] = {
    "assistant": ["#assistant-view", "#assistant-query", "#assistant-submit"],
    "session": ["#session-view", "#session-note-input", "#session-start"],
    "campaign-state": [
        "#campaign-state-view",
        "#campaign-state-body",
        "#campaign-state-reload",
    ],
}


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


class _FakeAssistant:
    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        raise AssertionError("geometry test must not run the assistant")


class _FakeSession:
    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        raise AssertionError("geometry test must not mutate sessions")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("geometry test must not mutate sessions")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("geometry test must not mutate sessions")


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


def _assert_visible(widget: Any, label: str) -> None:
    region = widget.region
    assert region.width > 0, f"{label} has zero width: {region}"
    assert region.height > 0, f"{label} has zero height (clipped body): {region}"


class TestPrimaryViewGeometry:
    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_all_primary_views_have_visible_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                for view_id, selectors in VIEW_CHECKS.items():
                    primary = selectors[1]
                    app.run_semantic_command(f"view.{view_id}")
                    await _drain(
                        pilot,
                        lambda v=view_id, s=primary: (
                            app._current_context().context_id == v
                            and app.query_one(s).region.height > 0
                        ),
                    )
                    assert app._current_context().context_id == view_id
                    for selector in selectors:
                        _assert_visible(
                            app.query_one(selector),
                            f"{view_id} {selector} at {width}x{height}",
                        )

        _run(scenario())

    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_assistant_composer_and_submit_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.assistant")
                await _drain(pilot, lambda: app._current_context().context_id == "assistant")
                view = app.query_one("#assistant-view")
                query = app.query_one("#assistant-query", TextArea)
                submit = app.query_one("#assistant-submit", Button)
                await _drain(pilot, lambda: query.region.height > 0)
                _assert_visible(view, "assistant view")
                assert query.region.height > 0
                assert submit.region.width > 0 and submit.region.height > 0

        _run(scenario())

    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_session_note_and_start_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.session")
                await _drain(pilot, lambda: app._current_context().context_id == "session")
                view = app.query_one("#session-view")
                note = app.query_one("#session-note-input", Input)
                start = app.query_one("#session-start", Button)
                await _drain(pilot, lambda: note.region.height > 0)
                _assert_visible(view, "session view")
                _assert_visible(note, "session note input")
                _assert_visible(start, "session start button")

        _run(scenario())

    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_campaign_state_body_and_reload_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.campaign-state")
                await _drain(pilot, lambda: app._current_context().context_id == "campaign-state")
                view = app.query_one("#campaign-state-view")
                body = app.query_one("#campaign-state-body", Static)
                reload_button = app.query_one("#campaign-state-reload", Button)
                await _drain(pilot, lambda: body.region.height > 0)
                _assert_visible(view, "campaign-state view")
                _assert_visible(body, "campaign-state body")
                _assert_visible(reload_button, "campaign-state reload button")

        _run(scenario())
