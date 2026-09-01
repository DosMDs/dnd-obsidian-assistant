"""Tests for recovery DTOs: RecoveryIssue, SessionRecoveryReport, RecoveryActionResult."""

from __future__ import annotations

from dnd_assistant.storage.session_recovery import (
    RecoveryActionResult,
    RecoveryIssue,
    SessionRecoveryReport,
)

# ── RecoveryIssue ─────────────────────────────────────────────────────────────


class TestRecoveryIssueValue:
    """RecoveryIssue construction, defaults, equality, hash, repr."""

    def test_construct(self) -> None:
        issue = RecoveryIssue(
            code="partial_start",
            session_id="S001",
            operation_id="op-001",
            recoverable=True,
            detail="Test detail",
        )
        assert issue.code == "partial_start"
        assert issue.session_id == "S001"
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
        a = RecoveryIssue("partial_start", session_id="S001", recoverable=True)
        b = RecoveryIssue("partial_start", session_id="S001", recoverable=True)
        c = RecoveryIssue("audit_corrupt", session_id="S001")
        assert a == b
        assert a != c
        assert a != "not an issue"

    def test_hashable(self) -> None:
        a = RecoveryIssue("partial_start", session_id="S001", recoverable=True)
        b = RecoveryIssue("partial_start", session_id="S001", recoverable=True)
        assert hash(a) == hash(b)
        s = {a, b}
        assert len(s) == 1

    def test_repr(self) -> None:
        issue = RecoveryIssue("partial_start", session_id="S001", recoverable=True)
        r = repr(issue)
        assert "RecoveryIssue" in r
        assert "partial_start" in r
        assert "S001" in r


# ── SessionRecoveryReport ─────────────────────────────────────────────────────


class TestSessionRecoveryReportValue:
    """SessionRecoveryReport construction, properties, equality, hash."""

    def test_empty_report(self) -> None:
        report = SessionRecoveryReport()
        assert report.issues == []
        assert not report.has_issues

    def test_with_issues(self) -> None:
        issues = [RecoveryIssue("audit_corrupt")]
        report = SessionRecoveryReport(issues)
        assert len(report.issues) == 1
        assert report.has_issues

    def test_equality(self) -> None:
        a = SessionRecoveryReport([RecoveryIssue("audit_corrupt")])
        b = SessionRecoveryReport([RecoveryIssue("audit_corrupt")])
        c = SessionRecoveryReport()
        assert a == b
        assert a != c

    def test_hashable(self) -> None:
        a = SessionRecoveryReport([RecoveryIssue("audit_corrupt")])
        b = SessionRecoveryReport([RecoveryIssue("audit_corrupt")])
        assert hash(a) == hash(b)


# ── RecoveryActionResult ──────────────────────────────────────────────────────


class TestRecoveryActionResultValue:
    """RecoveryActionResult construction, defaults, equality."""

    def test_construct(self) -> None:
        result = RecoveryActionResult(
            operation="audit.recovery.tail",
            session_id="S001",
            before_hash="abc",
            after_hash="def",
            detail="Repaired",
        )
        assert result.operation == "audit.recovery.tail"
        assert result.session_id == "S001"
        assert result.before_hash == "abc"
        assert result.after_hash == "def"
        assert result.detail == "Repaired"

    def test_defaults(self) -> None:
        result = RecoveryActionResult(operation="test")
        assert result.operation == "test"
        assert result.session_id is None
        assert result.before_hash is None
        assert result.after_hash is None
        assert result.detail == ""

    def test_equality(self) -> None:
        a = RecoveryActionResult("op", before_hash="a", after_hash="b")
        b = RecoveryActionResult("op", before_hash="a", after_hash="b")
        c = RecoveryActionResult("op", before_hash="x", after_hash="y")
        assert a == b
        assert a != c
