"""S11-06 processor result contracts and durable-state helpers.

Holds the typed processor result/status/dependency contracts and the bounded
helpers used by the orchestrator to:

- reconstruct a terminal result from durable evidence (no model calls);
- record one bounded ``AttemptFailed`` (or raise when that cannot be recorded);
- append artifact/proposal/terminal ledger events with uncertainty handling.

It contains no orchestration policy.  It is application-owned, provider-neutral
and depends on no concrete storage implementation (storage protocols are
referenced only under ``TYPE_CHECKING``).

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, or a
    concrete storage implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.post_session_attempt_state import AttemptStateFold
from dnd_assistant.application.post_session_ledger import (
    load_ledger_events,
    new_ledger_event_id,
    record_ledger_event,
    serialize_ledger_event,
)
from dnd_assistant.domain.post_session import (
    ArtifactPersisted,
    AttemptCompleted,
    AttemptFailed,
    FailureCategory,
    PersistedArtifactKind,
    ProcessingOutcome,
    ProcessingPhase,
    Sha256Fingerprint,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome
from dnd_assistant.errors import ConflictError, DndAssistantError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.application.post_session_clock import PostSessionClock
    from dnd_assistant.application.post_session_extraction import (
        PostSessionExtractionModel,
    )
    from dnd_assistant.application.post_session_rendering import (
        PostSessionRenderingModel,
    )
    from dnd_assistant.storage.changeset_store import ChangeSetStore
    from dnd_assistant.storage.post_session_artifacts import PostSessionArtifactStore
    from dnd_assistant.storage.post_session_processing import (
        PostSessionProcessingStore,
    )
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
        VaultRepository,
    )

# Re-exported for the orchestrator's convenience.
__all__ = [
    "PostSessionFailureRecordingError",
    "PostSessionProcessorDeps",
    "PostSessionProcessorResult",
    "PostSessionProcessorStatus",
    "append_artifact_event",
    "append_terminal",
    "failed_result",
    "interrupted_result",
    "record_failure",
    "result_from_terminal",
]


# ── Result and errors ─────────────────────────────────────────────────────


class PostSessionProcessorStatus(StrEnum):
    """Bounded orchestration status surfaced to the (future) CLI."""

    COMPLETED = "completed"
    ALREADY_TERMINAL = "already_terminal"
    INTERRUPTED = "interrupted"
    INELIGIBLE = "ineligible"
    FAILED = "failed"


@dataclass(frozen=True)
class PostSessionProcessorResult:
    """Typed, filesystem-authority-free processing result for S11-07."""

    status: PostSessionProcessorStatus
    session_id: str
    attempt_id: str
    input_fingerprint: Sha256Fingerprint | None = None
    outcome: ProcessingOutcome | None = None
    summary_path: str | None = None
    recap_path: str | None = None
    workflow_path: str | None = None
    recap_was_empty: bool = False
    changeset_id: str | None = None
    changeset_fingerprint: Sha256Fingerprint | None = None
    unresolved_count: int = 0
    phase: ProcessingPhase | None = None
    failure_category: FailureCategory | None = None
    failure_recorded: bool = False
    reason: str | None = None


class PostSessionFailureRecordingError(DndAssistantError):
    """Raised when a post-start failure could not be durably recorded.

    The attempt remains ``STARTED`` (interrupted/uncertain) in the ledger; the
    original failure is preserved as context.  A terminal failure is never
    claimed.
    """

    def __init__(
        self,
        phase: ProcessingPhase,
        failure_category: FailureCategory,
        original_message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            f"Post-session processing failed during {phase.value} and the failure "
            f"could not be durably recorded",
            cause=cause,
        )
        self.phase = phase
        self.failure_category = failure_category
        self.original_message = original_message


@dataclass(frozen=True)
class PostSessionProcessorDeps:
    """Injected dependencies for one processor instance."""

    metadata_repo: SessionMetadataRepository
    event_repo: SessionEventRepository
    vault_repo: VaultRepository
    processing_store: PostSessionProcessingStore
    artifact_store: PostSessionArtifactStore
    changeset_store: ChangeSetStore
    extraction_model: PostSessionExtractionModel
    rendering_model: PostSessionRenderingModel


# ── Result builders ───────────────────────────────────────────────────────


def failed_result(
    session_id: str,
    attempt_id: str,
    reason: str,
    *,
    phase: ProcessingPhase | None = None,
    category: FailureCategory | None = None,
    input_fingerprint: Sha256Fingerprint | None = None,
    failure_recorded: bool = False,
) -> PostSessionProcessorResult:
    return PostSessionProcessorResult(
        status=PostSessionProcessorStatus.FAILED,
        session_id=session_id,
        attempt_id=attempt_id,
        input_fingerprint=input_fingerprint,
        phase=phase,
        failure_category=category,
        failure_recorded=failure_recorded,
        reason=reason,
    )


def interrupted_result(
    session_id: str,
    attempt_id: str,
    reason: str,
    input_fingerprint: Sha256Fingerprint | None = None,
) -> PostSessionProcessorResult:
    return PostSessionProcessorResult(
        status=PostSessionProcessorStatus.INTERRUPTED,
        session_id=session_id,
        attempt_id=attempt_id,
        input_fingerprint=input_fingerprint,
        reason=reason,
    )


def _sha(fingerprint: object) -> Sha256Fingerprint | None:
    if fingerprint is None:
        return None
    digest = getattr(fingerprint, "digest", None)
    if not isinstance(digest, str):
        return None
    return Sha256Fingerprint(digest=digest)


# ── Terminal reconstruction ───────────────────────────────────────────────


def result_from_terminal(
    fold: AttemptStateFold,
    session_id: str,
    status: PostSessionProcessorStatus,
    *,
    artifact_store: PostSessionArtifactStore,
) -> PostSessionProcessorResult:
    """Reconstruct a terminal result from durable evidence (no model calls)."""
    import json

    from dnd_assistant.domain.post_session_workflow import AttemptWorkflowEvidence

    unresolved_count = 0
    recap_was_empty = False
    outcome: ProcessingOutcome | None = None
    changeset_id: str | None = None
    changeset_fingerprint: Sha256Fingerprint | None = None

    workflow_text = artifact_store.read_artifact_if_present(
        session_id, fold.attempt_id, PersistedArtifactKind.WORKFLOW
    )
    if workflow_text is not None:
        try:
            evidence = AttemptWorkflowEvidence.model_validate(json.loads(workflow_text))
        except (ValueError, TypeError):
            evidence = None
        if evidence is not None:
            unresolved_count = len(evidence.change_plan.unresolved)
            recap_was_empty = evidence.recap.outcome is RenderOutcome.EMPTY
            outcome = (
                ProcessingOutcome.PRODUCED
                if evidence.change_plan.produced
                else ProcessingOutcome.NO_CHANGES
            )
            changeset_id = evidence.change_plan.changeset_id
            changeset_fingerprint = _sha(evidence.change_plan.changeset_fingerprint)

    if fold.proposal is not None:
        changeset_id = fold.proposal.changeset_id
        changeset_fingerprint = _sha(fold.proposal.changeset_fingerprint)

    def _path(kind: PersistedArtifactKind) -> str | None:
        event = fold.artifacts.get(kind)
        return event.relative_path if event is not None else None

    terminal = fold.terminal
    phase: ProcessingPhase | None = None
    category: FailureCategory | None = None
    failure_recorded = False
    if isinstance(terminal, AttemptFailed):
        phase = terminal.phase
        category = terminal.failure_category
        failure_recorded = True

    return PostSessionProcessorResult(
        status=status,
        session_id=session_id,
        attempt_id=fold.attempt_id,
        input_fingerprint=(fold.started.input_fingerprint if fold.started is not None else None),
        outcome=outcome,
        summary_path=_path(PersistedArtifactKind.SUMMARY),
        recap_path=_path(PersistedArtifactKind.RECAP),
        workflow_path=_path(PersistedArtifactKind.WORKFLOW),
        recap_was_empty=recap_was_empty,
        changeset_id=changeset_id,
        changeset_fingerprint=changeset_fingerprint,
        unresolved_count=unresolved_count,
        phase=phase,
        failure_category=category,
        failure_recorded=failure_recorded,
    )


# ── Durable event helpers ─────────────────────────────────────────────────


def record_failure(
    deps: PostSessionProcessorDeps,
    session_id: str,
    attempt_id: str,
    phase: ProcessingPhase,
    category: FailureCategory,
    message: str,
    clock: PostSessionClock,
) -> PostSessionProcessorResult:
    """Append one bounded AttemptFailed; raise if it cannot be recorded."""
    event = AttemptFailed(
        event_id=new_ledger_event_id(),
        attempt_id=attempt_id,
        session_ref=session_id,
        real_time=clock(),
        phase=phase,
        failure_category=category,
        message=message,
    )
    try:
        record_ledger_event(deps.processing_store, session_id, event)
    except (StorageError, ConflictError) as exc:
        raise PostSessionFailureRecordingError(phase, category, message, cause=exc) from exc
    return failed_result(
        session_id,
        attempt_id,
        message,
        phase=phase,
        category=category,
        failure_recorded=True,
    )


def append_artifact_event(
    deps: PostSessionProcessorDeps,
    session_id: str,
    attempt_id: str,
    kind: PersistedArtifactKind,
    relative_path: str,
    content_hash: Sha256Fingerprint,
    clock: PostSessionClock,
) -> None:
    record_ledger_event(
        deps.processing_store,
        session_id,
        ArtifactPersisted(
            event_id=new_ledger_event_id(),
            attempt_id=attempt_id,
            session_ref=session_id,
            real_time=clock(),
            artifact_kind=kind,
            relative_path=relative_path,
            content_hash=content_hash,
        ),
    )


def append_terminal(
    deps: PostSessionProcessorDeps,
    session_id: str,
    event: AttemptCompleted,
) -> bool:
    """Append the terminal event, tolerating an uncertain filesystem result.

    Returns ``True`` only when the exact logical terminal event is proven
    present; otherwise ``False`` (the attempt remains interrupted).
    """
    try:
        record_ledger_event(deps.processing_store, session_id, event)
        return True
    except ConflictError:
        return False
    except StorageError:
        try:
            events = load_ledger_events(deps.processing_store, session_id)
        except StorageError:
            return False
        expected = serialize_ledger_event(event)
        return any(
            candidate.event_id == event.event_id and serialize_ledger_event(candidate) == expected
            for candidate in events
        )
