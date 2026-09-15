"""S11-03 structured extraction domain schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain.post_session_extraction import (
    MAX_CLAIM_EVIDENCE_REFS,
    MAX_CLAIM_TEXT_CHARS,
    MAX_CLAIMS,
    POST_SESSION_EXTRACTION_SCHEMA_VERSION,
    ClaimKind,
    ExtractedClaim,
    ExtractedEntityCandidate,
    ExtractedEntityMention,
    ExtractionKnowledgeHint,
    ExtractionVisibilityHint,
    PostSessionExtraction,
)
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility


def _claim(**overrides: object) -> ExtractedClaim:
    data: dict[str, object] = {
        "claim_id": "c1",
        "text": "Aria arrived.",
        "evidence_event_ids": ("evt_001",),
    }
    data.update(overrides)
    return ExtractedClaim(**data)  # type: ignore[arg-type]


def test_schema_version_is_required() -> None:
    with pytest.raises(ValidationError):
        PostSessionExtraction(claims=())  # type: ignore[call-arg]


def test_empty_extraction_is_valid() -> None:
    result = PostSessionExtraction(schema_version=POST_SESSION_EXTRACTION_SCHEMA_VERSION)
    assert result.claims == ()
    assert result.entity_candidates == ()


def test_evidence_is_mandatory_per_claim() -> None:
    with pytest.raises(ValidationError):
        _claim(evidence_event_ids=())


def test_evidence_is_mandatory_per_mention() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntityMention(
            mention_id="m1",
            text="Aria",
            entity_type=EntityType.NPC,
            evidence_event_ids=(),
        )


def test_claim_text_bound_enforced() -> None:
    with pytest.raises(ValidationError):
        _claim(text="x" * (MAX_CLAIM_TEXT_CHARS + 1))


def test_evidence_refs_per_claim_bound_enforced() -> None:
    with pytest.raises(ValidationError):
        _claim(evidence_event_ids=tuple(f"e{i}" for i in range(MAX_CLAIM_EVIDENCE_REFS + 1)))


def test_claims_bound_enforced() -> None:
    claims = tuple(_claim(claim_id=f"c{i}") for i in range(MAX_CLAIMS + 1))
    with pytest.raises(ValidationError):
        PostSessionExtraction(schema_version=POST_SESSION_EXTRACTION_SCHEMA_VERSION, claims=claims)


def test_unsupported_entity_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntityCandidate(
            candidate_id="n1",
            display_name="Faction X",
            entity_type="faction",  # type: ignore[arg-type]
            evidence_event_ids=("evt_001",),
        )


def test_change_set_shaped_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _claim(expected_revision=3)


def test_operation_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _claim(operations=())


def test_hints_are_distinct_from_canonical_enums() -> None:
    assert not issubclass(ExtractionVisibilityHint, Visibility)
    assert not issubclass(ExtractionKnowledgeHint, KnowledgeStatus)
    assert "player" in {h.value for h in ExtractionVisibilityHint}
    assert "confirmed" in {h.value for h in ExtractionKnowledgeHint}


def test_claim_kind_values() -> None:
    assert {k.value for k in ClaimKind} == {"event", "fact", "relationship", "other"}


def test_mention_candidate_entity_id_is_optional() -> None:
    mention = ExtractedEntityMention(
        mention_id="m1",
        text="Aria",
        entity_type=EntityType.NPC,
        evidence_event_ids=("evt_001",),
    )
    assert mention.candidate_entity_id is None
