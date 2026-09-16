"""Deterministic read-only Fast-Agent context builder.

This module provides immutable application-layer context snapshots for the
future Fast Agent.  It composes only already accepted data sources:

- ``SearchService`` for player-visible entity retrieval.
- ``VaultRepository.get_entity()`` for entity materialisation.
- ``SessionMetadataRepository.get_active_session()`` for active session.
- ``SessionEventRepository.list_events()`` for recent session events.
- ``WorldTimeRepository.get_current_world_time()`` for current world tick.
- an optional ``PlayerCampaignStateProvider`` capability for the compact,
  player-safe Campaign State ``campaign_memory`` (S12-04).

The builder is strictly read-only, synchronous, provider-neutral, and
performs zero model/tool/prompt work.  It never receives repositories, a
derived-state store or materialization internals for Campaign State: the
provider is the sole Campaign State dependency and returns an already
player-safe projection.

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

from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignState,
    PlayerCampaignStateProvider,
)
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

# Campaign State memory compactness (Fast-Agent policy).
#
# ``EntityId`` and ``NameStr`` are deliberately not length-bounded, so a count
# bound alone cannot bound the payload.  Both a deterministic entity-count
# bound and a UTF-8 text budget are enforced.  The budget counts the exact
# UTF-8 bytes of the entity id and display name; the first entry that would
# exceed the remaining budget stops inclusion.  Entries are never truncated
# and stable ids are never mutated.
MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES = 10
"""Maximum player-safe Campaign State entities exposed to the model."""

MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES = 2048
"""UTF-8 byte budget for the concatenated entity ids and names in memory."""


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
class AgentCampaignMemoryEntity:
    """One compact player-safe Campaign State memory entity.

    Only the player-safe minimum is exposed to the model: the exact stable id,
    the entity type and the display name.
    """

    entity_id: EntityId
    entity_type: EntityType
    name: str


@dataclass(frozen=True, slots=True)
class AgentCampaignMemory:
    """Compact, bounded, player-safe Campaign State memory for the Fast Agent.

    ``recently_touched`` contains at most
    ``MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES`` entries that fit within
    ``MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES``.  ``total_recently_touched`` is
    the full player-visible reference count *before* Fast-Agent compacting and
    ``truncated`` is ``True`` when any reference was omitted.  Ordering is the
    deterministic canonical ``entity_id`` ascending order; it is not a
    relevance ranking.
    """

    recently_touched: tuple[AgentCampaignMemoryEntity, ...]
    total_recently_touched: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Complete immutable compact context snapshot for the Fast Agent.

    This is an application-layer DTO.  It is NOT a ModelGateway DTO and must
    not be passed directly to a model provider.

    ``current_world_tick`` is the only model-facing world-time field; Campaign
    State memory carries no second tick or derived date.
    """

    user_input: str
    current_world_tick: WorldTick | None
    active_session: AgentSessionContext | None
    relevant_entities: tuple[AgentEntityContext, ...]
    recent_events: tuple[AgentEventContext, ...]
    campaign_memory: AgentCampaignMemory | None = None


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
        campaign_state_provider: PlayerCampaignStateProvider | None = None,
    ) -> None:
        self._search_service = search_service
        self._vault_repository = vault_repository
        self._session_repository = session_repository
        self._event_repository = event_repository
        self._world_time_repository = world_time_repository
        self._campaign_state_provider = campaign_state_provider

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

        # 6. Player-safe Campaign State memory (optional capability)
        campaign_memory = _read_campaign_memory(self._campaign_state_provider)

        return AgentContext(
            user_input=validated_input,
            current_world_tick=current_tick,
            active_session=active_session,
            relevant_entities=entities,
            recent_events=recent_events,
            campaign_memory=campaign_memory,
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


def _read_campaign_memory(
    provider: PlayerCampaignStateProvider | None,
) -> AgentCampaignMemory | None:
    """Build the compact player-safe Campaign State memory.

    ``None`` when no provider is configured or Campaign State is unavailable.
    The player-safe references are already in canonical ``entity_id``
    ascending order; this function applies the Fast-Agent count and UTF-8 byte
    bounds without truncating ids or names, stopping before the first entry
    that would not fit.
    """
    if provider is None:
        return None

    player_state: PlayerCampaignState | None = provider.get_player_campaign_state()
    if player_state is None:
        return None

    references = player_state.recently_touched
    total = len(references)

    included: list[AgentCampaignMemoryEntity] = []
    used_bytes = 0
    for ref in references:
        if len(included) >= MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES:
            break
        entry_bytes = len(ref.entity_id.encode("utf-8")) + len(ref.name.encode("utf-8"))
        if used_bytes + entry_bytes > MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES:
            break
        used_bytes += entry_bytes
        included.append(
            AgentCampaignMemoryEntity(
                entity_id=ref.entity_id,
                entity_type=ref.entity_type,
                name=ref.name,
            )
        )

    return AgentCampaignMemory(
        recently_touched=tuple(included),
        total_recently_touched=total,
        truncated=len(included) < total,
    )
