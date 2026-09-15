"""S11-01 append-only processing-ledger event semantics.

This module owns the *meaning* of persisted ledger bytes:

- trusted ledger event-id generation;
- canonical per-event serialization;
- strict, fail-closed parsing with idempotent replay semantics;
- append/duplicate/idempotency policy over a safe storage primitive.

Duplicate/idempotency contract (accepted correction):

    same event_id + canonically identical payload -> logical replay
        * the storage primitive performs no write on the sequential-retry path;
        * a physically duplicated identical line is folded to one logical event,
          preserving first-occurrence order, and the physical ledger is left
          untouched (never rewritten/truncated);
    same event_id + different payload            -> ConflictError (fail closed)
    repeated attempt_id with different events    -> valid, not a duplicate

Post-append verification tolerates unrelated valid concurrent appends:
the previously read bytes must remain an exact prefix, the complete ledger
must parse strictly, and the caller's logical event must be present with
exactly the expected canonical payload.  Any conflicting identity or
malformed/partial evidence fails closed.

The storage layer only performs safe opaque append/read placement; this module
depends on the ``PostSessionProcessingStore`` protocol (``TYPE_CHECKING`` only)
and stays free of concrete storage, model/provider and CLI layers.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os,
    shutil, tempfile, subprocess, or a concrete storage implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import TypeAdapter

from dnd_assistant.domain.post_session import ProcessingLedgerEvent
from dnd_assistant.errors import ConflictError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.storage.post_session_processing import (
        PostSessionProcessingStore,
    )

_LEDGER_EVENT_ADAPTER: TypeAdapter[ProcessingLedgerEvent] = TypeAdapter(ProcessingLedgerEvent)


# ── Event identity ────────────────────────────────────────────────────────


def new_ledger_event_id() -> str:
    """Generate a trusted, opaque ledger event identifier.

    Satisfies the domain ``LedgerEventId`` contract: lowercase ``le_`` prefix
    plus 32 hex characters.  The value identifies one logical append; it
    carries no decodeable semantics.
    """
    return f"le_{uuid4().hex}"


# ── Serialization ─────────────────────────────────────────────────────────


def serialize_ledger_event(event: ProcessingLedgerEvent) -> str:
    """Serialize a ledger event to its deterministic canonical JSON text.

    The output contains no trailing newline.  Keys are sorted, separators are
    compact, Unicode is preserved and NaN/Infinity are forbidden, so the text
    is stable across processes and dict insertion orders.
    """
    payload = event.model_dump(mode="json", exclude_unset=False)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


# ── Strict parsing with idempotent replay ─────────────────────────────────


def parse_ledger_text(text: str) -> tuple[ProcessingLedgerEvent, ...]:
    """Strictly parse a complete processing-ledger text.

    Every non-empty line must be a complete, schema-valid event terminated by
    a newline.  Blank lines, malformed JSON, non-object lines, invalid events,
    an unterminated final record and unsupported schema versions all fail
    closed.

    Physically duplicated identical events (same ``event_id`` and canonically
    identical payload) are folded to a single logical event, preserving the
    first occurrence order.  The same ``event_id`` with a different payload is
    contradictory and fails closed.

    Raises:
        StorageError: Any line is malformed, unsupported, or contradictory.
    """
    if text == "":
        return ()

    if not text.endswith("\n"):
        raise StorageError(
            "processing ledger: final record is not newline-terminated (uncertain tail)"
        )

    lines = text.split("\n")[:-1]

    ordered: list[ProcessingLedgerEvent] = []
    canonical_by_id: dict[str, str] = {}

    for line_no, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            raise StorageError(f"processing ledger: blank line at {line_no}")

        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"processing ledger: malformed JSON at line {line_no}",
                cause=exc,
            ) from exc

        if not isinstance(data, dict):
            raise StorageError(f"processing ledger: line {line_no} is not a JSON object")

        try:
            event = _LEDGER_EVENT_ADAPTER.validate_python(data)
        except Exception as exc:
            raise StorageError(
                f"processing ledger: invalid event at line {line_no}",
                cause=exc,
            ) from exc

        canonical = serialize_ledger_event(event)
        previous = canonical_by_id.get(event.event_id)
        if previous is not None:
            if previous != canonical:
                raise StorageError(
                    f"processing ledger: conflicting payload for event_id "
                    f"{event.event_id!r} at line {line_no}"
                )
            continue

        canonical_by_id[event.event_id] = canonical
        ordered.append(event)

    return tuple(ordered)


def load_ledger_events(
    store: PostSessionProcessingStore,
    session_id: str,
) -> tuple[ProcessingLedgerEvent, ...]:
    """Read and strictly parse the session's durable ledger.

    Returns an empty tuple when the ledger has not been created yet.

    Raises:
        StorageError: The ledger is unsafe, unreadable or malformed.
    """
    text = store.read_ledger_if_present(session_id)
    if text is None:
        return ()
    return parse_ledger_text(text)


def attempt_has_terminal_event(
    events: tuple[ProcessingLedgerEvent, ...],
    attempt_id: str,
) -> bool:
    """Minimal fold: whether ``attempt_id`` has a terminal event.

    Full attempt-state reconstruction belongs to S11-06; this predicate exists
    only to support the structural eligibility rule that a requested attempt
    must not already be terminal.
    """
    for event in events:
        if event.attempt_id != attempt_id:
            continue
        if event.event_kind in ("attempt_completed", "attempt_failed"):
            return True
    return False


# ── Append policy ─────────────────────────────────────────────────────────


class LedgerAppendOutcome(StrEnum):
    """Result of recording one logical ledger event."""

    CREATED = "created"
    ALREADY_PRESENT = "already_present"


@dataclass(frozen=True)
class LedgerAppendResult:
    """The logical persisted event plus the append outcome."""

    event: ProcessingLedgerEvent
    outcome: LedgerAppendOutcome


def record_ledger_event(
    store: PostSessionProcessingStore,
    session_id: str,
    event: ProcessingLedgerEvent,
) -> LedgerAppendResult:
    """Append one logical event with idempotent, concurrency-tolerant policy.

    Sequential retry of an identical event is an idempotent no-op (no write).
    A different payload for an already-recorded ``event_id`` is
    ``ConflictError``.  Post-append verification tolerates unrelated valid
    concurrent appends while still failing closed on any conflicting identity,
    prefix violation or malformed/partial persisted evidence.

    Raises:
        ConflictError: The same ``event_id`` already exists with different content.
        StorageError: The existing or persisted ledger is malformed/unsafe, or
            post-append verification failed.
    """
    before_text = store.read_ledger_if_present(session_id)
    if before_text is None:
        before_text = ""

    existing_events = parse_ledger_text(before_text)
    expected = serialize_ledger_event(event)

    for existing in existing_events:
        if existing.event_id == event.event_id:
            if serialize_ledger_event(existing) == expected:
                return LedgerAppendResult(
                    event=existing, outcome=LedgerAppendOutcome.ALREADY_PRESENT
                )
            raise ConflictError(
                f"Processing ledger event {event.event_id!r} already exists with different content"
            )

    store.append_ledger_line(session_id, expected + "\n")

    persisted_text = store.read_ledger_if_present(session_id)
    if persisted_text is None:
        raise StorageError(
            f"Processing ledger append of {event.event_id!r} reported success but "
            f"the ledger is absent"
        )

    if not persisted_text.startswith(before_text):
        raise StorageError(
            f"Processing ledger append of {event.event_id!r} violated the exact prefix invariant"
        )

    try:
        persisted_events = parse_ledger_text(persisted_text)
    except StorageError as exc:
        raise StorageError(
            f"Processing ledger is malformed after append of {event.event_id!r}",
            cause=exc,
        ) from exc

    persisted = None
    for candidate in persisted_events:
        if candidate.event_id == event.event_id:
            persisted = candidate
            break

    if persisted is None:
        raise StorageError(
            f"Processing ledger append of {event.event_id!r} is not present after append"
        )

    if serialize_ledger_event(persisted) != expected:
        raise StorageError(
            f"Processing ledger append of {event.event_id!r} payload mismatch after append"
        )

    return LedgerAppendResult(event=persisted, outcome=LedgerAppendOutcome.CREATED)


__all__ = [
    "LedgerAppendOutcome",
    "LedgerAppendResult",
    "attempt_has_terminal_event",
    "load_ledger_events",
    "new_ledger_event_id",
    "parse_ledger_text",
    "record_ledger_event",
    "serialize_ledger_event",
]
