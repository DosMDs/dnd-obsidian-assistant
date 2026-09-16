"""S11-06 durable post-session processor integration tests (real Vault).

Proves durable terminal idempotency, current-input binding, interrupted/orphan
claim semantics, immutable artifact persistence, terminal integrity failures,
crash windows, terminal-append uncertainty and zero canonical mutation.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    fold_attempt_state,
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
from dnd_assistant.domain.post_session import (
    ArtifactPersisted,
    AttemptCompleted,
    AttemptStarted,
    PersistedArtifactKind,
    ProcessingOutcome,
)
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from tests.integration.post_session_processor_helpers import (
    ATTEMPT_A,
    ATTEMPT_B,
    append_extraction,
    build_deps,
    fixed_clock,
)
from tests.integration.test_post_session_context import _build, _build_vault

_ENTITY_DIRS = ("Characters", "Locations", "Quests", "Items")


def _extraction_calls(deps: PostSessionProcessorDeps) -> int:
    return len(getattr(deps.extraction_model, "requests", []))


def _rendering_calls(deps: PostSessionProcessorDeps) -> int:
    return len(getattr(deps.rendering_model, "requests", []))


def _canonical_snapshot(root: Path) -> dict[str, bytes]:
    """Entity files + session metadata only (excludes workflow artifacts)."""
    result: dict[str, bytes] = {}
    for base in _ENTITY_DIRS:
        directory = root / base
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    result[path.relative_to(root).as_posix()] = path.read_bytes()
    meta = root / "_system" / "raw" / "sessions" / "S001" / "metadata.json"
    result["metadata.json"] = meta.read_bytes()
    return result


def _run(root, audit, prepared, attempt: str = ATTEMPT_A):
    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    return deps, run_post_session_processing(deps, "S001", attempt, clock=fixed_clock)


def test_first_run_produces_immutable_artifacts_and_terminal(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    deps, result = _run(root, audit, prepared)

    assert result.status is PostSessionProcessorStatus.COMPLETED
    assert result.outcome is ProcessingOutcome.PRODUCED
    assert result.changeset_id == f"cs_S001_{ATTEMPT_A}"
    assert result.summary_path and result.recap_path and result.workflow_path

    artifact_store = ObsidianPostSessionArtifactStore(root)
    assert artifact_store.read_artifact_if_present("S001", ATTEMPT_A, PersistedArtifactKind.SUMMARY)
    # S11-04 recap is EMPTY (no player-hinted claims) -> durable placeholder.
    assert result.recap_was_empty is True

    fold = fold_attempt_state(load_ledger_events(deps.processing_store, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.COMPLETED
    assert fold.proposal is not None


def test_no_changes_creates_no_proposal_but_keeps_artifacts(tmp_path: Path) -> None:
    from tests.unit.post_session.extraction_helpers import make_extraction

    root, audit, _ = _build_vault(tmp_path)
    deps = build_deps(root, audit, extraction=make_extraction())
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.COMPLETED
    assert result.outcome is ProcessingOutcome.NO_CHANGES
    assert result.changeset_id is None
    assert not (root / "_system" / "changesets").exists()
    artifact_store = ObsidianPostSessionArtifactStore(root)
    for kind in PersistedArtifactKind:
        assert artifact_store.artifact_exists("S001", ATTEMPT_A, kind)


def test_terminal_same_attempt_is_idempotent_with_zero_model_calls(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _deps1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    store = ObsidianPostSessionProcessingStore(root)
    ledger_before = store.read_ledger_if_present("S001")
    snapshot_before = _canonical_snapshot(root)

    deps2 = build_deps(root, audit, extraction=append_extraction(prepared))
    second = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)

    assert second.status is PostSessionProcessorStatus.ALREADY_TERMINAL
    assert second.changeset_id == first.changeset_id
    assert _extraction_calls(deps2) == 0
    assert _rendering_calls(deps2) == 0
    assert store.read_ledger_if_present("S001") == ledger_before
    assert _canonical_snapshot(root) == snapshot_before


def test_terminal_changed_input_cannot_reuse_attempt(tmp_path: Path) -> None:
    from dnd_assistant.storage.audit import AuditContext
    from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

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
    store = ObsidianPostSessionProcessingStore(root)
    ledger_before = store.read_ledger_if_present("S001")

    deps2 = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps2, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "fingerprint_mismatch"
    assert _extraction_calls(deps2) == 0
    assert store.read_ledger_if_present("S001") == ledger_before


def test_interrupted_attempt_never_reruns_model(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    store = ObsidianPostSessionProcessingStore(root)
    artifact_store = ObsidianPostSessionArtifactStore(root)
    assert artifact_store.claim_attempt("S001", ATTEMPT_A) is True
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
    before = store.read_ledger_if_present("S001")

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert result.reason == "attempt_interrupted"
    assert _extraction_calls(deps) == 0
    assert store.read_ledger_if_present("S001") == before


def test_orphan_claim_without_start_is_uncertain(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    artifact_store = ObsidianPostSessionArtifactStore(root)
    assert artifact_store.claim_attempt("S001", ATTEMPT_A) is True

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert result.reason == "attempt_claim_exists"
    assert _extraction_calls(deps) == 0


def test_new_attempt_over_same_input_is_allowed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _d1, first = _run(root, audit, prepared, ATTEMPT_A)
    _d2, second = _run(root, audit, prepared, ATTEMPT_B)

    assert first.status is PostSessionProcessorStatus.COMPLETED
    assert second.status is PostSessionProcessorStatus.COMPLETED
    assert first.changeset_id != second.changeset_id
    artifact_store = ObsidianPostSessionArtifactStore(root)
    assert artifact_store.artifact_exists("S001", ATTEMPT_A, PersistedArtifactKind.SUMMARY)
    assert artifact_store.artifact_exists("S001", ATTEMPT_B, PersistedArtifactKind.SUMMARY)


def test_terminal_retry_missing_artifact_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _d1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    artifact_store = ObsidianPostSessionArtifactStore(root)
    summary = artifact_store.expected_relative_path(
        "S001", ATTEMPT_A, PersistedArtifactKind.SUMMARY
    )
    (root / summary).unlink()

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "terminal_evidence:artifact_missing"
    assert _extraction_calls(deps) == 0


def test_terminal_retry_tampered_artifact_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _d1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    artifact_store = ObsidianPostSessionArtifactStore(root)
    recap = artifact_store.expected_relative_path("S001", ATTEMPT_A, PersistedArtifactKind.RECAP)
    (root / recap).write_bytes(b"tampered\n")

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "terminal_evidence:artifact_hash_mismatch"


def test_terminal_retry_missing_proposal_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    _d1, first = _run(root, audit, prepared)
    assert first.status is PostSessionProcessorStatus.COMPLETED

    proposal = root / "_system" / "changesets" / f"{first.changeset_id}.proposal.json"
    proposal.unlink()

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "terminal_evidence:proposal_missing"


def test_legacy_completed_ledger_is_not_reclassified_as_corrupt(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    store = ObsidianPostSessionProcessingStore(root)
    ObsidianPostSessionArtifactStore(root).claim_attempt("S001", ATTEMPT_A)
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
    record_ledger_event(
        store,
        "S001",
        AttemptCompleted(
            event_id=new_ledger_event_id(),
            attempt_id=ATTEMPT_A,
            session_ref="S001",
            real_time=fixed_clock(),
            outcome=ProcessingOutcome.NO_CHANGES,
        ),
    )

    fold = fold_attempt_state(load_ledger_events(store, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.COMPLETED  # structurally complete

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "terminal_evidence:terminal_evidence_incomplete"


def test_crash_after_start_before_artifacts_is_interrupted(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    store = ObsidianPostSessionProcessingStore(root)
    ObsidianPostSessionArtifactStore(root).claim_attempt("S001", ATTEMPT_A)
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
    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.INTERRUPTED


def test_crash_after_summary_event_before_terminal_is_interrupted(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
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
    _outcome, path = persist_immutable_artifact(
        artifact_store, "S001", ATTEMPT_A, PersistedArtifactKind.SUMMARY, "summary\n"
    )
    record_ledger_event(
        store,
        "S001",
        ArtifactPersisted(
            event_id=new_ledger_event_id(),
            attempt_id=ATTEMPT_A,
            session_ref="S001",
            real_time=fixed_clock(),
            artifact_kind=PersistedArtifactKind.SUMMARY,
            relative_path=path,
            content_hash=artifact_content_hash("summary\n"),
        ),
    )

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)
    assert result.status is PostSessionProcessorStatus.INTERRUPTED
    assert _extraction_calls(deps) == 0


def test_processing_leaves_canonical_entities_and_audit_unchanged(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    canonical_before = _canonical_snapshot(root)
    audit_before = audit.read_all()

    deps, result = _run(root, audit, prepared)
    assert result.status is PostSessionProcessorStatus.COMPLETED

    assert _canonical_snapshot(root) == canonical_before
    assert audit.read_all() == audit_before
