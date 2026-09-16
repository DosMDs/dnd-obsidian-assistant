"""S11-06 processor failure/uncertainty integration tests (real Vault).

Proves typed durable failure wording (no raw exception text/secret leakage),
the failure-category/phase map, artifact/proposal conflict mapping, terminal
append uncertainty, and failure-recording-failure semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.application.changeset_store import serialize_proposal
from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    PostSessionExtractionError,
)
from dnd_assistant.application.post_session_ledger import load_ledger_events
from dnd_assistant.application.post_session_processor import (
    PostSessionFailureRecordingError,
    PostSessionProcessorDeps,
    PostSessionProcessorStatus,
    run_post_session_processing,
)
from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RenderingFailureReason,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    ProposalProvenance,
)
from dnd_assistant.domain.post_session import FailureCategory, PersistedArtifactKind
from dnd_assistant.domain.types import Provenance
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from tests.integration.post_session_processor_helpers import (
    ATTEMPT_A,
    append_extraction,
    build_deps,
    fixed_clock,
)
from tests.integration.test_post_session_context import _build, _build_vault

_SECRETS = (
    "SECRET_MODEL_OUTPUT",
    "/private/local/path",
    "C:\\private\\local\\path",
    "line1\nline2",
)


class FaultyProcessingStore:
    """Delegating processing store that injects failures at chosen boundaries."""

    def __init__(
        self,
        real: ObsidianPostSessionProcessingStore,
        *,
        fail_failed: bool = False,
        fail_completed: bool = False,
        fail_completed_written: bool = False,
        fail_artifact: bool = False,
    ) -> None:
        self._real = real
        self._fail_failed = fail_failed
        self._fail_completed = fail_completed
        self._fail_completed_written = fail_completed_written
        self._fail_artifact = fail_artifact

    def append_ledger_line(self, session_id: str, content: str) -> None:
        if self._fail_artifact and '"event_kind":"artifact_persisted"' in content:
            raise StorageError("injected artifact persistence failure")
        if self._fail_failed and '"event_kind":"attempt_failed"' in content:
            raise StorageError("injected failure-recording failure")
        if '"event_kind":"attempt_completed"' in content:
            if self._fail_completed:
                raise StorageError("injected uncertain completed")
            if self._fail_completed_written:
                self._real.append_ledger_line(session_id, content)
                raise StorageError("injected uncertain completed after write")
        self._real.append_ledger_line(session_id, content)

    def read_ledger_if_present(self, session_id: str) -> str | None:
        return self._real.read_ledger_if_present(session_id)

    def ledger_exists(self, session_id: str) -> bool:
        return self._real.ledger_exists(session_id)


class ConflictingArtifactStore:
    """Artifact store that reports a conflict for the Summary slot."""

    def __init__(self, real: ObsidianPostSessionArtifactStore) -> None:
        self._real = real

    def claim_attempt(self, session_id: str, attempt_id: str) -> bool:
        return self._real.claim_attempt(session_id, attempt_id)

    def persist_artifact(
        self, session_id: str, attempt_id: str, artifact_kind: PersistedArtifactKind, text: str
    ):
        if artifact_kind is PersistedArtifactKind.SUMMARY:
            raise ConflictError("injected artifact conflict")
        return self._real.persist_artifact(session_id, attempt_id, artifact_kind, text)

    def read_artifact_if_present(self, session_id: str, attempt_id: str, artifact_kind):
        return self._real.read_artifact_if_present(session_id, attempt_id, artifact_kind)

    def artifact_exists(self, session_id: str, attempt_id: str, artifact_kind) -> bool:
        return self._real.artifact_exists(session_id, attempt_id, artifact_kind)

    def expected_relative_path(self, session_id: str, attempt_id: str, artifact_kind) -> str:
        return self._real.expected_relative_path(session_id, attempt_id, artifact_kind)


def _ledger_text(root: Path) -> str:
    store = ObsidianPostSessionProcessingStore(root)
    return store.read_ledger_if_present("S001") or ""


def test_extraction_failure_is_typed_and_secret_free(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)
    error = PostSessionExtractionError(
        ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT,
        "boom: " + " | ".join(_SECRETS),
    )
    deps = build_deps(root, audit, extraction_error=error)
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.failure_recorded is True
    assert result.phase is not None and result.phase.value == "extraction"
    assert result.failure_category is FailureCategory.INVALID_OUTPUT

    ledger = _ledger_text(root)
    assert "Post-session extraction failed: invalid_structured_output" in ledger
    for secret in _SECRETS:
        assert secret not in ledger


def test_rendering_timeout_maps_to_model_timeout(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    deps = build_deps(
        root,
        audit,
        extraction=append_extraction(prepared),
        render_error=PostSessionRenderingError(
            RenderingFailureReason.MODEL_TIMEOUT, "timeout " + _SECRETS[0]
        ),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.failure_category is FailureCategory.MODEL_TIMEOUT
    assert "Post-session rendering failed: model_timeout" in _ledger_text(root)
    assert _SECRETS[0] not in _ledger_text(root)


def test_unexpected_rendering_error_is_internal_and_secret_free(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    deps = build_deps(
        root,
        audit,
        extraction=append_extraction(prepared),
        render_error=RuntimeError("boom " + " | ".join(_SECRETS)),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.failure_category is FailureCategory.INTERNAL_ERROR
    ledger = _ledger_text(root)
    assert "Internal processing error" in ledger
    for secret in _SECRETS:
        assert secret not in ledger


def test_artifact_conflict_maps_to_artifact_conflict(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    real = ObsidianPostSessionArtifactStore(root)
    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    deps = PostSessionProcessorDeps(
        metadata_repo=deps.metadata_repo,
        event_repo=deps.event_repo,
        vault_repo=deps.vault_repo,
        processing_store=deps.processing_store,
        artifact_store=ConflictingArtifactStore(real),
        changeset_store=deps.changeset_store,
        extraction_model=deps.extraction_model,
        rendering_model=deps.rendering_model,
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.failure_category is FailureCategory.ARTIFACT_CONFLICT
    assert "Artifact persistence failed" in _ledger_text(root)


def test_proposal_conflict_maps_to_proposal_conflict(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    changeset = ChangeSet(
        changeset_id=f"cs_S001_{ATTEMPT_A}",
        provenance=ProposalProvenance(provenance=Provenance.MODEL_INFERENCE),
        session_ref="S001",
        operations=(
            AppendFactOperation(entity_id="npc-aria", expected_revision=1, fact="a different fact"),
        ),
    )
    ObsidianChangeSetStore(root).create_proposal(
        changeset.changeset_id, serialize_proposal(changeset)
    )

    deps = build_deps(root, audit, extraction=append_extraction(prepared))
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.failure_category is FailureCategory.PROPOSAL_CONFLICT
    assert "ChangeSet proposal conflict" in _ledger_text(root)


def test_persistence_storage_failure_maps_to_storage_error(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    real = ObsidianPostSessionProcessingStore(root)
    deps = build_deps(
        root,
        audit,
        extraction=append_extraction(prepared),
        processing_store=FaultyProcessingStore(real, fail_artifact=True),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.failure_category is FailureCategory.STORAGE_ERROR
    assert "Processing storage failure" in _ledger_text(root)


def test_failure_recording_failure_never_claims_terminal(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    _build(root, audit)
    error = PostSessionExtractionError(ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT, "boom")
    real = ObsidianPostSessionProcessingStore(root)
    deps = build_deps(
        root,
        audit,
        extraction_error=error,
        processing_store=FaultyProcessingStore(real, fail_failed=True),
    )
    with pytest.raises(PostSessionFailureRecordingError):
        run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    fold = fold_attempt_state(load_ledger_events(real, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.STARTED
    assert fold.terminal is None


def test_terminal_append_uncertain_but_present_returns_completed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    real = ObsidianPostSessionProcessingStore(root)
    deps = build_deps(
        root,
        audit,
        extraction=append_extraction(prepared),
        processing_store=FaultyProcessingStore(real, fail_completed_written=True),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.COMPLETED
    fold = fold_attempt_state(load_ledger_events(real, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.COMPLETED


def test_terminal_append_uncertain_and_absent_fails_closed(tmp_path: Path) -> None:
    root, audit, _ = _build_vault(tmp_path)
    prepared = _build(root, audit)
    real = ObsidianPostSessionProcessingStore(root)
    deps = build_deps(
        root,
        audit,
        extraction=append_extraction(prepared),
        processing_store=FaultyProcessingStore(real, fail_completed=True),
    )
    result = run_post_session_processing(deps, "S001", ATTEMPT_A, clock=fixed_clock)

    assert result.status is PostSessionProcessorStatus.FAILED
    assert result.reason == "terminal_append_uncertain"
    fold = fold_attempt_state(load_ledger_events(real, "S001"), ATTEMPT_A)
    assert fold.state is AttemptState.STARTED
