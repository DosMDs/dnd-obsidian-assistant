"""S11-06 structural attempt-state fold over the append-only processing ledger.

The ledger remains the **sole** Stage-11 processing-state authority.  This
module reconstructs a bounded, deterministic view of one attempt from its
logical ledger events and fails closed on any structural contradiction.

Scope separation (accepted S11-06 correction):

- this fold owns **structural / event-sequence invariants only** (event order,
  cardinality, identity consistency);
- S11-06 *artifact/proposal inventory, existence and hash completeness* is
  **not** enforced here; it lives in the terminal integrity verifier
  (``application.post_session_integrity``).

Consequently a legacy completed ledger that predates S11-06 artifacts still
folds to ``COMPLETED`` and is never reclassified as a malformed ledger.  Old
ledger lines are never rewritten or migrated.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval, or a concrete
    storage implementation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from dnd_assistant.domain.post_session import (
    ArtifactPersisted,
    AttemptCompleted,
    AttemptFailed,
    AttemptStarted,
    AttemptSuperseded,
    PersistedArtifactKind,
    PostSessionAttemptId,
    ProcessingLedgerEvent,
    ProposalPersisted,
)
from dnd_assistant.errors import DndAssistantError

_TERMINAL_KINDS: frozenset[str] = frozenset(
    {"attempt_completed", "attempt_failed", "attempt_superseded"}
)


class AttemptState(StrEnum):
    """Bounded state of one processing attempt."""

    NOT_STARTED = "not_started"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class AttemptStateConflictReason(StrEnum):
    """Bounded, stable reason a ledger fold is structurally contradictory."""

    EVENT_BEFORE_START = "event_before_start"
    MULTIPLE_STARTED = "multiple_started"
    DUPLICATE_ARTIFACT_SLOT = "duplicate_artifact_slot"
    MULTIPLE_PROPOSAL_EVENTS = "multiple_proposal_events"
    MULTIPLE_TERMINAL = "multiple_terminal"
    EVENT_AFTER_TERMINAL = "event_after_terminal"
    SESSION_REF_MISMATCH = "session_ref_mismatch"


class AttemptStateConflictError(DndAssistantError):
    """Raised when an attempt's ledger history is structurally contradictory."""

    def __init__(
        self,
        reason: AttemptStateConflictReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason


@dataclass(frozen=True)
class AttemptStateFold:
    """Deterministic structural view of one attempt's ledger history."""

    attempt_id: str
    state: AttemptState
    started: AttemptStarted | None = None
    artifacts: Mapping[PersistedArtifactKind, ArtifactPersisted] = field(default_factory=dict)
    proposal: ProposalPersisted | None = None
    terminal: AttemptCompleted | AttemptFailed | AttemptSuperseded | None = None

    @property
    def artifact_kinds(self) -> frozenset[PersistedArtifactKind]:
        """The persisted artifact slots present in the ledger."""
        return frozenset(self.artifacts)


def fold_attempt_state(
    events: Sequence[ProcessingLedgerEvent],
    attempt_id: PostSessionAttemptId | str,
) -> AttemptStateFold:
    """Fold the ledger events for ``attempt_id`` into a bounded state.

    Events belonging to other attempts are ignored.  A structurally
    contradictory history raises :class:`AttemptStateConflictError`.  Physical
    duplicate lines with the same ``event_id``/canonical payload are already
    folded by the ledger parser and are not re-examined here.
    """
    relevant = [event for event in events if event.attempt_id == attempt_id]
    if not relevant:
        return AttemptStateFold(attempt_id=attempt_id, state=AttemptState.NOT_STARTED)

    if relevant[0].event_kind != "attempt_started":
        raise AttemptStateConflictError(
            AttemptStateConflictReason.EVENT_BEFORE_START,
            f"Attempt {attempt_id!r} has an event before attempt_started",
        )

    started = relevant[0]
    assert isinstance(started, AttemptStarted)

    artifacts: dict[PersistedArtifactKind, ArtifactPersisted] = {}
    proposal: ProposalPersisted | None = None
    terminal: AttemptCompleted | AttemptFailed | AttemptSuperseded | None = None

    for index, event in enumerate(relevant):
        if index > 0 and isinstance(event, AttemptStarted):
            raise AttemptStateConflictError(
                AttemptStateConflictReason.MULTIPLE_STARTED,
                f"Attempt {attempt_id!r} has multiple distinct attempt_started events",
            )

        if event.session_ref != started.session_ref:
            raise AttemptStateConflictError(
                AttemptStateConflictReason.SESSION_REF_MISMATCH,
                f"Attempt {attempt_id!r} has a session_ref inconsistent with attempt_started",
            )

        if terminal is not None and event.event_kind not in _TERMINAL_KINDS:
            raise AttemptStateConflictError(
                AttemptStateConflictReason.EVENT_AFTER_TERMINAL,
                f"Attempt {attempt_id!r} has an event after its terminal event",
            )

        if isinstance(event, ArtifactPersisted):
            if event.artifact_kind in artifacts:
                raise AttemptStateConflictError(
                    AttemptStateConflictReason.DUPLICATE_ARTIFACT_SLOT,
                    f"Attempt {attempt_id!r} has multiple artifact_persisted events for "
                    f"{event.artifact_kind.value!r}",
                )
            artifacts[event.artifact_kind] = event
        elif isinstance(event, ProposalPersisted):
            if proposal is not None:
                raise AttemptStateConflictError(
                    AttemptStateConflictReason.MULTIPLE_PROPOSAL_EVENTS,
                    f"Attempt {attempt_id!r} has multiple proposal_persisted events",
                )
            proposal = event
        elif isinstance(event, (AttemptCompleted, AttemptFailed, AttemptSuperseded)):
            if terminal is not None:
                raise AttemptStateConflictError(
                    AttemptStateConflictReason.MULTIPLE_TERMINAL,
                    f"Attempt {attempt_id!r} has multiple terminal events",
                )
            terminal = event
        # Remaining events are AttemptStarted at index 0 (handled above).

    if terminal is None:
        state = AttemptState.STARTED
    elif isinstance(terminal, AttemptCompleted):
        state = AttemptState.COMPLETED
    elif isinstance(terminal, AttemptFailed):
        state = AttemptState.FAILED
    else:
        state = AttemptState.SUPERSEDED

    return AttemptStateFold(
        attempt_id=attempt_id,
        state=state,
        started=started,
        artifacts=artifacts,
        proposal=proposal,
        terminal=terminal,
    )


__all__ = [
    "AttemptState",
    "AttemptStateConflictError",
    "AttemptStateConflictReason",
    "AttemptStateFold",
    "fold_attempt_state",
]
