"""Tests for S5-03 FTS tier integration in VaultSearchService.

Covers:
- FTS tier is below exact/fuzzy tiers (precedence)
- FTS tier unavailable when no lexical index configured
- Current visibility/type eligibility enforced on FTS results
- Limit applied after FTS ranking and eligibility filtering
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Visibility
from dnd_assistant.errors import StorageError
from dnd_assistant.retrieval import (
    MatchKind,
    SearchQuery,
    VaultSearchService,
)
from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.storage.types import VaultDocument, VaultRepository

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_entity(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
) -> Entity:
    return Entity(
        id=cast(EntityId, entity_id),
        type=entity_type,
        name=name,
        status="active",
        visibility=visibility,
        knowledge_status="confirmed",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        revision=1,
    )


def _make_doc(
    entity_id: str,
    name: str = "Test Entity",
    body: str = "",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
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


class FakeRepository:
    def __init__(self, documents: list[VaultDocument] | None = None) -> None:
        self._docs: dict[str, VaultDocument] = {}
        if documents:
            for doc in documents:
                self._docs[doc.entity.id] = doc

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        from dnd_assistant.errors import NotFoundError

        try:
            return self._docs[str(entity_id)]
        except KeyError:
            raise NotFoundError(f"Entity not found: {entity_id}") from None

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        if entity_type is None:
            return list(self._docs.values())
        return [d for d in self._docs.values() if d.entity.type == entity_type]


def _create_index_dir(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    audit_dir = vault / "_system" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit.jsonl").write_text("", encoding="utf-8")
    return vault


# ── Tier precedence ──────────────────────────────────────────────────────────


class TestTierPrecedence:
    def test_exact_id_over_fts(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_varos", name="Some Name", body="unique body text"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="npc_varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ID

    def test_exact_name_over_fts(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_varos", name="Varos", body="unique body text"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="Varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_NAME

    def test_exact_alias_over_fts(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        extra = {"aliases": ["Lord Varos"]}
        doc = VaultDocument(
            entity=_make_entity("npc_varos", name="Varos"),
            extra_frontmatter=extra,
            body="unique body text",
        )
        docs = [doc]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="Lord Varos"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT_ALIAS

    def test_fuzzy_over_fts(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_varos", name="Magistr Varos", body="unique body text"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="Magistr Varo"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.FUZZY_NAME

    def test_fts_only_when_higher_tiers_empty(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_varos", name="XXXXX", body="The dark mage from Grayford"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        # Query a body-only word that has zero fuzzy similarity to the
        # canonical name "XXXXX" — no exact/fuzzy tier match, so FTS fires.
        results = svc.search(SearchQuery(text="mage"))
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.FTS


# ── No lexical index configured ──────────────────────────────────────────────


class TestNoLexicalIndex:
    def test_fts_unavailable_when_no_index(self) -> None:
        repo: VaultRepository = FakeRepository([])
        svc = VaultSearchService(repository=repo)
        results = svc.search(SearchQuery(text="anything"))
        assert len(results) == 0


# ── Current visibility/type eligibility ───────────────────────────────────────


class TestEligibility:
    def test_dm_entity_excluded_from_fts(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_secret", name="Secret", body="hidden text", visibility=Visibility.DM),
            _make_doc("npc_visible", name="Visible", body="visible text"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="text"))
        assert len(results) == 1
        assert results[0].entity_id == "npc_visible"

    def test_excluded_type_not_in_fts(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_a", name="Alpha", body="body text", entity_type=EntityType.NPC),
            _make_doc("loc_b", name="Beta", body="body text", entity_type=EntityType.LOCATION),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="body", entity_types={EntityType.LOCATION}))
        assert len(results) == 1
        assert results[0].entity_id == "loc_b"

    def test_excluded_result_does_not_consume_limit(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [
            _make_doc("npc_a", name="Alpha", body="common body", visibility=Visibility.DM),
            _make_doc("npc_b", name="Beta", body="common body"),
        ]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        svc = VaultSearchService(repository=repo, lexical_index=index)

        results = svc.search(SearchQuery(text="common"), limit=5)
        assert len(results) == 1
        assert results[0].entity_id == "npc_b"


# ── Repository/index error propagation ───────────────────────────────────────


class TestErrorPropagation:
    def test_stale_index_raises(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [_make_doc("npc_a", name="Alpha", body="body")]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(docs)
        VaultSearchService(repository=repo, lexical_index=index)

        # Change the repo data so it differs from the index fingerprint
        docs2 = [_make_doc("npc_a", name="Alpha", body="different body")]
        repo2: VaultRepository = FakeRepository(docs2)
        svc2 = VaultSearchService(repository=repo2, lexical_index=index)

        with pytest.raises(StorageError, match="\u0443\u0441\u0442\u0430\u0440\u0435\u043b"):
            svc2.search(SearchQuery(text="body"))

    def test_missing_index_raises(self, tmp_path: Path) -> None:
        vault = _create_index_dir(tmp_path)
        docs = [_make_doc("npc_a", name="Alpha", body="body")]
        repo: VaultRepository = FakeRepository(docs)
        index = SqliteFtsIndex(str(vault))
        svc = VaultSearchService(repository=repo, lexical_index=index)

        with pytest.raises(
            StorageError, match="\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442"
        ):
            svc.search(SearchQuery(text="body"))
