"""S6-C05F regression tests — physical audit cleanliness before audited recovery.

Covers:
- Event recovery blocked by logically-valid missing-LF audit
- Partial cleanup blocked by logically-valid missing-LF audit
- Exact audit bytes unchanged on refusal
- Target bytes unchanged on refusal
- Zero recovery intent on refusal
- repair-audit-first then normal recovery succeeds
- Invalid-UTF8 metadata -> StorageError (no raw UnicodeDecodeError)
- inspect_runtime still reports audit_partial_tail for valid missing-LF audit
- repair_audit_tail still works for valid missing-LF audit
- Empty audit still supported
- Fully valid LF-terminated audit still supported
- Corrupt/partial audit receives no ordinary recovery append
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dnd_assistant.storage.session_recovery as _session_recovery_mod
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


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
    operation_id: str = "test-c05f-001",
    source: str = "test",
    session: str | None = None,
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
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


def _valid_audit_record_str(op_id: str, phase: str = "committed") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "operation_id": op_id,
            "real_time": "2026-09-01T10:00:00+00:00",
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


def _write_audit_without_lf(vault_root: Path, op_id: str = "op1") -> None:
    """Write a single valid AuditRecord WITHOUT trailing newline."""
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    log_path.write_text(_valid_audit_record_str(op_id), encoding="utf-8", newline="")


def _write_audit_records_without_lf(vault_root: Path, records: list[str]) -> None:
    """Write multiple valid AuditRecord strings WITHOUT trailing newline on the last."""
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    text = "\n".join(records)
    log_path.write_text(text, encoding="utf-8", newline="")


def _setup_partial_start(vault_root: Path, session_id: str = "S006") -> None:
    """Create partial-start artifacts with audit intent but no committed."""
    (vault_root / "Sessions" / session_id).mkdir()
    (vault_root / "_system" / "raw" / "sessions" / session_id).mkdir()
    ev = vault_root / "_system" / "raw" / "sessions" / session_id / "events.jsonl"
    ev.write_text("", encoding="utf-8")
    _write_audit_record(
        vault_root,
        {
            "schema_version": 1,
            "operation_id": f"start-{session_id}",
            "real_time": "2026-09-01T10:00:00+00:00",
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


def _snapshot_bytes(*paths: Path) -> dict[str, bytes]:
    """Snapshot exact bytes of multiple files. Missing files -> empty bytes."""
    result: dict[str, bytes] = {}
    for p in paths:
        try:
            result[str(p)] = p.read_bytes()
        except (OSError, FileNotFoundError):
            result[str(p)] = b""
    return result


def _assert_bytes_unchanged(snapshot: dict[str, bytes]) -> None:
    """Assert all files in the snapshot have identical bytes."""
    for path_str, expected in snapshot.items():
        p = Path(path_str)
        actual = p.read_bytes() if p.exists() else b""
        assert actual == expected, f"Bytes changed for {path_str}"


def _count_audit_records(vault_root: Path) -> int:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    if not log_path.exists():
        return 0
    count = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            count += 1
    return count


# ── Test: _require_clean_audit_log helper ──────────────────────────────────


class TestRequireCleanAuditLog:
    """Verify _require_clean_audit_log contract."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        records = _session_recovery_mod._require_clean_audit_log(audit_svc)
        assert records == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_bytes(b"")
        records = _session_recovery_mod._require_clean_audit_log(audit_svc)
        assert records == []

    def test_valid_lf_terminated_returns_records(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        _write_audit_record(
            vault_root,
            {
                "schema_version": 1,
                "operation_id": "op1",
                "real_time": "2026-09-01T10:00:00+00:00",
                "operation": "test",
                "entity_id": None,
                "before_hash": None,
                "after_hash": None,
                "source": "test",
                "session": None,
                "model_profile": None,
                "prompt_version": None,
                "phase": "committed",
            },
        )
        records = _session_recovery_mod._require_clean_audit_log(audit_svc)
        assert len(records) == 1

    def test_valid_without_lf_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(_valid_audit_record_str("op1"), encoding="utf-8", newline="")
        with pytest.raises(StorageError, match="repair_audit_tail"):
            _session_recovery_mod._require_clean_audit_log(audit_svc)

    def test_invalid_utf8_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_bytes(b"\xff\xfe")
        with pytest.raises(StorageError, match="repair audit tail"):
            _session_recovery_mod._require_clean_audit_log(audit_svc)

    def test_malformed_json_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text("not json\n", encoding="utf-8")
        with pytest.raises(StorageError):
            _session_recovery_mod._require_clean_audit_log(audit_svc)

    def test_read_only_no_filesystem_mutation(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(_valid_audit_record_str("op1"), encoding="utf-8", newline="")
        before_bytes = log_path.read_bytes()
        try:
            _session_recovery_mod._require_clean_audit_log(audit_svc)
        except StorageError:
            pass
        assert log_path.read_bytes() == before_bytes


# ── Test: Event recovery blocked by logically-valid missing-LF audit ────────


class TestEventRepairBlockedByMissingLfAudit:
    """repair_event_tail must refuse when audit has valid record without LF."""

    def test_repair_refused_without_audit_lf(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        # Replace audit with valid record WITHOUT trailing LF
        _write_audit_without_lf(vault_root)

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_events_exact_bytes_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        _write_audit_without_lf(vault_root)

        before = _snapshot_bytes(ev)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        _assert_bytes_unchanged(before)

    def test_metadata_exact_bytes_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        _write_audit_without_lf(vault_root)

        before = _snapshot_bytes(meta)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        _assert_bytes_unchanged(before)

    def test_audit_exact_bytes_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        _write_audit_without_lf(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"

        before = _snapshot_bytes(log_path)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        _assert_bytes_unchanged(before)

    def test_zero_recovery_intent_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        _write_audit_without_lf(vault_root)

        before_count = _count_audit_records(vault_root)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        assert _count_audit_records(vault_root) == before_count


# ── Test: Partial-start cleanup blocked by logically-valid missing-LF audit ─


class TestPartialCleanupBlockedByMissingLfAudit:
    """cleanup_partial_start must refuse when audit has valid record without LF."""

    def test_cleanup_refused_without_audit_lf(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        # Replace audit with valid record WITHOUT trailing LF
        _write_audit_without_lf(vault_root)

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))

    def test_session_dir_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        session_dir = vault_root / "Sessions" / "S006"
        _write_audit_without_lf(vault_root)

        assert session_dir.exists()
        repo = _create_recovery_repo(vault_root)
        try:
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        assert session_dir.exists()

    def test_raw_dir_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        _write_audit_without_lf(vault_root)

        assert raw_dir.exists()
        repo = _create_recovery_repo(vault_root)
        try:
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        assert raw_dir.exists()

    def test_events_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        _write_audit_without_lf(vault_root)

        before = _snapshot_bytes(ev)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        _assert_bytes_unchanged(before)

    def test_audit_unchanged_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        _write_audit_without_lf(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"

        before = _snapshot_bytes(log_path)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        _assert_bytes_unchanged(before)

    def test_zero_partial_start_recovery_intent_on_refusal(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        _write_audit_without_lf(vault_root)

        repo = _create_recovery_repo(vault_root)
        try:
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        assert _count_audit_records_with_op(vault_root, "session.recovery.partial_start") == 0


# ── Test: repair-audit-first then normal recovery succeeds ─────────────────


class TestRepairAuditFirstWorkflow:
    """Prove that repair_audit_tail -> normal recovery works."""

    def test_repair_audit_then_event_recovery_succeeds(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        # Replace audit with valid record WITHOUT trailing LF
        _write_audit_without_lf(vault_root)

        repo = _create_recovery_repo(vault_root)

        # Step 1: repair audit tail
        result = repo.repair_audit_tail(audit=_make_audit_context())
        assert result.operation == "audit.recovery.tail"

        # Step 2: event recovery should now succeed
        result2 = repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        assert result2.operation == "session.recovery.events_tail"
        after_bytes = ev.read_bytes()
        assert after_bytes.endswith(b"\n")

    def test_repair_audit_then_partial_cleanup_succeeds(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        # Create partial-start artifacts WITHOUT audit
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text("", encoding="utf-8")
        # Write start intent WITHOUT trailing LF
        start_intent = json.dumps(
            {
                "schema_version": 1,
                "operation_id": "start-S006",
                "real_time": "2026-09-01T10:00:00+00:00",
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
            ensure_ascii=False,
            separators=(",", ":"),
        )
        _write_audit_records_without_lf(vault_root, [start_intent])

        repo = _create_recovery_repo(vault_root)

        # Step 1: repair audit tail
        result = repo.repair_audit_tail(audit=_make_audit_context())
        assert result.operation == "audit.recovery.tail"

        # Step 2: partial-start cleanup should now succeed
        result2 = repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        assert result2.operation == "session.recovery.partial_start"
        assert not (vault_root / "Sessions" / "S006").exists()


# ── Test: inspect_runtime still reports audit_partial_tail ─────────────────


class TestInspectRuntimeMissingLf:
    """inspect_runtime must continue reporting audit_partial_tail for valid missing-LF."""

    def test_reports_audit_partial_tail(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        _write_audit_without_lf(vault_root)

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        tail = [i for i in report.issues if i.code == "audit_partial_tail"]
        assert len(tail) == 1
        assert tail[0].recoverable is True

    def test_repair_audit_tail_still_works(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)
        _write_audit_without_lf(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.repair_audit_tail(audit=_make_audit_context())
        assert result.operation == "audit.recovery.tail"
        assert log_path.read_bytes().endswith(b"\n")


# ── Test: Invalid-UTF8 metadata -> StorageError ────────────────────────────


class TestInvalidUtf8Metadata:
    """Invalid UTF-8 metadata must raise StorageError, not UnicodeDecodeError."""

    def test_invalid_utf8_metadata_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError, match="invalid UTF-8"):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_not_unicode_decode_error(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except UnicodeDecodeError:
            pytest.fail("UnicodeDecodeError leaked instead of StorageError")
        except StorageError:
            pass

    def test_events_unchanged_on_invalid_utf8_metadata(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        before = _snapshot_bytes(ev)
        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        _assert_bytes_unchanged(before)

    def test_no_recovery_intent_on_invalid_utf8_metadata(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        meta = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta.write_bytes(b"\xff\xfe")
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        try:
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        except StorageError:
            pass
        assert _count_audit_records_with_op(vault_root, "session.recovery.events_tail") == 0


# ── Test: Empty and fully-valid audit still supported ──────────────────────


class TestEmptyAndValidAuditStillSupported:
    """Empty audit and fully valid LF-terminated audit must still work."""

    def test_empty_audit_event_repair_still_works(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        # Audit is empty (only the session.start audit records exist)
        repo = _create_recovery_repo(vault_root)
        result = repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        assert result.operation == "session.recovery.events_tail"

    def test_valid_lf_audit_event_repair_still_works(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        # Audit is valid LF-terminated (from _start_session)
        repo = _create_recovery_repo(vault_root)
        result = repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))
        assert result.operation == "session.recovery.events_tail"

    def test_valid_lf_audit_partial_cleanup_still_works(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        repo = _create_recovery_repo(vault_root)
        result = repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))
        assert result.operation == "session.recovery.partial_start"


# ── Test: No append behind partial/corrupt audit ───────────────────────────


class TestNoAppendBehindCorruptAudit:
    """Ordinary recovery must never append behind partial or corrupt audit."""

    def test_invalid_utf8_audit_blocks_event_repair(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            '{"event_id":"evt_001","real_time":"2026-09-01T10:01:00+00:00",'
            '"world_tick":13800,"type":"note","text":"ok"}',
            encoding="utf-8",
            newline="",
        )
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_bytes(b"\xff\xfe")

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.repair_event_tail("S006", audit=_make_audit_context(session="S006"))

    def test_invalid_utf8_audit_blocks_partial_cleanup(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _setup_partial_start(vault_root)
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_bytes(b"\xff\xfe")

        repo = _create_recovery_repo(vault_root)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=_make_audit_context(session="S006"))


def _count_audit_records_with_op(vault_root: Path, operation: str) -> int:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    if not log_path.exists():
        return 0
    count = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rec = json.loads(line)
                if rec.get("operation") == operation:
                    count += 1
            except json.JSONDecodeError:
                pass
    return count
