"""S11-06 terminal-integrity verifier tests (real artifacts, structural fold)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_integrity import (
    TerminalIntegrityReason,
    verify_terminal_integrity,
)
from dnd_assistant.application.post_session_persistence import (
    EMPTY_RECAP_ARTIFACT_TEXT,
    artifact_content_hash,
    persist_immutable_artifact,
    serialize_workflow_evidence,
)
from dnd_assistant.domain.post_session import (
    ArtifactKind,
    ArtifactPersisted,
    AttemptCompleted,
    AttemptStarted,
    PersistedArtifactKind,
    ProcessingLedgerEvent,
    ProcessingOutcome,
    ProposalPersisted,
    Sha256Fingerprint,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome
from dnd_assistant.domain.post_session_workflow import (
    POST_SESSION_WORKFLOW_SCHEMA_VERSION,
    AttemptWorkflowEvidence,
    ExtractionWorkflowProvenance,
    RenderingWorkflowProvenance,
    WorkflowChangePlan,
)
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from tests.unit.post_session.helpers import create_completed_session

_NOW = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)
_ATT = "att_" + "a" * 32
_FP = Sha256Fingerprint(digest="c" * 64)


def _eid(n: int) -> str:
    return "le_" + f"{n:032x}"


def _started() -> AttemptStarted:
    return AttemptStarted(
        event_id=_eid(1),
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        input_fingerprint=_FP,
        processor_version="2",
        prompt_version="v1",
    )


def _artifact(kind: PersistedArtifactKind, path: str, text: str, n: int) -> ArtifactPersisted:
    return ArtifactPersisted(
        event_id=_eid(n),
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        artifact_kind=kind,
        relative_path=path,
        content_hash=artifact_content_hash(text),
    )


def _completed(outcome: ProcessingOutcome = ProcessingOutcome.NO_CHANGES) -> AttemptCompleted:
    return AttemptCompleted(
        event_id=_eid(9),
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        outcome=outcome,
    )


def _evidence(produced: bool = False) -> AttemptWorkflowEvidence:
    return AttemptWorkflowEvidence(
        schema_version=POST_SESSION_WORKFLOW_SCHEMA_VERSION,
        session_ref="S001",
        attempt_id=_ATT,
        input_fingerprint=_FP,
        processor_version="2",
        prompt_version="v1",
        extraction=ExtractionWorkflowProvenance(extraction_schema_version=1),
        summary=RenderingWorkflowProvenance(
            artifact_kind=ArtifactKind.SUMMARY,
            render_prompt_version="s",
            render_schema_version=1,
            outcome=RenderOutcome.RENDERED,
        ),
        recap=RenderingWorkflowProvenance(
            artifact_kind=ArtifactKind.RECAP,
            render_prompt_version="r",
            render_schema_version=1,
            outcome=RenderOutcome.EMPTY,
        ),
        change_plan=WorkflowChangePlan(produced=produced),
    )


def _build_no_changes(vault_root: Path) -> tuple[ProcessingLedgerEvent, ...]:
    store = ObsidianPostSessionArtifactStore(vault_root)
    store.claim_attempt("S001", _ATT)
    summary_text = "summary body\n"
    recap_text = EMPTY_RECAP_ARTIFACT_TEXT
    workflow_text = serialize_workflow_evidence(_evidence(produced=False))
    _, sp = persist_immutable_artifact(
        store, "S001", _ATT, PersistedArtifactKind.SUMMARY, summary_text
    )
    _, rp = persist_immutable_artifact(store, "S001", _ATT, PersistedArtifactKind.RECAP, recap_text)
    _, wp = persist_immutable_artifact(
        store, "S001", _ATT, PersistedArtifactKind.WORKFLOW, workflow_text
    )
    return (
        _started(),
        _artifact(PersistedArtifactKind.SUMMARY, sp, summary_text, 2),
        _artifact(PersistedArtifactKind.RECAP, rp, recap_text, 3),
        _artifact(PersistedArtifactKind.WORKFLOW, wp, workflow_text, 4),
        _completed(ProcessingOutcome.NO_CHANGES),
    )


def _slot(
    events: Sequence[ProcessingLedgerEvent], kind: PersistedArtifactKind
) -> ArtifactPersisted:
    for event in events:
        if isinstance(event, ArtifactPersisted) and event.artifact_kind is kind:
            return event
    raise AssertionError(f"missing slot {kind}")


def _verify(vault_root: Path, events: Sequence[ProcessingLedgerEvent]):
    fold = fold_attempt_state(events, _ATT)
    return verify_terminal_integrity(
        fold,
        "S001",
        artifact_store=ObsidianPostSessionArtifactStore(vault_root),
        changeset_store=ObsidianChangeSetStore(vault_root),
    )


def test_non_completed_state_is_not_applicable(vault_root: Path, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    fold = fold_attempt_state((), _ATT)
    assert fold.state is AttemptState.NOT_STARTED
    assert _verify(vault_root, ()).ok is True


def test_legacy_completed_without_artifacts_is_incomplete(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    result = _verify(vault_root, (_started(), _completed()))
    assert result.ok is False
    assert result.reason is TerminalIntegrityReason.TERMINAL_EVIDENCE_INCOMPLETE


def test_missing_workflow_slot_is_incomplete(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionArtifactStore(vault_root)
    store.claim_attempt("S001", _ATT)
    _, sp = persist_immutable_artifact(
        store, "S001", _ATT, PersistedArtifactKind.SUMMARY, "summary\n"
    )
    _, rp = persist_immutable_artifact(
        store, "S001", _ATT, PersistedArtifactKind.RECAP, EMPTY_RECAP_ARTIFACT_TEXT
    )
    events = (
        _started(),
        _artifact(PersistedArtifactKind.SUMMARY, sp, "summary\n", 2),
        _artifact(PersistedArtifactKind.RECAP, rp, EMPTY_RECAP_ARTIFACT_TEXT, 3),
        _completed(),
    )
    result = _verify(vault_root, events)
    assert result.ok is False
    assert result.reason is TerminalIntegrityReason.TERMINAL_EVIDENCE_INCOMPLETE


def test_complete_no_changes_evidence_verifies(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    assert _verify(vault_root, _build_no_changes(vault_root)).ok is True


def test_tampered_artifact_hash_fails(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    events = _build_no_changes(vault_root)
    summary = _slot(events, PersistedArtifactKind.SUMMARY)
    (vault_root / summary.relative_path).write_bytes(b"tampered body\n")
    result = _verify(vault_root, events)
    assert result.ok is False
    assert result.reason is TerminalIntegrityReason.ARTIFACT_HASH_MISMATCH


def test_wrong_recorded_path_fails(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    events = _build_no_changes(vault_root)
    summary = _slot(events, PersistedArtifactKind.SUMMARY)
    bad = summary.model_copy(update={"relative_path": "wrong/summary.md"})
    replaced = tuple(
        bad
        if isinstance(e, ArtifactPersisted) and e.artifact_kind is PersistedArtifactKind.SUMMARY
        else e
        for e in events
    )
    result = _verify(vault_root, replaced)
    assert result.ok is False
    assert result.reason is TerminalIntegrityReason.ARTIFACT_PATH_MISMATCH


def test_invalid_workflow_evidence_fails(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    events = _build_no_changes(vault_root)
    workflow = _slot(events, PersistedArtifactKind.WORKFLOW)
    (vault_root / workflow.relative_path).write_bytes(b"not json\n")
    bad = workflow.model_copy(update={"content_hash": artifact_content_hash("not json\n")})
    replaced = tuple(
        bad
        if isinstance(e, ArtifactPersisted) and e.artifact_kind is PersistedArtifactKind.WORKFLOW
        else e
        for e in events
    )
    result = _verify(vault_root, replaced)
    assert result.ok is False
    assert result.reason is TerminalIntegrityReason.WORKFLOW_EVIDENCE_INVALID


def test_unexpected_proposal_fails(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    events = _build_no_changes(vault_root)
    proposal = ProposalPersisted(
        event_id=_eid(8),
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        changeset_id=f"cs_S001_{_ATT}",
        changeset_fingerprint=Sha256Fingerprint(digest="e" * 64),
    )
    result = _verify(vault_root, (*events[:-1], proposal, events[-1]))
    assert result.ok is False
    assert result.reason is TerminalIntegrityReason.UNEXPECTED_PROPOSAL
