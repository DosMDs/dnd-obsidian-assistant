"""TUI-04 Campaign-State integration: PLAYER-safe rendering and status mapping.

Uses a real temporary Vault with canonical entities of PLAYER/DM/SYSTEM
visibility and the production Campaign-State capability/app.  Proves hidden
DM/SYSTEM data cannot reach the player-facing TUI surface.
"""

from __future__ import annotations

import asyncio
import threading
import warnings
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Input, Static

from dnd_assistant.application.agent_contracts import AgentOutcomeKind, AgentTextOutcome
from dnd_assistant.application.session_recovery import RecoveryPartition
from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
    compose_campaign_state_capability,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId, Visibility
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.campaign_state import STATUS_LABELS, render_campaign_state_view
from dnd_assistant.tui.dispatch import DispatchResult
from dnd_assistant.tui.services import TuiLaunchContext, TuiServices, build_tui_services
from tests.unit.campaign_state.helpers import (
    BASE_END,
    close_session,
    create_entity,
    make_entity,
    make_services,
    setup_entity_dirs,
)
from tests.unit.post_session.helpers import make_audit_context, make_vault

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


def _build_populated_vault(tmp_path: Path) -> Path:
    root = make_vault(tmp_path)
    setup_entity_dirs(root)
    services = make_services(root)
    services.world_time.initialize_current_world_time(
        150,
        audit=make_audit_context(operation_id="wt-init"),
    )
    create_entity(
        services,
        make_entity("npc-varos", name="Варос", visibility=Visibility.PLAYER),
    )
    create_entity(
        services,
        make_entity("npc-secret", name="Тайный советник", visibility=Visibility.DM),
    )
    create_entity(
        services,
        make_entity("npc-system", name="Системная заметка", visibility=Visibility.SYSTEM),
    )
    close_session(
        services,
        "S001",
        finish=BASE_END,
        world_tick_end=200,
        touched=("npc-varos", "npc-secret", "npc-system"),
    )
    # Materialize the derived generation through the accepted trusted path so
    # the UI starts from a verified CURRENT generation.
    compose_campaign_state_capability(root).rebuild()
    return root


def _launch(root: Path) -> TuiLaunchContext:
    return TuiLaunchContext(
        vault_root=root,
        config_path=root.parent / "config.toml",
        profile_name="test-agent",
    )


def _body(app: DndTuiApp) -> str:
    return str(app.query_one("#campaign-state-body", Static).content)


class TestCapabilityProjection:
    def test_rebuild_then_inspect_is_current_player_only(self, tmp_path: Path) -> None:
        root = _build_populated_vault(tmp_path)
        capability = compose_campaign_state_capability(root)

        rebuilt = capability.rebuild()
        assert rebuilt.status is CampaignStateStatus.CURRENT
        assert rebuilt.recently_touched is not None
        assert {ref.name for ref in rebuilt.recently_touched} == {"Варос"}
        assert all(ref.entity_type.value == "npc" for ref in rebuilt.recently_touched)

        inspected = capability.inspect()
        assert inspected.status is CampaignStateStatus.CURRENT
        assert inspected.recently_touched is not None
        assert {ref.name for ref in inspected.recently_touched} == {"Варос"}

    def test_empty_vault_is_missing(self, tmp_path: Path) -> None:
        root = make_vault(tmp_path)
        capability = compose_campaign_state_capability(root)
        view = capability.inspect()
        assert view.status is CampaignStateStatus.MISSING
        assert view.recently_touched is None


class TestPlayerSafeUiRendering:
    def test_dm_and_system_entities_absent_from_rendered_body(self, tmp_path: Path) -> None:
        root = _build_populated_vault(tmp_path)
        app = DndTuiApp(build_tui_services(_launch(root)))

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _drain(pilot, lambda: "Варос" in _body(app))
                body = _body(app)
                assert "Варос" in body
                assert "Тайный советник" not in body
                assert "Системная заметка" not in body
                assert "DM" not in body
                assert "SYSTEM" not in body
                assert "актуально" in body
                assert "Недавно затронутые" in body

        _run(scenario())

    def test_no_invented_semantic_categories(self, tmp_path: Path) -> None:
        root = _build_populated_vault(tmp_path)
        app = DndTuiApp(build_tui_services(_launch(root)))

        async def scenario() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await _drain(pilot, lambda: "Варос" in _body(app))
                body = _body(app).lower()
                for forbidden in (
                    "текущее местоположение",
                    "активные задачи",
                    "важные персонажи",
                    "цели группы",
                    "дедлайны",
                ):
                    assert forbidden not in body

        _run(scenario())


class TestStatusMapping:
    def test_all_statuses_have_distinct_russian_labels(self) -> None:
        labels = {status: label for status, label in STATUS_LABELS.items()}
        assert set(labels) == set(CampaignStateStatus)
        assert len(set(labels.values())) == len(labels)
        assert labels[CampaignStateStatus.CURRENT] == "актуально"
        assert labels[CampaignStateStatus.MISSING] == "не создано"

    def test_non_current_view_shows_no_entity_data(self) -> None:
        for status in CampaignStateStatus:
            if status is CampaignStateStatus.CURRENT:
                continue
            rendered = render_campaign_state_view(PlayerCampaignStateView(status=status))
            assert STATUS_LABELS[status] in rendered
            assert "—" not in rendered


# ── Presentation concurrency contract (deterministic blocking fakes) ─────────


class _ControllableCampaign:
    def __init__(self) -> None:
        self.inspect_calls = 0
        self.rebuild_calls = 0
        self.block = False
        self.inspect_error: Exception | None = None
        self.rebuild_error: Exception | None = None
        self.started = threading.Event()
        self.release = threading.Event()

    def _gate(self) -> None:
        if self.block:
            self.started.set()
            self.release.wait(_WAIT)

    def inspect(self) -> PlayerCampaignStateView:
        self.inspect_calls += 1
        self._gate()
        if self.inspect_error is not None:
            raise self.inspect_error
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())

    def rebuild(self) -> PlayerCampaignStateView:
        self.rebuild_calls += 1
        self._gate()
        if self.rebuild_error is not None:
            raise self.rebuild_error
        return PlayerCampaignStateView(status=CampaignStateStatus.CURRENT, recently_touched=())


class _RecordingAssistant:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def run(self, query: str, *, allow_agent_write: bool) -> AgentTextOutcome:
        self.calls.append((query, allow_agent_write))
        return AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="Ответ")


class _RecordingSession:
    def __init__(self) -> None:
        self.start_calls = 0

    def recovery_partition(self) -> RecoveryPartition:
        return RecoveryPartition(blocking=(), externally_owned=())

    def status(self) -> Session | None:
        return None

    def start(self) -> Session:
        self.start_calls += 1
        raise AssertionError("session.start must not execute while the gate is held")

    def note(self, text: str) -> RawSessionEvent:
        raise AssertionError("session.note must not execute while the gate is held")

    def end(self, touched_entity_ids: Sequence[EntityId]) -> Session:
        raise AssertionError("session.end must not execute while the gate is held")


def _fake_services(
    assistant: _RecordingAssistant,
    session: _RecordingSession,
    campaign: _ControllableCampaign,
) -> TuiServices:
    return TuiServices(
        launch=TuiLaunchContext(
            vault_root=Path("vault"),
            config_path=Path("config.toml"),
            profile_name="test-agent",
        ),
        assistant=assistant,
        session=session,
        campaign_state=campaign,
    )


async def _ready(pilot: Any, app: DndTuiApp) -> None:
    """Let the initial (non-blocking) Campaign-State reload finish."""
    await _drain(pilot, lambda: not app._gate.is_busy)


def _body_text(app: DndTuiApp) -> str:
    return str(app.query_one("#campaign-state-body", Static).content)


def _error_text(app: DndTuiApp) -> str:
    return str(app.query_one("#campaign-state-error", Static).content)


class TestCampaignStateConcurrency:
    def test_assistant_in_flight_blocks_reload(self) -> None:
        async def scenario() -> None:
            assistant = _RecordingAssistant()
            session = _RecordingSession()
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(assistant, session, campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                campaign.inspect_calls = 0

                # Hold the gate with an assistant submission.
                assert app.acquire_exclusive("assistant") is True
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert (
                    app.run_semantic_command("campaign-state.reload") is not DispatchResult.EXECUTED
                )
                assert campaign.inspect_calls == 0
                app.release_exclusive("assistant")

        _run(scenario())

    def test_inspect_in_flight_blocks_other_exclusive_ops(self) -> None:
        async def scenario() -> None:
            assistant = _RecordingAssistant()
            session = _RecordingSession()
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(assistant, session, campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                campaign.inspect_calls = 0

                campaign.block = True
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert app.run_semantic_command("campaign-state.reload") is DispatchResult.EXECUTED
                await _drain(pilot, campaign.started.is_set)

                app.run_semantic_command("view.assistant")
                await pilot.pause()
                assert app.run_semantic_command("assistant.submit") is not DispatchResult.EXECUTED
                assert assistant.calls == []

                app.run_semantic_command("view.session")
                await pilot.pause()
                assert app.run_semantic_command("session.start") is not DispatchResult.EXECUTED
                assert session.start_calls == 0

                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert (
                    app.run_semantic_command("campaign-state.rebuild")
                    is not DispatchResult.EXECUTED
                )
                assert campaign.rebuild_calls == 0

                campaign.release.set()
                await _ready(pilot, app)

        _run(scenario())

    def test_rebuild_in_flight_blocks_reload(self) -> None:
        async def scenario() -> None:
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(_RecordingAssistant(), _RecordingSession(), campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                campaign.inspect_calls = 0

                campaign.block = True
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert app.run_semantic_command("campaign-state.rebuild") is DispatchResult.EXECUTED
                await _drain(pilot, campaign.started.is_set)

                assert (
                    app.run_semantic_command("campaign-state.reload") is not DispatchResult.EXECUTED
                )
                assert campaign.inspect_calls == 0

                campaign.release.set()
                await _ready(pilot, app)

        _run(scenario())

    def test_duplicate_reload_starts_one_inspect(self) -> None:
        async def scenario() -> None:
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(_RecordingAssistant(), _RecordingSession(), campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                campaign.inspect_calls = 0

                campaign.block = True
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                app.run_semantic_command("campaign-state.reload")
                await _drain(pilot, campaign.started.is_set)
                app.run_semantic_command("campaign-state.reload")
                app.run_semantic_command("campaign-state.reload")
                await pilot.pause()
                assert campaign.inspect_calls == 1

                campaign.release.set()
                await _ready(pilot, app)

        _run(scenario())

    def test_successful_inspect_releases_gate_and_renders(self) -> None:
        async def scenario() -> None:
            assistant = _RecordingAssistant()
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(assistant, _RecordingSession(), campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert app.run_semantic_command("campaign-state.reload") is DispatchResult.EXECUTED
                await _ready(pilot, app)
                assert app._gate.is_busy is False
                assert "актуально" in _body_text(app)

                # Later exclusive operations may execute.
                app.run_semantic_command("view.assistant")
                await pilot.pause()
                app.query_one("#assistant-query", Input).value = "q"
                assert app.run_semantic_command("assistant.submit") is DispatchResult.EXECUTED
                await _ready(pilot, app)
                assert assistant.calls == [("q", False)]

                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert app.run_semantic_command("campaign-state.rebuild") is DispatchResult.EXECUTED
                await _ready(pilot, app)
                assert campaign.rebuild_calls == 1

        _run(scenario())

    def test_expected_error_releases_gate_and_shows_russian(self) -> None:
        async def scenario() -> None:
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(_RecordingAssistant(), _RecordingSession(), campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                campaign.inspect_error = DndAssistantError("сбой состояния")
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                assert app.run_semantic_command("campaign-state.reload") is DispatchResult.EXECUTED
                await _ready(pilot, app)
                assert app._gate.is_busy is False
                assert "Ошибка: сбой состояния" in _error_text(app)

                # App remains usable: a subsequent rebuild executes.
                assert app.run_semantic_command("campaign-state.rebuild") is DispatchResult.EXECUTED
                await _ready(pilot, app)
                assert campaign.rebuild_calls == 1

        _run(scenario())

    def test_unexpected_inspect_error_observable_and_gate_released(self) -> None:
        async def scenario() -> None:
            campaign = _ControllableCampaign()
            app = DndTuiApp(_fake_services(_RecordingAssistant(), _RecordingSession(), campaign))
            async with app.run_test(size=(100, 30)) as pilot:
                await _ready(pilot, app)
                campaign.inspect_error = RuntimeError("inspect-boom")
                app.run_semantic_command("view.campaign-state")
                await pilot.pause()
                app.run_semantic_command("campaign-state.reload")
                await _drain(pilot, lambda: not app._gate.is_busy)

        with pytest.raises(RuntimeError, match="inspect-boom"):
            _run(scenario())
