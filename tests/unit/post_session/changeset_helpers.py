"""S11-05 ChangeSet producer test helpers (test-only, no pytest import).

Provide deterministic document/repository builders so producer/binding unit
tests run with no real Vault and no model.
"""

from __future__ import annotations

from collections.abc import Sequence

from dnd_assistant.application.entity_id_allocator import (
    allocate_candidate_entity_id,
)
from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_eligibility import (
    EligibilityReason,
    EligibilityResult,
)
from dnd_assistant.application.post_session_identity import (
    POST_SESSION_PROCESSOR_VERSION,
    POST_SESSION_PROMPT_VERSION,
    compute_input_fingerprint,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.post_session import (
    PreparedCalendarProjection,
    PreparedContextProjection,
    PreparedEntityProjection,
    PreparedInputIdentity,
    PreparedRawEvent,
    PreparedSessionProjection,
)
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Visibility,
)
from dnd_assistant.storage.types import VaultDocument
from tests.unit.post_session.helpers import BASE_END, BASE_START

ATTEMPT_A = "att_" + "a" * 32
ATTEMPT_B = "att_" + "b" * 32


def make_document(
    entity_id: str,
    *,
    entity_type: EntityType = EntityType.NPC,
    name: str = "Aria",
    status: str = "alive",
    visibility: Visibility = Visibility.PLAYER,
    knowledge_status: KnowledgeStatus = KnowledgeStatus.CONFIRMED,
    revision: int = 1,
    tags: Sequence[str] = (),
    body: str = "",
    aliases: Sequence[str] | None = None,
) -> VaultDocument:
    entity = Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status=status,
        visibility=visibility,
        knowledge_status=knowledge_status,
        created_at=BASE_START,
        updated_at=BASE_START,
        revision=revision,
        tags=list(tags),
    )
    extra = {"aliases": list(aliases)} if aliases is not None else {}
    return VaultDocument(entity=entity, extra_frontmatter=extra, body=body)


def projection_from_document(document: VaultDocument) -> PreparedEntityProjection:
    entity = document.entity
    return PreparedEntityProjection(
        id=entity.id,
        type=entity.type,
        revision=entity.revision,
        name=entity.name,
        status=entity.status,
        visibility=entity.visibility,
        knowledge_status=entity.knowledge_status,
        tags=tuple(entity.tags),
        body_projection=document.body,
    )


def make_prepared(
    documents: Sequence[VaultDocument],
    *,
    session_id: str = "S001",
    event_ids: Sequence[str] = ("evt_001",),
    context_text: str = "context",
) -> PreparedPostSessionInput:
    projections = tuple(projection_from_document(document) for document in documents)
    raw_events = tuple(
        PreparedRawEvent(
            event_id=event_id,
            real_time=BASE_START,
            world_tick=150,
            type="note",
        )
        for event_id in event_ids
    )
    touched = tuple(projection.id for projection in projections)
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
        entities=projections,
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


class FakeReadOnlyRepository:
    """Read-only repository double.

    Implements the full ``VaultRepository`` surface so it is structurally
    compatible, but every write method raises and records the attempt.  This
    makes any hidden write/read-method use visible and gives stronger zero-write
    evidence than a partial object.
    """

    def __init__(self, documents: Sequence[VaultDocument]) -> None:
        self._documents = list(documents)
        self.list_entities_calls = 0
        self.writes: list[tuple[str, str]] = []

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        self.list_entities_calls += 1
        if entity_type is None:
            return list(self._documents)
        return [d for d in self._documents if d.entity.type == entity_type]

    def get_entity(self, entity_id: str) -> VaultDocument:
        self.writes.append(("get_entity", entity_id))
        raise AssertionError("producer must not call get_entity")

    def create_entity(self, document: VaultDocument, *, audit: object) -> VaultDocument:
        self.writes.append(("create_entity", document.entity.id))
        raise AssertionError("producer must not call create_entity")

    def patch_entity(
        self,
        entity_id: str,
        patch: object,
        *,
        expected_revision: int,
        audit: object,
    ) -> VaultDocument:
        self.writes.append(("patch_entity", entity_id))
        raise AssertionError("producer must not call patch_entity")

    def append_entity_fact(
        self,
        entity_id: str,
        *,
        expected_revision: int,
        fact: str,
        audit: object,
    ) -> VaultDocument:
        self.writes.append(("append_entity_fact", entity_id))
        raise AssertionError("producer must not call append_entity_fact")


__all__ = [
    "ATTEMPT_A",
    "ATTEMPT_B",
    "FakeReadOnlyRepository",
    "allocate_candidate_entity_id",
    "make_document",
    "make_prepared",
    "projection_from_document",
]
