"""S11-05 deterministic post-session ChangeSet producer tests."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from dnd_assistant.application.changeset_review import (
    ChangeSetFingerprint,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_validation import validate_changeset
from dnd_assistant.application.entity_id_allocator import allocate_candidate_entity_id
from dnd_assistant.application.post_session_changeset import (
    CREATE_DEFAULT_KNOWLEDGE,
    CREATE_DEFAULT_STATUS,
    CREATE_DEFAULT_VISIBILITY,
    PostSessionChangeError,
    PostSessionChangeFailureReason,
    PostSessionChangeOutcome,
    PostSessionChangePlanResult,
    PostSessionChangeUnresolvedReason,
    produce_post_session_changeset,
)
from dnd_assistant.application.post_session_extraction import (
    run_post_session_extraction,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    CreateEntityOperation,
)
from dnd_assistant.domain.post_session_extraction import ClaimKind
from dnd_assistant.domain.types import (
    EntityType,
    Provenance,
    Visibility,
)
from dnd_assistant.storage.types import VaultDocument
from tests.unit.post_session.changeset_helpers import (
    ATTEMPT_A,
    ATTEMPT_B,
    FakeReadOnlyRepository,
    make_document,
    make_prepared,
)
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
)


def _accept(prepared, extraction):
    return run_post_session_extraction(FakePostSessionExtractionModel(extraction), prepared)


def _produce(
    documents: Sequence[VaultDocument],
    extraction,
    *,
    prepared=None,
    attempt: str = ATTEMPT_A,
    event_ids: Sequence[str] = ("evt_001",),
) -> tuple[PostSessionChangePlanResult, FakeReadOnlyRepository]:
    if prepared is None:
        prepared = make_prepared(documents, event_ids=event_ids)
    accepted = _accept(prepared, extraction)
    repository = FakeReadOnlyRepository(documents)
    result = produce_post_session_changeset(
        prepared, accepted, attempt_id=attempt, repository=repository
    )
    return result, repository


def _evidence_for(result: PostSessionChangePlanResult, reason):
    return [item for item in result.unresolved if item.reason is reason]


# ── Provenance / identity ──────────────────────────────────────────────────


def test_proposal_binds_identity_provenance_and_passes_preflight() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                text="Aria arrived at the tavern.",
                entity_mentions=(
                    make_mention(candidate_entity_id="npc-aria", entity_type=EntityType.NPC),
                ),
            ),
        )
    )
    result, repository = _produce([document], extraction)

    assert result.outcome is PostSessionChangeOutcome.PROPOSAL
    assert result.changeset is not None
    assert result.changeset.changeset_id == f"cs_S001_{ATTEMPT_A}"
    assert result.changeset.session_ref == "S001"
    assert result.changeset.provenance.provenance is Provenance.MODEL_INFERENCE
    assert result.changeset.provenance.prompt_version == result.provenance.prompt_version
    assert result.changeset.provenance.model_profile is None

    operation = result.changeset.operations[0]
    assert isinstance(operation, AppendFactOperation)
    assert operation.entity_id == "npc-aria"
    assert operation.expected_revision == 1
    assert operation.fact == "Aria arrived at the tavern."

    assert validate_changeset(result.changeset, repository).valid is True
    # binding snapshot + producer preflight + this explicit test validation
    assert repository.list_entities_calls == 3
    assert repository.writes == []


def test_provenance_mismatch_fails_before_any_read() -> None:
    document = make_document("npc-aria", name="Aria")
    first = make_prepared([document], context_text="context one")
    second = make_prepared([document], context_text="context two")
    accepted = _accept(first, make_extraction())
    repository = FakeReadOnlyRepository([document])

    with pytest.raises(PostSessionChangeError) as excinfo:
        produce_post_session_changeset(
            second, accepted, attempt_id=ATTEMPT_A, repository=repository
        )

    assert excinfo.value.reason is PostSessionChangeFailureReason.PROVENANCE_MISMATCH
    assert repository.list_entities_calls == 0


def test_invalid_attempt_id_fails_closed() -> None:
    document = make_document("npc-aria", name="Aria")
    prepared = make_prepared([document])
    accepted = _accept(prepared, make_extraction())
    repository = FakeReadOnlyRepository([document])

    with pytest.raises(PostSessionChangeError) as excinfo:
        produce_post_session_changeset(
            prepared, accepted, attempt_id="not-an-attempt", repository=repository
        )

    assert excinfo.value.reason is PostSessionChangeFailureReason.INVALID_ATTEMPT_ID


def test_same_input_and_attempt_are_byte_equivalent() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
            ),
        )
    )
    first, _ = _produce([document], extraction)
    second, _ = _produce([document], extraction)
    assert first.changeset is not None and second.changeset is not None
    assert compute_changeset_fingerprint(first.changeset) == compute_changeset_fingerprint(
        second.changeset
    )


# ── Existing entity binding ────────────────────────────────────────────────


def test_unique_trusted_binding_emits_append() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    assert isinstance(result.changeset.operations[0], AppendFactOperation)


def test_fabricated_model_id_never_becomes_target() -> None:
    document = make_document("npc-aria", name="Vera")
    extraction = make_extraction(
        claims=(
            make_claim(
                text="Unknown person appeared.",
                entity_mentions=(
                    make_mention(candidate_entity_id="npc-fabricated", text="Fabricated"),
                ),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert result.changeset is None


def test_multiple_operations_on_one_entity_use_projected_revisions() -> None:
    document = make_document("npc-aria", name="Aria", revision=3)
    extraction = make_extraction(
        claims=(
            make_claim(
                claim_id="c1",
                text="First fact.",
                entity_mentions=(make_mention(mention_id="m1", candidate_entity_id="npc-aria"),),
            ),
            make_claim(
                claim_id="c2",
                text="Second fact.",
                entity_mentions=(make_mention(mention_id="m2", candidate_entity_id="npc-aria"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    revisions = [
        op.expected_revision
        for op in result.changeset.operations
        if isinstance(op, AppendFactOperation)
    ]
    assert revisions == [3, 4]


def test_dm_target_is_allowed() -> None:
    document = make_document("npc-hidden", name="Hidden", visibility=Visibility.DM)
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(candidate_entity_id="npc-hidden"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    assert isinstance(result.changeset.operations[0], AppendFactOperation)


def test_system_target_is_excluded() -> None:
    document = make_document("npc-system", name="System", visibility=Visibility.SYSTEM)
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(candidate_entity_id="npc-system"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.SYSTEM_ENTITY_EXCLUDED)


def test_stale_revision_blocks_and_never_rebases() -> None:
    original = make_document("npc-aria", name="Aria", revision=1)
    prepared = make_prepared([original])
    accepted = _accept(
        prepared,
        make_extraction(
            claims=(make_claim(entity_mentions=(make_mention(candidate_entity_id="npc-aria"),)),)
        ),
    )
    mutated = make_document("npc-aria", name="Aria", revision=2)
    repository = FakeReadOnlyRepository([mutated])
    result = produce_post_session_changeset(
        prepared, accepted, attempt_id=ATTEMPT_A, repository=repository
    )
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.STALE_PREPARED_ENTITY)


def test_same_revision_but_changed_fields_are_stale() -> None:
    original = make_document(
        "npc-aria", name="Aria", status="alive", tags=["ranger"], body="body\n"
    )
    mutations = {
        "name": make_document("npc-aria", name="Aria the Bold", body="body\n"),
        "status": make_document("npc-aria", name="Aria", status="dead", body="body\n"),
        "tags": make_document("npc-aria", name="Aria", tags=["changed"], body="body\n"),
        "body": make_document("npc-aria", name="Aria", body="different\n"),
    }
    for label, mutated in mutations.items():
        prepared = make_prepared([original])
        accepted = _accept(
            prepared,
            make_extraction(
                claims=(
                    make_claim(entity_mentions=(make_mention(candidate_entity_id="npc-aria"),)),
                )
            ),
        )
        repository = FakeReadOnlyRepository([mutated])
        result = produce_post_session_changeset(
            prepared, accepted, attempt_id=ATTEMPT_A, repository=repository
        )
        assert result.outcome is PostSessionChangeOutcome.NO_CHANGES, label
        assert _evidence_for(result, PostSessionChangeUnresolvedReason.STALE_PREPARED_ENTITY), label


# ── Ambiguity and exact resolution ────────────────────────────────────────


def test_exact_name_wrong_type_is_not_bound() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(text="Aria", entity_type=EntityType.LOCATION),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES


def test_exact_alias_wrong_type_is_not_bound() -> None:
    document = make_document("npc-aria", name="Aria", aliases=["Лорд Ария"])
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(text="Лорд Ария", entity_type=EntityType.LOCATION),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES


def test_alias_only_mention_resolves_through_internal_resolver() -> None:
    document = make_document("npc-aria", name="Aria", aliases=["Лорд Ария"])
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(make_mention(text="Лорд Ария", entity_type=EntityType.NPC),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    appends = [op for op in result.changeset.operations if isinstance(op, AppendFactOperation)]
    assert appends[0].entity_id == "npc-aria"


def test_multiple_exact_candidates_are_ambiguous() -> None:
    documents = [
        make_document("npc-aria-1", name="Aria"),
        make_document("npc-aria-2", name="Aria"),
    ]
    extraction = make_extraction(
        claims=(
            make_claim(entity_mentions=(make_mention(text="Aria", entity_type=EntityType.NPC),)),
        )
    )
    result, _ = _produce(documents, extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES


def test_one_resolved_and_one_unresolved_mention_suppresses_whole_claim() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(
                    make_mention(mention_id="m1", candidate_entity_id="npc-aria"),
                    make_mention(mention_id="m2", text="Nobody", entity_type=EntityType.NPC),
                ),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.UNRESOLVED_REFERENCE)


def test_two_mentions_of_same_entity_make_one_target() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(
                    make_mention(mention_id="m1", candidate_entity_id="npc-aria"),
                    make_mention(mention_id="m2", candidate_entity_id="npc-aria"),
                ),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    assert len(result.changeset.operations) == 1


def test_two_different_resolved_entities_are_not_appendable() -> None:
    documents = [
        make_document("npc-aria", name="Aria"),
        make_document("npc-borin", name="Borin"),
    ]
    extraction = make_extraction(
        claims=(
            make_claim(
                entity_mentions=(
                    make_mention(mention_id="m1", candidate_entity_id="npc-aria"),
                    make_mention(mention_id="m2", candidate_entity_id="npc-borin"),
                ),
            ),
        )
    )
    result, _ = _produce(documents, extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.UNSUPPORTED_MULTI_TARGET)


# ── ClaimKind / duplicate fact ─────────────────────────────────────────────


@pytest.mark.parametrize("kind", [ClaimKind.RELATIONSHIP, ClaimKind.OTHER])
def test_unsupported_claim_kinds_are_omitted_with_diagnostic(kind: ClaimKind) -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                kind=kind,
                entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.UNSUPPORTED_CLAIM_KIND)


def test_zero_target_claim_produces_no_mutation() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(claims=(make_claim(text="Ambient event."),))
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.NO_CANONICAL_TARGET)


def test_exact_duplicate_fact_in_body_is_suppressed() -> None:
    document = make_document("npc-aria", name="Aria", body="- Aria arrived.\n")
    extraction = make_extraction(
        claims=(
            make_claim(
                text="Aria arrived.",
                entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_FACT)


def test_duplicate_fact_within_batch_is_suppressed() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                claim_id="c1",
                text="Repeated fact.",
                entity_mentions=(make_mention(mention_id="m1", candidate_entity_id="npc-aria"),),
            ),
            make_claim(
                claim_id="c2",
                text="Repeated fact.",
                entity_mentions=(make_mention(mention_id="m2", candidate_entity_id="npc-aria"),),
            ),
        )
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    assert len(result.changeset.operations) == 1
    assert len(_evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_FACT)) == 1


# ── New entity candidates ──────────────────────────────────────────────────


def _candidate_extraction(*candidates):
    return make_extraction(entity_candidates=tuple(candidates))


def test_new_candidate_creates_with_python_owned_defaults() -> None:
    document = make_document("npc-aria", name="Aria")
    candidate = make_candidate(
        candidate_id="cand-1",
        display_name="The Rusty Anchor",
        entity_type=EntityType.LOCATION,
    )
    result, repository = _produce([document], _candidate_extraction(candidate))
    assert result.changeset is not None
    operation = result.changeset.operations[0]
    assert isinstance(operation, CreateEntityOperation)
    assert operation.type is EntityType.LOCATION
    assert operation.name == "The Rusty Anchor"
    assert operation.status == CREATE_DEFAULT_STATUS
    assert operation.visibility is CREATE_DEFAULT_VISIBILITY
    assert operation.knowledge_status is CREATE_DEFAULT_KNOWLEDGE
    assert operation.created_session == "S001"
    assert operation.last_seen_session == "S001"
    assert operation.tags == ()
    assert validate_changeset(result.changeset, repository).valid is True


def test_candidate_attributes_and_summary_cannot_override_defaults() -> None:
    document = make_document("npc-aria", name="Aria")
    candidate = make_candidate(
        candidate_id="cand-1",
        display_name="The Rusty Anchor",
        entity_type=EntityType.LOCATION,
    )
    candidate = candidate.model_copy(
        update={
            "attributes": (),
            "summary": "A tavern with status alive and player visibility.",
        }
    )
    result, _ = _produce([document], _candidate_extraction(candidate))
    assert result.changeset is not None
    operation = result.changeset.operations[0]
    assert isinstance(operation, CreateEntityOperation)
    assert operation.status == CREATE_DEFAULT_STATUS
    assert operation.visibility is CREATE_DEFAULT_VISIBILITY
    assert operation.knowledge_status is CREATE_DEFAULT_KNOWLEDGE


def test_evidence_refs_do_not_change_allocated_identity() -> None:
    document = make_document("npc-aria", name="Aria")
    prepared = make_prepared([document], event_ids=("evt_001", "evt_002"))
    first = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
            evidence_event_ids=("evt_001",),
        )
    )
    second = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
            evidence_event_ids=("evt_002",),
        )
    )
    first_result, _ = _produce([document], first, prepared=prepared)
    second_result, _ = _produce([document], second, prepared=prepared)
    assert first_result.changeset is not None and second_result.changeset is not None
    first_op = first_result.changeset.operations[0]
    second_op = second_result.changeset.operations[0]
    assert isinstance(first_op, CreateEntityOperation)
    assert isinstance(second_op, CreateEntityOperation)
    assert first_op.entity_id == second_op.entity_id


def test_cross_attempt_reuses_candidate_scoped_entity_id() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    first, _ = _produce([document], extraction, attempt=ATTEMPT_A)
    second, _ = _produce([document], extraction, attempt=ATTEMPT_B)
    assert first.changeset is not None and second.changeset is not None
    first_op = first.changeset.operations[0]
    second_op = second.changeset.operations[0]
    assert isinstance(first_op, CreateEntityOperation)
    assert isinstance(second_op, CreateEntityOperation)
    assert first_op.entity_id == second_op.entity_id
    assert first.changeset.changeset_id != second.changeset.changeset_id


def test_two_candidates_with_same_allocation_identity_fail_closed() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = _candidate_extraction(
        make_candidate(candidate_id="cand-1", display_name="Rusty Anchor"),
        make_candidate(candidate_id="cand-2", display_name="Rusty Anchor"),
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.ENTITY_ID_COLLISION)


def test_exact_name_match_prevents_duplicate_create() -> None:
    document = make_document("loc-rusty", entity_type=EntityType.LOCATION, name="The Rusty Anchor")
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY)


def test_exact_alias_match_prevents_duplicate_create() -> None:
    document = make_document(
        "loc-rusty",
        entity_type=EntityType.LOCATION,
        name="The Anchor",
        aliases=["The Rusty Anchor"],
    )
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY)


def test_system_collision_prevents_duplicate_create() -> None:
    document = make_document(
        "loc-rusty",
        entity_type=EntityType.LOCATION,
        name="The Rusty Anchor",
        visibility=Visibility.SYSTEM,
    )
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY)


def test_cross_type_collision_prevents_duplicate_create() -> None:
    document = make_document("npc-rusty", name="The Rusty Anchor")
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY)


def test_allocated_id_collision_with_different_identity_fails_closed() -> None:
    allocated = allocate_candidate_entity_id("S001", EntityType.LOCATION, "The Rusty Anchor")
    document = make_document(allocated, entity_type=EntityType.LOCATION, name="Something Else")
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    result, _ = _produce([document], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.ENTITY_ID_COLLISION)


def test_rerun_after_entity_exists_does_not_create_duplicate() -> None:
    allocated = allocate_candidate_entity_id("S001", EntityType.LOCATION, "The Rusty Anchor")
    existing = make_document(allocated, entity_type=EntityType.LOCATION, name="The Rusty Anchor")
    extraction = _candidate_extraction(
        make_candidate(
            candidate_id="cand-1",
            display_name="The Rusty Anchor",
            entity_type=EntityType.LOCATION,
        )
    )
    result, _ = _produce([existing], extraction)
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert _evidence_for(result, PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY)


# ── Ordering / preflight / result contract ─────────────────────────────────


def test_creates_precede_appends_in_stable_order() -> None:
    document = make_document("npc-aria", name="Aria")
    extraction = make_extraction(
        claims=(
            make_claim(
                text="Aria found the anchor.",
                entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
            ),
        ),
        entity_candidates=(make_candidate(candidate_id="cand-1", display_name="The Rusty Anchor"),),
    )
    result, _ = _produce([document], extraction)
    assert result.changeset is not None
    kinds = [operation.kind for operation in result.changeset.operations]
    assert kinds == ["create_entity", "append_fact"]
    provenance_kinds = [item.operation_kind for item in result.operation_provenance]
    assert provenance_kinds == ["create_entity", "append_fact"]
    assert result.operation_provenance[0].candidate_ids == ("cand-1",)
    assert result.operation_provenance[1].claim_ids == ("c1",)


def test_zero_operations_yields_no_changes_without_preflight() -> None:
    document = make_document("npc-aria", name="Aria")
    result, repository = _produce([document], make_extraction())
    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert result.changeset is None
    assert result.changeset_fingerprint is None
    assert repository.list_entities_calls == 1  # binding only, no preflight
    assert repository.writes == []


def test_preflight_failure_fails_closed() -> None:
    document = make_document("npc-aria", name="Aria")
    prepared = make_prepared([document])
    accepted = _accept(
        prepared,
        _candidate_extraction(
            make_candidate(candidate_id="cand-1", display_name="The Rusty Anchor")
        ),
    )
    allocated = allocate_candidate_entity_id("S001", EntityType.LOCATION, "The Rusty Anchor")
    existing = make_document(allocated, entity_type=EntityType.LOCATION, name="Occupied")

    class SequencedRepository(FakeReadOnlyRepository):
        def __init__(self):
            super().__init__([document])

        def list_entities(self, entity_type=None):
            self.list_entities_calls += 1
            if self.list_entities_calls == 1:
                return [document]
            return [document, existing]

    repository = SequencedRepository()
    with pytest.raises(PostSessionChangeError) as excinfo:
        produce_post_session_changeset(
            prepared, accepted, attempt_id=ATTEMPT_A, repository=repository
        )

    assert excinfo.value.reason is PostSessionChangeFailureReason.CHANGESET_PREFLIGHT_FAILED


def test_result_rejects_inconsistent_outcome() -> None:
    with pytest.raises(ValueError):
        PostSessionChangePlanResult(
            outcome=PostSessionChangeOutcome.PROPOSAL,
            provenance=None,  # type: ignore[arg-type]
            attempt_id=ATTEMPT_A,
        )
    fingerprint = ChangeSetFingerprint(algorithm="sha256", digest="0" * 64)
    with pytest.raises(ValueError):
        PostSessionChangePlanResult(
            outcome=PostSessionChangeOutcome.NO_CHANGES,
            provenance=None,  # type: ignore[arg-type]
            attempt_id=ATTEMPT_A,
            changeset_fingerprint=fingerprint,
        )
