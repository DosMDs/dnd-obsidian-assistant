"""Unit tests for S10-03 ChangeSet review, fingerprint and approval binding.

Covers the application-owned contracts:

- canonical deterministic ChangeSet serialization;
- SHA-256 fingerprint stability and sensitivity (including explicit None vs
  omitted ``EntityFieldUpdate`` fields across both round-trip forms);
- proposal-only review DTOs and item ordering;
- explicit, immutable approval/rejection content binding;
- invalid-proposal refusal and zero-write evidence.

These tests exercise behavior directly rather than inspecting source text,
except for the deliberate boundary/zero-write guards that must prove a negative.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application import changeset_review
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ChangeSetFingerprint,
    ChangeSetReview,
    ReviewDecision,
    ReviewerId,
    ReviewItem,
    build_changeset_review,
    canonical_changeset_bytes,
    compute_changeset_fingerprint,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
    EntityFieldUpdate,
    ProposalProvenance,
    UpdateEntityOperation,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Provenance,
    Revision,
    Visibility,
)
from dnd_assistant.errors import ValidationError as DndValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultDocument
from tests.support.repository_doubles import VaultRepositoryWriteStubs

# ── Repository spy ────────────────────────────────────────────────────────

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

_reviewer_adapter: TypeAdapter[str] = TypeAdapter(ReviewerId)


class SpyVaultRepository(VaultRepositoryWriteStubs):
    """Read-only repository double that counts every attempted mutation."""

    def __init__(self, documents: list[VaultDocument] | None = None) -> None:
        self.create_calls = 0
        self.patch_calls = 0
        self.append_calls = 0
        self.list_calls = 0
        self._documents = list(documents) if documents else []

    @property
    def write_calls(self) -> int:
        return self.create_calls + self.patch_calls + self.append_calls

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        raise AssertionError("review must not call get_entity")

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        self.list_calls += 1
        return list(self._documents)

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        self.create_calls += 1
        raise AssertionError("review must not write")

    def patch_entity(
        self,
        entity_id: EntityId,
        patch: EntityPatch,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> VaultDocument:
        self.patch_calls += 1
        raise AssertionError("review must not write")

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        self.append_calls += 1
        raise AssertionError("review must not write")


# ── Builders ──────────────────────────────────────────────────────────────


def _document(
    entity_id: str,
    revision: int,
    entity_type: EntityType = EntityType.NPC,
) -> VaultDocument:
    entity = Entity(
        id=entity_id,
        type=entity_type,
        name=f"Entity {entity_id}",
        status="active",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=_T0,
        updated_at=_T0,
        revision=revision,
    )
    return VaultDocument(entity=entity)


def _create(
    entity_id: str = "npc_a",
    *,
    name: str = "Entity npc_a",
    entity_type: EntityType = EntityType.NPC,
    tags: tuple[str, ...] = (),
) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=entity_type,
        name=name,
        status="active",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        tags=tags,
    )


def _update(
    entity_id: str = "npc_a",
    expected_revision: int = 1,
    *,
    update: EntityFieldUpdate | None = None,
) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        update=update if update is not None else EntityFieldUpdate(status="dead"),
    )


def _append(entity_id: str = "npc_a", expected_revision: int = 2, *, fact: str = "A fact"):
    return AppendFactOperation(entity_id=entity_id, expected_revision=expected_revision, fact=fact)


def _changeset(
    *operations: object,
    changeset_id: str = "cs_test",
    provenance: ProposalProvenance | None = None,
    session_ref: str | None = "S014",
) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=provenance or ProposalProvenance(provenance=Provenance.MANUAL),
        session_ref=session_ref,
        operations=operations,  # type: ignore[arg-type]
    )


def _base_provenance() -> ProposalProvenance:
    return ProposalProvenance(
        provenance=Provenance.MODEL_INFERENCE,
        model_profile="post_session",
        prompt_version="v3",
    )


def _base_changeset() -> ChangeSet:
    return _changeset(
        _create("npc_a", name="Варос", tags=("mentor",)),
        _update("npc_a", 1),
        _append("npc_a", 2, fact="Убит у ворот"),
        changeset_id="cs_base",
        provenance=_base_provenance(),
    )


# ── 1. Canonical determinism ──────────────────────────────────────────────


class TestCanonicalDeterminism:
    def test_independent_construction_is_identical(self) -> None:
        first = _base_changeset()
        second = _base_changeset()
        assert first is not second
        assert canonical_changeset_bytes(first) == canonical_changeset_bytes(second)
        assert compute_changeset_fingerprint(first) == compute_changeset_fingerprint(second)

    def test_repeated_serialization_is_stable(self) -> None:
        changeset = _base_changeset()
        assert canonical_changeset_bytes(changeset) == canonical_changeset_bytes(changeset)

    def test_dict_insertion_order_is_irrelevant(self) -> None:
        forward = {
            "provenance": {"provenance": "manual", "model_profile": "m"},
            "changeset_id": "cs_order",
            "operations": [
                {
                    "kind": "create_entity",
                    "entity_id": "npc_a",
                    "type": "npc",
                    "name": "A",
                    "status": "alive",
                    "visibility": "dm",
                    "knowledge_status": "confirmed",
                }
            ],
        }
        reversed_keys = {key: forward[key] for key in reversed(list(forward))}
        assert canonical_changeset_bytes(ChangeSet.model_validate(forward)) == (
            canonical_changeset_bytes(ChangeSet.model_validate(reversed_keys))
        )

    def test_output_is_compact_and_single_line(self) -> None:
        data = canonical_changeset_bytes(_base_changeset())
        assert b"\n" not in data
        assert b'": "' not in data
        assert b'", "' not in data

    def test_utf8_unicode_is_preserved(self) -> None:
        data = canonical_changeset_bytes(_base_changeset())
        text = data.decode("utf-8")
        assert "Варос" in text
        assert "Убит у ворот" in text

    def test_review_metadata_and_repository_data_absent(self) -> None:
        import json as json_module

        payload = json_module.loads(canonical_changeset_bytes(_base_changeset()))
        assert set(payload) == {
            "schema_version",
            "changeset_id",
            "provenance",
            "session_ref",
            "operations",
        }

        forbidden = {
            "reviewer",
            "decision",
            "reason",
            "approved",
            "rejected",
            "applied",
            "fingerprint",
            "hash",
            "timestamp",
            "created_at",
            "updated_at",
            "path",
            "file",
            "filename",
            "repository",
        }

        def collect_keys(node: object) -> set[str]:
            keys: set[str] = set()
            if isinstance(node, dict):
                for key, value in node.items():
                    keys.add(key)
                    keys |= collect_keys(value)
            elif isinstance(node, list):
                for value in node:
                    keys |= collect_keys(value)
            return keys

        assert collect_keys(payload).isdisjoint(forbidden)


# ── 2 & 3. Round-trip stability ───────────────────────────────────────────


class TestRoundTripStability:
    def test_python_round_trip_is_stable(self) -> None:
        original = _base_changeset()
        reparsed = ChangeSet.model_validate(original.model_dump())
        assert canonical_changeset_bytes(reparsed) == canonical_changeset_bytes(original)
        assert compute_changeset_fingerprint(reparsed) == compute_changeset_fingerprint(original)

    def test_json_round_trip_is_stable(self) -> None:
        original = _base_changeset()
        reparsed = ChangeSet.model_validate_json(original.model_dump_json())
        assert canonical_changeset_bytes(reparsed) == canonical_changeset_bytes(original)
        assert compute_changeset_fingerprint(reparsed) == compute_changeset_fingerprint(original)


# ── 4. Explicit None vs omitted (blocking) ────────────────────────────────


class TestExplicitNoneVsOmitted:
    def _pair(self, field: str) -> tuple[ChangeSet, ChangeSet]:
        omitted = _changeset(
            _update(update=EntityFieldUpdate(name="X")),
            changeset_id="cs_none",
        )
        explicit = _changeset(
            _update(update=EntityFieldUpdate.model_validate({"name": "X", field: None})),
            changeset_id="cs_none",
        )
        return omitted, explicit

    @pytest.mark.parametrize("field", ["created_session", "last_seen_session"])
    def test_omitted_and_explicit_none_fingerprint_differently(self, field: str) -> None:
        omitted, explicit = self._pair(field)
        assert omitted.operations[0].update.model_fields_set == {"name"}  # type: ignore[union-attr]
        assert explicit.operations[0].update.model_fields_set == {"name", field}  # type: ignore[union-attr]
        assert canonical_changeset_bytes(omitted) != canonical_changeset_bytes(explicit)
        assert compute_changeset_fingerprint(omitted) != compute_changeset_fingerprint(explicit)

    @pytest.mark.parametrize("field", ["created_session", "last_seen_session"])
    def test_python_round_trip_preserves_distinction(self, field: str) -> None:
        omitted, explicit = self._pair(field)
        assert compute_changeset_fingerprint(ChangeSet.model_validate(omitted.model_dump())) == (
            compute_changeset_fingerprint(omitted)
        )
        assert compute_changeset_fingerprint(ChangeSet.model_validate(explicit.model_dump())) == (
            compute_changeset_fingerprint(explicit)
        )
        assert compute_changeset_fingerprint(ChangeSet.model_validate(omitted.model_dump())) != (
            compute_changeset_fingerprint(ChangeSet.model_validate(explicit.model_dump()))
        )

    @pytest.mark.parametrize("field", ["created_session", "last_seen_session"])
    def test_json_round_trip_preserves_distinction(self, field: str) -> None:
        omitted, explicit = self._pair(field)
        re_omitted = ChangeSet.model_validate_json(omitted.model_dump_json())
        re_explicit = ChangeSet.model_validate_json(explicit.model_dump_json())
        assert re_omitted.operations[0].update.model_fields_set == {"name"}  # type: ignore[union-attr]
        assert re_explicit.operations[0].update.model_fields_set == {"name", field}  # type: ignore[union-attr]
        assert canonical_changeset_bytes(re_omitted) != canonical_changeset_bytes(re_explicit)
        assert compute_changeset_fingerprint(re_omitted) != compute_changeset_fingerprint(
            re_explicit
        )


# ── 5. Fingerprint sensitivity ────────────────────────────────────────────


class TestFingerprintSensitivity:
    def _fingerprint(self, changeset: ChangeSet) -> ChangeSetFingerprint:
        return compute_changeset_fingerprint(changeset)

    @pytest.mark.parametrize(
        "variant",
        [
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_other",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=ProposalProvenance(
                    provenance=Provenance.SESSION,
                    model_profile="post_session",
                    prompt_version="v3",
                ),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=ProposalProvenance(
                    provenance=Provenance.MODEL_INFERENCE,
                    model_profile="other",
                    prompt_version="v3",
                ),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=ProposalProvenance(
                    provenance=Provenance.MODEL_INFERENCE,
                    model_profile="post_session",
                    prompt_version="v4",
                ),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
                session_ref="S099",
            ),
            _changeset(
                _append("npc_a", 2, fact="Убит у ворот"),
                _update("npc_a", 1),
                _create("npc_a", name="Варос", tags=("mentor",)),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_z", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 5),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1, update=EntityFieldUpdate(name="Other")),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1, update=EntityFieldUpdate(status="gone")),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Другая запись"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Другое имя", tags=("mentor",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", tags=("other",)),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
            _changeset(
                _create("npc_a", name="Варос", entity_type=EntityType.QUEST),
                _update("npc_a", 1),
                _append("npc_a", 2, fact="Убит у ворот"),
                changeset_id="cs_base",
                provenance=_base_provenance(),
            ),
        ],
    )
    def test_apply_relevant_change_changes_digest(self, variant: ChangeSet) -> None:
        assert self._fingerprint(variant) != self._fingerprint(_base_changeset())

    def test_semantically_equal_changesets_have_equal_digest(self) -> None:
        assert self._fingerprint(_base_changeset()) == self._fingerprint(_base_changeset())


# ── 6. Fingerprint format / immutability ──────────────────────────────────


class TestFingerprintFormat:
    def test_algorithm_and_digest_shape(self) -> None:
        fingerprint = compute_changeset_fingerprint(_base_changeset())
        assert fingerprint.algorithm == "sha256"
        assert len(fingerprint.digest) == 64
        assert fingerprint.digest == fingerprint.digest.lower()
        int(fingerprint.digest, 16)

    @pytest.mark.parametrize(
        "bad_digest",
        [
            "A" * 64,
            "a" * 63,
            "a" * 65,
            "z" * 64,
            "",
        ],
    )
    def test_invalid_digest_rejected(self, bad_digest: str) -> None:
        with pytest.raises(PydanticValidationError):
            ChangeSetFingerprint(digest=bad_digest)

    def test_frozen_and_extra_forbidden(self) -> None:
        fingerprint = compute_changeset_fingerprint(_base_changeset())
        with pytest.raises(PydanticValidationError):
            fingerprint.digest = "b" * 64
        with pytest.raises(PydanticValidationError):
            ChangeSetFingerprint.model_validate({"digest": "a" * 64, "extra": "x"})


# ── 7. Reviewer validation ────────────────────────────────────────────────


class TestReviewerValidation:
    @pytest.mark.parametrize("reviewer", ["dm", "Мастер", "reviewer.1", "a"])
    def test_accepts_valid_reviewer(self, reviewer: str) -> None:
        assert _reviewer_adapter.validate_python(reviewer) == reviewer

    @pytest.mark.parametrize(
        "reviewer",
        ["", " ", " padded", "padded ", "tab\there", "new\nline", "ctrl\x00"],
    )
    def test_rejects_invalid_reviewer(self, reviewer: str) -> None:
        with pytest.raises(PydanticValidationError):
            _reviewer_adapter.validate_python(reviewer)

    def test_rejects_non_string_reviewer(self) -> None:
        with pytest.raises(PydanticValidationError):
            _reviewer_adapter.validate_python(123)


# ── 8. Approval / rejection content binding ───────────────────────────────


class TestApprovalBinding:
    def _approval(self, changeset: ChangeSet, **overrides: Any) -> ChangeSetApproval:
        payload: dict[str, Any] = {
            "changeset_id": changeset.changeset_id,
            "fingerprint": compute_changeset_fingerprint(changeset),
            "decision": ReviewDecision.APPROVED,
            "reviewer": "dm",
        }
        payload.update(overrides)
        return ChangeSetApproval(**payload)

    def test_approved_with_matching_content_binds(self) -> None:
        changeset = _base_changeset()
        approval = self._approval(changeset)
        assert approval.is_approved is True
        assert approval.matches_approved_changeset(changeset) is True

    def test_approved_with_wrong_fingerprint_does_not_bind(self) -> None:
        changeset = _base_changeset()
        other = _changeset(_create("npc_other"))
        approval = self._approval(changeset, fingerprint=compute_changeset_fingerprint(other))
        assert approval.matches_approved_changeset(changeset) is False

    def test_approved_with_wrong_changeset_id_does_not_bind(self) -> None:
        changeset = _base_changeset()
        approval = self._approval(changeset, changeset_id="cs_other")
        assert approval.matches_approved_changeset(changeset) is False

    def test_rejected_with_correct_fingerprint_does_not_bind(self) -> None:
        changeset = _base_changeset()
        approval = self._approval(changeset, decision=ReviewDecision.REJECTED)
        assert approval.is_approved is False
        assert approval.matches_approved_changeset(changeset) is False

    def test_decision_and_reviewer_are_mandatory(self) -> None:
        changeset = _base_changeset()
        fingerprint = compute_changeset_fingerprint(changeset)
        with pytest.raises(PydanticValidationError):
            ChangeSetApproval(  # type: ignore[call-arg]
                changeset_id=changeset.changeset_id,
                fingerprint=fingerprint,
                reviewer="dm",
            )
        with pytest.raises(PydanticValidationError):
            ChangeSetApproval(  # type: ignore[call-arg]
                changeset_id=changeset.changeset_id,
                fingerprint=fingerprint,
                decision=ReviewDecision.APPROVED,
            )

    def test_reason_is_optional_and_validated(self) -> None:
        changeset = _base_changeset()
        approved = self._approval(changeset)
        assert approved.reason is None
        rejected = self._approval(
            changeset, decision=ReviewDecision.REJECTED, reason="Не соответствует кампании"
        )
        assert rejected.reason == "Не соответствует кампании"
        with pytest.raises(PydanticValidationError):
            self._approval(changeset, reason="  ")

    def test_frozen_and_extra_forbidden(self) -> None:
        approval = self._approval(_base_changeset())
        with pytest.raises(PydanticValidationError):
            approval.decision = ReviewDecision.REJECTED
        with pytest.raises(PydanticValidationError):
            ChangeSetApproval.model_validate(
                {
                    "changeset_id": approval.changeset_id,
                    "fingerprint": approval.fingerprint.model_dump(),
                    "decision": "approved",
                    "reviewer": "dm",
                    "extra": "x",
                }
            )

    def test_content_binding_predicate_takes_no_repository(self) -> None:
        parameters = list(
            inspect.signature(ChangeSetApproval.matches_approved_changeset).parameters
        )
        assert parameters == ["self", "changeset"]


# ── 9. Immutability of review DTOs ────────────────────────────────────────


class TestReviewImmutability:
    def _review(self) -> ChangeSetReview:
        return build_changeset_review(_base_changeset(), SpyVaultRepository())

    def test_review_is_frozen_and_strict(self) -> None:
        review = self._review()
        with pytest.raises(PydanticValidationError):
            review.changeset_id = "other"
        with pytest.raises(PydanticValidationError):
            ChangeSetReview.model_validate({**review.model_dump(), "extra": "x"})

    def test_item_is_frozen_and_strict(self) -> None:
        item = self._review().items[0]
        with pytest.raises(PydanticValidationError):
            item.operation_index = 99
        with pytest.raises(PydanticValidationError):
            ReviewItem.model_validate(
                {"operation_index": 0, "operation": item.operation.model_dump(), "extra": "x"}
            )

    def test_review_requires_non_empty_items(self) -> None:
        review = self._review()
        with pytest.raises(PydanticValidationError):
            ChangeSetReview(
                changeset_id=review.changeset_id,
                fingerprint=review.fingerprint,
                provenance=review.provenance,
                items=(),
            )

    def test_review_decision_is_str_enum(self) -> None:
        assert ReviewDecision.APPROVED == "approved"
        assert ReviewDecision.REJECTED == "rejected"


# ── 10. Review item order ─────────────────────────────────────────────────


class TestReviewItemOrder:
    def test_items_map_one_to_one_to_operations(self) -> None:
        changeset = _base_changeset()
        review = build_changeset_review(changeset, SpyVaultRepository())

        assert [item.operation_index for item in review.items] == [0, 1, 2]
        assert [item.kind for item in review.items] == [
            "create_entity",
            "update_entity",
            "append_fact",
        ]
        assert [item.entity_id for item in review.items] == ["npc_a", "npc_a", "npc_a"]
        assert review.items[0].expected_revision is None
        assert review.items[1].expected_revision == 1
        assert review.items[2].expected_revision == 2

    def test_review_is_content_bound_and_proposal_only(self) -> None:
        changeset = _base_changeset()
        review = build_changeset_review(changeset, SpyVaultRepository())
        assert review.changeset_id == changeset.changeset_id
        assert review.fingerprint == compute_changeset_fingerprint(changeset)
        assert review.provenance == changeset.provenance
        assert review.session_ref == changeset.session_ref
        assert review.items[0].operation is changeset.operations[0]
        assert "current" not in ChangeSetReview.model_fields
        assert "old_value" not in ChangeSetReview.model_fields

    def test_review_is_deterministic(self) -> None:
        changeset = _base_changeset()
        first = build_changeset_review(changeset, SpyVaultRepository())
        second = build_changeset_review(changeset, SpyVaultRepository())
        assert first == second


# ── 11. Invalid proposal guard ────────────────────────────────────────────


class TestInvalidProposalGuard:
    def test_create_of_existing_entity_refuses_review(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 7)])
        with pytest.raises(DndValidationError):
            build_changeset_review(_changeset(_create("npc_a")), repo)

    def test_stale_revision_refuses_review(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 4)])
        with pytest.raises(DndValidationError):
            build_changeset_review(_changeset(_update("npc_a", 99)), repo)

    def test_missing_target_refuses_review(self) -> None:
        with pytest.raises(DndValidationError):
            build_changeset_review(_changeset(_append("npc_missing", 1)), SpyVaultRepository())


# ── 12. Zero-write evidence ───────────────────────────────────────────────


class TestZeroWriteEvidence:
    def test_valid_review_performs_zero_writes(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 1)])
        build_changeset_review(_changeset(_update("npc_a", 1)), repo)
        assert repo.create_calls == 0
        assert repo.patch_calls == 0
        assert repo.append_calls == 0
        assert repo.write_calls == 0

    def test_invalid_review_performs_zero_writes(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 7)])
        with pytest.raises(DndValidationError):
            build_changeset_review(_changeset(_create("npc_a")), repo)
        assert repo.create_calls == 0
        assert repo.patch_calls == 0
        assert repo.append_calls == 0
        assert repo.write_calls == 0

    def test_fingerprint_performs_no_repository_access(self) -> None:
        repo = SpyVaultRepository([_document("npc_a", 1)])
        compute_changeset_fingerprint(_base_changeset())
        assert repo.list_calls == 0
        assert repo.write_calls == 0

    def test_module_source_has_no_write_method_references(self) -> None:
        tree = ast.parse(inspect.getsource(changeset_review))
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        write_methods = {"create_entity", "patch_entity", "append_entity_fact"}
        assert attributes.isdisjoint(write_methods), (
            f"changeset_review references write methods: {attributes & write_methods}"
        )
