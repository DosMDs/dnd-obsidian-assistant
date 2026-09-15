"""Unit tests for the S10-05 application ChangeSet persistence services.

Uses an in-memory ``ChangeSetStore`` double so proposal/approval workflow
policy is tested without a filesystem.  Real filesystem behavior is covered by
``tests/unit/test_changeset_store.py`` and the integration tests.
"""

from __future__ import annotations

import pytest

from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import (
    ApprovalPersistOutcome,
    ProposalPersistOutcome,
    deserialize_approval,
    load_approval,
    load_proposal,
    parse_changeset_document,
    persist_approval,
    persist_proposal,
    serialize_approval,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    EntityFieldUpdate,
    ProposalProvenance,
    UpdateEntityOperation,
)
from dnd_assistant.domain.types import Provenance
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError

# ── In-memory store double ─────────────────────────────────────────────────


class FakeChangeSetStore:
    """Minimal in-memory ``ChangeSetStore`` double with exclusive creates."""

    def __init__(self) -> None:
        self.proposals: dict[str, str] = {}
        self.approvals: dict[str, str] = {}

    def create_proposal(self, changeset_id: str, content: str) -> None:
        if changeset_id in self.proposals:
            raise ConflictError("proposal exists")
        self.proposals[changeset_id] = content

    def read_proposal(self, changeset_id: str) -> str:
        if changeset_id not in self.proposals:
            raise NotFoundError("proposal missing")
        return self.proposals[changeset_id]

    def read_proposal_if_present(self, changeset_id: str) -> str | None:
        return self.proposals.get(changeset_id)

    def create_approval(self, changeset_id: str, content: str) -> None:
        if changeset_id in self.approvals:
            raise ConflictError("approval exists")
        self.approvals[changeset_id] = content

    def read_approval(self, changeset_id: str) -> str:
        if changeset_id not in self.approvals:
            raise NotFoundError("approval missing")
        return self.approvals[changeset_id]

    def read_approval_if_present(self, changeset_id: str) -> str | None:
        return self.approvals.get(changeset_id)


# ── Builders ───────────────────────────────────────────────────────────────


def _changeset(changeset_id: str = "cs-1", *, fact: str = "Found a key") -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=(AppendFactOperation(entity_id="npc-1", expected_revision=1, fact=fact),),
    )


def _update_changeset(changeset_id: str, update: EntityFieldUpdate) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=(UpdateEntityOperation(entity_id="npc-1", expected_revision=1, update=update),),
    )


def _approval(
    changeset: ChangeSet,
    *,
    decision: ReviewDecision = ReviewDecision.APPROVED,
    reviewer: str = "dm",
    reason: str | None = None,
) -> ChangeSetApproval:
    return ChangeSetApproval(
        changeset_id=changeset.changeset_id,
        fingerprint=compute_changeset_fingerprint(changeset),
        decision=decision,
        reviewer=reviewer,
        reason=reason,
    )


# ── Proposal persistence ───────────────────────────────────────────────────


class TestProposalPersistence:
    def test_created(self) -> None:
        store = FakeChangeSetStore()
        assert persist_proposal(store, _changeset()) is ProposalPersistOutcome.CREATED
        assert "cs-1" in store.proposals

    def test_identical_is_already_present(self) -> None:
        store = FakeChangeSetStore()
        persist_proposal(store, _changeset())
        before = store.proposals["cs-1"]

        assert persist_proposal(store, _changeset()) is ProposalPersistOutcome.ALREADY_PRESENT
        assert store.proposals["cs-1"] == before

    def test_same_id_different_fingerprint_conflicts(self) -> None:
        store = FakeChangeSetStore()
        persist_proposal(store, _changeset(fact="First"))
        before = store.proposals["cs-1"]

        with pytest.raises(ConflictError):
            persist_proposal(store, _changeset(fact="Second"))

        assert store.proposals["cs-1"] == before

    def test_malformed_persisted_proposal_is_storage_error(self) -> None:
        store = FakeChangeSetStore()
        store.proposals["cs-1"] = "{not json"

        with pytest.raises(StorageError):
            persist_proposal(store, _changeset())

    def test_round_trip_preserves_fingerprint(self) -> None:
        store = FakeChangeSetStore()
        original = _changeset()
        persist_proposal(store, original)

        loaded = load_proposal(store, "cs-1")

        assert loaded == original
        assert compute_changeset_fingerprint(loaded) == compute_changeset_fingerprint(original)

    def test_explicit_none_vs_omitted_survives_round_trip(self) -> None:
        store = FakeChangeSetStore()
        omitted = _update_changeset("cs-omit", EntityFieldUpdate(status="dead"))
        explicit = _update_changeset(
            "cs-none", EntityFieldUpdate(status="dead", last_seen_session=None)
        )

        persist_proposal(store, omitted)
        persist_proposal(store, explicit)
        loaded_omitted = load_proposal(store, "cs-omit")
        loaded_explicit = load_proposal(store, "cs-none")
        op_omitted = loaded_omitted.operations[0]
        op_explicit = loaded_explicit.operations[0]
        assert isinstance(op_omitted, UpdateEntityOperation)
        assert isinstance(op_explicit, UpdateEntityOperation)

        assert "last_seen_session" not in op_omitted.update.model_fields_set
        assert "last_seen_session" in op_explicit.update.model_fields_set
        assert op_explicit.update.last_seen_session is None

        assert compute_changeset_fingerprint(loaded_omitted) == compute_changeset_fingerprint(
            omitted
        )
        assert compute_changeset_fingerprint(loaded_explicit) == compute_changeset_fingerprint(
            explicit
        )
        assert compute_changeset_fingerprint(loaded_omitted) != compute_changeset_fingerprint(
            loaded_explicit
        )

    def test_load_missing_proposal_raises(self) -> None:
        store = FakeChangeSetStore()
        with pytest.raises(NotFoundError):
            load_proposal(store, "cs-missing")


# ── Approval serialization / loading ───────────────────────────────────────


class TestApprovalSerialization:
    def test_round_trip_equality(self) -> None:
        approval = _approval(_changeset(), reason="looks good")
        assert deserialize_approval(serialize_approval(approval)) == approval

    def test_malformed_approval_is_storage_error(self) -> None:
        with pytest.raises(StorageError):
            deserialize_approval("{not json")

    def test_load_missing_approval_raises(self) -> None:
        store = FakeChangeSetStore()
        with pytest.raises(NotFoundError):
            load_approval(store, "cs-missing")


# ── Approval binding + policy ──────────────────────────────────────────────


class TestApprovalPersistence:
    def test_approved_bound_is_created_and_loadable(self) -> None:
        store = FakeChangeSetStore()
        changeset = _changeset()
        persist_proposal(store, changeset)

        outcome = persist_approval(store, _approval(changeset, decision=ReviewDecision.APPROVED))

        assert outcome is ApprovalPersistOutcome.CREATED
        loaded = load_approval(store, changeset.changeset_id)
        assert loaded.is_approved
        assert loaded.matches_approved_changeset(changeset)

    def test_rejected_bound_is_created_and_not_approved(self) -> None:
        store = FakeChangeSetStore()
        changeset = _changeset()
        persist_proposal(store, changeset)

        outcome = persist_approval(store, _approval(changeset, decision=ReviewDecision.REJECTED))

        assert outcome is ApprovalPersistOutcome.CREATED
        loaded = load_approval(store, changeset.changeset_id)
        assert not loaded.is_approved
        assert not loaded.matches_approved_changeset(changeset)

    def test_identical_approval_is_already_present(self) -> None:
        store = FakeChangeSetStore()
        changeset = _changeset()
        persist_proposal(store, changeset)
        approval = _approval(changeset)
        persist_approval(store, approval)
        before = store.approvals[changeset.changeset_id]

        assert persist_approval(store, approval) is ApprovalPersistOutcome.ALREADY_PRESENT
        assert store.approvals[changeset.changeset_id] == before

    def test_differing_approval_conflicts(self) -> None:
        changeset = _changeset()
        store = FakeChangeSetStore()
        persist_proposal(store, changeset)
        persist_approval(store, _approval(changeset, decision=ReviewDecision.APPROVED))

        with pytest.raises(ConflictError):
            persist_approval(store, _approval(changeset, decision=ReviewDecision.REJECTED))
        with pytest.raises(ConflictError):
            persist_approval(store, _approval(changeset, reviewer="other"))

    def test_missing_proposal_writes_no_approval(self) -> None:
        store = FakeChangeSetStore()
        changeset = _changeset()

        with pytest.raises(NotFoundError):
            persist_approval(store, _approval(changeset))

        assert store.approvals == {}

    def test_wrong_fingerprint_writes_no_approval(self) -> None:
        store = FakeChangeSetStore()
        changeset = _changeset()
        persist_proposal(store, changeset)
        other = _changeset(fact="Different")
        approval = _approval(other)

        with pytest.raises(ValidationError):
            persist_approval(store, approval)

        assert store.approvals == {}

    def test_wrong_changeset_id_binding_writes_no_approval(self) -> None:
        store = FakeChangeSetStore()
        canonical = _changeset("cs-other")
        # Tamper: artifact keyed by cs-key contains a proposal with a different id.
        store.proposals["cs-key"] = serialize_proposal_via(canonical)
        approval = ChangeSetApproval(
            changeset_id="cs-key",
            fingerprint=compute_changeset_fingerprint(canonical),
            decision=ReviewDecision.APPROVED,
            reviewer="dm",
        )

        with pytest.raises(ValidationError):
            persist_approval(store, approval)

        assert store.approvals == {}

    def test_malformed_existing_approval_is_storage_error(self) -> None:
        store = FakeChangeSetStore()
        changeset = _changeset()
        persist_proposal(store, changeset)
        store.approvals[changeset.changeset_id] = "{not json"

        with pytest.raises(StorageError):
            persist_approval(store, _approval(changeset))


# ── parse_changeset_document (external input) ──────────────────────────────


class TestParseDocument:
    def test_valid_document_round_trips(self) -> None:
        changeset = _changeset()
        from dnd_assistant.application.changeset_store import serialize_proposal

        assert parse_changeset_document(serialize_proposal(changeset)) == changeset

    def test_malformed_document_is_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_changeset_document("{not json")

    def test_non_object_document_is_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_changeset_document("[1, 2, 3]")

    def test_invalid_changeset_document_is_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_changeset_document('{"unexpected": true}')


def serialize_proposal_via(changeset: ChangeSet) -> str:
    """Local alias to avoid importing the serializer in every test."""
    from dnd_assistant.application.changeset_store import serialize_proposal

    return serialize_proposal(changeset)
