"""S13-04 bootstrap review: evidence binding, review states and preview bounds."""

from __future__ import annotations

from dnd_assistant.application.bootstrap_canonical import (
    CanonicalCoverage,
    build_canonical_snapshot,
)
from dnd_assistant.application.bootstrap_changeset import BootstrapMappingOutcome
from dnd_assistant.application.bootstrap_evidence import (
    BootstrapEvidenceRecord,
    EvidenceOperation,
    EvidenceSource,
    EvidenceUnresolved,
    build_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.bootstrap_review import (
    MAX_SOURCE_PREVIEW_CHARS,
    MAX_SOURCE_PREVIEW_TOTAL_CHARS,
    MAX_SOURCE_PREVIEWS,
    BootstrapEvidenceIssueCode,
    BootstrapReviewState,
    build_bootstrap_review,
    validate_bootstrap_evidence,
)
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    EntityFieldUpdate,
    ProposalProvenance,
    UpdateEntityOperation,
)
from dnd_assistant.domain.types import (
    EntityType,
    Provenance,
    Sha256Fingerprint,
)
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_report,
    make_source,
)

_CAMP = "camp-review"
_NEW_REF = source_ref(_CAMP, "Notes/new.md")
_EXISTING_REF = source_ref(_CAMP, "Characters/NPCs/varos.md")
_UNKNOWN_REF = "src_" + "0" * 32

_CODES = BootstrapEvidenceIssueCode


def _report(*, new_text: str = "новый персонаж"):
    return make_report(
        _CAMP,
        [
            make_source(
                "Characters/NPCs/varos.md",
                SourceClass.ENTITY_CANDIDATE,
                canonical_text("npc-1", EntityType.NPC, "Варос"),
            ),
            make_source("Notes/new.md", SourceClass.USER_SOURCE, new_text),
        ],
    )


def _run(*, new_text: str = "новый персонаж"):
    report = _report(new_text=new_text)
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый Герой", EntityType.NPC, [_NEW_REF]),),
    )
    return run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(extraction)
    )


def _record(run) -> BootstrapEvidenceRecord:
    return build_bootstrap_evidence(
        run.projection,
        run.result,
        producer_version=run.processor_version,
        prompt_version=run.prompt_version,
        extraction_schema_version=run.extraction_schema_version,
        model_profile="heavy",
        model="m",
        provider="ollama",
    )


def _cs(run) -> ChangeSet:
    changeset = run.result.changeset
    assert changeset is not None
    return changeset


def _codes(record: BootstrapEvidenceRecord, changeset: ChangeSet, projection):
    return {issue.code for issue in validate_bootstrap_evidence(record, changeset, projection)}


# ── Evidence binding ──────────────────────────────────────────────────────


def test_valid_evidence_has_no_issues() -> None:
    run = _run()
    record = _record(run)
    assert run.result.outcome is BootstrapMappingOutcome.PROPOSAL
    assert validate_bootstrap_evidence(record, _cs(run), run.projection) == ()


def test_changeset_id_mismatch() -> None:
    run = _run()
    record = _record(run).model_copy(update={"changeset_id": "cs_other"})
    assert _CODES.CHANGESET_ID_MISMATCH in _codes(record, _cs(run), run.projection)


def test_proposal_fingerprint_mismatch() -> None:
    run = _run()
    record = _record(run).model_copy(
        update={"proposal_fingerprint": Sha256Fingerprint(digest="0" * 64)}
    )
    assert _CODES.PROPOSAL_FINGERPRINT_MISMATCH in _codes(record, _cs(run), run.projection)


def test_wrong_campaign() -> None:
    run = _run()
    record = _record(run).model_copy(update={"campaign_id": "other-camp"})
    assert _CODES.WRONG_CAMPAIGN in _codes(record, _cs(run), run.projection)


def test_not_bootstrap_provenance() -> None:
    run = _run()
    record = _record(run)
    changeset = _cs(run)
    other = ChangeSet(
        changeset_id=changeset.changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        session_ref=None,
        operations=changeset.operations,
    )
    assert _CODES.NOT_BOOTSTRAP_PROVENANCE in _codes(record, other, run.projection)


def test_session_ref_present() -> None:
    run = _run()
    record = _record(run)
    changeset = _cs(run)
    other = ChangeSet(
        changeset_id=changeset.changeset_id,
        provenance=changeset.provenance,
        session_ref="S001",
        operations=changeset.operations,
    )
    assert _CODES.SESSION_REF_PRESENT in _codes(record, other, run.projection)


def test_duplicate_evidence_source_ref() -> None:
    run = _run()
    record = _record(run)
    duplicated = record.model_copy(update={"sources": (*record.sources, record.sources[0])})
    assert _CODES.DUPLICATE_SOURCE_REF in _codes(duplicated, _cs(run), run.projection)


def test_source_set_mismatch() -> None:
    run = _run()
    record = _record(run)
    shortened = record.model_copy(update={"sources": record.sources[:1]})
    assert _CODES.SOURCE_SET_MISMATCH in _codes(shortened, _cs(run), run.projection)


def test_source_field_mismatch() -> None:
    run = _run()
    record = _record(run)
    first = record.sources[0]
    tampered = first.model_copy(update={"relative_path": "Characters/NPCs/tampered.md"})
    changed = record.model_copy(update={"sources": (tampered, *record.sources[1:])})
    assert _CODES.SOURCE_FIELD_MISMATCH in _codes(changed, _cs(run), run.projection)


def test_operation_count_mismatch() -> None:
    run = _run()
    record = _record(run)
    shortened = record.model_copy(update={"operations": ()})
    assert _CODES.OPERATION_COUNT_MISMATCH in _codes(shortened, _cs(run), run.projection)


def test_duplicate_operation_evidence() -> None:
    run = _run()
    record = _record(run)
    dup = record.model_copy(update={"operations": (*record.operations, record.operations[0])})
    assert _CODES.DUPLICATE_OPERATION_EVIDENCE in _codes(dup, _cs(run), run.projection)


def test_operation_kind_mismatch() -> None:
    run = _run()
    record = _record(run)
    first = record.operations[0]
    changed = record.model_copy(
        update={
            "operations": (
                first.model_copy(update={"operation_kind": "append_fact"}),
                *record.operations[1:],
            )
        }
    )
    assert _CODES.OPERATION_KIND_MISMATCH in _codes(changed, _cs(run), run.projection)


def test_create_missing_candidate_provenance() -> None:
    run = _run()
    record = _record(run)
    first = record.operations[0]
    changed = record.model_copy(
        update={"operations": (first.model_copy(update={"candidate_ids": ()}),)}
    )
    assert _CODES.MISSING_CANDIDATE_PROVENANCE in _codes(changed, _cs(run), run.projection)


def test_append_missing_claim_provenance() -> None:
    source = EvidenceSource(
        source_ref=_EXISTING_REF,
        relative_path="Characters/NPCs/varos.md",
        source_class=SourceClass.ENTITY_CANDIDATE.value,
        size_bytes=1,
        content_sha256="a" * 64,
        included=True,
    )
    changeset = ChangeSet(
        changeset_id="cs_bootstrap_manual",
        provenance=ProposalProvenance(provenance=Provenance.BOOTSTRAP),
        session_ref=None,
        operations=(AppendFactOperation(entity_id="npc-1", expected_revision=1, fact="факт"),),
    )
    record = BootstrapEvidenceRecord(
        producer_version="v",
        campaign_id=_CAMP,
        changeset_id="cs_bootstrap_manual",
        proposal_fingerprint=Sha256Fingerprint(digest="b" * 64),
        input_fingerprint=Sha256Fingerprint(digest="c" * 64),
        prompt_version="p",
        extraction_schema_version=1,
        sources=(source,),
        operations=(
            EvidenceOperation(operation_index=0, operation_kind="append_fact", claim_ids=()),
        ),
    )
    run = _run()
    assert _CODES.MISSING_CLAIM_PROVENANCE in _codes(record, changeset, run.projection)


def test_unknown_operation_source_ref() -> None:
    run = _run()
    record = _record(run)
    first = record.operations[0]
    changed = record.model_copy(
        update={
            "operations": (
                first.model_copy(update={"source_refs": (*first.source_refs, _UNKNOWN_REF)}),
                *record.operations[1:],
            )
        }
    )
    assert _CODES.UNKNOWN_SOURCE_REF in _codes(changed, _cs(run), run.projection)


def test_unknown_unresolved_source_ref() -> None:
    run = _run()
    record = _record(run)
    extra = EvidenceUnresolved(reason="source_skipped", detail="d", source_refs=(_UNKNOWN_REF,))
    changed = record.model_copy(update={"unresolved": (*record.unresolved, extra)})
    assert _CODES.UNKNOWN_SOURCE_REF in _codes(changed, _cs(run), run.projection)


def test_update_entity_operation_rejected() -> None:
    run = _run()
    changeset = ChangeSet(
        changeset_id="cs_bootstrap_update",
        provenance=ProposalProvenance(provenance=Provenance.BOOTSTRAP),
        session_ref=None,
        operations=(
            UpdateEntityOperation(
                entity_id="npc-1",
                expected_revision=1,
                update=EntityFieldUpdate(name="X"),
            ),
        ),
    )
    record = BootstrapEvidenceRecord(
        producer_version="v",
        campaign_id=_CAMP,
        changeset_id="cs_bootstrap_update",
        proposal_fingerprint=Sha256Fingerprint(digest="b" * 64),
        input_fingerprint=Sha256Fingerprint(digest="c" * 64),
        prompt_version="p",
        extraction_schema_version=1,
        sources=(),
        operations=(EvidenceOperation(operation_index=0, operation_kind="update_entity"),),
    )
    assert _CODES.UNSUPPORTED_OPERATION_KIND in _codes(record, changeset, run.projection)


# ── Freshness / review state ──────────────────────────────────────────────


def test_fresh_review_is_reviewable_with_real_review() -> None:
    run = _run()
    record = _record(run)
    report = _report()
    snapshot = build_canonical_snapshot(canonical_candidates_from_report(report))
    bundle = build_bootstrap_review(
        changeset=_cs(run),
        evidence_record=record,
        evidence_present=True,
        report=report,
        snapshot=snapshot,
        coverage=run.coverage,
    )
    assert bundle.review_state is BootstrapReviewState.REVIEWABLE
    assert bundle.changeset_review is not None
    assert bundle.changeset_review.items


def test_stale_source_has_no_changeset_review_and_no_content() -> None:
    run = _run()
    record = _record(run)
    report = _report(new_text="ИЗМЕНЕНО")
    snapshot = build_canonical_snapshot(canonical_candidates_from_report(report))
    bundle = build_bootstrap_review(
        changeset=_cs(run),
        evidence_record=record,
        evidence_present=True,
        report=report,
        snapshot=snapshot,
        coverage=run.coverage,
    )
    assert bundle.review_state is BootstrapReviewState.STALE_SOURCE
    assert bundle.changeset_review is None
    assert all(view.content_text is None for view in bundle.sources)
    assert bundle.sources


def test_missing_evidence_is_not_reviewable() -> None:
    run = _run()
    report = _report()
    snapshot = build_canonical_snapshot(canonical_candidates_from_report(report))
    bundle = build_bootstrap_review(
        changeset=_cs(run),
        evidence_record=None,
        evidence_present=False,
        report=report,
        snapshot=snapshot,
        coverage=run.coverage,
    )
    assert bundle.review_state is BootstrapReviewState.NOT_REVIEWABLE
    assert bundle.changeset_review is None
    assert {issue.code for issue in bundle.evidence_issues} == {_CODES.MISSING_EVIDENCE}


def test_incomplete_coverage_blocks_changeset_review() -> None:
    run = _run()
    record = _record(run)
    report = _report()
    snapshot = build_canonical_snapshot(canonical_candidates_from_report(report))
    coverage = CanonicalCoverage(complete=False)
    bundle = build_bootstrap_review(
        changeset=_cs(run),
        evidence_record=record,
        evidence_present=True,
        report=report,
        snapshot=snapshot,
        coverage=coverage,
    )
    assert bundle.review_state is BootstrapReviewState.REVIEWABLE
    assert bundle.changeset_review is None


# ── Preview bounds ────────────────────────────────────────────────────────


def test_preview_bounds_applied() -> None:
    sources = [
        make_source(
            f"Notes/source-{index:02d}.md",
            SourceClass.USER_SOURCE,
            "x" * (MAX_SOURCE_PREVIEW_CHARS * 2),
        )
        for index in range(MAX_SOURCE_PREVIEWS + 5)
    ]
    report = make_report(_CAMP, sources)
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(
            make_candidate(
                "c1", "Новый Герой", EntityType.NPC, [source_ref(_CAMP, "Notes/source-00.md")]
            ),
        ),
    )
    run = run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(extraction)
    )
    record = _record(run)
    bundle = build_bootstrap_review(
        changeset=_cs(run),
        evidence_record=record,
        evidence_present=True,
        report=report,
        snapshot=run.snapshot,
        coverage=run.coverage,
    )
    previews = [view for view in bundle.sources if view.content_text is not None]
    assert 0 < len(previews) <= MAX_SOURCE_PREVIEWS
    assert all(len(view.content_text or "") <= MAX_SOURCE_PREVIEW_CHARS for view in previews)
    assert sum(len(view.content_text or "") for view in previews) <= MAX_SOURCE_PREVIEW_TOTAL_CHARS
