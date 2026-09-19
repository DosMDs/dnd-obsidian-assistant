"""S13-04 bootstrap apply orchestrator tests (real ``apply_bootstrap_changeset``)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.bootstrap_apply import (
    BOOTSTRAP_APPLY_SOURCE,
    BootstrapApplyResult,
    apply_bootstrap_changeset,
)
from dnd_assistant.application.bootstrap_evidence import build_bootstrap_evidence
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.bootstrap_readiness import (
    BootstrapApplyReadiness,
    StrictRepositoryProbe,
)
from dnd_assistant.application.changeset_apply import (
    ChangeSetApplyContext,
    ChangeSetApplyOutcome,
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
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Visibility,
)
from dnd_assistant.errors import ConflictError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditRecord
from dnd_assistant.storage.types import VaultDocument
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_claim,
    make_reference,
    make_report,
    make_source,
)

_CAMP = "camp-apply"
_NEW_REF = source_ref(_CAMP, "Notes/new.md")
_VAROS_REF = source_ref(_CAMP, "Characters/NPCs/varos.md")
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


# ── Report / evidence builders ────────────────────────────────────────────


def _report(*, with_append: bool):
    sources = [
        make_source(
            "Characters/NPCs/varos.md",
            SourceClass.ENTITY_CANDIDATE,
            canonical_text("npc-1", EntityType.NPC, "Варос"),
        ),
        make_source("Notes/new.md", SourceClass.USER_SOURCE, "новый персонаж"),
    ]
    return make_report(_CAMP, sources)


def _extraction(*, with_append: bool) -> BootstrapExtraction:
    claims = ()
    if with_append:
        claims = (
            make_claim(
                "cl1",
                "Варос — союзник партии.",
                [_VAROS_REF],
                references=(make_reference("r1", "Варос", EntityType.NPC, [_VAROS_REF]),),
            ),
        )
    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый Герой", EntityType.NPC, [_NEW_REF]),),
        claims=claims,
    )


def _run(*, with_append: bool):
    report = _report(with_append=with_append)
    return run_bootstrap_mapping(
        report,
        canonical_candidates_from_report(report),
        FakeBootstrapModel(_extraction(with_append=with_append)),
    )


def _record(run):
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


def _changeset(run) -> ChangeSet:
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


def _context() -> ChangeSetApplyContext:
    return ChangeSetApplyContext(source=BOOTSTRAP_APPLY_SOURCE, real_time=_NOW)


# ── Fakes ─────────────────────────────────────────────────────────────────


class FakeStore:
    """Minimal in-memory ChangeSetStore for the apply-attempt ledger."""

    def __init__(self, *, fail_append: bool = False) -> None:
        self._attempts: dict[str, str] = {}
        self.fail_append = fail_append

    def append_apply_attempt(self, changeset_id: str, content: str) -> None:
        if self.fail_append:
            raise StorageError("apply-attempt append failed")
        self._attempts[changeset_id] = self._attempts.get(changeset_id, "") + content

    def read_apply_attempts_if_present(self, changeset_id: str) -> str | None:
        return self._attempts.get(changeset_id)

    # Unused protocol members (kept so the fake satisfies ``ChangeSetStore``).
    def create_proposal(self, changeset_id: str, content: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def read_proposal(self, changeset_id: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def read_proposal_if_present(self, changeset_id: str) -> str | None:  # pragma: no cover
        raise NotImplementedError

    def create_approval(self, changeset_id: str, content: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def read_approval(self, changeset_id: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def read_approval_if_present(self, changeset_id: str) -> str | None:  # pragma: no cover
        raise NotImplementedError


class FakeRepository:
    """Duck-typed repository exercising the Stage-10 applier mutation path."""

    def __init__(
        self,
        documents: list[VaultDocument] | None = None,
        *,
        fail_append: bool = False,
    ) -> None:
        self.documents = list(documents or [])
        self.fail_append = fail_append
        self.list_calls = 0
        self.conflict_on_second_list: VaultDocument | None = None
        self.created: list[str] = []
        self.appended: list[tuple[str, str]] = []

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        self.list_calls += 1
        if self.conflict_on_second_list is not None and self.list_calls >= 2:
            return [*self.documents, self.conflict_on_second_list]
        return list(self.documents)

    def create_entity(self, document: VaultDocument, *, audit: object) -> VaultDocument:
        self.created.append(document.entity.id)
        self.documents.append(document)
        return document

    def patch_entity(
        self,
        entity_id: str,
        patch: object,
        *,
        expected_revision: int,
        audit: object,
    ) -> VaultDocument:  # pragma: no cover - bootstrap never patches
        raise NotImplementedError

    def append_entity_fact(
        self,
        entity_id: str,
        *,
        expected_revision: int,
        fact: str,
        audit: object,
    ) -> VaultDocument:
        if self.fail_append:
            raise ConflictError("append rejected by fake repository")
        self.appended.append((entity_id, fact))
        return VaultDocument(
            entity=Entity(
                id=entity_id,
                type=EntityType.NPC,
                name="Варос",
                status="alive",
                visibility=Visibility.DM,
                knowledge_status=KnowledgeStatus.CONFIRMED,
                created_session=None,
                last_seen_session=None,
                tags=[],
                created_at=_NOW,
                updated_at=_NOW,
                revision=expected_revision + 1,
            )
        )


def _probe(repository: FakeRepository) -> StrictRepositoryProbe:
    return StrictRepositoryProbe(repository=repository, issue=None)


def _base_repository(run) -> FakeRepository:
    return FakeRepository(list(run.snapshot.list_entities()))


# ── Applicability gate ────────────────────────────────────────────────────


def test_applicability_gate_blocks_before_any_mutation() -> None:
    run = _run(with_append=False)
    changeset = _changeset(run)
    repository = _base_repository(run)
    intent = AuditRecord(
        operation_id=f"{changeset.changeset_id}:0",
        real_time=_NOW,
        operation="create",
        source="test",
        phase="intent",
    )
    result = apply_bootstrap_changeset(
        changeset,
        store=FakeStore(),
        approval=_approval(changeset),
        evidence_record=_record(run),
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(repository),
        acknowledge_unresolved=True,
        audit_records=(intent,),
        context=_context(),
    )
    assert result.readiness is BootstrapApplyReadiness.NOT_APPLICABLE
    assert result.apply_result is None
    assert repository.created == []
    assert repository.appended == []


# ── PARTIAL preservation ──────────────────────────────────────────────────


def test_partial_apply_preserves_result_and_records_attempt() -> None:
    run = _run(with_append=True)
    changeset = _changeset(run)
    assert len(changeset.operations) == 2
    repository = _base_repository(run)
    repository.fail_append = True
    store = FakeStore()

    result = apply_bootstrap_changeset(
        changeset,
        store=store,
        approval=_approval(changeset),
        evidence_record=_record(run),
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(repository),
        acknowledge_unresolved=True,
        audit_records=(),
        context=_context(),
    )
    assert result.readiness is BootstrapApplyReadiness.READY
    assert result.apply_result is not None
    assert result.apply_result.outcome is ChangeSetApplyOutcome.PARTIAL
    assert result.apply_result.applied_operation_indices == (0,)
    assert result.apply_result.remaining_operation_indices == ()
    assert repository.created
    assert result.attempt_recorded is True
    assert result.attempt_error is None
    assert store.read_apply_attempts_if_present(changeset.changeset_id) is not None


# ── Apply-attempt persistence failure ─────────────────────────────────────


def test_attempt_persistence_failure_is_truthful_and_no_retry() -> None:
    run = _run(with_append=False)
    changeset = _changeset(run)
    repository = _base_repository(run)

    result = apply_bootstrap_changeset(
        changeset,
        store=FakeStore(fail_append=True),
        approval=_approval(changeset),
        evidence_record=_record(run),
        evidence_present=True,
        projection=run.projection,
        coverage=run.coverage,
        snapshot=run.snapshot,
        strict_probe=_probe(repository),
        acknowledge_unresolved=True,
        audit_records=(),
        context=_context(),
    )
    assert result.apply_result is not None
    assert result.apply_result.outcome is ChangeSetApplyOutcome.APPLIED
    assert result.attempt_recorded is False
    assert result.attempt_error is not None
    # Mutation happened exactly once; no rollback/retry attempted another write.
    assert repository.created == [changeset.operations[0].entity_id]


# ── Fresh Stage-10 preflight race ─────────────────────────────────────────


def _target_document(entity_id: str, entity_type: EntityType) -> VaultDocument:
    return VaultDocument(
        entity=Entity(
            id=entity_id,
            type=entity_type,
            name="Появился позже",
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


def test_fresh_stage10_preflight_race_fails_closed() -> None:
    run = _run(with_append=False)
    changeset = _changeset(run)
    create = changeset.operations[0]
    assert isinstance(create, CreateEntityOperation)
    repository = _base_repository(run)
    # Readiness succeeds against the initial snapshot; the applier's own second
    # preflight then observes the target id already present.
    repository.conflict_on_second_list = _target_document(create.entity_id, create.type)

    with pytest.raises(ValidationError):
        apply_bootstrap_changeset(
            changeset,
            store=FakeStore(),
            approval=_approval(changeset),
            evidence_record=_record(run),
            evidence_present=True,
            projection=run.projection,
            coverage=run.coverage,
            snapshot=run.snapshot,
            strict_probe=_probe(repository),
            acknowledge_unresolved=True,
            audit_records=(),
            context=_context(),
        )
    assert repository.created == []


def test_result_type_contract() -> None:
    assert BootstrapApplyResult.__dataclass_fields__["readiness"]
