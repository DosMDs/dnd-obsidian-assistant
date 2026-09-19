"""Shared UI-agnostic FTS index rebuild/verify composition.

Extracted from the inline construction previously owned by ``dnd index rebuild``
so the bootstrap finalization step can reuse the exact source-fingerprint
algorithm without duplicating it.  Both callers must observe identical behavior.

This module owns concrete dependency construction only.  It contains no Russian
text, no ``typer``/``textual`` types and no derived-store policy of its own.

This module is a composition layer and may import concrete storage/retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dnd_assistant.domain.types import Visibility
from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

__all__ = [
    "IndexRebuildResult",
    "compose_fts_documents",
    "rebuild_fts_index",
    "verify_fts_index",
]


@dataclass(frozen=True, slots=True)
class IndexRebuildResult:
    """Outcome of rebuilding the derived FTS index from canonical documents."""

    document_count: int
    player_count: int
    index_path: str


def compose_fts_documents(vault_root: Path) -> list[VaultDocument]:
    """Read the canonical documents through the strict Vault repository.

    Raises:
        StorageError: The Vault root/audit topology is invalid or the canonical
            entity set is malformed/duplicated.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    repository = ObsidianVaultRepository(
        vault_root=str(vault_root),
        audit_service=audit_service,
    )
    return repository.list_entities()


def rebuild_fts_index(vault_root: Path) -> IndexRebuildResult:
    """Rebuild the FTS index from a fresh canonical read.

    Only the already-defined player-visible entity set is indexed; visibility is
    never altered to index more content.

    Raises:
        StorageError: A canonical read or the index publication failed.
    """
    documents = compose_fts_documents(vault_root)
    index = SqliteFtsIndex(vault_root=str(vault_root))
    index.rebuild(documents)
    player_count = sum(
        1 for document in documents if document.entity.visibility is Visibility.PLAYER
    )
    return IndexRebuildResult(
        document_count=len(documents),
        player_count=player_count,
        index_path=str(index.index_path),
    )


def verify_fts_index(vault_root: Path) -> None:
    """Verify the index is fresh against a fresh canonical read.

    Raises:
        StorageError: The index is missing/stale/corrupt/incompatible.
    """
    documents = compose_fts_documents(vault_root)
    SqliteFtsIndex(vault_root=str(vault_root)).verify_freshness(documents)
