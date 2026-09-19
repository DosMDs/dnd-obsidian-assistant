"""World-time composition for the deterministic admin surface.

This module owns concrete construction for the canonical world-time repository
used by ``dnd time init`` and the read-only S13-01 initialization precondition
that must hold before a starting-world-time mutation is allowed.  It owns no
world-time mutation policy: initialize-once semantics and audit sequencing live
in ``ObsidianWorldTimeRepository``.

This module is a composition layer and may import concrete storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dnd_assistant.composition.vault_initialization import compose_vault_initializer
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.vault_initialization import CampaignConfigState
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

__all__ = [
    "WorldTimeInitPrecondition",
    "WorldTimeInitStatus",
    "compose_world_time_repository",
    "inspect_world_time_init_precondition",
]


class WorldTimeInitStatus(StrEnum):
    """Read-only classification of the S13-01 precondition for ``dnd time init``."""

    READY = "ready"
    UNINITIALIZED_VAULT = "uninitialized_vault"
    INVALID_VAULT = "invalid_vault"
    INCOMPLETE_LAYOUT = "incomplete_layout"


@dataclass(frozen=True, slots=True)
class WorldTimeInitPrecondition:
    """Result of the read-only S13-01 initialization-state check.

    ``campaign_id`` is present only for a ``READY`` Vault.  ``detail`` carries the
    trusted failure detail for ``INVALID_VAULT``/``INCOMPLETE_LAYOUT``.
    """

    status: WorldTimeInitStatus
    campaign_id: str | None = None
    detail: str | None = None


def compose_world_time_repository(vault_root: Path) -> ObsidianWorldTimeRepository:
    """Build the canonical world-time repository for a Vault root."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    return ObsidianWorldTimeRepository(vault_root, audit_service)


def inspect_world_time_init_precondition(vault_root: Path) -> WorldTimeInitPrecondition:
    """Validate the S13-01 initialized-Vault precondition without mutating anything.

    Reuses the trusted S13-01 storage capability (``ObsidianVaultInitializer``)
    rather than re-parsing ``campaign.yaml`` or re-implementing the managed
    layout policy.  A valid marker is required, and the managed S13-01 layout
    must already be complete; this surface never repairs the Vault.

    Raises:
        Nothing: trusted failures are returned as typed statuses.
    """
    try:
        report = compose_vault_initializer(vault_root).inspect()
    except DndAssistantError as exc:
        return WorldTimeInitPrecondition(status=WorldTimeInitStatus.INVALID_VAULT, detail=str(exc))

    if report.config_state is not CampaignConfigState.VALID:
        return WorldTimeInitPrecondition(status=WorldTimeInitStatus.UNINITIALIZED_VAULT)

    if report.campaign_id is None:
        return WorldTimeInitPrecondition(
            status=WorldTimeInitStatus.INVALID_VAULT,
            detail="campaign.yaml is valid but exposes no campaign identity",
        )

    if report.missing_directories:
        missing = ", ".join(relative.as_posix() for relative in report.missing_directories)
        return WorldTimeInitPrecondition(
            status=WorldTimeInitStatus.INCOMPLETE_LAYOUT,
            campaign_id=report.campaign_id,
            detail=f"missing managed directories: {missing}",
        )

    return WorldTimeInitPrecondition(
        status=WorldTimeInitStatus.READY, campaign_id=report.campaign_id
    )
