"""Tests for entity read tool safety: identity-chain and non-disclosing errors.

Covers C03 regression tests:
- get_entity requested-ID consistency (requested A -> hit B)
- get_entity hydrated-ID consistency (requested A -> hit A -> doc B)
- get_entity hydrated visibility check (requested A -> hit A -> DM/SYSTEM doc)
- search_entities hydration consistency (hit ID -> different doc ID)
- search_entities hydrated visibility check (hit -> DM/SYSTEM doc)
- Non-disclosing error messages for all consistency failures
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Revision, Visibility
from dnd_assistant.errors import NotFoundError, StorageError
from dnd_assistant.retrieval.types import MatchKind, SearchHit
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.tools.entity_reads import (
    GetEntityOutput,
    SearchEntitiesOutput,
    register_entity_read_tools,
)
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
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
        self._search_results: list[SearchHit] = []

    def set_get_by_id(self, entity_id: str, hit: SearchHit | None) -> None:
        self._by_id[entity_id] = hit

    def set_search_results(self, hits: list[SearchHit]) -> None:
        self._search_results = hits

    def search(self, query: object, *, limit: int = 20) -> list[SearchHit]:
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

    def add_mismatched_document(self, key: str, doc: VaultDocument) -> None:
        self._entities[key] = doc

    @property
    def get_calls(self) -> list[str]:
        return list(self._get_calls)

    def get_entity(self, entity_id: str) -> VaultDocument:
        self._get_calls.append(entity_id)
        doc = self._entities.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity '{entity_id}' not found")
        return doc

    def list_entities(self, entity_type: object = None) -> list[VaultDocument]:
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


# ═══════════════════════════════════════════════════════════════════════════
# get_entity: requested-ID consistency
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEntityRequestedIdConsistency:
    """Verify get_entity enforces requested-ID == SearchHit-ID consistency."""

    def test_requested_a_hit_b_raises_storage_error(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Requested A, but SearchService returns hit for B -> StorageError."""
        doc_b = _make_doc("npc--b", name="Entity B")
        repository.add_document(doc_b)

        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError, match="Entity search hydration consistency check failed"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

    def test_requested_a_hit_b_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """When requested A -> hit B, repository must NOT be called."""
        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

        assert repository.get_calls == []

    def test_requested_a_hit_b_error_does_not_reveal_b(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error for requested A -> hit B must not reveal B's ID."""
        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

        msg = str(exc_info.value)
        assert "npc--b" not in msg

    def test_gate_none_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """When gate returns None, repository must NOT be called."""
        search_service.set_get_by_id("npc--x", None)

        with pytest.raises(NotFoundError):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--x"},
                context=read_context,
            )

        assert repository.get_calls == []


# ═══════════════════════════════════════════════════════════════════════════
# get_entity: hydrated-document consistency
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEntityHydratedConsistency:
    """Verify get_entity checks hydrated document ID and visibility."""

    def test_requested_a_hit_a_hydrated_b_raises_storage_error(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Requested A -> hit A -> repository returns doc with ID B -> StorageError."""
        doc_b = _make_doc("npc--b", name="Entity B")
        repository.add_mismatched_document("npc--a", doc_b)

        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

    def test_requested_a_hit_a_hydrated_b_error_does_not_reveal_b(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error for hydrated ID mismatch must not reveal the alternate ID."""
        doc_b = _make_doc("npc--b", name="Entity B")
        repository.add_mismatched_document("npc--a", doc_b)

        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

        msg = str(exc_info.value)
        assert "npc--b" not in msg

    def test_requested_a_hit_a_hydrated_dm_system_raises_storage_error(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Requested A -> hit A -> repository returns DM/SYSTEM doc -> StorageError."""
        dm_doc = _make_doc("npc--a", visibility=Visibility.DM)
        repository.add_document(dm_doc)

        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

    def test_hydrated_dm_error_does_not_reveal_visibility(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error for hydrated DM doc must not reveal dm/system/hidden."""
        dm_doc = _make_doc("npc--a", visibility=Visibility.DM)
        repository.add_document(dm_doc)

        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_ID)
        )

        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc--a"},
                context=read_context,
            )

        msg = str(exc_info.value)
        assert "DM" not in msg
        assert "dm" not in msg
        assert "system" not in msg
        assert "hidden" not in msg

    def test_requested_a_hit_a_player_a_returns_success(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Requested A -> hit A -> PLAYER A -> successful typed result."""
        doc = _make_doc("npc--a", name="Entity A")
        repository.add_document(doc)

        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--a", match_kind=MatchKind.EXACT_ID)
        )

        result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc--a"},
            context=read_context,
        )
        assert isinstance(result, GetEntityOutput)
        assert result.entity.id == "npc--a"
        assert result.entity.name == "Entity A"


# ═══════════════════════════════════════════════════════════════════════════
# search_entities: hydration consistency and non-disclosing errors
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchHydrationConsistency:
    """Verify search hydration consistency checks and non-disclosing errors."""

    def test_search_hit_id_hydrated_different_id_raises_storage_error(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService hit ID differs from hydrated document ID -> StorageError."""
        doc = _make_doc("npc--actual")
        repository.add_mismatched_document("npc--hit", doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--hit", match_kind=MatchKind.EXACT_NAME)]
        )

        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "search_entities",
                input_data={"text": "test"},
                context=read_context,
            )

    def test_search_hit_id_hydrated_different_id_error_non_disclosing(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error must not reveal the alternate entity ID."""
        doc = _make_doc("npc--actual")
        repository.add_mismatched_document("npc--hit", doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--hit", match_kind=MatchKind.EXACT_NAME)]
        )

        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "search_entities",
                input_data={"text": "test"},
                context=read_context,
            )

        msg = str(exc_info.value)
        assert "npc--hit" not in msg
        assert "npc--actual" not in msg

    def test_search_hit_hydrated_dm_raises_storage_error(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService hit -> hydrated DM/SYSTEM doc -> StorageError."""
        dm_doc = _make_doc("npc--secret", visibility=Visibility.DM)
        repository.add_document(dm_doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--secret", match_kind=MatchKind.EXACT_NAME)]
        )

        with pytest.raises(StorageError, match="Entity read consistency check failed"):
            executor.execute(
                "search_entities",
                input_data={"text": "secret"},
                context=read_context,
            )

    def test_search_hit_hydrated_dm_error_non_disclosing(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """Error for hydrated DM doc must not reveal dm/system/hidden."""
        dm_doc = _make_doc("npc--secret", visibility=Visibility.DM)
        repository.add_document(dm_doc)

        search_service.set_search_results(
            [SearchHit(entity_id="npc--secret", match_kind=MatchKind.EXACT_NAME)]
        )

        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "search_entities",
                input_data={"text": "secret"},
                context=read_context,
            )

        msg = str(exc_info.value)
        assert "DM" not in msg
        assert "dm" not in msg
        assert "system" not in msg
        assert "hidden" not in msg
        assert "npc--secret" not in msg

    def test_search_hydrated_player_success(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        read_context: ExecutionContext,
    ) -> None:
        """SearchService hit -> hydrated PLAYER matching ID -> success."""
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
        assert isinstance(result, SearchEntitiesOutput)
        assert len(result.results) == 1
        assert result.results[0].entity_id == "npc--gandalf"
        assert result.results[0].name == "Gandalf"
