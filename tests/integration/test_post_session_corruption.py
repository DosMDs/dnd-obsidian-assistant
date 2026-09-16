"""S11-08 corruption/tamper, CLI fail-closed and R1 ownership integration tests.

Drives the real CLI against a temporary Vault with a deterministic Pydantic AI
``FunctionModel``.  Covers all nine ``TerminalIntegrityReason`` values, structural
ledger conflicts, proposal persistence failures, NO_CHANGES tamper and the R1
recovery-ownership boundary.  No Ollama, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dnd_assistant.application.changeset_recovery import ChangeSetIntentOwnershipGate
from dnd_assistant.application.changeset_store import serialize_proposal
from dnd_assistant.application.post_session_integrity import TerminalIntegrityReason
from dnd_assistant.application.post_session_persistence import artifact_content_hash
from dnd_assistant.application.post_session_processor import (
    PostSessionProcessorStatus,
    run_post_session_processing,
)
from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.domain.changeset import AppendFactOperation, ChangeSet, ProposalProvenance
from dnd_assistant.domain.types import Provenance
from dnd_assistant.storage.audit import AuditRecord, AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from dnd_assistant.storage.session_recovery import ObsidianSessionRecoveryRepository
from tests.integration.post_session_processor_helpers import (
    ATTEMPT_A,
    append_extraction,
    build_deps,
    fixed_clock,
)
from tests.integration.test_cli_post_session import (
    NO_CHANGES_ATTEMPT,
    PRODUCED_ATTEMPT,
    ScriptedPostSessionModel,
    _append_extraction,
    _invoke_outputs,
    _invoke_process,
    _run_no_changes,
    _write_config,
)
from tests.integration.test_post_session_context import _build, _build_vault
from tests.support.post_session_faults import FaultingChangeSetStore, always
from tests.unit.post_session.extraction_helpers import (
    make_claim,
    make_extraction,
    make_mention,
)

runner = CliRunner()

_SUMMARY = "summary.md"
_RECAP = "recap.md"
_WORKFLOW = "workflow.json"


def _ledger_path(root: Path, session: str = "S001") -> Path:
    return root / "_system" / "raw" / "sessions" / session / "processing" / "ledger.jsonl"


def _attempt_dir(root: Path, attempt: str, session: str = "S001") -> Path:
    return root / "_system" / "raw" / "sessions" / session / "processing" / "attempts" / attempt


def _rewrite_ledger(root: Path, transform, session: str = "S001") -> None:
    path = _ledger_path(root, session)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    rewritten = [result for record in records if (result := transform(record)) is not None]
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            for record in rewritten
        ),
        encoding="utf-8",
        newline="",
    )


def _is_kind(record: dict[str, Any], kind: str) -> bool:
    return record.get("event_kind") == kind


# ── `session outputs` fails closed for every TerminalIntegrityReason ───────


def test_outputs_terminal_evidence_incomplete(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)

    def drop_workflow(record: dict[str, Any]) -> dict[str, Any] | None:
        if _is_kind(record, "artifact_persisted") and record.get("artifact_kind") == "workflow":
            return None
        return record

    _rewrite_ledger(root, drop_workflow)
    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "terminal_evidence_incomplete" in result.stderr
    assert _SUMMARY not in result.stdout and _RECAP not in result.stdout


def test_outputs_artifact_missing(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)
    (_attempt_dir(root, NO_CHANGES_ATTEMPT) / _SUMMARY).unlink()

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "artifact_missing" in result.stderr


def test_outputs_artifact_hash_mismatch(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)
    (_attempt_dir(root, NO_CHANGES_ATTEMPT) / _RECAP).write_bytes(b"tampered\n")

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "artifact_hash_mismatch" in result.stderr


def test_outputs_artifact_path_mismatch(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)

    def wrong_path(record: dict[str, Any]) -> dict[str, Any]:
        if _is_kind(record, "artifact_persisted") and record.get("artifact_kind") == "summary":
            record["relative_path"] = "wrong/summary.md"
        return record

    _rewrite_ledger(root, wrong_path)
    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "artifact_path_mismatch" in result.stderr


def _produced_attempt(root: Path, audit: AuditService, tmp_path: Path, model=None) -> Any:
    config = _write_config(tmp_path)
    model = model or ScriptedPostSessionModel(extraction=_append_extraction(root, audit))
    result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)
    assert result.exit_code == 0
    return result


def test_outputs_proposal_missing(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _produced_attempt(root, audit, tmp_path)
    (root / "_system" / "changesets" / f"cs_S001_{PRODUCED_ATTEMPT}.proposal.json").unlink()

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "proposal_missing" in result.stderr


def test_outputs_proposal_fingerprint_mismatch(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _produced_attempt(root, audit, tmp_path)
    other = ChangeSet(
        changeset_id=f"cs_S001_{PRODUCED_ATTEMPT}",
        provenance=ProposalProvenance(provenance=Provenance.MODEL_INFERENCE),
        session_ref="S001",
        operations=(AppendFactOperation(entity_id="npc-aria", expected_revision=1, fact="Other"),),
    )
    path = root / "_system" / "changesets" / f"cs_S001_{PRODUCED_ATTEMPT}.proposal.json"
    path.write_text(serialize_proposal(other), encoding="utf-8", newline="")

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "proposal_fingerprint_mismatch" in result.stderr


def test_outputs_unexpected_proposal(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)
    changesets = root / "_system" / "changesets"
    changesets.mkdir(parents=True, exist_ok=True)
    (changesets / f"cs_S001_{NO_CHANGES_ATTEMPT}.proposal.json").write_text("{}", encoding="utf-8")

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "unexpected_proposal" in result.stderr


def _write_workflow(root: Path, attempt: str, text: str) -> None:
    (_attempt_dir(root, attempt) / _WORKFLOW).write_text(text, encoding="utf-8", newline="")
    digest = artifact_content_hash(text).digest

    def update_hash(record: dict[str, Any]) -> dict[str, Any]:
        if _is_kind(record, "artifact_persisted") and record.get("artifact_kind") == "workflow":
            record["content_hash"]["digest"] = digest
        return record

    _rewrite_ledger(root, update_hash)


def test_outputs_workflow_evidence_invalid(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)
    _write_workflow(root, NO_CHANGES_ATTEMPT, "not json\n")

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "workflow_evidence_invalid" in result.stderr


def test_outputs_workflow_evidence_inconsistent(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)
    workflow_path = _attempt_dir(root, NO_CHANGES_ATTEMPT) / _WORKFLOW
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    data["session_ref"] = "S999"
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    _write_workflow(root, NO_CHANGES_ATTEMPT, text)

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1
    assert "workflow_evidence_inconsistent" in result.stderr


def test_all_terminal_integrity_reasons_have_cli_coverage() -> None:
    covered = {
        "terminal_evidence_incomplete",
        "artifact_missing",
        "artifact_hash_mismatch",
        "artifact_path_mismatch",
        "proposal_missing",
        "proposal_fingerprint_mismatch",
        "unexpected_proposal",
        "workflow_evidence_invalid",
        "workflow_evidence_inconsistent",
    }
    assert covered == {reason.value for reason in TerminalIntegrityReason}


# ── Structural ledger conflict fail-closed ─────────────────────────────────


def test_process_structural_conflict_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    store = ObsidianPostSessionProcessingStore(root)
    for index in range(2):
        store.append_ledger_line(
            "S001",
            json.dumps(
                {
                    "event_kind": "attempt_started",
                    "schema_version": 1,
                    "event_id": "le_" + f"{index + 1:032x}",
                    "attempt_id": ATTEMPT_A,
                    "session_ref": "S001",
                    "real_time": fixed_clock().isoformat(),
                    "input_fingerprint": {
                        "algorithm": "sha256",
                        "digest": prepared.fingerprint.digest,
                    },
                    "processor_version": prepared.identity.processor_version,
                    "prompt_version": prepared.identity.prompt_version,
                    "model_profile": None,
                },
                separators=(",", ":"),
            )
            + "\n",
        )

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason is not None and result.reason.startswith(
        "ledger_conflict:multiple_started"
    )
    assert len(getattr(deps.extraction_model, "requests", [])) == 0


def test_outputs_structural_conflict_fails_closed(tmp_path: Path) -> None:
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)

    # Add a second terminal event for the same attempt (structural contradiction).
    terminal = {
        "event_kind": "attempt_completed",
        "schema_version": 1,
        "event_id": "le_" + "f" * 32,
        "attempt_id": NO_CHANGES_ATTEMPT,
        "session_ref": "S001",
        "real_time": fixed_clock().isoformat(),
        "outcome": "no_changes",
    }
    with _ledger_path(root).open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(terminal, separators=(",", ":")) + "\n")

    result = _invoke_outputs(root, "S001")
    assert result.exit_code == 1


# ── Proposal persistence failures ──────────────────────────────────────────


def test_proposal_storage_failure_fails_closed(tmp_path: Path) -> None:
    from dataclasses import replace

    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    deps = replace(
        deps,
        changeset_store=FaultingChangeSetStore(
            ObsidianChangeSetStore(root), fail_create_proposal=always
        ),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "Processing storage failure"
    ledger = _ledger_path(root).read_text(encoding="utf-8")
    assert '"attempt_failed"' in ledger
    assert '"proposal_persisted"' not in ledger
    assert not (root / "_system" / "changesets").exists()


# ── NO_CHANGES tamper: injected proposal event ─────────────────────────────


def test_no_changes_injected_proposal_event_fails(tmp_path: Path) -> None:
    from dnd_assistant.application.post_session_outputs import (
        PostSessionOutputsError,
        build_post_session_outputs,
    )
    from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore

    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    _run_no_changes(root, config)

    injected = {
        "event_kind": "proposal_persisted",
        "schema_version": 1,
        "event_id": "le_" + "e" * 32,
        "attempt_id": NO_CHANGES_ATTEMPT,
        "session_ref": "S001",
        "real_time": fixed_clock().isoformat(),
        "changeset_id": f"cs_S001_{NO_CHANGES_ATTEMPT}",
        "changeset_fingerprint": {"algorithm": "sha256", "digest": "e" * 64},
    }
    # Insert the injected proposal event before the terminal event so the fold
    # stays structurally valid and the failure is specifically UNEXPECTED_PROPOSAL.
    records = [
        json.loads(line)
        for line in _ledger_path(root).read_text(encoding="utf-8").splitlines()
        if line
    ]
    rewritten: list[dict[str, Any]] = []
    for record in records:
        if _is_kind(record, "attempt_completed") and record.get("attempt_id") == NO_CHANGES_ATTEMPT:
            rewritten.append(injected)
        rewritten.append(record)
    _ledger_path(root).write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in rewritten),
        encoding="utf-8",
        newline="",
    )

    with pytest.raises(PostSessionOutputsError) as exc:
        build_post_session_outputs(
            ObsidianPostSessionProcessingStore(root),
            ObsidianPostSessionArtifactStore(root),
            ObsidianChangeSetStore(root),
            "S001",
        )
    assert exc.value.reason is TerminalIntegrityReason.UNEXPECTED_PROPOSAL


# ── R1 recovery ownership ──────────────────────────────────────────────────


def _recovery_service(root: Path, audit: AuditService) -> SessionRecoveryService:
    return SessionRecoveryService(
        ObsidianSessionRecoveryRepository(root, audit),
        ownership_gate=ChangeSetIntentOwnershipGate(
            ObsidianChangeSetStore(root), read_audit_records=audit.read_all
        ),
    )


def test_processing_state_is_not_a_recovery_blocker(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.COMPLETED

    partition = _recovery_service(root, audit).inspect_runtime_partition()
    assert partition.blocking == ()


def test_changeset_owned_intent_does_not_block_process(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    audit_before = audit.read_all()

    proposal = ChangeSet(
        changeset_id="cs_S001_manual",
        provenance=ProposalProvenance(provenance=Provenance.MODEL_INFERENCE),
        session_ref="S001",
        operations=(AppendFactOperation(entity_id="npc-aria", expected_revision=1, fact="Fact"),),
    )
    ObsidianChangeSetStore(root).create_proposal(
        proposal.changeset_id, serialize_proposal(proposal)
    )
    audit.append(
        AuditRecord(
            operation_id="cs_S001_manual:0",
            real_time=fixed_clock(),
            session="S001",
            operation="append_entity_fact",
            entity_id="npc-aria",
            source="test",
            phase="intent",
        )
    )

    config = _write_config(tmp_path)
    model = ScriptedPostSessionModel(extraction=make_extraction())

    result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)

    assert result.exit_code == 0
    assert "Обнаружено" not in result.stderr
    _ = audit_before


def test_failed_attempt_adds_no_repair_action(tmp_path: Path) -> None:
    from dnd_assistant.application.post_session_extraction import (
        ExtractionFailureReason,
        PostSessionExtractionError,
    )

    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)
    audit_before = audit.read_all()
    error = PostSessionExtractionError(ExtractionFailureReason.MODEL_UNAVAILABLE, "down")
    deps = build_deps(root, audit, extraction_error=error)
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.FAILED

    assert audit.read_all() == audit_before
    partition = _recovery_service(root, audit).inspect_runtime_partition()
    assert partition.blocking == ()


# ── CLI privacy and model-lifetime hardening ───────────────────────────────


def test_cli_never_prints_artifact_body_canary(tmp_path: Path) -> None:
    canary = "CLI_BODY_SECRET_CANARY"
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    model = ScriptedPostSessionModel(
        extraction=make_extraction(), render_body=f"# {canary}\nBody.\n"
    )

    result = _invoke_process(root, config, model, args=["S001"], attempt_id=NO_CHANGES_ATTEMPT)
    assert result.exit_code == 0
    assert canary not in result.stdout
    assert canary not in result.stderr

    outputs = _invoke_outputs(root, "S001")
    assert canary not in outputs.stdout
    assert canary not in outputs.stderr


def test_cli_never_prints_workflow_unresolved_canary(tmp_path: Path) -> None:
    canary = "CLI_UNRESOLVED_SECRET_CANARY"
    root, _audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    extraction = make_extraction(
        claims=(
            make_claim(
                claim_id="c1",
                entity_mentions=(
                    make_mention(mention_id="m1", candidate_entity_id=None, text=canary),
                ),
            ),
        )
    )
    model = ScriptedPostSessionModel(extraction=extraction)

    result = _invoke_process(root, config, model, args=["S001"], attempt_id=NO_CHANGES_ATTEMPT)
    assert canary not in result.stdout
    assert canary not in result.stderr


def test_cli_model_close_invoked_on_processor_failure(tmp_path: Path) -> None:
    from unittest.mock import patch

    root, audit, _ = _build_vault(tmp_path)
    config = _write_config(tmp_path)
    model = ScriptedPostSessionModel(
        extraction=_append_extraction(root, audit), extraction_error=RuntimeError("boom")
    )
    closed: list[Any] = []

    with patch(
        "dnd_assistant.cli.post_session_runtime._close_model",
        side_effect=lambda value: closed.append(value),
    ):
        result = _invoke_process(root, config, model, args=["S001"], attempt_id=PRODUCED_ATTEMPT)

    assert result.exit_code == 1
    assert closed, "model close hook must run on the processor-failure path"
    assert "boom" not in result.stdout
    assert "boom" not in result.stderr
