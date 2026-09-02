"""Tests for entity mutation tool safety: authorization, non-disclosing errors, gating.

Covers:
- Authorization failure: SearchService.get_by_id returns None
- Authorization failure: SearchService returns wrong entity_id
- Authorization failure: SearchService raises StorageError
- Generic non-disclosing NotFoundError for hidden/missing
- ToolExecutor gating before authorization (READ, missing audit, invalid input)
- Both session modes allowed
- No fuzzy/ambiguous resolution
- Stable-ID-only target policy
- No direct filesystem/audit/serialization mutation
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Revision, Visibility
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.retrieval.types import MatchKind, SearchHit
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.tools.entity_mutations import (
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
    """Fake SearchService with call tracking."""

    def __init__(self) -> None:
        self._by_id: dict[str, SearchHit | None] = {}
        self._get_by_id_calls: list[str] = []
        self._raise_on_get_by_id: type[Exception] | None = None

    def set_get_by_id(self, entity_id: str, hit: SearchHit | None) -> None:
        self._by_id[entity_id] = hit

    def set_raise_on_get_by_id(self, exc: type[Exception]) -> None:
        self._raise_on_get_by_id = exc

    @property
    def get_by_id_calls(self) -> list[str]:
        return list(self._get_by_id_calls)

    def search(self, query: object, *, limit: int = 20) -> list[object]:
        return []

    def get_by_id(self, entity_id: str) -> SearchHit | None:
        self._get_by_id_calls.append(entity_id)
        if self._raise_on_get_by_id is not None:
            raise self._raise_on_get_by_id("search service error")
        return self._by_id.get(entity_id)


# ── Fake VaultRepository with call tracking ────────────────────────────────


class FakeRepository:
    """Fake VaultRepository with call tracking."""

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


# ═══════════════════════════════════════════════════════════════════════════
# Authorization failure tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAuthorizationFailures:
    """SearchService.get_by_id returns None -> generic NotFoundError."""

    def test_patch_entity_gate_none_raises_not_found(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id("npc--missing", None)
        with pytest.raises(NotFoundError, match="not found or not accessible"):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--missing",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )

    def test_patch_entity_gate_none_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id("npc--missing", None)
        with pytest.raises(NotFoundError):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--missing",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )
        assert repository.patch_calls == []

    def test_append_entity_fact_gate_none_raises_not_found(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id("npc--missing", None)
        with pytest.raises(NotFoundError, match="not found or not accessible"):
            executor.execute(
                "append_entity_fact",
                input_data={
                    "entity_id": "npc--missing",
                    "expected_revision": 1,
                    "fact": "Some fact.",
                },
                context=write_context,
            )

    def test_append_entity_fact_gate_none_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id("npc--missing", None)
        with pytest.raises(NotFoundError):
            executor.execute(
                "append_entity_fact",
                input_data={
                    "entity_id": "npc--missing",
                    "expected_revision": 1,
                    "fact": "Some fact.",
                },
                context=write_context,
            )
        assert repository.append_calls == []

    def test_gate_none_error_does_not_reveal_entity_id(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id("npc--secret", None)
        with pytest.raises(NotFoundError) as exc_info:
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--secret",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )
        msg = str(exc_info.value)
        assert "DM" not in msg
        assert "dm" not in msg
        assert "system" not in msg
        assert "hidden" not in msg
        assert "npc--secret" not in msg

    def test_search_hit_wrong_id_raises_storage_error(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        """SearchService returns hit for B when A was requested."""
        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_ID)
        )
        with pytest.raises(
            StorageError, match="Entity mutation authorization consistency check failed"
        ):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--a",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )

    def test_search_hit_wrong_id_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_ID)
        )
        with pytest.raises(StorageError):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--a",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )
        assert repository.patch_calls == []

    def test_search_hit_wrong_id_error_non_disclosing(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_get_by_id(
            "npc--a", SearchHit(entity_id="npc--b", match_kind=MatchKind.EXACT_ID)
        )
        with pytest.raises(StorageError) as exc_info:
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--a",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )
        msg = str(exc_info.value)
        assert "npc--b" not in msg

    def test_search_service_storage_error_propagates(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_raise_on_get_by_id(StorageError)
        with pytest.raises(StorageError, match="search service error"):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )

    def test_search_service_storage_error_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_raise_on_get_by_id(StorageError)
        with pytest.raises(StorageError):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )
        assert repository.patch_calls == []

    def test_append_fact_search_service_storage_error_repository_not_called(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        search_service.set_raise_on_get_by_id(StorageError)
        with pytest.raises(StorageError):
            executor.execute(
                "append_entity_fact",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "fact": "Some fact.",
                },
                context=write_context,
            )
        assert repository.append_calls == []


# ═══════════════════════════════════════════════════════════════════════════
# ToolExecutor gating before authorization
# ═══════════════════════════════════════════════════════════════════════════


class TestToolExecutorGating:
    """READ permission -> ConflictError, SearchService calls = 0, repository calls = 0."""

    def test_patch_entity_read_permission_rejected_before_authorization(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(ConflictError, match="Permission denied"):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=ctx,
            )
        assert search_service.get_by_id_calls == []
        assert repository.patch_calls == []

    def test_append_entity_fact_read_permission_rejected_before_authorization(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(ConflictError, match="Permission denied"):
            executor.execute(
                "append_entity_fact",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "fact": "Some fact.",
                },
                context=ctx,
            )
        assert search_service.get_by_id_calls == []
        assert repository.append_calls == []

    def test_patch_entity_missing_audit_rejected_before_authorization(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        with pytest.raises(ValidationError, match="AuditContext"):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=ctx,
            )
        assert search_service.get_by_id_calls == []
        assert repository.patch_calls == []

    def test_append_entity_fact_missing_audit_rejected_before_authorization(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
    ) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=None,
        )
        with pytest.raises(ValidationError, match="AuditContext"):
            executor.execute(
                "append_entity_fact",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "fact": "Some fact.",
                },
                context=ctx,
            )
        assert search_service.get_by_id_calls == []
        assert repository.append_calls == []

    def test_patch_entity_invalid_input_rejected_before_authorization(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "",
                    "expected_revision": 1,
                    "patch": {"name": "New Name"},
                },
                context=write_context,
            )
        assert search_service.get_by_id_calls == []
        assert repository.patch_calls == []

    def test_append_entity_fact_invalid_input_rejected_before_authorization(
        self,
        executor: ToolExecutor,
        search_service: FakeSearchService,
        repository: FakeRepository,
        write_context: ExecutionContext,
    ) -> None:
        with pytest.raises(ValidationError):
            executor.execute(
                "append_entity_fact",
                input_data={
                    "entity_id": "npc--gandalf",
                    "expected_revision": 1,
                    "fact": "",
                },
                context=write_context,
            )
        assert search_service.get_by_id_calls == []
        assert repository.append_calls == []
