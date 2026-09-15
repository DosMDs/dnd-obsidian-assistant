"""Session recovery service — application-level recovery orchestration.

This module composes ``SessionRecoveryRepository`` to provide explicit,
deterministic recovery operations for failure states.

``inspect_runtime`` preserves raw recovery truth unchanged.  Mutation preflight
consumers instead use ``inspect_runtime_partition``, which narrows *blocking
scope* (never detection/reporting scope) through an optional application-layer
``IntentOwnershipGate``.

This module belongs to the application layer and must not import from:
    models, tools, ollama
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditContext
    from dnd_assistant.storage.session_recovery import (
        RecoveryActionResult,
        RecoveryIssue,
        SessionRecoveryReport,
        SessionRecoveryRepository,
    )


@dataclass(frozen=True)
class RecoveryPartition:
    """Raw recovery issues split by blocking scope.

    ``blocking`` issues must still stop a mutation preflight.  ``externally_owned``
    issues are raw issues whose safe handling is delegated to another application
    owner (currently ChangeSet status/applicability) and therefore must not block
    unrelated mutations.  Raw detection and reporting are unchanged: the full
    report is always available through ``SessionRecoveryService.inspect_runtime``.
    """

    blocking: tuple[RecoveryIssue, ...]
    externally_owned: tuple[RecoveryIssue, ...]


@runtime_checkable
class IntentOwnershipGate(Protocol):
    """Structural contract for a recovery-issue ownership partitioner.

    ``ChangeSetIntentOwnershipGate`` satisfies this protocol.  The session
    recovery service depends on the protocol so that it stays independent of
    ChangeSet semantics.
    """

    def partition(self, report: SessionRecoveryReport) -> RecoveryPartition: ...


@runtime_checkable
class SessionRecovery(Protocol):
    """Structural contract for the session recovery service.

    ``SessionRecoveryService`` satisfies this protocol.  Tools depend on the
    protocol so that deterministic test doubles can stand in for the
    application service without inheriting from the concrete class.
    """

    def inspect_runtime(self) -> SessionRecoveryReport: ...

    def inspect_runtime_partition(self) -> RecoveryPartition: ...


class SessionRecoveryService:
    """Application service for session runtime recovery operations.

    Composes ``SessionRecoveryRepository`` to provide explicit recovery
    methods corresponding to inspect, audit-tail repair, partial-start
    cleanup, and event-tail repair.

    No filesystem calls in this service.  No model/tool imports.

    Args:
        recovery_repo: The session recovery repository.
        ownership_gate: Optional application-layer partitioner that delegates
            conclusively ChangeSet-owned issues.  When omitted, every raw issue
            is blocking (unchanged legacy behaviour).
    """

    def __init__(
        self,
        recovery_repo: SessionRecoveryRepository,
        *,
        ownership_gate: IntentOwnershipGate | None = None,
    ) -> None:
        self._recovery_repo = recovery_repo
        self._ownership_gate = ownership_gate

    def inspect_runtime(self) -> SessionRecoveryReport:
        """Read-only inspection of current Vault runtime state.

        Returns the complete/raw report exactly as session recovery detects it,
        including any ChangeSet-owned ``unresolved_audit_intent`` issues.

        Returns:
            A ``SessionRecoveryReport`` with all discovered issues.
        """
        return self._recovery_repo.inspect_runtime()

    def inspect_runtime_partition(self) -> RecoveryPartition:
        """Partition the raw report into blocking and externally-owned issues.

        Mutation preflight consumers use ``blocking``; diagnostic callers keep
        using :meth:`inspect_runtime` to observe every original issue.  When no
        ownership gate is composed, all issues are blocking.

        Returns:
            A ``RecoveryPartition`` with both issue subsets.
        """
        report = self._recovery_repo.inspect_runtime()
        if self._ownership_gate is None:
            return RecoveryPartition(blocking=tuple(report.issues), externally_owned=())
        return self._ownership_gate.partition(report)

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
