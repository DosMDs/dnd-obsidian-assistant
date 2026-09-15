"""R1 unit tests: ChangeSet intent ownership parsing, classification and gate.

Covers the canonical operation-id format, the fail-closed ownership classifier
that verifies the persisted proposal and the audit evidence, and the preflight
partition that narrows blocking scope without narrowing detection.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.changeset_recovery import (
    CHANGESET_OPERATION_ID_SEPARATOR,
    ChangeSetIntentOwnershipGate,
    ChangeSetIntentVerdict,
    ParsedChangeSetOperationId,
    classify_changeset_intent,
    format_changeset_operation_id,
    parse_changeset_operation_id,
)
from dnd_assistant.application.changeset_store import serialize_proposal
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
    ProposalProvenance,
)
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditRecord
from dnd_assistant.storage.session_recovery import RecoveryIssue, SessionRecoveryReport

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


# ── Store double ───────────────────────────────────────────────────────────


class FakeStore:
    """Minimal in-memory ``ChangeSetStore`` double."""

    def __init__(self) -> None:
        self.proposals: dict[str, str] = {}
        self.raise_on_read = False

    def read_proposal_if_present(self, changeset_id: str) -> str | None:
        if self.raise_on_read:
            raise StorageError("unreadable")
        return self.proposals.get(changeset_id)

    def read_proposal(self, changeset_id: str) -> str:
        text = self.read_proposal_if_present(changeset_id)
        if text is None:
            raise StorageError("absent")
        return text

    def create_proposal(self, changeset_id: str, content: str) -> None:
        if changeset_id in self.proposals:
            raise ConflictError("exists")
        self.proposals[changeset_id] = content

    def create_approval(self, changeset_id: str, content: str) -> None:
        raise NotImplementedError

    def read_approval(self, changeset_id: str) -> str:
        raise NotImplementedError

    def read_approval_if_present(self, changeset_id: str) -> str | None:
        return None

    def append_apply_attempt(self, changeset_id: str, content: str) -> None:
        raise NotImplementedError

    def read_apply_attempts_if_present(self, changeset_id: str) -> str | None:
        return None


# ── Builders ───────────────────────────────────────────────────────────────


def _create(entity_id: str) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=EntityType.NPC,
        name=f"Entity {entity_id}",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
    )


def _append(entity_id: str, revision: int = 1) -> AppendFactOperation:
    return AppendFactOperation(entity_id=entity_id, expected_revision=revision, fact="A fact")


def _changeset(
    *operations: object,
    changeset_id: str = "cs-1",
    session_ref: str | None = "S006",
) -> ChangeSet:
    ops = operations or (_create("npc-1"),)
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        session_ref=session_ref,
        operations=ops,  # type: ignore[arg-type]
    )


def _record(
    operation_id: str,
    *,
    phase: str = "intent",
    operation: str = "create_entity",
    entity_id: str | None = "npc-1",
    session: str | None = "S006",
    real_time: datetime = _T0,
) -> AuditRecord:
    return AuditRecord(
        operation_id=operation_id,
        real_time=real_time,
        session=session,
        operation=operation,
        entity_id=entity_id,
        source="test",
        phase=phase,  # type: ignore[arg-type]
    )


def _intent_issue(operation_id: str, session_id: str = "S006") -> RecoveryIssue:
    return RecoveryIssue(
        code="unresolved_audit_intent",
        session_id=session_id,
        operation_id=operation_id,
        detail="intent",
    )


# ── Operation-id format ────────────────────────────────────────────────────


class TestOperationIdFormat:
    def test_separator_is_colon(self) -> None:
        assert CHANGESET_OPERATION_ID_SEPARATOR == ":"

    def test_format_matches_apply_scheme(self) -> None:
        assert format_changeset_operation_id("cs-1", 0) == "cs-1:0"
        assert format_changeset_operation_id("cs-1", 12) == "cs-1:12"

    @pytest.mark.parametrize(
        ("operation_id", "expected"),
        [
            ("cs-1:0", ParsedChangeSetOperationId("cs-1", 0)),
            ("a:b:3", ParsedChangeSetOperationId("a:b", 3)),
            ("cs:0:7", ParsedChangeSetOperationId("cs:0", 7)),
        ],
    )
    def test_round_trip_with_colons_in_id(
        self, operation_id: str, expected: ParsedChangeSetOperationId
    ) -> None:
        assert parse_changeset_operation_id(operation_id) == expected
        assert format_changeset_operation_id(expected.changeset_id, expected.index) == operation_id

    @pytest.mark.parametrize(
        "operation_id",
        [
            "",
            "no-colon",
            ":0",
            "cs-1:",
            "cs-1:+1",
            "cs-1:-1",
            "cs-1:01",
            "cs-1: 1",
            "cs-1:1 ",
            "cs-1:1.0",
            "cs-1:\u00b2",
        ],
    )
    def test_non_canonical_returns_none(self, operation_id: str) -> None:
        assert parse_changeset_operation_id(operation_id) is None


# ── Classification ─────────────────────────────────────────────────────────


class TestClassifyChangeSetIntent:
    def _store_with(self, changeset: ChangeSet) -> FakeStore:
        store = FakeStore()
        store.proposals[changeset.changeset_id] = serialize_proposal(changeset)
        return store

    def test_owned_when_fully_bound(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.OWNED

    def test_owned_at_nonzero_index(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:1"),
            [_record("cs-1:1", entity_id="npc-2")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.OWNED

    def test_absent_proposal_is_not_owned(self) -> None:
        verdict = classify_changeset_intent(
            _intent_issue("cs-missing:0"),
            [_record("cs-missing:0")],
            FakeStore(),
        )
        assert verdict is ChangeSetIntentVerdict.NOT_OWNED

    def test_malformed_proposal_is_unknown(self) -> None:
        store = FakeStore()
        store.proposals["cs-1"] = "{not json"
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_unreadable_store_is_unknown(self) -> None:
        store = FakeStore()
        store.raise_on_read = True
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_index_out_of_range_is_unknown(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:5"),
            [_record("cs-1:5")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_session_ref_mismatch_is_unknown(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0", session_id="S999"),
            [_record("cs-1:0", session="S999")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_entity_mismatch_is_unknown(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0", entity_id="npc-other")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_operation_name_mismatch_is_unknown(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0", operation="session.note")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_committed_present_is_unknown(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0"), _record("cs-1:0", phase="committed")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_multiple_intents_is_unknown(self) -> None:
        changeset = _changeset()
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0"), _record("cs-1:0")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.UNKNOWN

    def test_update_operation_maps_to_patch_entity(self) -> None:
        changeset = _changeset(_append("npc-1"))
        store = self._store_with(changeset)
        verdict = classify_changeset_intent(
            _intent_issue("cs-1:0"),
            [_record("cs-1:0", operation="append_entity_fact")],
            store,
        )
        assert verdict is ChangeSetIntentVerdict.OWNED

    def test_non_unresolved_issue_is_not_owned(self) -> None:
        issue = RecoveryIssue(code="audit_corrupt")
        verdict = classify_changeset_intent(issue, [], FakeStore())
        assert verdict is ChangeSetIntentVerdict.NOT_OWNED


# ── Gate partition ─────────────────────────────────────────────────────────


def _gate(store: FakeStore, records: list[AuditRecord] | None) -> ChangeSetIntentOwnershipGate:
    def _read() -> list[AuditRecord]:
        if records is None:
            raise StorageError("audit unreadable")
        return records

    return ChangeSetIntentOwnershipGate(store, read_audit_records=_read)


class TestOwnershipGatePartition:
    def test_owned_intent_is_delegated(self) -> None:
        changeset = _changeset()
        store = FakeStore()
        store.proposals["cs-1"] = serialize_proposal(changeset)
        gate = _gate(store, [_record("cs-1:0")])

        report = SessionRecoveryReport([_intent_issue("cs-1:0")])
        partition = gate.partition(report)

        assert partition.blocking == ()
        assert partition.externally_owned == (_intent_issue("cs-1:0"),)

    def test_genuine_intent_stays_blocking(self) -> None:
        gate = _gate(FakeStore(), [_record("cli-note-op")])
        issue = _intent_issue("cli-note-op")
        partition = gate.partition(SessionRecoveryReport([issue]))
        assert partition.blocking == (issue,)
        assert partition.externally_owned == ()

    def test_other_issue_codes_always_block(self) -> None:
        changeset = _changeset()
        store = FakeStore()
        store.proposals["cs-1"] = serialize_proposal(changeset)
        gate = _gate(store, [_record("cs-1:0")])
        corrupt = RecoveryIssue(code="audit_corrupt")
        owned = _intent_issue("cs-1:0")

        partition = gate.partition(SessionRecoveryReport([corrupt, owned]))

        assert partition.blocking == (corrupt,)
        assert partition.externally_owned == (owned,)

    def test_unreadable_audit_keeps_everything_blocking(self) -> None:
        changeset = _changeset()
        store = FakeStore()
        store.proposals["cs-1"] = serialize_proposal(changeset)
        gate = _gate(store, None)
        issue = _intent_issue("cs-1:0")
        partition = gate.partition(SessionRecoveryReport([issue]))
        assert partition.blocking == (issue,)
        assert partition.externally_owned == ()

    def test_mixed_state_keeps_genuine_blocking(self) -> None:
        changeset = _changeset()
        store = FakeStore()
        store.proposals["cs-1"] = serialize_proposal(changeset)
        owned = _intent_issue("cs-1:0")
        genuine = _intent_issue("cli-session-end-abc")
        gate = _gate(store, [_record("cs-1:0")])

        partition = gate.partition(SessionRecoveryReport([owned, genuine]))

        assert partition.blocking == (genuine,)
        assert partition.externally_owned == (owned,)
