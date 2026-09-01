"""Event-tail validation and repair.

This module owns:

- ``_validate_metadata_for_event_recovery`` — metadata prerequisite check.
- ``_inspect_events`` — classify event log issues.
- ``repair_event_tail`` — explicit event tail repair.
"""

from __future__ import annotations

import os

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.session_events import (
    _O_BINARY,
    _parse_events_jsonl,
)
from dnd_assistant.storage.session_metadata import (
    _deserialize as _deserialize_metadata,
)
from dnd_assistant.storage.session_metadata import (
    _validate_session_runtime_roots,
)
from dnd_assistant.storage.session_paths import (
    resolve_session_storage_paths,
)
from dnd_assistant.storage.session_recovery.support import (
    _build_audit_record,
    _bytes_hash,
    _read_exact_bytes,
    _require_clean_audit_log,
)
from dnd_assistant.storage.session_recovery.types import RecoveryActionResult, RecoveryIssue

# ── Event-tail metadata prerequisite ──────────────────────────────────────


def _validate_metadata_for_event_recovery(session_id: str, paths) -> tuple[bytes, str]:
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
    try:
        meta_text = meta_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"metadata.json for {session_id} contains invalid UTF-8",
            cause=exc,
        ) from exc
    meta = _deserialize_metadata(meta_text, expected_id=session_id)

    if meta.session.status not in ("active", "completed"):
        raise StorageError(
            f"Session {session_id} has status {meta.session.status!r} — "
            "event-tail recovery requires active or completed status"
        )

    return meta_bytes, _bytes_hash(meta_bytes)


# ── Event inspection ──────────────────────────────────────────────────────


def _inspect_events(session_id: str, events_path) -> list[RecoveryIssue]:
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
    from dnd_assistant.storage.session_recovery.audit_tail import _split_final_unterminated_tail

    prefix_bytes, tail_bytes = _split_final_unterminated_tail(raw_bytes)

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


# ── Event tail repair ─────────────────────────────────────────────────────


def repair_event_tail(
    vault_root,
    audit_service,
    session_id: str,
    *,
    audit,
) -> RecoveryActionResult:
    """Repair a provably partial final event-log tail.

    Recovery is allowed only when:
    - Canonical metadata exists with active/completed status.
    - The audit log is clean (no partial tail, no corruption).

    Args:
        vault_root: The resolved Vault root path.
        audit_service: The audit service.
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
    _validate_session_runtime_roots(vault_root)
    paths = resolve_session_storage_paths(vault_root, session_id)
    events_path = paths.raw_events

    if not events_path.exists():
        raise StorageError(f"events.jsonl not found for session {session_id}")

    if events_path.is_symlink():
        raise StorageError(f"events.jsonl is a symlink, rejected for safety: {events_path}")

    if events_path.is_dir():
        raise StorageError(f"events.jsonl is a directory: {events_path}")

    # Require valid metadata with allowed status
    meta_before_bytes, meta_before_hash = _validate_metadata_for_event_recovery(session_id, paths)

    # Require physically clean audit log first
    try:
        _require_clean_audit_log(audit_service)
    except StorageError as exc:
        raise StorageError(
            f"Audit log is corrupt or physically partial — "
            f"repair_audit_tail() must be performed before "
            f"repairing events for {session_id}",
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
    from dnd_assistant.storage.session_recovery.audit_tail import _split_final_unterminated_tail

    prefix_bytes, tail_bytes = _split_final_unterminated_tail(before_bytes)

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
    _validate_session_runtime_roots(vault_root)
    paths = resolve_session_storage_paths(vault_root, session_id)
    events_path = paths.raw_events

    # Re-read and verify unchanged
    current_bytes = _read_exact_bytes(events_path)
    if _bytes_hash(current_bytes) != before_hash:
        raise ConflictError(f"events.jsonl for {session_id} changed between inspection and repair")

    # Re-check metadata unchanged
    meta_current_bytes = _read_exact_bytes(paths.raw_metadata)
    if _bytes_hash(meta_current_bytes) != meta_before_hash:
        raise ConflictError(
            f"Session metadata for {session_id} changed before event-tail repair intent"
        )
    # Revalidate metadata status
    try:
        meta_current_text = meta_current_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"metadata.json for {session_id} now contains invalid UTF-8",
            cause=exc,
        ) from exc
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
    audit_service.append(intent_record)

    # Reauthorize after durable intent
    _validate_session_runtime_roots(vault_root)
    paths = resolve_session_storage_paths(vault_root, session_id)
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
        audit_service.append(committed_record)
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
