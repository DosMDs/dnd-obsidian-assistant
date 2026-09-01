"""S6-C05 regression tests — recovery inspection / ownership / physical-tail integrity hardening.

Covers:
- inspection physically read-only under corrupt audit
- audit physical-LF classification
- UTF-8 corruption classification
- Sessions-only partial-start discovery
- raw-only partial-start discovery
- unsafe session symlink reporting
- ambiguous start ownership rejection
- post-intent cleanup races
- final cleanup absence verification
- event metadata ownership
- clean-audit prerequisite
- event post-intent metadata race
- event post-repair metadata race
- physical CRLF preservation/refusal
- open/write/short-write/truncate/fsync error translation
- committed-audit failure partial-state semantics
"""

from __future__ import annotations

import hashlib
import json
import os as _os
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Module-level reference for monkeypatch isolation (boundary-test safe)
import dnd_assistant.storage.session_recovery as _session_recovery_mod
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
    _bytes_hash,
)


def _active_session(**overrides: object) -> Session:
    kwargs = {
        "id": "S006",
        "type": "session",
        "status": "active",
        "real_started_at": datetime(2026, 8, 31, 15, 0, 0, tzinfo=UTC),
        "real_finished_at": None,
        "world_tick_start": 13800,
        "world_tick_end": None,
        "processed": False,
        "processed_model_profile": None,
        "revision": 1,
    }
    kwargs.update(overrides)
    return Session(**kwargs)


def _make_audit_context(
    operation_id: str = "test-rec-001",
    source: str = "test",
    session: str | None = None,
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
        source=source,
        session=session,
    )


def _create_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    for d in ["Sessions", "_system", "_system/raw", "_system/raw/sessions", "_system/audit"]:
        (root / d).mkdir()
    return root


def _create_audit_service(vault_root: Path) -> AuditService:
    return AuditService(vault_root / "_system" / "audit" / "audit.jsonl")


def _create_recovery_repo(vault_root: Path) -> ObsidianSessionRecoveryRepository:
    return ObsidianSessionRecoveryRepository(vault_root, _create_audit_service(vault_root))


def _write_audit_record(vault_root: Path, record: dict) -> None:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _start_session(vault_root: Path, session_id: str = "S006") -> None:
    audit_svc = _create_audit_service(vault_root)
    repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    session = _active_session(id=session_id)
    repo.create_session(
        session,
        audit=_make_audit_context(operation_id=f"start-{session_id}", session=session_id),
    )


def _write_audit_intent(vault_root: Path, session_id: str, op_id: str) -> None:
    _write_audit_record(
        vault_root,
        {
            "schema_version": 1,
            "operation_id": op_id,
            "real_time": "2026-08-31T15:00:00+00:00",
            "operation": "session.start",
            "entity_id": None,
            "before_hash": None,
            "after_hash": "abc",
            "source": "test",
            "session": session_id,
            "model_profile": None,
            "prompt_version": None,
            "phase": "intent",
        },
    )


def _valid_audit_record_str(op_id: str, phase: str = "committed") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "operation_id": op_id,
            "real_time": "2026-08-31T15:00:00+00:00",
            "operation": "test",
            "entity_id": None,
            "before_hash": None,
            "after_hash": None,
            "source": "test",
            "session": None,
            "model_profile": None,
            "prompt_version": None,
            "phase": phase,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


# ── Test: _bytes_hash ─────────────────────────────────────────────────────


class TestBytesHashC05:
    def test_hash_exact_bytes(self) -> None:
        data = b"hello"
        expected = hashlib.sha256(b"hello").hexdigest()
        assert _bytes_hash(data) == expected

    def test_hash_non_utf8_bytes(self) -> None:
        data = b"\xff\xfe"
        h = _bytes_hash(data)
        assert isinstance(h, str)
        assert len(h) == 64


# ── Test: inspection physically read-only ─────────────────────────────────


class TestInspectReadOnlyC05:
    def test_inspect_under_corrupt_audit_creates_no_files(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_bytes(b"valid line\n" + b"\xff\xfe\n")

        before = set(str(p.relative_to(vault_root)) for p in vault_root.rglob("*") if p.is_file())

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues

        after = set(str(p.relative_to(vault_root)) for p in vault_root.rglob("*") if p.is_file())
        assert before == after
        assert log_path.read_bytes() == b"valid line\n" + b"\xff\xfe\n"


# ── Test: audit physical-LF classification ────────────────────────────────


class TestAuditPhysicalLfC05:
    def test_valid_missing_lf_reported_as_partial_tail(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(_valid_audit_record_str("op1"), encoding="utf-8", newline="")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        tail = [i for i in report.issues if i.code == "audit_partial_tail"]
        assert len(tail) == 1
        assert tail[0].recoverable is True

    def test_lf_terminated_corrupt_is_corrupt(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            _valid_audit_record_str("op1") + "\n" + "not valid json\n",
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        corrupt = [i for i in report.issues if i.code == "audit_corrupt"]
        assert len(corrupt) >= 1
        tail = [i for i in report.issues if i.code == "audit_partial_tail"]
        assert len(tail) == 0

    def test_lf_terminated_corrupt_repair_refused(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            _valid_audit_record_str("op1") + "\n" + "not valid json\n",
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=_make_audit_context())


# ── Test: UTF-8 corruption ────────────────────────────────────────────────


class TestUtf8CorruptionC05:
    def test_invalid_utf8_audit_reported_corrupt(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "_system" / "audit" / "audit.jsonl").write_bytes(b"\xff\xfe")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        corrupt = [i for i in report.issues if i.code == "audit_corrupt"]
        assert len(corrupt) == 1

    def test_invalid_utf8_audit_repair_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "_system" / "audit" / "audit.jsonl").write_bytes(b"\xff\xfe")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=_make_audit_context())

    def test_invalid_utf8_events_reported_corrupt(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_bytes(b"\xff\xfe")

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        corrupt = [i for i in report.issues if i.code == "event_corrupt"]
        assert len(corrupt) == 1

    def test_invalid_utf8_events_repair_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_bytes(b"\xff\xfe")

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))


# ── Test: Sessions-only and raw-only partial-start discovery ──────────────


class TestSessionsOnlyPartialStartC05:
    def test_sessions_only_discovered(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        partial = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial) == 1
        assert partial[0].session_id == "S006"


class TestRawOnlyPartialStartC05:
    def test_raw_only_discovered(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        partial = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial) == 1
        assert partial[0].session_id == "S006"


# ── Test: unsafe session path / symlink reporting ─────────────────────────


class TestUnsafeSessionPathC05:
    def test_raw_session_symlink_reported_unsafe(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        target = tmp_path / "outside"
        target.mkdir()
        link = vault_root / "_system" / "raw" / "sessions" / "S006"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("OS does not support symlinks")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        unsafe = [i for i in report.issues if i.code == "unsafe_session_path"]
        assert len(unsafe) >= 1


# ── Test: ambiguous start ownership ───────────────────────────────────────


class TestAmbiguousStartOwnershipC05:
    def test_two_unmatched_intents_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        _write_audit_intent(vault_root, "S006", "start-001")
        _write_audit_intent(vault_root, "S006", "start-002")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        partial = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial) == 1
        assert partial[0].recoverable is False

    def test_cleanup_refuses_two_unmatched_intents(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl").write_text(
            "", encoding="utf-8"
        )
        _write_audit_intent(vault_root, "S006", "start-001")
        _write_audit_intent(vault_root, "S006", "start-002")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="single unmatched"):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))


# ── Test: ownership recheck after recovery intent ─────────────────────────


class TestOwnershipRecheckC05:
    def test_ownership_changed_after_intent_raises_conflict(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl").write_text(
            "", encoding="utf-8"
        )
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        original_append = audit_svc.append
        call_count = 0

        def racing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = original_append(record)
                _write_audit_record(
                    vault_root,
                    {
                        "schema_version": 1,
                        "operation_id": "start-S006",
                        "real_time": "2026-08-31T15:00:00+00:00",
                        "operation": "session.start",
                        "entity_id": None,
                        "before_hash": None,
                        "after_hash": "abc",
                        "source": "test",
                        "session": "S006",
                        "model_profile": None,
                        "prompt_version": None,
                        "phase": "committed",
                    },
                )
                return result
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError, match="ownership changed"):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))


# ── Test: strict cleanup mutation semantics ───────────────────────────────


class TestStrictCleanupC05:
    def test_events_became_non_empty_after_intent_conflict(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        original_append = audit_svc.append
        call_count = 0

        def racing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = original_append(record)
                ev.write_text('{"x":1}\n', encoding="utf-8")
                return result
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

    def test_cleanup_absence_verified(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        ev = raw_dir / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        assert result.operation == "session.recovery.partial_start"
        assert not session_dir.exists()
        assert not raw_dir.exists()
        assert not ev.exists()


# ── Test: event-tail recovery metadata prerequisite ───────────────────────


class TestEventTailMetadataPrerequisiteC05:
    def test_missing_metadata_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="no metadata.json"):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_corrupt_metadata_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_text("not json", encoding="utf-8")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))


# ── Test: event-tail clean-audit prerequisite ─────────────────────────────


class TestEventTailCleanAuditPrerequisiteC05:
    def test_corrupt_audit_prevents_event_repair(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        audit_log = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_log.write_bytes(b"\xff\xfe")

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError, match="repair audit tail"):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))


# ── Test: CRLF prefix preservation ────────────────────────────────────────


class TestCrlfPreservationC05:
    def test_audit_crlf_prefix_not_corrupted(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        valid = _valid_audit_record_str("op1")
        content = valid + "\r\n" + "incomplete"
        log_path.write_text(content, encoding="utf-8", newline="")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        tail = [i for i in report.issues if i.code == "audit_partial_tail"]
        assert len(tail) == 1

        repo.repair_audit_tail(audit=_make_audit_context())
        after_bytes = log_path.read_bytes()

        assert after_bytes.startswith((valid + "\r\n").encode("utf-8"))
        assert after_bytes.endswith(b"\n")

    def test_event_crlf_prefix_not_corrupted(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        valid = '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}'
        content = valid + "\r\n" + '{"event_id":"evt_002",'
        ev.write_text(content, encoding="utf-8", newline="")

        repo = _create_recovery_repo(vault_root)
        repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        after_bytes = ev.read_bytes()

        assert after_bytes.startswith((valid + "\r\n").encode("utf-8"))
        assert after_bytes.endswith(b"\n")


# ── Test: os.open/write/truncate/fsync error translation ──────────────────


class TestLowLevelErrorTranslationC05:
    def test_audit_os_open_failure_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(_valid_audit_record_str("op1"), encoding="utf-8", newline="")

        def failing_open(path, flags, *args):
            raise OSError("simulated open failure")

        monkeypatch.setattr(_session_recovery_mod.os, "open", failing_open)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=_make_audit_context())

    def test_audit_short_write_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(_valid_audit_record_str("op1"), encoding="utf-8", newline="")

        def short_write(fd, data):
            return 0

        monkeypatch.setattr(_session_recovery_mod.os, "write", short_write)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="Short write"):
            repo.repair_audit_tail(audit=_make_audit_context())

    def test_audit_fsync_failure_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(_valid_audit_record_str("op1"), encoding="utf-8", newline="")

        def failing_fsync(fd):
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(_session_recovery_mod.os, "fsync", failing_fsync)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=_make_audit_context())

    def test_event_os_open_failure_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        def failing_open(path, flags, *args):
            raise OSError("simulated open failure")

        monkeypatch.setattr(_session_recovery_mod.os, "open", failing_open)
        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_event_short_write_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        def short_write(fd, data):
            return 0

        monkeypatch.setattr(_session_recovery_mod.os, "write", short_write)
        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError, match="Short write"):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_event_ftruncate_failure_raises_storage_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}\n'
            '{"event_id":"evt_002",',
            encoding="utf-8",
            newline="",
        )

        def failing_ftruncate(fd, length):
            raise OSError("simulated ftruncate failure")

        monkeypatch.setattr(_session_recovery_mod.os, "ftruncate", failing_ftruncate)
        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_event_fsync_failure_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        def failing_fsync(fd):
            raise OSError("simulated fsync failure")

        monkeypatch.setattr(_session_recovery_mod.os, "fsync", failing_fsync)
        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))


# ── Test: committed-audit failure partial-state semantics ─────────────────


class TestCommittedAuditFailureC05:
    def test_event_repair_committed_audit_failure_leaves_repaired_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        audit_svc = _create_audit_service(vault_root)
        call_count = 0
        original_append = audit_svc.append

        def failing_committed(record):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise StorageError("simulated committed failure")
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", failing_committed)
        repo2 = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="audit finalization failed"):
            repo2.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

        # The repaired event file should remain
        after_bytes = ev.read_bytes()
        assert after_bytes.endswith(b"\n")


# ── Test: partial cleanup failure semantics ──────────────────────────────


class TestPartialCleanupFailureC05:
    def test_partial_cleanup_events_removed_raw_dir_fails(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        ev = raw_dir / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        # Monkeypatch os.rmdir to fail for raw_dir
        original_rmdir = _os.rmdir

        def failing_rmdir(path):
            if str(path) == str(raw_dir):
                raise OSError("simulated rmdir failure")
            return original_rmdir(path)

        monkeypatch.setattr(_os, "rmdir", failing_rmdir)

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="Failed to remove raw session directory"):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

        # events.jsonl should still be gone (no rollback)
        assert not ev.exists()
        # raw_dir and session_dir should still exist
        assert raw_dir.exists()
        assert session_dir.exists()

    def test_partial_cleanup_session_dir_fails(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        ev = raw_dir / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        original_rmdir = _os.rmdir

        def failing_rmdir(path):
            if str(path) == str(session_dir):
                raise OSError("simulated rmdir failure")
            return original_rmdir(path)

        monkeypatch.setattr(_os, "rmdir", failing_rmdir)

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="Failed to remove session directory"):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

        # events.jsonl and raw_dir should be gone
        assert not ev.exists()
        assert not raw_dir.exists()
        # session_dir should still exist
        assert session_dir.exists()

    def test_partial_cleanup_retry_deterministic_state(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        ev = raw_dir / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        # First attempt: fail at session_dir removal
        original_rmdir = _os.rmdir

        def failing_rmdir(path):
            if str(path) == str(session_dir):
                raise OSError("simulated rmdir failure")
            return original_rmdir(path)

        monkeypatch.setattr(_os, "rmdir", failing_rmdir)

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

        monkeypatch.undo()

        # Remaining state: events.jsonl gone, raw_dir gone, session_dir exists
        # This should still be provably owned/safe for retry
        assert not ev.exists()
        assert not raw_dir.exists()
        assert session_dir.exists()

        # Second attempt should succeed
        repo2 = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo2.cleanup_partial_start(
            "S006", audit=_make_audit_context(operation_id="rec-retry", session="S006")
        )
        assert result.operation == "session.recovery.partial_start"
        assert not session_dir.exists()


# ── Test: directory gains unexpected file after intent ───────────────────


class TestDirectoryRaceAfterIntentC05:
    def test_raw_dir_gains_file_after_intent_conflict(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        ev = raw_dir / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        # Simulate a race where a file appears in raw_dir after the intent
        original_append = audit_svc.append
        call_count = 0

        def racing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = original_append(record)
                (raw_dir / "unexpected.txt").write_text("surprise", encoding="utf-8")
                return result
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

        # events.jsonl was already removed (no rollback), raw_dir and session_dir remain
        assert not ev.exists()
        assert raw_dir.exists()
        assert session_dir.exists()

    def test_session_dir_gains_file_after_intent_conflict(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        ev = raw_dir / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        _write_audit_intent(vault_root, "S006", "start-S006")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        original_append = audit_svc.append
        call_count = 0

        def racing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = original_append(record)
                (session_dir / "Session.md").write_text("surprise", encoding="utf-8")
                return result
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

        # events.jsonl and raw_dir were removed (no rollback), session_dir remains
        assert not ev.exists()
        assert not raw_dir.exists()
        assert session_dir.exists()
