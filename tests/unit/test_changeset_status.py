"""Unit tests for S10-06 ChangeSet apply-attempt evidence and status.

Exercises the append-only apply-attempt DTO, deterministic audit correlation,
fail-closed history validation, the pre-apply applicability gate and the
derived status, using deterministic in-memory storage and synthetic
``AuditRecord`` sequences.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.changeset_apply import (
    ApplyCommitState,
    ApplyFailure,
    ApplyFailureCategory,
    ChangeSetApplyOutcome,
    ChangeSetApplyResult,
)
from dnd_assistant.application.changeset_review import compute_changeset_fingerprint
from dnd_assistant.application.changeset_status import (
    ApplyAttempt,
    AuditOperationState,
    assert_changeset_applicable,
    build_changeset_status,
    correlate_audit,
    deserialize_apply_attempts,
    load_apply_attempts,
    record_apply_attempt,
    serialize_apply_attempt,
    validate_attempt_history,
)
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

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_APPLY_TIME = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


# ── In-memory store double ─────────────────────────────────────────────────


class _Backend:
    def __init__(self) -> None:
        self.proposals: dict[str, str] = {}
        self.approvals: dict[str, str] = {}
        self.apply_attempts: dict[str, str] = {}


class FakeStore:
    """Minimal in-memory ``ChangeSetStore`` double with a shareable backend."""

    def __init__(self, backend: _Backend | None = None) -> None:
        self._backend = backend if backend is not None else _Backend()

    def create_proposal(self, changeset_id: str, content: str) -> None:
        if changeset_id in self._backend.proposals:
            raise ConflictError("proposal exists")
        self._backend.proposals[changeset_id] = content

    def read_proposal(self, changeset_id: str) -> str:
        return self._backend.proposals[changeset_id]

    def read_proposal_if_present(self, changeset_id: str) -> str | None:
        return self._backend.proposals.get(changeset_id)

    def create_approval(self, changeset_id: str, content: str) -> None:
        if changeset_id in self._backend.approvals:
            raise ConflictError("approval exists")
        self._backend.approvals[changeset_id] = content

    def read_approval(self, changeset_id: str) -> str:
        return self._backend.approvals[changeset_id]

    def read_approval_if_present(self, changeset_id: str) -> str | None:
        return self._backend.approvals.get(changeset_id)

    def append_apply_attempt(self, changeset_id: str, content: str) -> None:
        existing = self._backend.apply_attempts.get(changeset_id, "")
        self._backend.apply_attempts[changeset_id] = existing + content

    def read_apply_attempts_if_present(self, changeset_id: str) -> str | None:
        return self._backend.apply_attempts.get(changeset_id)


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


def _append(entity_id: str, revision: int = 1, fact: str = "A fact") -> AppendFactOperation:
    return AppendFactOperation(entity_id=entity_id, expected_revision=revision, fact=fact)


def _changeset(*operations: object, changeset_id: str = "cs-1") -> ChangeSet:
    ops = operations or (_create("npc-1"),)
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=ops,  # type: ignore[arg-type]
    )


def _result(
    outcome: ChangeSetApplyOutcome,
    applied: tuple[int, ...],
    remaining: tuple[int, ...],
    *,
    failure: ApplyFailure | None = None,
    commit_state: ApplyCommitState | None = None,
) -> ChangeSetApplyResult:
    return ChangeSetApplyResult(
        changeset_id="cs-1",
        outcome=outcome,
        applied_operation_indices=applied,
        remaining_operation_indices=remaining,
        failure=failure,
        failing_operation_commit_state=commit_state,
    )


def _applied_result(total: int = 1) -> ChangeSetApplyResult:
    return _result(
        ChangeSetApplyOutcome.APPLIED,
        tuple(range(total)),
        (),
    )


def _failed_result(
    *, commit_state: ApplyCommitState, total: int = 2, category: ApplyFailureCategory | None = None
) -> ChangeSetApplyResult:
    resolved_category = category or (
        ApplyFailureCategory.STORAGE
        if commit_state is ApplyCommitState.UNCONFIRMED
        else ApplyFailureCategory.CONFLICT
    )
    return _result(
        ChangeSetApplyOutcome.FAILED,
        (),
        tuple(range(1, total)),
        failure=ApplyFailure(
            operation_index=0,
            category=resolved_category,
            message="boom",
            entity_id="npc-1",
        ),
        commit_state=commit_state,
    )


def _partial_result(total: int = 3) -> ChangeSetApplyResult:
    return _result(
        ChangeSetApplyOutcome.PARTIAL,
        (0,),
        (2,),
        failure=ApplyFailure(
            operation_index=1,
            category=ApplyFailureCategory.STORAGE,
            message="disk",
            entity_id="npc-2",
        ),
        commit_state=ApplyCommitState.UNCONFIRMED,
    )


def _audit(operation_id: str, phase: str) -> AuditRecord:
    return AuditRecord(
        operation_id=operation_id,
        real_time=_T0,
        operation="patch_entity",
        entity_id="npc-1",
        source="test",
        phase=phase,  # type: ignore[arg-type]
    )


def _record(
    changeset: ChangeSet,
    result: ChangeSetApplyResult,
    store: FakeStore,
) -> ApplyAttempt:
    return record_apply_attempt(
        store,
        changeset,
        result,
        source="test",
        real_time=_APPLY_TIME,
    )


# ── Round-trips ────────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_applied_round_trip(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        _record(changeset, _applied_result(1), store)

        attempts = load_apply_attempts(store, "cs-1")
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.outcome is ChangeSetApplyOutcome.APPLIED
        assert attempt.applied_operation_indices == (0,)
        assert attempt.remaining_operation_indices == ()
        assert attempt.failure is None
        assert attempt.failing_operation_commit_state is None
        assert attempt.fingerprint == compute_changeset_fingerprint(changeset)

    def test_failed_not_written_round_trip(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = FakeStore()
        _record(
            changeset,
            _failed_result(commit_state=ApplyCommitState.NOT_WRITTEN),
            store,
        )

        attempt = load_apply_attempts(store, "cs-1")[0]
        assert attempt.outcome is ChangeSetApplyOutcome.FAILED
        assert attempt.failing_operation_commit_state is ApplyCommitState.NOT_WRITTEN
        assert attempt.remaining_operation_indices == (1,)

    def test_failed_unconfirmed_round_trip(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = FakeStore()
        _record(
            changeset,
            _failed_result(commit_state=ApplyCommitState.UNCONFIRMED),
            store,
        )

        attempt = load_apply_attempts(store, "cs-1")[0]
        assert attempt.failing_operation_commit_state is ApplyCommitState.UNCONFIRMED

    def test_partial_round_trip(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"), _create("npc-3"))
        store = FakeStore()
        _record(changeset, _partial_result(3), store)

        attempt = load_apply_attempts(store, "cs-1")[0]
        assert attempt.outcome is ChangeSetApplyOutcome.PARTIAL
        assert attempt.applied_operation_indices == (0,)
        assert attempt.remaining_operation_indices == (2,)
        assert attempt.failure is not None
        assert attempt.failure.operation_index == 1

    def test_restart_new_store_instance_preserves_status_truth(self) -> None:
        backend = _Backend()
        changeset = _changeset(_create("npc-1"))
        _record(changeset, _applied_result(1), FakeStore(backend))

        # A brand-new store instance over the same durable backend.
        attempts = load_apply_attempts(FakeStore(backend), "cs-1")
        assert len(attempts) == 1
        assert attempts[0].outcome is ChangeSetApplyOutcome.APPLIED


# ── Deserialization / fail-closed ──────────────────────────────────────────


class TestDeserializeFailClosed:
    def test_blank_line_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts('{"a":1}\n\n')

    def test_malformed_json_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts('{"a":\n')

    def test_partial_final_line_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts('{"schema_version":1,"changeset_id":')

    def test_non_object_line_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts("[1,2,3]\n")

    def test_invalid_record_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts('{"schema_version":1}\n')

    def test_empty_present_artifact_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts("")

    def test_unterminated_final_record_fails(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        attempt = _record(changeset, _applied_result(1), store)
        unterminated = serialize_apply_attempt(attempt).rstrip("\n")

        with pytest.raises(StorageError):
            deserialize_apply_attempts(unterminated)

    def test_whitespace_only_artifact_fails(self) -> None:
        with pytest.raises(StorageError):
            deserialize_apply_attempts("   \n")


# ── Audit correlation ──────────────────────────────────────────────────────


class TestAuditCorrelation:
    def test_no_records_is_not_attempted(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        assert correlate_audit(changeset, []) == (
            AuditOperationState.NOT_ATTEMPTED,
            AuditOperationState.NOT_ATTEMPTED,
        )

    def test_intent_only_is_unconfirmed(self) -> None:
        changeset = _changeset(_create("npc-1"))
        states = correlate_audit(changeset, [_audit("cs-1:0", "intent")])
        assert states == (AuditOperationState.UNCONFIRMED,)

    def test_intent_then_committed_is_committed(self) -> None:
        changeset = _changeset(_create("npc-1"))
        states = correlate_audit(
            changeset,
            [_audit("cs-1:0", "intent"), _audit("cs-1:0", "committed")],
        )
        assert states == (AuditOperationState.COMMITTED,)

    def test_committed_without_intent_is_contradictory(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            correlate_audit(changeset, [_audit("cs-1:0", "committed")])

    def test_duplicate_intent_is_contradictory(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            correlate_audit(
                changeset,
                [_audit("cs-1:0", "intent"), _audit("cs-1:0", "intent")],
            )

    def test_duplicate_committed_is_contradictory(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            correlate_audit(
                changeset,
                [
                    _audit("cs-1:0", "intent"),
                    _audit("cs-1:0", "committed"),
                    _audit("cs-1:0", "committed"),
                ],
            )

    def test_order_violation_is_contradictory(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            correlate_audit(
                changeset,
                [_audit("cs-1:0", "committed"), _audit("cs-1:0", "intent")],
            )

    def test_unrelated_records_ignored(self) -> None:
        changeset = _changeset(_create("npc-1"))
        states = correlate_audit(
            changeset, [_audit("other:0", "intent"), _audit("cs-2:0", "intent")]
        )
        assert states == (AuditOperationState.NOT_ATTEMPTED,)


# ── Attempt history validation ─────────────────────────────────────────────


def _attempt(
    outcome: ChangeSetApplyOutcome,
    applied: tuple[int, ...],
    remaining: tuple[int, ...],
    *,
    failure_index: int | None = None,
    commit_state: ApplyCommitState | None = None,
    changeset_id: str = "cs-1",
    fingerprint: object | None = None,
) -> ApplyAttempt:
    failure = None
    if failure_index is not None:
        failure = ApplyFailure(
            operation_index=failure_index,
            category=ApplyFailureCategory.CONFLICT,
            message="x",
            entity_id="npc-1",
        )
    return ApplyAttempt(
        changeset_id=changeset_id,
        fingerprint=fingerprint
        or compute_changeset_fingerprint(_changeset(_create("npc-1"), _create("npc-2"))),  # type: ignore[arg-type]
        outcome=outcome,
        applied_operation_indices=applied,
        remaining_operation_indices=remaining,
        failure=failure,
        failing_operation_commit_state=commit_state,
        source="test",
        real_time=_APPLY_TIME,
    )


class TestAttemptHistoryValidation:
    def _fingerprint(self) -> object:
        return compute_changeset_fingerprint(_changeset(_create("npc-1"), _create("npc-2")))

    def test_fingerprint_mismatch_fails(self) -> None:
        other = compute_changeset_fingerprint(_changeset(_create("npc-9")))
        attempt = _attempt(
            ChangeSetApplyOutcome.APPLIED,
            (0, 1),
            (),
            fingerprint=other,
        )
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [attempt],
                total_operations=2,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_changeset_id_mismatch_fails(self) -> None:
        attempt = _attempt(ChangeSetApplyOutcome.APPLIED, (0, 1), (), changeset_id="cs-other")
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [attempt],
                total_operations=2,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_non_prefix_applied_fails(self) -> None:
        attempt = _attempt(ChangeSetApplyOutcome.APPLIED, (0, 2), ())
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [attempt],
                total_operations=3,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_invalid_remaining_fails(self) -> None:
        attempt = _attempt(
            ChangeSetApplyOutcome.PARTIAL,
            (0,),
            (3,),
            failure_index=1,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [attempt],
                total_operations=3,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_overlap_fails(self) -> None:
        attempt = _attempt(
            ChangeSetApplyOutcome.PARTIAL,
            (0,),
            (0,),
            failure_index=1,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [attempt],
                total_operations=2,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_out_of_range_fails(self) -> None:
        attempt = _attempt(ChangeSetApplyOutcome.APPLIED, (0, 1, 5), ())
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [attempt],
                total_operations=2,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_applied_followed_by_record_fails(self) -> None:
        applied = _attempt(ChangeSetApplyOutcome.APPLIED, (0, 1), ())
        later = _attempt(
            ChangeSetApplyOutcome.FAILED,
            (),
            (1,),
            failure_index=0,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [applied, later],
                total_operations=2,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_partial_followed_by_record_fails(self) -> None:
        partial = _attempt(
            ChangeSetApplyOutcome.PARTIAL,
            (0,),
            (2,),
            failure_index=1,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        later = _attempt(
            ChangeSetApplyOutcome.FAILED,
            (),
            (2,),
            failure_index=0,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        with pytest.raises(ConflictError):
            validate_attempt_history(
                [partial, later],
                total_operations=3,
                changeset_id="cs-1",
                fingerprint=self._fingerprint(),  # type: ignore[arg-type]
            )

    def test_failed_then_failed_is_allowed(self) -> None:
        first = _attempt(
            ChangeSetApplyOutcome.FAILED,
            (),
            (1,),
            failure_index=0,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        second = _attempt(
            ChangeSetApplyOutcome.FAILED,
            (),
            (1,),
            failure_index=0,
            commit_state=ApplyCommitState.NOT_WRITTEN,
        )
        validate_attempt_history(
            [first, second],
            total_operations=2,
            changeset_id="cs-1",
            fingerprint=self._fingerprint(),  # type: ignore[arg-type]
        )


# ── Applicability gate ─────────────────────────────────────────────────────


class TestApplicabilityGate:
    def test_no_history_no_audit_allowed(self) -> None:
        changeset = _changeset(_create("npc-1"))
        assert_changeset_applicable(changeset, (), [])

    def test_applied_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        _record(changeset, _applied_result(1), store)
        with pytest.raises(ConflictError):
            assert_changeset_applicable(changeset, load_apply_attempts(store, "cs-1"), [])

    def test_partial_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"), _create("npc-3"))
        store = FakeStore()
        _record(changeset, _partial_result(3), store)
        with pytest.raises(ConflictError):
            assert_changeset_applicable(changeset, load_apply_attempts(store, "cs-1"), [])

    def test_failed_not_written_clean_state_allowed(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = FakeStore()
        _record(changeset, _failed_result(commit_state=ApplyCommitState.NOT_WRITTEN), store)
        assert_changeset_applicable(changeset, load_apply_attempts(store, "cs-1"), [])

    def test_failed_unconfirmed_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = FakeStore()
        _record(changeset, _failed_result(commit_state=ApplyCommitState.UNCONFIRMED), store)
        with pytest.raises(ConflictError):
            assert_changeset_applicable(changeset, load_apply_attempts(store, "cs-1"), [])

    def test_intent_only_without_artifact_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            assert_changeset_applicable(changeset, (), [_audit("cs-1:0", "intent")])

    def test_committed_without_artifact_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            assert_changeset_applicable(
                changeset,
                (),
                [_audit("cs-1:0", "intent"), _audit("cs-1:0", "committed")],
            )

    def test_failed_not_written_with_intent_evidence_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = FakeStore()
        _record(changeset, _failed_result(commit_state=ApplyCommitState.NOT_WRITTEN), store)
        with pytest.raises(ConflictError):
            assert_changeset_applicable(
                changeset,
                load_apply_attempts(store, "cs-1"),
                [_audit("cs-1:0", "intent")],
            )

    def test_failed_not_written_with_committed_evidence_blocks(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"))
        store = FakeStore()
        _record(changeset, _failed_result(commit_state=ApplyCommitState.NOT_WRITTEN), store)
        with pytest.raises(ConflictError):
            assert_changeset_applicable(
                changeset,
                load_apply_attempts(store, "cs-1"),
                [_audit("cs-1:0", "intent"), _audit("cs-1:0", "committed")],
            )


# ── Status ─────────────────────────────────────────────────────────────────


class TestStatus:
    def test_status_allows_clean_state(self) -> None:
        changeset = _changeset(_create("npc-1"))
        status = build_changeset_status(changeset, (), [])
        assert status.can_apply is True
        assert status.block_reason is None
        assert status.attempt_count == 0
        assert status.audit_evidence_present is False

    def test_status_reports_blocked_applied(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        _record(changeset, _applied_result(1), store)
        status = build_changeset_status(changeset, load_apply_attempts(store, "cs-1"), [])
        assert status.can_apply is False
        assert status.block_reason is not None
        assert status.latest_attempt is not None
        assert status.latest_attempt.outcome is ChangeSetApplyOutcome.APPLIED

    def test_status_reports_audit_states(self) -> None:
        changeset = _changeset(_create("npc-1"))
        status = build_changeset_status(changeset, (), [_audit("cs-1:0", "intent")])
        assert status.audit_states == (AuditOperationState.UNCONFIRMED,)
        assert status.audit_evidence_present is True

    def test_status_raises_on_contradictory_audit(self) -> None:
        changeset = _changeset(_create("npc-1"))
        with pytest.raises(ConflictError):
            build_changeset_status(changeset, (), [_audit("cs-1:0", "committed")])


# ── Record terminal refusal / malformed history ────────────────────────────


class TestRecordRefusal:
    def test_record_after_applied_refused(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        _record(changeset, _applied_result(1), store)
        with pytest.raises(ConflictError):
            _record(changeset, _applied_result(1), store)

    def test_record_after_partial_refused(self) -> None:
        changeset = _changeset(_create("npc-1"), _create("npc-2"), _create("npc-3"))
        store = FakeStore()
        _record(changeset, _partial_result(3), store)
        with pytest.raises(ConflictError):
            _record(changeset, _partial_result(3), store)

    def test_record_with_malformed_existing_history_refused(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        store.append_apply_attempt("cs-1", "{not json\n")
        with pytest.raises(StorageError):
            _record(changeset, _applied_result(1), store)


class TestSerializeDeterminism:
    def test_serialize_is_stable(self) -> None:
        changeset = _changeset(_create("npc-1"))
        store = FakeStore()
        first = _record(changeset, _applied_result(1), store)

        first_text = serialize_apply_attempt(first)
        second_text = serialize_apply_attempt(first)

        assert first_text == second_text
        assert first_text.endswith("\n")
        assert "\n" not in first_text.rstrip("\n")
        assert ", " not in first_text
        assert ": " not in first_text
        assert deserialize_apply_attempts(first_text) == (first,)
