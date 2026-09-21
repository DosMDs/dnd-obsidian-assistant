"""Primary-workspace render-geometry regression (Textual 8.2.8; TUI-UX-01).

Proves that the persistent agent workspace (transcript + composer), the
persistent campaign sidebar and the secondary session screen are actually laid
out with a positive visible region at the accepted terminal sizes.

DOM presence or ``display`` alone is not render evidence: Textual auto-height
containers can collapse a body to zero height while children still report
non-zero regions.  These assertions therefore require positive width and
height on the laid-out widgets.  No screenshots are used.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Button, Input, TextArea

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

_LAUNCH = TuiLaunchContext(
    vault_root=Path("vault"),
    config_path=Path("config.toml"),
    profile_name="test-agent",
    allow_agent_write=False,
)

SIZES: list[tuple[int, int]] = [(100, 30), (80, 24), (60, 20)]


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


def _session_wired(app: DndTuiApp) -> bool:
    view = app._first(SessionView)
    return view is not None and view.is_configured


class TestWorkspaceGeometry:
    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_assistant_workspace_has_visible_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                for selector in (
                    "#assistant-view",
                    "#assistant-transcript",
                    "#assistant-query",
                    "#assistant-submit",
                ):
                    _assert_visible(
                        app.screen.query_one(selector),
                        f"assistant {selector} at {width}x{height}",
                    )
                query = app.screen.query_one("#assistant-query", TextArea)
                composer = app.screen.query_one("#assistant-composer")
                assert composer.region.height > 0
                assert query.region.height > 0

        _run(scenario())

    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_campaign_sidebar_has_visible_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                for selector in (
                    "#campaign-sidebar",
                    "#sidebar-session-status",
                    "#sidebar-open-session",
                    "#campaign-state-body",
                    "#campaign-state-reload",
                ):
                    _assert_visible(
                        app.screen.query_one(selector),
                        f"sidebar {selector} at {width}x{height}",
                    )

        _run(scenario())

    @pytest.mark.parametrize(("width", "height"), SIZES)
    def test_session_screen_has_visible_geometry(self, width: int, height: int) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services())
            async with app.run_test(size=(width, height)) as pilot:
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.session")
                await _drain(
                    pilot,
                    lambda: app._current_context().context_id == "session" and _session_wired(app),
                )
                for selector in ("#session-view", "#session-note-input", "#session-start"):
                    _assert_visible(
                        app.screen.query_one(selector),
                        f"session {selector} at {width}x{height}",
                    )
                assert app.screen.query_one("#session-note-input", Input) is not None
                assert app.screen.query_one("#session-start", Button) is not None

        _run(scenario())
