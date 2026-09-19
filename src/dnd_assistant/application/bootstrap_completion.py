"""S13-05 bootstrap completion policy and typed result.

Pure application-layer policy for the final bootstrap finalization step.  It owns
the unambiguous typed completion vocabulary and the closure classification over
the trusted S13-03 mapping outcome.  Python decides completion; the model only
supplies the typed ``BootstrapMappingResult``.

Invariants:

- completion is never a single ambiguous boolean; every terminal condition has an
  explicit status;
- canonical coverage is a structural safety prerequisite and can never be
  acknowledged away (``--acknowledge-unresolved`` applies to ordinary unresolved
  diagnostics only);
- a source-stability failure is distinct from an ordinary derived-maintenance
  failure.

This module belongs to the application layer and must not import from:
    storage (runtime), models, ollama, pydantic_ai, tools, cli, retrieval,
    pathlib, os.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.application.bootstrap_result import BootstrapMappingOutcome
from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateStatus,
)
from dnd_assistant.domain.types import Sha256Fingerprint

__all__ = [
    "BootstrapClosureInput",
    "BootstrapCompletionResult",
    "BootstrapCompletionStatus",
    "classify_bootstrap_closure",
]


class BootstrapCompletionStatus(StrEnum):
    """Explicit terminal status of one ``dnd bootstrap finalize`` invocation."""

    COMPLETE = "complete"
    COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED = "complete_with_acknowledged_unresolved"

    UNINITIALIZED_VAULT = "uninitialized_vault"
    RECOVERY_BLOCKED = "recovery_blocked"
    CANONICAL_NOT_READY = "canonical_not_ready"

    CANONICAL_COVERAGE_INCOMPLETE = "canonical_coverage_incomplete"
    WORLD_TIME_UNINITIALIZED = "world_time_uninitialized"
    WORLD_TIME_INVALID = "world_time_invalid"
    ACTIVE_SESSION_PRESENT = "active_session_present"

    MAPPING_FAILED = "mapping_failed"
    PROPOSAL_PERSISTENCE_FAILED = "proposal_persistence_failed"
    EVIDENCE_PERSISTENCE_FAILED = "evidence_persistence_failed"
    PENDING_CHANGESET = "pending_changeset"
    UNRESOLVED_NOT_ACKNOWLEDGED = "unresolved_not_acknowledged"

    SOURCE_CHANGED_DURING_VALIDATION = "source_changed_during_validation"
    CAMPAIGN_STATE_REBUILD_FAILED = "campaign_state_rebuild_failed"
    FTS_REBUILD_FAILED = "fts_rebuild_failed"
    DERIVED_VERIFICATION_FAILED = "derived_verification_failed"

    @property
    def is_completed(self) -> bool:
        """True only for the two operational-completion outcomes."""
        return self in (
            BootstrapCompletionStatus.COMPLETE,
            BootstrapCompletionStatus.COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED,
        )


@dataclass(frozen=True, slots=True)
class BootstrapClosureInput:
    """Trusted closure inputs derived from one fresh S13-03 mapping run."""

    outcome: BootstrapMappingOutcome
    coverage_complete: bool
    unresolved_count: int
    proposal_persisted: bool
    evidence_persistence_failed: bool
    changeset_id: str | None = None


@dataclass(frozen=True, slots=True)
class BootstrapCompletionResult:
    """Complete typed result of one bootstrap finalization.

    ``status`` is the primary outcome; ``issues`` preserves every observed
    sub-failure so no secondary problem is concealed by the primary status.
    """

    status: BootstrapCompletionStatus
    campaign_id: str | None = None
    completion_fingerprint: Sha256Fingerprint | None = None
    mapping_outcome: BootstrapMappingOutcome | None = None
    changeset_id: str | None = None
    coverage_complete: bool | None = None
    unresolved_count: int = 0
    unresolved_acknowledged: bool = False
    canonical_documents: int | None = None
    current_world_tick: int | None = None
    active_session_id: str | None = None
    campaign_state_status: CampaignStateStatus | None = None
    fts_verified: bool = False
    final_source_stable: bool = False
    detail: str | None = None
    issues: tuple[str, ...] = ()

    @property
    def completed(self) -> bool:
        """True only for ``COMPLETE`` / ``COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED``."""
        return self.status.is_completed


def classify_bootstrap_closure(
    closure: BootstrapClosureInput,
    *,
    acknowledge_unresolved: bool,
) -> BootstrapCompletionStatus | None:
    """Return a blocking closure status, or ``None`` to proceed to rebuilds.

    Ordering:

    1. incomplete canonical coverage is a structural safety prerequisite and is
       never acknowledgeable;
    2. evidence persistence failure after a stable source is truthful partial
       workflow persistence;
    3. a produced proposal requires review/apply before completion;
    4. ordinary unresolved diagnostics require explicit acknowledgement.
    """
    if not closure.coverage_complete:
        return BootstrapCompletionStatus.CANONICAL_COVERAGE_INCOMPLETE

    if closure.evidence_persistence_failed:
        return BootstrapCompletionStatus.EVIDENCE_PERSISTENCE_FAILED

    if closure.outcome is BootstrapMappingOutcome.PROPOSAL:
        return BootstrapCompletionStatus.PENDING_CHANGESET

    if closure.unresolved_count and not acknowledge_unresolved:
        return BootstrapCompletionStatus.UNRESOLVED_NOT_ACKNOWLEDGED

    return None
