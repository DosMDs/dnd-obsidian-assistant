"""World-time repository composition for the deterministic admin surface.

This module owns concrete construction for the canonical world-time repository
used by ``dnd time init``.  It owns no mutation policy: initialize-once semantics
and audit sequencing live in ``ObsidianWorldTimeRepository``.

This module is a composition layer and may import concrete storage.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

__all__ = ["compose_world_time_repository"]


def compose_world_time_repository(vault_root: Path) -> ObsidianWorldTimeRepository:
    """Build the canonical world-time repository for a Vault root."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    return ObsidianWorldTimeRepository(vault_root, audit_service)
