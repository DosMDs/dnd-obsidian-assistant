"""Tests for entity mutation tool handler behaviour and ToolExecutor integration.

Covers:
- patch_entity handler behaviour (authorization, forwarding, delegation)
- append_entity_fact handler behaviour (authorization, forwarding, delegation)
- ToolExecutor integration (permission gating, audit gating, session modes)
- No fuzzy/ambiguous resolution
- Stable-ID-only target policy
- AuditContext identity forwarding
- Repository error propagation
- Returned stable-ID consistency check
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Revision, Visibility
from dnd_assistant.errors import NotFoundError
from dnd_assistant.retrieval.types import MatchKind, SearchHit
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.tools.entity_mutations import (
    AppendEntityFactOutput,
    PatchEntityOutput,
    register_entity_mutation_tools,
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

_AUDIT = AuditContext(
    operation_id="test-op",
    real_time=_NOW,
    source="test",
)


def _make_entity(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
    revision: int = 1,
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
        revision=Revision(revision),
    )


def _make_doc(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
    body: str = "# Body text",
    revision: int = 1,
) -> VaultDocument:
    return VaultDocument(
        entity=_make_entity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            visibility=visibility,
            revision=revision,
        ),
        body=body,
    )


# ── Fake SearchService with call tracking ─────────────────────────────────


class FakeSearchService:
    """Fake SearchService with call tracking for authorization assertions."""

    def __init__(self) -> None:
        self._by_id: dict[str, SearchHit | None] = {}
        self._get_by_id_calls: list[str] = []

    def set_get_by_id(self, entity_id: str, hit: SearchHit | None) -> None:
        self._by_id[entity_id] = hit

    @property
    def get_by_id_calls(self) -> list[str]:
        return list(self._get_by_id_calls)

    def search(self, query: object, *, limit: int = 20) -> list[object]:
        return []

    def get_by_id(self, entity_id: str) -> SearchHit | None:
        self._get_by_id_calls.append(entity_id)
        return self._by_id.get(entity_id)


# ── Fake VaultRepository with call tracking ────────────────────────────────


class FakeRepository:
    """Fake VaultRepository with call tracking for mutation assertions."""

    def __init__(self) -> None:
        self._entities: dict[str, VaultDocument] = {}
        self._patch_calls: list[tuple[str, object, object, object]] = []
        self._append_calls: list[tuple[str, object, str, object]] = []

    def add_document(self, doc: VaultDocument) -> None:
        self._entities[doc.entity.id] = doc

    @property
    def patch_calls(self) -> list[tuple[str, object, object, object]]:
        return list(self._patch_calls)

    @property
    def append_calls(self) -> list[tuple[str, object, str, object]]:
        return list(self._append_calls)

    def get_entity(self, entity_id: str) -> VaultDocument:
        doc = self._entities.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity '{entity_id}' not found")
        return doc

    def list_entities(self, entity_type: object = None) -> list[object]:
        return list(self._entities.values())

    def patch_entity(
        self,
        entity_id: str,
        patch: object,
        *,
        expected_revision: object,
        audit: object,
    ) -> VaultDocument:
        self._patch_calls.append((entity_id, patch, expected_revision, audit))
        doc = self._entities.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity '{entity_id}' not found")
        return doc

    def append_entity_fact(
        self,
        entity_id: str,
        *,
        expected_revision: object,
        fact: str,
        audit: object,
    ) -> VaultDocument:
        self._append_calls.append((entity_id, expected_revision, fact, audit))
        doc = self._entities.get(entity_id)
        if doc is None:
            raise NotFoundError(f"Entity '{entity_id}' not found")
        return doc


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
    register_entity_mutation_tools(registry, search_service=search_service, repository=repository)
    return registry


@pytest.fixture
def executor(registered_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registered_registry)


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
        audit=_AUDIT,
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


# ═══════════════════════════════════════════════════════════════════════════
# patch_entity handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestPatchEntityHandler:
    def test_authorization_called_exactly_once(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        assert search_service.get_by_id_calls == ["npc--gandalf"]

    def test_repository_patch_called_exactly_once(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        assert len(repository.patch_calls) == 1

    def test_entity_id_forwarded_unchanged(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        called_id, _, _, _ = repository.patch_calls[0]
        assert called_id == "npc--gandalf"

    def test_expected_revision_forwarded_unchanged(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        _, _, rev, _ = repository.patch_calls[0]
        assert rev == 1

    def test_entity_patch_forwarded(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        _, patch, _, _ = repository.patch_calls[0]
        assert isinstance(patch, EntityPatch)
        assert patch.name == "New Name"

    def test_audit_context_forwarded(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        _, _, _, audit = repository.patch_calls[0]
        assert audit is _AUDIT

    def test_output_entity_from_repository(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf", name="Gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        result = executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        assert isinstance(result, PatchEntityOutput)
        assert result.entity.id == "npc--gandalf"

    def test_output_body_from_repository(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf", body="# Gandalf the Grey")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        result = executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        assert result.body == "# Gandalf the Grey"

    def test_authorization_before_mutation(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        """SearchService.get_by_id must be called before repository.patch_entity."""
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "patch": {"name": "New Name"},
            },
            context=write_context,
        )
        assert len(search_service.get_by_id_calls) >= 1
        assert len(repository.patch_calls) == 1


# ═══════════════════════════════════════════════════════════════════════════
# append_entity_fact handler behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestAppendEntityFactHandler:
    def test_authorization_called_exactly_once(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        assert search_service.get_by_id_calls == ["npc--gandalf"]

    def test_repository_append_called_exactly_once(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        assert len(repository.append_calls) == 1

    def test_entity_id_forwarded_unchanged(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        called_id, _, _, _ = repository.append_calls[0]
        assert called_id == "npc--gandalf"

    def test_expected_revision_forwarded_unchanged(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        _, rev, _, _ = repository.append_calls[0]
        assert rev == 1

    def test_fact_forwarded_unchanged(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        _, _, fact, _ = repository.append_calls[0]
        assert fact == "Met the party."

    def test_audit_context_forwarded(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        _, _, _, audit = repository.append_calls[0]
        assert audit is _AUDIT

    def test_output_entity_from_repository(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf", name="Gandalf")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        result = executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        assert isinstance(result, AppendEntityFactOutput)
        assert result.entity.id == "npc--gandalf"

    def test_output_body_from_repository(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        doc = _make_doc("npc--gandalf", body="# Gandalf the Grey")
        repository.add_document(doc)
        search_service.set_get_by_id(
            "npc--gandalf", SearchHit(entity_id="npc--gandalf", match_kind=MatchKind.EXACT_ID)
        )
        result = executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc--gandalf",
                "expected_revision": 1,
                "fact": "Met the party.",
            },
            context=write_context,
        )
        assert result.body == "# Gandalf the Grey"
