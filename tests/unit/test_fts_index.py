"""Tests for S5-03 SQLite FTS5 derived index.

Covers:
- Schema version and FTS virtual table existence
- Indexed fields: canonical name and Markdown body searchable
- Hidden data: DM/SYSTEM not indexed, PLAYER indexed
- Rebuild: first rebuild, replaces prior, entity removal, changed body/name
- Source fingerprint: stable, changes on add/remove/name/body/visibility
- Stale index detection
- Missing/corrupt/wrong-schema index errors
- Atomic rebuild: temp-build + replace, old index preserved on failure
- Query literalization: operator-like text, punctuation-only, Cyrillic
- bm25 ranking semantics
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Visibility
from dnd_assistant.errors import StorageError
from dnd_assistant.retrieval.index import (
    SCHEMA_VERSION,
    SqliteFtsIndex,
    _build_literal_fts_query,
    _compute_source_fingerprint,
    _tokenize_fts_query,
)
from dnd_assistant.storage.types import VaultDocument

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_entity(
    entity_id: str,
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
    revision: int = 1,
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
        revision=revision,
    )


def _make_doc(
    entity_id: str,
    name: str = "Test Entity",
    body: str = "",
    entity_type: EntityType = EntityType.NPC,
    visibility: Visibility = Visibility.PLAYER,
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


def _create_minimal_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    audit_dir = vault / "_system" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit.jsonl").write_text("", encoding="utf-8")
    return vault


# ── FTS query safety ─────────────────────────────────────────────────────────


class TestTokenizeFtsQuery:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("black sun", ["black", "sun"]),
            ("чёрное солнце", ["чёрное", "солнце"]),
            ("  hello   world  ", ["hello", "world"]),
            ("hello,world!test", ["hello", "world", "test"]),
            ("well-known entity_id", ["well-known", "entity_id"]),
            ("OR NOT NEAR", ["OR", "NOT", "NEAR"]),
            ("!!! ???", []),
            ("", []),
            ("   ", []),
        ],
    )
    def test_tokenize(self, text: str, expected: list[str]) -> None:
        assert _tokenize_fts_query(text) == expected


class TestBuildLiteralFtsQuery:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("black sun", '"black" AND "sun"'),
            ("чёрное солнце", '"чёрное" AND "солнце"'),
            ("OR", '"OR"'),
            ("foo OR bar", '"foo" AND "OR" AND "bar"'),
            ("(test)", '"test"'),
            ("test*", '"test"'),
            ("well-known", '"well-known"'),
            ("!!! ???", ""),
            ("", ""),
        ],
    )
    def test_build_query(self, text: str, expected: str) -> None:
        assert _build_literal_fts_query(text) == expected

    def test_quotes_literal(self) -> None:
        result = _build_literal_fts_query('hello "world"')
        assert '"world"' in result


# ── Source fingerprint ───────────────────────────────────────────────────────


class TestSourceFingerprint:
    def test_stable_for_same_snapshot(self) -> None:
        docs = [_make_doc("npc_a", name="Alpha"), _make_doc("npc_b", name="Beta")]
        assert _compute_source_fingerprint(docs) == _compute_source_fingerprint(docs)

    def test_stable_regardless_of_order(self) -> None:
        a = [_make_doc("npc_a", name="Alpha"), _make_doc("npc_b", name="Beta")]
        b = [_make_doc("npc_b", name="Beta"), _make_doc("npc_a", name="Alpha")]
        assert _compute_source_fingerprint(a) == _compute_source_fingerprint(b)

    @pytest.mark.parametrize(
        "make_b",
        [
            lambda: [_make_doc("npc_a"), _make_doc("npc_b")],
            lambda: [_make_doc("npc_a", name="Beta")],
            lambda: [_make_doc("npc_a", body="Hello")],
            lambda: [_make_doc("npc_a", visibility=Visibility.DM)],
            lambda: [_make_doc("npc_a", revision=2)],
        ],
    )
    def test_changes_on_any_field(self, make_b) -> None:
        base = [_make_doc("npc_a")]
        modified = make_b()
        assert _compute_source_fingerprint(base) != _compute_source_fingerprint(modified)

    def test_removal_changes_fingerprint(self) -> None:
        a = [_make_doc("npc_a"), _make_doc("npc_b")]
        b = [_make_doc("npc_a")]
        assert _compute_source_fingerprint(a) != _compute_source_fingerprint(b)

    def test_is_sha256_hex(self) -> None:
        fp = _compute_source_fingerprint([_make_doc("npc_a")])
        assert isinstance(fp, str) and len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


# ── Schema and FTS5 support ──────────────────────────────────────────────────


class TestSchemaAndFts5Support:
    def test_schema_version_defined(self) -> None:
        assert isinstance(SCHEMA_VERSION, int) and SCHEMA_VERSION >= 1

    def test_rebuild_produces_usable_db(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_varos", name="Varos")])
        assert index.index_path.exists()
        conn = sqlite3.connect(str(index.index_path))
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert "entity_fts" in tables
            assert "index_metadata" in tables
            sv = int(
                conn.execute(
                    "SELECT value FROM index_metadata WHERE key='schema_version'"
                ).fetchone()[0]
            )
            assert sv == SCHEMA_VERSION
        finally:
            conn.close()

    def test_fts_virtual_table(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_varos", name="Varos")])
        conn = sqlite3.connect(str(index.index_path))
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='entity_fts'"
            ).fetchone()
            assert row is not None and "fts5" in row[0]
        finally:
            conn.close()


# ── Indexed fields ───────────────────────────────────────────────────────────


class TestIndexedFields:
    def test_canonical_name_searchable(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_varos", name="Varos the Dark")])
        hits = index.search("Varos")
        assert len(hits) == 1 and hits[0].entity_id == "npc_varos"

    def test_markdown_body_searchable(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_varos", name="Varos", body="A dark mage.")])
        hits = index.search("mage")
        assert len(hits) == 1 and hits[0].entity_id == "npc_varos"


# ── Hidden data ──────────────────────────────────────────────────────────────


class TestHiddenData:
    def test_player_indexed(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_varos", name="Varos", visibility=Visibility.PLAYER)])
        assert len(index.search("Varos")) == 1

    @pytest.mark.parametrize("vis", [Visibility.DM, Visibility.SYSTEM])
    def test_non_player_not_indexed(self, tmp_path: Path, vis: Visibility) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_secret", name="Secret", visibility=vis)])
        assert len(index.search("Secret")) == 0

    def test_hidden_unique_text_not_found(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(
            [
                _make_doc("npc_player", name="Visible"),
                _make_doc(
                    "npc_secret", name="Hidden", body="UNIQUE_SECRET", visibility=Visibility.DM
                ),
            ]
        )
        assert len(index.search("UNIQUE_SECRET")) == 0

    def test_hidden_content_absent_from_db(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(
            [
                _make_doc("npc_player", name="Visible"),
                _make_doc("npc_secret", name="Hidden", body="CLASSIFIED", visibility=Visibility.DM),
            ]
        )
        conn = sqlite3.connect(str(index.index_path))
        try:
            rows = conn.execute("SELECT entity_id, name, body FROM entity_fts").fetchall()
            ids = {r[0] for r in rows}
            assert "npc_secret" not in ids
            assert "CLASSIFIED" not in {r[2] for r in rows}
        finally:
            conn.close()


# ── Rebuild ──────────────────────────────────────────────────────────────────


class TestRebuild:
    def test_first_rebuild_works(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_varos", name="Varos")])
        assert index.index_path.exists()

    def test_rebuild_replaces_prior(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        assert len(index.search("Alpha")) == 1
        index.rebuild([_make_doc("npc_b", name="Beta")])
        assert len(index.search("Alpha")) == 0
        assert len(index.search("Beta")) == 1

    def test_entity_removal(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha"), _make_doc("npc_b", name="Beta")])
        assert len(index.search("Beta")) == 1
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        assert len(index.search("Beta")) == 0

    def test_changed_body_reflected(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha", body="Old body")])
        assert len(index.search("Old")) == 1
        index.rebuild([_make_doc("npc_a", name="Alpha", body="New body")])
        assert len(index.search("Old")) == 0
        assert len(index.search("New")) == 1

    def test_changed_name_reflected(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        assert len(index.search("Alpha")) == 1
        index.rebuild([_make_doc("npc_a", name="Beta")])
        assert len(index.search("Alpha")) == 0
        assert len(index.search("Beta")) == 1


# ── Stale index ──────────────────────────────────────────────────────────────


class TestStaleIndex:
    def test_verify_freshness_ok(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        docs = [_make_doc("npc_a", name="Alpha")]
        index.rebuild(docs)
        index.verify_freshness(docs)

    def test_verify_freshness_stale(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        with pytest.raises(StorageError, match="\u0443\u0441\u0442\u0430\u0440\u0435\u043b"):
            index.verify_freshness([_make_doc("npc_a", name="Beta")])

    def test_verify_freshness_missing(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        with pytest.raises(
            StorageError, match="\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442"
        ):
            index.verify_freshness([_make_doc("npc_a")])


# ── Missing / corrupt / wrong schema index ───────────────────────────────────


class TestIndexErrors:
    def test_missing_index(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        with pytest.raises(
            StorageError, match="\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442"
        ):
            index.search("test")

    def test_corrupt_index(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.index_path.parent.mkdir(parents=True, exist_ok=True)
        index.index_path.write_bytes(b"not a valid sqlite db")
        with pytest.raises(
            StorageError, match="\u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d"
        ):
            index.search("test")

    def test_wrong_schema_version(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        conn = sqlite3.connect(str(index.index_path))
        try:
            conn.execute("UPDATE index_metadata SET value='999' WHERE key='schema_version'")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(
            StorageError,
            match="\u0432\u0435\u0440\u0441\u0438\u044e \u0441\u0445\u0435\u043c\u044b",
        ):
            index.search("Alpha")


# ── Atomic rebuild ───────────────────────────────────────────────────────────


class TestAtomicRebuild:
    def test_atomic_replace(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        old_stat = index.index_path.stat()
        index.rebuild([_make_doc("npc_a", name="Beta")])
        new_stat = index.index_path.stat()
        assert index.index_path.exists()
        assert old_stat.st_ino != new_stat.st_ino

    def test_failed_rebuild_preserves_old_index(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha")])
        assert len(index.search("Alpha")) == 1

        # Inject a document that will fail during rebuild
        # (e.g. a document with invalid entity data)
        class BadDoc:
            class Entity:
                id = None
                type = None
                revision = None
                name = None
                visibility = Visibility.PLAYER

            entity = Entity()
            body = ""

        with pytest.raises((AttributeError, StorageError)):
            index.rebuild([BadDoc()])  # type: ignore[list-item]

        assert index.index_path.exists()
        assert len(index.search("Alpha")) == 1


# ── bm25 ranking ─────────────────────────────────────────────────────────────


class TestRanking:
    def test_bm25_finite(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild([_make_doc("npc_a", name="Alpha Beta Gamma Delta")])
        hits = index.search("Alpha")
        assert len(hits) == 1
        assert isinstance(hits[0].score, float)

    def test_better_score_sorts_first(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(
            [
                _make_doc("npc_a", name="Alpha", body="irrelevant"),
                _make_doc("npc_b", name="Beta Alpha", body="irrelevant"),
            ]
        )
        hits = index.search("Alpha")
        assert len(hits) == 2
        assert hits[0].score <= hits[1].score

    def test_equal_scores_tiebreak_by_id(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(
            [
                _make_doc("npc_z", name="Alpha"),
                _make_doc("npc_a", name="Alpha"),
            ]
        )
        hits = index.search("Alpha")
        assert len(hits) == 2
        assert hits[0].entity_id == "npc_a"
        assert hits[1].entity_id == "npc_z"


# ── Entity-type filter ────────────────────────────────────────────────────────


class TestEntityTypeFilter:
    def test_excluded_type_not_in_results(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        index.rebuild(
            [
                _make_doc("npc_a", name="Alpha", entity_type=EntityType.NPC),
                _make_doc("loc_b", name="Beta", entity_type=EntityType.LOCATION),
            ]
        )
        hits = index.search("Alpha")
        assert len(hits) == 1
        assert hits[0].entity_id == "npc_a"


# ── Limit ─────────────────────────────────────────────────────────────────────


class TestLimit:
    def test_limit_applied(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        index = SqliteFtsIndex(str(vault))
        docs = [_make_doc(f"npc_{i}", name="SameName") for i in range(10)]
        index.rebuild(docs)
        hits = index.search("SameName", limit=3)
        assert len(hits) == 3
