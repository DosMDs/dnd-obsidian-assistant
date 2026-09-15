"""S11-04 rendering test helpers (test-only, no pytest import).

Provides deterministic builders for prepared inputs with configurable
canonical entity visibility, accepted extractions (via the S11-03 fake
extraction model) and a capturing fake rendering model.
"""

from __future__ import annotations

from collections.abc import Sequence

from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_eligibility import (
    EligibilityReason,
    EligibilityResult,
)
from dnd_assistant.application.post_session_extraction import (
    AcceptedPostSessionExtraction,
    ModelExecutionIdentity,
    run_post_session_extraction,
)
from dnd_assistant.application.post_session_identity import (
    POST_SESSION_PROCESSOR_VERSION,
    POST_SESSION_PROMPT_VERSION,
    compute_input_fingerprint,
)
from dnd_assistant.application.post_session_rendering import (
    RecapRenderRequest,
    SummaryRenderRequest,
    serialize_recap_request,
    serialize_summary_request,
)
from dnd_assistant.domain.post_session import (
    PreparedCalendarProjection,
    PreparedContextProjection,
    PreparedEntityProjection,
    PreparedInputIdentity,
    PreparedRawEvent,
    PreparedSessionProjection,
)
from dnd_assistant.domain.post_session_artifacts import (
    POST_SESSION_RENDER_SCHEMA_VERSION,
    PostSessionRenderOutput,
)
from dnd_assistant.domain.post_session_extraction import PostSessionExtraction
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from tests.unit.post_session.extraction_helpers import FakePostSessionExtractionModel
from tests.unit.post_session.helpers import BASE_END, BASE_START

# ── Security canaries ─────────────────────────────────────────────────────

DM_SECRET_CANARY_ENTITY_BODY = "DM_SECRET_CANARY_ENTITY_BODY"
SYSTEM_SECRET_CANARY_ENTITY_BODY = "SYSTEM_SECRET_CANARY_ENTITY_BODY"
DM_SECRET_CANARY_CLAIM_TEXT = "DM_SECRET_CANARY_CLAIM_TEXT"
UNRESOLVED_SECRET_CANARY_MENTION = "UNRESOLVED_SECRET_CANARY_MENTION"
DM_SECRET_CANARY_CANDIDATE = "DM_SECRET_CANARY_CANDIDATE"

ALL_SECRET_CANARIES: tuple[str, ...] = (
    DM_SECRET_CANARY_ENTITY_BODY,
    SYSTEM_SECRET_CANARY_ENTITY_BODY,
    DM_SECRET_CANARY_CLAIM_TEXT,
    UNRESOLVED_SECRET_CANARY_MENTION,
    DM_SECRET_CANARY_CANDIDATE,
)


# ── Prepared input ────────────────────────────────────────────────────────


def prepared_entity(
    entity_id: str,
    entity_type: EntityType = EntityType.NPC,
    *,
    name: str | None = None,
    visibility: Visibility = Visibility.PLAYER,
    knowledge_status: KnowledgeStatus = KnowledgeStatus.CONFIRMED,
    body: str = "",
    revision: int = 1,
) -> PreparedEntityProjection:
    """Build a canonical prepared entity projection."""
    return PreparedEntityProjection(
        id=entity_id,
        type=entity_type,
        revision=revision,
        name=name or entity_id,
        status="alive",
        visibility=visibility,
        knowledge_status=knowledge_status,
        body_projection=body,
    )


def make_prepared_input(
    *,
    session_id: str = "S001",
    event_ids: Sequence[str] = ("evt_001",),
    entities: Sequence[PreparedEntityProjection] = (),
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
    entities_tuple = tuple(entities)
    touched = tuple(entity.id for entity in entities_tuple)
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
        entities=entities_tuple,
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


def make_accepted(
    prepared: PreparedPostSessionInput,
    extraction: PostSessionExtraction,
) -> AcceptedPostSessionExtraction:
    """Run the S11-03 pipeline with the fake extraction model."""
    fake = FakePostSessionExtractionModel(extraction)
    return run_post_session_extraction(
        fake,
        prepared,
        model_identity=ModelExecutionIdentity(profile="heavy", model="qwen3", provider="ollama"),
    )


# ── Fake rendering model ──────────────────────────────────────────────────


def make_render_output(body: str = "# Rendered\n\nBody.") -> PostSessionRenderOutput:
    """Build a valid bounded render output."""
    return PostSessionRenderOutput(
        schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
        body=body,
    )


class FakePostSessionRenderingModel:
    """Deterministic application-protocol rendering model (no provider)."""

    def __init__(
        self,
        output: PostSessionRenderOutput | None = None,
        *,
        error: Exception | None = None,
        echo: bool = False,
    ) -> None:
        self._output = output
        self._error = error
        self._echo = echo
        self.requests: list[SummaryRenderRequest | RecapRenderRequest] = []

    def render(
        self,
        request: SummaryRenderRequest | RecapRenderRequest,
    ) -> PostSessionRenderOutput:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._echo:
            body = (
                serialize_summary_request(request)
                if isinstance(request, SummaryRenderRequest)
                else serialize_recap_request(request)
            )
            return PostSessionRenderOutput(
                schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
                body=body,
            )
        assert self._output is not None, "fake rendering model has neither output nor error"
        return self._output
