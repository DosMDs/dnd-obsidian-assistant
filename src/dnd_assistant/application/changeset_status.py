"""S10-06 ChangeSet apply-attempt evidence, audit correlation and status.

This module owns the durable application-layer evidence produced by a ChangeSet
apply attempt and the fail-closed rules that decide whether another apply may
start:

    apply_changeset(...) -> structured result
    -> one append-only ApplyAttempt record                 (record_apply_attempt)
    -> deterministic correlation with repository audit     (correlate_audit)
    -> derived workflow status / applicability gate        (build_changeset_status,
                                                             assert_changeset_applicable)

The append-only artifact is a **workflow/control** record, never campaign entity
truth:

    <vault>/_system/changesets/<changeset_id>.apply.jsonl

Every record binds the exact ``changeset_id`` and the exact
``ChangeSetFingerprint`` of the reviewed proposal.  Records are never rewritten
or truncated; malformed or partial history fails closed (``StorageError``) and
contradictory history fails closed (``ConflictError``).

Audit correlation uses only the deterministic per-operation id
``f"{changeset_id}:{index}"`` and the repository's two audit phases:

    no records              -> NOT_ATTEMPTED
    exactly [intent]        -> UNCONFIRMED   (may have been interrupted)
    exactly [intent, committed] -> COMMITTED (repository considers it committed)

Any other sequence is contradictory.  Entity filesystem state is **never**
inferred from the audit log alone.

Repository recovery is not duplicated here: this module only reads application
artifacts and already-produced audit records.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, shutil,
    tempfile, subprocess, or a concrete storage implementation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic.types import AwareDatetime

from dnd_assistant.application.changeset_apply import (
    ApplyCommitState,
    ApplyFailure,
    ApplySource,
    ChangeSetApplyOutcome,
    ChangeSetApplyResult,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetFingerprint,
    compute_changeset_fingerprint,
)
from dnd_assistant.domain.changeset import ChangeSet, ChangeSetId
from dnd_assistant.errors import ConflictError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditRecord
    from dnd_assistant.storage.changeset_store import ChangeSetStore

# ── Audit-derived operation state ─────────────────────────────────────────


class AuditOperationState(StrEnum):
    """Repository audit evidence for one ChangeSet operation index."""

    NOT_ATTEMPTED = "not_attempted"
    """No audit record with the deterministic operation id."""

    UNCONFIRMED = "unconfirmed"
    """Exactly one ``intent`` record: the mutation may have been interrupted."""

    COMMITTED = "committed"
    """Exactly ``intent`` then ``committed``: the repository considers it
    committed.  This is audit evidence, not filesystem-state proof."""


# ── Apply-attempt DTO ─────────────────────────────────────────────────────


class ApplyAttempt(BaseModel):
    """One durable, immutable apply-attempt record.

    The record is bound to the exact ``changeset_id`` and proposal
    ``fingerprint``; it captures the structured ``ChangeSetApplyResult``
    verbatim plus the trusted apply actor and timestamp.
    """

    schema_version: int = Field(default=1, ge=1)
    changeset_id: ChangeSetId
    fingerprint: ChangeSetFingerprint
    outcome: ChangeSetApplyOutcome
    applied_operation_indices: tuple[int, ...]
    remaining_operation_indices: tuple[int, ...]
    failure: ApplyFailure | None = None
    failing_operation_commit_state: ApplyCommitState | None = None
    source: ApplySource
    real_time: AwareDatetime

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class ChangeSetStatus(BaseModel):
    """Derived, read-only workflow status for one ChangeSet.

    ``can_apply`` is ``False`` when the applicability gate refuses another apply;
    ``block_reason`` carries the human-readable gate message.  Contradictory or
    malformed evidence raises instead of producing a status.
    """

    changeset_id: ChangeSetId
    fingerprint: ChangeSetFingerprint
    attempt_count: int = Field(ge=0)
    latest_attempt: ApplyAttempt | None = None
    audit_states: tuple[AuditOperationState, ...]
    audit_evidence_present: bool
    can_apply: bool
    block_reason: str | None = None

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── Serialization ─────────────────────────────────────────────────────────


def serialize_apply_attempt(attempt: ApplyAttempt) -> str:
    """Serialize one attempt to deterministic compact JSON plus one newline."""
    payload = attempt.model_dump(mode="json")
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def deserialize_apply_attempts(text: str) -> tuple[ApplyAttempt, ...]:
    """Parse and validate a complete apply-attempt JSONL artifact.

    A blank line, a partial final line, malformed JSON, a non-object line or an
    invalid record all fail closed.

    Raises:
        StorageError: The persisted history is empty, truncated or malformed.
    """
    if text == "":
        raise StorageError("Apply-attempt artifact is empty")
    if not text.endswith("\n"):
        raise StorageError("Apply-attempt artifact has an unterminated final record")

    attempts: list[ApplyAttempt] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            raise StorageError(f"Apply-attempt artifact has a blank line at {line_no}")
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"Apply-attempt artifact has malformed JSON at line {line_no}",
                cause=exc,
            ) from exc
        if not isinstance(data, dict):
            raise StorageError(f"Apply-attempt artifact line {line_no} is not a JSON object")
        try:
            attempts.append(ApplyAttempt.model_validate(data))
        except Exception as exc:
            raise StorageError(
                f"Apply-attempt artifact line {line_no} is invalid",
                cause=exc,
            ) from exc
    return tuple(attempts)


# ── Load / record ─────────────────────────────────────────────────────────


def load_apply_attempts(store: ChangeSetStore, changeset_id: str) -> tuple[ApplyAttempt, ...]:
    """Load the ordered apply-attempt history, or ``()`` when none exists.

    Raises:
        StorageError: The id is unsafe or the persisted history is malformed.
    """
    text = store.read_apply_attempts_if_present(changeset_id)
    if text is None:
        return ()
    return deserialize_apply_attempts(text)


def _validate_single_attempt(
    attempt: ApplyAttempt,
    *,
    total_operations: int,
    changeset_id: str,
    fingerprint: ChangeSetFingerprint,
) -> None:
    """Validate one attempt's binding and internal index consistency.

    Raises:
        ConflictError: The attempt is bound to a different id/fingerprint or
            its indices/outcome/commit-state are internally impossible.
    """
    if attempt.changeset_id != changeset_id:
        raise ConflictError(
            f"Apply-attempt record id {attempt.changeset_id!r} does not match {changeset_id!r}"
        )
    if attempt.fingerprint != fingerprint:
        raise ConflictError(
            f"Apply-attempt record for {changeset_id!r} is bound to a different proposal fingerprint"
        )

    applied = attempt.applied_operation_indices
    remaining = attempt.remaining_operation_indices

    for index in (*applied, *remaining):
        if index < 0 or index >= total_operations:
            raise ConflictError(
                f"Apply-attempt record for {changeset_id!r} has out-of-range index {index}"
            )

    if len(set(applied)) != len(applied) or len(set(remaining)) != len(remaining):
        raise ConflictError(f"Apply-attempt record for {changeset_id!r} has duplicate indices")

    if set(applied) & set(remaining):
        raise ConflictError(
            f"Apply-attempt record for {changeset_id!r} overlaps applied and remaining indices"
        )

    if attempt.outcome is ChangeSetApplyOutcome.APPLIED:
        if (
            applied != tuple(range(total_operations))
            or remaining != ()
            or attempt.failure is not None
            or attempt.failing_operation_commit_state is not None
        ):
            raise ConflictError(
                f"APPLIED apply-attempt record for {changeset_id!r} is inconsistent"
            )
        return

    failure = attempt.failure
    if failure is None:
        raise ConflictError(f"{attempt.outcome.value} apply-attempt record has no failure")
    if attempt.failing_operation_commit_state not in (
        ApplyCommitState.NOT_WRITTEN,
        ApplyCommitState.UNCONFIRMED,
    ):
        raise ConflictError(
            f"{attempt.outcome.value} apply-attempt record has an invalid commit state"
        )
    if applied != tuple(range(len(applied))):
        raise ConflictError(
            f"{attempt.outcome.value} apply-attempt record has non-prefix applied indices"
        )
    if failure.operation_index != len(applied):
        raise ConflictError(
            f"Apply-attempt failure index does not follow the applied prefix for {changeset_id!r}"
        )
    if remaining != tuple(range(len(applied) + 1, total_operations)):
        raise ConflictError(
            f"{attempt.outcome.value} apply-attempt record has invalid remaining indices"
        )
    if attempt.outcome is ChangeSetApplyOutcome.FAILED and applied:
        raise ConflictError(f"FAILED apply-attempt record for {changeset_id!r} has applied indices")
    if attempt.outcome is ChangeSetApplyOutcome.PARTIAL and not applied:
        raise ConflictError(
            f"PARTIAL apply-attempt record for {changeset_id!r} has no applied indices"
        )


def validate_attempt_history(
    attempts: Sequence[ApplyAttempt],
    *,
    total_operations: int,
    changeset_id: str,
    fingerprint: ChangeSetFingerprint,
) -> None:
    """Validate a complete ordered attempt history.

    Raises:
        ConflictError: Any record is invalid or a terminal (``APPLIED`` /
            ``PARTIAL``) record is followed by another attempt.
    """
    for attempt in attempts:
        _validate_single_attempt(
            attempt,
            total_operations=total_operations,
            changeset_id=changeset_id,
            fingerprint=fingerprint,
        )

    for index, attempt in enumerate(attempts[:-1]):
        if attempt.outcome in (ChangeSetApplyOutcome.APPLIED, ChangeSetApplyOutcome.PARTIAL):
            raise ConflictError(
                f"Apply-attempt history for {changeset_id!r} continues after a "
                f"{attempt.outcome.value} record at position {index}"
            )


def record_apply_attempt(
    store: ChangeSetStore,
    changeset: ChangeSet,
    result: ChangeSetApplyResult,
    *,
    source: str,
    real_time: AwareDatetime,
) -> ApplyAttempt:
    """Append one attempt record after a structured apply result.

    The append is refused when the existing history is malformed/contradictory
    or already terminal.  A successful call returns the persisted attempt.

    Raises:
        ConflictError: The existing history is contradictory or terminal.
        StorageError: Reading existing history or appending the record failed.
    """
    total = len(changeset.operations)
    fingerprint = compute_changeset_fingerprint(changeset)
    existing = load_apply_attempts(store, changeset.changeset_id)
    validate_attempt_history(
        existing,
        total_operations=total,
        changeset_id=changeset.changeset_id,
        fingerprint=fingerprint,
    )
    if existing and existing[-1].outcome in (
        ChangeSetApplyOutcome.APPLIED,
        ChangeSetApplyOutcome.PARTIAL,
    ):
        raise ConflictError(
            f"Apply-attempt history for {changeset.changeset_id!r} is already terminal "
            f"({existing[-1].outcome.value})"
        )

    attempt = ApplyAttempt(
        changeset_id=changeset.changeset_id,
        fingerprint=fingerprint,
        outcome=result.outcome,
        applied_operation_indices=result.applied_operation_indices,
        remaining_operation_indices=result.remaining_operation_indices,
        failure=result.failure,
        failing_operation_commit_state=result.failing_operation_commit_state,
        source=source,
        real_time=real_time,
    )
    _validate_single_attempt(
        attempt,
        total_operations=total,
        changeset_id=changeset.changeset_id,
        fingerprint=fingerprint,
    )
    store.append_apply_attempt(changeset.changeset_id, serialize_apply_attempt(attempt))
    return attempt


# ── Audit correlation ─────────────────────────────────────────────────────


def correlate_audit(
    changeset: ChangeSet,
    audit_records: Sequence[AuditRecord],
) -> tuple[AuditOperationState, ...]:
    """Derive per-index audit state from deterministic operation ids.

    Raises:
        ConflictError: An impossible intent/committed phase sequence exists.
    """
    total = len(changeset.operations)
    prefix = f"{changeset.changeset_id}:"
    by_operation_id: dict[str, list[str]] = {}
    for record in audit_records:
        if record.operation_id.startswith(prefix):
            by_operation_id.setdefault(record.operation_id, []).append(record.phase)

    states: list[AuditOperationState] = []
    for index in range(total):
        operation_id = f"{changeset.changeset_id}:{index}"
        phases = by_operation_id.get(operation_id, [])
        if not phases:
            states.append(AuditOperationState.NOT_ATTEMPTED)
        elif phases == ["intent"]:
            states.append(AuditOperationState.UNCONFIRMED)
        elif phases == ["intent", "committed"]:
            states.append(AuditOperationState.COMMITTED)
        else:
            raise ConflictError(
                f"Impossible audit phase sequence for operation {operation_id!r}: {phases!r}"
            )
    return tuple(states)


# ── Applicability gate ────────────────────────────────────────────────────


def assert_changeset_applicable(
    changeset: ChangeSet,
    attempts: Sequence[ApplyAttempt],
    audit_records: Sequence[AuditRecord],
) -> None:
    """Fail closed unless another apply attempt may safely start.

    Raises:
        ConflictError: The apply history is terminal/unconfirmed or the audit
            evidence makes a retry unsafe.
    """
    total = len(changeset.operations)
    fingerprint = compute_changeset_fingerprint(changeset)
    validate_attempt_history(
        attempts,
        total_operations=total,
        changeset_id=changeset.changeset_id,
        fingerprint=fingerprint,
    )
    states = correlate_audit(changeset, audit_records)

    has_intent_only = AuditOperationState.UNCONFIRMED in states
    has_committed = AuditOperationState.COMMITTED in states

    if attempts:
        latest = attempts[-1]
        if latest.outcome is ChangeSetApplyOutcome.APPLIED:
            raise ConflictError(f"ChangeSet {changeset.changeset_id!r} was already applied")
        if latest.outcome is ChangeSetApplyOutcome.PARTIAL:
            raise ConflictError(
                f"ChangeSet {changeset.changeset_id!r} has an unresolved partial application"
            )
        # latest is FAILED
        if latest.failing_operation_commit_state is ApplyCommitState.UNCONFIRMED:
            raise ConflictError(
                f"ChangeSet {changeset.changeset_id!r} has an unconfirmed prior attempt; "
                f"manual review is required"
            )
        if has_intent_only:
            raise ConflictError(
                f"ChangeSet {changeset.changeset_id!r} has unresolved intent audit evidence"
            )
        if has_committed:
            raise ConflictError(
                f"ChangeSet {changeset.changeset_id!r} has committed audit evidence that "
                f"contradicts its failed attempt record"
            )
        return

    # No workflow record: audit evidence must not silently allow a re-apply.
    if has_intent_only:
        raise ConflictError(
            f"ChangeSet {changeset.changeset_id!r} has unresolved intent audit evidence "
            f"without a workflow record"
        )
    if has_committed:
        raise ConflictError(
            f"ChangeSet {changeset.changeset_id!r} has committed audit evidence without "
            f"a workflow record"
        )


# ── Status ────────────────────────────────────────────────────────────────


def build_changeset_status(
    changeset: ChangeSet,
    attempts: Sequence[ApplyAttempt],
    audit_records: Sequence[AuditRecord],
) -> ChangeSetStatus:
    """Build a structured, read-only status for CLI rendering.

    Raises:
        ConflictError: The history or audit evidence is contradictory.
        StorageError: The history is malformed (raised by the loader).
    """
    total = len(changeset.operations)
    fingerprint = compute_changeset_fingerprint(changeset)
    validate_attempt_history(
        attempts,
        total_operations=total,
        changeset_id=changeset.changeset_id,
        fingerprint=fingerprint,
    )
    states = correlate_audit(changeset, audit_records)

    can_apply = True
    block_reason: str | None = None
    try:
        assert_changeset_applicable(changeset, attempts, audit_records)
    except ConflictError as exc:
        can_apply = False
        block_reason = str(exc)

    return ChangeSetStatus(
        changeset_id=changeset.changeset_id,
        fingerprint=fingerprint,
        attempt_count=len(attempts),
        latest_attempt=attempts[-1] if attempts else None,
        audit_states=states,
        audit_evidence_present=any(
            state is not AuditOperationState.NOT_ATTEMPTED for state in states
        ),
        can_apply=can_apply,
        block_reason=block_reason,
    )


__all__ = [
    "ApplyAttempt",
    "AuditOperationState",
    "ChangeSetStatus",
    "assert_changeset_applicable",
    "build_changeset_status",
    "correlate_audit",
    "deserialize_apply_attempts",
    "load_apply_attempts",
    "record_apply_attempt",
    "serialize_apply_attempt",
    "validate_attempt_history",
]
