"""S11-01 append-only processing-ledger storage tests (real filesystem)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dnd_assistant.application.post_session_ledger import (
    LedgerAppendOutcome,
    load_ledger_events,
    record_ledger_event,
    serialize_ledger_event,
)
from dnd_assistant.domain.post_session import (
    AttemptCompleted,
    AttemptStarted,
    ProcessingOutcome,
    Sha256Fingerprint,
)
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from tests.unit.post_session.helpers import create_completed_session

_NOW = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)
_FP = Sha256Fingerprint(digest="c" * 64)
_ATT = "att_" + "a" * 32


def _started(event_id: str = "le_" + "a" * 32) -> AttemptStarted:
    return AttemptStarted(
        event_id=event_id,
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        input_fingerprint=_FP,
        processor_version="1",
        prompt_version="1",
    )


def _can_symlink() -> bool:
    tmp = tempfile.mkdtemp()
    try:
        target = os.path.join(tmp, "target")
        Path(target).write_text("", encoding="utf-8")
        os.symlink(target, os.path.join(tmp, "link"))
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


requires_symlink = pytest.mark.skipif(not _can_symlink(), reason="host cannot create symlinks")


def test_absent_ledger_reads_as_not_created(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    assert store.read_ledger_if_present("S001") is None
    assert store.ledger_exists("S001") is False
    assert load_ledger_events(store, "S001") == ()


def test_append_then_fresh_instance_read_returns_exact_event(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    event = _started()
    result = record_ledger_event(store, "S001", event)
    assert result.outcome is LedgerAppendOutcome.CREATED

    fresh = ObsidianPostSessionProcessingStore(vault_root)
    assert load_ledger_events(fresh, "S001") == (event,)


def test_append_preserves_exact_previous_history(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    first = _started("le_" + "1" * 32)
    second = AttemptCompleted(
        event_id="le_" + "2" * 32,
        attempt_id=_ATT,
        session_ref="S001",
        real_time=_NOW,
        outcome=ProcessingOutcome.PRODUCED,
    )
    record_ledger_event(store, "S001", first)
    record_ledger_event(store, "S001", second)

    text = store.read_ledger_if_present("S001")
    assert text is not None
    lines = text.splitlines(keepends=True)
    assert lines[0] == serialize_ledger_event(first) + "\n"
    assert text == lines[0] + lines[1]
    assert load_ledger_events(store, "S001") == (first, second)


def test_session_id_path_escape_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    for bad in ("../evil", "S001/../evil", "..", "a/b"):
        with pytest.raises(StorageError):
            store.append_ledger_line(bad, "x\n")
        with pytest.raises(StorageError):
            store.read_ledger_if_present(bad)


def test_processing_directory_collision_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    raw_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
    (raw_dir / "processing").write_text("not a directory", encoding="utf-8")

    with pytest.raises(StorageError):
        store.read_ledger_if_present("S001")
    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_started()) + "\n")


def test_ledger_leaf_directory_collision_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    processing = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing"
    processing.mkdir()
    (processing / "ledger.jsonl").mkdir()

    with pytest.raises(StorageError):
        store.read_ledger_if_present("S001")
    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_started()) + "\n")


@requires_symlink
def test_ledger_leaf_symlink_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    processing = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing"
    processing.mkdir()
    target = processing / "target.jsonl"
    target.write_text("", encoding="utf-8")
    os.symlink(target, processing / "ledger.jsonl")

    with pytest.raises(StorageError):
        store.read_ledger_if_present("S001")
    with pytest.raises(StorageError):
        store.append_ledger_line("S001", serialize_ledger_event(_started()) + "\n")


def test_malformed_line_fails_closed(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", "{not json}\n")
    with pytest.raises(StorageError):
        load_ledger_events(store, "S001")


def test_partial_tail_fails_closed(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    event = _started()
    record_ledger_event(store, "S001", event)

    ledger = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.jsonl"
    text = ledger.read_text(encoding="utf-8")
    ledger.write_text(text[:-1], encoding="utf-8")  # drop terminating newline

    with pytest.raises(StorageError):
        load_ledger_events(store, "S001")

    # An append on top of an uncertain tail must also fail closed.
    with pytest.raises(StorageError):
        record_ledger_event(
            store,
            "S001",
            AttemptCompleted(
                event_id="le_" + "f" * 32,
                attempt_id=_ATT,
                session_ref="S001",
                real_time=_NOW,
                outcome=ProcessingOutcome.PRODUCED,
            ),
        )


def test_blank_line_fails_closed(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", serialize_ledger_event(_started()) + "\n")
    store.append_ledger_line("S001", "\n")
    with pytest.raises(StorageError):
        load_ledger_events(store, "S001")


def test_unsupported_schema_version_fails_closed(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    payload = json.loads(serialize_ledger_event(_started()))
    payload["schema_version"] = 2
    store.append_ledger_line("S001", json.dumps(payload, separators=(",", ":")) + "\n")
    with pytest.raises(StorageError):
        load_ledger_events(store, "S001")


def test_duplicate_retry_does_not_change_physical_ledger(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    event = _started()
    record_ledger_event(store, "S001", event)
    before = store.read_ledger_if_present("S001")

    again = record_ledger_event(store, "S001", event)
    assert again.outcome is LedgerAppendOutcome.ALREADY_PRESENT
    assert store.read_ledger_if_present("S001") == before


def test_ledger_operations_do_not_write_audit_records(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    audit_log = vault_root / "_system" / "audit" / "audit.jsonl"
    baseline = AuditService(audit_log).read_all()
    baseline_count = len(baseline)

    store = ObsidianPostSessionProcessingStore(vault_root)
    record_ledger_event(store, "S001", _started())
    record_ledger_event(store, "S001", _started())  # idempotent retry
    ObsidianPostSessionProcessingStore(vault_root).read_ledger_if_present("S001")

    after = AuditService(audit_log).read_all()
    assert len(after) == baseline_count
    assert all(record.operation not in ("attempt_started",) for record in after)
    assert [r for r in after if r.session == "S001"] == [r for r in baseline if r.session == "S001"]
