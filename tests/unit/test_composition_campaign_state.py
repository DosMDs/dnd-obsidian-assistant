"""Campaign-State capability composition DTO/privacy contract (TUI-04)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from dnd_assistant.application.campaign_state_consumer import (
    FAST_AGENT_RECENT_SESSION_LIMIT,
)
from dnd_assistant.application.campaign_state_materialization import CampaignStateStatus
from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignEntityReference,
)
from dnd_assistant.composition.campaign_state import (
    PlayerCampaignStateView,
    compose_campaign_state_capability,
)

_REQUIRED_VAULT_DIRS: tuple[str, ...] = (
    "Sessions",
    "_system",
    "_system/raw",
    "_system/raw/sessions",
    "_system/audit",
)


def _minimal_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    for relative in _REQUIRED_VAULT_DIRS:
        (vault_root / relative).mkdir(parents=True, exist_ok=True)
    return vault_root


class TestInspect:
    def test_empty_vault_is_missing_without_semantic_data(self, tmp_path: Path) -> None:
        capability = compose_campaign_state_capability(_minimal_vault(tmp_path))
        view = capability.inspect()
        assert view.status is CampaignStateStatus.MISSING
        assert view.recently_touched is None


class TestPolicyUnification:
    def test_effective_recent_session_limit_is_shared(self, tmp_path: Path) -> None:
        capability = compose_campaign_state_capability(_minimal_vault(tmp_path))
        assert capability.recent_session_limit == FAST_AGENT_RECENT_SESSION_LIMIT
        assert capability.recent_session_limit == 5


class TestPrivacyShape:
    def test_view_fields_are_player_safe_only(self) -> None:
        names = {field.name for field in dataclasses.fields(PlayerCampaignStateView)}
        assert names == {"status", "recently_touched"}
        forbidden = {
            "state",
            "manifest",
            "input_fingerprint",
            "fingerprint",
            "detail",
            "cause",
            "provenance",
            "visibility",
            "revision",
        }
        assert not (names & forbidden)

    def test_reference_fields_are_minimal(self) -> None:
        names = {field.name for field in dataclasses.fields(PlayerCampaignEntityReference)}
        assert names == {"entity_id", "entity_type", "name"}
