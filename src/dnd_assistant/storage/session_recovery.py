"""Session runtime recovery — inspection and explicit repair.

This module defines:

- ``RecoveryIssue`` — typed issue found during runtime inspection.
- ``SessionRecoveryReport`` — ordered collection of issues.
- ``RecoveryActionResult`` — result of a recovery operation.
- ``ObsidianSessionRecoveryRepository`` — concrete filesystem-backed
  implementation.

This module belongs to the storage layer and must not import from:
    models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditRecord, AuditService
from dnd_assistant.storage.session_events import (
    _O_BINARY,
    _parse_events_jsonl,
)
from dnd_assistant.storage.session_metadata import (
    _deserialize as _deserialize_metadata,
)
from dnd_assistant.storage.session_metadata import (
    _read_exact_text as _read_meta_text,
)
from dnd_assistant.storage.session_metadata import (
    _validate_session_runtime_roots,
)
from dnd_assistant.storage.session_paths import (
    resolve_session_storage_paths,
)

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditContext

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


# ── Hash helper ────────────────────────────────────────────────────────────────


def _content_hash(text: str) -> str:
    """SHA-256 hash of the exact UTF-8 content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Exact text reader ──────────────────────────────────────────────────────────


def _read_exact_bytes(path: Path) -> bytes:
    """Read a file's exact bytes.

    Raises:
        StorageError: The file could not be read.
    """
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StorageError(
            f"Failed to read file: {path}",
            cause=exc,
        ) from exc


# ── Audit helpers ──────────────────────────────────────────────────────────────


def _read_audit_log(audit_service: AuditService) -> tuple[list[AuditRecord], str]:
    """Read the audit log and return (records, exact_text).

    Returns:
        ``(records, exact_text)`` — records may be empty, text may be empty.

    Raises:
        StorageError: The audit log is corrupt.
    """
    if not audit_service.log_path.exists():
        return [], ""
    text = _read_meta_text(audit_service.log_path)
    records = audit_service.read_all()
    return records, text


# ── Composite snapshot for partial-start state ─────────────────────────────────


def _build_partial_start_snapshot(
    session_dir: Path,
    raw_dir: Path,
    events_path: Path,
) -> str:
    """Build a deterministic canonical snapshot of partial-start artifacts.

    The snapshot contains only recovery-owned facts, serialized as
    compact sorted JSON.  Platform-dependent absolute paths are NOT
    included.

    Returns:
        A SHA-256 hex digest of the canonical snapshot.
    """
    facts: dict[str, object] = {}

    # session_dir
    facts["session_dir_exists"] = session_dir.exists()
    if session_dir.exists():
        facts["session_dir_is_dir"] = session_dir.is_dir()
        facts["session_dir_is_symlink"] = session_dir.is_symlink()

    # raw_dir
    facts["raw_dir_exists"] = raw_dir.exists()
    if raw_dir.exists():
        facts["raw_dir_is_dir"] = raw_dir.is_dir()
        facts["raw_dir_is_symlink"] = raw_dir.is_symlink()

    # metadata.json
    facts["metadata_exists"] = raw_dir.exists() and (raw_dir / "metadata.json").exists()

    # events.jsonl
    facts["events_exists"] = events_path.exists()
    if events_path.exists() and not events_path.is_symlink() and not events_path.is_dir():
        facts["events_size"] = events_path.stat().st_size
        facts["events_hash"] = _content_hash(events_path.read_text(encoding="utf-8"))

    snapshot = json.dumps(facts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _content_hash(snapshot)


# ── Audit record builder ───────────────────────────────────────────────────────


def _build_audit_record(
    *,
    operation_id: str,
    real_time,
    operation: str,
    before_hash: str | None,
    after_hash: str | None,
    source: str,
    session: str | None = None,
    model_profile: str | None = None,
    prompt_version: str | None = None,
    phase: str = "committed",
):
    """Build an ``AuditRecord`` for a recovery operation."""
    return AuditRecord(
        operation_id=operation_id,
        real_time=real_time,
        operation=operation,
        entity_id=None,
        before_hash=before_hash,
        after_hash=after_hash,
        source=source,
        session=session,
        model_profile=model_profile,
        prompt_version=prompt_version,
        phase=phase,
    )


# ── ObsidianSessionRecoveryRepository ──────────────────────────────────────────


class ObsidianSessionRecoveryRepository:
    """Concrete session recovery repository backed by the Vault filesystem.

    Provides read-only inspection and explicit recovery operations for
    failure states left by partial session starts, corrupt event tails,
    and corrupt audit tails.

    Args:
        vault_root: The root directory of the Obsidian Vault.
        audit_service: The audit service for logging recovery operations.

    Raises:
        StorageError: The Vault root is invalid, or the audit path is
            misconfigured.
    """

    def __init__(
        self,
        vault_root: str | Path,
        audit_service: AuditService,
    ) -> None:
        self._vault_root = Path(vault_root).resolve(strict=False)
        if not self._vault_root.is_dir():
            raise StorageError(f"Vault root must be an existing directory: {self._vault_root}")

        self._audit_service = audit_service

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    # ── Runtime root validation ───────────────────────────────────────────

    def _validate_roots(self) -> None:
        """Validate canonical session runtime roots.

        Raises:
            StorageError: A root is unsafe.
        """
        _validate_session_runtime_roots(self._vault_root)

    def _reauthorize_roots(self) -> None:
        """Reauthorize runtime roots after a durable audit intent.

        Raises:
            StorageError: A root became unsafe.
        """
        _validate_session_runtime_roots(self._vault_root)

    # ── inspect_runtime — read-only ───────────────────────────────────────

    def inspect_runtime(self) -> SessionRecoveryReport:
        """Read-only inspection of current Vault runtime state.

        This method must NOT write, truncate, delete, or modify any
        filesystem state.

        Returns:
            A ``SessionRecoveryReport`` with ordered issues.

        Raises:
            StorageError: A canonical runtime root is unsafe.
        """
        self._validate_roots()
        issues: list[RecoveryIssue] = []

        # 1. Check audit log
        audit_issues = self._inspect_audit()
        issues.extend(audit_issues)

        # 2. Scan sessions
        session_issues = self._inspect_sessions()
        issues.extend(session_issues)

        # 3. Sort deterministically
        issues.sort(key=lambda i: (i.code, i.session_id or "", i.operation_id or ""))

        return SessionRecoveryReport(issues)

    def _inspect_audit(self) -> list[RecoveryIssue]:
        """Inspect the audit log for corruption or partial tails.

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []
        log_path = self._audit_service.log_path

        if not log_path.exists():
            return issues

        try:
            raw_bytes = _read_exact_bytes(log_path)
        except StorageError:
            issues.append(
                RecoveryIssue(
                    code="audit_corrupt",
                    detail="Audit log is unreadable",
                    recoverable=False,
                )
            )
            return issues

        if not raw_bytes:
            return issues

        text = raw_bytes.decode("utf-8")

        # Normalize line endings: splitlines() handles \r\n, \n, \r uniformly
        raw_lines = text.splitlines()
        # Reconstruct with \n only for deterministic splitting
        normalized = "\n".join(raw_lines)
        if text.endswith("\n"):
            normalized += "\n"

        # Check if the audit log has a partial tail (does not end with LF)
        if not normalized.endswith("\n"):
            # Try strict parsing first — some parsers may tolerate missing final LF
            try:
                self._audit_service.read_all()
                # If strict parsing succeeds, no issue
                return issues
            except StorageError:
                pass

            # Split into complete prefix and final unterminated tail
            lines = normalized.split("\n")
            if lines and lines[-1] == "":
                lines = lines[:-1]

            if len(lines) >= 1:
                complete_prefix = "\n".join(lines[:-1])
                if complete_prefix:
                    complete_prefix += "\n"
                final_tail = lines[-1]

                # Check if the complete prefix is valid by parsing it
                prefix_valid = self._check_audit_prefix_valid(complete_prefix)
                if not prefix_valid:
                    issues.append(
                        RecoveryIssue(
                            code="audit_corrupt",
                            detail="Audit log has corruption in a completed record",
                            recoverable=False,
                        )
                    )
                    return issues

                # Check if the tail is a complete record missing LF
                tail_with_lf = final_tail + "\n"
                if self._check_audit_text_valid(tail_with_lf):
                    issues.append(
                        RecoveryIssue(
                            code="audit_partial_tail",
                            detail="Audit log has a final record missing trailing newline",
                            recoverable=True,
                        )
                    )
                else:
                    issues.append(
                        RecoveryIssue(
                            code="audit_partial_tail",
                            detail="Audit log has an incomplete final record",
                            recoverable=True,
                        )
                    )
        else:
            # File ends with LF — try strict parsing
            try:
                self._audit_service.read_all()
            except StorageError:
                # read_all() failed. Check if the last LF-terminated line is
                # an incomplete record (partial tail) or a corrupt completed line.
                lines = normalized.split("\n")
                if lines and lines[-1] == "":
                    lines = lines[:-1]

                if len(lines) >= 1:
                    complete_prefix = "\n".join(lines[:-1])
                    if complete_prefix:
                        complete_prefix += "\n"
                    final_line = lines[-1]

                    # Check if the complete prefix is valid
                    prefix_valid = self._check_audit_prefix_valid(complete_prefix)
                    if prefix_valid:
                        # The last line is the problem — check if it's a partial tail
                        tail_with_lf = final_line + "\n"
                        if self._check_audit_text_valid(tail_with_lf):
                            issues.append(
                                RecoveryIssue(
                                    code="audit_partial_tail",
                                    detail="Audit log has a final record missing trailing newline",
                                    recoverable=True,
                                )
                            )
                        else:
                            # The last line is incomplete even with LF
                            issues.append(
                                RecoveryIssue(
                                    code="audit_partial_tail",
                                    detail="Audit log has an incomplete final record",
                                    recoverable=True,
                                )
                            )
                    else:
                        issues.append(
                            RecoveryIssue(
                                code="audit_corrupt",
                                detail="Audit log has corruption in a completed record",
                                recoverable=False,
                            )
                        )

        return issues

    # ── repair_audit_tail — self-targeting recovery ───────────────────────

    def repair_audit_tail(
        self,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Repair a provably partial final audit-log tail.

        This is an exceptional self-targeting recovery path.  The audit
        log cannot write a durable intent into itself while corrupt, so
        the normal two-phase audit is replaced by:
        repair -> verify -> append recovery marker.

        Args:
            audit: Audit context for the recovery marker.

        Returns:
            A ``RecoveryActionResult`` with before/after hashes.

        Raises:
            ConflictError: The audit log changed between inspection and
                repair.
            StorageError: The corruption is not limited to the final tail,
                or the repair itself failed.
        """
        log_path = self._audit_service.log_path

        if not log_path.exists():
            raise StorageError("Audit log does not exist")

        # Snapshot exact before state
        before_bytes = _read_exact_bytes(log_path)
        before_hash = _content_hash(before_bytes.decode("utf-8"))

        # Reauthorize audit path
        if log_path.is_symlink():
            raise StorageError("Audit log is a symlink, rejected for safety")

        # Re-read and verify same before hash
        current_bytes = _read_exact_bytes(log_path)
        current_hash = _content_hash(current_bytes.decode("utf-8"))
        if current_hash != before_hash:
            raise ConflictError("Audit log changed between inspection and repair")

        text = before_bytes.decode("utf-8")

        # Check if the file already ends with LF using the ORIGINAL bytes
        # (before_bytes, not normalized text, to correctly detect \n even
        # when the file uses \r\n line endings on Windows)
        if before_bytes.endswith(b"\n"):
            raise StorageError("Audit log already ends with newline — no repair needed")

        # Normalize line endings: splitlines() handles \r\n, \n, \r uniformly
        raw_lines = text.splitlines()
        normalized = "\n".join(raw_lines)

        # Split into complete prefix and final tail
        lines = normalized.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]

        if len(lines) < 1:
            raise StorageError("Audit log has no content to repair")

        complete_prefix = "\n".join(lines[:-1])
        if complete_prefix:
            complete_prefix += "\n"
        final_tail = lines[-1]

        # Verify complete prefix is valid
        if not self._check_audit_prefix_valid(complete_prefix):
            raise StorageError(
                "Audit log corruption is not limited to the final tail — "
                "manual intervention required"
            )

        # Determine repair mode
        tail_with_lf = final_tail + "\n"
        if self._check_audit_text_valid(tail_with_lf):
            repair_mode = "append_missing_newline"
        else:
            repair_mode = "truncate_invalid_tail"

        # Perform repair
        if repair_mode == "append_missing_newline":
            fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | _O_BINARY)
            try:
                os.write(fd, b"\n")
                os.fsync(fd)
            except OSError as exc:
                raise StorageError(
                    f"Failed to append LF to audit log: {log_path}",
                    cause=exc,
                ) from exc
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
        else:
            prefix_bytes = complete_prefix.encode("utf-8")
            fd = os.open(str(log_path), os.O_WRONLY | _O_BINARY)
            try:
                os.ftruncate(fd, len(prefix_bytes))
                os.fsync(fd)
            except OSError as exc:
                raise StorageError(
                    f"Failed to truncate audit log: {log_path}",
                    cause=exc,
                ) from exc
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass

        # Verify repair
        repaired_bytes = _read_exact_bytes(log_path)
        after_hash = _content_hash(repaired_bytes.decode("utf-8"))

        # Strict AuditService.read_all() verification
        try:
            self._audit_service.read_all()
        except StorageError as exc:
            raise StorageError(
                "Audit tail repair completed but strict parsing failed",
                cause=exc,
            ) from exc

        # Append recovery marker (no intent — this is the self-target exception)
        marker = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="audit.recovery.tail",
            before_hash=before_hash,
            after_hash=after_hash,
            source=audit.source,
            session=None,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="committed",
        )
        try:
            self._audit_service.append(marker)
        except StorageError as exc:
            raise StorageError(
                "Audit tail repaired but recovery marker append failed. "
                "The repaired audit log remains intact.",
                cause=exc,
            ) from exc

        return RecoveryActionResult(
            operation="audit.recovery.tail",
            before_hash=before_hash,
            after_hash=after_hash,
            detail=f"Audit log repaired: {repair_mode}",
        )

    # ── cleanup_partial_start — explicit cleanup ──────────────────────────

    def cleanup_partial_start(
        self,
        session_id: str,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Clean up a provably owned partial session start.

        Only exact known-empty artifacts are removed.  No recursive
        deletion.  No unexpected content is removed.

        Args:
            session_id: The session identifier to clean up.
            audit: Audit context for this recovery operation.

        Returns:
            A ``RecoveryActionResult`` with before/after composite
            snapshot hashes.

        Raises:
            ConflictError: The partial-start state changed between
                inspection and cleanup.
            StorageError: The state is not safely recoverable, or a
                filesystem operation failed.
        """
        self._validate_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)

        # Build pre-cleanup snapshot
        before_hash = _build_partial_start_snapshot(
            paths.session_dir, paths.raw_dir, paths.raw_events
        )

        # Verify audit ownership
        try:
            records, _ = _read_audit_log(self._audit_service)
        except StorageError as exc:
            raise StorageError(
                f"Cannot verify audit ownership for session {session_id}: audit log is corrupt",
                cause=exc,
            ) from exc

        matching_intents = [
            r
            for r in records
            if r.operation == "session.start" and r.session == session_id and r.phase == "intent"
        ]
        matching_committed = [
            r
            for r in records
            if r.operation == "session.start" and r.session == session_id and r.phase == "committed"
        ]

        if not matching_intents:
            raise StorageError(
                f"No unmatched session.start intent found for {session_id} — "
                "cannot prove ownership of partial start"
            )

        if matching_committed:
            raise StorageError(
                f"Session {session_id} has a committed session.start record — not a partial start"
            )

        # Verify safe state
        if not self._is_safe_partial_start(session_id, paths):
            raise StorageError(
                f"Session {session_id} has unexpected content — "
                "cannot safely clean up partial start"
            )

        # Reauthorize paths
        self._reauthorize_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)

        # Re-inspect exact snapshot
        current_hash = _build_partial_start_snapshot(
            paths.session_dir, paths.raw_dir, paths.raw_events
        )
        if current_hash != before_hash:
            raise ConflictError(
                f"Partial-start state for {session_id} changed between inspection and cleanup"
            )

        # Recovery audit intent
        intent_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.recovery.partial_start",
            before_hash=before_hash,
            after_hash=None,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="intent",
        )
        self._audit_service.append(intent_record)

        # Reauthorize after durable intent
        self._reauthorize_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)

        # Re-inspect snapshot unchanged
        current_hash2 = _build_partial_start_snapshot(
            paths.session_dir, paths.raw_dir, paths.raw_events
        )
        if current_hash2 != before_hash:
            raise ConflictError(
                f"Partial-start state for {session_id} changed after recovery intent"
            )

        # Remove only exact known-empty artifacts
        if paths.raw_events.exists():
            if paths.raw_events.stat().st_size == 0:
                try:
                    paths.raw_events.unlink()
                except OSError as exc:
                    raise StorageError(
                        f"Failed to remove events.jsonl for {session_id}",
                        cause=exc,
                    ) from exc

        if paths.raw_dir.exists():
            try:
                contents = list(paths.raw_dir.iterdir())
                if not contents:
                    paths.raw_dir.rmdir()
            except OSError as exc:
                raise StorageError(
                    f"Failed to remove raw session directory for {session_id}",
                    cause=exc,
                ) from exc

        if paths.session_dir.exists():
            try:
                contents = list(paths.session_dir.iterdir())
                if not contents:
                    paths.session_dir.rmdir()
            except OSError as exc:
                raise StorageError(
                    f"Failed to remove session directory for {session_id}",
                    cause=exc,
                ) from exc

        # Build after snapshot
        after_hash = _build_partial_start_snapshot(
            paths.session_dir, paths.raw_dir, paths.raw_events
        )

        # Committed audit
        committed_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.recovery.partial_start",
            before_hash=before_hash,
            after_hash=after_hash,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="committed",
        )
        try:
            self._audit_service.append(committed_record)
        except StorageError as exc:
            raise StorageError(
                f"Partial-start cleanup for {session_id} committed but audit finalization failed",
                cause=exc,
            ) from exc

        return RecoveryActionResult(
            operation="session.recovery.partial_start",
            session_id=session_id,
            before_hash=before_hash,
            after_hash=after_hash,
            detail=f"Partial start for {session_id} cleaned up",
        )

    # ── repair_event_tail — append-LF or truncate ─────────────────────────

    def repair_event_tail(
        self,
        session_id: str,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Repair a provably partial final event-log tail.

        Recovery is allowed only when all complete LF-terminated prefix
        events are valid and corruption is isolated to the final
        unterminated tail.

        Args:
            session_id: The session identifier.
            audit: Audit context for this recovery operation.

        Returns:
            A ``RecoveryActionResult`` with before/after hashes.

        Raises:
            ConflictError: The events file changed between inspection and
                repair.
            StorageError: The corruption is not limited to the final tail,
                or the repair itself failed.
        """
        self._validate_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        events_path = paths.raw_events

        if not events_path.exists():
            raise StorageError(f"events.jsonl not found for session {session_id}")

        if events_path.is_symlink():
            raise StorageError(f"events.jsonl is a symlink, rejected for safety: {events_path}")

        if events_path.is_dir():
            raise StorageError(f"events.jsonl is a directory: {events_path}")

        # Snapshot metadata hash for race detection
        metadata_path = paths.raw_metadata
        if metadata_path.exists():
            meta_before_text = _read_meta_text(metadata_path)
            meta_before_hash = _content_hash(meta_before_text)
        else:
            meta_before_hash = None

        # Snapshot exact before state
        before_bytes = _read_exact_bytes(events_path)
        before_hash = _content_hash(before_bytes.decode("utf-8"))

        # Try strict parsing first
        text = before_bytes.decode("utf-8")
        parse_ok = False
        try:
            _parse_events_jsonl(text)
            parse_ok = True
        except StorageError:
            pass

        if parse_ok:
            raise StorageError(f"events.jsonl for {session_id} is already valid — no repair needed")

        # Normalize line endings: splitlines() handles \r\n, \n, \r uniformly
        raw_lines = text.splitlines()
        normalized = "\n".join(raw_lines)

        # Check if the file already ends with LF using the ORIGINAL bytes
        # (before_bytes, not normalized text, to correctly detect \n even
        # when the file uses \r\n line endings on Windows)
        if before_bytes.endswith(b"\n"):
            raise StorageError(
                f"events.jsonl for {session_id} ends with newline but is corrupt — "
                "corruption is not limited to the final tail"
            )

        # Split into complete prefix and final tail
        lines = normalized.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]

        if len(lines) < 1:
            raise StorageError(f"events.jsonl for {session_id} has no content to repair")

        complete_prefix = "\n".join(lines[:-1])
        if complete_prefix:
            complete_prefix += "\n"
        final_tail = lines[-1]

        # Verify complete prefix is valid
        try:
            if complete_prefix:
                _parse_events_jsonl(complete_prefix)
        except StorageError as exc:
            raise StorageError(
                f"events.jsonl for {session_id}: corruption is not limited to "
                "the final tail — manual intervention required",
                cause=exc,
            ) from exc

        # Determine repair mode
        tail_with_lf = final_tail + "\n"
        try:
            _parse_events_jsonl(tail_with_lf)
            repair_mode = "append_missing_newline"
        except StorageError:
            repair_mode = "truncate_invalid_tail"

        # Reauthorize after inspection
        self._reauthorize_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        events_path = paths.raw_events

        # Re-read and verify unchanged
        current_bytes = _read_exact_bytes(events_path)
        current_hash = _content_hash(current_bytes.decode("utf-8"))
        if current_hash != before_hash:
            raise ConflictError(
                f"events.jsonl for {session_id} changed between inspection and repair"
            )

        # Re-check metadata unchanged
        if meta_before_hash is not None:
            if metadata_path.exists():
                meta_current_text = _read_meta_text(metadata_path)
                meta_current_hash = _content_hash(meta_current_text)
                if meta_current_hash != meta_before_hash:
                    raise ConflictError(
                        f"Session metadata for {session_id} changed after event-tail repair intent"
                    )

        # Audit intent
        intent_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.recovery.events_tail",
            before_hash=before_hash,
            after_hash=None,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="intent",
        )
        self._audit_service.append(intent_record)

        # Reauthorize after durable intent
        self._reauthorize_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        events_path = paths.raw_events

        # Re-read and verify unchanged
        current_bytes2 = _read_exact_bytes(events_path)
        current_hash2 = _content_hash(current_bytes2.decode("utf-8"))
        if current_hash2 != before_hash:
            raise ConflictError(f"events.jsonl for {session_id} changed after recovery intent")

        # Perform repair
        if repair_mode == "append_missing_newline":
            fd = os.open(str(events_path), os.O_WRONLY | os.O_APPEND | _O_BINARY)
            try:
                os.write(fd, b"\n")
                os.fsync(fd)
            except OSError as exc:
                raise StorageError(
                    f"Failed to append LF to events.jsonl: {events_path}",
                    cause=exc,
                ) from exc
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
        else:
            prefix_bytes = complete_prefix.encode("utf-8")
            fd = os.open(str(events_path), os.O_WRONLY | _O_BINARY)
            try:
                os.ftruncate(fd, len(prefix_bytes))
                os.fsync(fd)
            except OSError as exc:
                raise StorageError(
                    f"Failed to truncate events.jsonl: {events_path}",
                    cause=exc,
                ) from exc
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass

        # Verify repair — re-read exact bytes
        repaired_bytes = _read_exact_bytes(events_path)
        after_hash = _content_hash(repaired_bytes.decode("utf-8"))

        # Strictly parse entire event log
        try:
            all_events = _parse_events_jsonl(repaired_bytes.decode("utf-8"))
        except StorageError as exc:
            raise StorageError(
                f"Event-tail repair for {session_id} completed but strict parsing failed",
                cause=exc,
            ) from exc

        # Verify all complete prior events unchanged
        if complete_prefix:
            try:
                prior_events = _parse_events_jsonl(complete_prefix)
            except StorageError as exc:
                raise StorageError(
                    f"Event-tail repair for {session_id} completed but "
                    "prior events are no longer valid",
                    cause=exc,
                ) from exc
            if len(all_events) < len(prior_events):
                raise StorageError(f"Event-tail repair for {session_id} lost events")
            for i, prior in enumerate(prior_events):
                if all_events[i] != prior:
                    raise StorageError(
                        f"Event-tail repair for {session_id} modified prior event {prior.event_id}"
                    )

        # Committed audit
        committed_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.recovery.events_tail",
            before_hash=before_hash,
            after_hash=after_hash,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="committed",
        )
        try:
            self._audit_service.append(committed_record)
        except StorageError as exc:
            raise StorageError(
                f"Event-tail repair for {session_id} committed but "
                "audit finalization failed. The repaired file remains.",
                cause=exc,
            ) from exc

        return RecoveryActionResult(
            operation="session.recovery.events_tail",
            session_id=session_id,
            before_hash=before_hash,
            after_hash=after_hash,
            detail=f"events.jsonl repaired: {repair_mode}",
        )

    def _check_audit_prefix_valid(self, text: str) -> bool:
        """Check if audit text (complete prefix) is strictly valid.

        Writes to a temp file and uses AuditService.read_all() to validate.
        Uses ``newline=""`` to prevent platform ``\\n`` → ``\\r\\n`` translation.

        Returns:
            True if valid, False if corrupt.
        """
        if not text:
            return True
        log_path = self._audit_service.log_path
        temp_path = log_path.with_name(f"._audit_check_{os.urandom(4).hex()}.tmp")
        try:
            temp_path.write_text(text, encoding="utf-8", newline="")
            temp_service = AuditService(temp_path)
            temp_service.read_all()
            return True
        except (StorageError, OSError):
            return False
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _check_audit_text_valid(self, text: str) -> bool:
        """Check if audit text is a valid complete audit log.

        Uses ``newline=""`` to prevent platform ``\\n`` → ``\\r\\n`` translation.

        Returns:
            True if valid, False if corrupt.
        """
        if not text:
            return True
        log_path = self._audit_service.log_path
        temp_path = log_path.with_name(f"._audit_check_{os.urandom(4).hex()}.tmp")
        try:
            temp_path.write_text(text, encoding="utf-8", newline="")
            temp_service = AuditService(temp_path)
            temp_service.read_all()
            return True
        except (StorageError, OSError):
            return False
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    # ── Session inspection ────────────────────────────────────────────────

    def _inspect_sessions(self) -> list[RecoveryIssue]:
        """Scan session directories for issues.

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []
        raw_root = self._vault_root / "_system" / "raw" / "sessions"

        if not raw_root.exists() or not raw_root.is_dir():
            return issues

        try:
            entries = sorted(raw_root.iterdir(), key=lambda p: p.name)
        except OSError:
            return issues

        active_count = 0

        for entry in entries:
            if entry.is_symlink():
                continue
            if not entry.is_dir():
                continue

            session_id = entry.name

            # Check for unsafe paths
            try:
                paths = resolve_session_storage_paths(self._vault_root, session_id)
            except StorageError:
                issues.append(
                    RecoveryIssue(
                        code="unsafe_session_path",
                        session_id=session_id,
                        detail=f"Session {session_id} has unsafe storage paths",
                        recoverable=False,
                    )
                )
                continue

            # Check metadata
            metadata_path = paths.raw_metadata
            if metadata_path.exists():
                if metadata_path.is_symlink():
                    issues.append(
                        RecoveryIssue(
                            code="unsafe_session_path",
                            session_id=session_id,
                            detail=f"metadata.json for {session_id} is a symlink",
                            recoverable=False,
                        )
                    )
                    continue

                try:
                    text = _read_meta_text(metadata_path)
                    meta = _deserialize_metadata(text, expected_id=session_id)
                except StorageError:
                    issues.append(
                        RecoveryIssue(
                            code="metadata_corrupt",
                            session_id=session_id,
                            detail=f"metadata.json for {session_id} is corrupt",
                            recoverable=False,
                        )
                    )
                    continue

                # Count active sessions
                if meta.session.status == "active":
                    active_count += 1

                # Check events
                events_path = paths.raw_events
                events_issues = self._inspect_events(session_id, events_path)
                issues.extend(events_issues)

                # Check for unresolved audit intents
                intent_issues = self._inspect_unresolved_intents(session_id)
                issues.extend(intent_issues)

            else:
                # metadata.json absent — check for partial start
                partial_issues = self._inspect_partial_start(session_id, paths)
                issues.extend(partial_issues)

        # Check for multiple active sessions
        if active_count > 1:
            issues.append(
                RecoveryIssue(
                    code="multiple_active_sessions",
                    detail=f"Found {active_count} active sessions",
                    recoverable=False,
                )
            )

        return issues

    def _inspect_events(self, session_id: str, events_path: Path) -> list[RecoveryIssue]:
        """Inspect the events file for corruption or partial tails.

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []

        if not events_path.exists():
            return issues

        if events_path.is_symlink():
            issues.append(
                RecoveryIssue(
                    code="unsafe_session_path",
                    session_id=session_id,
                    detail=f"events.jsonl for {session_id} is a symlink",
                    recoverable=False,
                )
            )
            return issues

        if events_path.is_dir():
            issues.append(
                RecoveryIssue(
                    code="unsafe_session_path",
                    session_id=session_id,
                    detail=f"events.jsonl for {session_id} is a directory",
                    recoverable=False,
                )
            )
            return issues

        try:
            raw_bytes = _read_exact_bytes(events_path)
        except StorageError:
            issues.append(
                RecoveryIssue(
                    code="event_corrupt",
                    session_id=session_id,
                    detail=f"events.jsonl for {session_id} is unreadable",
                    recoverable=False,
                )
            )
            return issues

        if not raw_bytes:
            return issues

        text = raw_bytes.decode("utf-8")

        # Try strict parsing first
        try:
            _parse_events_jsonl(text)
            return issues  # No issues
        except StorageError:
            pass

        # Check if the issue is a partial tail
        if not text.endswith("\n"):
            lines = text.split("\n")
            if lines and lines[-1] == "":
                lines = lines[:-1]

            if len(lines) >= 1:
                complete_prefix = "\n".join(lines[:-1])
                if complete_prefix:
                    complete_prefix += "\n"
                final_tail = lines[-1]

                # Check if the complete prefix is valid
                try:
                    if complete_prefix:
                        _parse_events_jsonl(complete_prefix)
                    # If we get here, the complete prefix is valid
                    tail_with_lf = final_tail + "\n"
                    try:
                        _parse_events_jsonl(tail_with_lf)
                        issues.append(
                            RecoveryIssue(
                                code="event_partial_tail",
                                session_id=session_id,
                                detail=f"events.jsonl for {session_id} has a final record missing trailing newline",
                                recoverable=True,
                            )
                        )
                    except StorageError:
                        issues.append(
                            RecoveryIssue(
                                code="event_partial_tail",
                                session_id=session_id,
                                detail=f"events.jsonl for {session_id} has an incomplete final record",
                                recoverable=True,
                            )
                        )
                except StorageError:
                    issues.append(
                        RecoveryIssue(
                            code="event_corrupt",
                            session_id=session_id,
                            detail=f"events.jsonl for {session_id} has corruption in a completed record",
                            recoverable=False,
                        )
                    )
        else:
            # Ends with LF but parsing failed — corruption in middle
            issues.append(
                RecoveryIssue(
                    code="event_corrupt",
                    session_id=session_id,
                    detail=f"events.jsonl for {session_id} has corruption in a completed record",
                    recoverable=False,
                )
            )

        return issues

    def _inspect_partial_start(self, session_id: str, paths) -> list[RecoveryIssue]:
        """Check if a session directory without metadata is a recoverable partial start.

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []

        # Check for at least one candidate artifact
        has_session_dir = paths.session_dir.exists()
        has_raw_dir = paths.raw_dir.exists()

        if not has_session_dir and not has_raw_dir:
            return issues

        # Check for unmatched session.start intent
        try:
            records, _ = _read_audit_log(self._audit_service)
        except StorageError:
            return issues

        matching_intents = [
            r
            for r in records
            if r.operation == "session.start" and r.session == session_id and r.phase == "intent"
        ]
        matching_committed = [
            r
            for r in records
            if r.operation == "session.start" and r.session == session_id and r.phase == "committed"
        ]

        if not matching_intents:
            # No audit ownership — not auto-recoverable
            issues.append(
                RecoveryIssue(
                    code="partial_start",
                    session_id=session_id,
                    detail=f"Session {session_id} has artifacts but no matching session.start intent",
                    recoverable=False,
                )
            )
            return issues

        if matching_committed:
            # Has committed record — not a partial start
            return issues

        # Check if all artifacts are safe
        if not self._is_safe_partial_start(session_id, paths):
            issues.append(
                RecoveryIssue(
                    code="partial_start",
                    session_id=session_id,
                    detail=f"Session {session_id} has unexpected content preventing safe cleanup",
                    recoverable=False,
                )
            )
            return issues

        issues.append(
            RecoveryIssue(
                code="partial_start",
                session_id=session_id,
                detail=f"Session {session_id} is a recoverable partial start",
                recoverable=True,
            )
        )

        return issues

    def _is_safe_partial_start(self, session_id: str, paths) -> bool:
        """Check if all existing partial-start artifacts are known-safe.

        Safe artifacts:
        - Sessions/<id>/ directory: empty, not symlink
        - raw session directory: empty, not symlink
        - events.jsonl: zero bytes, not symlink

        Returns:
            True if safe to clean up.
        """
        # Check session_dir
        if paths.session_dir.exists():
            if paths.session_dir.is_symlink():
                return False
            if not paths.session_dir.is_dir():
                return False
            try:
                contents = list(paths.session_dir.iterdir())
                if contents:
                    return False  # Unexpected content
            except OSError:
                return False

        # Check raw_dir
        if paths.raw_dir.exists():
            if paths.raw_dir.is_symlink():
                return False
            if not paths.raw_dir.is_dir():
                return False
            try:
                contents = list(paths.raw_dir.iterdir())
            except OSError:
                return False

            # Only events.jsonl is allowed
            allowed = {paths.raw_events.name}
            for item in contents:
                if item.name not in allowed:
                    return False

        # Check events.jsonl
        if paths.raw_events.exists():
            if paths.raw_events.is_symlink():
                return False
            if paths.raw_events.is_dir():
                return False
            if paths.raw_events.stat().st_size != 0:
                return False

        return True

    def _inspect_unresolved_intents(self, session_id: str) -> list[RecoveryIssue]:
        """Check for unresolved audit intents for session operations.

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []

        try:
            records, _ = _read_audit_log(self._audit_service)
        except StorageError:
            return issues

        # Group by operation_id
        by_op: dict[str, list[AuditRecord]] = {}
        for r in records:
            if r.session == session_id:
                by_op.setdefault(r.operation_id, []).append(r)

        for op_id, op_records in by_op.items():
            has_intent = any(r.phase == "intent" for r in op_records)
            has_committed = any(r.phase == "committed" for r in op_records)

            if has_intent and not has_committed:
                # Get the operation name from the intent record
                op_name = ""
                for r in op_records:
                    if r.phase == "intent":
                        op_name = r.operation
                        break
                issues.append(
                    RecoveryIssue(
                        code="unresolved_audit_intent",
                        session_id=session_id,
                        operation_id=op_id,
                        detail=f"Session {session_id} has unresolved intent for operation {op_name} ({op_id})",
                        recoverable=False,
                    )
                )

        return issues
