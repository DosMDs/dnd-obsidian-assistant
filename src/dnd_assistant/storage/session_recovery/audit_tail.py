"""Audit-tail inspection and self-targeting repair.

This module owns:

- ``_parse_audit_jsonl_bytes`` — strict in-memory audit JSONL parsing.
- ``_validate_audit_prefix_bytes`` — check complete prefix validity.
- ``_split_final_unterminated_tail`` — split bytes at last ``\\n``.
- ``_inspect_audit`` — classify audit log issues.
- ``repair_audit_tail`` — self-targeting audit tail repair.
"""

from __future__ import annotations

import json
import os

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditContext, AuditRecord
from dnd_assistant.storage.session_events import _O_BINARY
from dnd_assistant.storage.session_recovery.support import (
    _build_audit_record,
    _bytes_hash,
    _read_exact_bytes,
)
from dnd_assistant.storage.session_recovery.types import RecoveryActionResult, RecoveryIssue

# ── Pure in-memory audit validation ──────────────────────────────────────


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


def _validate_audit_prefix_bytes(prefix_bytes: bytes) -> bool:
    """Check if complete audit prefix bytes are strictly valid.

    Pure in-memory — no temporary files.

    Returns:
        True if valid, False if corrupt.
    """
    if not prefix_bytes:
        return True
    try:
        _parse_audit_jsonl_bytes(prefix_bytes)
        return True
    except StorageError:
        return False


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


# ── Audit inspection ─────────────────────────────────────────────────────


def _inspect_audit(audit_service) -> list[RecoveryIssue]:
    """Inspect the audit log for corruption or partial tails.

    Returns:
        A list of issues (may be empty).
    """
    issues: list[RecoveryIssue] = []
    log_path = audit_service.log_path

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
            audit_service.read_all()
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
    prefix_bytes, tail_bytes = _split_final_unterminated_tail(raw_bytes)

    # Validate the complete prefix strictly
    if not _validate_audit_prefix_bytes(prefix_bytes):
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
        _parse_audit_jsonl_bytes(tail_with_lf)
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


# ── Audit tail repair ────────────────────────────────────────────────────


def repair_audit_tail(
    audit_service,
    *,
    audit: AuditContext,
) -> RecoveryActionResult:
    """Repair a provably partial final audit-log tail.

    This is an exceptional self-targeting recovery path.  The audit
    log cannot write a durable intent into itself while corrupt, so
    the normal two-phase audit is replaced by:
    repair -> verify -> append recovery marker.

    Args:
        audit_service: The audit service for reading/writing.
        audit: Audit context for the recovery marker.

    Returns:
        A ``RecoveryActionResult`` with before/after hashes.

    Raises:
        ConflictError: The audit log changed between inspection and
            repair.
        StorageError: The corruption is not limited to the final tail,
            or the repair itself failed.
    """
    log_path = audit_service.log_path

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
    prefix_bytes, tail_bytes = _split_final_unterminated_tail(before_bytes)

    # Verify complete prefix is valid (pure in-memory, may be empty for single-line)
    if not _validate_audit_prefix_bytes(prefix_bytes):
        raise StorageError(
            "Audit log corruption is not limited to the final tail — manual intervention required"
        )

    # Determine repair mode
    tail_with_lf = tail_bytes + b"\n"
    try:
        _parse_audit_jsonl_bytes(tail_with_lf)
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
        audit_service.read_all()
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
        audit_service.append(marker)
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
