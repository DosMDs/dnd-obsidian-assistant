"""S6-05 failure-path tests — session recovery failure semantics.

Covers:
- cleanup_partial_start success and failure paths
- cleanup_partial_start audit semantics
- repair_event_tail success and failure paths
- repair_event_tail audit and race semantics
- repair_audit_tail success and failure paths
- repair_audit_tail marker semantics
"""

from __future__ import annotations

import json
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


def _make_audit_context(operation_id="test-rec-001", source="test", session=None):
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


def _read_audit_records(vault_root: Path) -> list[dict]:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    if not log_path.exists():
        return []
    records: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _setup_partial_start(vault_root: Path) -> tuple[Path, Path]:
    session_dir = vault_root / "Sessions" / "S006"
    session_dir.mkdir()
    raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
    raw_dir.mkdir()
    (raw_dir / "events.jsonl").write_text("", encoding="utf-8")
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
            "phase": "intent",
        },
    )
    return session_dir, raw_dir


# ── cleanup_partial_start — success ────────────────────────────────────────────


class TestCleanupPartialStart:
    def test_cleanup_safe_partial_start_succeeds(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir, raw_dir = _setup_partial_start(vault_root)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.cleanup_partial_start(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        assert result.operation == "session.recovery.partial_start"
        assert result.session_id == "S006"
        assert result.before_hash is not None
        assert result.after_hash is not None
        assert not session_dir.exists()
        assert not raw_dir.exists()

    def test_cleanup_only_known_empty_artifacts_removed(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        _setup_partial_start(vault_root)
        other_file = vault_root / "Sessions" / "other.txt"
        other_file.write_text("untouched", encoding="utf-8")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        assert other_file.exists()
        assert other_file.read_text(encoding="utf-8") == "untouched"

    def test_cleanup_other_sessions_untouched(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(id="S005"),
            audit=_make_audit_context(operation_id="start-S005", session="S005"),
        )
        _setup_partial_start(vault_root)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        assert (vault_root / "_system" / "raw" / "sessions" / "S005" / "metadata.json").exists()


# ── cleanup_partial_start — failures ───────────────────────────────────────────


class TestCleanupPartialStartFailures:
    def test_unexpected_file_prevents_cleanup(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "Sessions" / "S006" / "Session.md").write_text("unexpected", encoding="utf-8")
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
                "phase": "intent",
            },
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="unexpected content"):
            repo.cleanup_partial_start(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )

    def test_non_empty_events_prevents_cleanup(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        (raw_dir / "events.jsonl").write_text('{"event_id":"evt_001"}\n', encoding="utf-8")
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
                "phase": "intent",
            },
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="unexpected content"):
            repo.cleanup_partial_start(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )

    def test_missing_intent_prevents_cleanup(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        (vault_root / "Sessions" / "S006").mkdir()
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="No unmatched session.start intent"):
            repo.cleanup_partial_start(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )


# ── cleanup_partial_start — audit ──────────────────────────────────────────────


class TestCleanupPartialStartAudit:
    def test_recovery_audit_intent_and_committed(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        _setup_partial_start(vault_root)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        records = _read_audit_records(vault_root)
        intent = [
            r
            for r in records
            if r.get("phase") == "intent" and r.get("operation") == "session.recovery.partial_start"
        ]
        committed = [
            r
            for r in records
            if r.get("phase") == "committed"
            and r.get("operation") == "session.recovery.partial_start"
        ]
        assert len(intent) == 1
        assert len(committed) == 1

    def test_exact_before_after_composite_hash(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        _setup_partial_start(vault_root)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.cleanup_partial_start(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        assert result.before_hash is not None
        assert result.after_hash is not None
        assert result.before_hash != result.after_hash

    def test_intent_failure_zero_cleanup(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        session_dir, raw_dir = _setup_partial_start(vault_root)
        call_count = 0
        original_append = audit_svc.append

        def failing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise StorageError("simulated audit intent failure")
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", failing_append)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )
        assert session_dir.exists()
        assert raw_dir.exists()


# ── repair_event_tail — success ────────────────────────────────────────────────


class TestEventTailRepair:
    def test_valid_event_missing_lf_appends_lf(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        valid_line = '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"hello"}'
        events_path.write_text(valid_line, encoding="utf-8", newline="")
        before_bytes = events_path.read_bytes()
        assert not before_bytes.endswith(b"\n")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )

        after_bytes = events_path.read_bytes()
        assert after_bytes.endswith(b"\n")
        assert after_bytes == before_bytes + b"\n"
        assert result.before_hash is not None
        assert result.after_hash is not None

    def test_invalid_partial_tail_truncated(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        valid_line = '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}\n'
        events_path.write_text(valid_line + '{"event_id":"evt_002",', encoding="utf-8", newline="")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_event_tail(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )

        after_text = events_path.read_text(encoding="utf-8")
        assert after_text == valid_line
        assert after_text.endswith("\n")

    def test_clean_log_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}\n',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="already valid"):
            repo.repair_event_tail(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )

    def test_corrupt_middle_line_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}\n'
            "not json\n"
            '{"event_id":"evt_002","real_time":"2026-08-31T15:02:00+00:00","world_tick":13801,"type":"note","text":"bad"}\n',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="not limited to the final tail"):
            repo.repair_event_tail(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )


# ── repair_event_tail — audit ──────────────────────────────────────────────────


class TestEventTailRepairAudit:
    def test_intent_and_committed_audit(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_event_tail(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        records = _read_audit_records(vault_root)
        intent = [
            r
            for r in records
            if r.get("phase") == "intent" and r.get("operation") == "session.recovery.events_tail"
        ]
        committed = [
            r
            for r in records
            if r.get("phase") == "committed"
            and r.get("operation") == "session.recovery.events_tail"
        ]
        assert len(intent) == 1
        assert len(committed) == 1

    def test_exact_before_after_hash(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_event_tail(
            "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
        )
        assert result.before_hash is not None
        assert result.after_hash is not None
        assert result.before_hash != result.after_hash

    def test_intent_failure_bytes_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta_repo.create_session(
            _active_session(), audit=_make_audit_context(operation_id="start", session="S006")
        )
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        before_bytes = events_path.read_bytes()
        call_count = 0
        original_append = audit_svc.append

        def failing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise StorageError("simulated audit intent failure")
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", failing_append)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_event_tail(
                "S006", audit=_make_audit_context(operation_id="rec-001", session="S006")
            )
        assert events_path.read_bytes() == before_bytes


# ── repair_audit_tail — success ────────────────────────────────────────────────


class TestAuditTailRepair:
    def test_valid_record_missing_lf_appends_lf(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        valid = '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
        log_path.write_text(
            valid
            + '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}',
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_audit_tail(audit=_make_audit_context(operation_id="rec-001"))

        after_bytes = log_path.read_bytes()
        assert after_bytes.endswith(b"\n")
        assert result.before_hash is not None
        assert result.after_hash is not None

    def test_invalid_incomplete_tail_truncated(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        valid = '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
        log_path.write_text(valid + '{"schema_version":1,', encoding="utf-8", newline="")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_audit_tail(audit=_make_audit_context(operation_id="rec-001"))

        after_text = log_path.read_text(encoding="utf-8")
        # The valid record is preserved; the recovery marker is appended after it
        assert after_text.startswith(valid)
        assert "audit.recovery.tail" in after_text
        assert after_text.endswith("\n")

    def test_malformed_completed_line_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
            "not valid json\n"
            '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.repair_audit_tail(audit=_make_audit_context(operation_id="rec-001"))


# ── repair_audit_tail — marker ─────────────────────────────────────────────────


class TestAuditTailRepairMarker:
    def test_recovery_marker_correct_semantics(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        valid = '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
        log_path.write_text(
            valid
            + '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}',
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.repair_audit_tail(audit=_make_audit_context(operation_id="rec-001"))

        records = _read_audit_records(vault_root)
        markers = [r for r in records if r.get("operation") == "audit.recovery.tail"]
        assert len(markers) == 1
        assert markers[0]["phase"] == "committed"
        assert markers[0]["session"] is None
        assert markers[0]["entity_id"] is None
        assert markers[0]["before_hash"] is not None
        assert markers[0]["after_hash"] is not None

    def test_race_before_repair_raises_conflict(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        # Simulate a race by modifying the audit log between the first and
        # second read via monkeypatching the module-level function
        original_read = _session_recovery_mod._read_exact_bytes
        call_count = 0

        def racing_read(path):
            nonlocal call_count
            call_count += 1
            if call_count == 2 and path == log_path:
                log_path.write_text(
                    '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
                    '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n',
                    encoding="utf-8",
                    newline="",
                )
            return original_read(path)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(_session_recovery_mod, "_read_exact_bytes", racing_read)
        try:
            with pytest.raises(ConflictError):
                repo.repair_audit_tail(audit=_make_audit_context(operation_id="rec-001"))
        finally:
            monkeypatch.undo()

    def test_marker_append_failure_leaves_repaired_audit(self, tmp_path: Path, monkeypatch) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        valid = '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
        log_path.write_text(
            valid
            + '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00","operation":"test","entity_id":null,"before_hash":null,"after_hash":null,"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}',
            encoding="utf-8",
            newline="",
        )

        call_count = 0
        original_append = audit_svc.append

        def failing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count > 0:
                if (
                    hasattr(record, "operation")
                    and getattr(record, "operation", None) == "audit.recovery.tail"
                ):
                    raise StorageError("simulated marker append failure")
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", failing_append)

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="recovery marker append failed"):
            repo.repair_audit_tail(audit=_make_audit_context(operation_id="rec-001"))

        # The repaired audit log should still be valid
        after_text = log_path.read_text(encoding="utf-8")
        assert after_text.endswith("\n")
        # read_all should succeed
        audit_svc.read_all()
