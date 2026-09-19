"""S13-04 bootstrap review/approval/apply runtime composition.

Owns concrete dependency construction and orchestration for the bootstrap
review/approval/apply workflow so the CLI presentation layer stays free of
storage details:

- composes the accepted S13-02 read-only discovery service and the S13-03
  canonical recognition/projection;
- loads the persisted proposal + immutable evidence sidecar;
- builds the read-only review representation and typed readiness results;
- constructs the strict ``ObsidianVaultRepository`` when the Vault is
  repository-ready, without weakening it for bootstrap;
- drives the bootstrap apply orchestration (which itself reuses the Stage-10
  applier and apply-attempt ledger).

It contains no Russian text and no ``typer``/``textual`` types.  It calls no
model and performs no canonical Vault mutation.

This module is a composition layer and may import concrete storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dnd_assistant.application.bootstrap_apply import (
    BOOTSTRAP_APPLY_SOURCE,
    BootstrapApplyResult,
    apply_bootstrap_changeset,
)
from dnd_assistant.application.bootstrap_canonical import (
    CanonicalCoverage,
    CanonicalStateSnapshot,
    assess_canonical_coverage,
    build_canonical_snapshot,
)
from dnd_assistant.application.bootstrap_input import (
    BootstrapInputProjection,
    prepare_bootstrap_input,
)
from dnd_assistant.application.bootstrap_readiness import (
    BootstrapReadinessResult,
    assess_bootstrap_approval_readiness,
    assess_bootstrap_preconditions,
)
from dnd_assistant.application.bootstrap_review import (
    BootstrapArtifactBundle,
    BootstrapReviewBundle,
    build_bootstrap_review,
    load_bootstrap_bundle,
)
from dnd_assistant.application.changeset_apply import ChangeSetApplyContext
from dnd_assistant.application.changeset_review import ChangeSetApproval
from dnd_assistant.application.changeset_store import load_approval
from dnd_assistant.application.vault_discovery import VaultDiscoveryReport
from dnd_assistant.composition.audit_context import now_utc
from dnd_assistant.composition.bootstrap import (
    canonical_candidates_from_report,
    compose_bootstrap_discovery,
)
from dnd_assistant.domain.changeset import ChangeSet
from dnd_assistant.errors import NotFoundError, StorageError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.bootstrap_evidence import ObsidianBootstrapEvidenceStore
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

__all__ = [
    "BootstrapApprovalRun",
    "BootstrapReviewRun",
    "BootstrapWorkflowContext",
    "compose_bootstrap_approval",
    "compose_bootstrap_apply",
    "compose_bootstrap_context",
    "compose_bootstrap_proposal",
    "compose_bootstrap_review",
    "compose_strict_repository",
]


@dataclass(frozen=True, slots=True)
class BootstrapWorkflowContext:
    """Concrete stores/audit wiring for the bootstrap review/apply workflow."""

    vault_root: Path
    changeset_store: ObsidianChangeSetStore
    evidence_store: ObsidianBootstrapEvidenceStore
    audit_service: AuditService


@dataclass(frozen=True, slots=True)
class BootstrapReviewRun:
    """Read-only review bundle plus strict apply-readiness diagnostics."""

    bundle: BootstrapReviewBundle
    readiness: BootstrapReadinessResult


@dataclass(frozen=True, slots=True)
class BootstrapApprovalRun:
    """Review bundle plus approval-readiness (no strict repository needed)."""

    bundle: BootstrapReviewBundle
    readiness: BootstrapReadinessResult


def compose_bootstrap_context(vault_root: Path) -> BootstrapWorkflowContext:
    """Build the concrete bootstrap workflow wiring for a Vault root."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    return BootstrapWorkflowContext(
        vault_root=vault_root,
        changeset_store=ObsidianChangeSetStore(vault_root),
        evidence_store=ObsidianBootstrapEvidenceStore(vault_root),
        audit_service=AuditService(str(audit_log_path)),
    )


def compose_strict_repository(vault_root: Path) -> ObsidianVaultRepository | None:
    """Construct the strict Vault repository, or ``None`` when it is unavailable.

    The strict repository is never weakened for bootstrap.  A missing/invalid
    audit topology or any other constructor failure yields ``None`` (the typed
    readiness gate reports ``STRICT_REPOSITORY_NOT_READY``); a mixed historical
    Vault that constructs but cannot build a clean snapshot is detected later by
    the read-only strict preflight.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    try:
        audit_service = AuditService(str(audit_log_path))
        return ObsidianVaultRepository(vault_root=str(vault_root), audit_service=audit_service)
    except StorageError:
        return None


def compose_bootstrap_proposal(vault_root: Path, changeset_id: str) -> ChangeSet:
    """Load a persisted bootstrap proposal (used by the reject path)."""
    context = compose_bootstrap_context(vault_root)
    bundle = load_bootstrap_bundle(context.changeset_store, context.evidence_store, changeset_id)
    return bundle.changeset


def _load_bundle(
    context: BootstrapWorkflowContext,
    changeset_id: str,
) -> tuple[
    BootstrapArtifactBundle,
    VaultDiscoveryReport,
    CanonicalStateSnapshot,
    CanonicalCoverage,
    BootstrapInputProjection,
]:
    """Load the artifact bundle and fresh discovery-derived projections."""
    bundle = load_bootstrap_bundle(context.changeset_store, context.evidence_store, changeset_id)
    report = compose_bootstrap_discovery(context.vault_root)
    candidates = canonical_candidates_from_report(report)
    snapshot = build_canonical_snapshot(candidates)
    coverage = assess_canonical_coverage(report)
    projection = prepare_bootstrap_input(report)
    return bundle, report, snapshot, coverage, projection


def compose_bootstrap_review(vault_root: Path, changeset_id: str) -> BootstrapReviewRun:
    """Build the read-only bootstrap review plus strict apply readiness."""
    context = compose_bootstrap_context(vault_root)
    bundle, report, snapshot, coverage, projection = _load_bundle(context, changeset_id)
    review = build_bootstrap_review(
        changeset=bundle.changeset,
        evidence_record=bundle.evidence_record,
        evidence_present=bundle.evidence_present,
        report=report,
        snapshot=snapshot,
        coverage=coverage,
    )
    readiness = assess_bootstrap_preconditions(
        bundle.changeset,
        evidence_record=bundle.evidence_record,
        evidence_present=bundle.evidence_present,
        projection=projection,
        coverage=coverage,
        snapshot=snapshot,
        strict_repository=compose_strict_repository(vault_root),
    )
    return BootstrapReviewRun(bundle=review, readiness=readiness)


def compose_bootstrap_approval(
    vault_root: Path,
    changeset_id: str,
    *,
    acknowledge_unresolved: bool,
) -> BootstrapApprovalRun:
    """Build the review bundle plus approval readiness (no strict repository)."""
    context = compose_bootstrap_context(vault_root)
    bundle, report, snapshot, coverage, projection = _load_bundle(context, changeset_id)
    review = build_bootstrap_review(
        changeset=bundle.changeset,
        evidence_record=bundle.evidence_record,
        evidence_present=bundle.evidence_present,
        report=report,
        snapshot=snapshot,
        coverage=coverage,
    )
    readiness = assess_bootstrap_approval_readiness(
        bundle.changeset,
        evidence_record=bundle.evidence_record,
        evidence_present=bundle.evidence_present,
        projection=projection,
        coverage=coverage,
        snapshot=snapshot,
        acknowledge_unresolved=acknowledge_unresolved,
    )
    return BootstrapApprovalRun(bundle=review, readiness=readiness)


def compose_bootstrap_apply(
    vault_root: Path,
    changeset_id: str,
    *,
    acknowledge_unresolved: bool,
) -> BootstrapApplyResult:
    """Run the full bootstrap apply pipeline for one proposal."""
    context = compose_bootstrap_context(vault_root)
    bundle, report, snapshot, coverage, projection = _load_bundle(context, changeset_id)

    try:
        approval: ChangeSetApproval | None = load_approval(context.changeset_store, changeset_id)
    except NotFoundError:
        approval = None

    strict_repository = compose_strict_repository(vault_root)
    audit_records = context.audit_service.read_all()
    apply_context = ChangeSetApplyContext(
        source=BOOTSTRAP_APPLY_SOURCE,
        real_time=now_utc(),
    )

    return apply_bootstrap_changeset(
        bundle.changeset,
        store=context.changeset_store,
        approval=approval,
        evidence_record=bundle.evidence_record,
        evidence_present=bundle.evidence_present,
        projection=projection,
        coverage=coverage,
        snapshot=snapshot,
        strict_repository=strict_repository,
        acknowledge_unresolved=acknowledge_unresolved,
        audit_records=audit_records,
        context=apply_context,
    )
