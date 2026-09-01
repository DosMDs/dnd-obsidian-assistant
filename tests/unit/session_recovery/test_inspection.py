"""Tests for read-only session runtime inspection.

Covers:
- Inspect does not create files
- Clean active/completed session detection
- Partial start detection (recoverable, no intent, unexpected content)
- Event tail detection (missing LF, incomplete, corrupt)
- Metadata corruption detection
- Multiple active sessions detection
- Unresolved audit intents detection
- UTF-8 corruption in events
- Sessions-only and raw-only partial start discovery
- Unsafe session path detection
- Ambiguous start ownership
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)
from tests.unit.session_recovery.conftest import (
    make_audit_context,
    make_audit_record,
    start_session,
    valid_event_line,
    valid_event_record_str,
)

# ── Inspect read-only ─────────────────────────────────────────────────────────


class TestInspectReadOnly:
    """Inspect must not create any files."""

    def test_inspect_does_not_create_files(self, vault_root: Path, audit_svc) -> None:
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        before = set(vault_root.rglob("*"))
        repo.inspect_runtime()
        after = set(vault_root.rglob("*"))
        assert before == after

    def test_inspect_clean_active_session(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert not report.has_issues

    def test_inspect_clean_completed_session(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root, status="completed")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert not report.has_issues


# ── Partial start detection ───────────────────────────────────────────────────


class TestPartialStartDetection:
    """Partial start detection scenarios."""

    def test_partial_start_with_intent_recoverable(self, vault_root: Path, audit_svc) -> None:
        _setup_partial_start_with_intent(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        issue = next(i for i in report.issues if i.code == "partial_start")
        assert issue.recoverable is True

    def test_partial_start_without_intent_not_recoverable(
        self, vault_root: Path, audit_svc
    ) -> None:
        _setup_partial_start_no_intent(vault_root)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        issue = next(i for i in report.issues if i.code == "partial_start")
        assert issue.recoverable is False

    def test_partial_start_with_unexpected_file_not_recoverable(
        self, vault_root: Path, audit_svc
    ) -> None:
        _setup_partial_start_with_intent(vault_root, audit_svc)
        (vault_root / "Sessions" / "S006" / "unexpected.txt").write_text("x")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        issue = next(i for i in report.issues if i.code == "partial_start")
        assert issue.recoverable is False

    def test_partial_start_with_non_empty_events_not_recoverable(
        self, vault_root: Path, audit_svc
    ) -> None:
        _setup_partial_start_with_intent(vault_root, audit_svc)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text('{"dummy":true}\n', encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        issue = next(i for i in report.issues if i.code == "partial_start")
        assert issue.recoverable is False


# ── Event tail detection ──────────────────────────────────────────────────────


class TestEventTailDetection:
    """Event log inspection classification."""

    def test_event_missing_lf_recoverable(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(valid_event_record_str("evt_001"), encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "event_partial_tail" in codes

    def test_event_incomplete_tail_recoverable(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            valid_event_line("evt_001") + '{"incomplete"',
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "event_partial_tail" in codes

    def test_event_middle_line_corrupt_not_recoverable(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            valid_event_line("evt_001") + "corrupt\n" + valid_event_line("evt_002"),
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "event_corrupt" in codes

    def test_duplicate_event_ids_not_recoverable(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_text(
            valid_event_line("evt_001") + valid_event_line("evt_001"),
            encoding="utf-8",
            newline="",
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "event_corrupt" in codes


# ── Metadata corruption ───────────────────────────────────────────────────────


class TestMetadataCorruption:
    """Corrupt metadata detection."""

    def test_corrupt_metadata_detected(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta_path.write_text("not json", encoding="utf-8", newline="")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "metadata_corrupt" in codes


# ── Multiple active sessions ──────────────────────────────────────────────────


class TestMultipleActiveSessions:
    """Multiple active session detection."""

    def test_two_active_sessions_detected(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root, session_id="S006")
        start_session(vault_root, session_id="S007")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "multiple_active_sessions" in codes


# ── Unresolved audit intents ──────────────────────────────────────────────────


class TestUnresolvedAuditIntents:
    """Unresolved audit intent detection."""

    def test_unresolved_intent_detected(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ctx = make_audit_context(operation_id="unresolved-op", session="S006")
        audit_svc.append(
            make_audit_record(
                ctx,
                operation="session.note",
                phase="intent",
            )
        )
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "unresolved_audit_intent" in codes


# ── Sessions-only and raw-only partial start ──────────────────────────────────


class TestSessionsOnlyPartialStartC05:
    """Partial start discovered from Sessions/ only — no raw session directory."""

    def test_sessions_only_discovered(self, vault_root: Path, audit_svc) -> None:
        _setup_sessions_only_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        # Verify raw session directory does NOT exist
        assert not (vault_root / "_system" / "raw" / "sessions" / "S006").exists()


class TestRawOnlyPartialStartC05:
    """Partial start discovered from _system/raw/sessions/ only — no Sessions/<id> directory."""

    def test_raw_only_discovered(self, vault_root: Path, audit_svc) -> None:
        _setup_raw_only_partial_start(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        # Verify Sessions directory does NOT exist
        assert not (vault_root / "Sessions" / "S006").exists()


# ── Unsafe session path ───────────────────────────────────────────────────────


class TestUnsafeSessionPathC05:
    """Unsafe session path detection."""

    def test_raw_session_symlink_reported_unsafe(self, vault_root: Path, audit_svc) -> None:
        raw_sessions = vault_root / "_system" / "raw" / "sessions"
        link_target = vault_root / "nonexistent"
        try:
            (raw_sessions / "S006").symlink_to(link_target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("OS does not support symlinks")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "unsafe_session_path" in codes


# ── Ambiguous start ownership ─────────────────────────────────────────────────


class TestAmbiguousStartOwnershipC05:
    """Ambiguous start ownership detection."""

    def test_two_unmatched_intents_not_recoverable(self, vault_root: Path, audit_svc) -> None:
        _setup_dual_unmatched_intent(vault_root, audit_svc)
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "partial_start" in codes
        issue = next(i for i in report.issues if i.code == "partial_start")
        assert issue.recoverable is False


# ── UTF-8 corruption in events ────────────────────────────────────────────────


class TestUtf8CorruptionEventsC05:
    """UTF-8 corruption detection for events."""

    def test_invalid_utf8_events_reported_corrupt(self, vault_root: Path, audit_svc) -> None:
        start_session(vault_root)
        ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        ev.write_bytes(b"\xff\xfe\x00\x01")
        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        codes = [i.code for i in report.issues]
        assert "event_corrupt" in codes


# ── Helpers (local to this module) ────────────────────────────────────────────


def _setup_partial_start_with_intent(vault_root: Path, audit_svc) -> None:
    """Create a partial start with one unmatched intent."""
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


def _setup_partial_start_no_intent(vault_root: Path) -> None:
    """Create session artifacts without any audit intent."""
    (vault_root / "Sessions" / "S006").mkdir()
    (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
    ev = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
    ev.write_text("", encoding="utf-8", newline="")


def _setup_sessions_only_partial_start(vault_root: Path, audit_svc) -> None:
    """Create a partial start with only Sessions/<id> directory (no raw dir)."""
    (vault_root / "Sessions" / "S006").mkdir()
    ctx = make_audit_context(operation_id="start-op-001", session="S006")
    audit_svc.append(
        make_audit_record(
            ctx,
            operation="session.start",
            phase="intent",
        )
    )


def _setup_raw_only_partial_start(vault_root: Path, audit_svc) -> None:
    """Create a partial start with only _system/raw/sessions/<id> (no Sessions/<id>)."""
    (vault_root / "_system" / "raw" / "sessions" / "S006").mkdir()
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
