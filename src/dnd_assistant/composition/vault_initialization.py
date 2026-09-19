"""S13-01 shared Vault-initialization composition.

This module owns concrete dependency construction for ``dnd init`` so that
presentation surfaces stay free of storage/composition details.  It contains
no Russian text and no ``typer``/``textual`` types.

The ``AuditService`` cannot be constructed before ``_system/audit/`` exists
(``AuditService`` requires its parent directory).  The storage initializer
therefore receives a zero-argument factory and invokes it only after
bootstrapping the canonical audit directory.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.vault_initialization import VaultInitializationService
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.vault_initialization import ObsidianVaultInitializer


def compose_vault_initializer(vault_root: str | Path) -> ObsidianVaultInitializer:
    """Compose the trusted S13-01 storage initializer for a Vault root.

    The initializer exposes the read-only ``inspect()`` layout report and the
    mutating initialization/repair operations.  Sharing this construction keeps
    the S13-01 initialization precondition identical across admin surfaces.

    Args:
        vault_root: The selected Vault root (resolved once here so the audit
            factory targets the physical authoritative root).

    Returns:
        A ready-to-use ``ObsidianVaultInitializer``.
    """
    resolved_root = Path(vault_root).expanduser().resolve(strict=False)

    def _audit_service_factory() -> AuditService:
        audit_log_path = resolved_root / "_system" / "audit" / "audit.jsonl"
        return AuditService(str(audit_log_path))

    return ObsidianVaultInitializer(resolved_root, _audit_service_factory)


def compose_vault_initialization_service(
    vault_root: str | Path,
) -> VaultInitializationService:
    """Compose a ready-to-use ``VaultInitializationService``.

    Args:
        vault_root: The selected Vault root (resolved once here so the audit
            factory targets the physical authoritative root).

    Returns:
        A ready-to-use ``VaultInitializationService``.
    """
    return VaultInitializationService(compose_vault_initializer(vault_root))


__all__ = ["compose_vault_initialization_service", "compose_vault_initializer"]
