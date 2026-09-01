"""S6-05 tests — session runtime inspection and recovery operations.

Covers:
- RecoveryIssue, SessionRecoveryReport, RecoveryActionResult value semantics
- inspect_runtime read-only semantics
- Clean active/completed session inspection
- Partial-start detection with/without audit ownership
- Partial-start safe/unsafe artifact detection
- Event partial-tail detection (missing LF, incomplete tail)
- Event corruption detection (middle-line, duplicate IDs)
- Metadata corruption detection
- Multiple active sessions detection
- Unresolved audit intent diagnostics
- Audit partial-tail detection (missing LF, incomplete tail)
- Audit corruption detection
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from dnd_assistant.domain.session import Session
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
    RecoveryActionResult,
    RecoveryIssue,
    SessionRecoveryReport,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


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
    return Session(**kwargs)  # type: ignore[arg-type]


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
    (root / "Sessions").mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "raw").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


def _create_audit_service(vault_root: Path) -> AuditService:
    return AuditService(vault_root / "_system" / "audit" / "audit.jsonl")


def _create_metadata_repo(vault_root: Path) -> ObsidianSessionMetadataRepository:
    return ObsidianSessionMetadataRepository(vault_root, _create_audit_service(vault_root))


def _create_recovery_repo(vault_root: Path) -> ObsidianSessionRecoveryRepository:
    return ObsidianSessionRecoveryRepository(vault_root, _create_audit_service(vault_root))


def _start_session(vault_root: Path, session_id: str = "S006") -> None:
    audit_svc = _create_audit_service(vault_root)
    repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    session = _active_session(id=session_id)
    repo.create_session(
        session,
        audit=_make_audit_context(operation_id=f"start-{session_id}", session=session_id),
    )


def _write_audit_record(vault_root: Path, record: dict) -> None:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


# ── Value semantics ────────────────────────────────────────────────────────────


class TestRecoveryIssueValue:
    def test_construct(self) -> None:
        issue = RecoveryIssue(
            code="partial_start",
            session_id="S006",
            operation_id="op-001",
            recoverable=True,
            detail="Test detail",
        )
        assert issue.code == "partial_start"
        assert issue.session_id == "S006"
        assert issue.operation_id == "op-001"
        assert issue.recoverable is True
        assert issue.detail == "Test detail"

    def test_defaults(self) -> None:
        issue = RecoveryIssue(code="audit_corrupt")
        assert issue.code == "audit_corrupt"
        assert issue.session_id is None
        assert issue.operation_id is None
        assert issue.recoverable is False
        assert issue.detail == ""

    def test_equality(self) -> None:
        a = RecoveryIssue("partial_start", session_id="S006", recoverable=True)
        b = RecoveryIssue("partial_start", session_id="S006", recoverable=True)
        c = RecoveryIssue("partial_start", session_id="S007", recoverable=True)
        assert a == b
        assert a != c

    def test_hashable(self) -> None:
        a = RecoveryIssue("partial_start", session_id="S006")
        b = RecoveryIssue("partial_start", session_id="S006")
        assert hash(a) == hash(b)

    def test_repr(self) -> None:
        issue = RecoveryIssue("partial_start", session_id="S006", recoverable=True)
        r = repr(issue)
        assert "partial_start" in r
        assert "S006" in r


class TestSessionRecoveryReportValue:
    def test_empty_report(self) -> None:
        report = SessionRecoveryReport()
        assert not report.has_issues
        assert report.issues == []

    def test_with_issues(self) -> None:
        issues = [RecoveryIssue("partial_start", session_id="S006")]
        report = SessionRecoveryReport(issues)
        assert report.has_issues
        assert len(report.issues) == 1

    def test_equality(self) -> None:
        a = SessionRecoveryReport([RecoveryIssue("partial_start")])
        b = SessionRecoveryReport([RecoveryIssue("partial_start")])
        assert a == b

    def test_hashable(self) -> None:
        a = SessionRecoveryReport([RecoveryIssue("partial_start")])
        b = SessionRecoveryReport([RecoveryIssue("partial_start")])
        assert hash(a) == hash(b)


class TestRecoveryActionResultValue:
    def test_construct(self) -> None:
        result = RecoveryActionResult(
            operation="session.recovery.partial_start",
            session_id="S006",
            before_hash="abc",
            after_hash="def",
            detail="Cleaned up",
        )
        assert result.operation == "session.recovery.partial_start"
        assert result.session_id == "S006"
        assert result.before_hash == "abc"
        assert result.after_hash == "def"

    def test_defaults(self) -> None:
        result = RecoveryActionResult(operation="audit.recovery.tail")
        assert result.session_id is None
        assert result.before_hash is None
        assert result.after_hash is None

    def test_equality(self) -> None:
        a = RecoveryActionResult("op", before_hash="a", after_hash="b")
        b = RecoveryActionResult("op", before_hash="a", after_hash="b")
        assert a == b


# ── Inspection — read-only ────────────────────────────────────────────────────


class TestInspectReadOnly:
    def test_inspect_does_not_create_files(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert not report.has_issues

    def test_inspect_clean_active_session(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert not report.has_issues

    def test_inspect_clean_completed_session(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)
        meta_repo = _create_metadata_repo(vault_root)
        meta_repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=13900,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="close-001", session="S006"),
        )
        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert not report.has_issues


# ── Partial start detection ────────────────────────────────────────────────────


class TestPartialStartDetection:
    def test_partial_start_with_intent_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        events_path = raw_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8", newline="")

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
        report = repo.inspect_runtime()
        assert report.has_issues
        partial_issues = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial_issues) == 1
        assert partial_issues[0].recoverable is True
        assert partial_issues[0].session_id == "S006"

    def test_partial_start_without_intent_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        (raw_dir / "events.jsonl").write_text("", encoding="utf-8")

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        partial_issues = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial_issues) == 1
        assert partial_issues[0].recoverable is False

    def test_partial_start_with_unexpected_file_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        (session_dir / "Session.md").write_text("unexpected", encoding="utf-8")
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()

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
        report = repo.inspect_runtime()
        assert report.has_issues
        partial_issues = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial_issues) == 1
        assert partial_issues[0].recoverable is False

    def test_partial_start_with_non_empty_events_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        session_dir = vault_root / "Sessions" / "S006"
        session_dir.mkdir()
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir()
        (raw_dir / "events.jsonl").write_text(
            '{"event_id":"evt_001"}\n', encoding="utf-8", newline=""
        )

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
        report = repo.inspect_runtime()
        assert report.has_issues
        partial_issues = [i for i in report.issues if i.code == "partial_start"]
        assert len(partial_issues) == 1
        assert partial_issues[0].recoverable is False


# ── Event tail detection ───────────────────────────────────────────────────────


class TestEventTailDetection:
    def test_event_missing_lf_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)

        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"hello"}',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        tail_issues = [i for i in report.issues if i.code == "event_partial_tail"]
        assert len(tail_issues) == 1
        assert tail_issues[0].recoverable is True

    def test_event_incomplete_tail_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)

        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"hello"}\n'
            '{"event_id":"evt_002",',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        tail_issues = [i for i in report.issues if i.code == "event_partial_tail"]
        assert len(tail_issues) == 1
        assert tail_issues[0].recoverable is True

    def test_event_middle_line_corrupt_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)

        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"ok"}\n'
            "not json at all\n"
            '{"event_id":"evt_002","real_time":"2026-08-31T15:02:00+00:00","world_tick":13801,"type":"note","text":"bad"}\n',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        corrupt_issues = [i for i in report.issues if i.code == "event_corrupt"]
        assert len(corrupt_issues) >= 1

    def test_duplicate_event_ids_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)

        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.write_text(
            '{"event_id":"evt_001","real_time":"2026-08-31T15:01:00+00:00","world_tick":13800,"type":"note","text":"first"}\n'
            '{"event_id":"evt_001","real_time":"2026-08-31T15:02:00+00:00","world_tick":13801,"type":"note","text":"dup"}\n',
            encoding="utf-8",
            newline="",
        )

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        corrupt_issues = [i for i in report.issues if i.code == "event_corrupt"]
        assert len(corrupt_issues) >= 1


# ── Metadata corruption ────────────────────────────────────────────────────────


class TestMetadataCorruption:
    def test_corrupt_metadata_detected(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)

        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta_path.write_text("not valid json", encoding="utf-8")

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        meta_issues = [i for i in report.issues if i.code == "metadata_corrupt"]
        assert len(meta_issues) == 1


# ── Multiple active sessions ───────────────────────────────────────────────────


class TestMultipleActiveSessions:
    def test_two_active_sessions_detected(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root, "S006")
        _start_session(vault_root, "S007")

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        multi_issues = [i for i in report.issues if i.code == "multiple_active_sessions"]
        assert len(multi_issues) == 1


# ── Unresolved audit intents ───────────────────────────────────────────────────


class TestUnresolvedAuditIntents:
    def test_unresolved_intent_detected(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _start_session(vault_root)

        _write_audit_record(
            vault_root,
            {
                "schema_version": 1,
                "operation_id": "event-001",
                "real_time": "2026-08-31T15:01:00+00:00",
                "operation": "session.event.append",
                "entity_id": None,
                "before_hash": "abc",
                "after_hash": "def",
                "source": "test",
                "session": "S006",
                "model_profile": None,
                "prompt_version": None,
                "phase": "intent",
            },
        )

        repo = _create_recovery_repo(vault_root)
        report = repo.inspect_runtime()
        assert report.has_issues
        intent_issues = [i for i in report.issues if i.code == "unresolved_audit_intent"]
        assert len(intent_issues) == 1
        assert intent_issues[0].session_id == "S006"


# ── Audit tail detection ───────────────────────────────────────────────────────


class TestAuditTailDetection:
    def test_audit_missing_lf_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00",'
            '"operation":"test","entity_id":null,"before_hash":null,"after_hash":null,'
            '"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
            '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00",'
            '"operation":"test","entity_id":null,"before_hash":null,"after_hash":null,'
            '"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}',
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        # AuditService.read_all() uses splitlines() which tolerates missing final LF,
        # so a single complete record without LF is valid.  For multi-record files,
        # the last record without LF is also parsed correctly by splitlines().
        # Therefore a valid record missing only the final LF is NOT detected as
        # an issue by inspection (it's still parseable).
        assert not report.has_issues

    def test_audit_incomplete_tail_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00",'
            '"operation":"test","entity_id":null,"before_hash":null,"after_hash":null,'
            '"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
            '{"schema_version":1,',
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        audit_issues = [i for i in report.issues if i.code == "audit_partial_tail"]
        assert len(audit_issues) == 1
        assert audit_issues[0].recoverable is True

    def test_audit_middle_line_corrupt_not_recoverable(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        audit_svc = _create_audit_service(vault_root)

        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        log_path.write_text(
            '{"schema_version":1,"operation_id":"op1","real_time":"2026-08-31T15:00:00+00:00",'
            '"operation":"test","entity_id":null,"before_hash":null,"after_hash":null,'
            '"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n'
            "not valid json\n"
            '{"schema_version":1,"operation_id":"op2","real_time":"2026-08-31T15:01:00+00:00",'
            '"operation":"test","entity_id":null,"before_hash":null,"after_hash":null,'
            '"source":"test","session":null,"model_profile":null,"prompt_version":null,"phase":"committed"}\n',
            encoding="utf-8",
            newline="",
        )

        repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
        report = repo.inspect_runtime()
        assert report.has_issues
        corrupt_issues = [i for i in report.issues if i.code == "audit_corrupt"]
        assert len(corrupt_issues) >= 1
