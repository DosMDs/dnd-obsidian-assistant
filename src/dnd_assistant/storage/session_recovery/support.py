"""Shared recovery primitives used by more than one recovery area.

This module provides:

- ``_bytes_hash`` — SHA-256 hash of exact bytes.
- ``_content_hash`` — SHA-256 hash of UTF-8 content.
- ``_read_exact_bytes`` — read a file's exact bytes.
- ``_read_audit_log`` — read and parse the audit log.
- ``_require_clean_audit_log`` — validate physical JSONL append safety.
- ``_build_partial_start_snapshot`` — deterministic canonical snapshot.
- ``_build_audit_record`` — build an AuditRecord for recovery operations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditRecord, AuditService
from dnd_assistant.storage.session_metadata import _read_exact_text as _read_meta_text

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


def _require_clean_audit_log(audit_service: AuditService) -> list[AuditRecord]:
    """Read and validate the audit log, requiring physical JSONL append safety.

    Contract:
    - Missing audit file → return [] (empty valid state).
    - Empty audit file (``b""``) → return [].
    - Non-empty audit file MUST end with ``b"\\n"``, otherwise ``StorageError``.
    - All complete bytes are parsed and validated strictly.
    - Invalid UTF-8, blank lines, malformed JSON, non-object JSON, and invalid
      ``AuditRecord`` all raise ``StorageError``.

    This is a read-only check — no temporary files, no repair, no appended
    records, no filesystem mutation.

    Returns:
        All valid ``AuditRecord`` values in physical order.

    Raises:
        StorageError: The audit log is missing a final LF (physically partial),
            contains invalid UTF-8, or has structural corruption.
    """
    log_path = audit_service.log_path

    if not log_path.exists():
        return []

    raw_bytes = _read_exact_bytes(log_path)

    if not raw_bytes:
        return []

    # UTF-8 check — must not leak UnicodeDecodeError
    try:
        raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError(
            "Audit log contains invalid UTF-8 — repair audit tail first",
            cause=exc,
        ) from exc

    # Non-empty audit MUST end with physical LF
    if not raw_bytes.endswith(b"\n"):
        raise StorageError(
            "Audit log has a valid final record missing trailing newline — "
            "repair_audit_tail() must be performed before recovery"
        )

    # Parse and validate all complete bytes strictly
    try:
        return audit_service.read_all()
    except (StorageError, UnicodeDecodeError) as exc:
        raise StorageError(
            "Audit log has structural corruption in a completed record",
            cause=exc,
        ) from exc


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
