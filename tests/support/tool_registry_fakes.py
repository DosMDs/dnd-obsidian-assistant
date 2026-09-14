"""Structurally conforming sentinel fakes for MVP registry composition tests.

``build_mvp_tool_registry`` only composes already-registered tool families;
it must never execute a handler.  These fakes satisfy the production
protocols structurally so the composition call type-checks without casts.
Read methods return benign empty defaults; mutation methods raise
``NotImplementedError`` so any accidental handler execution fails loudly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic.types import AwareDatetime

from dnd_assistant.domain.calendar import CalendarDefinition, GameDate, WorldTick
from dnd_assistant.domain.events import TimelineEvent
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.retrieval.types import SearchHit, SearchQuery
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.session_recovery import SessionRecoveryReport
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.tools.mvp_registry import build_mvp_tool_registry
from dnd_assistant.tools.registry import ToolRegistry

_UNUSED = "Unit test must not execute handlers"


class FakeSearchService:
    """Structural ``SearchService`` sentinel."""

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        return []

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        return None


class FakeVaultRepository:
    """Structural ``VaultRepository`` sentinel."""

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        raise NotImplementedError(_UNUSED)

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        raise NotImplementedError(_UNUSED)

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        return []

    def patch_entity(
        self,
        entity_id: EntityId,
        patch: EntityPatch,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> VaultDocument:
        raise NotImplementedError(_UNUSED)

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        raise NotImplementedError(_UNUSED)


class FakeSessionRuntime:
    """Structural ``SessionRuntime`` sentinel."""

    def get_active_session(self) -> Session | None:
        return None

    def start_session(self, *, audit: AuditContext) -> Session:
        raise NotImplementedError(_UNUSED)

    def record_event(
        self,
        event_type: str,
        *,
        extra_fields: Mapping[str, object] | None = None,
        audit: AuditContext,
    ) -> RawSessionEvent:
        raise NotImplementedError(_UNUSED)

    def record_note(self, text: str, *, audit: AuditContext) -> RawSessionEvent:
        raise NotImplementedError(_UNUSED)

    def end_session(
        self,
        *,
        touched_entity_ids: Sequence[EntityId] = (),
        audit: AuditContext,
    ) -> Session:
        raise NotImplementedError(_UNUSED)


class FakeSessionRecovery:
    """Structural ``SessionRecovery`` sentinel."""

    def inspect_runtime(self) -> SessionRecoveryReport:
        return SessionRecoveryReport([])


class FakeSessionMetadataRepository:
    """Structural ``SessionMetadataRepository`` sentinel."""

    def allocate_next_session_id(self) -> str:
        raise NotImplementedError(_UNUSED)

    def create_session(self, session: Session, *, audit: AuditContext) -> RawSessionMetadata:
        raise NotImplementedError(_UNUSED)

    def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
        raise NotImplementedError(_UNUSED)

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
        raise NotImplementedError(_UNUSED)


class FakeSessionEventRepository:
    """Structural ``SessionEventRepository`` sentinel."""

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
        raise NotImplementedError(_UNUSED)


class FakeWorldTimeRepository:
    """Structural ``WorldTimeRepository`` sentinel."""

    def get_current_world_time(self) -> CurrentWorldTime:
        raise NotImplementedError(_UNUSED)

    def initialize_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        raise NotImplementedError(_UNUSED)

    def set_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        raise NotImplementedError(_UNUSED)


class FakeCalendarService:
    """Structural ``CalendarService`` sentinel."""

    @property
    def definition(self) -> CalendarDefinition:
        raise NotImplementedError(_UNUSED)

    def date_to_tick(self, date: GameDate) -> WorldTick:
        raise NotImplementedError(_UNUSED)

    def tick_to_date(self, tick: WorldTick) -> GameDate:
        raise NotImplementedError(_UNUSED)

    def advance_world_time(self, current_tick: WorldTick, *, minutes: int) -> WorldTick:
        raise NotImplementedError(_UNUSED)

    def time_until(self, start_tick: WorldTick, end_tick: WorldTick) -> int:
        raise NotImplementedError(_UNUSED)

    def events_between(
        self,
        events: Sequence[TimelineEvent],
        start_tick: WorldTick,
        end_tick: WorldTick,
    ) -> tuple[TimelineEvent, ...]:
        raise NotImplementedError(_UNUSED)

    def events_near(
        self,
        events: Sequence[TimelineEvent],
        event: TimelineEvent,
        *,
        radius: int,
    ) -> tuple[TimelineEvent, ...]:
        raise NotImplementedError(_UNUSED)

    def upcoming(
        self,
        events: Sequence[TimelineEvent],
        current_tick: WorldTick,
        *,
        days: int,
    ) -> tuple[TimelineEvent, ...]:
        raise NotImplementedError(_UNUSED)

    def overdue_events(
        self,
        events: Sequence[TimelineEvent],
        current_tick: WorldTick,
    ) -> tuple[TimelineEvent, ...]:
        raise NotImplementedError(_UNUSED)

    def time_until_event(
        self,
        current_tick: WorldTick,
        event: TimelineEvent,
    ) -> tuple[int, int] | None:
        raise NotImplementedError(_UNUSED)


def build_registry_with_fakes() -> ToolRegistry:
    """Build the MVP registry with structurally conforming sentinel fakes."""
    return build_mvp_tool_registry(
        search_service=FakeSearchService(),
        repository=FakeVaultRepository(),
        runtime_service=FakeSessionRuntime(),
        recovery_service=FakeSessionRecovery(),
        session_repository=FakeSessionMetadataRepository(),
        event_repository=FakeSessionEventRepository(),
        world_time_repository=FakeWorldTimeRepository(),
        calendar_service=FakeCalendarService(),
    )
