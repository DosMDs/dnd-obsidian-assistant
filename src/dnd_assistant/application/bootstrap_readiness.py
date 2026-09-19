"""S13-04 bootstrap approval / apply readiness gates.

Typed, fail-closed readiness assessment for a persisted bootstrap proposal.  Two
distinct gates share the evidence/freshness/coverage/projection logic:

- *approval readiness* may be satisfied on a mixed historical Vault as long as
  evidence binding, semantic freshness, canonical coverage and projection
  consistency hold; a strict repository is deliberately **not** required;
- *apply readiness* additionally requires a strict, currently-valid
  ``VaultRepository`` and a passing fresh Stage-10 preflight, because canonical
  mutation must never bypass repository readiness.

The strict probe is read-only: it runs ``validate_changeset`` through the narrow
``EntityReadSource`` protocol, which performs no mutation and no ChangeSet
operation audit intent.  Only typed project errors (``StorageError`` /
``ConflictError``) are caught to classify strict unavailability; exception
messages are never parsed.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, a concrete
    storage implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.bootstrap_canonical import (
    CanonicalCoverage,
    CanonicalStateSnapshot,
)
from dnd_assistant.application.bootstrap_evidence import BootstrapEvidenceRecord
from dnd_assistant.application.bootstrap_input import BootstrapInputProjection
from dnd_assistant.application.bootstrap_review import (
    BootstrapEvidenceIssue,
    assess_source_freshness,
    validate_bootstrap_evidence,
)
from dnd_assistant.application.changeset_review import ChangeSetApproval
from dnd_assistant.application.changeset_validation import (
    ChangeSetValidationResult,
    validate_changeset,
)
from dnd_assistant.domain.changeset import ChangeSet
from dnd_assistant.domain.types import Provenance
from dnd_assistant.errors import ConflictError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.application.changeset_validation import EntityReadSource


class BootstrapApplyReadiness(StrEnum):
    """Typed outcome of a bootstrap approval / apply readiness assessment."""

    READY = "ready"
    NOT_APPROVED = "not_approved"
    MISSING_EVIDENCE = "missing_evidence"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    STALE_SOURCE = "stale_source"
    INCOMPLETE_CANONICAL_COVERAGE = "incomplete_canonical_coverage"
    PROJECTION_INCONSISTENT = "projection_inconsistent"
    UNRESOLVED_NOT_ACKNOWLEDGED = "unresolved_not_acknowledged"
    STRICT_REPOSITORY_NOT_READY = "strict_repository_not_ready"
    CHANGESET_PREFLIGHT_FAILED = "changeset_preflight_failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class BootstrapReadinessResult:
    """Read-only readiness result with typed diagnostics."""

    readiness: BootstrapApplyReadiness
    detail: str | None = None
    issues: tuple[BootstrapEvidenceIssue, ...] = ()
    validation: ChangeSetValidationResult | None = None


def _evidence_gate(
    changeset: ChangeSet,
    evidence_record: BootstrapEvidenceRecord | None,
    evidence_present: bool,
    projection: BootstrapInputProjection,
) -> BootstrapReadinessResult | None:
    """Return a blocking readiness result, or ``None`` when evidence passes."""
    if changeset.provenance.provenance is not Provenance.BOOTSTRAP:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.EVIDENCE_MISMATCH,
            detail="Proposal provenance is not bootstrap",
        )
    if not evidence_present or evidence_record is None:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.MISSING_EVIDENCE,
            detail="Bootstrap mapping evidence is absent for this proposal",
        )
    issues = validate_bootstrap_evidence(evidence_record, changeset, projection)
    if issues:
        codes = ", ".join(issue.code.value for issue in issues)
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.EVIDENCE_MISMATCH,
            detail=f"Bootstrap evidence failed cross-validation: {codes}",
            issues=issues,
        )
    if not assess_source_freshness(evidence_record, projection):
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.STALE_SOURCE,
            detail="Campaign source material changed since bootstrap mapping",
        )
    return None


def assess_bootstrap_approval_readiness(
    changeset: ChangeSet,
    *,
    evidence_record: BootstrapEvidenceRecord | None,
    evidence_present: bool,
    projection: BootstrapInputProjection,
    coverage: CanonicalCoverage,
    snapshot: CanonicalStateSnapshot,
    acknowledge_unresolved: bool,
) -> BootstrapReadinessResult:
    """Assess whether the proposal may be approved (no strict repository needed).

    This gate deliberately does not require strict repository readiness: a mixed
    historical Vault may still be reviewable/approvable once evidence binding,
    freshness, coverage and projection consistency hold.
    """
    blocked = _evidence_gate(changeset, evidence_record, evidence_present, projection)
    if blocked is not None:
        return blocked

    if not coverage.complete:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.INCOMPLETE_CANONICAL_COVERAGE,
            detail=(
                f"Canonical coverage is incomplete ({len(coverage.issues)} issue(s)); "
                "approval is refused"
            ),
        )

    consistency = validate_changeset(changeset, snapshot)
    if not consistency.valid:
        codes = ", ".join(issue.code.value for issue in consistency.issues)
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.PROJECTION_INCONSISTENT,
            detail=f"Proposal is inconsistent with the current canonical projection: {codes}",
            validation=consistency,
        )

    assert evidence_record is not None  # guaranteed by _evidence_gate
    if evidence_record.unresolved and not acknowledge_unresolved:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.UNRESOLVED_NOT_ACKNOWLEDGED,
            detail=(
                f"Evidence contains {len(evidence_record.unresolved)} unresolved item(s); "
                "explicit acknowledgement is required"
            ),
        )

    return BootstrapReadinessResult(readiness=BootstrapApplyReadiness.READY)


def assess_bootstrap_preconditions(
    changeset: ChangeSet,
    *,
    evidence_record: BootstrapEvidenceRecord | None,
    evidence_present: bool,
    projection: BootstrapInputProjection,
    coverage: CanonicalCoverage,
    snapshot: CanonicalStateSnapshot,
    strict_repository: EntityReadSource | None,
) -> BootstrapReadinessResult:
    """Assess the strict apply prerequisites, excluding approval/acknowledgement.

    Used to render apply readiness during read-only review.  The strict probe is
    read-only and performs no ChangeSet audit intent.
    """
    blocked = _evidence_gate(changeset, evidence_record, evidence_present, projection)
    if blocked is not None:
        return blocked

    if not coverage.complete:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.INCOMPLETE_CANONICAL_COVERAGE,
            detail=f"Canonical coverage is incomplete ({len(coverage.issues)} issue(s))",
        )

    consistency = validate_changeset(changeset, snapshot)
    if not consistency.valid:
        codes = ", ".join(issue.code.value for issue in consistency.issues)
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.PROJECTION_INCONSISTENT,
            detail=f"Proposal is inconsistent with the canonical projection: {codes}",
            validation=consistency,
        )

    if strict_repository is None:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY,
            detail="Strict Vault repository could not be constructed",
        )

    try:
        strict_validation = validate_changeset(changeset, strict_repository)
    except (StorageError, ConflictError) as exc:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY,
            detail=f"Strict Vault repository is not ready: {exc}",
        )

    if not strict_validation.valid:
        codes = ", ".join(issue.code.value for issue in strict_validation.issues)
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.CHANGESET_PREFLIGHT_FAILED,
            detail=f"Proposal failed the strict Stage-10 preflight: {codes}",
            validation=strict_validation,
        )

    return BootstrapReadinessResult(
        readiness=BootstrapApplyReadiness.READY,
        validation=strict_validation,
    )


def assess_bootstrap_apply_readiness(
    changeset: ChangeSet,
    *,
    evidence_record: BootstrapEvidenceRecord | None,
    evidence_present: bool,
    projection: BootstrapInputProjection,
    coverage: CanonicalCoverage,
    snapshot: CanonicalStateSnapshot,
    strict_repository: EntityReadSource | None,
    approval: ChangeSetApproval | None,
    acknowledge_unresolved: bool,
) -> BootstrapReadinessResult:
    """Assess whether the exact proposal may be applied through the bootstrap path.

    Ordering: evidence binding -> freshness -> coverage -> projection
    consistency -> unresolved acknowledgement -> approval binding -> strict
    repository readiness + fresh strict preflight.  A generic approval artifact
    is never sufficient here; the bootstrap gates always run independently.
    """
    preconditions = assess_bootstrap_preconditions(
        changeset,
        evidence_record=evidence_record,
        evidence_present=evidence_present,
        projection=projection,
        coverage=coverage,
        snapshot=snapshot,
        strict_repository=strict_repository,
    )
    if preconditions.readiness is not BootstrapApplyReadiness.READY:
        return preconditions

    assert evidence_record is not None  # guaranteed by the preconditions
    if evidence_record.unresolved and not acknowledge_unresolved:
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.UNRESOLVED_NOT_ACKNOWLEDGED,
            detail=(
                f"Evidence contains {len(evidence_record.unresolved)} unresolved item(s); "
                "explicit acknowledgement is required"
            ),
        )

    if approval is None or not approval.matches_approved_changeset(changeset):
        return BootstrapReadinessResult(
            readiness=BootstrapApplyReadiness.NOT_APPROVED,
            detail="No content-bound bootstrap approval authorizes this exact proposal",
        )

    return BootstrapReadinessResult(
        readiness=BootstrapApplyReadiness.READY,
        validation=preconditions.validation,
    )


__all__ = [
    "BootstrapApplyReadiness",
    "BootstrapReadinessResult",
    "assess_bootstrap_apply_readiness",
    "assess_bootstrap_approval_readiness",
    "assess_bootstrap_preconditions",
]
