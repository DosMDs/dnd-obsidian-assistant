"""Read-only session runtime inspection.

This module owns:

- ``inspect_runtime`` — read-only inspection of Vault runtime state.
- ``_inspect_sessions`` — scan session directories for issues.
- ``_inspect_partial_start`` — check for recoverable partial starts.
- ``_inspect_unresolved_intents`` — check for unresolved audit intents.
"""

from __future__ import annotations

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditRecord
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
from dnd_assistant.storage.session_recovery.audit_tail import _inspect_audit
from dnd_assistant.storage.session_recovery.event_tail import _inspect_events
from dnd_assistant.storage.session_recovery.support import (
    _read_audit_log,
)
from dnd_assistant.storage.session_recovery.types import RecoveryIssue, SessionRecoveryReport


def inspect_runtime(vault_root, audit_service) -> SessionRecoveryReport:
    """Read-only inspection of current Vault runtime state.

    This method must NOT write, truncate, delete, or modify any
    filesystem state.

    Returns:
        A ``SessionRecoveryReport`` with ordered issues.

    Raises:
        StorageError: A canonical runtime root is unsafe.
    """
    _validate_session_runtime_roots(vault_root)
    issues: list[RecoveryIssue] = []

    # 1. Check audit log
    audit_issues = _inspect_audit(audit_service)
    issues.extend(audit_issues)

    # 2. Scan sessions
    session_issues = _inspect_sessions(vault_root, audit_service)
    issues.extend(session_issues)

    # 3. Sort deterministically
    issues.sort(key=lambda i: (i.code, i.session_id or "", i.operation_id or ""))

    return SessionRecoveryReport(issues)


def _inspect_sessions(vault_root, audit_service) -> list[RecoveryIssue]:
    """Scan session directories for issues.

    Discovers candidate session IDs from the union of:
    - ``Sessions/*``
    - ``_system/raw/sessions/*``

    Returns:
        A list of issues (may be empty).
    """
    issues: list[RecoveryIssue] = []
    sessions_root = vault_root / "Sessions"
    raw_root = vault_root / "_system" / "raw" / "sessions"

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
            paths = resolve_session_storage_paths(vault_root, session_id)
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
            events_issues = _inspect_events(session_id, events_path)
            issues.extend(events_issues)

            # Check for unresolved audit intents
            intent_issues = _inspect_unresolved_intents(session_id, audit_service)
            issues.extend(intent_issues)

        else:
            # metadata.json absent — check for partial start
            partial_issues = _inspect_partial_start(session_id, paths, audit_service)
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


def _inspect_partial_start(session_id: str, paths, audit_service) -> list[RecoveryIssue]:
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
        records, _ = _read_audit_log(audit_service)
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
    from dnd_assistant.storage.session_recovery.partial_start import _is_safe_partial_start

    if not _is_safe_partial_start(session_id, paths):
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


def _inspect_unresolved_intents(session_id: str, audit_service) -> list[RecoveryIssue]:
    """Check for unresolved audit intents for session operations.

    Returns:
        A list of issues (may be empty).
    """
    issues: list[RecoveryIssue] = []

    try:
        records, _ = _read_audit_log(audit_service)
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
