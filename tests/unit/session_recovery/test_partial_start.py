"""Tests for partial-start ownership verification and cleanup.

Covers:
- Safe partial start cleanup
- Only known-empty artifacts removed
- Other sessions untouched
- Unexpected file prevents cleanup
- Non-empty events prevents cleanup
- Missing intent prevents cleanup
- Recovery audit intent and committed records
- Exact before/after composite hash
- Intent failure zero cleanup
"""

from __future__ import annotations

import os as _os
from pathlib import Path

import pytest

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditService as _AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)
from tests.unit.session_recovery.conftest import (
    make_audit_context,
    make_audit_record,
    make_session,
    start_session,
    valid_audit_record_str,
    valid_event_record_str,
)


def _setup_partial_start(vault_root: Path, audit_svc) -> None:
    """Create a partial start with one unmatched session.start intent."""
    (vault_root / "Sessions" / "S006").mkdir()
    (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
    ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
    ev.write_text("", encoding="utf-8", newline="")
    ctx = make_audit_context(operation_id="start-op-001", session="S006")
    audit_svc.append(
        make_audit_record(
            ctx,
            operation="session.start",
            phase="intent",
        )
    )


def _setup_dual_unmatched_intent(vault_root: Path, audit_svc) -> None:
    """Create a partial start with two unmatched intents."""
    (vault_root / "Sessions" / "S006").mkdir()
    (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
    ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
    ev.write_text("", encoding="utf-8", newline="")
    for op_id in ("start-op-001", "start-op-002"):
        ctx = make_audit_context(operation_id=op_id, session="S006")
        audit_svc.append(
            make_audit_record(
                ctx,
                operation="session.start",
                phase="intent",
            )
        )


def _start_session_meta(vault_root: Path, session_id: str = "S007") -> None:
    """Create a fully started session with metadata."""
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_svc = _AuditService(log_path=log_path)
    meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    session = make_session(id=session_id, status="active")
    meta_repo.create_session(
        session,
        audit=make_audit_context(operation_id=f"start-{session_id}"),
    )


class TestCleanupPartialStart:
    """Successful partial start cleanup."""

    def test_cleanup_safe_partial_start_succeeds(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert result.operation == "session.recovery.partial_start"
        assert result.session_id == "S006"
        assert not (vault_root / "Sessions" / "S006").exists()
        assert not (vault_root / "_system" / "raw" / "sessions" / "S006").exists()

    def test_cleanup_only_known_empty_artifacts_removed(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        (vault_root / "Sessions" / "S007").mkdir()
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert (vault_root / "Sessions" / "S007").exists()

    def test_cleanup_other_sessions_untouched(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        _start_session_meta(vault_root, session_id="S007")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert (vault_root / "Sessions" / "S007").exists()


class TestCleanupPartialStartFailures:
    """Conditions that prevent partial start cleanup."""

    def test_unexpected_file_prevents_cleanup(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        (vault_root / "Sessions" / "S006" / "unexpected.txt").write_text("x")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="unexpected content"):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_non_empty_events_prevents_cleanup(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text('{"dummy":true}\n', encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="unexpected content"):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_missing_intent_prevents_cleanup(self, vault_root: Path, audit_svc) -> None:
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text("", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="No single unmatched"):
            repo.cleanup_partial_start("S006", audit=make_audit_context())


class TestCleanupPartialStartAudit:
    """Audit trail for partial start cleanup."""

    def test_recovery_audit_intent_and_committed(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start("S006", audit=make_audit_context(operation_id="rec-001"))
        records = audit_svc.read_all()
        assert len(records) >= 2
        intent = next(
            r
            for r in records
            if r.phase == "intent" and r.operation == "session.recovery.partial_start"
        )
        committed = next(
            r
            for r in records
            if r.phase == "committed" and r.operation == "session.recovery.partial_start"
        )
        assert intent is not None
        assert committed is not None

    def test_exact_before_after_composite_hash(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        result = repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert result.before_hash is not None
        assert result.after_hash is not None
        assert result.before_hash != result.after_hash

    def test_intent_failure_zero_cleanup(self, vault_root: Path, audit_svc, monkeypatch) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        def failing_append(record):
            raise StorageError("simulated append failure")

        monkeypatch.setattr(audit_svc, "append", failing_append)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert (vault_root / "Sessions" / "S006").exists()


class TestAmbiguousStartOwnershipC05:
    """Ambiguous start ownership."""

    def test_cleanup_refuses_two_unmatched_intents(self, vault_root: Path, audit_svc) -> None:
        _setup_dual_unmatched_intent(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="No single unmatched"):
            repo.cleanup_partial_start("S006", audit=make_audit_context())


class TestOwnershipRecheckC05:
    """Ownership recheck after intent."""

    def test_ownership_changed_after_intent_raises_conflict(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        call_count = 0

        original_append = audit_svc.append

        def racing_append(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                ctx2 = make_audit_context(operation_id="start-op-002", session="S006")
                original_append(
                    make_audit_record(
                        ctx2,
                        operation="session.start",
                        phase="intent",
                    )
                )
            return original_append(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError, match="ownership changed"):
            repo.cleanup_partial_start("S006", audit=make_audit_context())


class TestStrictCleanupC05:
    """Strict cleanup semantics."""

    def test_events_became_non_empty_after_intent_conflict(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"

        original_append2 = audit_svc.append

        def racing_append(record):
            ev.write_text('{"dummy":true}\n', encoding="utf-8", newline="")
            return original_append2(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_cleanup_absence_verified(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert not (vault_root / "Sessions" / "S006").exists()
        assert not (vault_root / "_system" / "raw" / "sessions" / "S006").exists()


class TestPartialCleanupFailureC05:
    """Partial cleanup failure handling."""

    def test_partial_cleanup_events_removed_raw_dir_fails(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        original_rmdir = _os.rmdir

        def failing_rmdir(path):
            if "raw" in str(path):
                raise OSError("simulated rmdir failure")
            return original_rmdir(path)

        monkeypatch.setattr(_os, "rmdir", failing_rmdir)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_partial_cleanup_session_dir_fails(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        original_rmdir = _os.rmdir

        def failing_rmdir(path):
            if "Sessions" in str(path) and path.name == "S006":
                raise OSError("simulated rmdir failure")
            return original_rmdir(path)

        monkeypatch.setattr(_os, "rmdir", failing_rmdir)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_partial_cleanup_retry_deterministic_state(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        call_count = 0
        original_rmdir = _os.rmdir

        def failing_then_ok_rmdir(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1 and "raw" in str(path):
                raise OSError("simulated rmdir failure")
            return original_rmdir(path)

        monkeypatch.setattr(_os, "rmdir", failing_then_ok_rmdir)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        assert not ev.exists()


class TestDirectoryRaceAfterIntentC05:
    """Directory race conditions after intent."""

    def test_raw_dir_gains_file_after_intent_conflict(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)

        original_append3 = audit_svc.append

        def racing_append(record):
            (vault_root / "_system" / "raw" / "sessions" / "S006" / "unexpected.txt").write_text(
                "x"
            )
            return original_append3(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_session_dir_gains_file_after_intent_conflict(
        self, vault_root: Path, audit_svc, monkeypatch
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        original_append4 = audit_svc.append

        def racing_append(record):
            (vault_root / "Sessions" / "S006" / "unexpected.txt").write_text("x")
            return original_append4(record)

        monkeypatch.setattr(audit_svc, "append", racing_append)
        with pytest.raises(ConflictError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())


class TestPartialCleanupBlockedByMissingLfAudit:
    """Partial cleanup blocked by missing LF in audit."""

    def test_cleanup_refused_without_audit_lf(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError, match="repair_audit_tail"):
            repo.cleanup_partial_start("S006", audit=make_audit_context())

    def test_session_dir_unchanged_on_refusal(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert (vault_root / "Sessions" / "S006").exists()

    def test_raw_dir_unchanged_on_refusal(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert (vault_root / "_system" / "raw" / "sessions" / "S006").exists()

    def test_events_unchanged_on_refusal(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        assert ev.exists()

    def test_audit_unchanged_on_refusal(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        assert audit_svc.log_path.exists()

    def test_zero_partial_start_recovery_intent_on_refusal(
        self, vault_root: Path, audit_svc
    ) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
        records = audit_svc.read_all()
        assert not any(r.operation == "session.recovery.partial_start" for r in records)


class TestRepairAuditFirstWorkflowC05F:
    """Prove that repair_audit_tail -> normal recovery works."""

    def test_repair_audit_then_partial_cleanup_succeeds(self, vault_root: Path, audit_svc) -> None:
        # Create partial-start artifacts
        (vault_root / "Sessions" / "S006").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text("", encoding="utf-8", newline="")
        # Write start intent WITHOUT trailing LF (single record, no LF)
        import json

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
        audit_svc.log_path.write_text(start_intent, encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        # Step 1: repair audit tail
        result = repo.repair_audit_tail(audit=make_audit_context())
        assert result.operation == "audit.recovery.tail"
        # Step 2: partial-start cleanup should now succeed
        result2 = repo.cleanup_partial_start("S006", audit=make_audit_context(session="S006"))
        assert result2.operation == "session.recovery.partial_start"
        assert not (vault_root / "Sessions" / "S006").exists()

    def test_repair_audit_then_event_recovery_succeeds(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        # Replace audit with valid record WITHOUT trailing LF
        audit_svc.log_path.write_text(
            valid_audit_record_str("orphan"), encoding="utf-8", newline=""
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        # Step 1: repair audit tail
        result = repo.repair_audit_tail(audit=make_audit_context())
        assert result.operation == "audit.recovery.tail"
        # Step 2: event recovery should now succeed
        result2 = repo.repair_event_tail("S006", audit=make_audit_context(session="S006"))
        assert result2.operation == "session.recovery.events_tail"
        assert ev.read_bytes().endswith(b"\n")


class TestNoAppendBehindCorruptAuditPartialC05F:
    """Partial cleanup must never append behind corrupt audit."""

    def test_invalid_utf8_audit_blocks_partial_cleanup(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start(vault_root, audit_svc)
        audit_svc.log_path.write_bytes(b"\xff\xfe")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        with pytest.raises(StorageError):
            repo.cleanup_partial_start("S006", audit=make_audit_context())
