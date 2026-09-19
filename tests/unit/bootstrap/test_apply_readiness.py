"""S13-04 bootstrap readiness gates (approval, preconditions, apply)."""

from __future__ import annotations

from datetime import UTC, datetime

from dnd_assistant.application.bootstrap_changeset import BootstrapMappingOutcome
from dnd_assistant.application.bootstrap_evidence import (
    BootstrapEvidenceRecord,
    EvidenceUnresolved,
    build_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_evidence_validation import assess_source_freshness
from dnd_assistant.application.bootstrap_input import prepare_bootstrap_input, source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.bootstrap_readiness import (
    BootstrapApplyReadiness,
    StrictRepositoryProbe,
    assess_bootstrap_apply_readiness,
    assess_bootstrap_approval_readiness,
    assess_bootstrap_preconditions,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.changeset import ChangeSet, CreateEntityOperation
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.storage.types import VaultDocument
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_report,
    make_source,
)

_CAMP = "camp-ready"
_NEW_REF = source_ref(_CAMP, "Notes/new.md")
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


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


def _approval(changeset: ChangeSet) -> ChangeSetApproval:
    return ChangeSetApproval(
        changeset_id=changeset.changeset_id,
        fingerprint=compute_changeset_fingerprint(changeset),
        decision=ReviewDecision.APPROVED,
        reviewer="dm",
    )


def _projection(run, *, new_text: str):
    return prepare_bootstrap_input(_report(new_text=new_text))


def _probe(repository) -> StrictRepositoryProbe:
    return StrictRepositoryProbe(repository=repository, issue=None)


class _ConflictRepo:
    """Read-only source exposing an entity id targeted by a create operation."""

    def __init__(self, entity_id: str, *, entity_type: EntityType) -> None:
        self._document = VaultDocument(
            entity=Entity(
                id=entity_id,
                type=entity_type,
                name="Занято",
                status="alive",
                visibility=Visibility.DM,
                knowledge_status=KnowledgeStatus.CONFIRMED,
                created_session=None,
                last_seen_session=None,
                tags=[],
                created_at=_NOW,
                updated_at=_NOW,
                revision=1,
            )
        )

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        return [self._document]


def test_fresh_proposal_is_source_fresh() -> None:
    run = _run()
    record = _record(run)
    assert assess_source_freshness(record, run.projection) is True


def test_changed_source_is_not_fresh() -> None:
    run = _run()
    record = _record(run)
    changed = _projection(run, new_text="ИЗМЕНЕНО")
    assert assess_source_freshness(record, changed) is False


def test_approval_readiness_ready_without_strict_repository() -> None:
    run = _run()
    record = _record(run)
    result = assess_bootstrap_approval_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.READY


def test_approval_readiness_missing_evidence() -> None:
    run = _run()
    result = assess_bootstrap_approval_readiness(
        _cs(run),
        evidence_record=None,
        evidence_present=False,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.MISSING_EVIDENCE


def test_approval_readiness_stale_source() -> None:
    run = _run()
    record = _record(run)
    result = assess_bootstrap_approval_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=_projection(run, new_text="ИЗМЕНЕНО"),
        coverage=run.coverage,
        snapshot=run.snapshot,
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.STALE_SOURCE


def test_approval_readiness_incomplete_coverage() -> None:
    from dnd_assistant.application.bootstrap_canonical import CanonicalCoverage

    run = _run()
    record = _record(run)
    result = assess_bootstrap_approval_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=CanonicalCoverage(complete=False),
        snapshot=run.snapshot,
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.INCOMPLETE_CANONICAL_COVERAGE


def test_approval_readiness_requires_unresolved_acknowledgement() -> None:
    run = _run()
    record = _record(run)
    ref = record.sources[0].source_ref
    record = record.model_copy(
        update={"unresolved": (EvidenceUnresolved(reason="x", detail="y", source_refs=(ref,)),)}
    )
    result = assess_bootstrap_approval_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        acknowledge_unresolved=False,
    )
    assert result.readiness is BootstrapApplyReadiness.UNRESOLVED_NOT_ACKNOWLEDGED


def test_preconditions_strict_not_ready_when_repository_absent() -> None:
    run = _run()
    record = _record(run)
    result = assess_bootstrap_preconditions(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=StrictRepositoryProbe(repository=None, issue=None),
    )
    assert result.readiness is BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY


def test_preconditions_ready_with_strict_repository() -> None:
    run = _run()
    record = _record(run)
    result = assess_bootstrap_preconditions(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(run.snapshot),
    )
    assert result.readiness is BootstrapApplyReadiness.READY


def test_preconditions_strict_preflight_failure() -> None:
    run = _run()
    record = _record(run)
    create = _cs(run).operations[0]
    assert isinstance(create, CreateEntityOperation)
    conflict = _ConflictRepo(create.entity_id, entity_type=create.type)
    result = assess_bootstrap_preconditions(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(conflict),
    )
    assert result.readiness is BootstrapApplyReadiness.CHANGESET_PREFLIGHT_FAILED


def test_apply_readiness_not_approved_without_approval() -> None:
    run = _run()
    record = _record(run)
    result = assess_bootstrap_apply_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(run.snapshot),
        approval=None,
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.NOT_APPROVED


def test_apply_readiness_ready_with_bound_approval() -> None:
    run = _run()
    record = _record(run)
    result = assess_bootstrap_apply_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(run.snapshot),
        approval=_approval(_cs(run)),
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.READY


def test_apply_readiness_rejected_approval_is_not_authority() -> None:
    run = _run()
    record = _record(run)
    rejected = ChangeSetApproval(
        changeset_id=_cs(run).changeset_id,
        fingerprint=compute_changeset_fingerprint(_cs(run)),
        decision=ReviewDecision.REJECTED,
        reviewer="dm",
    )
    result = assess_bootstrap_apply_readiness(
        _cs(run),
        evidence_record=record,
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(run.snapshot),
        approval=rejected,
        acknowledge_unresolved=True,
    )
    assert result.readiness is BootstrapApplyReadiness.NOT_APPROVED


def test_run_is_proposal() -> None:
    assert _run().result.outcome is BootstrapMappingOutcome.PROPOSAL
