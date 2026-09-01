"""ObsidianSessionRecoveryRepository — concrete filesystem-backed recovery.

This module provides the concrete ``ObsidianSessionRecoveryRepository``
that orchestrates read-only inspection and explicit recovery operations
by delegating to focused internal modules.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.session_metadata import (
    _validate_session_runtime_roots,
)
from dnd_assistant.storage.session_recovery.audit_tail import repair_audit_tail
from dnd_assistant.storage.session_recovery.event_tail import repair_event_tail
from dnd_assistant.storage.session_recovery.inspection import inspect_runtime
from dnd_assistant.storage.session_recovery.partial_start import cleanup_partial_start
from dnd_assistant.storage.session_recovery.types import (
    RecoveryActionResult,
    SessionRecoveryReport,
)


class ObsidianSessionRecoveryRepository:
    """Concrete session recovery repository backed by the Vault filesystem.

    Provides read-only inspection and explicit recovery operations for
    failure states left by partial session starts, corrupt event tails,
    and corrupt audit tails.

    Args:
        vault_root: The root directory of the Obsidian Vault.
        audit_service: The audit service for logging recovery operations.

    Raises:
        StorageError: The Vault root is invalid, or the audit path is
            misconfigured.
    """

    def __init__(
        self,
        vault_root: str | Path,
        audit_service: AuditService,
    ) -> None:
        self._vault_root = Path(vault_root).resolve(strict=False)
        if not self._vault_root.is_dir():
            raise StorageError(f"Vault root must be an existing directory: {self._vault_root}")

        self._audit_service = audit_service

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    # ── Runtime root validation ───────────────────────────────────────────

    def _validate_roots(self) -> None:
        """Validate canonical session runtime roots.

        Raises:
            StorageError: A root is unsafe.
        """
        _validate_session_runtime_roots(self._vault_root)

    def _reauthorize_roots(self) -> None:
        """Reauthorize runtime roots after a durable audit intent.

        Raises:
            StorageError: A root became unsafe.
        """
        _validate_session_runtime_roots(self._vault_root)

    # ── inspect_runtime — read-only ───────────────────────────────────────

    def inspect_runtime(self) -> SessionRecoveryReport:
        """Read-only inspection of current Vault runtime state.

        This method must NOT write, truncate, delete, or modify any
        filesystem state.

        Returns:
            A ``SessionRecoveryReport`` with ordered issues.

        Raises:
            StorageError: A canonical runtime root is unsafe.
        """
        return inspect_runtime(self._vault_root, self._audit_service)

    # ── repair_audit_tail — self-targeting recovery ───────────────────────

    def repair_audit_tail(
        self,
        *,
        audit,
    ) -> RecoveryActionResult:
        """Repair a provably partial final audit-log tail.

        This is an exceptional self-targeting recovery path.  The audit
        log cannot write a durable intent into itself while corrupt, so
        the normal two-phase audit is replaced by:
        repair -> verify -> append recovery marker.

        Args:
            audit: Audit context for the recovery marker.

        Returns:
            A ``RecoveryActionResult`` with before/after hashes.

        Raises:
            ConflictError: The audit log changed between inspection and
                repair.
            StorageError: The corruption is not limited to the final tail,
                or the repair itself failed.
        """
        return repair_audit_tail(self._audit_service, audit=audit)

    # ── cleanup_partial_start — explicit cleanup ──────────────────────────

    def cleanup_partial_start(
        self,
        session_id: str,
        *,
        audit,
    ) -> RecoveryActionResult:
        """Clean up a provably owned partial session start.

        Only exact known-empty artifacts are removed.  No recursive
        deletion.  No unexpected content is removed.

        Args:
            session_id: The session identifier to clean up.
            audit: Audit context for this recovery operation.

        Returns:
            A ``RecoveryActionResult`` with before/after composite
            snapshot hashes.

        Raises:
            ConflictError: The partial-start state changed between
                inspection and cleanup.
            StorageError: The state is not safely recoverable, or a
                filesystem operation failed.
        """
        return cleanup_partial_start(self._vault_root, self._audit_service, session_id, audit=audit)

    # ── repair_event_tail — append-LF or truncate ─────────────────────────

    def repair_event_tail(
        self,
        session_id: str,
        *,
        audit,
    ) -> RecoveryActionResult:
        """Repair a provably partial final event-log tail.

        Recovery is allowed only when:
        - Canonical metadata exists with active/completed status.
        - The audit log is clean (no partial tail, no corruption).

        Args:
            session_id: The session identifier.
            audit: Audit context for this recovery operation.

        Returns:
            A ``RecoveryActionResult`` with before/after hashes.

        Raises:
            ConflictError: The events file changed between inspection and
                repair.
            StorageError: The corruption is not limited to the final tail,
                or the repair itself failed.
        """
        return repair_event_tail(self._vault_root, self._audit_service, session_id, audit=audit)
