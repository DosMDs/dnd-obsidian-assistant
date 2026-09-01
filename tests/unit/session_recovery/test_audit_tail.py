"""Tests for audit-tail inspection and self-targeting repair.

Covers:
- Audit inspection classification (partial tail, corrupt, clean)
- Audit tail repair (append LF, truncate)
- UTF-8 corruption handling
- CRLF prefix preservation
- Low-level I/O error translation
- Recovery marker semantics
- Race detection
"""

from __future__ import annotations

from pathlib import Path

import pytest

import dnd_assistant.storage.session_recovery.audit_tail as _audit_tail_mod
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)
from tests.unit.session_recovery.conftest import (
    make_audit_context,
    valid_audit_line,
    valid_audit_record_str,
)

# ── Audit inspection ──────────────────────────────────────────────────────────


class TestAuditTailDetection:
    """Audit log inspection classification."""

    def test_audit_missing_lf_recoverable(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "audit_partial_tail" in codes
        issue = next(i for i in report.issues if i.code == "audit_partial_tail")
        assert issue.recoverable is True

    def test_audit_incomplete_tail_recoverable(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(
            valid_audit_line("op1") + '{"incomplete"',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "audit_partial_tail" in codes

    def test_audit_middle_line_corrupt_not_recoverable(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(
            valid_audit_line("op1") + "corrupt\n" + valid_audit_line("op2"),
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "audit_corrupt" in codes


class TestInspectReadOnlyC05:
    """Inspect must not create any files under corrupt audit."""

    def test_inspect_under_corrupt_audit_creates_no_files(
        self, vault_root: Path, audit_svc
    ) -> None:
        log = audit_svc.log_path
        log.write_text("not json\n", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        assert list((vault_root / "_system" / "audit").iterdir()) == [log]


class TestAuditTailRepair:
    """Audit tail repair operations."""

    def test_valid_record_missing_lf_appends_lf(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_audit_tail(audit=make_audit_context())
        assert result.operation == "audit.recovery.tail"
        assert result.before_hash is not None
        assert result.after_hash is not None
        content = log.read_bytes()
        assert content.endswith(b"\n")

    def test_invalid_incomplete_tail_truncated(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(
            valid_audit_line("op1") + '{"incomplete"',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_audit_tail(audit=make_audit_context())
        assert result.operation == "audit.recovery.tail"
        content = log.read_text(encoding="utf-8")
        assert content.startswith(valid_audit_line("op1"))
        assert "audit.recovery.tail" in content
        assert content.endswith("\n")

    def test_malformed_completed_line_raises_storage_error(
        self, vault_root: Path, audit_svc
    ) -> None:
        log = audit_svc.log_path
        log.write_text("not json\n", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="already ends with newline"):
            repo.repair_audit_tail(audit=make_audit_context())


class TestAuditTailRepairMarker:
    """Recovery marker semantics."""

    def test_recovery_marker_correct_semantics(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_audit_tail(audit=make_audit_context(operation_id="rec-001"))
        records = audit_svc.read_all()
        marker = records[-1]
        assert marker.operation == "audit.recovery.tail"
        assert marker.phase == "committed"
        assert marker.before_hash == result.before_hash
        assert marker.after_hash == result.after_hash

    def test_race_before_repair_raises_conflict(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        original_read = _audit_tail_mod._read_exact_bytes
        call_count = 0

        def racing_read(path):
            nonlocal call_count
            call_count += 1
            if call_count == 2 and path == log:
                log.write_text(
                    valid_audit_line("op1") + valid_audit_line("op2"),
                    encoding="utf-8",
                    newline="",
                )
            return original_read(path)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(_audit_tail_mod, "_read_exact_bytes", racing_read)
        try:
            with pytest.raises(ConflictError):
                repo.repair_audit_tail(audit=make_audit_context(operation_id="rec-001"))
        finally:
            monkeypatch.undo()

    def test_marker_append_failure_leaves_repaired_audit(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        log = audit_svc.log_path
        valid_line = valid_audit_line("op1")
        log.write_text(
            valid_line + valid_audit_record_str("op2"),
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        def failing_append(record):
            raise StorageError("simulated append failure")

        monkeypatch.setattr(audit_svc, "append", failing_append)
        with pytest.raises(StorageError, match="recovery marker append failed"):
            repo.repair_audit_tail(audit=make_audit_context(operation_id="rec-001"))
        content = log.read_bytes()
        assert content.endswith(b"\n")


class TestCrlfPreservationC05:
    """CRLF prefix must not be corrupted by audit repair."""

    def test_audit_crlf_prefix_not_corrupted(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        crlf_line = valid_audit_line("op1").replace("\n", "\r\n")
        log.write_text(crlf_line + valid_audit_record_str("op2"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_audit_tail(audit=make_audit_context())
        content = log.read_bytes()
        assert b"\r\n" in content
        assert content.endswith(b"\n")


class TestLowLevelErrorTranslationC05:
    """Low-level I/O errors must be translated to StorageError."""

    def test_audit_os_open_failure_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")

        def failing_open(path, flags, *args):
            raise OSError("simulated open failure")

        monkeypatch.setattr(_audit_tail_mod.os, "open", failing_open)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=make_audit_context())

    def test_audit_short_write_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")

        def short_write(fd, data):
            return 0

        monkeypatch.setattr(_audit_tail_mod.os, "write", short_write)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="Short write"):
            repo.repair_audit_tail(audit=make_audit_context())

    def test_audit_fsync_failure_raises_storage_error(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")

        def failing_fsync(fd):
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(_audit_tail_mod.os, "fsync", failing_fsync)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=make_audit_context())


class TestRequireCleanAuditLog:
    """_require_clean_audit_log validation."""

    def test_missing_file_returns_empty(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        records = _require_clean_audit_log(audit_svc)
        assert records == []

    def test_empty_file_returns_empty(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        audit_svc.log_path.write_text("", encoding="utf-8", newline="")
        records = _require_clean_audit_log(audit_svc)
        assert records == []

    def test_valid_lf_terminated_returns_records(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        audit_svc.log_path.write_text(valid_audit_line("op1"), encoding="utf-8", newline="")
        records = _require_clean_audit_log(audit_svc)
        assert len(records) == 1

    def test_valid_without_lf_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.errors import StorageError as SE
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        audit_svc.log_path.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")
        try:
            _require_clean_audit_log(audit_svc)
            pytest.fail("Expected StorageError")
        except SE as e:
            assert "trailing newline" in str(e)

    def test_invalid_utf8_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.errors import StorageError as SE
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        audit_svc.log_path.write_bytes(b"\xff\xfe\x00\x01")
        try:
            _require_clean_audit_log(audit_svc)
            pytest.fail("Expected StorageError")
        except SE as e:
            assert "invalid UTF-8" in str(e)

    def test_malformed_json_raises_storage_error(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        audit_svc.log_path.write_text("not json\n", encoding="utf-8", newline="")
        with pytest.raises(StorageError, match="corruption"):
            _require_clean_audit_log(audit_svc)

    def test_read_only_no_filesystem_mutation(self, vault_root: Path, audit_svc) -> None:
        from dnd_assistant.storage.session_recovery.support import _require_clean_audit_log

        audit_svc.log_path.write_text(valid_audit_line("op1"), encoding="utf-8", newline="")
        before = set((vault_root / "_system" / "audit").iterdir())
        _require_clean_audit_log(audit_svc)
        after = set((vault_root / "_system" / "audit").iterdir())
        assert before == after

    """UTF-8 corruption detection for audit logs."""

    def test_invalid_utf8_audit_reported_corrupt(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_bytes(b"\xff\xfe\x00\x01")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "audit_corrupt" in codes

    def test_invalid_utf8_audit_repair_raises_storage_error(
        self, vault_root: Path, audit_svc
    ) -> None:
        log = audit_svc.log_path
        log.write_bytes(b"\xff\xfe\x00\x01")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="invalid UTF-8"):
            repo.repair_audit_tail(audit=make_audit_context())


class TestAuditPhysicalLfC05:
    """Physical LF boundary tests for audit logs."""

    def test_valid_missing_lf_reported_as_partial_tail(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text(valid_audit_record_str("op1"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "audit_partial_tail" in codes

    def test_lf_terminated_corrupt_is_corrupt(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text("not json\n", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "audit_corrupt" in codes

    def test_lf_terminated_corrupt_repair_refused(self, vault_root: Path, audit_svc) -> None:
        log = audit_svc.log_path
        log.write_text("not json\n", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="already ends with newline"):
            repo.repair_audit_tail(audit=make_audit_context())
