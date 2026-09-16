"""S11-08 ledger durability/lock hardening tests (real filesystem).

Closes gaps left by S11-01/S11-06: fsync failure classification, the ordinary
(no-reread) uncertainty contract of ``record_ledger_event``, and permanent
(non-contention) lock failure on the read path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.post_session_ledger import (
    record_ledger_event,
    serialize_ledger_event,
)
from dnd_assistant.domain.post_session import AttemptStarted, Sha256Fingerprint
from dnd_assistant.errors import StorageError
from dnd_assistant.storage import post_session_processing as pse
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from tests.unit.post_session.helpers import create_completed_session

_NOW = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)
_ATT = "att_" + "a" * 32
_FP = Sha256Fingerprint(digest="c" * 64)


def _event(event_id: str = "le_" + "a" * 32) -> AttemptStarted:
    return AttemptStarted(
        event_id=event_id,
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        input_fingerprint=_FP,
        processor_version="2",
        prompt_version="v1",
    )


class _CountingStore:
    """Delegating store counting reads to prove the no-reread uncertainty path."""

    def __init__(self, real: ObsidianPostSessionProcessingStore) -> None:
        self._real = real
        self.reads = 0

    def append_ledger_line(self, session_id: str, content: str) -> None:
        self._real.append_ledger_line(session_id, content)

    def read_ledger_if_present(self, session_id: str) -> str | None:
        self.reads += 1
        return self._real.read_ledger_if_present(session_id)

    def ledger_exists(self, session_id: str) -> bool:
        return self._real.ledger_exists(session_id)


def test_fsync_failure_reports_storage_error_but_bytes_may_persist(
    vault_root, audit_service, monkeypatch
) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    line = serialize_ledger_event(_event()) + "\n"

    def failing_fsync(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pse.os, "fsync", failing_fsync)

    with pytest.raises(StorageError):
        store.append_ledger_line("S001", line)

    ledger = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.jsonl"
    # The single O_APPEND write already happened; fsync failure is an uncertain,
    # not a proven-absent, outcome.  No truncation/repair is attempted.
    assert ledger.read_text(encoding="utf-8") == line


def test_record_ledger_event_does_not_reread_when_append_raises(
    vault_root, audit_service, monkeypatch
) -> None:
    create_completed_session(vault_root, audit_service)
    real = ObsidianPostSessionProcessingStore(vault_root)
    store = _CountingStore(real)

    def failing_append(session_id: str, content: str) -> None:
        raise StorageError("injected append failure")

    monkeypatch.setattr(real, "append_ledger_line", failing_append)

    with pytest.raises(StorageError):
        record_ledger_event(store, "S001", _event())  # type: ignore[arg-type]

    # Exactly the initial read; the append failure propagates without an
    # internal post-failure reread (the stronger terminal-append recovery is
    # intentionally confined to ``append_terminal``).
    assert store.reads == 1


def test_permanent_lock_acquisition_failure_on_read_is_storage_error(
    vault_root, audit_service, monkeypatch
) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", serialize_ledger_event(_event()) + "\n")

    calls = {"count": 0}

    def permanent(fd: int) -> None:
        calls["count"] += 1
        raise OSError(9, "Bad file descriptor")

    monkeypatch.setattr(pse, "_acquire_exclusive", permanent)

    with pytest.raises(StorageError):
        store.read_ledger_if_present("S001")

    # A non-contention error is permanent: it is not retried.
    assert calls["count"] == 1
