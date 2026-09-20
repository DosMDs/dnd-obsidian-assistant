"""Eval-only synthetic in-memory runtime fixture.

Builds the real production agent runtime below the Vault composition boundary:

    real AgentContextBuilder / DndAgentRunPreparer / DndAgentPolicy /
    PydanticAIToolBridge / PydanticAIAgentRuntime and the four real production
    tool registration functions,

backed by *eval-only* in-memory implementations of the accepted repository /
service protocols.

This is NOT a Vault replacement, NOT a production storage implementation and is
never exported through ``dnd_assistant.storage``.  It owns no filesystem
objects (no ``Path``, temp files, SQLite or Obsidian Vault) and is constructed
fresh for every ``(scenario, repetition)`` sample.

Only the fixed synthetic ``EvalExecutionSpec``/``EvalSessionState`` selects
which deterministic starting state is built.  Search hits derive from query
text/content, never from a scenario ID.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_tool_selection import select_agent_tools
from dnd_assistant.application.pydantic_ai_agent_runtime import PydanticAIAgentRuntime
from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer
from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Revision,
    Visibility,
)
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ConflictError, NotFoundError
from dnd_assistant.evals.dataset import EvalExecutionSpec, EvalPermission, EvalSessionState
from dnd_assistant.retrieval.types import MatchKind, SearchHit, SearchQuery
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.session_recovery import SessionRecoveryReport
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.tools.catalog import ToolRegistrySchema, build_tool_registry_schema
from dnd_assistant.tools.entity_mutations import register_entity_mutation_tools
from dnd_assistant.tools.entity_reads import register_entity_read_tools
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_mutations import register_session_mutation_tools
from dnd_assistant.tools.session_reads import register_session_read_tools
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode

FIXTURE_WORLD_TICK = 2100
FIXTURE_TIME = datetime(2026, 1, 1, tzinfo=UTC)

_ENTITY_TYPES = {
    "npc": EntityType.NPC,
    "location": EntityType.LOCATION,
    "quest": EntityType.QUEST,
    "item": EntityType.ITEM,
}


# ── Synthetic deterministic state ──────────────────────────────────────────


def _make_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    *,
    revision: int = 1,
    body: str = "",
) -> VaultDocument:
    entity = Entity(
        id=entity_id,
        type=_ENTITY_TYPES[entity_type],
        name=name,
        status="active",
        visibility=Visibility.PLAYER,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=FIXTURE_TIME,
        updated_at=FIXTURE_TIME,
        revision=revision,
        tags=[],
    )
    return VaultDocument(entity=entity, body=body)


def _make_session(
    session_id: str,
    status: str,
    *,
    world_tick_start: int,
    world_tick_end: int | None = None,
) -> Session:
    return Session(
        id=session_id,
        type="session",
        status=status,
        real_started_at=FIXTURE_TIME,
        real_finished_at=FIXTURE_TIME if world_tick_end is not None else None,
        world_tick_start=world_tick_start,
        world_tick_end=world_tick_end,
        processed=False,
        processed_model_profile=None,
        revision=1,
    )


_Kell_tail = (
    "Хроника Келла описывает множество архивных событий. "
) * 60 + "В самом конце записи Келл упоминает печать совета."


def _base_documents() -> dict[str, VaultDocument]:
    docs: dict[str, VaultDocument] = {
        "npc-arlen-001": _make_entity(
            "npc-arlen-001", "Арлен", "npc", revision=3, body="Арлен — воин из северной деревни."
        ),
        "npc-varos-elder": _make_entity("npc-varos-elder", "Варос", "npc"),
        "npc-varos-younger": _make_entity("npc-varos-younger", "Варос Младший", "npc"),
        "npc-kell-001": _make_entity("npc-kell-001", "Архивист Келл", "npc", body=_Kell_tail),
        "loc-blackkeep-001": _make_entity("loc-blackkeep-001", "Чёрный Замок", "location"),
        "quest-moongate-001": _make_entity("quest-moongate-001", "Лунные Врата", "quest"),
        "item-amulet-001": _make_entity("item-amulet-001", "Амулет Луны", "item"),
    }
    for index in range(1, 7):
        guard_id = f"npc-guard-{index:03d}"
        docs[guard_id] = _make_entity(guard_id, f"Стража {index}", "npc")
    return docs


def _base_sessions() -> dict[str, Session]:
    return {
        "S001": _make_session("S001", "completed", world_tick_start=100, world_tick_end=400),
        "S002": _make_session("S002", "completed", world_tick_start=500, world_tick_end=800),
    }


# ── In-memory storage protocols ────────────────────────────────────────────


class _InMemorySearchService:
    """Token-substring player-visible search over the synthetic fixture."""

    def __init__(self, vault_repository: _InMemoryVaultRepository) -> None:
        self._repository = vault_repository

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        tokens = [t for t in query.text.lower().split() if len(t) >= 3]
        hits: list[SearchHit] = []
        for document in self._repository._all_documents():
            entity = document.entity
            if entity.visibility is not Visibility.PLAYER:
                continue
            if query.entity_types is not None and entity.type not in query.entity_types:
                continue
            haystack = " ".join((entity.name, entity.status, document.body, *entity.tags)).lower()
            if any(token in haystack for token in tokens):
                hits.append(SearchHit(entity_id=entity.id, match_kind=MatchKind.FTS, score=None))
            if len(hits) >= limit:
                break
        return hits

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        document = self._repository._documents.get(entity_id)
        if document is None or document.entity.visibility is not Visibility.PLAYER:
            return None
        return SearchHit(entity_id=document.entity.id, match_kind=MatchKind.EXACT_ID, score=None)


class _InMemoryVaultRepository:
    """Eval-only in-memory entity repository (not a production repository)."""

    def __init__(self, documents: dict[str, VaultDocument]) -> None:
        self._documents: dict[str, VaultDocument] = dict(documents)

    def _all_documents(self) -> list[VaultDocument]:
        return [self._documents[key] for key in sorted(self._documents)]

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        if document.entity.id in self._documents:
            raise ConflictError(f"Entity already exists: {document.entity.id}")
        self._documents[document.entity.id] = document
        return document

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        document = self._documents.get(entity_id)
        if document is None:
            raise NotFoundError("Entity not found or not accessible")
        return document

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        documents = self._all_documents()
        if entity_type is not None:
            documents = [d for d in documents if d.entity.type is entity_type]
        return documents

    def patch_entity(
        self,
        entity_id: EntityId,
        patch: EntityPatch,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> VaultDocument:
        current = self.get_entity(entity_id)
        if current.entity.revision != expected_revision:
            raise ConflictError("Revision conflict")
        data = current.entity.model_dump()
        for name in patch.model_fields_set:
            data[name] = getattr(patch, name)
        data["revision"] = expected_revision + 1
        data["updated_at"] = audit.real_time
        updated = VaultDocument(
            entity=Entity.model_validate(data),
            extra_frontmatter=current.extra_frontmatter,
            body=current.body,
        )
        self._documents[entity_id] = updated
        return updated

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        current = self.get_entity(entity_id)
        if current.entity.revision != expected_revision:
            raise ConflictError("Revision conflict")
        data = current.entity.model_dump()
        data["revision"] = expected_revision + 1
        data["updated_at"] = audit.real_time
        body = current.body
        if body and not body.endswith("\n"):
            body += "\n"
        body += f"- {fact}\n"
        updated = VaultDocument(
            entity=Entity.model_validate(data),
            extra_frontmatter=current.extra_frontmatter,
            body=body,
        )
        self._documents[entity_id] = updated
        return updated


class _InMemoryWorldTimeRepository:
    """Immediate in-memory world time at the fixed eval tick."""

    def __init__(self, current_world_tick: int) -> None:
        self._current = CurrentWorldTime(current_world_tick=current_world_tick, revision=1)

    def get_current_world_time(self) -> CurrentWorldTime:
        return self._current

    def initialize_current_world_time(
        self, world_tick: WorldTick, *, audit: AuditContext
    ) -> CurrentWorldTime:
        self._current = CurrentWorldTime(current_world_tick=world_tick, revision=1)
        return self._current

    def set_current_world_time(
        self, world_tick: WorldTick, *, expected_revision: Revision, audit: AuditContext
    ) -> CurrentWorldTime:
        if expected_revision != self._current.revision:
            raise ConflictError("Revision conflict")
        self._current = CurrentWorldTime(
            current_world_tick=world_tick, revision=expected_revision + 1
        )
        return self._current


class _InMemorySessionMetadataRepository:
    """Eval-only in-memory session metadata repository."""

    def __init__(self, sessions: dict[str, Session]) -> None:
        self._sessions: dict[str, Session] = dict(sessions)

    def allocate_next_session_id(self) -> str:
        highest = 0
        for session_id in self._sessions:
            if session_id.startswith("S") and session_id[1:].isdigit():
                highest = max(highest, int(session_id[1:]))
        return f"S{highest + 1:04d}"

    def create_session(self, session: Session, *, audit: AuditContext) -> RawSessionMetadata:
        if session.id in self._sessions:
            raise ConflictError(f"Session already exists: {session.id}")
        self._sessions[session.id] = session
        return RawSessionMetadata(session)

    def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError(f"Session not found: {session_id}")
        return RawSessionMetadata(session)

    def list_session_metadata(self) -> list[RawSessionMetadata]:
        return [RawSessionMetadata(self._sessions[key]) for key in sorted(self._sessions)]

    def get_active_session(self) -> RawSessionMetadata | None:
        active = [s for s in self._sessions.values() if s.status == "active"]
        if not active:
            return None
        if len(active) > 1:
            raise ConflictError("More than one active session")
        return RawSessionMetadata(active[0])

    def close_session(
        self,
        session_id: str,
        *,
        expected_revision: Revision,
        world_tick_end: WorldTick,
        touched_entity_ids: Sequence[EntityId],
        audit: AuditContext,
    ) -> RawSessionMetadata:
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError(f"Session not found: {session_id}")
        if session.revision != expected_revision:
            raise ConflictError("Revision conflict")
        data = session.model_dump()
        data["status"] = "completed"
        data["world_tick_end"] = world_tick_end
        data["real_finished_at"] = audit.real_time
        data["revision"] = expected_revision + 1
        self._sessions[session_id] = Session.model_validate(data)
        return RawSessionMetadata(self._sessions[session_id])


class _InMemorySessionEventRepository:
    """Eval-only in-memory append-only event repository."""

    def __init__(self, events: dict[str, list[RawSessionEvent]] | None = None) -> None:
        self._events: dict[str, list[RawSessionEvent]] = {
            key: list(value) for key, value in (events or {}).items()
        }
        self._next_event = 1 + sum(len(v) for v in self._events.values())

    def list_events(self, session_id: str) -> list[RawSessionEvent]:
        return list(self._events.get(session_id, []))

    def append_event(
        self,
        session_id: str,
        *,
        event_type: str,
        real_time: datetime,
        world_tick: WorldTick,
        extra_fields: Mapping[str, object] | None,
        audit: AuditContext,
    ) -> RawSessionEvent:
        event_id = f"evt_{self._next_event}"
        self._next_event += 1
        event = RawSessionEvent(
            event_id=event_id,
            real_time=real_time,
            world_tick=world_tick,
            type=event_type,
            extra_fields=dict(extra_fields) if extra_fields else None,
        )
        self._events.setdefault(session_id, []).append(event)
        return event


class _InMemorySessionRecoveryRepository:
    """Clean, empty recovery report for the synthetic fixture."""

    def inspect_runtime(self) -> SessionRecoveryReport:
        return SessionRecoveryReport()

    def repair_audit_tail(self, *, audit: AuditContext) -> Any:
        raise RuntimeError("eval fixture: recovery repair must not be called")

    def cleanup_partial_start(self, session_id: str, *, audit: AuditContext) -> Any:
        raise RuntimeError("eval fixture: recovery repair must not be called")

    def repair_event_tail(self, session_id: str, *, audit: AuditContext) -> Any:
        raise RuntimeError("eval fixture: recovery repair must not be called")


# ── Instrumented registry ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HandlerInvocation:
    """Literal evidence of one production handler invocation."""

    tool_name: str
    arguments: dict[str, Any]
    is_write: bool


class InstrumentedToolRegistry(ToolRegistry):
    """Production ``ToolRegistry`` that records handler invocations.

    Definitions and handlers remain the canonical production objects; the
    wrapper records entry and immediately delegates.  Outputs and exceptions
    propagate unchanged.
    """

    def __init__(self) -> None:
        super().__init__()
        self.handler_invocations: list[HandlerInvocation] = []

    def register(self, definition: Any, handler: Callable[..., object]) -> None:
        is_write = definition.permission is Permission.WRITE

        def _wrapped(input_model: Any, context: ExecutionContext) -> object:
            self.handler_invocations.append(
                HandlerInvocation(
                    tool_name=definition.name,
                    arguments=input_model.model_dump(mode="json"),
                    is_write=is_write,
                )
            )
            return handler(input_model, context)

        super().register(definition, _wrapped)


# ── Fixture bundle ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class EvalFixture:
    """One fresh synthetic eval fixture with a real production runtime."""

    registry: InstrumentedToolRegistry
    catalog: ToolRegistrySchema
    vault_repository: _InMemoryVaultRepository
    context_builder: AgentContextBuilder
    run_preparer: DndAgentRunPreparer
    runtime: PydanticAIAgentRuntime
    execution_context: ExecutionContext
    handler_invocations: list[HandlerInvocation] = field(default_factory=list)

    def exposed_tools(self) -> tuple[Any, ...]:
        """Real production tool exposure for this fixture's execution context."""
        return tuple(select_agent_tools(self.catalog, context=self.execution_context))


def _build_audit_context(
    spec: EvalExecutionSpec, scenario_id: str, repetition: int
) -> AuditContext:
    return AuditContext(
        operation_id=f"eval:{scenario_id}:{repetition}",
        real_time=FIXTURE_TIME,
        source="eval-scripted",
    )


def build_fixture(
    spec: EvalExecutionSpec,
    *,
    model: Any,
    scenario_id: str = "eval",
    repetition: int = 0,
) -> EvalFixture:
    """Build a fresh synthetic fixture + real production runtime for one sample."""
    documents = _base_documents()
    sessions = _base_sessions()
    events: dict[str, list[RawSessionEvent]] = {
        "S001": [
            RawSessionEvent(f"evt_{i}", FIXTURE_TIME, FIXTURE_WORLD_TICK, "event")
            for i in range(1, 4)
        ],
        "S002": [
            RawSessionEvent(f"evt_{i}", FIXTURE_TIME, FIXTURE_WORLD_TICK, "event")
            for i in range(4, 6)
        ],
    }
    if spec.session_state is EvalSessionState.ACTIVE:
        sessions["S010"] = _make_session(
            "S010", "active", world_tick_start=FIXTURE_WORLD_TICK - 100
        )
        events["S010"] = [
            RawSessionEvent(
                f"evt_{100 + i}",
                FIXTURE_TIME,
                FIXTURE_WORLD_TICK,
                "note",
                {"text": f"Событие {i}"},
            )
            for i in range(1, 8)
        ]

    vault_repository = _InMemoryVaultRepository(documents)
    search_service = _InMemorySearchService(vault_repository)
    world_time_repository = _InMemoryWorldTimeRepository(FIXTURE_WORLD_TICK)
    session_repository = _InMemorySessionMetadataRepository(sessions)
    event_repository = _InMemorySessionEventRepository(events)
    recovery_repository = _InMemorySessionRecoveryRepository()

    runtime_service = SessionRuntimeService(
        session_repository, world_time_repository, event_repository
    )
    recovery_service = SessionRecoveryService(recovery_repository)

    registry = InstrumentedToolRegistry()
    register_entity_read_tools(registry, search_service=search_service, repository=vault_repository)
    register_entity_mutation_tools(
        registry, search_service=search_service, repository=vault_repository
    )
    register_session_read_tools(
        registry,
        runtime_service=runtime_service,
        session_repository=session_repository,
        event_repository=event_repository,
    )
    register_session_mutation_tools(
        registry,
        runtime_service=runtime_service,
        recovery_service=recovery_service,
    )

    catalog = build_tool_registry_schema(registry)
    bridge = PydanticAIToolBridge(registry=registry)

    context_builder = AgentContextBuilder(
        search_service=search_service,
        vault_repository=vault_repository,
        session_repository=session_repository,
        event_repository=event_repository,
        world_time_repository=world_time_repository,
    )
    run_preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=catalog,
        tool_bridge=bridge,
    )
    runtime = PydanticAIAgentRuntime(run_preparer=run_preparer, model=model)

    session_mode = (
        SessionMode.ACTIVE_SESSION
        if spec.session_state is EvalSessionState.ACTIVE
        else SessionMode.NO_ACTIVE_SESSION
    )
    if spec.permission is EvalPermission.WRITE:
        execution_context = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=session_mode,
            audit=_build_audit_context(spec, scenario_id, repetition),
        )
    else:
        execution_context = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=session_mode,
            audit=None,
        )

    return EvalFixture(
        registry=registry,
        catalog=catalog,
        vault_repository=vault_repository,
        context_builder=context_builder,
        run_preparer=run_preparer,
        runtime=runtime,
        execution_context=execution_context,
        handler_invocations=registry.handler_invocations,
    )
