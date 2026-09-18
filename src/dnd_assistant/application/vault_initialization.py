"""S13-01 Vault initialization application policy.

This module owns the deterministic initialization state machine, campaign
identity decision and typed result.  It never touches the filesystem and
never depends on a concrete storage implementation or ``AuditService``:
filesystem authorization, mutation and audit persistence mechanics are
owned by the ``VaultInitializer`` capability implemented in the storage
layer.

State semantics
===============

``_system/campaign.yaml`` is the single authoritative initialization commit
marker:

    initialization committed
        valid campaign.yaml exists

    initialization complete
        valid campaign.yaml
        + all required managed directories exist
        + all managed topology is safe

A Vault with a valid marker but missing managed directories is *committed
but not complete*; ``dnd init`` repairs the missing directories without
rewriting the marker.

This module belongs to the application layer and must not import from:
    storage.audit (concrete), models, tools, retrieval, cli, ollama,
    pydantic_ai.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.vault_initialization import (
    CAMPAIGN_CONFIG_RELATIVE,
    CampaignConfigState,
    VaultInitializer,
)

_CAMPAIGN_ID_PREFIX = "camp_"
_CAMPAIGN_ID_BYTES = 16


class VaultInitializationStatus(StrEnum):
    """Outcome status of a ``dnd init`` invocation."""

    CREATED = "created"
    ALREADY_INITIALIZED = "already_initialized"
    COMPLETED_PARTIAL = "completed_partial"


@dataclass(frozen=True, slots=True)
class VaultInitializationResult:
    """Typed result of a ``dnd init`` invocation.

    Only fields required by the CLI and tests are present.  Directories are
    reported as Vault-relative POSIX strings.
    """

    status: VaultInitializationStatus
    campaign_id: str
    created_directories: tuple[str, ...]
    config_relative_path: str
    audit_recorded: bool


def generate_campaign_id() -> str:
    """Generate a stable-once opaque campaign identity.

    The value is random but persisted, so re-runs never regenerate it.  It
    is deliberately not derived from folder names, the Vault path or any
    campaign content.
    """
    return f"{_CAMPAIGN_ID_PREFIX}{secrets.token_hex(_CAMPAIGN_ID_BYTES)}"


class VaultInitializationService:
    """Deterministic application service for Vault initialization.

    Args:
        initializer: The storage capability that authorizes, mutates and
            audits the Vault topology.
        campaign_id_factory: Injected identity factory, called only when the
            preflight confirms the config marker is genuinely absent.
    """

    def __init__(
        self,
        initializer: VaultInitializer,
        campaign_id_factory: Callable[[], str] = generate_campaign_id,
    ) -> None:
        self._initializer = initializer
        self._campaign_id_factory = campaign_id_factory

    def initialize(self, *, audit: AuditContext) -> VaultInitializationResult:
        """Initialize or repair the selected Vault.

        Required outcomes::

            config absent + compatible topology
                -> create layout + config          -> CREATED
            config valid + full safe layout
                -> zero writes                     -> ALREADY_INITIALIZED
            config valid + safe missing dirs
                -> repair missing dirs             -> COMPLETED_PARTIAL
            config invalid / conflicting / unsafe
                -> fail closed (StorageError)

        Raises:
            StorageError: The Vault is missing/unsafe/conflicting, or a
                mutation or audit finalization failed.
            ConflictError: An exclusive configuration publication raced and
                no valid config could be adopted.
        """
        report = self._initializer.inspect()

        if report.config_state is CampaignConfigState.VALID:
            assert report.campaign_id is not None  # noqa: S101 - validated report invariant
            if not report.missing_directories:
                return VaultInitializationResult(
                    status=VaultInitializationStatus.ALREADY_INITIALIZED,
                    campaign_id=report.campaign_id,
                    created_directories=(),
                    config_relative_path=CAMPAIGN_CONFIG_RELATIVE.as_posix(),
                    audit_recorded=False,
                )

            outcome = self._initializer.repair_layout(audit=audit)
            return VaultInitializationResult(
                status=VaultInitializationStatus.COMPLETED_PARTIAL,
                campaign_id=outcome.campaign_id,
                created_directories=tuple(p.as_posix() for p in outcome.created_directories),
                config_relative_path=CAMPAIGN_CONFIG_RELATIVE.as_posix(),
                audit_recorded=True,
            )

        campaign_id = self._campaign_id_factory()
        outcome = self._initializer.commit_initialization(campaign_id, audit=audit)
        status = (
            VaultInitializationStatus.CREATED
            if outcome.published_config
            else VaultInitializationStatus.ALREADY_INITIALIZED
        )
        return VaultInitializationResult(
            status=status,
            campaign_id=outcome.campaign_id,
            created_directories=tuple(p.as_posix() for p in outcome.created_directories),
            config_relative_path=CAMPAIGN_CONFIG_RELATIVE.as_posix(),
            audit_recorded=True,
        )


__all__ = [
    "VaultInitializationResult",
    "VaultInitializationService",
    "VaultInitializationStatus",
    "generate_campaign_id",
]
