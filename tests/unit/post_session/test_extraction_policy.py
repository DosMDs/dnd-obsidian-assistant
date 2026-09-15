"""S11-03 extraction protocol, request-binding and semantic validation tests."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from dnd_assistant.application.post_session_extraction import (
    AcceptedPostSessionExtraction,
    ExtractionFailureReason,
    ModelExecutionIdentity,
    PostSessionExtractionError,
    PostSessionExtractionModel,
    UnresolvedReferenceReason,
    build_post_session_extraction_request,
    run_post_session_extraction,
    validate_post_session_extraction,
)
from dnd_assistant.domain.post_session import FailureCategory
from dnd_assistant.domain.post_session_extraction import (
    ClaimKind,
    ExtractedClaim,
    ExtractedEntityCandidate,
    ExtractionKnowledgeHint,
    ExtractionVisibilityHint,
    PostSessionExtraction,
)
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
    make_prepared_input,
)


def _accepted(
    extraction: PostSessionExtraction,
    prepared=None,
):
    model = FakePostSessionExtractionModel(extraction)
    return run_post_session_extraction(model, prepared or make_prepared_input()), model


# ── Protocol / fake ───────────────────────────────────────────────────────


def test_fake_implements_application_protocol() -> None:
    fake = FakePostSessionExtractionModel(make_extraction())

    def _consume(model: PostSessionExtractionModel) -> str:
        return type(model).__name__

    assert _consume(fake) == "FakePostSessionExtractionModel"


def test_policy_runs_without_provider() -> None:
    accepted, model = _accepted(make_extraction(claims=(make_claim(),)))
    assert accepted.validated.extraction.claims[0].claim_id == "c1"
    assert len(model.requests) == 1


def test_structurally_invalid_request_performs_no_model_call() -> None:
    fake = FakePostSessionExtractionModel(make_extraction())
    prepared = make_prepared_input(context_text="   ")
    with pytest.raises(PostSessionExtractionError) as exc_info:
        run_post_session_extraction(fake, prepared)
    assert exc_info.value.reason is ExtractionFailureReason.INVALID_REQUEST
    assert fake.requests == []


# ── Trusted request construction (Correction 1) ───────────────────────────


def test_request_is_derived_from_prepared_input() -> None:
    prepared = make_prepared_input(
        event_ids=("evt_001", "evt_002"),
        entity_bindings=(("npc-aria", EntityType.NPC), ("loc-grayford", EntityType.LOCATION)),
        context_text="derived context",
    )
    fake = FakePostSessionExtractionModel(make_extraction())
    run_post_session_extraction(fake, prepared)

    request = fake.requests[0]
    assert request.context_text == prepared.identity.context.text == "derived context"
    assert request.expected_event_ids == ("evt_001", "evt_002")
    assert request.input_fingerprint == prepared.fingerprint
    assert request.session_ref == prepared.identity.session.id
    assert request.processor_version == prepared.identity.processor_version
    assert request.prompt_version == prepared.identity.prompt_version
    assert {(b.entity_id, b.entity_type) for b in request.expected_entity_bindings} == {
        ("npc-aria", EntityType.NPC),
        ("loc-grayford", EntityType.LOCATION),
    }


def test_public_entrypoint_does_not_accept_a_request() -> None:
    params = inspect.signature(run_post_session_extraction).parameters
    assert set(params) == {"model", "prepared", "model_identity"}


def test_fabricated_request_cannot_substitute_run_binding() -> None:
    prepared = make_prepared_input(
        event_ids=("evt_001",),
        entity_bindings=(("npc-aria", EntityType.NPC),),
    )
    # A model fabricated against a separately built request still fails when
    # the public policy derives the real request internally.
    fabricated = build_post_session_extraction_request(make_prepared_input(event_ids=("evt_999",)))
    fake = FakePostSessionExtractionModel(
        make_extraction(claims=(make_claim(evidence_event_ids=("evt_999",)),))
    )
    with pytest.raises(PostSessionExtractionError) as exc_info:
        run_post_session_extraction(fake, prepared)
    assert exc_info.value.reason is ExtractionFailureReason.INVALID_EVIDENCE_REFERENCE
    assert fabricated.expected_event_ids == ("evt_999",)


def test_unsupported_schema_version_rejected_before_model_call() -> None:
    fake = FakePostSessionExtractionModel(make_extraction())
    with pytest.raises(PostSessionExtractionError) as exc_info:
        build_post_session_extraction_request(make_prepared_input(), extraction_schema_version=999)
    assert exc_info.value.reason is ExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION
    assert fake.requests == []


# ── Structured output ─────────────────────────────────────────────────────


def test_valid_extraction_accepted() -> None:
    accepted, _ = _accepted(
        make_extraction(
            claims=(make_claim(),),
            entity_candidates=(make_candidate(),),
        )
    )
    assert isinstance(accepted, AcceptedPostSessionExtraction)
    assert accepted.provenance.session_ref == "S001"


class _WrongTypeModel:
    def extract(self, request: object) -> Any:
        return object()


def test_non_extraction_output_rejected() -> None:
    prepared = make_prepared_input()
    with pytest.raises(PostSessionExtractionError) as exc_info:
        run_post_session_extraction(_WrongTypeModel(), prepared)
    assert exc_info.value.reason is ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT


def test_unknown_model_schema_version_rejected() -> None:
    with pytest.raises(PostSessionExtractionError) as exc_info:
        _accepted(make_extraction(schema_version=999))
    assert exc_info.value.reason is ExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION


def test_unsupported_candidate_type_rejected() -> None:
    bad_candidate = ExtractedEntityCandidate.model_construct(
        candidate_id="n1",
        display_name="Faction X",
        entity_type="faction",
        evidence_event_ids=("evt_001",),
        attributes=(),
        summary=None,
    )
    extraction = PostSessionExtraction.model_construct(
        schema_version=1, claims=(), entity_candidates=(bad_candidate,)
    )
    request = build_post_session_extraction_request(make_prepared_input())
    with pytest.raises(PostSessionExtractionError) as exc_info:
        validate_post_session_extraction(extraction, request)
    assert exc_info.value.reason is ExtractionFailureReason.UNSUPPORTED_ENTITY_TYPE


def test_output_total_bounds_enforced() -> None:
    big = "x" * 3000
    claims = tuple(
        ExtractedClaim.model_construct(
            claim_id=f"c{i}",
            kind=ClaimKind.FACT,
            text=big,
            evidence_event_ids=("evt_001",),
            entity_mentions=(),
            visibility_hint=ExtractionVisibilityHint.UNCERTAIN,
            knowledge_hint=ExtractionKnowledgeHint.UNCERTAIN,
        )
        for i in range(200)
    )
    extraction = PostSessionExtraction.model_construct(
        schema_version=1, claims=claims, entity_candidates=()
    )
    request = build_post_session_extraction_request(make_prepared_input())
    with pytest.raises(PostSessionExtractionError) as exc_info:
        validate_post_session_extraction(extraction, request)
    assert exc_info.value.reason is ExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED


# ── Evidence binding ──────────────────────────────────────────────────────


def test_valid_event_ids_accepted() -> None:
    prepared = make_prepared_input(event_ids=("evt_001", "evt_002"))
    accepted, _ = _accepted(
        make_extraction(claims=(make_claim(evidence_event_ids=("evt_001", "evt_002")),)),
        prepared,
    )
    assert accepted.validated.extraction.claims[0].evidence_event_ids == ("evt_001", "evt_002")


def test_unknown_evidence_event_id_rejected() -> None:
    accepted_error = None
    try:
        _accepted(make_extraction(claims=(make_claim(evidence_event_ids=("evt_nope",)),)))
    except PostSessionExtractionError as exc:
        accepted_error = exc
    assert accepted_error is not None
    assert accepted_error.reason is ExtractionFailureReason.INVALID_EVIDENCE_REFERENCE


def test_duplicate_evidence_ids_normalized() -> None:
    accepted, _ = _accepted(
        make_extraction(claims=(make_claim(evidence_event_ids=("evt_001", "evt_001")),))
    )
    assert accepted.validated.extraction.claims[0].evidence_event_ids == ("evt_001",)


def test_missing_required_evidence_rejected() -> None:
    with pytest.raises(ValueError):
        make_claim(evidence_event_ids=())


# ── Entity references ─────────────────────────────────────────────────────


def test_selected_existing_entity_id_accepted() -> None:
    prepared = make_prepared_input(entity_bindings=(("npc-aria", EntityType.NPC),))
    accepted, _ = _accepted(
        make_extraction(
            claims=(
                make_claim(
                    entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
                ),
            )
        ),
        prepared,
    )
    resolved = accepted.validated.resolved_mentions
    assert len(resolved) == 1
    assert resolved[0].entity_id == "npc-aria"
    assert resolved[0].entity_type is EntityType.NPC


def test_fabricated_entity_id_not_trusted() -> None:
    accepted, _ = _accepted(
        make_extraction(
            claims=(
                make_claim(
                    entity_mentions=(make_mention(candidate_entity_id="npc-fabricated"),),
                ),
            )
        )
    )
    assert accepted.validated.resolved_mentions == ()
    assert len(accepted.validated.unresolved_references) == 1
    assert (
        accepted.validated.unresolved_references[0].reason
        is UnresolvedReferenceReason.NOT_IN_PREPARED_INPUT
    )
    # The fabricated id is cleared from the sanitized extraction.
    assert accepted.validated.extraction.claims[0].entity_mentions[0].candidate_entity_id is None


def test_type_mismatch_not_trusted() -> None:
    prepared = make_prepared_input(entity_bindings=(("loc-grayford", EntityType.LOCATION),))
    accepted, _ = _accepted(
        make_extraction(
            claims=(
                make_claim(
                    entity_mentions=(
                        make_mention(
                            candidate_entity_id="loc-grayford",
                            entity_type=EntityType.NPC,
                        ),
                    ),
                ),
            )
        ),
        prepared,
    )
    assert accepted.validated.resolved_mentions == ()
    assert (
        accepted.validated.unresolved_references[0].reason
        is UnresolvedReferenceReason.TYPE_MISMATCH
    )


def test_new_entity_candidate_has_no_final_entity_id() -> None:
    candidate = make_candidate()
    assert not hasattr(candidate, "entity_id")
    assert not hasattr(candidate, "id")
    accepted, _ = _accepted(make_extraction(entity_candidates=(candidate,)))
    stored = accepted.validated.extraction.entity_candidates[0]
    assert stored.candidate_id == "n1"
    assert "entity_id" not in stored.model_dump()


def test_expected_revision_and_operations_not_expressible() -> None:
    with pytest.raises(ValueError):
        ExtractedClaim(
            claim_id="c1",
            text="x",
            evidence_event_ids=("evt_001",),
            expected_revision=2,  # type: ignore[call-arg]
        )
    with pytest.raises(ValueError):
        PostSessionExtraction(schema_version=1, operations=())  # type: ignore[call-arg]


# ── Trust ─────────────────────────────────────────────────────────────────


def test_visibility_hint_cannot_override_canonical_visibility() -> None:
    prepared = make_prepared_input(
        entity_bindings=(("npc-aria", EntityType.NPC),),
    )
    # Canonical entity is player-visible; the model claims it is DM-only.
    assert prepared.identity.entities[0].visibility is Visibility.PLAYER
    accepted, _ = _accepted(
        make_extraction(
            claims=(
                make_claim(
                    visibility_hint=ExtractionVisibilityHint.DM,
                    entity_mentions=(make_mention(candidate_entity_id="npc-aria"),),
                ),
            )
        ),
        prepared,
    )
    claim = accepted.validated.extraction.claims[0]
    assert claim.visibility_hint is ExtractionVisibilityHint.DM  # untrusted hint preserved
    # Canonical binding remains the prepared player entity; no canonical
    # Visibility is promoted from the hint.
    assert accepted.validated.resolved_mentions[0].entity_id == "npc-aria"
    assert prepared.identity.entities[0].visibility is Visibility.PLAYER


def test_model_confidence_is_not_canonical_knowledge_status() -> None:
    accepted, _ = _accepted(
        make_extraction(claims=(make_claim(knowledge_hint=ExtractionKnowledgeHint.RUMOR),))
    )
    hint = accepted.validated.extraction.claims[0].knowledge_hint
    assert isinstance(hint, ExtractionKnowledgeHint)
    assert not isinstance(hint, KnowledgeStatus)


def test_semantic_validator_runs_after_syntactic_parse() -> None:
    # The object is already a valid typed PostSessionExtraction (syntactic
    # parse succeeded) yet is rejected semantically.
    good = make_extraction(claims=(make_claim(evidence_event_ids=("evt_unknown",)),))
    assert isinstance(good, PostSessionExtraction)
    with pytest.raises(PostSessionExtractionError) as exc_info:
        _accepted(good)
    assert exc_info.value.reason is ExtractionFailureReason.INVALID_EVIDENCE_REFERENCE


# ── Error mapping / provenance ────────────────────────────────────────────


def test_failure_category_mapping() -> None:
    assert (
        PostSessionExtractionError(ExtractionFailureReason.MODEL_TIMEOUT, "t").to_failure_category()
        is FailureCategory.MODEL_TIMEOUT
    )
    assert (
        PostSessionExtractionError(
            ExtractionFailureReason.MODEL_UNAVAILABLE, "u"
        ).to_failure_category()
        is FailureCategory.MODEL_UNAVAILABLE
    )
    assert (
        PostSessionExtractionError(
            ExtractionFailureReason.INVALID_EVIDENCE_REFERENCE, "e"
        ).to_failure_category()
        is FailureCategory.INVALID_OUTPUT
    )


def test_provenance_carries_execution_identity() -> None:
    fake = FakePostSessionExtractionModel(make_extraction())
    accepted = run_post_session_extraction(
        fake,
        make_prepared_input(),
        model_identity=ModelExecutionIdentity(profile="heavy", model="qwen3", provider="ollama"),
    )
    assert accepted.provenance.model_profile == "heavy"
    assert accepted.provenance.model == "qwen3"
    assert accepted.provenance.provider == "ollama"
    assert accepted.provenance.extraction_schema_version == 1
