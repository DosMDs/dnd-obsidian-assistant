"""Shared session runtime and recovery composition (TUI-02).

This module owns presentation-neutral construction of the trusted session
capabilities shared by the Typer CLI and the future Textual TUI:

- ``compose_session_runtime`` builds a fully wired ``SessionRuntimeService``;
- ``compose_recovery_service`` builds a ``SessionRecoveryService`` including
  the ChangeSet intent-ownership gate used for recovery preflight.

It owns concrete dependency construction only.  It contains no Russian text,
no ``typer`` types and no recovery policy of its own: the trusted policy lives
in ``application`` and the presentation mapping stays in the CLI/TUI layer.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.changeset_recovery import ChangeSetIntentOwnershipGate
from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.session_recovery import ObsidianSessionRecoveryRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository


def compose_session_runtime(vault_root: Path) -> SessionRuntimeService:
    """Compose a fully wired ``SessionRuntimeService`` for a Vault root.

    Args:
        vault_root: The resolved Vault root path.

    Returns:
        A ready-to-use ``SessionRuntimeService``.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))

    session_repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_service)
    world_time_repo = ObsidianWorldTimeRepository(vault_root, audit_service)

    return SessionRuntimeService(session_repo, world_time_repo, event_repo)


def compose_recovery_service(vault_root: Path) -> SessionRecoveryService:
    """Compose a ``SessionRecoveryService`` for recovery preflight.

    The ChangeSet ownership gate narrows blocking scope only: conclusively
    ChangeSet-owned intent-only audit records are delegated to
    ``dnd changeset status`` / the ChangeSet applicability gate instead of
    wedging unrelated mutations.  Raw inspection remains available through
    ``inspect_runtime``.

    Args:
        vault_root: The resolved Vault root path.

    Returns:
        A ready-to-use ``SessionRecoveryService``.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))

    recovery_repo = ObsidianSessionRecoveryRepository(vault_root, audit_service)
    ownership_gate = ChangeSetIntentOwnershipGate(
        ObsidianChangeSetStore(vault_root),
        read_audit_records=audit_service.read_all,
    )
    return SessionRecoveryService(recovery_repo, ownership_gate=ownership_gate)
