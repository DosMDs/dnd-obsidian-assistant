"""S11-07 read-only post-session attempt output query service.

Reconstructs a bounded, truthful view of every processing attempt recorded in
the append-only processing ledger.  It is **read-only**: it loads the ledger,
reads immutable artifacts, reads Stage-10 proposals and calls the existing
terminal-integrity verifier.  It writes nothing, mutates nothing and owns no
processing policy of its own.

Structural ``COMPLETED`` is **not** sufficient evidence that outputs are usable.
Only an attempt whose terminal integrity verifies (``verify_terminal_integrity``)
is surfaced as a verified completed output set.  A structurally ``COMPLETED``
attempt with missing/tampered artifacts or a missing/mismatched/orphan proposal
fails closed by raising :class:`PostSessionOutputsError` carrying only the
bounded ``TerminalIntegrityReason``.  Terminal-integrity rules are never
duplicated here; they remain owned by
``application.post_session_integrity``.

The service depends only on the existing storage protocols it needs (processing
ledger, immutable artifacts, Stage-10 proposals).  It references no concrete
storage implementation.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, or a
    concrete storage implementation (storage protocols are referenced only
    under ``TYPE_CHECKING``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    AttemptStateFold,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_integrity import (
    TerminalIntegrityReason,
    verify_terminal_integrity,
)
from dnd_assistant.application.post_session_ledger import load_ledger_events
from dnd_assistant.domain.post_session import (
    AttemptCompleted,
    AttemptFailed,
    FailureCategory,
    PersistedArtifactKind,
    ProcessingOutcome,
    ProcessingPhase,
)
from dnd_assistant.errors import DndAssistantError

if TYPE_CHECKING:
    from dnd_assistant.storage.changeset_store import ChangeSetStore
    from dnd_assistant.storage.post_session_artifacts import PostSessionArtifactStore
    from dnd_assistant.storage.post_session_processing import PostSessionProcessingStore

__all__ = [
    "PostSessionAttemptOutput",
    "PostSessionOutputsError",
    "build_post_session_outputs",
]


class PostSessionOutputsError(DndAssistantError):
    """A structurally terminal attempt failed terminal-integrity verification.

    Carries only the trusted ``attempt_id`` and the bounded
    ``TerminalIntegrityReason``; no artifact body or raw exception detail is
    exposed.
    """

    def __init__(self, attempt_id: str, reason: TerminalIntegrityReason) -> None:
        super().__init__(f"Attempt {attempt_id} terminal evidence is not verified: {reason.value}")
        self.attempt_id = attempt_id
        self.reason = reason


@dataclass(frozen=True)
class PostSessionAttemptOutput:
    """Bounded, read-only projection of one processing attempt.

    ``verified`` is ``True`` only for a structurally ``COMPLETED`` attempt whose
    terminal integrity was verified.  ``failure_phase`` / ``failure_category``
    are populated only from a bounded ``AttemptFailed`` terminal event.
    """

    attempt_id: str
    state: AttemptState
    verified: bool = False
    outcome: ProcessingOutcome | None = None
    summary_path: str | None = None
    recap_path: str | None = None
    workflow_path: str | None = None
    changeset_id: str | None = None
    failure_phase: ProcessingPhase | None = None
    failure_category: FailureCategory | None = None


def _artifact_path(fold: AttemptStateFold, kind: PersistedArtifactKind) -> str | None:
    event = fold.artifacts.get(kind)
    return event.relative_path if event is not None else None


def _summarize_attempt(
    fold: AttemptStateFold,
    session_id: str,
    *,
    artifact_store: PostSessionArtifactStore,
    changeset_store: ChangeSetStore,
) -> PostSessionAttemptOutput:
    if fold.state is AttemptState.COMPLETED:
        integrity = verify_terminal_integrity(
            fold,
            session_id,
            artifact_store=artifact_store,
            changeset_store=changeset_store,
        )
        if not integrity.ok:
            assert integrity.reason is not None
            raise PostSessionOutputsError(fold.attempt_id, integrity.reason)

        terminal = fold.terminal
        outcome = terminal.outcome if isinstance(terminal, AttemptCompleted) else None
        changeset_id = fold.proposal.changeset_id if fold.proposal is not None else None
        return PostSessionAttemptOutput(
            attempt_id=fold.attempt_id,
            state=fold.state,
            verified=True,
            outcome=outcome,
            summary_path=_artifact_path(fold, PersistedArtifactKind.SUMMARY),
            recap_path=_artifact_path(fold, PersistedArtifactKind.RECAP),
            workflow_path=_artifact_path(fold, PersistedArtifactKind.WORKFLOW),
            changeset_id=changeset_id,
        )

    terminal = fold.terminal
    failure_phase = terminal.phase if isinstance(terminal, AttemptFailed) else None
    failure_category = terminal.failure_category if isinstance(terminal, AttemptFailed) else None
    return PostSessionAttemptOutput(
        attempt_id=fold.attempt_id,
        state=fold.state,
        verified=False,
        summary_path=_artifact_path(fold, PersistedArtifactKind.SUMMARY),
        recap_path=_artifact_path(fold, PersistedArtifactKind.RECAP),
        workflow_path=_artifact_path(fold, PersistedArtifactKind.WORKFLOW),
        failure_phase=failure_phase,
        failure_category=failure_category,
    )


def build_post_session_outputs(
    processing_store: PostSessionProcessingStore,
    artifact_store: PostSessionArtifactStore,
    changeset_store: ChangeSetStore,
    session_id: str,
) -> tuple[PostSessionAttemptOutput, ...]:
    """Build the bounded attempt-output view for one session's ledger.

    Attempts are ordered by first appearance in the physical ledger (fold
    order).  A structurally ``COMPLETED`` attempt whose terminal evidence does
    not verify raises :class:`PostSessionOutputsError` (fail closed).

    Raises:
        PostSessionOutputsError: A structurally terminal attempt failed
            terminal-integrity verification.
        StorageError: The ledger or an artifact/proposal is unsafe, unreadable
            or malformed (uncertain durable state fails closed).
        AttemptStateConflictError: The ledger is structurally contradictory.
    """
    events = load_ledger_events(processing_store, session_id)

    ordered: list[str] = []
    seen: set[str] = set()
    for event in events:
        if event.attempt_id not in seen:
            seen.add(event.attempt_id)
            ordered.append(event.attempt_id)

    return tuple(
        _summarize_attempt(
            fold_attempt_state(events, attempt_id),
            session_id,
            artifact_store=artifact_store,
            changeset_store=changeset_store,
        )
        for attempt_id in ordered
    )
