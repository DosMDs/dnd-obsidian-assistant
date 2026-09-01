"""Partial-start ownership verification and cleanup.

This module owns:

- ``_find_unmatched_start_operation`` — find the one unmatched start op.
- ``_build_cleanup_plan`` — deterministic cleanup plan.
- ``_execute_cleanup_plan`` — strict mutation semantics.
- ``_verify_cleanup_absence`` — final absence verification.
- ``_is_safe_partial_start`` — safe-state classification.
- ``cleanup_partial_start`` — explicit cleanup orchestration.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditRecord
from dnd_assistant.storage.session_metadata import (
    _validate_session_runtime_roots,
)
from dnd_assistant.storage.session_paths import (
    resolve_session_storage_paths,
)
from dnd_assistant.storage.session_recovery.support import (
    _build_audit_record,
    _build_partial_start_snapshot,
    _require_clean_audit_log,
)
from dnd_assistant.storage.session_recovery.types import RecoveryActionResult


def _find_unmatched_start_operation(session_id: str, records: list[AuditRecord]) -> str | None:
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


def _execute_cleanup_plan(plan: dict[str, object], session_id: str, vault_root: Path) -> None:
    """Execute the cleanup plan with strict mutation semantics.

    Raises:
        ConflictError: An artifact changed from expected state.
        StorageError: A filesystem operation failed.
    """
    paths = None  # resolved lazily

    # Remove events.jsonl
    if plan.get("events_expected_exists"):
        # Need paths to find the actual file
        paths = resolve_session_storage_paths(vault_root, session_id)
        ev = paths.raw_events
        if not ev.exists():
            raise ConflictError(f"events.jsonl for {session_id} disappeared before cleanup")
        if ev.is_symlink():
            raise ConflictError(f"events.jsonl for {session_id} became a symlink before cleanup")
        if not ev.is_file():
            raise ConflictError(f"events.jsonl for {session_id} is not a regular file")
        if ev.stat().st_size != 0:
            raise ConflictError(f"events.jsonl for {session_id} became non-empty before cleanup")
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
            paths = resolve_session_storage_paths(vault_root, session_id)
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
            paths = resolve_session_storage_paths(vault_root, session_id)
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


def _verify_cleanup_absence(plan: dict[str, object], session_id: str, vault_root: Path) -> None:
    """Verify all expected artifacts are absent after cleanup.

    Raises:
        StorageError: An artifact that should be absent still exists.
    """
    paths = resolve_session_storage_paths(vault_root, session_id)

    if plan.get("events_expected_exists") and paths.raw_events.exists():
        raise StorageError(f"events.jsonl for {session_id} was not removed during cleanup")
    if plan.get("raw_dir_expected_exists") and paths.raw_dir.exists():
        raise StorageError(f"Raw session directory for {session_id} was not removed during cleanup")
    if plan.get("session_dir_expected_exists") and paths.session_dir.exists():
        raise StorageError(f"Session directory for {session_id} was not removed during cleanup")


def _is_safe_partial_start(session_id: str, paths) -> bool:
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


def cleanup_partial_start(
    vault_root: Path,
    audit_service,
    session_id: str,
    *,
    audit,
) -> RecoveryActionResult:
    """Clean up a provably owned partial session start.

    Only exact known-empty artifacts are removed.  No recursive
    deletion.  No unexpected content is removed.

    Args:
        vault_root: The resolved Vault root path.
        audit_service: The audit service.
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
    _validate_session_runtime_roots(vault_root)
    paths = resolve_session_storage_paths(vault_root, session_id)

    # Build pre-cleanup snapshot
    before_hash = _build_partial_start_snapshot(paths.session_dir, paths.raw_dir, paths.raw_events)

    # Verify audit ownership — exactly one unmatched operation
    # Requires physically clean audit (no missing final LF)
    try:
        records = _require_clean_audit_log(audit_service)
    except StorageError as exc:
        raise StorageError(
            f"Cannot verify audit ownership for session {session_id}: "
            f"audit log is corrupt or physically partial — "
            f"repair_audit_tail() must be performed first",
            cause=exc,
        ) from exc

    owning_op = _find_unmatched_start_operation(session_id, records)
    if owning_op is None:
        raise StorageError(
            f"No single unmatched session.start intent found for {session_id} — "
            "cannot prove ownership of partial start"
        )

    # Verify safe state
    if not _is_safe_partial_start(session_id, paths):
        raise StorageError(
            f"Session {session_id} has unexpected content — cannot safely clean up partial start"
        )

    # Reauthorize paths
    _validate_session_runtime_roots(vault_root)
    paths = resolve_session_storage_paths(vault_root, session_id)

    # Re-inspect exact snapshot
    current_hash = _build_partial_start_snapshot(paths.session_dir, paths.raw_dir, paths.raw_events)
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
    audit_service.append(intent_record)

    # Reauthorize after durable intent
    _validate_session_runtime_roots(vault_root)
    paths = resolve_session_storage_paths(vault_root, session_id)

    # Re-inspect snapshot unchanged
    current_hash2 = _build_partial_start_snapshot(
        paths.session_dir, paths.raw_dir, paths.raw_events
    )
    if current_hash2 != before_hash:
        raise ConflictError(f"Partial-start state for {session_id} changed after recovery intent")

    # Revalidate ownership — recovery intent must not confuse the check
    # The newly appended intent ends with LF and should be physically clean
    try:
        records2 = _require_clean_audit_log(audit_service)
    except StorageError as exc:
        raise StorageError(
            f"Cannot revalidate audit ownership for session {session_id}",
            cause=exc,
        ) from exc

    owning_op2 = _find_unmatched_start_operation(session_id, records2)
    if owning_op2 is None or owning_op2 != owning_op:
        raise ConflictError(f"Session {session_id} start ownership changed after recovery intent")

    # Snapshot the expected cleanup plan before mutation
    cleanup_plan = _build_cleanup_plan(paths)

    # Remove only exact known-empty artifacts — strict mutation semantics
    _execute_cleanup_plan(cleanup_plan, session_id, vault_root)

    # Verify final absence — all expected artifacts are gone
    _verify_cleanup_absence(cleanup_plan, session_id, vault_root)

    # Build after snapshot
    after_hash = _build_partial_start_snapshot(paths.session_dir, paths.raw_dir, paths.raw_events)

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
        audit_service.append(committed_record)
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
