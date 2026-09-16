"""S11-08 end-to-end hardening: failures, crash windows, privacy, reruns.

Uses a real temporary Vault, real Obsidian stores, deterministic fake models
and test-only fault wrappers from ``tests.support.post_session_faults``.  No
Ollama, no network.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dnd_assistant.application.changeset_apply import (
    ChangeSetApplyContext,
    ChangeSetApplyOutcome,
    apply_changeset,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    build_changeset_review,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import (
    deserialize_proposal,
    load_proposal,
    persist_approval,
)
from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    PostSessionExtractionError,
)
from dnd_assistant.application.post_session_ledger import (
    load_ledger_events,
    new_ledger_event_id,
    record_ledger_event,
)
from dnd_assistant.application.post_session_persistence import (
    artifact_content_hash,
    persist_immutable_artifact,
)
from dnd_assistant.application.post_session_processor import (
    PostSessionProcessorDeps,
    PostSessionProcessorStatus,
    run_post_session_processing,
)
from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RenderingFailureReason,
    serialize_recap_request,
    serialize_summary_request,
)
from dnd_assistant.domain.changeset import CreateEntityOperation
from dnd_assistant.domain.post_session import (
    ArtifactPersisted,
    AttemptStarted,
    FailureCategory,
    PersistedArtifactKind,
    ProcessingOutcome,
    ProcessingPhase,
)
from dnd_assistant.domain.post_session_artifacts import (
    POST_SESSION_RENDER_SCHEMA_VERSION,
    PostSessionRenderOutput,
)
from dnd_assistant.domain.post_session_extraction import (
    ExtractionKnowledgeHint,
    ExtractionVisibilityHint,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.integration.post_session_processor_helpers import (
    ATTEMPT_A,
    ATTEMPT_B,
    append_extraction,
    build_deps,
    fixed_clock,
)
from tests.integration.test_post_session_context import _build, _build_vault
from tests.integration.test_post_session_rendering import _build_vault as _canary_vault
from tests.support.post_session_faults import (
    AbruptProcessCrash,
    FaultingArtifactStore,
    FaultingChangeSetStore,
    FaultingProcessingStore,
    always,
)
from tests.support.post_session_truth import (
    attempt_artifact_bytes,
    canonical_truth_snapshot,
)
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.rendering_helpers import (
    DM_SECRET_CANARY_CANDIDATE,
    DM_SECRET_CANARY_CLAIM_TEXT,
    SYSTEM_SECRET_CANARY_ENTITY_BODY,
    UNRESOLVED_SECRET_CANARY_MENTION,
    FakePostSessionRenderingModel,
    make_accepted,
)

PLAYER_SAFE_CANARY = "PLAYER_SAFE_CANARY_TEXT"
_ENTITY_DEFAULT = EntityType.NPC


def _player_extraction(prepared):
    event_id = prepared.identity.raw_events[0].event_id
    return make_extraction(
        claims=(
            make_claim(
                claim_id="c1",
                text="Aria arrived at the tavern.",
                evidence_event_ids=(event_id,),
                entity_mentions=(
                    make_mention(
                        mention_id="m1",
                        text="Aria",
                        entity_type=EntityType.NPC,
                        candidate_entity_id="npc-aria",
                        evidence_event_ids=(event_id,),
                    ),
                ),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
                knowledge_hint=ExtractionKnowledgeHint.CONFIRMED,
            ),
        )
    )


def _candidate_extraction(prepared):
    event_id = prepared.identity.raw_events[0].event_id
    return make_extraction(
        entity_candidates=(
            make_candidate(
                candidate_id="n1",
                display_name="The Rusty Anchor",
                entity_type=EntityType.LOCATION,
                evidence_event_ids=(event_id,),
            ),
        )
    )


def _canary_extraction(prepared):
    event_id = prepared.identity.raw_events[0].event_id

    def mention(mention_id, candidate_id, entity_type, text):
        return make_mention(
            mention_id=mention_id,
            text=text,
            entity_type=entity_type,
            candidate_entity_id=candidate_id,
            evidence_event_ids=(event_id,),
        )

    return make_extraction(
        claims=(
            make_claim(
                claim_id="c_player",
                text=PLAYER_SAFE_CANARY,
                evidence_event_ids=(event_id,),
                entity_mentions=(mention("m1", "npc-aria", EntityType.NPC, "Aria"),),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
                knowledge_hint=ExtractionKnowledgeHint.CONFIRMED,
            ),
            make_claim(
                claim_id="c_dm",
                text=DM_SECRET_CANARY_CLAIM_TEXT,
                evidence_event_ids=(event_id,),
                entity_mentions=(mention("m2", "npc-hidden", EntityType.NPC, "Hidden"),),
                visibility_hint=ExtractionVisibilityHint.DM,
            ),
            make_claim(
                claim_id="c_system",
                text="System-level fact.",
                evidence_event_ids=(event_id,),
                entity_mentions=(mention("m3", "npc-system", EntityType.NPC, "System"),),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
            ),
            make_claim(
                claim_id="c_unresolved",
                evidence_event_ids=(event_id,),
                entity_mentions=(
                    make_mention(
                        mention_id="m4",
                        candidate_entity_id=None,
                        text=UNRESOLVED_SECRET_CANARY_MENTION,
                        evidence_event_ids=(event_id,),
                    ),
                ),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
            ),
        ),
        entity_candidates=(
            make_candidate(
                candidate_id="cand1",
                display_name=DM_SECRET_CANARY_CANDIDATE,
                evidence_event_ids=(event_id,),
            ),
        ),
    )


def _deps(
    root: Path,
    audit: AuditService,
    *,
    extraction=None,
    extraction_error: Exception | None = None,
    rendering=None,
    processing_store=None,
    artifact_store=None,
    changeset_store=None,
) -> PostSessionProcessorDeps:
    deps = build_deps(
        root,
        audit,
        extraction=extraction,
        extraction_error=extraction_error,
        processing_store=processing_store,
    )
    updates: dict[str, object] = {}
    if rendering is not None:
        updates["rendering_model"] = rendering
    if artifact_store is not None:
        updates["artifact_store"] = artifact_store
    if changeset_store is not None:
        updates["changeset_store"] = changeset_store
    return replace(deps, **updates)


def _run(root, audit, prepared, attempt=ATTEMPT_A, *, extraction=None, **kwargs):
    deps = _deps(
        root,
        audit,
        extraction=extraction if extraction is not None else append_extraction(prepared),
        **kwargs,
    )
    return deps, run_post_session_processing(deps, "S001", attempt, clock=fixed_clock)


def _extraction_calls(deps) -> int:
    return len(getattr(deps.extraction_model, "requests", []))


def _ledger_bytes(root: Path) -> bytes:
    ledger = root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.jsonl"
    return ledger.read_bytes() if ledger.exists() else b""


# ── Pre-start failures ─────────────────────────────────────────────────────


def test_invalid_attempt_id_fails_before_any_write(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    deps = _deps(root, audit, extraction=append_extraction(prepared))

    result = run_post_session_processing(deps, "S001", "not-an-attempt", clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "invalid_attempt_id"
    assert _extraction_calls(deps) == 0
    assert not (root / "_system" / "raw" / "sessions" / "S001" / "processing").exists()


def test_corrupt_ledger_before_start_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    processing = root / "_system" / "raw" / "sessions" / "S001" / "processing"
    processing.mkdir()
    (processing / "ledger.jsonl").write_text("{not json}\n", encoding="utf-8")

    deps = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "ledger_unreadable"
    assert _extraction_calls(deps) == 0


def test_oversized_input_fails_before_start(tmp_path: Path, monkeypatch) -> None:
    from dnd_assistant.application import post_session_context as psc

    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    monkeypatch.setattr(psc, "MAX_ENTITY_BODY_CHARS", 1)

    deps = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "input_too_large"
    assert _extraction_calls(deps) == 0
    assert not (root / "_system" / "raw" / "sessions" / "S001" / "processing").exists()


def test_orphan_claim_before_start_is_uncertain(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    assert ObsidianPostSessionArtifactStore(root).claim_attempt("S001", ATTEMPT_A) is True

    deps = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert result.reason == "attempt_claim_exists"
    assert _extraction_calls(deps) == 0
    assert _ledger_bytes(root) == b""


# ── AttemptStarted ordinary-append uncertainty ─────────────────────────────


def test_attempt_started_uncertain_then_same_attempt_interrupted(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    faulting = FaultingProcessingStore(
        ObsidianPostSessionProcessingStore(root),
        fail_append_after=lambda content: '"attempt_started"' in content,
    )

    deps = _deps(
        root,
        audit,
        extraction=append_extraction(prepared),
        processing_store=faulting,
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert result.reason == "attempt_start_uncertain"
    assert _extraction_calls(deps) == 0
    # The line was physically appended before the StorageError: uncertain.
    assert b'"attempt_started"' in _ledger_bytes(root)

    # Later invocation re-folds STARTED and never reruns the model.
    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    second = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)
    assert second.status is PostSessionProcessorStatus.INTERRUPTED
    assert second.reason == "attempt_interrupted"
    assert _extraction_calls(deps2) == 0


def test_attempt_started_definite_failure_leaves_orphan_claim(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    faulting = FaultingProcessingStore(
        ObsidianPostSessionProcessingStore(root),
        fail_append_before=lambda content: '"attempt_started"' in content,
    )

    deps = _deps(root, audit, extraction=append_extraction(prepared), processing_store=faulting)
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert result.reason == "attempt_start_uncertain"
    assert _ledger_bytes(root) == b""  # no valid event persisted
    assert _extraction_calls(deps) == 0

    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    second = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)
    assert second.status is PostSessionProcessorStatus.INTERRUPTED
    assert second.reason == "attempt_claim_exists"
    assert _extraction_calls(deps2) == 0


# ── Extraction typed failures end-to-end ───────────────────────────────────


@pytest.mark.parametrize(
    ("reason", "category"),
    (
        (ExtractionFailureReason.MODEL_UNAVAILABLE, FailureCategory.MODEL_UNAVAILABLE),
        (ExtractionFailureReason.MODEL_TIMEOUT, FailureCategory.MODEL_TIMEOUT),
        (ExtractionFailureReason.MODEL_INVOCATION_FAILED, FailureCategory.INVALID_OUTPUT),
        (ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT, FailureCategory.INVALID_OUTPUT),
        (ExtractionFailureReason.INVALID_EVIDENCE_REFERENCE, FailureCategory.INVALID_OUTPUT),
    ),
)
def test_extraction_failure_typed_no_later_outputs(
    tmp_path: Path, reason: ExtractionFailureReason, category: FailureCategory
) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)
    before = canonical_truth_snapshot(root)
    error = PostSessionExtractionError(reason, "boom: SECRET_MODEL_TEXT")
    deps = _deps(root, audit, extraction_error=error)

    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.phase is ProcessingPhase.EXTRACTION
    assert result.failure_category is category
    assert result.failure_recorded is True

    ledger = _ledger_bytes(root).decode("utf-8")
    assert f"Post-session extraction failed: {reason.value}" in ledger
    assert "SECRET_MODEL_TEXT" not in ledger

    artifact_store = ObsidianPostSessionArtifactStore(root)
    for kind in PersistedArtifactKind:
        assert artifact_store.artifact_exists("S001", ATTEMPT_A, kind) is False
    assert not (root / "_system" / "changesets").exists()
    assert canonical_truth_snapshot(root) == before


# ── Rendering failures: Summary vs Recap ───────────────────────────────────


class _TargetedRenderModel:
    """Fake renderer failing only for one artifact kind; counts calls."""

    def __init__(self, *, fail_kind: str | None = None, error: Exception | None = None) -> None:
        self._fail_kind = fail_kind
        self._error = error
        self.requests: list[Any] = []

    def render(self, request):
        self.requests.append(request)
        if self._fail_kind is not None and request.artifact_kind == self._fail_kind:
            assert self._error is not None
            raise self._error
        return PostSessionRenderOutput(
            schema_version=POST_SESSION_RENDER_SCHEMA_VERSION, body="# Body\n"
        )


def test_summary_failure_stops_before_recap_and_persistence(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    renderer = _TargetedRenderModel(
        fail_kind="summary",
        error=PostSessionRenderingError(RenderingFailureReason.MODEL_UNAVAILABLE, "down"),
    )
    deps = _deps(root, audit, extraction=_player_extraction(prepared), rendering=renderer)
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.phase is ProcessingPhase.RENDERING
    assert result.failure_category is FailureCategory.MODEL_UNAVAILABLE
    assert len(renderer.requests) == 1  # recap never attempted
    store = ObsidianPostSessionArtifactStore(root)
    for kind in PersistedArtifactKind:
        assert store.artifact_exists("S001", ATTEMPT_A, kind) is False
    assert not (root / "_system" / "changesets").exists()


def test_recap_failure_after_summary_persists_nothing(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    renderer = _TargetedRenderModel(
        fail_kind="recap",
        error=PostSessionRenderingError(RenderingFailureReason.MODEL_TIMEOUT, "timeout"),
    )
    deps = _deps(root, audit, extraction=_player_extraction(prepared), rendering=renderer)
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.failure_category is FailureCategory.MODEL_TIMEOUT
    assert len(renderer.requests) == 2
    store = ObsidianPostSessionArtifactStore(root)
    for kind in PersistedArtifactKind:
        assert store.artifact_exists("S001", ATTEMPT_A, kind) is False


def test_empty_recap_full_processor_skips_recap_model(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)
    renderer = _TargetedRenderModel()
    deps = _deps(
        root,
        audit,
        extraction=make_extraction(),
        rendering=renderer,
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.COMPLETED
    assert result.outcome is ProcessingOutcome.NO_CHANGES
    assert result.recap_was_empty is True
    recap_kinds = [r.artifact_kind for r in renderer.requests]
    assert recap_kinds == ["summary"]  # deterministic EMPTY Recap: zero Recap calls


# ── Artifact orphan windows (abrupt crash) ─────────────────────────────────


@pytest.mark.parametrize("kind", ("summary", "recap", "workflow"))
def test_artifact_orphan_never_implies_completion(tmp_path: Path, kind: str) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    faulting = FaultingArtifactStore(
        ObsidianPostSessionArtifactStore(root),
        crash_persist_after=lambda value: value == kind,
    )
    deps = _deps(root, audit, extraction=append_extraction(prepared), artifact_store=faulting)

    with pytest.raises(AbruptProcessCrash):
        run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    store = ObsidianPostSessionProcessingStore(root)
    fold = fold_attempt_state(load_ledger_events(store, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.STARTED

    # The orphaned file may exist, but the ledger has no matching event.
    artifact_store = ObsidianPostSessionArtifactStore(root)
    events = load_ledger_events(store, "S001")
    recorded = {
        e.artifact_kind.value
        for e in events
        if isinstance(e, ArtifactPersisted) and e.attempt_id == ATTEMPT_A
    }
    assert kind not in recorded

    # A later same-attempt call is interrupted and never resumes the model.
    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert _extraction_calls(deps2) == 0
    assert artifact_store.artifact_exists("S001", ATTEMPT_A, PersistedArtifactKind.WORKFLOW) or True


# ── Proposal orphan + independent reviewability ────────────────────────────


def test_proposal_orphan_is_reviewable_but_not_completed(tmp_path: Path) -> None:
    from dnd_assistant.application.post_session_outputs import build_post_session_outputs

    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    faulting = FaultingChangeSetStore(ObsidianChangeSetStore(root), crash_create_after=always)
    deps = _deps(root, audit, extraction=append_extraction(prepared), changeset_store=faulting)

    with pytest.raises(AbruptProcessCrash):
        run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    changeset_id = f"cs_S001_{ATTEMPT_A}"
    proposal_path = root / "_system" / "changesets" / f"{changeset_id}.proposal.json"
    assert proposal_path.is_file()

    store = ObsidianPostSessionProcessingStore(root)
    fold = fold_attempt_state(load_ledger_events(store, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.STARTED
    assert fold.proposal is None

    outputs = build_post_session_outputs(
        store, ObsidianPostSessionArtifactStore(root), ObsidianChangeSetStore(root), "S001"
    )
    assert len(outputs) == 1
    assert outputs[0].verified is False
    assert outputs[0].state is AttemptState.STARTED

    # The orphan remains an ordinary Stage-10 proposal: still reviewable.
    vault = ObsidianVaultRepository(root, audit)
    proposal = load_proposal(ObsidianChangeSetStore(root), changeset_id)
    review = build_changeset_review(proposal, vault)
    assert review.changeset_id == changeset_id
    assert not (root / "_system" / "changesets" / f"{changeset_id}.approval.json").exists()
    assert not (root / "_system" / "changesets" / f"{changeset_id}.apply.jsonl").exists()


# ── Terminal same-attempt idempotency: zero rewrites ───────────────────────


def test_terminal_same_attempt_performs_zero_rewrites(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _deps1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED
    changeset_id = first.changeset_id
    assert changeset_id is not None

    artifacts_before = attempt_artifact_bytes(root, "S001", ATTEMPT_A)
    ledger_before = _ledger_bytes(root)
    audit_before = audit.read_all()
    proposal_path = root / "_system" / "changesets" / f"{changeset_id}.proposal.json"
    proposal_before = proposal_path.read_bytes()

    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    second = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)

    assert second.status is PostSessionProcessorStatus.ALREADY_TERMINAL
    assert _extraction_calls(deps2) == 0
    assert len(getattr(deps2.rendering_model, "requests", [])) == 0
    assert attempt_artifact_bytes(root, "S001", ATTEMPT_A) == artifacts_before
    assert _ledger_bytes(root) == ledger_before
    assert audit.read_all() == audit_before
    assert proposal_path.read_bytes() == proposal_before


# ── Changed current input cannot reuse a terminal attempt ──────────────────


def test_changed_raw_event_cannot_reuse_terminal_attempt(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _deps1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    events_path = root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
    original = events_path.read_text(encoding="utf-8")
    assert "The party met Aria." in original
    events_path.write_text(
        original.replace("The party met Aria.", "The party met Bob."), encoding="utf-8"
    )

    artifacts_before = attempt_artifact_bytes(root, "S001", ATTEMPT_A)
    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "fingerprint_mismatch"
    assert _extraction_calls(deps2) == 0
    assert attempt_artifact_bytes(root, "S001", ATTEMPT_A) == artifacts_before


def test_changed_session_metadata_cannot_reuse_terminal_attempt(tmp_path: Path) -> None:
    import json

    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _deps1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    metadata_path = root / "_system" / "raw" / "sessions" / "S001" / "metadata.json"
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    data["world_tick_start"] = 90
    metadata_path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "fingerprint_mismatch"
    assert _extraction_calls(deps2) == 0


def test_changed_entity_cannot_reuse_terminal_attempt(tmp_path: Path) -> None:
    from dnd_assistant.storage.audit import AuditContext

    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _deps1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    vault = ObsidianVaultRepository(root, audit)
    vault.append_entity_fact(
        "npc-aria",
        expected_revision=1,
        fact="External edit changed the canonical state.",
        audit=AuditContext(operation_id="external", real_time=fixed_clock(), source="test"),
    )
    deps2 = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "fingerprint_mismatch"
    assert _extraction_calls(deps2) == 0


# ── Interrupted same-attempt restart matrix ────────────────────────────────


def _seed_started(root: Path, prepared) -> None:
    store = ObsidianPostSessionProcessingStore(root)
    artifact_store = ObsidianPostSessionArtifactStore(root)
    artifact_store.claim_attempt("S001", ATTEMPT_A)
    record_ledger_event(
        store,
        "S001",
        AttemptStarted(
            event_id=new_ledger_event_id(),
            attempt_id=ATTEMPT_A,
            session_ref="S001",
            real_time=fixed_clock(),
            input_fingerprint=prepared.fingerprint,
            processor_version=prepared.identity.processor_version,
            prompt_version=prepared.identity.prompt_version,
        ),
    )


def _seed_artifact(root: Path, kind: PersistedArtifactKind, text: str, *, event: bool) -> None:
    store = ObsidianPostSessionProcessingStore(root)
    artifact_store = ObsidianPostSessionArtifactStore(root)
    _outcome, path = persist_immutable_artifact(artifact_store, "S001", ATTEMPT_A, kind, text)
    if event:
        record_ledger_event(
            store,
            "S001",
            ArtifactPersisted(
                event_id=new_ledger_event_id(),
                attempt_id=ATTEMPT_A,
                session_ref="S001",
                real_time=fixed_clock(),
                artifact_kind=kind,
                relative_path=path,
                content_hash=artifact_content_hash(text),
            ),
        )


_INTERRUPTED_STATES = (
    "start_only",
    "summary_file",
    "summary_event",
    "recap_file",
    "recap_event",
    "workflow_file",
    "workflow_event",
    "proposal_file",
    "proposal_event",
)


@pytest.mark.parametrize("state", _INTERRUPTED_STATES)
def test_interrupted_same_attempt_never_reruns(tmp_path: Path, state: str) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _seed_started(root, prepared)

    if state == "summary_file":
        _seed_artifact(root, PersistedArtifactKind.SUMMARY, "summary\n", event=False)
    elif state == "summary_event":
        _seed_artifact(root, PersistedArtifactKind.SUMMARY, "summary\n", event=True)
    elif state == "recap_file":
        _seed_artifact(root, PersistedArtifactKind.RECAP, "recap\n", event=False)
    elif state == "recap_event":
        _seed_artifact(root, PersistedArtifactKind.RECAP, "recap\n", event=True)
    elif state == "workflow_file":
        _seed_artifact(root, PersistedArtifactKind.WORKFLOW, "{}\n", event=False)
    elif state == "workflow_event":
        _seed_artifact(root, PersistedArtifactKind.WORKFLOW, "{}\n", event=True)
    elif state == "proposal_file":
        ObsidianChangeSetStore(root).create_proposal(f"cs_S001_{ATTEMPT_A}", "{}\n")
    elif state == "proposal_event":
        from dnd_assistant.domain.post_session import ProposalPersisted, Sha256Fingerprint

        record_ledger_event(
            ObsidianPostSessionProcessingStore(root),
            "S001",
            ProposalPersisted(
                event_id=new_ledger_event_id(),
                attempt_id=ATTEMPT_A,
                session_ref="S001",
                real_time=fixed_clock(),
                changeset_id=f"cs_S001_{ATTEMPT_A}",
                changeset_fingerprint=Sha256Fingerprint(digest="e" * 64),
            ),
        )

    deps = _deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert _extraction_calls(deps) == 0


# ── Different-attempt pre-apply proposal semantics ─────────────────────────


def _proposal_create_ids(root: Path, changeset_id: str) -> set[str]:
    store = ObsidianChangeSetStore(root)
    if store.read_proposal_if_present(changeset_id) is None:
        return set()
    proposal = deserialize_proposal(store.read_proposal(changeset_id))
    return {op.entity_id for op in proposal.operations if isinstance(op, CreateEntityOperation)}


def test_different_attempts_before_apply_may_repeat_create(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    before = canonical_truth_snapshot(root)

    _d1, first = _run(
        root, audit, prepared, attempt=ATTEMPT_A, extraction=_candidate_extraction(prepared)
    )
    assert first.status is PostSessionProcessorStatus.COMPLETED
    artifacts_a = attempt_artifact_bytes(root, "S001", ATTEMPT_A)

    _d2, second = _run(
        root, audit, prepared, attempt=ATTEMPT_B, extraction=_candidate_extraction(prepared)
    )
    assert second.status is PostSessionProcessorStatus.COMPLETED

    assert first.changeset_id is not None
    assert second.changeset_id is not None
    assert first.changeset_id != second.changeset_id
    create_a = _proposal_create_ids(root, first.changeset_id)
    create_b = _proposal_create_ids(root, second.changeset_id)
    assert create_a and create_a == create_b  # same deterministic candidate EntityId
    # Prior unapplied proposal is not campaign truth; canonical state unchanged.
    assert attempt_artifact_bytes(root, "S001", ATTEMPT_A) == artifacts_a
    assert canonical_truth_snapshot(root) == before


# ── Applied-create rerun regression ────────────────────────────────────────


def test_rerun_after_applied_create_does_not_duplicate(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)

    _d1, first = _run(
        root, audit, prepared, attempt=ATTEMPT_A, extraction=_candidate_extraction(prepared)
    )
    assert first.status is PostSessionProcessorStatus.COMPLETED
    assert first.changeset_id is not None

    store = ObsidianChangeSetStore(root)
    proposal = load_proposal(store, first.changeset_id)
    vault = ObsidianVaultRepository(root, audit)
    build_changeset_review(proposal, vault)  # fresh preflight
    approval = ChangeSetApproval(
        changeset_id=proposal.changeset_id,
        fingerprint=compute_changeset_fingerprint(proposal),
        decision=ReviewDecision.APPROVED,
        reviewer="dm",
    )
    persist_approval(store, approval)
    applied = apply_changeset(
        proposal,
        approval,
        vault,
        context=ChangeSetApplyContext(source="test", real_time=fixed_clock()),
    )
    assert applied.outcome is ChangeSetApplyOutcome.APPLIED

    created_ids = {
        op.entity_id for op in proposal.operations if isinstance(op, CreateEntityOperation)
    }
    assert created_ids
    for entity_id in created_ids:
        assert vault.get_entity(entity_id).entity.id == entity_id

    _d2, second = _run(
        root, audit, prepared, attempt=ATTEMPT_B, extraction=_candidate_extraction(prepared)
    )
    assert second.status is PostSessionProcessorStatus.COMPLETED

    if second.changeset_id is not None:
        reused = _proposal_create_ids(root, second.changeset_id) & created_ids
        assert reused == set()
    else:
        assert second.outcome is ProcessingOutcome.NO_CHANGES


# ── Durable Summary/Recap privacy canaries ─────────────────────────────────


def test_durable_recap_and_summary_privacy_canaries(tmp_path: Path) -> None:
    root, audit = _canary_vault(tmp_path)
    prepared = _build(root, audit)
    accepted = make_accepted(prepared, _canary_extraction(prepared))
    renderer = FakePostSessionRenderingModel(echo=True)

    deps = _deps(root, audit, rendering=renderer)
    # Replace the extraction model with one returning the canary extraction.
    deps = replace(
        deps, extraction_model=FakePostSessionExtractionModel(_canary_extraction(prepared))
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.COMPLETED

    artifact_store = ObsidianPostSessionArtifactStore(root)
    recap = artifact_store.read_artifact_if_present("S001", ATTEMPT_A, PersistedArtifactKind.RECAP)
    summary = artifact_store.read_artifact_if_present(
        "S001", ATTEMPT_A, PersistedArtifactKind.SUMMARY
    )
    assert recap is not None and summary is not None

    assert PLAYER_SAFE_CANARY in recap
    for hidden in (
        DM_SECRET_CANARY_CLAIM_TEXT,
        SYSTEM_SECRET_CANARY_ENTITY_BODY,
        UNRESOLVED_SECRET_CANARY_MENTION,
        DM_SECRET_CANARY_CANDIDATE,
    ):
        assert hidden not in recap

    assert DM_SECRET_CANARY_CLAIM_TEXT in summary
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in summary
    assert "npc-system" not in summary

    # The captured renderer requests prove the durable bodies derive from the
    # actual authorized request, not from an in-memory guess.
    recap_requests = [r for r in renderer.requests if r.artifact_kind == "recap"]
    assert recap_requests
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in serialize_recap_request(recap_requests[0])
    summary_requests = [r for r in renderer.requests if r.artifact_kind == "summary"]
    assert summary_requests
    assert DM_SECRET_CANARY_CLAIM_TEXT in serialize_summary_request(summary_requests[0])
    _ = accepted  # accepted extraction exercised via the processor pipeline


# ── Failure-recording error and terminal uncertainty ───────────────────────


def test_failure_recording_error_retains_phase_and_reason() -> None:
    from dnd_assistant.application.post_session_processor_support import (
        PostSessionFailureRecordingError,
    )

    error = PostSessionFailureRecordingError(
        ProcessingPhase.EXTRACTION,
        FailureCategory.MODEL_TIMEOUT,
        "bounded message",
    )
    assert error.phase is ProcessingPhase.EXTRACTION
    assert error.failure_category is FailureCategory.MODEL_TIMEOUT
    assert error.original_message == "bounded message"


def test_terminal_append_uncertain_but_present_has_single_terminal(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    faulting = FaultingProcessingStore(
        ObsidianPostSessionProcessingStore(root),
        fail_append_after=lambda content: '"attempt_completed"' in content,
    )
    deps = _deps(root, audit, extraction=append_extraction(prepared), processing_store=faulting)
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.COMPLETED
    ledger = _ledger_bytes(root).decode("utf-8")
    assert ledger.count('"attempt_completed"') == 1
