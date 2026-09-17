"""Shared Campaign-State presentation capability composition (TUI-04).

This module is the UI-agnostic composition for the interactive Campaign-State
capability.  It owns exactly one capability reason: exposing the trusted
materialized-generation status together with the already-projected **player-safe**
semantic content, without leaking any internal all-visibility ``CampaignState``,
manifest, fingerprint, provenance, cause or arbitrary detail to presentation.

::

    inspect_campaign_state(...)                 (trusted integrity/freshness)
      -> CampaignStateStatus
      -> project_player_campaign_state(state)   (PLAYER-safe, only for CURRENT)
      -> PlayerCampaignStateView

    rebuild_campaign_state(...)                 (trusted ensure-current)
      -> project_player_campaign_state(state)
      -> PlayerCampaignStateView

The recent-session selection limit deliberately reuses the single production
Fast-Agent policy value ``FAST_AGENT_RECENT_SESSION_LIMIT`` so the derivation
source fingerprint semantics do not diverge between the assistant and the TUI.
The Stage-12 application ownership of that constant is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dnd_assistant.application.campaign_state_consumer import (
    FAST_AGENT_RECENT_SESSION_LIMIT,
)
from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateStatus,
    inspect_campaign_state,
    rebuild_campaign_state,
)
from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignEntityReference,
    project_player_campaign_state,
)
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.derived_state import ObsidianDerivedStateStore
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

__all__ = [
    "CampaignStateCapability",
    "CampaignStateStatus",
    "PlayerCampaignEntityReference",
    "PlayerCampaignStateView",
    "compose_campaign_state_capability",
]


@dataclass(frozen=True, slots=True)
class PlayerCampaignStateView:
    """Player-facing Campaign-State view.

    It deliberately carries only what the player-facing TUI may render:

    - the exact trusted :class:`CampaignStateStatus`;
    - the PLAYER-safe projected ``recently_touched`` references, present
      (possibly empty) only for a verified ``CURRENT`` generation.

    Internal ``CampaignState``, manifest, input fingerprint, provenance,
    revision, internal visibility, inspection cause and arbitrary detail are
    structurally absent.  ``recently_touched is None`` means no player-safe
    semantic content is available for the current status.
    """

    status: CampaignStateStatus
    recently_touched: tuple[PlayerCampaignEntityReference, ...] | None = None


class CampaignStateCapability:
    """Interactive Campaign-State capability over the trusted materialization.

    Inspect is read-only and never writes derived artifacts.  Rebuild is the
    explicit, user-triggered ensure-current path (noncanonical derived-cache
    maintenance only).
    """

    def __init__(
        self,
        *,
        vault_repository: ObsidianVaultRepository,
        session_repository: ObsidianSessionMetadataRepository,
        world_time_repository: ObsidianWorldTimeRepository,
        derived_state_store: ObsidianDerivedStateStore,
        recent_session_limit: int,
    ) -> None:
        self._vault_repository = vault_repository
        self._session_repository = session_repository
        self._world_time_repository = world_time_repository
        self._derived_state_store = derived_state_store
        self._recent_session_limit = recent_session_limit

    @property
    def recent_session_limit(self) -> int:
        """The effective recent-session selection limit for this capability."""
        return self._recent_session_limit

    def inspect(self) -> PlayerCampaignStateView:
        """Return the current status plus PLAYER-safe content when CURRENT.

        Only a verified ``CURRENT`` generation contributes player-facing
        semantic content.  Every other status is reported without any semantic
        data and without forwarding raw inspection detail.
        """
        inspection = inspect_campaign_state(
            vault_repository=self._vault_repository,
            session_repository=self._session_repository,
            world_time_repository=self._world_time_repository,
            derived_state_store=self._derived_state_store,
            recent_session_limit=self._recent_session_limit,
        )
        if inspection.status is CampaignStateStatus.CURRENT and inspection.state is not None:
            projected = project_player_campaign_state(inspection.state)
            return PlayerCampaignStateView(
                status=CampaignStateStatus.CURRENT,
                recently_touched=projected.recently_touched,
            )
        return PlayerCampaignStateView(status=inspection.status)

    def rebuild(self) -> PlayerCampaignStateView:
        """Ensure-current (derived maintenance) then return PLAYER-safe content.

        Uses only the trusted materialization capability.  No canonical audit
        record and no write-policy claim are made: this maintains rebuildable
        derived artifacts only.
        """
        result = rebuild_campaign_state(
            vault_repository=self._vault_repository,
            session_repository=self._session_repository,
            world_time_repository=self._world_time_repository,
            derived_state_store=self._derived_state_store,
            recent_session_limit=self._recent_session_limit,
        )
        projected = project_player_campaign_state(result.state)
        return PlayerCampaignStateView(
            status=CampaignStateStatus.CURRENT,
            recently_touched=projected.recently_touched,
        )


def compose_campaign_state_capability(vault_root: Path) -> CampaignStateCapability:
    """Compose the interactive Campaign-State capability for a Vault root.

    Reuses the single production Fast-Agent recent-session policy value so the
    assistant and the TUI derive from the same effective selection limit.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))

    return CampaignStateCapability(
        vault_repository=ObsidianVaultRepository(
            vault_root=str(vault_root),
            audit_service=audit_service,
        ),
        session_repository=ObsidianSessionMetadataRepository(vault_root, audit_service),
        world_time_repository=ObsidianWorldTimeRepository(vault_root, audit_service),
        derived_state_store=ObsidianDerivedStateStore(vault_root),
        recent_session_limit=FAST_AGENT_RECENT_SESSION_LIMIT,
    )
