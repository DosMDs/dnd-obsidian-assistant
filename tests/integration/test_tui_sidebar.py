"""Persistent campaign sidebar regressions (TUI-UX-01).

Proves the sidebar renders only accepted PLAYER-safe presentation DTOs, offers
a visible session entry point that routes through the semantic ``view.session``
command, and converges its session summary after session lifecycle actions
without inventing a second canonical state source.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from textual.widgets import Static

from dnd_assistant.application.agent_contracts import AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.screens import SessionScreen
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices
from dnd_assistant.tui.session import SessionView

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


class FakeAssistant:
    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        raise AssertionError("sidebar test must not run the assistant")


class MutableSession:
    """Trusted-capability fake whose status changes across lifecycle actions."""

    def __init__(self) -> None:
        self.current: Session | None = None

    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return self.current

    def start(self) -> Session:
        self.current = _session("active")
        return self.current

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("sidebar test does not record notes")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        completed = _session("completed")
        self.current = None
        return completed


class PlayerSafeCampaign:
    def inspect(self) -> PlayerCampaignStateView:
        from dnd_assistant.application.campaign_state_projection import (
            PlayerCampaignEntityReference,
        )

        return PlayerCampaignStateView(
            status=CampaignStateStatus.CURRENT,
            recently_touched=(
                PlayerCampaignEntityReference(
                    entity_id="npc-varos",
                    entity_type=EntityType.NPC,
                    name="Варос",
                ),
            ),
        )

    def rebuild(self) -> PlayerCampaignStateView:
        return self.inspect()


def _services(session: Any, campaign: Any) -> TuiServices:
    return TuiServices(
        launch=_LAUNCH,
        assistant=FakeAssistant(),
        session=session,
        campaign_state=campaign,
    )


def _text(app: DndTuiApp, selector: str) -> str:
    return str(app.screen.query_one(selector, Static).content)


def _session_wired(app: DndTuiApp) -> bool:
    view = app._first(SessionView)
    return view is not None and view.is_configured


class TestSidebarContent:
    def test_renders_player_safe_campaign_and_session_summary(self) -> None:
        async def scenario() -> None:
            session = MutableSession()
            session.current = _session("active")
            app = DndTuiApp(_services(session, PlayerSafeCampaign()))
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(pilot, lambda: "Варос" in _text(app, "#campaign-state-body"))
                body = _text(app, "#campaign-state-body")
                assert "Варос" in body
                assert "npc" in body
                assert "актуально" in body
                await _drain(pilot, lambda: "S001" in _text(app, "#sidebar-session-status"))
                status = _text(app, "#sidebar-session-status")
                assert "S001" in status and "active" in status

        _run(scenario())

    def test_no_active_session_shows_placeholder(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(MutableSession(), PlayerSafeCampaign()))
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(
                    pilot,
                    lambda: "нет" in _text(app, "#sidebar-session-status"),
                )
                assert "Активной сессии нет" in _text(app, "#sidebar-session-status")

        _run(scenario())


class TestSidebarNavigation:
    def test_open_session_button_routes_through_semantic_command(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(MutableSession(), PlayerSafeCampaign()))
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                seen: list[str] = []
                original = app._dispatcher.dispatch

                def spy(command_id: str) -> DispatchResult:
                    seen.append(command_id)
                    return original(command_id)

                app._dispatcher.dispatch = spy  # type: ignore[method-assign]
                await pilot.click("#sidebar-open-session")
                await _drain(pilot, lambda: isinstance(app.screen, SessionScreen))
                assert seen == ["view.session"]

        _run(scenario())


class TestSidebarConvergence:
    def test_session_summary_converges_after_start_and_end(self) -> None:
        async def scenario() -> None:
            app = DndTuiApp(_services(MutableSession(), PlayerSafeCampaign()))
            async with app.run_test(size=(100, 30)) as pilot:
                await _drain(
                    pilot,
                    lambda: "нет" in _text(app, "#sidebar-session-status"),
                )

                # Start from the session screen, then return to the workspace.
                app.run_semantic_command("view.session")
                await _drain(
                    pilot,
                    lambda: app._current_context().context_id == "session" and _session_wired(app),
                )
                assert app.run_semantic_command("session.start") is DispatchResult.EXECUTED
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.assistant")
                await _drain(pilot, lambda: app._current_context().context_id == "assistant")
                await _drain(pilot, lambda: "S001" in _text(app, "#sidebar-session-status"))

                # End, then return again; the summary converges back to none.
                app.run_semantic_command("view.session")
                await _drain(
                    pilot,
                    lambda: app._current_context().context_id == "session" and _session_wired(app),
                )
                assert app.run_semantic_command("session.end") is DispatchResult.EXECUTED
                await _drain(pilot, lambda: not app._gate.is_busy)
                app.run_semantic_command("view.assistant")
                await _drain(pilot, lambda: app._current_context().context_id == "assistant")
                await _drain(
                    pilot,
                    lambda: "Активной сессии нет" in _text(app, "#sidebar-session-status"),
                )

        _run(scenario())
