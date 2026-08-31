"""SQLite FTS5 concrete lexical index implementation.

This module provides ``SqliteFtsIndex``, a rebuildable FTS5 index over
player-visible campaign entities.  The SQLite database is **derived
storage only** — the Obsidian Vault remains the only Source of Truth.

The index is fully disposable and reconstructable from the canonical
Vault via ``rebuild()``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from dnd_assistant.domain.types import Visibility
from dnd_assistant.errors import StorageError
from dnd_assistant.retrieval.lexical import LexicalHit
from dnd_assistant.storage.types import VaultDocument

# ── Schema version ──────────────────────────────────────────────────────────

SCHEMA_VERSION = 1
"""Current FTS index schema version.

Increment when the FTS table schema or metadata layout changes.
"""

# ── Canonical index path ────────────────────────────────────────────────────

FTS_INDEX_FILENAME = "entities.sqlite3"
"""Canonical SQLite database filename within the Vault's derived-index
directory."""


# ── FTS query safety ────────────────────────────────────────────────────────


def _tokenize_fts_query(text: str) -> list[str]:
    """Split *text* into lexical word tokens for safe FTS querying.

    Normalises via NFC, then splits on whitespace/punctuation.
    Each token is non-empty after stripping.

    Returns:
        A list of normalised word tokens.
    """
    normalised = unicodedata.normalize("NFC", text.strip())
    if not normalised:
        return []

    tokens: list[str] = []
    current: list[str] = []

    for ch in normalised:
        if ch.isalnum() or ch in ("_", "-"):
            current.append(ch)
        else:
            if current:
                token = "".join(current).strip()
                if token:
                    tokens.append(token)
                current = []
    if current:
        token = "".join(current).strip()
        if token:
            tokens.append(token)

    return tokens


def _build_literal_fts_query(text: str) -> str:
    """Build a safe literal FTS5 query from user text.

    Policy:
    1. Strip and NFC-normalise.
    2. Tokenise into word tokens.
    3. Quote each token as an FTS5 literal.
    4. Combine with deterministic ``AND``.

    This prevents FTS operator injection (``OR``, ``NOT``, ``NEAR``,
    ``*``, ``"``, parentheses, etc.).

    Returns:
        A safe FTS5 query string, or empty string if no tokens.

    Example:
        ``"black sun"`` -> ``'"black" AND "sun"'``
        ``"OR"`` -> ``'"or"'``
    """
    tokens = _tokenize_fts_query(text)
    if not tokens:
        return ""
    quoted = [f'"{t}"' for t in tokens]
    return " AND ".join(quoted)


# ── Source fingerprint ──────────────────────────────────────────────────────


def _compute_source_fingerprint(documents: Sequence[VaultDocument]) -> str:
    """Compute a deterministic SHA-256 fingerprint for the given documents.

    The fingerprint changes when any indexed canonical source changes,
    including:

    - entity added/removed
    - ``EntityId``
    - ``EntityType``
    - ``revision``
    - ``name``
    - Markdown body
    - player visibility membership

    Uses canonical JSON (sorted by stable ``EntityId``) then SHA-256.

    Args:
        documents: The canonical Vault documents to fingerprint.

    Returns:
        Hex digest of the SHA-256 hash.
    """
    entries: list[dict[str, object]] = []
    for doc in sorted(documents, key=lambda d: d.entity.id):
        entries.append(
            {
                "entity_id": doc.entity.id,
                "entity_type": doc.entity.type.value,
                "revision": doc.entity.revision,
                "name": doc.entity.name,
                "body": doc.body,
                "visibility": doc.entity.visibility.value,
            }
        )

    raw = json.dumps(entries, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Path safety ──────────────────────────────────────────────────────────────


def _resolve_index_dir(vault_root: Path) -> Path:
    """Resolve and validate the derived-index directory path.

    Requirements:
    - *vault_root* must exist and be a directory.
    - The resulting path must be inside *vault_root*.
    - No ``..`` traversal in the relative path.
    - No existing symlink for any path component beneath *vault_root*.

    Args:
        vault_root: The resolved Vault root path.

    Returns:
        The canonical index directory path.

    Raises:
        StorageError: Path safety validation failed.
    """
    vault_root = vault_root.resolve(strict=False)
    if not vault_root.is_dir():
        raise StorageError(f"Vault root must be an existing directory: {vault_root}")

    relative_parts = ["_system", "indexes"]
    accumulated = vault_root

    for part in relative_parts:
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Derived-index path component is a symlink, rejected for safety: {accumulated}"
            )

    try:
        accumulated.relative_to(vault_root)
    except ValueError:
        raise StorageError(
            f"Derived-index path resolves outside the Vault root: {accumulated}"
        ) from None

    return accumulated


def _resolve_index_path(vault_root: Path) -> Path:
    """Resolve the canonical SQLite index file path."""
    index_dir = _resolve_index_dir(vault_root)
    return index_dir / FTS_INDEX_FILENAME


# ── Concrete SqliteFtsIndex ─────────────────────────────────────────────────


class SqliteFtsIndex:
    """SQLite FTS5 lexical index over player-visible campaign entities.

    The index is **derived storage only**.  It is fully disposable and
    reconstructable from the canonical Vault via ``rebuild()``.

    The index lives at ``<vault>/_system/indexes/entities.sqlite3``.

    Args:
        vault_root: The resolved Vault root path.  Used to locate the
            canonical index file.

    Raises:
        StorageError: The Vault root or index directory is invalid.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self._vault_root = Path(vault_root).resolve(strict=False)
        self._index_path = _resolve_index_path(self._vault_root)
        self._index_dir = self._index_path.parent

    @property
    def index_path(self) -> Path:
        """The canonical SQLite index file path."""
        return self._index_path

    # ── search ──────────────────────────────────────────────────────────

    def search(self, query: str, *, limit: int = 20) -> Sequence[LexicalHit]:
        """Search the FTS index and return ranked hits.

        Args:
            query: The literal search text (not an FTS query expression).
            limit: Maximum number of hits to return.

        Returns:
            Ranked ``LexicalHit`` values ordered by bm25 ascending
            (smaller = better), then EntityId ascending.

        Raises:
            StorageError: The index is missing, corrupt, stale, or
                the query could not be executed.
        """
        if not self._index_path.exists():
            raise StorageError(
                "FTS index \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            )

        fts_query = _build_literal_fts_query(query)
        if not fts_query:
            return []

        try:
            conn = sqlite3.connect(str(self._index_path))
        except sqlite3.DatabaseError as exc:
            raise StorageError(
                "FTS index \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild",
                cause=exc,
            ) from exc

        try:
            cursor = conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            cursor.fetchone()
        except sqlite3.DatabaseError:
            conn.close()
            raise StorageError(
                "FTS index \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            ) from None

        try:
            self._verify_index_fresh(conn)
        except StorageError:
            conn.close()
            raise

        try:
            cursor = conn.execute(
                "SELECT entity_id, bm25(entity_fts) AS score "
                "FROM entity_fts WHERE entity_fts MATCH ? "
                "ORDER BY score ASC, entity_id ASC "
                "LIMIT ?",
                (fts_query, limit),
            )
            results = cursor.fetchall()
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise StorageError(
                "FTS-\u0437\u0430\u043f\u0440\u043e\u0441 \u043d\u0435 \u0443\u0434\u0430\u043b\u0441\u044f; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild",
                cause=exc,
            ) from exc
        finally:
            conn.close()

        return [LexicalHit(entity_id=row[0], score=float(row[1])) for row in results]

    # ── rebuild ─────────────────────────────────────────────────────────

    def rebuild(self, documents: Sequence[VaultDocument]) -> None:
        """Rebuild the FTS index from the given canonical documents.

        The rebuild lifecycle:
        1. Validate the index directory.
        2. Create a unique temp SQLite DB in the same directory.
        3. Create the schema.
        4. Insert only player-visible entities.
        5. Write metadata and source fingerprint.
        6. Commit.
        7. Validate the temp DB.
        8. Close the connection.
        9. Atomically replace the old index.
        10. Clean up temp artifacts on failure.

        Args:
            documents: Canonical entity documents to index.

        Raises:
            StorageError: The rebuild failed.
        """
        index_dir = _resolve_index_dir(self._vault_root)
        if not index_dir.exists():
            try:
                index_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StorageError(
                    "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0437\u0434\u0430\u0442\u044c "
                    "\u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440\u0438\u044e \u0438\u043d\u0434\u0435\u043a\u0441\u0430: "
                    f"{index_dir}",
                    cause=exc,
                ) from exc

        if index_dir.is_symlink():
            raise StorageError(
                "\u0414\u0438\u0440\u0435\u043a\u0442\u043e\u0440\u0438\u044f \u0438\u043d\u0434\u0435\u043a\u0441\u0430 "
                "\u044f\u0432\u043b\u044f\u0435\u0442\u0441\u044f \u0441\u0438\u043c\u0432\u043e\u043b\u0438\u0447\u0435\u0441\u043a\u043e\u0439 "
                "\u0441\u0441\u044b\u043b\u043a\u043e\u0439: {index_dir}"
            )

        fd, temp_path_str = tempfile.mkstemp(
            suffix=".sqlite3",
            prefix="fts_rebuild_",
            dir=str(index_dir),
        )
        os.close(fd)
        temp_path = Path(temp_path_str)

        try:
            self._build_index(temp_path, documents)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

        final_path = self._index_path

        try:
            os.replace(str(temp_path), str(final_path))
        except OSError as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise StorageError(
                "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0430\u0442\u043e\u043c\u0430\u0440\u043d\u043e "
                "\u0437\u0430\u043c\u0435\u043d\u0438\u0442\u044c \u0438\u043d\u0434\u0435\u043a\u0441: "
                f"{final_path}",
                cause=exc,
            ) from exc

    # ── Internal helpers ────────────────────────────────────────────────

    def _build_index(self, db_path: Path, documents: Sequence[VaultDocument]) -> None:
        """Build a fresh FTS index at *db_path* from *documents*.

        Only ``Visibility.PLAYER`` entities are indexed.
        """
        player_docs = [d for d in documents if d.entity.visibility == Visibility.PLAYER]

        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.DatabaseError as exc:
            raise StorageError(
                "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0437\u0434\u0430\u0442\u044c "
                "\u0432\u0440\u0435\u043c\u0435\u043d\u043d\u0443\u044e \u0411\u0414: "
                f"{db_path}",
                cause=exc,
            ) from exc

        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS index_metadata ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL"
                ")"
            )

            conn.execute(
                "CREATE VIRTUAL TABLE entity_fts USING fts5("
                "  entity_id UNINDEXED,"
                "  entity_type UNINDEXED,"
                "  revision UNINDEXED,"
                "  name,"
                "  body,"
                "  tokenize='unicode61'"
                ")"
            )

            for doc in player_docs:
                conn.execute(
                    "INSERT INTO entity_fts (entity_id, entity_type, revision, name, body) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        doc.entity.id,
                        doc.entity.type.value,
                        doc.entity.revision,
                        doc.entity.name,
                        doc.body,
                    ),
                )

            fingerprint = _compute_source_fingerprint(documents)

            conn.execute(
                "INSERT INTO index_metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.execute(
                "INSERT INTO index_metadata (key, value) VALUES (?, ?)",
                ("source_fingerprint", fingerprint),
            )
            conn.execute(
                "INSERT INTO index_metadata (key, value) VALUES (?, ?)",
                ("indexed_entity_count", str(len(player_docs))),
            )

            conn.commit()

            cursor = conn.execute("SELECT COUNT(*) FROM entity_fts")
            count = cursor.fetchone()[0]
            if count != len(player_docs):
                raise StorageError(
                    f"FTS rebuild: inserted {count} rows, expected {len(player_docs)}"
                )

        except sqlite3.DatabaseError as exc:
            raise StorageError(
                f"FTS rebuild \u043d\u0435 \u0443\u0434\u0430\u043b\u0441\u044f: {exc}",
                cause=exc,
            ) from exc
        finally:
            conn.close()

    def _verify_index_fresh(self, conn: sqlite3.Connection) -> None:
        """Verify the index schema version.

        Raises:
            StorageError: The index has the wrong schema version or
                metadata is missing.
        """
        try:
            cursor = conn.execute("SELECT value FROM index_metadata WHERE key = 'schema_version'")
            row = cursor.fetchone()
        except sqlite3.DatabaseError as exc:
            raise StorageError(
                "FTS index \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild",
                cause=exc,
            ) from exc

        if row is None:
            raise StorageError(
                "FTS index \u0438\u043c\u0435\u0435\u0442 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0443\u044e "
                "\u0432\u0435\u0440\u0441\u0438\u044e \u0441\u0445\u0435\u043c\u044b; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            )

        stored_version = int(row[0])
        if stored_version != SCHEMA_VERSION:
            raise StorageError(
                f"FTS index \u0438\u043c\u0435\u0435\u0442 \u0432\u0435\u0440\u0441\u0438\u044e "
                f"\u0441\u0445\u0435\u043c\u044b {stored_version}, "
                f"\u0442\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f {SCHEMA_VERSION}; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            )

    def verify_freshness(self, current_documents: Sequence[VaultDocument]) -> None:
        """Verify the index is fresh relative to the current Vault state.

        Computes the source fingerprint for *current_documents* and
        compares it with the stored fingerprint.  Raises ``StorageError``
        if they differ.

        Args:
            current_documents: The current canonical Vault documents.

        Raises:
            StorageError: The index is stale or missing.
        """
        if not self._index_path.exists():
            raise StorageError(
                "FTS index \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            )

        try:
            conn = sqlite3.connect(str(self._index_path))
        except sqlite3.DatabaseError as exc:
            raise StorageError(
                "FTS index \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild",
                cause=exc,
            ) from exc

        try:
            cursor = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'source_fingerprint'"
            )
            row = cursor.fetchone()
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise StorageError(
                "FTS index \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild",
                cause=exc,
            ) from exc

        if row is None:
            conn.close()
            raise StorageError(
                "FTS index \u043d\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 "
                "\u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c\u043d\u0443\u044e \u0441\u0443\u043c\u043c\u0443; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            )

        conn.close()

        stored_fingerprint = row[0]
        current_fingerprint = _compute_source_fingerprint(current_documents)

        if stored_fingerprint != current_fingerprint:
            raise StorageError(
                "FTS index \u0443\u0441\u0442\u0430\u0440\u0435\u043b; "
                "\u0438\u0441\u0445\u043e\u0434\u043d\u044b\u0439 \u0434\u0430\u043d\u043d\u044b\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c; "
                "\u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 dnd index rebuild"
            )
