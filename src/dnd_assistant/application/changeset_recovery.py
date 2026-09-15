"""R1 ChangeSet intent ownership classification for global recovery preflight.

Stage 10 accepted the limitation (R1) that an intent-only ChangeSet repository
audit record carrying a real ``session_ref`` can participate in the global
session-recovery ``unresolved_audit_intent`` detector and wedge unrelated
mutations.  This module owns the **narrowing of blocking scope**, never the
narrowing of detection/reporting scope:

- the storage layer still detects and reports every raw recovery issue;
- this application layer decides which ``unresolved_audit_intent`` issues are
  conclusively owned by the ChangeSet workflow and therefore delegated to the
  ChangeSet status/applicability gate instead of blocking unrelated mutations;
- every ambiguity is fail-closed: only an exact, fully-bound match is
  delegated, everything else remains globally blocking.

Ownership is proven from durable evidence only:

    operation_id == "<changeset_id>:<index>"   (one shared format helper)
    -> persisted proposal for that changeset id exists and is valid
    -> index is in range and proposal.session_ref matches the issue session
    -> exactly one ``intent`` audit record and no ``committed`` record
    -> audit ``operation``/``entity_id`` match the proposal operation

No filesystem state is inspected and no repository mutation is performed.  The
affected ChangeSet remains permanently blocked by the existing
``application.changeset_status`` applicability gate; no repair, replay, resume
or rollback is introduced.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, shutil,
    tempfile, subprocess, or a concrete storage implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.changeset_store import deserialize_proposal
from dnd_assistant.application.session_recovery import (
    IntentOwnershipGate,
    RecoveryPartition,
)
from dnd_assistant.errors import DndAssistantError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditRecord
    from dnd_assistant.storage.changeset_store import ChangeSetStore
    from dnd_assistant.storage.session_recovery import RecoveryIssue, SessionRecoveryReport

# ── Canonical operation-id format ──────────────────────────────────────────

CHANGESET_OPERATION_ID_SEPARATOR = ":"
"""Separator between a ChangeSet id and its operation index.

The ChangeSet id is an opaque validated string and may itself contain ``:``;
the parser always splits on the **final** separator, so the index is the
trailing component.  This is the single source of truth for the apply-time
operation-id format.
"""


def format_changeset_operation_id(changeset_id: str, index: int) -> str:
    """Return the canonical deterministic repository operation id."""
    return f"{changeset_id}{CHANGESET_OPERATION_ID_SEPARATOR}{index}"


@dataclass(frozen=True)
class ParsedChangeSetOperationId:
    """A parsed ``<changeset_id>:<index>`` repository operation id."""

    changeset_id: str
    index: int


def parse_changeset_operation_id(operation_id: str) -> ParsedChangeSetOperationId | None:
    """Parse a repository operation id into ``(changeset_id, index)``.

    The final separator is split so that ChangeSet ids containing ``:`` are
    preserved.  The suffix must be the canonical decimal form of a
    non-negative integer (no sign, no leading zeros, ASCII digits only).

    Returns:
        The parsed pair, or ``None`` when the string is not a canonical
        ChangeSet operation id.  ``None`` is a fail-closed outcome: the caller
        must not treat the operation as ChangeSet-owned.
    """
    if not isinstance(operation_id, str) or not operation_id:
        return None

    changeset_id, separator, suffix = operation_id.rpartition(CHANGESET_OPERATION_ID_SEPARATOR)
    if not separator or not changeset_id:
        return None
    if not (suffix.isascii() and suffix.isdigit()):
        return None

    index = int(suffix)
    if str(index) != suffix:
        return None
    return ParsedChangeSetOperationId(changeset_id=changeset_id, index=index)


# ── Ownership verdict ──────────────────────────────────────────────────────

_AUDIT_OPERATION_BY_KIND: dict[str, str] = {
    "create_entity": "create_entity",
    "update_entity": "patch_entity",
    "append_fact": "append_entity_fact",
}
"""ChangeSet operation kind -> repository audit ``operation`` name."""


class ChangeSetIntentVerdict(StrEnum):
    """Ownership verdict for one recovery issue."""

    OWNED = "owned"
    """Conclusively owned by the ChangeSet workflow; safe to delegate."""

    NOT_OWNED = "not_owned"
    """Not a ChangeSet intent; session recovery keeps global ownership."""

    UNKNOWN = "unknown"
    """Ambiguous/contradictory evidence; fail-closed (stays blocking)."""


def classify_changeset_intent(
    issue: RecoveryIssue,
    audit_records: Sequence[AuditRecord],
    store: ChangeSetStore,
) -> ChangeSetIntentVerdict:
    """Classify one recovery issue as ChangeSet-owned or not.

    Only an exact, fully-bound match returns :attr:`ChangeSetIntentVerdict.OWNED`.
    Every absent artifact, malformed artifact, index/session/operation mismatch
    or contradictory phase sequence returns ``UNKNOWN`` or ``NOT_OWNED`` and
    therefore remains globally blocking.  This method is read-only and never
    raises for expected malformed/absent evidence.
    """
    if issue.code != "unresolved_audit_intent":
        return ChangeSetIntentVerdict.NOT_OWNED

    operation_id = issue.operation_id
    if not operation_id:
        return ChangeSetIntentVerdict.NOT_OWNED

    parsed = parse_changeset_operation_id(operation_id)
    if parsed is None:
        return ChangeSetIntentVerdict.NOT_OWNED

    try:
        proposal_text = store.read_proposal_if_present(parsed.changeset_id)
    except StorageError:
        return ChangeSetIntentVerdict.UNKNOWN
    if proposal_text is None:
        return ChangeSetIntentVerdict.NOT_OWNED

    try:
        changeset = deserialize_proposal(proposal_text)
    except StorageError:
        return ChangeSetIntentVerdict.UNKNOWN
    if changeset.changeset_id != parsed.changeset_id:
        return ChangeSetIntentVerdict.UNKNOWN
    if parsed.index < 0 or parsed.index >= len(changeset.operations):
        return ChangeSetIntentVerdict.UNKNOWN

    session_id = issue.session_id
    if session_id is None or changeset.session_ref != session_id:
        return ChangeSetIntentVerdict.UNKNOWN

    matching = [record for record in audit_records if record.operation_id == operation_id]
    intents = [record for record in matching if record.phase == "intent"]
    if len(intents) != 1 or any(record.phase == "committed" for record in matching):
        return ChangeSetIntentVerdict.UNKNOWN

    record = intents[0]
    if record.session != session_id:
        return ChangeSetIntentVerdict.UNKNOWN

    operation = changeset.operations[parsed.index]
    expected_operation = _AUDIT_OPERATION_BY_KIND.get(operation.kind)
    if expected_operation is None or record.operation != expected_operation:
        return ChangeSetIntentVerdict.UNKNOWN
    if record.entity_id != operation.entity_id:
        return ChangeSetIntentVerdict.UNKNOWN

    return ChangeSetIntentVerdict.OWNED


# ── Preflight gate ─────────────────────────────────────────────────────────


class ChangeSetIntentOwnershipGate(IntentOwnershipGate):
    """Partition a raw recovery report into blocking and delegated issues.

    The gate implements the application-layer :class:`IntentOwnershipGate`
    protocol consumed by mutation preflight.  It reads the audit log once per
    partition and classifies every ``unresolved_audit_intent`` issue; a single
    unreadable audit log makes the whole report blocking (fail-closed).

    Args:
        store: Persisted ChangeSet proposal store.
        read_audit_records: Typed audit-record reader; never parsed here.
    """

    def __init__(
        self,
        store: ChangeSetStore,
        *,
        read_audit_records: Callable[[], Sequence[AuditRecord]],
    ) -> None:
        self._store = store
        self._read_audit_records = read_audit_records

    def partition(self, report: SessionRecoveryReport) -> RecoveryPartition:
        """Return ``(blocking, externally_owned)`` for the raw report."""
        records = self._read_records_or_none()

        blocking: list[RecoveryIssue] = []
        delegated: list[RecoveryIssue] = []

        for issue in report.issues:
            verdict = (
                ChangeSetIntentVerdict.UNKNOWN
                if records is None
                else classify_changeset_intent(issue, records, self._store)
            )
            if verdict is ChangeSetIntentVerdict.OWNED:
                delegated.append(issue)
            else:
                blocking.append(issue)

        return RecoveryPartition(
            blocking=tuple(blocking),
            externally_owned=tuple(delegated),
        )

    def _read_records_or_none(self) -> Sequence[AuditRecord] | None:
        """Read audit records, or ``None`` (fail-closed) on a read failure."""
        try:
            return self._read_audit_records()
        except DndAssistantError:
            return None


__all__ = [
    "CHANGESET_OPERATION_ID_SEPARATOR",
    "ChangeSetIntentOwnershipGate",
    "ChangeSetIntentVerdict",
    "ParsedChangeSetOperationId",
    "classify_changeset_intent",
    "format_changeset_operation_id",
    "parse_changeset_operation_id",
]
