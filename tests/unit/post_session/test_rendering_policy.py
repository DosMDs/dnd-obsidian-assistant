"""S11-04 deterministic Summary/Recap visibility policy tests (no model, no Vault)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    ExtractionProvenance,
    PostSessionExtractionError,
)
from dnd_assistant.application.post_session_identity import POST_SESSION_PROMPT_VERSION
from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RecapRenderRequest,
    RenderedPostSessionArtifact,
    RenderingFailureReason,
    SummaryRenderRequest,
    build_recap_render_request,
    build_summary_render_request,
    generate_recap,
    generate_summary,
    serialize_recap_request,
    serialize_summary_request,
)
from dnd_assistant.application.post_session_visibility import (
    RecapExclusionReason,
    SummaryEntityRef,
    SummaryExclusionReason,
    project_recap,
    project_summary,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome
from dnd_assistant.domain.post_session_extraction import (
    ExtractionKnowledgeHint,
    ExtractionVisibilityHint,
)
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.prompts.post_session_recap_v1 import POST_SESSION_RECAP_PROMPT_ID
from dnd_assistant.prompts.post_session_summary_v1 import POST_SESSION_SUMMARY_PROMPT_ID
from tests.unit.post_session.extraction_helpers import (
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.rendering_helpers import (
    ALL_SECRET_CANARIES,
    DM_SECRET_CANARY_CANDIDATE,
    DM_SECRET_CANARY_CLAIM_TEXT,
    DM_SECRET_CANARY_ENTITY_BODY,
    SYSTEM_SECRET_CANARY_ENTITY_BODY,
    UNRESOLVED_SECRET_CANARY_MENTION,
    FakePostSessionRenderingModel,
    make_accepted,
    make_prepared_input,
    make_render_output,
    prepared_entity,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


def _prepared():
    return make_prepared_input(
        entities=(
            prepared_entity("npc-aria", name="Aria"),
            prepared_entity(
                "npc-hidden",
                name="The Hidden One",
                visibility=Visibility.DM,
                body=DM_SECRET_CANARY_ENTITY_BODY,
            ),
            prepared_entity(
                "npc-system",
                name="System Entity",
                visibility=Visibility.SYSTEM,
                body=SYSTEM_SECRET_CANARY_ENTITY_BODY,
            ),
            prepared_entity("loc-grayford", EntityType.LOCATION, name="Grayford"),
        )
    )


def _mention(mention_id: str, entity_id: str | None = None, text: str = "Aria"):
    return make_mention(mention_id=mention_id, candidate_entity_id=entity_id, text=text)


def _accepted(prepared, claims, candidates=()):
    return make_accepted(
        prepared,
        make_extraction(claims=tuple(claims), entity_candidates=tuple(candidates)),
    )


def _player_claim(claim_id="c_player", text="Aria arrived at the tavern."):
    return make_claim(
        claim_id=claim_id,
        text=text,
        entity_mentions=(_mention(f"m_{claim_id}", "npc-aria"),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )


# ── Recap eligibility ─────────────────────────────────────────────────────


def test_recap_accepts_player_claim_with_player_binding() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))

    result = project_recap(prepared, accepted)

    assert result.included_claim_ids == ("c_player",)
    assert [entity.entity_id for entity in result.entities] == ["npc-aria"]
    assert result.excluded == ()


def test_recap_excludes_dm_entity_whole_claim() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_dm",
        text=DM_SECRET_CANARY_CLAIM_TEXT,
        entity_mentions=(_mention("m_c_dm", "npc-hidden"),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    assert result.included_claim_ids == ()
    assert result.entities == ()
    assert result.excluded[0].reason is RecapExclusionReason.REFERENCES_NON_PLAYER_ENTITY
    request = build_recap_render_request(prepared, result)
    serialized = serialize_recap_request(request)
    assert DM_SECRET_CANARY_CLAIM_TEXT not in serialized
    assert DM_SECRET_CANARY_ENTITY_BODY not in serialized
    assert "npc-hidden" not in serialized


def test_recap_excludes_system_entity_whole_claim() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_system",
        entity_mentions=(_mention("m_c_system", "npc-system"),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    assert result.excluded[0].reason is RecapExclusionReason.REFERENCES_NON_PLAYER_ENTITY
    serialized = serialize_recap_request(build_recap_render_request(prepared, result))
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in serialized
    assert "npc-system" not in serialized


def test_recap_excludes_unresolved_reference_claim() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_unresolved",
        entity_mentions=(_mention("m_c_unresolved", None, UNRESOLVED_SECRET_CANARY_MENTION),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    assert result.excluded[0].reason is RecapExclusionReason.CONTAINS_UNRESOLVED_REFERENCE
    serialized = serialize_recap_request(build_recap_render_request(prepared, result))
    assert UNRESOLVED_SECRET_CANARY_MENTION not in serialized


def test_recap_excludes_non_player_and_uncertain_hints() -> None:
    prepared = _prepared()
    claims = (
        make_claim(
            claim_id="c_dm_hint",
            entity_mentions=(_mention("m_c_dm_hint", "npc-aria"),),
            visibility_hint=ExtractionVisibilityHint.DM,
        ),
        make_claim(
            claim_id="c_uncertain",
            entity_mentions=(_mention("m_c_uncertain", "npc-aria"),),
            visibility_hint=ExtractionVisibilityHint.UNCERTAIN,
        ),
    )
    accepted = _accepted(prepared, claims)

    result = project_recap(prepared, accepted)

    assert result.included_claim_ids == ()
    assert {exclusion.reason for exclusion in result.excluded} == {
        RecapExclusionReason.VISIBILITY_HINT_NOT_PLAYER
    }


def test_recap_excludes_no_entity_player_claim() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_no_entity",
        text="Something happened.",
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    assert result.included_claim_ids == ()
    assert result.excluded[0].reason is RecapExclusionReason.NO_CANONICAL_PLAYER_SAFE_EVIDENCE


def test_canonical_visibility_outranks_model_hint_player_hint_dm_entity() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_player_hint_dm_entity",
        entity_mentions=(_mention("m_player_hint_dm", "npc-hidden"),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    assert result.excluded[0].reason is RecapExclusionReason.REFERENCES_NON_PLAYER_ENTITY


def test_player_entity_with_dm_hint_is_excluded() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_dm_hint_player_entity",
        entity_mentions=(_mention("m_dm_hint_player", "npc-aria"),),
        visibility_hint=ExtractionVisibilityHint.DM,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    assert result.excluded[0].reason is RecapExclusionReason.VISIBILITY_HINT_NOT_PLAYER


def test_recap_excludes_candidates() -> None:
    prepared = _prepared()
    accepted = _accepted(
        prepared,
        (_player_claim(),),
        candidates=(make_candidate(candidate_id="cand1", display_name=DM_SECRET_CANARY_CANDIDATE),),
    )

    result = project_recap(prepared, accepted)

    request = build_recap_render_request(prepared, result)
    assert "candidate" not in request.model_dump_json()
    assert DM_SECRET_CANARY_CANDIDATE not in serialize_recap_request(request)


def test_recap_request_type_has_no_unsafe_fields() -> None:
    fields = set(RecapRenderRequest.model_fields)
    assert fields.isdisjoint(
        {
            "unresolved_references",
            "entity_candidates",
            "body_projection",
            "context_text",
            "extraction",
        }
    )
    assert "claims" in fields
    assert "entities" in fields


def test_knowledge_hint_never_becomes_canonical_knowledge_status() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_rumor",
        entity_mentions=(_mention("m_c_rumor", "npc-aria"),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
        knowledge_hint=ExtractionKnowledgeHint.RUMOR,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_recap(prepared, accepted)

    projection = result.claims[0]
    assert isinstance(projection.knowledge_hint, ExtractionKnowledgeHint)
    assert projection.knowledge_hint is ExtractionKnowledgeHint.RUMOR
    assert not any(isinstance(value, KnowledgeStatus) for value in projection.model_dump().values())


# ── Summary projection ────────────────────────────────────────────────────


def test_summary_includes_player_and_dm_claims() -> None:
    prepared = _prepared()
    claims = (
        _player_claim("c_player"),
        make_claim(
            claim_id="c_dm",
            text=DM_SECRET_CANARY_CLAIM_TEXT,
            entity_mentions=(_mention("m_c_dm", "npc-hidden"),),
            visibility_hint=ExtractionVisibilityHint.DM,
        ),
    )
    accepted = _accepted(prepared, claims)

    result = project_summary(prepared, accepted)

    assert set(result.included_claim_ids) == {"c_player", "c_dm"}
    serialized = serialize_summary_request(build_summary_render_request(prepared, result))
    assert DM_SECRET_CANARY_CLAIM_TEXT in serialized


def test_summary_excludes_system_entity_claim_and_canary() -> None:
    prepared = _prepared()
    claim = make_claim(
        claim_id="c_system",
        text="System-level fact.",
        entity_mentions=(_mention("m_c_system", "npc-system"),),
        visibility_hint=ExtractionVisibilityHint.DM,
    )
    accepted = _accepted(prepared, (claim,))

    result = project_summary(prepared, accepted)

    assert result.included_claim_ids == ()
    assert result.excluded[0].reason is SummaryExclusionReason.REFERENCES_SYSTEM_ENTITY
    serialized = serialize_summary_request(build_summary_render_request(prepared, result))
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in serialized
    assert "npc-system" not in serialized
    assert "System Entity" not in serialized


def test_summary_carries_unresolved_and_candidates_separately() -> None:
    prepared = _prepared()
    claims = (
        _player_claim("c_player"),
        make_claim(
            claim_id="c_unresolved",
            entity_mentions=(_mention("m_c_unresolved", None, UNRESOLVED_SECRET_CANARY_MENTION),),
            visibility_hint=ExtractionVisibilityHint.UNCERTAIN,
        ),
    )
    candidates = (make_candidate(candidate_id="cand1", display_name=DM_SECRET_CANARY_CANDIDATE),)
    accepted = _accepted(prepared, claims, candidates=candidates)

    result = project_summary(prepared, accepted)

    assert len(result.unresolved_references) == 1
    assert result.unresolved_references[0].text == UNRESOLVED_SECRET_CANARY_MENTION
    assert [candidate.candidate_id for candidate in result.entity_candidates] == ["cand1"]
    serialized = serialize_summary_request(build_summary_render_request(prepared, result))
    assert UNRESOLVED_SECRET_CANARY_MENTION in serialized
    assert DM_SECRET_CANARY_CANDIDATE in serialized


def test_summary_entity_ref_structurally_rejects_system() -> None:
    with pytest.raises(ValueError):
        SummaryEntityRef(
            entity_id="npc-system",
            name="System Entity",
            entity_type=EntityType.NPC,
            visibility=Visibility.SYSTEM,
        )


# ── Provenance binding ────────────────────────────────────────────────────


def test_provenance_mismatch_fails_before_model_call() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    tampered = replace(
        accepted,
        provenance=replace(accepted.provenance, prompt_version="tampered-prompt"),
    )
    fake = FakePostSessionRenderingModel(make_render_output())

    with pytest.raises(PostSessionRenderingError) as exc_info:
        generate_summary(fake, prepared, tampered)

    assert exc_info.value.reason is RenderingFailureReason.PROVENANCE_MISMATCH
    assert fake.requests == []


def test_extraction_prompt_version_mismatch_regression() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    assert accepted.provenance.prompt_version == POST_SESSION_PROMPT_VERSION
    tampered = replace(
        accepted,
        provenance=replace(accepted.provenance, prompt_version="post-session-extraction-vX"),
    )
    fake = FakePostSessionRenderingModel(make_render_output())

    with pytest.raises(PostSessionRenderingError) as exc_info:
        generate_recap(fake, prepared, tampered)

    assert exc_info.value.reason is RenderingFailureReason.PROVENANCE_MISMATCH
    assert fake.requests == []


def test_provenance_fingerprint_mismatch_fails() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    other = make_prepared_input(
        session_id="S001",
        entities=prepared.identity.entities,
        context_text="different prepared context",
    )
    tampered = replace(
        accepted,
        provenance=ExtractionProvenance(
            session_ref=accepted.provenance.session_ref,
            input_fingerprint=other.fingerprint,
            processor_version=accepted.provenance.processor_version,
            prompt_version=accepted.provenance.prompt_version,
            extraction_schema_version=accepted.provenance.extraction_schema_version,
        ),
    )
    fake = FakePostSessionRenderingModel(make_render_output())

    with pytest.raises(PostSessionRenderingError) as exc_info:
        generate_recap(fake, prepared, tampered)

    assert exc_info.value.reason is RenderingFailureReason.PROVENANCE_MISMATCH
    assert fake.requests == []


# ── EMPTY outcome ─────────────────────────────────────────────────────────


def test_zero_safe_claims_returns_empty_without_model_call() -> None:
    prepared = _prepared()
    dm_claim = make_claim(
        claim_id="c_dm",
        entity_mentions=(_mention("m_c_dm", "npc-hidden"),),
        visibility_hint=ExtractionVisibilityHint.PLAYER,
    )
    accepted = _accepted(prepared, (dm_claim,))
    fake = FakePostSessionRenderingModel(make_render_output())

    result = generate_recap(fake, prepared, accepted)

    assert result.outcome is RenderOutcome.EMPTY
    assert result.content is None
    assert fake.requests == []


def test_rendered_artifact_requires_content_and_empty_requires_none() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    rendered = generate_recap(
        FakePostSessionRenderingModel(make_render_output()), prepared, accepted
    )
    assert rendered.outcome is RenderOutcome.RENDERED
    assert isinstance(rendered.content, str) and rendered.content

    with pytest.raises(ValueError):
        RenderedPostSessionArtifact(rendered.provenance, RenderOutcome.RENDERED, None)
    with pytest.raises(ValueError):
        RenderedPostSessionArtifact(rendered.provenance, RenderOutcome.EMPTY, "")


# ── Separate request architecture ─────────────────────────────────────────


def test_summary_and_recap_use_separate_requests() -> None:
    prepared = _prepared()
    claims = (
        _player_claim("c_player"),
        make_claim(
            claim_id="c_dm",
            text=DM_SECRET_CANARY_CLAIM_TEXT,
            entity_mentions=(_mention("m_c_dm", "npc-hidden"),),
            visibility_hint=ExtractionVisibilityHint.DM,
        ),
    )
    accepted = _accepted(prepared, claims)
    fake = FakePostSessionRenderingModel(make_render_output())

    generate_summary(fake, prepared, accepted)
    generate_recap(fake, prepared, accepted)

    assert [type(request) for request in fake.requests] == [
        SummaryRenderRequest,
        RecapRenderRequest,
    ]
    recap_request = fake.requests[1]
    assert isinstance(recap_request, RecapRenderRequest)
    assert DM_SECRET_CANARY_CLAIM_TEXT not in serialize_recap_request(recap_request)


def test_render_prompt_versions_are_artifact_specific() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    summary_request = build_summary_render_request(prepared, project_summary(prepared, accepted))
    recap_request = build_recap_render_request(prepared, project_recap(prepared, accepted))

    assert summary_request.render_prompt_version == POST_SESSION_SUMMARY_PROMPT_ID
    assert recap_request.render_prompt_version == POST_SESSION_RECAP_PROMPT_ID
    assert summary_request.render_prompt_version != recap_request.render_prompt_version
    assert POST_SESSION_SUMMARY_PROMPT_ID != POST_SESSION_PROMPT_VERSION
    assert POST_SESSION_RECAP_PROMPT_ID != POST_SESSION_PROMPT_VERSION


def test_rendering_does_not_alter_input_fingerprint() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    before = prepared.fingerprint
    fake = FakePostSessionRenderingModel(make_render_output())

    generate_summary(fake, prepared, accepted)
    generate_recap(fake, prepared, accepted)

    assert prepared.fingerprint == before
    assert accepted.provenance.input_fingerprint == before


# ── Security canaries on the actual request ───────────────────────────────


def _canary_scenario(prepared):
    claims = (
        _player_claim("c_player"),
        make_claim(
            claim_id="c_dm",
            text=DM_SECRET_CANARY_CLAIM_TEXT,
            entity_mentions=(_mention("m_c_dm", "npc-hidden"),),
            visibility_hint=ExtractionVisibilityHint.PLAYER,
        ),
        make_claim(
            claim_id="c_system",
            entity_mentions=(_mention("m_c_system", "npc-system"),),
            visibility_hint=ExtractionVisibilityHint.PLAYER,
        ),
        make_claim(
            claim_id="c_unresolved",
            entity_mentions=(_mention("m_c_unresolved", None, UNRESOLVED_SECRET_CANARY_MENTION),),
            visibility_hint=ExtractionVisibilityHint.PLAYER,
        ),
        make_claim(
            claim_id="c_no_entity",
            visibility_hint=ExtractionVisibilityHint.PLAYER,
        ),
    )
    candidates = (make_candidate(candidate_id="cand1", display_name=DM_SECRET_CANARY_CANDIDATE),)
    return _accepted(prepared, claims, candidates=candidates)


def test_recap_request_contains_no_hidden_canary() -> None:
    prepared = _prepared()
    accepted = _canary_scenario(prepared)
    recap = project_recap(prepared, accepted)
    serialized = serialize_recap_request(build_recap_render_request(prepared, recap))

    assert recap.included_claim_ids == ("c_player",)
    for canary in ALL_SECRET_CANARIES:
        assert canary not in serialized


def test_recap_echo_render_is_safe() -> None:
    prepared = _prepared()
    accepted = _canary_scenario(prepared)
    fake = FakePostSessionRenderingModel(echo=True)

    result = generate_recap(fake, prepared, accepted)

    assert result.outcome is RenderOutcome.RENDERED
    assert result.content is not None
    for canary in ALL_SECRET_CANARIES:
        assert canary not in result.content


def test_summary_request_dm_canary_present_system_canary_absent() -> None:
    prepared = _prepared()
    accepted = _canary_scenario(prepared)
    summary = project_summary(prepared, accepted)
    serialized = serialize_summary_request(build_summary_render_request(prepared, summary))

    assert DM_SECRET_CANARY_CLAIM_TEXT in serialized
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in serialized
    assert "npc-system" not in serialized


def test_diagnostics_do_not_expose_hidden_text() -> None:
    prepared = _prepared()
    accepted = _canary_scenario(prepared)

    recap = project_recap(prepared, accepted)
    assert all(canary not in repr(recap.excluded) for canary in ALL_SECRET_CANARIES)
    summary = project_summary(prepared, accepted)
    assert all(canary not in repr(summary.excluded) for canary in ALL_SECRET_CANARIES)


def test_recap_projects_no_secret_entity_metadata() -> None:
    prepared = _prepared()
    accepted = _canary_scenario(prepared)
    recap = project_recap(prepared, accepted)

    assert [entity.entity_id for entity in recap.entities] == ["npc-aria"]
    assert all(canary not in repr(recap.entities) for canary in ALL_SECRET_CANARIES)


# ── Error propagation ─────────────────────────────────────────────────────


def test_model_error_propagates_from_generate_recap() -> None:
    prepared = _prepared()
    accepted = _accepted(prepared, (_player_claim(),))
    boom = PostSessionExtractionError(
        ExtractionFailureReason.MODEL_TIMEOUT,
        "timed out",
    )
    fake = FakePostSessionRenderingModel(error=boom)

    with pytest.raises(PostSessionExtractionError):
        generate_recap(fake, prepared, accepted)
