"""S13-04 bootstrap review: artifact binding, review DTOs and inspection.

Loads the persisted S13-03 bootstrap proposal and its immutable mapping-evidence
sidecar and produces a read-only human-review representation.  This module owns:

- fail-closed loading of the proposal + evidence pair;
- the bootstrap-specific inspection DTO and bounded source review views;
- an optional real Stage-10 ``ChangeSetReview`` that is produced **only** when
  the proposal is genuinely reviewable (fresh, evidence-valid, coverage-complete
  and projection-consistent).

Evidence/source cross-validation and semantic source freshness are owned by
``application.bootstrap_evidence_validation``.

A ``ChangeSetReview`` is never fabricated for a stale/invalid/not-reviewable
proposal: bootstrap inspection is a separate, weaker representation that carries
no approval authority.

No model, filesystem, storage implementation or apply authority is involved.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, a concrete
    storage implementation (only protocols under ``TYPE_CHECKING``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.bootstrap_canonical import (
    CanonicalCoverage,
    CanonicalStateSnapshot,
)
from dnd_assistant.application.bootstrap_evidence import (
    BootstrapEvidenceRecord,
    EvidenceUnresolved,
    deserialize_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_evidence_validation import (
    BootstrapEvidenceIssue,
    BootstrapEvidenceIssueCode,
    assess_source_freshness,
    validate_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_input import (
    BootstrapInputProjection,
    prepare_bootstrap_input,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetFingerprint,
    ChangeSetReview,
    build_changeset_review,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import load_proposal
from dnd_assistant.application.changeset_validation import (
    ChangeSetValidationResult,
    validate_changeset,
)
from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    VaultDiscoveryReport,
)
from dnd_assistant.domain.changeset import (
    ChangeSet,
    ProposalProvenance,
)
from dnd_assistant.domain.types import Provenance

if TYPE_CHECKING:
    from dnd_assistant.storage.bootstrap_evidence import BootstrapEvidenceStore
    from dnd_assistant.storage.changeset_store import ChangeSetStore

# ── Preview bounds ────────────────────────────────────────────────────────

MAX_SOURCE_PREVIEWS: int = 10
"""Maximum number of evidence-linked sources whose content is previewed."""

MAX_SOURCE_PREVIEW_CHARS: int = 2_000
"""Maximum characters rendered per source content preview."""

MAX_SOURCE_PREVIEW_TOTAL_CHARS: int = 12_000
"""Maximum aggregate characters across all source content previews."""


# ── Vocabulary ────────────────────────────────────────────────────────────


class BootstrapReviewState(StrEnum):
    """Human-review availability for one bootstrap proposal."""

    REVIEWABLE = "reviewable"
    """Evidence is valid, the campaign matches and the source is current."""

    STALE_SOURCE = "stale_source"
    """Evidence is valid but campaign source material changed since mapping."""

    NOT_REVIEWABLE = "not_reviewable"
    """Evidence is absent, malformed/inconsistent, or the proposal is not BOOTSTRAP."""


@dataclass(frozen=True, slots=True)
class BootstrapProposalInspection:
    """Read-only proposal view that never implies ChangeSetReview validity."""

    changeset_id: str
    fingerprint: ChangeSetFingerprint
    provenance: ProposalProvenance
    operation_count: int
    operation_kinds: tuple[str, ...]
    entity_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BootstrapSourceView:
    """Review descriptor for one evidence-linked bootstrap source.

    ``content_text`` is populated only for a genuinely reviewable proposal from
    the fresh bounded S13-02 report; it is ``None`` for stale/not-reviewable
    states so stale content is never rendered as if it were the reviewed
    evidence.
    """

    source_ref: str
    relative_path: str
    source_class: str
    content_sha256: str | None
    included: bool
    content_text: str | None


@dataclass(frozen=True, slots=True)
class BootstrapArtifactBundle:
    """Loaded proposal + optional evidence sidecar."""

    changeset: ChangeSet
    evidence_record: BootstrapEvidenceRecord | None
    evidence_present: bool


@dataclass(frozen=True, slots=True)
class BootstrapReviewBundle:
    """Complete read-only bootstrap review representation."""

    changeset_id: str
    changeset: ChangeSet
    fingerprint: ChangeSetFingerprint
    provenance: ProposalProvenance
    review_state: BootstrapReviewState
    evidence_issues: tuple[BootstrapEvidenceIssue, ...]
    proposal_inspection: BootstrapProposalInspection
    changeset_review: ChangeSetReview | None
    evidence_record: BootstrapEvidenceRecord | None
    sources: tuple[BootstrapSourceView, ...]
    unresolved: tuple[EvidenceUnresolved, ...]
    coverage: CanonicalCoverage
    projection: BootstrapInputProjection
    snapshot: CanonicalStateSnapshot
    proposal_consistency: ChangeSetValidationResult | None


# ── Loading ───────────────────────────────────────────────────────────────


def load_bootstrap_bundle(
    store: ChangeSetStore,
    evidence_store: BootstrapEvidenceStore,
    changeset_id: str,
) -> BootstrapArtifactBundle:
    """Load the persisted proposal and its optional evidence sidecar.

    The evidence sidecar is deliberately optional here (S13-03 allows proposal
    persistence to succeed while evidence persistence fails); the *review/
    approval/apply* gates treat a missing sidecar as fail-closed.  Malformed
    persisted evidence raises ``StorageError``.

    Raises:
        NotFoundError: No proposal artifact exists.
        StorageError: The proposal or evidence artifact is malformed/unreadable.
    """
    changeset = load_proposal(store, changeset_id)
    text = evidence_store.read_evidence_if_present(changeset_id)
    if text is None:
        return BootstrapArtifactBundle(
            changeset=changeset,
            evidence_record=None,
            evidence_present=False,
        )
    return BootstrapArtifactBundle(
        changeset=changeset,
        evidence_record=deserialize_bootstrap_evidence(text),
        evidence_present=True,
    )


# ── Review construction ───────────────────────────────────────────────────


def _build_proposal_inspection(changeset: ChangeSet) -> BootstrapProposalInspection:
    return BootstrapProposalInspection(
        changeset_id=changeset.changeset_id,
        fingerprint=compute_changeset_fingerprint(changeset),
        provenance=changeset.provenance,
        operation_count=len(changeset.operations),
        operation_kinds=tuple(operation.kind for operation in changeset.operations),
        entity_ids=tuple(operation.entity_id for operation in changeset.operations),
    )


def _build_source_view(
    record: BootstrapEvidenceRecord,
    report: VaultDiscoveryReport,
    *,
    allow_content: bool,
) -> tuple[BootstrapSourceView, ...]:
    """Build bounded review descriptors, previewing content only when fresh."""
    content_by_path = {
        entry.relative_path: entry.content_text
        for entry in report.entries
        if entry.content_status is ContentReadStatus.READ and entry.content_text is not None
    }

    views: list[BootstrapSourceView] = []
    previews = 0
    aggregate = 0
    for source in record.sources:
        content_text: str | None = None
        if allow_content and source.included and previews < MAX_SOURCE_PREVIEWS:
            raw = content_by_path.get(source.relative_path)
            if raw is not None:
                remaining = MAX_SOURCE_PREVIEW_TOTAL_CHARS - aggregate
                budget = min(MAX_SOURCE_PREVIEW_CHARS, remaining)
                if budget > 0:
                    content_text = raw[:budget]
                    aggregate += len(content_text)
                    previews += 1
        views.append(
            BootstrapSourceView(
                source_ref=source.source_ref,
                relative_path=source.relative_path,
                source_class=source.source_class,
                content_sha256=source.content_sha256,
                included=source.included,
                content_text=content_text,
            )
        )
    return tuple(views)


def build_bootstrap_review(
    *,
    changeset: ChangeSet,
    evidence_record: BootstrapEvidenceRecord | None,
    evidence_present: bool,
    report: VaultDiscoveryReport,
    snapshot: CanonicalStateSnapshot,
    coverage: CanonicalCoverage,
) -> BootstrapReviewBundle:
    """Assemble a read-only bootstrap review without any apply authority.

    A real Stage-10 ``ChangeSetReview`` is produced only when the proposal is
    reviewable, canonical coverage is complete and the read-only projection
    preflight passes.  Otherwise ``changeset_review`` is ``None`` and only the
    weaker :class:`BootstrapProposalInspection` is available.
    """
    projection = prepare_bootstrap_input(report)
    inspection = _build_proposal_inspection(changeset)

    if changeset.provenance.provenance is not Provenance.BOOTSTRAP:
        state = BootstrapReviewState.NOT_REVIEWABLE
        issues: tuple[BootstrapEvidenceIssue, ...] = (
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.NOT_BOOTSTRAP_PROVENANCE,
                detail="Proposal provenance is not bootstrap",
            ),
        )
    elif not evidence_present or evidence_record is None:
        state = BootstrapReviewState.NOT_REVIEWABLE
        issues = (
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.MISSING_EVIDENCE,
                detail="Bootstrap mapping evidence is absent for this proposal",
            ),
        )
    else:
        issues = validate_bootstrap_evidence(evidence_record, changeset, projection)
        if issues:
            state = BootstrapReviewState.NOT_REVIEWABLE
        elif not assess_source_freshness(evidence_record, projection):
            state = BootstrapReviewState.STALE_SOURCE
        else:
            state = BootstrapReviewState.REVIEWABLE

    proposal_consistency: ChangeSetValidationResult | None = None
    if coverage.complete:
        proposal_consistency = validate_changeset(changeset, snapshot)

    changeset_review: ChangeSetReview | None = None
    if (
        state is BootstrapReviewState.REVIEWABLE
        and coverage.complete
        and proposal_consistency is not None
        and proposal_consistency.valid
    ):
        changeset_review = build_changeset_review(changeset, snapshot)

    sources = (
        _build_source_view(
            evidence_record,
            report,
            allow_content=state is BootstrapReviewState.REVIEWABLE,
        )
        if evidence_record is not None
        else ()
    )
    unresolved = evidence_record.unresolved if evidence_record is not None else ()

    return BootstrapReviewBundle(
        changeset_id=changeset.changeset_id,
        changeset=changeset,
        fingerprint=inspection.fingerprint,
        provenance=changeset.provenance,
        review_state=state,
        evidence_issues=issues,
        proposal_inspection=inspection,
        changeset_review=changeset_review,
        evidence_record=evidence_record,
        sources=sources,
        unresolved=unresolved,
        coverage=coverage,
        projection=projection,
        snapshot=snapshot,
        proposal_consistency=proposal_consistency,
    )


__all__ = [
    "MAX_SOURCE_PREVIEWS",
    "MAX_SOURCE_PREVIEW_CHARS",
    "MAX_SOURCE_PREVIEW_TOTAL_CHARS",
    "BootstrapArtifactBundle",
    "BootstrapEvidenceIssue",
    "BootstrapEvidenceIssueCode",
    "BootstrapProposalInspection",
    "BootstrapReviewBundle",
    "BootstrapReviewState",
    "BootstrapSourceView",
    "assess_source_freshness",
    "build_bootstrap_review",
    "load_bootstrap_bundle",
    "validate_bootstrap_evidence",
]
