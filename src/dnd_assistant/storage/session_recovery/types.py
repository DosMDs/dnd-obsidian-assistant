"""Recovery-specific types and DTOs.

This module defines:

- ``RecoveryIssue`` — a single typed issue found during runtime inspection.
- ``SessionRecoveryReport`` — an ordered collection of issues.
- ``RecoveryActionResult`` — the result of a recovery operation.

These types are used by the session recovery package and re-exported
through the public facade.
"""

from __future__ import annotations

from typing import Literal

# ── Issue codes ────────────────────────────────────────────────────────────────

_RECOVERY_ISSUE_CODES = Literal[
    "audit_partial_tail",
    "audit_corrupt",
    "partial_start",
    "event_partial_tail",
    "event_corrupt",
    "metadata_corrupt",
    "multiple_active_sessions",
    "unresolved_audit_intent",
    "unsafe_session_path",
]

# ── Recovery issue ─────────────────────────────────────────────────────────────


class RecoveryIssue:
    """A single issue found during runtime inspection.

    Carries enough structured information for a future CLI to display
    or act upon.

    Args:
        code: The issue code.
        session_id: Optional session identifier.
        operation_id: Optional operation identifier.
        recoverable: Whether this issue is automatically recoverable.
        detail: Human-readable detail string.
    """

    def __init__(
        self,
        code: str,
        *,
        session_id: str | None = None,
        operation_id: str | None = None,
        recoverable: bool = False,
        detail: str = "",
    ) -> None:
        self._code = code
        self._session_id = session_id
        self._operation_id = operation_id
        self._recoverable = recoverable
        self._detail = detail

    @property
    def code(self) -> str:
        """The issue code."""
        return self._code

    @property
    def session_id(self) -> str | None:
        """Optional session identifier."""
        return self._session_id

    @property
    def operation_id(self) -> str | None:
        """Optional operation identifier."""
        return self._operation_id

    @property
    def recoverable(self) -> bool:
        """Whether this issue is automatically recoverable."""
        return self._recoverable

    @property
    def detail(self) -> str:
        """Human-readable detail string."""
        return self._detail

    def __repr__(self) -> str:
        return (
            f"RecoveryIssue(code={self._code!r}, "
            f"session_id={self._session_id!r}, "
            f"recoverable={self._recoverable})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RecoveryIssue):
            return NotImplemented
        return (
            self._code == other._code
            and self._session_id == other._session_id
            and self._operation_id == other._operation_id
            and self._recoverable == other._recoverable
            and self._detail == other._detail
        )

    def __hash__(self) -> int:
        return hash(
            (self._code, self._session_id, self._operation_id, self._recoverable, self._detail)
        )


# ── Recovery report ────────────────────────────────────────────────────────────


class SessionRecoveryReport:
    """Read-only report of current Vault runtime state.

    Contains an ordered list of ``RecoveryIssue`` values.  Issues are
    ordered by (code, session_id, operation_id) for deterministic,
    reproducible output.
    """

    def __init__(self, issues: list[RecoveryIssue] | None = None) -> None:
        self._issues = list(issues) if issues else []

    @property
    def issues(self) -> list[RecoveryIssue]:
        """Ordered list of recovery issues."""
        return list(self._issues)

    @property
    def has_issues(self) -> bool:
        """True if any issues were found."""
        return len(self._issues) > 0

    def __repr__(self) -> str:
        return f"SessionRecoveryReport(issues={len(self._issues)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SessionRecoveryReport):
            return NotImplemented
        return self._issues == other._issues

    def __hash__(self) -> int:
        return hash(tuple(self._issues))


# ── Recovery action result ─────────────────────────────────────────────────────


class RecoveryActionResult:
    """Result of an explicit recovery operation.

    Args:
        operation: The recovery operation name.
        session_id: Optional session identifier.
        before_hash: SHA-256 hash of the state before recovery.
        after_hash: SHA-256 hash of the state after recovery.
        detail: Human-readable detail string.
    """

    def __init__(
        self,
        operation: str,
        *,
        session_id: str | None = None,
        before_hash: str | None = None,
        after_hash: str | None = None,
        detail: str = "",
    ) -> None:
        self._operation = operation
        self._session_id = session_id
        self._before_hash = before_hash
        self._after_hash = after_hash
        self._detail = detail

    @property
    def operation(self) -> str:
        """The recovery operation name."""
        return self._operation

    @property
    def session_id(self) -> str | None:
        """Optional session identifier."""
        return self._session_id

    @property
    def before_hash(self) -> str | None:
        """SHA-256 hash of the state before recovery."""
        return self._before_hash

    @property
    def after_hash(self) -> str | None:
        """SHA-256 hash of the state after recovery."""
        return self._after_hash

    @property
    def detail(self) -> str:
        """Human-readable detail string."""
        return self._detail

    def __repr__(self) -> str:
        return (
            f"RecoveryActionResult(operation={self._operation!r}, session_id={self._session_id!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RecoveryActionResult):
            return NotImplemented
        return (
            self._operation == other._operation
            and self._session_id == other._session_id
            and self._before_hash == other._before_hash
            and self._after_hash == other._after_hash
        )

    def __hash__(self) -> int:
        return hash((self._operation, self._session_id, self._before_hash, self._after_hash))
