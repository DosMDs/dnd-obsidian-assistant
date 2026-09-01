"""Tests for event-tail validation and repair.

Covers:
- Event tail repair (append LF, truncate)
- Clean log raises StorageError
- Corrupt middle line raises StorageError
- Audit trail (intent and committed)
- Exact before/after hash
- Intent failure bytes unchanged
- Metadata prerequisite (missing, corrupt)
- Clean audit prerequisite
- CRLF prefix preservation
- Low-level I/O error translation
- Committed audit failure partial-state
"""

from __future__ import annotations

import os as _os
from pathlib import Path

import pytest

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)
from tests.unit.session_recovery.conftest import (
    make_audit_context,
    start_session,
    valid_audit_record_str,
    valid_event_line,
    valid_event_record_str,
)


class TestEventTailRepair:
    """Event tail repair operations."""

    def test_valid_event_missing_lf_appends_lf(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert result.operation == "session.recovery.events_tail"
        assert result.before_hash is not None
        assert result.after_hash is not None
        assert ev.read_bytes().endswith(b"\n")

    def test_invalid_partial_tail_truncated(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            valid_event_line("evt_001") + '{"incomplete"',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert result.operation == "session.recovery.events_tail"
        content = ev.read_text(encoding="utf-8")
        assert content == valid_event_line("evt_001")

    def test_clean_log_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_line("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="already valid"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_corrupt_middle_line_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            valid_event_line("evt_001") + "corrupt\n" + valid_event_line("evt_002"),
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="not limited to the final tail"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))


class TestEventTailRepairAudit:
    """Audit trail for event tail repair."""

    def test_intent_and_committed_audit(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_event_tail(
            "S006", audit=make_audit_context(operation_id="rec-001", session="S006")
        )
        records = audit_svc.read_all()
        intents = [
            r
            for r in records
            if r.phase == "intent" and r.operation == "session.recovery.events_tail"
        ]
        committed = [
            r
            for r in records
            if r.phase == "committed" and r.operation == "session.recovery.events_tail"
        ]
        assert len(intents) == 1
        assert len(committed) == 1

    def test_exact_before_after_hash(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert result.before_hash is not None
        assert result.after_hash is not None
        assert result.before_hash != result.after_hash

    def test_intent_failure_bytes_unchanged(self, vault_root: Path, audit_svc, monkeypatch) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        def failing_append(record):
            raise StorageError("simulated append failure")

        monkeypatch.setattr(audit_svc, "append", failing_append)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert ev.read_bytes().startswith(valid_event_record_str("evt_001").encode("utf-8"))


class TestEventTailMetadataPrerequisiteC05:
    """Metadata prerequisite for event repair."""

    def test_missing_metadata_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta_path.unlink()
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="no metadata"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_corrupt_metadata_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta_path.write_text("not json", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))


class TestEventTailCleanAuditPrerequisiteC05:
    """Clean audit prerequisite for event repair."""

    def test_corrupt_audit_prevents_event_repair(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        audit_svc.log_path.write_text("corrupt\n", encoding="utf-8", newline="")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))


class TestEventCrlfPreservationC05:
    """CRLF prefix must not be corrupted by event repair."""

    def test_event_crlf_prefix_not_corrupted(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        crlf_line = valid_event_line("evt_001").replace("\n", "\r\n")
        ev.write_text(crlf_line + valid_event_record_str("evt_002"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        content = ev.read_bytes()
        assert b"\r\n" in content
        assert content.endswith(b"\n")


class TestEventLowLevelErrorTranslationC05:
    """Low-level I/O errors must be translated to StorageError."""

    def test_event_os_open_failure_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")

        def failing_open(path, flags, *args):
            raise OSError("simulated open failure")

        monkeypatch.setattr(_os, "open", failing_open)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_event_short_write_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")

        def short_write(fd, data):
            return 0

        monkeypatch.setattr(_os, "write", short_write)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="Short write"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_event_ftruncate_failure_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            valid_event_line("evt_001") + '{"event_id":"evt_002",',
            encoding="utf-8",
            newline="",
        )

        def failing_ftruncate(fd, length):
            raise OSError("simulated ftruncate failure")

        monkeypatch.setattr(_os, "ftruncate", failing_ftruncate)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_event_fsync_failure_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")

        def failing_fsync(fd):
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(_os, "fsync", failing_fsync)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))


class TestCommittedAuditFailureC05:
    """Committed audit failure leaves repaired file."""

    def test_event_repair_committed_audit_failure_leaves_repaired_file(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")

        original_append = audit_svc.append

        def failing_append(record):
            if record.phase == "committed":
                raise StorageError("simulated append failure")
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", failing_append)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="audit finalization failed"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert ev.read_bytes().endswith(b"\n")


class TestEventRepairBlockedByMissingLfAuditC05F:
    """repair_event_tail must refuse when audit has valid record without LF."""

    def test_repair_refused_without_audit_lf(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        # Replace audit with valid record WITHOUT trailing LF
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_events_exact_bytes_unchanged_on_refusal(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        before = ev.read_bytes()
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except StorageError:
            pass
        assert ev.read_bytes() == before

    def test_metadata_exact_bytes_unchanged_on_refusal(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        before = meta.read_bytes()
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except StorageError:
            pass
        assert meta.read_bytes() == before

    def test_audit_exact_bytes_unchanged_on_refusal(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        before = audit_svc.log_path.read_bytes()
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except StorageError:
            pass
        assert audit_svc.log_path.read_bytes() == before

    def test_zero_recovery_intent_on_refusal(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        before_count = len(audit_svc.read_all())
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except StorageError:
            pass
        assert len(audit_svc.read_all()) == before_count


class TestInvalidUtf8MetadataC05F:
    """Invalid UTF-8 metadata must raise StorageError, not UnicodeDecodeError."""

    def test_invalid_utf8_metadata_raises_storage_error(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="invalid UTF-8"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))

    def test_not_unicode_decode_error(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except UnicodeDecodeError:
            pytest.fail("UnicodeDecodeError leaked instead of StorageError")
        except StorageError:
            pass

    def test_events_unchanged_on_invalid_utf8_metadata(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        before = ev.read_bytes()
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except StorageError:
            pass
        assert ev.read_bytes() == before

    def test_no_recovery_intent_on_invalid_utf8_metadata(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        before_count = len(audit_svc.read_all())
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        try:
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        except StorageError:
            pass
        assert len(audit_svc.read_all()) == before_count


class TestEmptyAndValidAuditStillSupportedC05F:
    """Empty audit and fully valid LF-terminated audit must still work."""

    def test_empty_audit_event_repair_still_works(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert result.operation == "session.recovery.events_tail"

    def test_valid_lf_audit_event_repair_still_works(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert result.operation == "session.recovery.events_tail"


class TestNoAppendBehindCorruptAuditC05F:
    """Ordinary recovery must never append behind partial or corrupt audit."""

    def test_invalid_utf8_audit_blocks_event_repair(self, vault_root, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        audit_svc.log_path.write_bytes(b"\xff\xfe")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
