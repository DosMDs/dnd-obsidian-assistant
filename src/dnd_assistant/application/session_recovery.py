"""Session recovery service — application-level recovery orchestration.

This module composes ``SessionRecoveryRepository`` to provide explicit,
deterministic recovery operations for failure states.

This module belongs to the application layer and must not import from:
    models, tools, ollama
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditContext
    from dnd_assistant.storage.session_recovery import (
        RecoveryActionResult,
        SessionRecoveryReport,
        SessionRecoveryRepository,
    )


class SessionRecoveryService:
    """Application service for session runtime recovery operations.

    Composes ``SessionRecoveryRepository`` to provide explicit recovery
    methods corresponding to inspect, audit-tail repair, partial-start
    cleanup, and event-tail repair.

    No filesystem calls in this service.  No model/tool imports.

    Args:
        recovery_repo: The session recovery repository.
    """

    def __init__(self, recovery_repo: SessionRecoveryRepository) -> None:
        self._recovery_repo = recovery_repo

    def inspect_runtime(self) -> SessionRecoveryReport:
        """Read-only inspection of current Vault runtime state.

        Returns:
            A ``SessionRecoveryReport`` with all discovered issues.
        """
        return self._recovery_repo.inspect_runtime()

    def repair_audit_tail(
        self,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Repair a provably partial final audit-log tail.

        Args:
            audit: Audit context for the recovery marker.

        Returns:
            A ``RecoveryActionResult`` with before/after hashes.
        """
        return self._recovery_repo.repair_audit_tail(audit=audit)

    def cleanup_partial_start(
        self,
        session_id: str,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Clean up a provably owned partial session start.

        Args:
            session_id: The session identifier to clean up.
            audit: Audit context for this recovery operation.

        Returns:
            A ``RecoveryActionResult`` with before/after composite
            snapshot hashes.
        """
        return self._recovery_repo.cleanup_partial_start(session_id, audit=audit)

    def repair_event_tail(
        self,
        session_id: str,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Repair a provably partial final event-log tail.

        Args:
            session_id: The session identifier.
            audit: Audit context for this recovery operation.

        Returns:
            A ``RecoveryActionResult`` with before/after hashes.
        """
        return self._recovery_repo.repair_event_tail(session_id, audit=audit)
