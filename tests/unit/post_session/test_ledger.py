"""S11-01 append-only processing-ledger event semantics tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.post_session_ledger import (
    LedgerAppendOutcome,
    attempt_has_terminal_event,
    load_ledger_events,
    new_ledger_event_id,
    parse_ledger_text,
    record_ledger_event,
    serialize_ledger_event,
)
from dnd_assistant.domain.post_session import (
    AttemptCompleted,
    AttemptStarted,
    ProcessingLedgerEvent,
    ProcessingOutcome,
    Sha256Fingerprint,
)
from dnd_assistant.errors import ConflictError, StorageError

_NOW = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)
_FP = Sha256Fingerprint(digest="c" * 64)


class FakeStore:
    """In-memory ``PostSessionProcessingStore`` for semantics tests."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_ledger_line(self, session_id: str, content: str) -> None:
        self.lines.append(content)

    def read_ledger_if_present(self, session_id: str) -> str | None:
        return "".join(self.lines) if self.lines else None

    def ledger_exists(self, session_id: str) -> bool:
        return bool(self.lines)


class RacingStore(FakeStore):
    """Insert an unrelated valid append between a caller's pre-read and append."""

    def __init__(self, unrelated_line: str) -> None:
        super().__init__()
        self._unrelated_line = unrelated_line
        self._raced = False

    def append_ledger_line(self, session_id: str, content: str) -> None:
        if not self._raced:
            self._raced = True
            self.lines.append(self._unrelated_line)
        super().append_ledger_line(session_id, content)


def _started(
    event_id: str = "le_" + "a" * 32,
    attempt_id: str = "att_" + "a" * 32,
    real_time: datetime = _NOW,
) -> AttemptStarted:
    return AttemptStarted(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref="S001",
        real_time=real_time,
        input_fingerprint=_FP,
        processor_version="1",
        prompt_version="1",
    )


def _completed(
    event_id: str = "le_" + "b" * 32,
    attempt_id: str = "att_" + "a" * 32,
) -> AttemptCompleted:
    return AttemptCompleted(
        event_id=event_id,
        attempt_id=attempt_id,
        session_ref="S001",
        real_time=_NOW,
        outcome=ProcessingOutcome.PRODUCED,
    )


def test_parse_empty_text_is_no_events() -> None:
    assert parse_ledger_text("") == ()
    assert load_ledger_events(FakeStore(), "S001") == ()


def test_parse_single_event_roundtrip() -> None:
    event = _started()
    text = serialize_ledger_event(event) + "\n"
    assert parse_ledger_text(text) == (event,)


def test_physically_duplicated_identical_event_folds_to_one_logical_event() -> None:
    event = _started()
    line = serialize_ledger_event(event) + "\n"
    text = line + line
    parsed = parse_ledger_text(text)
    assert parsed == (event,)
    # The physical text is untouched by the reader (append-only evidence).
    assert text.count("\n") == 2


def test_physically_duplicated_conflicting_payload_fails_closed() -> None:
    line_a = serialize_ledger_event(_started()) + "\n"
    line_b = serialize_ledger_event(_started(real_time=datetime(2026, 9, 1, tzinfo=UTC))) + "\n"
    with pytest.raises(StorageError):
        parse_ledger_text(line_a + line_b)


def test_repeated_attempt_id_with_different_events_is_valid() -> None:
    attempt = "att_" + "a" * 32
    events = (_started(attempt_id=attempt), _completed(attempt_id=attempt))
    text = "".join(serialize_ledger_event(e) + "\n" for e in events)
    assert parse_ledger_text(text) == events


def test_sequential_retry_is_idempotent_no_op() -> None:
    store = FakeStore()
    event = _started()
    first = record_ledger_event(store, "S001", event)
    assert first.outcome is LedgerAppendOutcome.CREATED
    snapshot = list(store.lines)

    second = record_ledger_event(store, "S001", event)
    assert second.outcome is LedgerAppendOutcome.ALREADY_PRESENT
    assert second.event == event
    assert store.lines == snapshot


def test_same_event_id_different_payload_conflicts() -> None:
    store = FakeStore()
    event = _started()
    record_ledger_event(store, "S001", event)
    conflicting = _started(real_time=datetime(2026, 9, 1, tzinfo=UTC))
    with pytest.raises(ConflictError):
        record_ledger_event(store, "S001", conflicting)
    assert len(store.lines) == 1


def test_unrelated_concurrent_valid_append_does_not_falsely_corrupt() -> None:
    existing = _started(event_id="le_" + "9" * 32)
    unrelated = _completed(event_id="le_" + "8" * 32, attempt_id="att_" + "9" * 32)
    unrelated_line = serialize_ledger_event(unrelated) + "\n"

    store = RacingStore(unrelated_line)
    record_ledger_event(store, "S001", existing)

    new_event = _completed(event_id="le_" + "7" * 32)
    result = record_ledger_event(store, "S001", new_event)
    assert result.outcome is LedgerAppendOutcome.CREATED
    assert result.event == new_event

    parsed = parse_ledger_text("".join(store.lines))
    assert existing in parsed
    assert unrelated in parsed
    assert new_event in parsed


def test_malformed_and_partial_tails_fail_closed() -> None:
    valid = serialize_ledger_event(_started()) + "\n"
    with pytest.raises(StorageError):
        parse_ledger_text(valid + "{not json")
    with pytest.raises(StorageError):
        parse_ledger_text(valid[:-1])  # unterminated final record
    with pytest.raises(StorageError):
        parse_ledger_text(valid + "\n")  # blank line


def test_record_fails_closed_on_malformed_existing_ledger() -> None:
    store = FakeStore()
    store.lines.append("{not json\n")
    with pytest.raises(StorageError):
        record_ledger_event(store, "S001", _started())


def test_attempt_has_terminal_event() -> None:
    attempt = "att_" + "a" * 32
    events: tuple[ProcessingLedgerEvent, ...] = (_started(attempt_id=attempt),)
    assert attempt_has_terminal_event(events, attempt) is False
    assert attempt_has_terminal_event(events + (_completed(attempt_id=attempt),), attempt) is True
    assert attempt_has_terminal_event(events, "att_" + "b" * 32) is False


def test_new_ledger_event_id_shape() -> None:
    value = new_ledger_event_id()
    assert value.startswith("le_")
    assert len(value) == 3 + 32
    assert new_ledger_event_id() != value


def test_serialize_is_deterministic_across_construction() -> None:
    a = _started()
    b = _started()
    assert serialize_ledger_event(a) == serialize_ledger_event(b)


def test_load_ledger_events_reads_missing_as_empty() -> None:
    assert load_ledger_events(FakeStore(), "S001") == ()
