"""TUI-04 Campaign-State integration: PLAYER-safe rendering and status mapping.

Uses a real temporary Vault with canonical entities of PLAYER/DM/SYSTEM
visibility and the production Campaign-State capability/app.  Proves hidden
DM/SYSTEM data cannot reach the player-facing TUI surface.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from textual.widgets import Static

from dnd_assistant.composition.campaign_state import (
    CampaignStateStatus,
    PlayerCampaignStateView,
    compose_campaign_state_capability,
)
from dnd_assistant.domain.types import Visibility
from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.campaign_state import STATUS_LABELS, render_campaign_state_view
from dnd_assistant.tui.services import TuiLaunchContext, build_tui_services
from tests.unit.campaign_state.helpers import (
    BASE_END,
    close_session,
    create_entity,
    make_entity,
    make_services,
    setup_entity_dirs,
)
from tests.unit.post_session.helpers import make_audit_context, make_vault


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
