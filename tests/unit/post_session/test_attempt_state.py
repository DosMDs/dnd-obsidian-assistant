"""S11-06 structural attempt-state fold tests (pure, no Vault)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    AttemptStateConflictError,
    AttemptStateConflictReason,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_ledger import (
    parse_ledger_text,
    serialize_ledger_event,
)
from dnd_assistant.domain.post_session import (
    ArtifactPersisted,
    AttemptCompleted,
    AttemptFailed,
    AttemptStarted,
    FailureCategory,
    PersistedArtifactKind,
    ProcessingOutcome,
    ProcessingPhase,
    ProposalPersisted,
    Sha256Fingerprint,
)

_NOW = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)
_ATT = "att_" + "a" * 32
_ATT2 = "att_" + "b" * 32
_FP = Sha256Fingerprint(digest="c" * 64)
_HASH = Sha256Fingerprint(digest="d" * 64)


def _eid(n: int) -> str:
    return "le_" + f"{n:032x}"


def _started(*, event_id: str = _eid(1), attempt_id: str = _ATT, session: str = "S001"):
    return AttemptStarted(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref=session,
        real_time=_NOW,
        input_fingerprint=_FP,
        processor_version="2",
        prompt_version="post-session-extraction-v1",
    )


def _artifact(
    kind: PersistedArtifactKind,
    *,
    event_id: str = _eid(2),
    attempt_id: str = _ATT,
    session: str = "S001",
    path: str = "a/summary.md",
):
    return ArtifactPersisted(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref=session,
        real_time=_NOW,
        artifact_kind=kind,
        relative_path=path,
        content_hash=_HASH,
    )


def _proposal(*, event_id: str = _eid(3), attempt_id: str = _ATT, session: str = "S001"):
    return ProposalPersisted(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref=session,
        real_time=_NOW,
        changeset_id="cs_S001_" + attempt_id,
        changeset_fingerprint=_HASH,
    )


def _completed(
    *,
    event_id: str = _eid(9),
    attempt_id: str = _ATT,
    session: str = "S001",
    outcome: ProcessingOutcome = ProcessingOutcome.PRODUCED,
):
    return AttemptCompleted(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref=session,
        real_time=_NOW,
        outcome=outcome,
    )


def _failed(*, event_id: str = _eid(8), attempt_id: str = _ATT, session: str = "S001"):
    return AttemptFailed(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref=session,
        real_time=_NOW,
        phase=ProcessingPhase.EXTRACTION,
        failure_category=FailureCategory.INVALID_OUTPUT,
        message="Post-session extraction failed: invalid_structured_output",
    )


def test_empty_ledger_is_not_started() -> None:
    assert fold_attempt_state((), _ATT).state is AttemptState.NOT_STARTED


def test_only_other_attempts_is_not_started() -> None:
    assert fold_attempt_state((_started(attempt_id=_ATT2),), _ATT).state is AttemptState.NOT_STARTED


def test_single_start_is_started() -> None:
    fold = fold_attempt_state((_started(),), _ATT)
    assert fold.state is AttemptState.STARTED
    assert fold.started is not None
    assert fold.artifact_kinds == frozenset()


def test_completed_is_completed() -> None:
    fold = fold_attempt_state((_started(), _completed()), _ATT)
    assert fold.state is AttemptState.COMPLETED
    assert fold.terminal is not None


def test_failed_is_failed() -> None:
    fold = fold_attempt_state((_started(), _failed()), _ATT)
    assert fold.state is AttemptState.FAILED


def test_legacy_completed_without_artifacts_is_still_completed() -> None:
    # Structural fold must not enforce S11-06 artifact inventory.
    fold = fold_attempt_state((_started(), _completed(outcome=ProcessingOutcome.NO_CHANGES)), _ATT)
    assert fold.state is AttemptState.COMPLETED
    assert fold.artifacts == {}


def test_physical_duplicate_same_event_id_folds_to_one_logical_event() -> None:
    start = _started()
    text = serialize_ledger_event(start) + "\n" + serialize_ledger_event(start) + "\n"
    events = parse_ledger_text(text)
    assert len(events) == 1
    assert fold_attempt_state(events, _ATT).state is AttemptState.STARTED


def test_two_distinct_starts_fail_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state((_started(event_id=_eid(1)), _started(event_id=_eid(2))), _ATT)
    assert exc.value.reason is AttemptStateConflictReason.MULTIPLE_STARTED


def test_artifact_before_start_fails_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state(
            (_artifact(PersistedArtifactKind.SUMMARY), _started(event_id=_eid(5))), _ATT
        )
    assert exc.value.reason is AttemptStateConflictReason.EVENT_BEFORE_START


def test_proposal_before_start_fails_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state((_proposal(), _started(event_id=_eid(5))), _ATT)
    assert exc.value.reason is AttemptStateConflictReason.EVENT_BEFORE_START


def test_duplicate_artifact_slot_fails_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state(
            (
                _started(),
                _artifact(PersistedArtifactKind.SUMMARY, event_id=_eid(2)),
                _artifact(PersistedArtifactKind.SUMMARY, event_id=_eid(3)),
            ),
            _ATT,
        )
    assert exc.value.reason is AttemptStateConflictReason.DUPLICATE_ARTIFACT_SLOT


def test_multiple_proposal_events_fail_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state(
            (_started(), _proposal(event_id=_eid(3)), _proposal(event_id=_eid(4))), _ATT
        )
    assert exc.value.reason is AttemptStateConflictReason.MULTIPLE_PROPOSAL_EVENTS


def test_multiple_terminals_fail_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state(
            (_started(), _completed(event_id=_eid(9)), _failed(event_id=_eid(10))), _ATT
        )
    assert exc.value.reason is AttemptStateConflictReason.MULTIPLE_TERMINAL


def test_event_after_terminal_fails_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state(
            (
                _started(),
                _completed(event_id=_eid(9)),
                _artifact(PersistedArtifactKind.SUMMARY, event_id=_eid(10)),
            ),
            _ATT,
        )
    assert exc.value.reason is AttemptStateConflictReason.EVENT_AFTER_TERMINAL


def test_session_ref_mismatch_fails_closed() -> None:
    with pytest.raises(AttemptStateConflictError) as exc:
        fold_attempt_state(
            (_started(), _artifact(PersistedArtifactKind.SUMMARY, session="S999")), _ATT
        )
    assert exc.value.reason is AttemptStateConflictReason.SESSION_REF_MISMATCH
