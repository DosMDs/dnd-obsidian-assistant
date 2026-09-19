"""S13-04 bootstrap evidence/source cross-validation and freshness.

Focused application module owning the structural validation of the persisted
S13-03 mapping evidence against the exact proposal and the fresh
``prepare_bootstrap_input`` projection, plus the semantic source-freshness rule.

This is deliberately stronger than "the sidecar parsed": it binds the exact
proposal id/fingerprint, the BOOTSTRAP provenance and session contract, the
campaign identity and one exact evidence record per operation.  The complete
evidence-source descriptor set is compared against the fresh S13-02-derived
projection only while the semantic input fingerprint still matches, so a
genuinely changed source is classified as staleness (and still fails closed)
rather than as evidence corruption.

Candidate/claim id *text* is treated as provenance metadata, not as apply
authority, so it is only checked for presence/absence and operation kind; every
applied operation must nevertheless cite at least one source reference.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, or a
    concrete storage implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.application.bootstrap_evidence import (
    BootstrapEvidenceRecord,
    EvidenceOperation,
)
from dnd_assistant.application.bootstrap_input import BootstrapInputProjection
from dnd_assistant.application.changeset_review import compute_changeset_fingerprint
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
)
from dnd_assistant.domain.types import Provenance

_CREATE_KIND = "create_entity"
_APPEND_KIND = "append_fact"


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
    MISSING_SOURCE_PROVENANCE = "missing_source_provenance"
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


# ── Evidence cross-validation ─────────────────────────────────────────────


def _evidence_source_index(
    record: BootstrapEvidenceRecord,
) -> list[BootstrapEvidenceIssue]:
    """Flag duplicate ``source_ref`` values across the evidence sources."""
    issues: list[BootstrapEvidenceIssue] = []
    seen: set[str] = set()
    for source in record.sources:
        if source.source_ref in seen:
            issues.append(
                BootstrapEvidenceIssue(
                    code=BootstrapEvidenceIssueCode.DUPLICATE_SOURCE_REF,
                    detail=f"Duplicate evidence source_ref {source.source_ref!r}",
                    source_ref=source.source_ref,
                )
            )
            continue
        seen.add(source.source_ref)
    return issues


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

        # Every applied operation must cite at least one evidence source.
        if not evidence.source_refs:
            issues.append(
                BootstrapEvidenceIssue(
                    code=BootstrapEvidenceIssueCode.MISSING_SOURCE_PROVENANCE,
                    detail=f"Operation {index} has no source reference",
                    operation_index=index,
                )
            )
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
    """Structurally cross-validate evidence against proposal and fresh projection."""
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
    issues.extend(_evidence_source_index(record))

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


__all__ = [
    "BootstrapEvidenceIssue",
    "BootstrapEvidenceIssueCode",
    "assess_source_freshness",
    "validate_bootstrap_evidence",
]
