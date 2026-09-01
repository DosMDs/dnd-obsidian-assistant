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


# ── Hash helpers ────────────────────────────────────────────────────────────────


def _bytes_hash(data: bytes) -> str:
    """SHA-256 hash of exact bytes."""
    return hashlib.sha256(data).hexdigest()


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
    try:
        text = _read_meta_text(audit_service.log_path)
    except (StorageError, UnicodeDecodeError) as exc:
        raise StorageError("Audit log is unreadable", cause=exc) from exc
    try:
        records = audit_service.read_all()
    except (StorageError, UnicodeDecodeError) as exc:
        raise StorageError("Audit log is corrupt", cause=exc) from exc
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
    included.  Uses exact bytes for events — no ``read_text`` that
    could raise ``UnicodeDecodeError`` on non-UTF-8 content.

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

    # events.jsonl — use exact bytes, no read_text
    facts["events_exists"] = events_path.exists()
    if events_path.exists() and not events_path.is_symlink() and not events_path.is_dir():
        try:
            facts["events_size"] = events_path.stat().st_size
            events_bytes = events_path.read_bytes()
            facts["events_hash"] = _bytes_hash(events_bytes)
        except OSError:
            facts["events_size"] = -1
            facts["events_hash"] = None

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

        # UTF-8 corruption check — must not leak UnicodeDecodeError
        try:
            raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(
                RecoveryIssue(
                    code="audit_corrupt",
                    detail="Audit log contains invalid UTF-8",
                    recoverable=False,
                )
            )
            return issues

        # Physical-LF classification
        if raw_bytes.endswith(b"\n"):
            # File ends with LF — try strict parsing
            try:
                self._audit_service.read_all()
                return issues  # clean
            except StorageError:
                # Strict parsing failed — a completed LF-terminated line is corrupt
                issues.append(
                    RecoveryIssue(
                        code="audit_corrupt",
                        detail="Audit log has corruption in a completed record",
                        recoverable=False,
                    )
                )
                return issues

        # File does NOT end with LF — split at last physical \n
        prefix_bytes, tail_bytes = self._split_final_unterminated_tail(raw_bytes)

        # Validate the complete prefix strictly
        if not self._validate_audit_prefix_bytes(prefix_bytes):
            issues.append(
                RecoveryIssue(
                    code="audit_corrupt",
                    detail="Audit log has corruption in a completed record",
                    recoverable=False,
                )
            )
            return issues

        # Check if the tail bytes + LF form one valid AuditRecord
        tail_with_lf = tail_bytes + b"\n"
        try:
            self._parse_audit_jsonl_bytes(tail_with_lf)
            issues.append(
                RecoveryIssue(
                    code="audit_partial_tail",
                    detail="Audit log has a final record missing trailing newline",
                    recoverable=True,
                )
            )
        except StorageError:
            issues.append(
                RecoveryIssue(
                    code="audit_partial_tail",
                    detail="Audit log has an incomplete final fragment",
                    recoverable=True,
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

        # Reauthorize audit path
        if log_path.is_symlink():
            raise StorageError("Audit log is a symlink, rejected for safety")

        # Snapshot exact before state
        before_bytes = _read_exact_bytes(log_path)
        before_hash = _bytes_hash(before_bytes)

        # Re-read and verify same before hash
        current_bytes = _read_exact_bytes(log_path)
        if _bytes_hash(current_bytes) != before_hash:
            raise ConflictError("Audit log changed between inspection and repair")

        # UTF-8 check
        try:
            before_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StorageError(
                "Audit log contains invalid UTF-8 — cannot safely repair tail",
                cause=exc,
            ) from exc

        # Check if the file already ends with LF using the ORIGINAL bytes
        if before_bytes.endswith(b"\n"):
            raise StorageError("Audit log already ends with newline — no repair needed")

        # Split at last physical \n — exact bytes, no normalization
        prefix_bytes, tail_bytes = self._split_final_unterminated_tail(before_bytes)

        # Verify complete prefix is valid (pure in-memory, may be empty for single-line)
        if not self._validate_audit_prefix_bytes(prefix_bytes):
            raise StorageError(
                "Audit log corruption is not limited to the final tail — "
                "manual intervention required"
            )

        # Determine repair mode
        tail_with_lf = tail_bytes + b"\n"
        try:
            self._parse_audit_jsonl_bytes(tail_with_lf)
            repair_mode = "append_missing_newline"
        except StorageError:
            repair_mode = "truncate_invalid_tail"

        # Perform repair
        if repair_mode == "append_missing_newline":
            expected_bytes = before_bytes + b"\n"
            try:
                fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | _O_BINARY)
            except OSError as exc:
                raise StorageError(
                    f"Failed to open audit log for append: {log_path}",
                    cause=exc,
                ) from exc
            try:
                written = os.write(fd, b"\n")
                if written != 1:
                    raise StorageError(
                        f"Short write when appending LF to audit log: wrote {written} of 1 byte"
                    )
                os.fsync(fd)
            except StorageError:
                raise
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
            # Truncate to exact prefix bytes
            expected_bytes = prefix_bytes
            try:
                fd = os.open(str(log_path), os.O_WRONLY | _O_BINARY)
            except OSError as exc:
                raise StorageError(
                    f"Failed to open audit log for truncation: {log_path}",
                    cause=exc,
                ) from exc
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

        # Verify exact repair bytes
        repaired_bytes = _read_exact_bytes(log_path)
        if repaired_bytes != expected_bytes:
            raise StorageError("Audit tail repair produced unexpected bytes")
        after_hash = _bytes_hash(repaired_bytes)

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

    def _find_unmatched_start_operation(
        self, session_id: str, records: list[AuditRecord]
    ) -> str | None:
        """Find the exactly one unmatched ``session.start`` operation ID.

        Groups records by ``operation_id`` and requires exactly one
        operation with intent(s) and zero committed records.

        Returns:
            The owning operation ID, or ``None`` if none or ambiguous.
        """
        start_by_op: dict[str, list[AuditRecord]] = {}
        for r in records:
            if r.operation == "session.start" and r.session == session_id:
                start_by_op.setdefault(r.operation_id, []).append(r)

        unmatched: list[str] = []
        for op_id, op_records in start_by_op.items():
            has_intent = any(r.phase == "intent" for r in op_records)
            has_committed = any(r.phase == "committed" for r in op_records)
            if has_intent and not has_committed:
                unmatched.append(op_id)

        if len(unmatched) == 1:
            return unmatched[0]
        return None

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

        # Verify audit ownership — exactly one unmatched operation
        try:
            records, _ = _read_audit_log(self._audit_service)
        except StorageError as exc:
            raise StorageError(
                f"Cannot verify audit ownership for session {session_id}: audit log is corrupt",
                cause=exc,
            ) from exc

        owning_op = self._find_unmatched_start_operation(session_id, records)
        if owning_op is None:
            raise StorageError(
                f"No single unmatched session.start intent found for {session_id} — "
                "cannot prove ownership of partial start"
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

        # Revalidate ownership — recovery intent must not confuse the check
        try:
            records2, _ = _read_audit_log(self._audit_service)
        except StorageError as exc:
            raise StorageError(
                f"Cannot revalidate audit ownership for session {session_id}",
                cause=exc,
            ) from exc

        owning_op2 = self._find_unmatched_start_operation(session_id, records2)
        if owning_op2 is None or owning_op2 != owning_op:
            raise ConflictError(
                f"Session {session_id} start ownership changed after recovery intent"
            )

        # Snapshot the expected cleanup plan before mutation
        cleanup_plan = self._build_cleanup_plan(paths)

        # Remove only exact known-empty artifacts — strict mutation semantics
        self._execute_cleanup_plan(cleanup_plan, session_id)

        # Verify final absence — all expected artifacts are gone
        self._verify_cleanup_absence(cleanup_plan, session_id)

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

    @staticmethod
    def _build_cleanup_plan(paths) -> dict[str, object]:
        """Build a deterministic plan of what to remove during cleanup.

        Returns:
            A dict with artifact names as keys and expected pre-removal
            state as values.
        """
        plan: dict[str, object] = {}
        plan["events_expected_exists"] = paths.raw_events.exists()
        if paths.raw_events.exists():
            plan["events_expected_size"] = paths.raw_events.stat().st_size
        plan["raw_dir_expected_exists"] = paths.raw_dir.exists()
        plan["session_dir_expected_exists"] = paths.session_dir.exists()
        return plan

    def _execute_cleanup_plan(self, plan: dict[str, object], session_id: str) -> None:
        """Execute the cleanup plan with strict mutation semantics.

        Raises:
            ConflictError: An artifact changed from expected state.
            StorageError: A filesystem operation failed.
        """
        paths = None  # resolved lazily

        # Remove events.jsonl
        if plan.get("events_expected_exists"):
            # Need paths to find the actual file
            paths = resolve_session_storage_paths(self._vault_root, session_id)
            ev = paths.raw_events
            if not ev.exists():
                raise ConflictError(f"events.jsonl for {session_id} disappeared before cleanup")
            if ev.is_symlink():
                raise ConflictError(
                    f"events.jsonl for {session_id} became a symlink before cleanup"
                )
            if not ev.is_file():
                raise ConflictError(f"events.jsonl for {session_id} is not a regular file")
            if ev.stat().st_size != 0:
                raise ConflictError(
                    f"events.jsonl for {session_id} became non-empty before cleanup"
                )
            try:
                ev.unlink()
            except OSError as exc:
                raise StorageError(
                    f"Failed to remove events.jsonl for {session_id}",
                    cause=exc,
                ) from exc

        # Remove raw_dir if empty
        if plan.get("raw_dir_expected_exists"):
            if paths is None:
                paths = resolve_session_storage_paths(self._vault_root, session_id)
            rd = paths.raw_dir
            if rd.exists():
                try:
                    contents = list(rd.iterdir())
                except OSError as exc:
                    raise StorageError(
                        f"Failed to list raw session directory for {session_id}",
                        cause=exc,
                    ) from exc
                if contents:
                    raise ConflictError(
                        f"Raw session directory for {session_id} is not empty before cleanup"
                    )
                try:
                    rd.rmdir()
                except OSError as exc:
                    raise StorageError(
                        f"Failed to remove raw session directory for {session_id}",
                        cause=exc,
                    ) from exc

        # Remove session_dir if empty
        if plan.get("session_dir_expected_exists"):
            if paths is None:
                paths = resolve_session_storage_paths(self._vault_root, session_id)
            sd = paths.session_dir
            if sd.exists():
                try:
                    contents = list(sd.iterdir())
                except OSError as exc:
                    raise StorageError(
                        f"Failed to list session directory for {session_id}",
                        cause=exc,
                    ) from exc
                if contents:
                    raise ConflictError(
                        f"Session directory for {session_id} is not empty before cleanup"
                    )
                try:
                    sd.rmdir()
                except OSError as exc:
                    raise StorageError(
                        f"Failed to remove session directory for {session_id}",
                        cause=exc,
                    ) from exc

    def _verify_cleanup_absence(self, plan: dict[str, object], session_id: str) -> None:
        """Verify all expected artifacts are absent after cleanup.

        Raises:
            StorageError: An artifact that should be absent still exists.
        """
        paths = resolve_session_storage_paths(self._vault_root, session_id)

        if plan.get("events_expected_exists") and paths.raw_events.exists():
            raise StorageError(f"events.jsonl for {session_id} was not removed during cleanup")
        if plan.get("raw_dir_expected_exists") and paths.raw_dir.exists():
            raise StorageError(
                f"Raw session directory for {session_id} was not removed during cleanup"
            )
        if plan.get("session_dir_expected_exists") and paths.session_dir.exists():
            raise StorageError(f"Session directory for {session_id} was not removed during cleanup")

    # ── Event-tail metadata prerequisite ──────────────────────────────────

    def _validate_metadata_for_event_recovery(self, session_id: str, paths) -> tuple[bytes, str]:
        """Validate that metadata exists, is valid, and has allowed status.

        Returns:
            ``(metadata_bytes, metadata_hash)``.

        Raises:
            StorageError: Metadata is missing, corrupt, or has disallowed status.
        """
        metadata_path = paths.raw_metadata
        if not metadata_path.exists():
            raise StorageError(f"Session {session_id} has no metadata.json — cannot repair events")
        if metadata_path.is_symlink():
            raise StorageError(f"metadata.json for {session_id} is a symlink — rejected for safety")
        if metadata_path.is_dir():
            raise StorageError(f"metadata.json for {session_id} is a directory")

        meta_bytes = _read_exact_bytes(metadata_path)
        meta_text = meta_bytes.decode("utf-8")
        meta = _deserialize_metadata(meta_text, expected_id=session_id)

        if meta.session.status not in ("active", "completed"):
            raise StorageError(
                f"Session {session_id} has status {meta.session.status!r} — "
                "event-tail recovery requires active or completed status"
            )

        return meta_bytes, _bytes_hash(meta_bytes)

    # ── repair_event_tail — append-LF or truncate ─────────────────────────

    def repair_event_tail(
        self,
        session_id: str,
        *,
        audit: AuditContext,
    ) -> RecoveryActionResult:
        """Repair a provably partial final event-log tail.

        Recovery is allowed only when:
        - Canonical metadata exists with active/completed status.
        - The audit log is clean (no partial tail, no corruption).

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

        # Require valid metadata with allowed status
        meta_before_bytes, meta_before_hash = self._validate_metadata_for_event_recovery(
            session_id, paths
        )

        # Require clean audit log first
        try:
            self._audit_service.read_all()
        except (StorageError, UnicodeDecodeError) as exc:
            raise StorageError(
                f"Audit log is corrupt — repair audit tail before repairing events for {session_id}",
                cause=exc,
            ) from exc

        # Snapshot exact before state
        before_bytes = _read_exact_bytes(events_path)
        before_hash = _bytes_hash(before_bytes)

        # UTF-8 check
        try:
            before_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StorageError(
                f"events.jsonl for {session_id} contains invalid UTF-8",
                cause=exc,
            ) from exc

        # Try strict parsing first
        parse_succeeded = False
        try:
            _parse_events_jsonl(before_bytes.decode("utf-8"))
            parse_succeeded = True
        except StorageError:
            pass

        if parse_succeeded:
            raise StorageError(f"events.jsonl for {session_id} is already valid — no repair needed")

        # Check if the file already ends with LF using the ORIGINAL bytes
        if before_bytes.endswith(b"\n"):
            raise StorageError(
                f"events.jsonl for {session_id} ends with newline but is corrupt — "
                "corruption is not limited to the final tail"
            )

        # Split at last physical \n — exact bytes, no normalization
        prefix_bytes, tail_bytes = self._split_final_unterminated_tail(before_bytes)

        # Verify complete prefix is valid (may be empty for single-line file)
        if prefix_bytes:
            try:
                _parse_events_jsonl(prefix_bytes.decode("utf-8"))
            except StorageError as exc:
                raise StorageError(
                    f"events.jsonl for {session_id}: corruption is not limited to "
                    "the final tail — manual intervention required",
                    cause=exc,
                ) from exc

        # Determine repair mode
        tail_with_lf = tail_bytes + b"\n"
        try:
            _parse_events_jsonl(tail_with_lf.decode("utf-8"))
            repair_mode = "append_missing_newline"
        except StorageError:
            repair_mode = "truncate_invalid_tail"

        # Reauthorize after inspection
        self._reauthorize_roots()
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        events_path = paths.raw_events

        # Re-read and verify unchanged
        current_bytes = _read_exact_bytes(events_path)
        if _bytes_hash(current_bytes) != before_hash:
            raise ConflictError(
                f"events.jsonl for {session_id} changed between inspection and repair"
            )

        # Re-check metadata unchanged
        meta_current_bytes = _read_exact_bytes(paths.raw_metadata)
        if _bytes_hash(meta_current_bytes) != meta_before_hash:
            raise ConflictError(
                f"Session metadata for {session_id} changed before event-tail repair intent"
            )
        # Revalidate metadata status
        meta_current_text = meta_current_bytes.decode("utf-8")
        meta_current = _deserialize_metadata(meta_current_text, expected_id=session_id)
        if meta_current.session.status not in ("active", "completed"):
            raise StorageError(
                f"Session {session_id} status changed to {meta_current.session.status!r} "
                "before event-tail repair"
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

        # Re-read and verify events unchanged
        current_bytes2 = _read_exact_bytes(events_path)
        if _bytes_hash(current_bytes2) != before_hash:
            raise ConflictError(f"events.jsonl for {session_id} changed after recovery intent")

        # Recheck metadata unchanged after intent
        meta_post_intent_bytes = _read_exact_bytes(paths.raw_metadata)
        if _bytes_hash(meta_post_intent_bytes) != meta_before_hash:
            raise ConflictError(f"Session metadata for {session_id} changed after recovery intent")

        # Perform repair
        if repair_mode == "append_missing_newline":
            expected_bytes = before_bytes + b"\n"
            try:
                fd = os.open(str(events_path), os.O_WRONLY | os.O_APPEND | _O_BINARY)
            except OSError as exc:
                raise StorageError(
                    f"Failed to open events.jsonl for append: {events_path}",
                    cause=exc,
                ) from exc
            try:
                written = os.write(fd, b"\n")
                if written != 1:
                    raise StorageError(
                        f"Short write when appending LF to events.jsonl: wrote {written} of 1 byte"
                    )
                os.fsync(fd)
            except StorageError:
                raise
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
            expected_bytes = prefix_bytes
            try:
                fd = os.open(str(events_path), os.O_WRONLY | _O_BINARY)
            except OSError as exc:
                raise StorageError(
                    f"Failed to open events.jsonl for truncation: {events_path}",
                    cause=exc,
                ) from exc
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

        # Verify exact repair bytes
        repaired_bytes = _read_exact_bytes(events_path)
        if repaired_bytes != expected_bytes:
            raise StorageError(f"Event-tail repair for {session_id} produced unexpected bytes")
        after_hash = _bytes_hash(repaired_bytes)

        # Strictly parse entire event log
        try:
            all_events = _parse_events_jsonl(repaired_bytes.decode("utf-8"))
        except StorageError as exc:
            raise StorageError(
                f"Event-tail repair for {session_id} completed but strict parsing failed",
                cause=exc,
            ) from exc

        # Recheck metadata after physical repair
        meta_final_bytes = _read_exact_bytes(paths.raw_metadata)
        if _bytes_hash(meta_final_bytes) != meta_before_hash:
            raise StorageError(
                f"Session metadata for {session_id} changed after event-tail physical repair"
            )

        # Verify all complete prior events unchanged
        if prefix_bytes:
            try:
                prior_events = _parse_events_jsonl(prefix_bytes.decode("utf-8"))
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

    # ── Pure in-memory audit validation ──────────────────────────────────

    @staticmethod
    def _parse_audit_jsonl_bytes(data: bytes) -> list[AuditRecord]:
        """Parse audit JSONL bytes in-memory.

        Uses the same strict logic as ``AuditService.read_all()`` but
        operates on a bytes buffer instead of a file.

        Returns:
            All valid ``AuditRecord`` values in order.

        Raises:
            StorageError: Malformed JSON, invalid record, or blank line.
        """
        if not data:
            return []

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StorageError("Audit data is not valid UTF-8", cause=exc) from exc

        records: list[AuditRecord] = []
        for line_no, raw_line in enumerate(text.splitlines(keepends=False), start=1):
            stripped = raw_line.strip()
            if not stripped:
                raise StorageError(f"Audit corruption at line {line_no}: unexpected blank line")
            try:
                parsed = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise StorageError(
                    f"Audit corruption at line {line_no}: malformed JSON",
                    cause=exc,
                ) from exc
            if not isinstance(parsed, dict):
                raise StorageError(
                    f"Audit corruption at line {line_no}: expected JSON object, "
                    f"got {type(parsed).__name__}"
                )
            try:
                records.append(AuditRecord.model_validate(parsed))
            except Exception as exc:
                raise StorageError(
                    f"Audit corruption at line {line_no}: invalid AuditRecord",
                    cause=exc,
                ) from exc
        return records

    @staticmethod
    def _validate_audit_prefix_bytes(prefix_bytes: bytes) -> bool:
        """Check if complete audit prefix bytes are strictly valid.

        Pure in-memory — no temporary files.

        Returns:
            True if valid, False if corrupt.
        """
        if not prefix_bytes:
            return True
        try:
            ObsidianSessionRecoveryRepository._parse_audit_jsonl_bytes(prefix_bytes)
            return True
        except StorageError:
            return False

    @staticmethod
    def _split_final_unterminated_tail(
        data: bytes,
    ) -> tuple[bytes, bytes]:
        """Split bytes at the last physical ``\\n``.

        Returns:
            ``(prefix_bytes, tail_bytes)`` where ``prefix_bytes`` includes
            the final ``\\n`` (if any), and ``tail_bytes`` is everything
            after it.
        """
        last_lf = data.rfind(b"\n")
        if last_lf >= 0:
            return data[: last_lf + 1], data[last_lf + 1 :]
        return b"", data

    # ── Session inspection ────────────────────────────────────────────────

    def _inspect_sessions(self) -> list[RecoveryIssue]:
        """Scan session directories for issues.

        Discovers candidate session IDs from the union of:
        - ``Sessions/*``
        - ``_system/raw/sessions/*``

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []
        sessions_root = self._vault_root / "Sessions"
        raw_root = self._vault_root / "_system" / "raw" / "sessions"

        # Collect candidate IDs from both roots
        candidate_ids: set[str] = set()

        for root in (sessions_root, raw_root):
            if not root.exists() or not root.is_dir():
                continue
            try:
                for entry in sorted(root.iterdir(), key=lambda p: p.name):
                    # Report unsafe entries rather than silently skipping
                    if entry.is_symlink():
                        sid = entry.name
                        if sid:
                            issues.append(
                                RecoveryIssue(
                                    code="unsafe_session_path",
                                    session_id=sid,
                                    detail=f"Session path {entry} is a symlink",
                                    recoverable=False,
                                )
                            )
                        continue
                    if not entry.is_dir():
                        continue
                    candidate_ids.add(entry.name)
            except OSError:
                continue

        active_count = 0

        for session_id in sorted(candidate_ids):
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

        # UTF-8 check
        try:
            raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(
                RecoveryIssue(
                    code="event_corrupt",
                    session_id=session_id,
                    detail=f"events.jsonl for {session_id} contains invalid UTF-8",
                    recoverable=False,
                )
            )
            return issues

        # Try strict parsing first
        try:
            _parse_events_jsonl(raw_bytes.decode("utf-8"))
            return issues  # No issues
        except StorageError:
            pass

        # Physical-LF classification
        if raw_bytes.endswith(b"\n"):
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

        # Split at last physical \n — exact bytes
        prefix_bytes, tail_bytes = self._split_final_unterminated_tail(raw_bytes)

        # Validate the complete prefix (may be empty for single-line file)
        if prefix_bytes:
            try:
                _parse_events_jsonl(prefix_bytes.decode("utf-8"))
            except StorageError:
                issues.append(
                    RecoveryIssue(
                        code="event_corrupt",
                        session_id=session_id,
                        detail=f"events.jsonl for {session_id} has corruption in a completed record",
                        recoverable=False,
                    )
                )
                return issues

        # Check if the tail bytes + LF form one valid event
        tail_with_lf = tail_bytes + b"\n"
        try:
            _parse_events_jsonl(tail_with_lf.decode("utf-8"))
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
                    detail=f"events.jsonl for {session_id} has an incomplete final fragment",
                    recoverable=True,
                )
            )

        return issues

    def _inspect_partial_start(self, session_id: str, paths) -> list[RecoveryIssue]:
        """Check if a session directory without metadata is a recoverable partial start.

        Ownership is determined by grouping ``session.start`` records by
        ``operation_id``.  An unmatched start operation has at least one
        intent record and zero committed records.  Exactly one such
        operation must exist for automatic recovery.

        Returns:
            A list of issues (may be empty).
        """
        issues: list[RecoveryIssue] = []

        # Check for at least one candidate artifact
        has_session_dir = paths.session_dir.exists()
        has_raw_dir = paths.raw_dir.exists()

        if not has_session_dir and not has_raw_dir:
            return issues

        # Check for unmatched session.start intent by operation_id
        try:
            records, _ = _read_audit_log(self._audit_service)
        except StorageError:
            return issues

        # Group session.start records for this session by operation_id
        start_by_op: dict[str, list[AuditRecord]] = {}
        for r in records:
            if r.operation == "session.start" and r.session == session_id:
                start_by_op.setdefault(r.operation_id, []).append(r)

        # Find unmatched operation IDs (have intent, no committed)
        unmatched_ops: list[str] = []
        for op_id, op_records in start_by_op.items():
            has_intent = any(r.phase == "intent" for r in op_records)
            has_committed = any(r.phase == "committed" for r in op_records)
            if has_intent and not has_committed:
                unmatched_ops.append(op_id)

        if not unmatched_ops:
            # No unmatched intent — not a recoverable partial start
            if start_by_op:
                # Has committed records — not a partial start, return no issue
                return issues
            # No audit ownership at all
            issues.append(
                RecoveryIssue(
                    code="partial_start",
                    session_id=session_id,
                    detail=f"Session {session_id} has artifacts but no matching session.start intent",
                    recoverable=False,
                )
            )
            return issues

        if len(unmatched_ops) > 1:
            # Multiple unmatched start operations — ambiguous ownership
            issues.append(
                RecoveryIssue(
                    code="partial_start",
                    session_id=session_id,
                    detail=(
                        f"Session {session_id} has {len(unmatched_ops)} unmatched "
                        "session.start operations — ambiguous ownership"
                    ),
                    recoverable=False,
                )
            )
            return issues

        # Exactly one unmatched operation
        owning_op_id = unmatched_ops[0]

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
                operation_id=owning_op_id,
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
