"""S13-04 bootstrap review: artifact binding, evidence integrity and inspection.

Loads the persisted S13-03 bootstrap proposal and its immutable mapping-evidence
sidecar and produces a read-only human-review representation.  This module owns:

- fail-closed loading of the proposal + evidence pair;
- structural cross-validation of the evidence against the exact proposal and the
  fresh ``prepare_bootstrap_input`` projection;
- semantic source freshness (the exact ``input_fingerprint``);
- a bootstrap-specific inspection DTO and an optional real Stage-10
  ``ChangeSetReview`` that is produced **only** when the proposal is genuinely
  reviewable (fresh, evidence-valid, coverage-complete and projection-consistent).

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
    EvidenceOperation,
    EvidenceUnresolved,
    deserialize_bootstrap_evidence,
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
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
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

_CREATE_KIND = "create_entity"
_APPEND_KIND = "append_fact"


# ── Vocabulary ────────────────────────────────────────────────────────────


class BootstrapReviewState(StrEnum):
    """Human-review availability for one bootstrap proposal."""

    REVIEWABLE = "reviewable"
    """Evidence is valid, the campaign matches and the source is current."""

    STALE_SOURCE = "stale_source"
    """Evidence is valid but campaign source material changed since mapping."""

    NOT_REVIEWABLE = "not_reviewable"
    """Evidence is absent, malformed/inconsistent, or the proposal is not BOOTSTRAP."""


class BootstrapEvidenceIssueCode(StrEnum):
    """Stable, language-neutral codes for evidence cross-validation failures."""

    MISSING_EVIDENCE = "missing_evidence"
    CHANGESET_ID_MISMATCH = "changeset_id_mismatch"
    PROPOSAL_FINGERPRINT_MISMATCH = "proposal_fingerprint_mismatch"
    NOT_BOOTSTRAP_PROVENANCE = "not_bootstrap_provenance"
    SESSION_REF_PRESENT = "session_ref_present"
    WRONG_CAMPAIGN = "wrong_campaign"
    OPERATION_COUNT_MISMATCH = "operation_count_mismatch"
    OPERATION_INDEX_MISMATCH = "operation_index_mismatch"
    OPERATION_KIND_MISMATCH = "operation_kind_mismatch"
    UNSUPPORTED_OPERATION_KIND = "unsupported_operation_kind"
    MISSING_CANDIDATE_PROVENANCE = "missing_candidate_provenance"
    MISSING_CLAIM_PROVENANCE = "missing_claim_provenance"
    UNEXPECTED_CANDIDATE_PROVENANCE = "unexpected_candidate_provenance"
    UNEXPECTED_CLAIM_PROVENANCE = "unexpected_claim_provenance"
    UNKNOWN_SOURCE_REF = "unknown_source_ref"
    DUPLICATE_SOURCE_REF = "duplicate_source_ref"
    SOURCE_SET_MISMATCH = "source_set_mismatch"
    SOURCE_FIELD_MISMATCH = "source_field_mismatch"
    DUPLICATE_OPERATION_EVIDENCE = "duplicate_operation_evidence"


@dataclass(frozen=True, slots=True)
class BootstrapEvidenceIssue:
    """One evidence cross-validation problem, retaining linkage where known."""

    code: BootstrapEvidenceIssueCode
    detail: str
    operation_index: int | None = None
    source_ref: str | None = None


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


# ── Evidence cross-validation ─────────────────────────────────────────────


def _evidence_source_index(
    record: BootstrapEvidenceRecord,
) -> tuple[dict[str, object], list[BootstrapEvidenceIssue]]:
    """Index evidence sources by ``source_ref``, flagging duplicates."""
    index: dict[str, object] = {}
    issues: list[BootstrapEvidenceIssue] = []
    for source in record.sources:
        if source.source_ref in index:
            issues.append(
                BootstrapEvidenceIssue(
                    code=BootstrapEvidenceIssueCode.DUPLICATE_SOURCE_REF,
                    detail=f"Duplicate evidence source_ref {source.source_ref!r}",
                    source_ref=source.source_ref,
                )
            )
            continue
        index[source.source_ref] = source
    return index, issues


def _validate_source_descriptors(
    record: BootstrapEvidenceRecord,
    projection: BootstrapInputProjection,
    issues: list[BootstrapEvidenceIssue],
) -> None:
    """Cross-check evidence sources against the fresh projection, field by field."""
    projection_refs = [source.source_ref for source in projection.sources]
    if len(set(projection_refs)) != len(projection_refs):
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.DUPLICATE_SOURCE_REF,
                detail="Fresh bootstrap projection contains duplicate source_ref values",
            )
        )
    projection_by_ref = {source.source_ref: source for source in projection.sources}
    evidence_by_ref = {source.source_ref: source for source in record.sources}

    if set(evidence_by_ref) != set(projection_by_ref):
        missing = sorted(set(projection_by_ref) - set(evidence_by_ref))
        extra = sorted(set(evidence_by_ref) - set(projection_by_ref))
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.SOURCE_SET_MISMATCH,
                detail=(
                    "Evidence source set does not match the fresh projection "
                    f"(missing={missing}, extra={extra})"
                ),
            )
        )
        return

    for ref, evidence_source in evidence_by_ref.items():
        projected = projection_by_ref[ref]
        expected_skip = projected.skip_reason.value if projected.skip_reason else None
        mismatched = (
            evidence_source.relative_path != projected.relative_path
            or evidence_source.source_class != projected.source_class.value
            or evidence_source.size_bytes != projected.size_bytes
            or evidence_source.content_sha256 != projected.content_sha256
            or evidence_source.included != projected.included
            or evidence_source.skip_reason != expected_skip
        )
        if mismatched:
            issues.append(
                BootstrapEvidenceIssue(
                    code=BootstrapEvidenceIssueCode.SOURCE_FIELD_MISMATCH,
                    detail=f"Evidence source descriptor differs for source_ref {ref!r}",
                    source_ref=ref,
                )
            )


def _validate_operation_evidence(
    record: BootstrapEvidenceRecord,
    changeset: ChangeSet,
    known_source_refs: set[str],
    issues: list[BootstrapEvidenceIssue],
) -> None:
    """Validate operation provenance against the exact ChangeSet operations."""
    by_index: dict[int, EvidenceOperation] = {}
    for operation in record.operations:
        if operation.operation_index in by_index:
            issues.append(
                BootstrapEvidenceIssue(
                    code=BootstrapEvidenceIssueCode.DUPLICATE_OPERATION_EVIDENCE,
                    detail=(f"Duplicate operation evidence for index {operation.operation_index}"),
                    operation_index=operation.operation_index,
                )
            )
            continue
        by_index[operation.operation_index] = operation

    expected_count = len(changeset.operations)
    if len(by_index) != expected_count or set(by_index) != set(range(expected_count)):
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.OPERATION_COUNT_MISMATCH,
                detail=(
                    f"Evidence has {len(by_index)} operation record(s) for "
                    f"{expected_count} ChangeSet operation(s); indices must be exactly 0..N-1"
                ),
            )
        )
        return

    for index, change_operation in enumerate(changeset.operations):
        evidence = by_index[index]
        if isinstance(change_operation, CreateEntityOperation):
            if evidence.operation_kind != _CREATE_KIND:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.OPERATION_KIND_MISMATCH,
                        detail=(
                            f"Evidence kind {evidence.operation_kind!r} does not match "
                            f"create operation at index {index}"
                        ),
                        operation_index=index,
                    )
                )
            if not evidence.candidate_ids:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.MISSING_CANDIDATE_PROVENANCE,
                        detail=f"Create operation {index} has no candidate provenance",
                        operation_index=index,
                    )
                )
            if evidence.claim_ids:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.UNEXPECTED_CLAIM_PROVENANCE,
                        detail=f"Create operation {index} must not carry claim provenance",
                        operation_index=index,
                    )
                )
        elif isinstance(change_operation, AppendFactOperation):
            if evidence.operation_kind != _APPEND_KIND:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.OPERATION_KIND_MISMATCH,
                        detail=(
                            f"Evidence kind {evidence.operation_kind!r} does not match "
                            f"append operation at index {index}"
                        ),
                        operation_index=index,
                    )
                )
            if not evidence.claim_ids:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.MISSING_CLAIM_PROVENANCE,
                        detail=f"Append operation {index} has no claim provenance",
                        operation_index=index,
                    )
                )
            if evidence.candidate_ids:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.UNEXPECTED_CANDIDATE_PROVENANCE,
                        detail=f"Append operation {index} must not carry candidate provenance",
                        operation_index=index,
                    )
                )
        else:
            issues.append(
                BootstrapEvidenceIssue(
                    code=BootstrapEvidenceIssueCode.UNSUPPORTED_OPERATION_KIND,
                    detail=(
                        f"Operation kind {change_operation.kind!r} at index {index} is not "
                        "supported by the bootstrap workflow"
                    ),
                    operation_index=index,
                )
            )
            continue

        for ref in evidence.source_refs:
            if ref not in known_source_refs:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.UNKNOWN_SOURCE_REF,
                        detail=(f"Operation {index} references unknown source_ref {ref!r}"),
                        operation_index=index,
                        source_ref=ref,
                    )
                )


def validate_bootstrap_evidence(
    record: BootstrapEvidenceRecord,
    changeset: ChangeSet,
    projection: BootstrapInputProjection,
) -> tuple[BootstrapEvidenceIssue, ...]:
    """Structurally cross-validate evidence against proposal and fresh projection.

    This is deliberately stronger than "the sidecar parsed": it binds the exact
    proposal id/fingerprint, the BOOTSTRAP provenance and session contract, the
    campaign identity and one exact evidence record per operation.  The complete
    evidence-source descriptor set is compared against the fresh S13-02-derived
    projection only while the semantic input fingerprint still matches, so a
    genuinely changed source is classified as staleness (and still fails closed)
    rather than as evidence corruption.

    Candidate/claim id *text* is treated as provenance metadata, not as apply
    authority, so it is only checked for presence/absence and operation kind.
    """
    issues: list[BootstrapEvidenceIssue] = []

    if changeset.provenance.provenance is not Provenance.BOOTSTRAP:
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.NOT_BOOTSTRAP_PROVENANCE,
                detail="Proposal provenance is not bootstrap",
            )
        )
    if changeset.session_ref is not None:
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.SESSION_REF_PRESENT,
                detail="Bootstrap proposal must not carry a session reference",
            )
        )
    if record.changeset_id != changeset.changeset_id:
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.CHANGESET_ID_MISMATCH,
                detail=(
                    f"Evidence changeset_id {record.changeset_id!r} does not match "
                    f"the proposal {changeset.changeset_id!r}"
                ),
            )
        )
    if record.proposal_fingerprint.digest != compute_changeset_fingerprint(changeset).digest:
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.PROPOSAL_FINGERPRINT_MISMATCH,
                detail="Evidence proposal fingerprint does not match the proposal content",
            )
        )
    if record.campaign_id != projection.campaign_id:
        issues.append(
            BootstrapEvidenceIssue(
                code=BootstrapEvidenceIssueCode.WRONG_CAMPAIGN,
                detail=(
                    f"Evidence campaign_id {record.campaign_id!r} does not match the "
                    f"current Vault campaign {projection.campaign_id!r}"
                ),
            )
        )

    # Duplicate source_ref values are malformed evidence regardless of freshness.
    _, source_issues = _evidence_source_index(record)
    issues.extend(source_issues)

    # The semantic input fingerprint is derived exactly from the descriptor
    # fields compared below.  When it still matches the fresh projection, any
    # descriptor disagreement is genuine evidence tampering.  When it does not
    # match, the campaign source material changed (staleness) and is reported
    # separately by ``assess_source_freshness`` rather than as evidence
    # corruption; approval/apply fail closed on staleness either way.
    if record.input_fingerprint.digest == projection.input_fingerprint.digest:
        _validate_source_descriptors(record, projection, issues)

    known_source_refs = {source.source_ref for source in record.sources}
    _validate_operation_evidence(record, changeset, known_source_refs, issues)

    for unresolved in record.unresolved:
        for ref in unresolved.source_refs:
            if ref not in known_source_refs:
                issues.append(
                    BootstrapEvidenceIssue(
                        code=BootstrapEvidenceIssueCode.UNKNOWN_SOURCE_REF,
                        detail=f"Unresolved diagnostic references unknown source_ref {ref!r}",
                        source_ref=ref,
                    )
                )

    return tuple(issues)


def assess_source_freshness(
    record: BootstrapEvidenceRecord,
    projection: BootstrapInputProjection,
) -> bool:
    """Return whether current semantic source material matches the evidence."""
    return record.input_fingerprint.digest == projection.input_fingerprint.digest


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
