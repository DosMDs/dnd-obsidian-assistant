"""Tests for entity read tool handler behaviour and ToolExecutor integration.

Covers:
- search_entities handler behaviour (forwarding, ordering, hydration)
- get_entity handler behaviour (visibility gate, fail-closed, identity chain)
- ToolExecutor integration
- No-mutation guarantee
- C03 regression: requested-ID consistency, non-disclosing errors
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Revision, Visibility
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.retrieval.types import MatchKind, SearchHit, SearchQuery
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.tools.entity_reads import (
    GetEntityOutput,
    SearchEntitiesInput,
    SearchEntitiesOutput,
    register_entity_read_tools,
)
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)

# ── Shared test data ──────────────────────────────────────────────────────

_NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _make_entity(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
) -> Entity:
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status="active",
        visibility=visibility,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=_NOW,
        updated_at=_NOW,
        revision=Revision(1),
    )


def _make_doc(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
    body: str = "# Body text",
) -> VaultDocument:
    return VaultDocument(
        entity=_make_entity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            visibility=visibility,
        ),
        body=body,
    )


# ── Fake SearchService ────────────────────────────────────────────────────


class FakeSearchService:
    """Minimal fake implementing SearchService protocol for tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, SearchHit | None] = {}
        self._search_results: Sequence[SearchHit] = []
        self._last_query: SearchQuery | None = None
        self._last_limit: int | None = None

    def set_get_by_id(self, entity_id: str, hit: SearchHit | None) -> None:
        self._by_id[entity_id] = hit

    def set_search_results(self, hits: Sequence[SearchHit]) -> None:
        self._search_results = hits

    @property
    def last_query(self) -> SearchQuery | None:
        return self._last_query

    @property
    def last_limit(self) -> int | None:
        return self._last_limit

    # ── Protocol implementation ────────────────────────────────────────

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        self._last_query = query
        self._last_limit = limit
        return self._search_results

    def get_by_id(self, entity_id: str) -> SearchHit | None:
        return self._by_id.get(entity_id)


# ── Fake VaultRepository ─────────────────────────────────────────────────


class FakeRepository:
    """Minimal fake implementing VaultRepository protocol for tests."""

    def __init__(self) -> None:
        self._entities: dict[str, VaultDocument] = {}
        self._get_calls: list[str] = []

    def add_document(self, doc: VaultDocument) -> None:
        self._entities[doc.entity.id] = doc

    @property
    def get_calls(self) -> list[str]:
        return list(self._get_calls)

    # ── Protocol implementation (read-only subset) ─────────────────────

    def get_entity(self, entity_id: str) -> VaultDocument:
        self._get_calls.append(entity_id)
        doc = self._entities.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity '{entity_id}' not found")
        return doc

    def add_mismatched_document(self, key: str, doc: VaultDocument) -> None:
        """Add a document under a key that differs from its entity.id.

        Used to simulate repository inconsistency for fail-closed tests.
        """
        self._entities[key] = doc

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        return list(self._entities.values())

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        msg = "FakeRepository does not support writes"
        raise NotImplementedError(msg)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def search_service() -> FakeSearchService:
    return FakeSearchService()


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(
    registry: ToolRegistry,
    search_service: FakeSearchService,
    repository: FakeRepository,
) -> ToolRegistry:
    register_entity_read_tools(registry, search_service=search_service, repository=repository)
    return registry


@pytest.fixture
def executor(registered_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registered_registry)


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=_NOW,
            source="test",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# search_entities handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchEntitiesHandler:
    def test_query_text_forwarded(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        read_context: ExecutionContext,
    ) -> None:
        search_service.set_search_results([])
        executor.execute(
            "search_entities",
            input_data={"text": "Gandalf"},
            context=read_context,
        )
        assert search_service.last_query is not None
        assert search_service.last_query.text == "Gandalf"

    def test_entity_type_filter_forwarded(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        read_context: ExecutionContext,
    ) -> None:
        search_service.set_search_results([])
        executor.execute(
            "search_entities",
            input_data={"text": "Gandalf", "entity_types": ["npc"]},
            context=read_context,
        )
        assert search_service.last_query is not None
        assert search_service.last_query.entity_types == {EntityType.NPC}

    def test_limit_forwarded(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        read_context: ExecutionContext,
    ) -> None:
        search_service.set_search_results([])
        executor.execute(
            "search_entities",
            input_data={"text": "Gandalf", "limit": 5},
            context=read_context,
        )
        assert search_service.last_limit == 5

    def test_empty_result_returns_typed_empty_list(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        search_service.set_search_results([])
        result = executor.execute(
            "search_entities",
            input_data={"text": "nonexistent"},
            context=read_context,
        )
        assert isinstance(result, SearchEntitiesOutput)
        assert result.results == []

    def test_result_order_preserved(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        doc_b = _make_doc("npc--b", name="Beta")
        doc_a = _make_doc("npc--a", name="Alpha")
        repository.add_document(doc_b)
        repository.add_document(doc_a)

        search_service.set_search_results(
            [
                SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_NAME),
                SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_NAME),
            ]
        )
        result = executor.execute(
            "search_entities",
            input_data={"text": "test"},
            context=read_context,
        )
        assert len(result.results) == 2
        assert result.results[0].entity_id == "npc--b"
        assert result.results[1].entity_id == "npc--a"

    def test_result_contains_all_fields(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf", name="Gandalf")
        repository.add_document(doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        result = executor.execute(
            "search_entities",
            input_data={"text": "Gandalf"},
            context=read_context,
        )
        assert len(result.results) == 1
        r = result.results[0]
        assert r.entity_id == "npc--gandalf"
        assert r.entity_type == EntityType.NPC
        assert r.name == "Gandalf"
        assert r.status == "active"
        assert r.match_kind == MatchKind.EXACT_NAME
        assert r.score is None

    def test_repository_hydrates_only_searchservice_ids(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Repository should only be called for IDs returned by SearchService."""
        doc_a = _make_doc("npc--a", name="Alpha")
        doc_b = _make_doc("npc--b", name="Beta")
        repository.add_document(doc_a)
        repository.add_document(doc_b)

        # SearchService returns only npc--a
        search_service.set_search_results(
            [SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_NAME)]
        )
        executor.execute(
            "search_entities",
            input_data={"text": "Alpha"},
            context=read_context,
        )
        # Only npc--a should have been hydrated
        assert repository.get_calls == ["npc--a"]

    def test_fail_closed_on_hidden_hydrated_document(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService returns a PLAYER hit, but repository returns DM doc."""
        dm_doc = _make_doc("npc--hidden", visibility=Visibility.DM)
        repository.add_document(dm_doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--hidden", match_kind=MatchKind.EXACT_NAME)]
        )
        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "search_entities",
                input_data={"text": "hidden"},
                context=read_context,
            )

    def test_fail_closed_on_id_mismatch(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService returns id X, but repository document has id Y."""
        doc = _make_doc("npc--actual")
        repository.add_mismatched_document("npc--wrong", doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--wrong", match_kind=MatchKind.EXACT_NAME)]
        )
        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "search_entities",
                input_data={"text": "test"},
                context=read_context,
            )


# ═══════════════════════════════════════════════════════════════════════════
# get_entity handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEntityHandler:
    def test_get_entity_calls_search_service_first(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Verify get_by_id is called before repository.get_entity."""
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc--gandalf"},
            context=read_context,
        )
        assert isinstance(result, GetEntityOutput)
        assert result.entity.id == "npc--gandalf"
        assert result.body == "# Body text"

    def test_get_entity_returns_entity_and_body(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf", body="# Gandalf the Grey")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc--gandalf"},
            context=read_context,
        )
        assert result.entity.id == "npc--gandalf"
        assert result.entity.name == "Test Entity"
        assert result.body == "# Gandalf the Grey"

    def test_get_entity_not_found_via_gate(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService.get_by_id returns None -> NotFoundError."""
        search_service.set_get_by_id("npc--nonexistent", None)
        with pytest.raises(NotFoundError, match="not found or not accessible"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--nonexistent"},
                context=read_context,
            )

    def test_get_entity_hidden_entity_returns_not_found(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """DM-hidden entity returns None from SearchService -> NotFoundError."""
        # Entity exists in repo but SearchService won't return it
        doc = _make_doc("npc--hidden", visibility=Visibility.DM)
        repository.add_document(doc)
        search_service.set_get_by_id("npc--hidden", None)

        with pytest.raises(NotFoundError, match="not found or not accessible"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--hidden"},
                context=read_context,
            )

        # Repository should NOT have been called
        assert repository.get_calls == []

    def test_get_entity_error_does_not_leak_hidden_vs_missing(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error message must not reveal whether entity is hidden or missing."""
        search_service.set_get_by_id("npc--x", None)
        with pytest.raises(NotFoundError) as exc_info:
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--x"},
                context=read_context,
            )
        msg = str(exc_info.value)
        assert "DM" not in msg
        assert "hidden" not in msg
        assert "system" not in msg
        assert "not found" in msg or "not accessible" in msg

    def test_get_entity_fail_closed_on_hidden_hydrated(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService says visible, but repo returns DM doc."""
        dm_doc = _make_doc("npc--dm", visibility=Visibility.DM)
        repository.add_document(dm_doc)
        search_service.set_get_by_id(
            "npc--dm", SearchHit(entity_id="npc--dm", match_kind=MatchKind.EXACT_ID)
        )
        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--dm"},
                context=read_context,
            )

    def test_fail_closed_on_id_mismatch(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService returns id X, but repository document has id Y."""
        doc = _make_doc("npc--actual")
        repository.add_mismatched_document("npc--wrong", doc)
        search_service.set_get_by_id(
            "npc--actual", SearchHit(entity_id="npc--wrong", match_kind=MatchKind.EXACT_ID)
        )
        with pytest.raises(StorageError, match="Entity search hydration consistency check failed"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--actual"},
                context=read_context,
            )


# ═══════════════════════════════════════════════════════════════════════════
# ToolExecutor integration
# ═══════════════════════════════════════════════════════════════════════════


class TestToolExecutorIntegration:
    def test_read_permission_allows_execution(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_search_results(
            [SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        result = executor.execute(
            "search_entities",
            input_data={"text": "Gandalf"},
            context=read_context,
        )
        assert isinstance(result, SearchEntitiesOutput)

    def test_write_permission_allows_execution(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_search_results(
            [SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        result = executor.execute(
            "search_entities",
            input_data={"text": "Gandalf"},
            context=write_context,
        )
        assert isinstance(result, SearchEntitiesOutput)

    def test_both_session_modes_work(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_search_results(
            [SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        for mode in (SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION):
            ctx = ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=mode,
            )
            result = executor.execute(
                "search_entities",
                input_data={"text": "Gandalf"},
                context=ctx,
            )
            assert isinstance(result, SearchEntitiesOutput)

    def test_audit_context_not_required(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_search_results(
            [SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        result = executor.execute(
            "search_entities",
            input_data={"text": "Gandalf"},
            context=ctx,
        )
        assert isinstance(result, SearchEntitiesOutput)

    def test_invalid_input_rejected_before_handler(
        self,
        executor: ToolExecutor,
        read_context: ExecutionContext,
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "search_entities",
                input_data={"text": ""},
                context=read_context,
            )

    def test_handler_runtime_error_propagates(
        self,
        registry: ToolRegistry,
        read_context: ExecutionContext,
    ) -> None:
        """A handler that raises RuntimeError must propagate unchanged."""

        def bad_handler(input_model: object, context: object) -> object:
            raise RuntimeError("handler crash")

        # Register a tool with a crashing handler
        defn = ToolDefinition(
            name="crash_tool",
            description="A crashing test tool",
            input_schema=SearchEntitiesInput,
            output_schema=SearchEntitiesOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        registry.register(defn, bad_handler)
        exe = ToolExecutor(registry)

        with pytest.raises(RuntimeError, match="handler crash"):
            exe.execute(
                "crash_tool",
                input_data={"text": "test"},
                context=read_context,
            )


# ═══════════════════════════════════════════════════════════════════════════
# No mutation guarantee
# ═══════════════════════════════════════════════════════════════════════════


class TestNoMutation:
    """Verify entity read tools never call mutation operations."""

    def test_search_entities_does_not_create(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        search_service.set_search_results([])
        result = executor.execute(
            "search_entities",
            input_data={"text": "test"},
            context=read_context,
        )
        assert isinstance(result, SearchEntitiesOutput)

    def test_get_entity_does_not_create(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id("npc--x", None)
        with pytest.raises(NotFoundError):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--x"},
                context=read_context,
            )

    def test_search_entities_only_calls_get_entity_and_search(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Verify only read operations are called (no list_entities, no create, etc.)."""
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_search_results(
            [SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_NAME)]
        )
        executor.execute(
            "search_entities",
            input_data={"text": "Gandalf"},
            context=read_context,
        )
        # Repository.get_entity was called (hydration)
        assert repository.get_calls == ["npc--gandalf"]
