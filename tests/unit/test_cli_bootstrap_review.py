"""S13-04 ``dnd bootstrap`` review/approve/reject/apply CLI presentation tests."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from dnd_assistant.application.bootstrap_apply import BootstrapApplyResult
from dnd_assistant.application.bootstrap_canonical import build_canonical_snapshot
from dnd_assistant.application.bootstrap_evidence import build_bootstrap_evidence
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.bootstrap_readiness import (
    BootstrapApplyReadiness,
    BootstrapReadinessResult,
)
from dnd_assistant.application.bootstrap_review import (
    build_bootstrap_review,
)
from dnd_assistant.application.changeset_apply import (
    ApplyCommitState,
    ApplyFailure,
    ApplyFailureCategory,
    ChangeSetApplyOutcome,
    ChangeSetApplyResult,
)
from dnd_assistant.application.vault_discovery import SourceClass
from dnd_assistant.cli.bootstrap_review import register_bootstrap_review_apply_commands
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.composition.bootstrap_review_apply import (
    BootstrapApprovalRun,
    BootstrapReviewRun,
)
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_report,
    make_source,
)

_CAMP = "camp-cli"
_NEW_REF = source_ref(_CAMP, "Notes/new.md")

runner = CliRunner()


def _app() -> typer.Typer:
    app = typer.Typer()
    register_bootstrap_review_apply_commands(app)
    return app


def _run(*, new_text: str = "новый персонаж"):
    report = make_report(
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
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый Герой", EntityType.NPC, [_NEW_REF]),),
    )
    return run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(extraction)
    )


def _bundle(*, stale: bool = False, evidence_present: bool = True):
    run = _run()
    record = build_bootstrap_evidence(
        run.projection,
        run.result,
        producer_version=run.processor_version,
        prompt_version=run.prompt_version,
        extraction_schema_version=run.extraction_schema_version,
        model_profile="heavy",
        model="m",
        provider="ollama",
    )
    report = make_report(
        _CAMP,
        [
            make_source(
                "Characters/NPCs/varos.md",
                SourceClass.ENTITY_CANDIDATE,
                canonical_text("npc-1", EntityType.NPC, "Варос"),
            ),
            make_source(
                "Notes/new.md", SourceClass.USER_SOURCE, "ИЗМЕНЕНО" if stale else "новый персонаж"
            ),
        ],
    )
    snapshot = build_canonical_snapshot(canonical_candidates_from_report(report))
    changeset = run.result.changeset
    assert changeset is not None
    return build_bootstrap_review(
        changeset=changeset,
        evidence_record=record if evidence_present else None,
        evidence_present=evidence_present,
        report=report,
        snapshot=snapshot,
        coverage=run.coverage,
    )


class _FakeContext:
    def __init__(self, store: object) -> None:
        self.changeset_store = store


def _patch(monkeypatch, bundle, *, approval_readiness=None, apply_result=None):
    monkeypatch.setattr("dnd_assistant.cli.bootstrap_review._recovery_preflight", lambda root: None)
    monkeypatch.setattr(
        "dnd_assistant.cli.bootstrap_review.compose_bootstrap_review",
        lambda root, cid: BootstrapReviewRun(
            bundle=bundle,
            readiness=BootstrapReadinessResult(BootstrapApplyReadiness.READY),
        ),
    )
    readiness = approval_readiness or BootstrapReadinessResult(BootstrapApplyReadiness.READY)
    monkeypatch.setattr(
        "dnd_assistant.cli.bootstrap_review.compose_bootstrap_approval",
        lambda root, cid, acknowledge_unresolved: BootstrapApprovalRun(
            bundle=bundle, readiness=readiness
        ),
    )
    monkeypatch.setattr(
        "dnd_assistant.cli.bootstrap_review.compose_bootstrap_proposal",
        lambda root, cid: bundle.changeset,
    )
    monkeypatch.setattr(
        "dnd_assistant.cli.bootstrap_review.compose_bootstrap_context",
        lambda root: _FakeContext(object()),
    )
    if apply_result is not None:
        monkeypatch.setattr(
            "dnd_assistant.cli.bootstrap_review.compose_bootstrap_apply",
            lambda root, cid, acknowledge_unresolved: apply_result,
        )


def _record_persist(monkeypatch) -> list[object]:
    calls: list[object] = []

    def _persist(store, approval):
        calls.append(approval)
        return None

    monkeypatch.setattr("dnd_assistant.cli.bootstrap_review.persist_approval", _persist)
    return calls


def test_review_reviewable(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle()
    _patch(monkeypatch, bundle)
    invocation = runner.invoke(_app(), ["review", bundle.changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 0, invocation.output
    assert "доступен для обзора" in invocation.output
    assert "НЕ применено" in invocation.output


def test_review_not_reviewable(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(evidence_present=False)
    _patch(monkeypatch, bundle)
    invocation = runner.invoke(_app(), ["review", bundle.changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 1
    assert "недоступен для обзора" in invocation.output


def test_review_stale(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(stale=True)
    _patch(monkeypatch, bundle)
    invocation = runner.invoke(_app(), ["review", bundle.changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 0, invocation.output
    assert "устарел" in invocation.output
    assert "предпросмотр" not in invocation.output


def test_approve_persists(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle()
    _patch(monkeypatch, bundle)
    calls = _record_persist(monkeypatch)
    invocation = runner.invoke(
        _app(),
        ["approve", bundle.changeset_id, "--vault", str(tmp_path), "--reviewer", "dm"],
    )
    assert invocation.exit_code == 0, invocation.output
    assert "одобрен" in invocation.output
    assert len(calls) == 1


def test_approve_blocked(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle()
    _patch(
        monkeypatch,
        bundle,
        approval_readiness=BootstrapReadinessResult(
            BootstrapApplyReadiness.STALE_SOURCE, "устарело"
        ),
    )
    calls = _record_persist(monkeypatch)
    invocation = runner.invoke(
        _app(),
        ["approve", bundle.changeset_id, "--vault", str(tmp_path), "--reviewer", "dm"],
    )
    assert invocation.exit_code == 1
    assert not calls


def test_reject_persists_without_apply_readiness(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(stale=True)
    _patch(monkeypatch, bundle)
    calls = _record_persist(monkeypatch)
    invocation = runner.invoke(
        _app(),
        ["reject", bundle.changeset_id, "--vault", str(tmp_path), "--reviewer", "dm"],
    )
    assert invocation.exit_code == 0, invocation.output
    assert "отклонён" in invocation.output
    assert len(calls) == 1


def test_apply_applied_states_not_complete(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle()
    result = BootstrapApplyResult(
        readiness=BootstrapApplyReadiness.READY,
        apply_result=ChangeSetApplyResult(
            changeset_id=bundle.changeset_id,
            outcome=ChangeSetApplyOutcome.APPLIED,
            applied_operation_indices=(0,),
            remaining_operation_indices=(),
        ),
        attempt_recorded=True,
    )
    _patch(monkeypatch, bundle, apply_result=result)
    invocation = runner.invoke(_app(), ["apply", bundle.changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 0, invocation.output
    assert "НЕ означает завершение" in invocation.output


def test_apply_readiness_failure(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle()
    result = BootstrapApplyResult(
        readiness=BootstrapApplyReadiness.MISSING_EVIDENCE,
        detail="нет доказательств",
    )
    _patch(monkeypatch, bundle, apply_result=result)
    invocation = runner.invoke(_app(), ["apply", bundle.changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 1
    assert "доказательства" in invocation.output


def test_apply_partial_warns(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle()
    result = BootstrapApplyResult(
        readiness=BootstrapApplyReadiness.READY,
        apply_result=ChangeSetApplyResult(
            changeset_id=bundle.changeset_id,
            outcome=ChangeSetApplyOutcome.PARTIAL,
            applied_operation_indices=(0,),
            remaining_operation_indices=(),
            failure=ApplyFailure(
                operation_index=1,
                category=ApplyFailureCategory.CONFLICT,
                message="конфликт",
            ),
            failing_operation_commit_state=ApplyCommitState.NOT_WRITTEN,
        ),
        attempt_recorded=True,
    )
    _patch(monkeypatch, bundle, apply_result=result)
    invocation = runner.invoke(_app(), ["apply", bundle.changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 1
    assert "частично" in invocation.output
