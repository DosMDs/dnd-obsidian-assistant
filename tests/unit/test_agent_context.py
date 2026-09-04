"""Tests for the compact Fast-Agent context builder (S9-01).

Tests cover:

- Input validation boundary
- Search integration
- Entity materialisation and de-duplication
- Player-visibility defence in depth
- Current world time
- Active session and recent events
- Determinism and immutability
- Forbidden behaviour (no writes, no model, no tools)
- Fresh-process import isolation
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from dnd_assistant.application.agent_context import (
    _MAX_RELEVANT_ENTITIES,
    AgentContext,
    AgentContextBuilder,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.retrieval.types import MatchKind, SearchHit
from dnd_assistant.storage.types import VaultDocument

if TYPE_CHECKING:
    from dnd_assistant.domain.types import EntityId
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.session_metadata import RawSessionMetadata


# ── Constants ──────────────────────────────────────────────────────────────────

_MAX_ENTITY_BODY = 1000
_MAX_EVENT_TEXT = 400

# Sentinel for "text field missing from event extras"
_TEXT_MISSING: object = object()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_entity(
    *,
    entity_id: str = "npc_gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Гэндальф",
    status: str = "active",
    visibility: Visibility = Visibility.PLAYER,
    knowledge_status: KnowledgeStatus = KnowledgeStatus.CONFIRMED,
    tags: list[str] | None = None,
) -> Entity:
    """Create a minimal Entity for testing."""
    now = datetime.now(UTC)
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status=status,
        visibility=visibility,
        knowledge_status=knowledge_status,
        created_at=now,
        updated_at=now,
        revision=1,
        tags=tags or [],
    )


def _make_document(
    *,
    entity_id: str = "npc_gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Гэндальф",
    status: str = "active",
    visibility: Visibility = Visibility.PLAYER,
    knowledge_status: KnowledgeStatus = KnowledgeStatus.CONFIRMED,
    tags: list[str] | None = None,
    body: str = "",
) -> VaultDocument:
    """Create a minimal VaultDocument for testing."""
    entity = _make_entity(
        entity_id=entity_id,
        entity_type=entity_type,
        name=name,
        status=status,
        visibility=visibility,
        knowledge_status=knowledge_status,
        tags=tags,
    )
    return VaultDocument(entity=entity, body=body)


def _make_event(
    *,
    event_id: str = "evt_001",
    world_tick: int = 100,
    event_type: str = "note",
    text: object = _TEXT_MISSING,
) -> RawSessionEvent:
    """Create a minimal RawSessionEvent for testing.

    When ``text`` is ``_TEXT_MISSING`` (the default), the ``"text"`` key
    is omitted from ``extra_fields`` — representing a structurally missing
    field.

    Pass an explicit value (including ``None``) to include ``"text"`` in
    ``extra_fields`` with that value.
    """
    from dnd_assistant.storage.session_events import RawSessionEvent

    extras: dict[str, object] = {}
    if text is not _TEXT_MISSING:
        extras["text"] = text
    return RawSessionEvent(
        event_id=event_id,
        real_time=datetime.now(UTC),
        world_tick=world_tick,
        type=event_type,
        extra_fields=extras,
    )


def _make_raw_metadata(
    *,
    session_id: str = "S001",
    world_tick_start: int = 0,
) -> RawSessionMetadata:
    """Create a minimal RawSessionMetadata for testing."""
    from dnd_assistant.domain.session import Session
    from dnd_assistant.storage.session_metadata import RawSessionMetadata

    session = Session(
        id=session_id,
        status="active",
        real_started_at=datetime.now(UTC),
        world_tick_start=world_tick_start,
        revision=1,
    )
    return RawSessionMetadata(session=session)


# ── Fake implementations ───────────────────────────────────────────────────────


class FakeSearchService:
    """Minimal SearchService fake for testing."""

    def __init__(self, hits: Sequence[SearchHit] | None = None) -> None:
        self._hits = list(hits) if hits else []
        self.last_query: object | None = None
        self.last_limit: int | None = None
        self.search_call_count: int = 0

    def search(self, query: object, *, limit: int = 20) -> Sequence[SearchHit]:
        self.last_query = query
        self.last_limit = limit
        self.search_call_count += 1
        return list(self._hits)

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        for hit in self._hits:
            if hit.entity_id == entity_id:
                return hit
        return None


class FakeVaultRepository:
    """Minimal VaultRepository fake for testing."""

    def __init__(self, documents: dict[str, VaultDocument] | None = None) -> None:
        self._documents = dict(documents) if documents else {}
        self.get_entity_call_count: int = 0

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        self.get_entity_call_count += 1
        if entity_id not in self._documents:
            raise NotFoundError(f"Entity {entity_id} not found")
        return self._documents[entity_id]

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        raise NotImplementedError("not needed for S9-01")


class FakeSessionMetadataRepository:
    """Minimal SessionMetadataRepository fake for testing."""

    def __init__(self, active: RawSessionMetadata | None = None) -> None:
        self._active = active
        self.get_active_session_call_count: int = 0

    def get_active_session(self) -> RawSessionMetadata | None:
        self.get_active_session_call_count += 1
        return self._active

    # Unused stubs required by Protocol
    def allocate_next_session_id(self) -> str:
        raise NotImplementedError

    def create_session(self, session: object, *, audit: object) -> object:
        raise NotImplementedError

    def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
        raise NotImplementedError

    def list_session_metadata(self) -> list[RawSessionMetadata]:
        raise NotImplementedError

    def close_session(self, session_id: str, *, world_tick_end: object, audit: object) -> object:
        raise NotImplementedError


class FakeSessionEventRepository:
    """Minimal SessionEventRepository fake for testing."""

    def __init__(self, events: list[RawSessionEvent] | None = None) -> None:
        self._events = list(events) if events else []
        self.last_session_id: str | None = None
        self.list_events_call_count: int = 0

    def list_events(self, session_id: str) -> list[RawSessionEvent]:
        self.last_session_id = session_id
        self.list_events_call_count += 1
        return list(self._events)

    def append_event(
        self,
        session_id: str,
        *,
        event_type: object,
        real_time: object,
        world_tick: object,
        extra_fields: object,
        audit: object,
    ) -> object:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _FakeCurrentWorldTime:
    """Minimal test-only CurrentWorldTime stand-in."""

    current_world_tick: int
    revision: int = 1


class FakeWorldTimeRepository:
    """Minimal WorldTimeRepository fake for testing."""

    def __init__(self, world_tick: int | None = None) -> None:
        self._world_tick = world_tick
        self.get_current_world_time_call_count: int = 0

    def get_current_world_time(self) -> _FakeCurrentWorldTime:
        self.get_current_world_time_call_count += 1
        if self._world_tick is None:
            raise NotFoundError("World time not initialised")
        return _FakeCurrentWorldTime(current_world_tick=self._world_tick, revision=1)

    def initialize_current_world_time(self, world_tick: object, *, audit: object) -> object:
        raise NotImplementedError

    def set_current_world_time(
        self, world_tick: object, *, expected_revision: object, audit: object
    ) -> object:
        raise NotImplementedError


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def builder() -> AgentContextBuilder:
    """Create a builder wired to empty fakes."""
    return _make_builder()


def _make_builder(
    *,
    search: FakeSearchService | None = None,
    vault: FakeVaultRepository | None = None,
    session: FakeSessionMetadataRepository | None = None,
    events: FakeSessionEventRepository | None = None,
    world_time: FakeWorldTimeRepository | None = None,
) -> AgentContextBuilder:
    """Compact builder factory to reduce repetitive construction."""
    return AgentContextBuilder(
        search_service=search or FakeSearchService(),
        vault_repository=vault or FakeVaultRepository(),
        session_repository=session or FakeSessionMetadataRepository(),
        event_repository=events or FakeSessionEventRepository(),
        world_time_repository=world_time or FakeWorldTimeRepository(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Input boundary
# ═══════════════════════════════════════════════════════════════════════════════


class TestInputValidation:
    """user_input must be a valid printable non-empty string."""

    def test_valid_string_preserved(self, builder: AgentContextBuilder) -> None:
        ctx = builder.build("кто такой Гэндальф?")
        assert ctx.user_input == "кто такой Гэндальф?"

    def test_empty_raises(self, builder: AgentContextBuilder) -> None:
        with pytest.raises(ValidationError):
            builder.build("")

    def test_whitespace_only_raises(self, builder: AgentContextBuilder) -> None:
        with pytest.raises(ValidationError):
            builder.build("   ")

    def test_non_string_raises(self, builder: AgentContextBuilder) -> None:
        with pytest.raises(ValidationError):
            builder.build(42)  # type: ignore[arg-type]

    def test_control_char_raises(self, builder: AgentContextBuilder) -> None:
        with pytest.raises(ValidationError):
            builder.build("hello\nworld")

    @pytest.mark.parametrize(
        "bad_input",
        [
            pytest.param("", id="empty"),
            pytest.param("   ", id="whitespace-only"),
            pytest.param(42, id="non-string"),
            pytest.param("hello\nworld", id="control-char"),
        ],
    )
    def test_zero_dependency_reads_on_invalid_input(self, bad_input: object) -> None:
        """Invalid user input must perform zero dependency reads across
        all five Context Builder dependencies."""
        search = FakeSearchService()
        vault = FakeVaultRepository()
        session = FakeSessionMetadataRepository()
        events = FakeSessionEventRepository()
        world_time = FakeWorldTimeRepository()
        b = _make_builder(
            search=search,
            vault=vault,
            session=session,
            events=events,
            world_time=world_time,
        )
        with pytest.raises(ValidationError):
            b.build(bad_input)  # type: ignore[arg-type]
        assert search.search_call_count == 0
        assert vault.get_entity_call_count == 0
        assert session.get_active_session_call_count == 0
        assert events.list_events_call_count == 0
        assert world_time.get_current_world_time_call_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Search integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestSearch:
    """SearchQuery construction and SearchService integration."""

    def test_search_called(self) -> None:
        from dnd_assistant.retrieval.types import SearchQuery

        search = FakeSearchService()
        _make_builder(search=search).build("Гэндальф")
        assert search.last_query is not None
        assert isinstance(search.last_query, SearchQuery)
        assert search.last_query.text == "Гэндальф"

    def test_search_called_with_limit(self) -> None:
        search = FakeSearchService()
        _make_builder(search=search).build("test")
        assert search.last_limit == _MAX_RELEVANT_ENTITIES

    def test_zero_hits_empty_entities(self, builder: AgentContextBuilder) -> None:
        ctx = builder.build("test")
        assert ctx.relevant_entities == ()

    def test_order_preserved(self) -> None:
        hits = [
            SearchHit(entity_id="npc_a", match_kind=MatchKind.EXACT_NAME),
            SearchHit(entity_id="npc_b", match_kind=MatchKind.FUZZY_NAME, score=80.0),
        ]
        vault = FakeVaultRepository(
            {
                "npc_a": _make_document(entity_id="npc_a", name="A"),
                "npc_b": _make_document(entity_id="npc_b", name="B"),
            }
        )
        ctx = _make_builder(search=FakeSearchService(hits=hits), vault=vault).build("test")
        assert [e.entity_id for e in ctx.relevant_entities] == ["npc_a", "npc_b"]

    def test_more_than_max_hits_clipped(self) -> None:
        """Builder enforces its own max even if search returns more."""
        hits = [SearchHit(entity_id=f"npc_{i}", match_kind=MatchKind.EXACT_NAME) for i in range(10)]
        vault = FakeVaultRepository(
            {f"npc_{i}": _make_document(entity_id=f"npc_{i}", name=str(i)) for i in range(10)}
        )
        ctx = _make_builder(search=FakeSearchService(hits=hits), vault=vault).build("test")
        assert len(ctx.relevant_entities) == _MAX_RELEVANT_ENTITIES

    def test_exact_search_query_preserved(self) -> None:
        """SearchQuery receives the exact original input with preserved
        whitespace; limit is _MAX_RELEVANT_ENTITIES."""
        from dnd_assistant.retrieval.types import SearchQuery

        original = "  Гэндальф?  "
        search = FakeSearchService()
        ctx = _make_builder(search=search).build(original)
        assert ctx.user_input == original
        assert isinstance(search.last_query, SearchQuery)
        assert search.last_query.text == original
        assert search.last_limit == _MAX_RELEVANT_ENTITIES

    def test_duplicate_ids_first_only(self) -> None:
        """Duplicate entity IDs: only the first occurrence is included."""
        hits = [
            SearchHit(entity_id="npc_a", match_kind=MatchKind.EXACT_NAME),
            SearchHit(entity_id="npc_a", match_kind=MatchKind.FUZZY_NAME, score=90.0),
            SearchHit(entity_id="npc_b", match_kind=MatchKind.EXACT_NAME),
        ]
        vault = FakeVaultRepository(
            {
                "npc_a": _make_document(entity_id="npc_a", name="A"),
                "npc_b": _make_document(entity_id="npc_b", name="B"),
            }
        )
        ctx = _make_builder(search=FakeSearchService(hits=hits), vault=vault).build("test")
        assert [e.entity_id for e in ctx.relevant_entities] == ["npc_a", "npc_b"]


# ═══════════════════════════════════════════════════════════════════════════════
# Entity materialisation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntityMaterialisation:
    """Entity fields are copied correctly."""

    def test_canonical_fields_copied(self) -> None:
        doc = _make_document(
            entity_id="npc_gandalf",
            entity_type=EntityType.NPC,
            name="Гэндальф Серый",
            status="active",
            knowledge_status=KnowledgeStatus.CONFIRMED,
            tags=["magic", "istari"],
            body="Описание Гэндальфа.",
        )
        vault = FakeVaultRepository({"npc_gandalf": doc})
        search = FakeSearchService(
            hits=[SearchHit(entity_id="npc_gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        ctx = _make_builder(search=search, vault=vault).build("Гэндальф")
        assert len(ctx.relevant_entities) == 1
        ent = ctx.relevant_entities[0]
        assert ent.entity_id == "npc_gandalf"
        assert ent.entity_type == EntityType.NPC
        assert ent.name == "Гэндальф Серый"
        assert ent.status == "active"
        assert ent.knowledge_status == KnowledgeStatus.CONFIRMED

    def test_tag_order_preserved(self) -> None:
        doc = _make_document(tags=["magic", "istari", "wizard"])
        vault = FakeVaultRepository({"npc_gandalf": doc})
        search = FakeSearchService(
            hits=[SearchHit(entity_id="npc_gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        ctx = _make_builder(search=search, vault=vault).build("test")
        assert ctx.relevant_entities[0].tags == ("magic", "istari", "wizard")

    def test_body_exact_no_truncation(self) -> None:
        body = "Короткое описание."
        doc = _make_document(body=body)
        vault = FakeVaultRepository({"npc_gandalf": doc})
        search = FakeSearchService(
            hits=[SearchHit(entity_id="npc_gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        ctx = _make_builder(search=search, vault=vault).build("test")
        ent = ctx.relevant_entities[0]
        assert ent.body_excerpt == body
        assert ent.body_truncated is False

    def test_body_long_truncated(self) -> None:
        body = "x" * (_MAX_ENTITY_BODY + 50)
        doc = _make_document(body=body)
        vault = FakeVaultRepository({"npc_gandalf": doc})
        search = FakeSearchService(
            hits=[SearchHit(entity_id="npc_gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        ctx = _make_builder(search=search, vault=vault).build("test")
        ent = ctx.relevant_entities[0]
        assert ent.body_excerpt == body[:_MAX_ENTITY_BODY]
        assert ent.body_truncated is True

    def test_stale_hit_not_found_skipped(self) -> None:
        """A SearchHit whose entity is no longer in the Vault is skipped."""
        hits = [
            SearchHit(entity_id="npc_stale", match_kind=MatchKind.EXACT_NAME),
            SearchHit(entity_id="npc_valid", match_kind=MatchKind.EXACT_NAME),
        ]
        vault = FakeVaultRepository(
            {
                "npc_valid": _make_document(entity_id="npc_valid", name="Valid"),
            }
        )
        ctx = _make_builder(search=FakeSearchService(hits=hits), vault=vault).build("test")
        assert [e.entity_id for e in ctx.relevant_entities] == ["npc_valid"]

    def test_storage_error_not_swallowed(self) -> None:
        """StorageError from get_entity is propagated, not silently caught."""

        class _FailingVault(FakeVaultRepository):
            def get_entity(self, entity_id: EntityId) -> VaultDocument:
                raise StorageError("Disk failure")

        hits = [SearchHit(entity_id="npc_a", match_kind=MatchKind.EXACT_NAME)]
        with pytest.raises(StorageError):
            _make_builder(
                search=FakeSearchService(hits=hits),
                vault=_FailingVault(),
            ).build("test")


# ═══════════════════════════════════════════════════════════════════════════════
# Visibility safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestVisibilityDefence:
    """Player-visibility defence in depth."""

    def test_player_eligible(self) -> None:
        doc = _make_document(visibility=Visibility.PLAYER, name="Видимый")
        ctx = _make_builder(
            search=FakeSearchService(
                hits=[SearchHit(entity_id="npc_visible", match_kind=MatchKind.EXACT_NAME)]
            ),
            vault=FakeVaultRepository({"npc_visible": doc}),
        ).build("test")
        assert len(ctx.relevant_entities) == 1
        assert ctx.relevant_entities[0].name == "Видимый"

    @pytest.mark.parametrize("visibility", [Visibility.DM, Visibility.SYSTEM])
    def test_non_player_skipped(self, visibility: Visibility) -> None:
        doc = _make_document(visibility=visibility)
        ctx = _make_builder(
            search=FakeSearchService(
                hits=[SearchHit(entity_id="npc_x", match_kind=MatchKind.EXACT_NAME)]
            ),
            vault=FakeVaultRepository({"npc_x": doc}),
        ).build("test")
        assert len(ctx.relevant_entities) == 0

    def test_plain_string_player_fails_closed(self) -> None:
        """A plain string 'player' must NOT expose entity info."""
        doc = _make_document(visibility=Visibility.PLAYER, name="Тест")
        object.__setattr__(doc.entity, "visibility", "player")
        ctx = _make_builder(
            search=FakeSearchService(
                hits=[SearchHit(entity_id="npc_test", match_kind=MatchKind.EXACT_NAME)]
            ),
            vault=FakeVaultRepository({"npc_test": doc}),
        ).build("test")
        assert len(ctx.relevant_entities) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# World time
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorldTime:
    """Current world time integration."""

    def test_initialized_world_tick(self) -> None:
        ctx = _make_builder(world_time=FakeWorldTimeRepository(world_tick=12345)).build("test")
        assert ctx.current_world_tick == 12345

    def test_not_found_returns_none(self) -> None:
        ctx = _make_builder(world_time=FakeWorldTimeRepository(world_tick=None)).build("test")
        assert ctx.current_world_tick is None

    def test_storage_error_propagated(self) -> None:
        class _FailingWT(FakeWorldTimeRepository):
            def get_current_world_time(self) -> object:
                raise StorageError("Corrupt world time file")

        with pytest.raises(StorageError):
            _make_builder(world_time=_FailingWT()).build("test")


# ═══════════════════════════════════════════════════════════════════════════════
# Active session
# ═══════════════════════════════════════════════════════════════════════════════


class TestActiveSession:
    """Active session integration."""

    def test_no_active_session(self) -> None:
        event_repo = FakeSessionEventRepository()
        ctx = _make_builder(
            session=FakeSessionMetadataRepository(active=None),
            events=event_repo,
        ).build("test")
        assert ctx.active_session is None
        assert ctx.recent_events == ()
        assert event_repo.last_session_id is None

    def test_active_session_fields(self) -> None:
        raw = _make_raw_metadata(session_id="S042", world_tick_start=5000)
        ctx = _make_builder(
            session=FakeSessionMetadataRepository(active=raw),
        ).build("test")
        assert ctx.active_session is not None
        assert ctx.active_session.session_id == "S042"
        assert ctx.active_session.world_tick_start == 5000


# ═══════════════════════════════════════════════════════════════════════════════
# Recent events
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecentEvents:
    """Recent active-session events."""

    def test_zero_events(self) -> None:
        raw = _make_raw_metadata()
        ctx = _make_builder(
            session=FakeSessionMetadataRepository(active=raw),
            events=FakeSessionEventRepository(events=[]),
        ).build("test")
        assert ctx.recent_events == ()

    def test_one_to_five_events(self) -> None:
        events = [_make_event(event_id=f"evt_{i:03d}", world_tick=i * 10) for i in range(1, 4)]
        raw = _make_raw_metadata()
        ctx = _make_builder(
            session=FakeSessionMetadataRepository(active=raw),
            events=FakeSessionEventRepository(events=events),
        ).build("test")
        assert len(ctx.recent_events) == 3
        assert [e.event_id for e in ctx.recent_events] == ["evt_001", "evt_002", "evt_003"]

    def test_more_than_five_tail(self) -> None:
        events = [_make_event(event_id=f"evt_{i:03d}", world_tick=i * 10) for i in range(1, 8)]
        raw = _make_raw_metadata()
        ctx = _make_builder(
            session=FakeSessionMetadataRepository(active=raw),
            events=FakeSessionEventRepository(events=events),
        ).build("test")
        assert len(ctx.recent_events) == 5
        assert [e.event_id for e in ctx.recent_events] == [
            "evt_003",
            "evt_004",
            "evt_005",
            "evt_006",
            "evt_007",
        ]

    def test_event_fields(self) -> None:
        ev = _make_event(event_id="evt_001", world_tick=100, event_type="note", text="Привет мир")
        raw = _make_raw_metadata()
        ctx = _make_builder(
            session=FakeSessionMetadataRepository(active=raw),
            events=FakeSessionEventRepository(events=[ev]),
        ).build("test")
        assert len(ctx.recent_events) == 1
        e = ctx.recent_events[0]
        assert e.event_id == "evt_001"
        assert e.event_type == "note"
        assert e.world_tick == 100
        assert e.text_excerpt == "Привет мир"
        assert e.text_truncated is False


# ═══════════════════════════════════════════════════════════════════════════════
# Event text structural states
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventText:
    """Event ``text`` field structural equivalence classes (MNT-04)."""

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_with_event(text_value: object = _TEXT_MISSING) -> AgentContext:
        raw = _make_raw_metadata()
        return _make_builder(
            session=FakeSessionMetadataRepository(active=raw),
            events=FakeSessionEventRepository(events=[_make_event(text=text_value)]),
        ).build("test")

    # ── Missing key ────────────────────────────────────────────────────────

    def test_text_missing(self) -> None:
        """Field missing from extra_fields -> text_excerpt is None."""
        ctx = self._build_with_event(_TEXT_MISSING)
        ev = ctx.recent_events[0]
        assert ev.text_excerpt is None
        assert ev.text_truncated is False

    # ── Present None ───────────────────────────────────────────────────────

    def test_text_present_none(self) -> None:
        """Field present with explicit None -> text_excerpt is None."""
        ctx = self._build_with_event(None)
        ev = ctx.recent_events[0]
        # Prove the source event actually contains "text": None
        source = _make_event(text=None)
        assert "text" in source.extra_fields
        assert source.extra_fields["text"] is None
        assert ev.text_excerpt is None
        assert ev.text_truncated is False

    # ── Present empty string ───────────────────────────────────────────────

    def test_text_empty_string(self) -> None:
        """Field present with '' -> text_excerpt == ''."""
        ctx = self._build_with_event("")
        ev = ctx.recent_events[0]
        assert ev.text_excerpt == ""
        assert ev.text_truncated is False

    # ── Present non-string types (all produce None) ────────────────────────

    @pytest.mark.parametrize(
        "wrong_val",
        [
            pytest.param(0, id="zero"),
            pytest.param(False, id="false"),
            pytest.param([], id="empty-list"),
            pytest.param({}, id="empty-dict"),
        ],
    )
    def test_text_non_string_types(self, wrong_val: object) -> None:
        """Non-string types -> text_excerpt is None."""
        ctx = self._build_with_event(wrong_val)
        ev = ctx.recent_events[0]
        assert ev.text_excerpt is None
        assert ev.text_truncated is False

    # ── Valid short string ─────────────────────────────────────────────────

    def test_text_valid_short(self) -> None:
        """Valid short string preserved exactly."""
        text = "Привет мир"
        ctx = self._build_with_event(text)
        ev = ctx.recent_events[0]
        assert ev.text_excerpt == text
        assert ev.text_truncated is False

    # ── Long string clipped ────────────────────────────────────────────────

    def test_text_long_clipped(self) -> None:
        """String > 400 chars -> first 400 chars, text_truncated=True."""
        long_text = "x" * (_MAX_EVENT_TEXT + 50)
        ctx = self._build_with_event(long_text)
        ev = ctx.recent_events[0]
        assert ev.text_excerpt == long_text[:_MAX_EVENT_TEXT]
        assert ev.text_truncated is True


# ═══════════════════════════════════════════════════════════════════════════════
# Determinism and immutability
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """Context builder determinism and immutability."""

    def test_identical_reads_equal(self) -> None:
        hits = [SearchHit(entity_id="npc_a", match_kind=MatchKind.EXACT_NAME)]
        doc = _make_document(entity_id="npc_a", name="A")
        vault = FakeVaultRepository({"npc_a": doc})
        search = FakeSearchService(hits=hits)
        wt_repo = FakeWorldTimeRepository(world_tick=100)
        raw = _make_raw_metadata()

        def _make() -> AgentContext:
            return _make_builder(
                search=search,
                vault=vault,
                session=FakeSessionMetadataRepository(active=raw),
                world_time=wt_repo,
            ).build("test")

        assert _make() == _make()

    def test_returned_collections_are_tuples(self) -> None:
        ctx = _make_builder().build("test")
        assert isinstance(ctx.relevant_entities, tuple)
        assert isinstance(ctx.recent_events, tuple)

    def test_source_objects_unchanged(self) -> None:
        """Builder must not mutate source documents."""
        doc = _make_document(body="original body")
        vault = FakeVaultRepository({"npc_gandalf": doc})
        _make_builder(
            search=FakeSearchService(
                hits=[SearchHit(entity_id="npc_gandalf", match_kind=MatchKind.EXACT_NAME)]
            ),
            vault=vault,
        ).build("test")
        assert doc.body == "original body"

    def test_first_hit_dedupe_deterministic(self) -> None:
        """Duplicate IDs always resolve to the first occurrence."""
        hits = [
            SearchHit(entity_id="npc_a", match_kind=MatchKind.EXACT_NAME),
            SearchHit(entity_id="npc_a", match_kind=MatchKind.FUZZY_NAME, score=90.0),
        ]
        vault = FakeVaultRepository({"npc_a": _make_document(entity_id="npc_a", name="A")})
        ctx = _make_builder(
            search=FakeSearchService(hits=hits),
            vault=vault,
        ).build("test")
        assert len(ctx.relevant_entities) == 1
        assert ctx.relevant_entities[0].entity_id == "npc_a"


# ═══════════════════════════════════════════════════════════════════════════════
# Forbidden behaviour
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoForbiddenBehavior:
    """Context Builder must not perform writes, model calls, or tool work."""

    def test_no_writes(self) -> None:
        """Verification: build() calls only read methods."""
        import inspect

        from dnd_assistant.application import agent_context

        source = inspect.getsource(agent_context.AgentContextBuilder.build)
        write_indicators = [
            "create_entity",
            "patch_entity",
            "append_entity_fact",
            "create_session",
            "close_session",
            "append_event",
            "initialize_current_world_time",
            "set_current_world_time",
        ]
        for indicator in write_indicators:
            assert indicator not in source, f"build() references write method: {indicator}"

    def test_no_model_gateway(self) -> None:
        import inspect

        from dnd_assistant.application import agent_context

        source = inspect.getsource(agent_context)
        # The docstring mentions ModelGateway as a deferral note;
        # check that no runtime import or reference exists outside TYPE_CHECKING.
        lines = source.splitlines()
        runtime_lines = [
            line
            for line in lines
            if "TYPE_CHECKING" not in line and not line.strip().startswith("#")
        ]
        runtime_source = "\n".join(runtime_lines)
        assert "ChatMessage" not in runtime_source
        assert "ChatRequest" not in runtime_source
        assert "ToolAwareResponse" not in runtime_source

    def test_no_tool_executor(self) -> None:
        import inspect

        from dnd_assistant.application import agent_context

        source = inspect.getsource(agent_context)
        assert "ToolExecutor" not in source
        assert "select_agent_tools" not in source


# ═══════════════════════════════════════════════════════════════════════════════
# Fresh-process import isolation
# ═══════════════════════════════════════════════════════════════════════════════


def test_fresh_process_import_isolation() -> None:
    """Importing agent_context in a fresh process must not eagerly load
    dnd_assistant.models, dnd_assistant.tools, or dnd_assistant.cli."""
    code = """import sys
sys.modules.pop('dnd_assistant.application.agent_context', None)
import dnd_assistant.application.agent_context
forbidden = ['dnd_assistant.models', 'dnd_assistant.tools', 'dnd_assistant.cli']
loaded = [m for m in sys.modules if any(m.startswith(f) or m == f for f in forbidden)]
if loaded:
    print('FAIL: forbidden packages loaded:', loaded)
    sys.exit(1)
else:
    print('OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Fresh import failed: {result.stderr}"
    assert "OK" in result.stdout
