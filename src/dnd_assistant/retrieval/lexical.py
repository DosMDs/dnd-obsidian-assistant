"""Provider-independent lexical-index contract.

This module defines the abstract interface for a rebuildable lexical
(Full-Text Search) index over campaign entities.  The concrete SQLite
FTS5 implementation lives in ``retrieval.index``.

The lexical index is **derived storage only**.  It must be fully
disposable and reconstructable from the canonical Vault.

This module depends only on retrieval-layer types and must not import:
    sqlite3, storage implementation internals, models, tools, ollama
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dnd_assistant.domain.types import EntityId
from dnd_assistant.storage.types import VaultDocument


@dataclass(frozen=True)
class LexicalHit:
    """A single lexical-index search result."""

    entity_id: EntityId
    """The stable domain identifier of the matched entity."""

    score: float
    """The FTS relevance score (bm25).  Smaller values mean better matches."""


@runtime_checkable
class LexicalIndex(Protocol):
    """Provider-independent lexical index over campaign entities.

    The index is rebuildable from a sequence of ``VaultDocument`` values
    and is expected to contain only ``Visibility.PLAYER`` entities.
    """

    def search(self, query: str, *, limit: int = 20) -> Sequence[LexicalHit]:
        """Search the lexical index and return ranked hits.

        Args:
            query: The literal search text (not an FTS query expression).
            limit: Maximum number of hits to return.

        Returns:
            Ranked ``LexicalHit`` values ordered by descending relevance.

        Raises:
            StorageError: The index is missing, corrupt, stale, or
                the query could not be executed.
        """
        ...

    def rebuild(self, documents: Sequence[VaultDocument]) -> None:
        """Rebuild the index from the given canonical documents.

        The implementation must:
        - create a new temporary index;
        - populate it with the supplied documents;
        - atomically replace the old index.

        Args:
            documents: Canonical entity documents to index (expected
                to be player-visible only).

        Raises:
            StorageError: The rebuild failed.
        """
        ...


__all__: list[str] = [
    "LexicalHit",
    "LexicalIndex",
]
