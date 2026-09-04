"""Deterministic read-only Fast-Agent context builder.

This module provides immutable application-layer context snapshots for the
future Fast Agent.  It composes only already accepted data sources:

- ``SearchService`` for player-visible entity retrieval.
- ``VaultRepository.get_entity()`` for entity materialisation.
- ``SessionMetadataRepository.get_active_session()`` for active session.
- ``SessionEventRepository.list_events()`` for recent session events.
- ``WorldTimeRepository.get_current_world_time()`` for current world tick.

The builder is strictly read-only, synchronous, provider-neutral, and
performs zero model/tool/prompt work.

Runtime imports are deferred to avoid eagerly loading ``dnd_assistant.models``,
``dnd_assistant.tools``, or ``dnd_assistant.cli`` at module-import time.

A fresh ``import dnd_assistant.application.agent_context`` must NOT eagerly
load any of::

    dnd_assistant.models
    dnd_assistant.models.ollama
    dnd_assistant.tools
    dnd_assistant.cli
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dnd_assistant.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from dnd_assistant.domain.calendar import WorldTick
    from dnd_assistant.domain.types import EntityId, EntityType, KnowledgeStatus, Visibility
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.retrieval.types import SearchHit
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
        VaultRepository,
        WorldTimeRepository,
    )

# ── Private compactness limits ─────────────────────────────────────────────────

_MAX_RELEVANT_ENTITIES = 5
_MAX_RECENT_EVENTS = 5
_MAX_ENTITY_BODY_EXCERPT = 1000
_MAX_EVENT_TEXT_EXCERPT = 400


# ── Context DTOs ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentEntityContext:
    """Immutable player-visible entity snapshot for agent context."""

    entity_id: EntityId
    entity_type: EntityType
    name: str
    status: str
    knowledge_status: KnowledgeStatus
    tags: tuple[str, ...]
    body_excerpt: str
    body_truncated: bool


@dataclass(frozen=True, slots=True)
class AgentSessionContext:
    """Immutable active-session snapshot for agent context."""

    session_id: str
    world_tick_start: WorldTick


@dataclass(frozen=True, slots=True)
class AgentEventContext:
    """Immutable recent-session-event snapshot for agent context."""

    event_id: str
    event_type: str
    world_tick: WorldTick
    text_excerpt: str | None
    text_truncated: bool


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Complete immutable compact context snapshot for the Fast Agent.

    This is an application-layer DTO.  It is NOT a ModelGateway DTO and must
    not be passed directly to a model provider.
    """

    user_input: str
    current_world_tick: WorldTick | None
    active_session: AgentSessionContext | None
    relevant_entities: tuple[AgentEntityContext, ...]
    recent_events: tuple[AgentEventContext, ...]


# ── Input validation ───────────────────────────────────────────────────────────


def _validate_user_input(user_input: object) -> str:
    """Validate and return the user input string.

    Raises:
        ValidationError: If the input is not a printable non-empty string.
    """
    if not isinstance(user_input, str):
        raise ValidationError(f"user_input must be a str, got {type(user_input).__name__}")
    if not user_input.strip():
        raise ValidationError("user_input must not be empty or whitespace-only")
    if not user_input.isprintable():
        raise ValidationError("user_input must be printable")
    return user_input


# ── Entity snapshot helpers ────────────────────────────────────────────────────


def _build_entity_excerpt(body: str) -> tuple[str, bool]:
    """Build a clipped body excerpt and truncation flag."""
    if len(body) <= _MAX_ENTITY_BODY_EXCERPT:
        return body, False
    return body[:_MAX_ENTITY_BODY_EXCERPT], True


def _extract_event_text(
    extra_fields: dict[str, object],
) -> tuple[str | None, bool]:
    """Extract and clip the ``text`` field from event extra fields.

    Returns ``(text_excerpt, text_truncated)``.
    """
    text = extra_fields.get("text")
    if not isinstance(text, str):
        return None, False
    if len(text) <= _MAX_EVENT_TEXT_EXCERPT:
        return text, False
    return text[:_MAX_EVENT_TEXT_EXCERPT], True


# ── Builder ────────────────────────────────────────────────────────────────────


class AgentContextBuilder:
    """Deterministic read-only compact context builder.

    Composes accepted retrieval, storage, and domain services into an
    immutable ``AgentContext`` snapshot.

    The builder is synchronous, provider-neutral, and performs zero model
    or tool work.
    """

    def __init__(
        self,
        *,
        search_service: SearchService,
        vault_repository: VaultRepository,
        session_repository: SessionMetadataRepository,
        event_repository: SessionEventRepository,
        world_time_repository: WorldTimeRepository,
    ) -> None:
        self._search_service = search_service
        self._vault_repository = vault_repository
        self._session_repository = session_repository
        self._event_repository = event_repository
        self._world_time_repository = world_time_repository

    def build(self, user_input: str) -> AgentContext:
        """Build a compact context snapshot from the given user input.

        Args:
            user_input: The validated user query string.

        Returns:
            An immutable ``AgentContext`` snapshot.

        Raises:
            ValidationError: If ``user_input`` is not a valid printable
                non-empty string.
        """
        # Deferred runtime imports: keep provider/model/tool packages out of
        # module-import scope.
        from dnd_assistant.domain.types import Visibility
        from dnd_assistant.retrieval.types import SearchQuery

        # 1. Validate input (no reads before validation)
        validated_input = _validate_user_input(user_input)

        # 2. Search for relevant entities
        query = SearchQuery(text=validated_input)
        hits = self._search_service.search(query, limit=_MAX_RELEVANT_ENTITIES)

        # 3. Materialise unique entities
        entities = _build_entity_contexts(
            hits=hits,
            vault_repository=self._vault_repository,
            visibility_enum=Visibility,
        )

        # 4. Current world time
        current_tick = _read_current_world_tick(self._world_time_repository)

        # 5. Active session + recent events
        active_session, recent_events = _build_session_context(
            session_repository=self._session_repository,
            event_repository=self._event_repository,
        )

        return AgentContext(
            user_input=validated_input,
            current_world_tick=current_tick,
            active_session=active_session,
            relevant_entities=entities,
            recent_events=recent_events,
        )


# ── Internal helpers ───────────────────────────────────────────────────────────


def _build_entity_contexts(
    *,
    hits: Sequence[SearchHit],
    vault_repository: VaultRepository,
    visibility_enum: type[Visibility],
) -> tuple[AgentEntityContext, ...]:
    """Build entity contexts from search hits.

    De-duplicates by entity ID (first occurrence wins).
    Skips stale hits where ``get_entity`` raises ``NotFoundError``.
    Enforces player-visibility defence in depth.
    """
    seen_ids: set[EntityId] = set()
    result: list[AgentEntityContext] = []

    for hit in hits:
        if hit.entity_id in seen_ids:
            continue
        seen_ids.add(hit.entity_id)

        # Materialise the entity
        try:
            document = vault_repository.get_entity(hit.entity_id)
        except NotFoundError:
            # Stale search hit: skip silently
            continue

        entity = document.entity

        # Player-visibility defence in depth
        if entity.visibility is not visibility_enum.PLAYER:
            continue

        body_excerpt, body_truncated = _build_entity_excerpt(document.body)

        result.append(
            AgentEntityContext(
                entity_id=entity.id,
                entity_type=entity.type,
                name=entity.name,
                status=entity.status,
                knowledge_status=entity.knowledge_status,
                tags=tuple(entity.tags),
                body_excerpt=body_excerpt,
                body_truncated=body_truncated,
            )
        )

        if len(result) >= _MAX_RELEVANT_ENTITIES:
            break

    return tuple(result)


def _read_current_world_tick(
    world_time_repository: WorldTimeRepository,
) -> WorldTick | None:
    """Read the current world tick, returning ``None`` if uninitialised."""
    try:
        current = world_time_repository.get_current_world_time()
    except NotFoundError:
        return None
    return current.current_world_tick


def _build_session_context(
    *,
    session_repository: SessionMetadataRepository,
    event_repository: SessionEventRepository,
) -> tuple[AgentSessionContext | None, tuple[AgentEventContext, ...]]:
    """Build active-session and recent-event context.

    When no active session exists, returns ``(None, ())`` and does NOT call
    ``event_repository.list_events()``.
    """
    raw_metadata = session_repository.get_active_session()
    if raw_metadata is None:
        return None, ()

    session = raw_metadata.session
    session_ctx = AgentSessionContext(
        session_id=session.id,
        world_tick_start=session.world_tick_start,
    )

    events = event_repository.list_events(session.id)
    tail = events[-_MAX_RECENT_EVENTS:] if len(events) > _MAX_RECENT_EVENTS else events

    event_ctxs: list[AgentEventContext] = []
    for ev in tail:
        text_excerpt, text_truncated = _extract_event_text(ev.extra_fields)
        event_ctxs.append(
            AgentEventContext(
                event_id=ev.event_id,
                event_type=ev.type,
                world_tick=ev.world_tick,
                text_excerpt=text_excerpt,
                text_truncated=text_truncated,
            )
        )

    return session_ctx, tuple(event_ctxs)
