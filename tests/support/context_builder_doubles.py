"""Shared structural doubles for ``AgentContextBuilder`` construction.

Many PAIM parity/evidence tests construct a real ``AgentContextBuilder`` whose
retrieval/storage reads are deliberately inert.  These doubles satisfy the full
production protocols structurally so those tests no longer need local stub
classes or ``# type: ignore`` casts.

Behavior is intentionally minimal and matches the previously duplicated local
stubs:

* search returns no hits (and exact-id lookup returns ``None``);
* entity reads raise ``ValueError`` because they must not be reached;
* there is no active session and no recent events;
* world time raises ``NotFoundError`` so the builder reports an uninitialised
  tick (``None``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic.types import AwareDatetime

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import NotFoundError
from dnd_assistant.retrieval.types import SearchHit, SearchQuery
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.types import VaultDocument
from tests.support.repository_doubles import VaultRepositoryWriteStubs

_UNEXPECTED = "unexpected call"


class NullSearchService:
    """Structural ``SearchService`` double returning no results."""

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        return []

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        return None


class UntouchedVaultRepository(VaultRepositoryWriteStubs):
    """Structural ``VaultRepository`` double whose reads must not be reached."""

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        raise ValueError(_UNEXPECTED)

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        return []


class NullSessionMetadataRepository:
    """Structural ``SessionMetadataRepository`` double with no active session."""

    def allocate_next_session_id(self) -> str:
        return "S000"

    def create_session(self, session: Session, *, audit: AuditContext) -> RawSessionMetadata:
        raise ValueError(_UNEXPECTED)

    def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
        raise ValueError(_UNEXPECTED)

    def list_session_metadata(self) -> list[RawSessionMetadata]:
        return []

    def get_active_session(self) -> RawSessionMetadata | None:
        return None

    def close_session(
        self,
        session_id: str,
        *,
        expected_revision: Revision,
        world_tick_end: WorldTick,
        touched_entity_ids: Sequence[EntityId],
        audit: AuditContext,
    ) -> RawSessionMetadata:
        raise ValueError(_UNEXPECTED)


class NullSessionEventRepository:
    """Structural ``SessionEventRepository`` double with no events."""

    def list_events(self, session_id: str) -> list[RawSessionEvent]:
        return []

    def append_event(
        self,
        session_id: str,
        *,
        event_type: str,
        real_time: AwareDatetime,
        world_tick: WorldTick,
        extra_fields: Mapping[str, object] | None,
        audit: AuditContext,
    ) -> RawSessionEvent:
        raise ValueError(_UNEXPECTED)


class MissingWorldTimeRepository:
    """Structural ``WorldTimeRepository`` double reporting uninitialised state."""

    def get_current_world_time(self) -> CurrentWorldTime:
        raise NotFoundError("no world time")

    def initialize_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        raise ValueError(_UNEXPECTED)

    def set_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        raise ValueError(_UNEXPECTED)


def make_stub_context_builder() -> AgentContextBuilder:
    """Build an ``AgentContextBuilder`` with inert structural doubles."""
    return AgentContextBuilder(
        search_service=NullSearchService(),
        vault_repository=UntouchedVaultRepository(),
        session_repository=NullSessionMetadataRepository(),
        event_repository=NullSessionEventRepository(),
        world_time_repository=MissingWorldTimeRepository(),
    )
