"""S11-03 extraction test helpers (test-only, no pytest import).

Provides a deterministic fake application-protocol model and builders for
``PreparedPostSessionInput`` and extraction objects so extraction policy tests
run with no Ollama and no Vault.
"""

from __future__ import annotations

from collections.abc import Sequence

from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_eligibility import (
    EligibilityReason,
    EligibilityResult,
)
from dnd_assistant.application.post_session_extraction import (
    PostSessionExtractionRequest,
)
from dnd_assistant.application.post_session_identity import (
    POST_SESSION_PROCESSOR_VERSION,
    POST_SESSION_PROMPT_VERSION,
    compute_input_fingerprint,
)
from dnd_assistant.domain.post_session import (
    PreparedCalendarProjection,
    PreparedContextProjection,
    PreparedEntityProjection,
    PreparedInputIdentity,
    PreparedRawEvent,
    PreparedSessionProjection,
)
from dnd_assistant.domain.post_session_extraction import (
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
from tests.unit.post_session.helpers import BASE_END, BASE_START

# ── Prepared input ────────────────────────────────────────────────────────


def make_prepared_input(
    *,
    session_id: str = "S001",
    event_ids: Sequence[str] = ("evt_001",),
    entity_bindings: Sequence[tuple[str, EntityType]] = (("npc-aria", EntityType.NPC),),
    context_text: str = "context: event id=evt_001 entity id=npc-aria",
) -> PreparedPostSessionInput:
    """Build an accepted prepared input without touching a Vault."""
    raw_events = tuple(
        PreparedRawEvent(
            event_id=event_id,
            real_time=BASE_START,
            world_tick=150,
            type="note",
        )
        for event_id in event_ids
    )
    entities = tuple(
        PreparedEntityProjection(
            id=entity_id,
            type=entity_type,
            revision=1,
            name=entity_id,
            status="alive",
            visibility=Visibility.PLAYER,
            knowledge_status=KnowledgeStatus.CONFIRMED,
        )
        for entity_id, entity_type in entity_bindings
    )
    touched = tuple(entity_id for entity_id, _ in entity_bindings)
    session = PreparedSessionProjection(
        id=session_id,
        status="completed",
        real_started_at=BASE_START,
        real_finished_at=BASE_END,
        world_tick_start=100,
        world_tick_end=200,
        revision=1,
        touched_entities=touched,
    )
    identity = PreparedInputIdentity(
        processor_version=POST_SESSION_PROCESSOR_VERSION,
        prompt_version=POST_SESSION_PROMPT_VERSION,
        session=session,
        raw_events=raw_events,
        entities=entities,
        context=PreparedContextProjection(text=context_text),
        calendar=PreparedCalendarProjection(world_tick_start=100, world_tick_end=200),
    )
    eligibility = EligibilityResult(
        eligible=True,
        reason=EligibilityReason.ELIGIBLE,
        session_id=session_id,
        session_revision=1,
        touched_entity_ids=touched,
    )
    return PreparedPostSessionInput(
        identity=identity,
        fingerprint=compute_input_fingerprint(identity),
        eligibility=eligibility,
    )


# ── Extraction builders ───────────────────────────────────────────────────


def make_mention(
    *,
    mention_id: str = "m1",
    text: str = "Aria",
    entity_type: EntityType = EntityType.NPC,
    candidate_entity_id: str | None = None,
    evidence_event_ids: tuple[str, ...] = ("evt_001",),
) -> ExtractedEntityMention:
    return ExtractedEntityMention(
        mention_id=mention_id,
        text=text,
        entity_type=entity_type,
        candidate_entity_id=candidate_entity_id,
        evidence_event_ids=evidence_event_ids,
    )


def make_claim(
    *,
    claim_id: str = "c1",
    text: str = "Aria arrived at the tavern.",
    evidence_event_ids: tuple[str, ...] = ("evt_001",),
    entity_mentions: tuple[ExtractedEntityMention, ...] = (),
    kind: ClaimKind = ClaimKind.FACT,
    visibility_hint: ExtractionVisibilityHint = ExtractionVisibilityHint.UNCERTAIN,
    knowledge_hint: ExtractionKnowledgeHint = ExtractionKnowledgeHint.UNCERTAIN,
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        kind=kind,
        text=text,
        evidence_event_ids=evidence_event_ids,
        entity_mentions=entity_mentions,
        visibility_hint=visibility_hint,
        knowledge_hint=knowledge_hint,
    )


def make_candidate(
    *,
    candidate_id: str = "n1",
    display_name: str = "The Rusty Anchor",
    entity_type: EntityType = EntityType.LOCATION,
    evidence_event_ids: tuple[str, ...] = ("evt_001",),
) -> ExtractedEntityCandidate:
    return ExtractedEntityCandidate(
        candidate_id=candidate_id,
        display_name=display_name,
        entity_type=entity_type,
        evidence_event_ids=evidence_event_ids,
    )


def make_extraction(
    *,
    claims: tuple[ExtractedClaim, ...] = (),
    entity_candidates: tuple[ExtractedEntityCandidate, ...] = (),
    schema_version: int = POST_SESSION_EXTRACTION_SCHEMA_VERSION,
) -> PostSessionExtraction:
    return PostSessionExtraction(
        schema_version=schema_version,
        claims=claims,
        entity_candidates=entity_candidates,
    )


# ── Deterministic fake model ──────────────────────────────────────────────


class FakePostSessionExtractionModel:
    """Deterministic application-protocol implementation (no provider)."""

    def __init__(
        self,
        extraction: PostSessionExtraction | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._extraction = extraction
        self._error = error
        self.requests: list[PostSessionExtractionRequest] = []

    def extract(self, request: PostSessionExtractionRequest) -> PostSessionExtraction:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        assert self._extraction is not None, "fake model has neither extraction nor error"
        return self._extraction
