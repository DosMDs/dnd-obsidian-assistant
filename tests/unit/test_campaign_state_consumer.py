"""S12-04 lazy Campaign State provider unit tests.

Verifies the exact graceful-vs-propagated failure mapping and that the
provider projects a player-safe state from the rebuilt typed Campaign State.
The S12-03 rebuild service is monkeypatched so each reason class is exercised
literally without constructing full canonical sources.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import dnd_assistant.application.campaign_state_consumer as consumer
from dnd_assistant.application.campaign_state_consumer import (
    FAST_AGENT_RECENT_SESSION_LIMIT,
    RebuildPlayerCampaignStateProvider,
)
from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateSourceChangedError,
)
from dnd_assistant.application.campaign_state_source import (
    CampaignStateSourceError,
    CampaignStateSourceReason,
)
from dnd_assistant.domain.types import Visibility
from dnd_assistant.errors import StorageError
from tests.unit.campaign_state.helpers import make_reference, make_state

_FP = "a" * 64


def _provider() -> RebuildPlayerCampaignStateProvider:
    return RebuildPlayerCampaignStateProvider(
        vault_repository=object(),  # type: ignore[arg-type]
        session_repository=object(),  # type: ignore[arg-type]
        world_time_repository=object(),  # type: ignore[arg-type]
        derived_state_store=object(),  # type: ignore[arg-type]
        recent_session_limit=FAST_AGENT_RECENT_SESSION_LIMIT,
    )


def _patch_rebuild(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def _fake(**kwargs: Any) -> Any:
        calls.update(kwargs)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(consumer, "rebuild_campaign_state", _fake)
    return calls


class TestGracefulOmission:
    def test_world_time_unavailable_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_rebuild(
            monkeypatch,
            CampaignStateSourceError(
                CampaignStateSourceReason.WORLD_TIME_UNAVAILABLE, "no world time"
            ),
        )
        assert _provider().get_player_campaign_state() is None

    def test_source_changed_race_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_rebuild(monkeypatch, CampaignStateSourceChangedError("race"))
        assert _provider().get_player_campaign_state() is None


_PROPAGATED_REASONS = [
    CampaignStateSourceReason.INVALID_COMPLETED_SESSION,
    CampaignStateSourceReason.INVALID_TOUCHED_ENTITIES,
    CampaignStateSourceReason.MISSING_TOUCHED_ENTITY,
    CampaignStateSourceReason.INVALID_CALENDAR_INPUT,
    CampaignStateSourceReason.INVALID_SELECTION_LIMIT,
    CampaignStateSourceReason.INPUT_TOO_LARGE,
]


class TestPropagatedFailures:
    @pytest.mark.parametrize("reason", _PROPAGATED_REASONS)
    def test_other_source_reasons_propagate(
        self, monkeypatch: pytest.MonkeyPatch, reason: CampaignStateSourceReason
    ) -> None:
        _patch_rebuild(monkeypatch, CampaignStateSourceError(reason, "invalid"))
        with pytest.raises(CampaignStateSourceError) as exc_info:
            _provider().get_player_campaign_state()
        assert exc_info.value.reason is reason

    def test_storage_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_rebuild(monkeypatch, StorageError("unsafe derived-state topology"))
        with pytest.raises(StorageError):
            _provider().get_player_campaign_state()


class TestProjection:
    def test_success_returns_player_safe_projection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = make_state(
            _FP,
            references=(
                make_reference("npc-player", name="Aria"),
                make_reference("npc-dm", name="Тайный Лорд", visibility=Visibility.DM),
                make_reference("npc-sys", name="Система", visibility=Visibility.SYSTEM),
            ),
        )
        _patch_rebuild(monkeypatch, SimpleNamespace(state=state, status=object()))

        result = _provider().get_player_campaign_state()
        assert result is not None
        assert [ref.entity_id for ref in result.recently_touched] == ["npc-player"]

    def test_rebuild_receives_explicit_policy_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = make_state(_FP)
        calls = _patch_rebuild(monkeypatch, SimpleNamespace(state=state))
        _provider().get_player_campaign_state()
        assert calls["recent_session_limit"] == FAST_AGENT_RECENT_SESSION_LIMIT
        assert calls["calendar_definition"] is None
