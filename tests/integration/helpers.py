"""Shared helpers for S3-08 Vault Repository integration tests.

These are test-only helpers, not production code.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.types import VaultDocument

# ── Shared constants ─────────────────────────────────────────────────────────

BASE_TIME = datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC)
MUTATION_TIME = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


# ── Helpers ──────────────────────────────────────────────────────────────────


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_entity(
    entity_id: str = "npc-gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
    revision: int = 1,
) -> Entity:
    return Entity(
        id=cast(EntityId, entity_id),
        type=entity_type,
        name=name,
        status="alive",
        visibility="player",
        knowledge_status="confirmed",
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
        revision=cast(Revision, revision),
    )


def make_document(
    entity_id: str = "npc-gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
    body: str = "",
    extra: dict[str, object] | None = None,
    revision: int = 1,
) -> VaultDocument:
    return VaultDocument(
        entity=make_entity(
            entity_id=entity_id,
            entity_type=entity_type,
            name=name,
            revision=revision,
        ),
        extra_frontmatter=extra,
        body=body,
    )


def make_audit_context(
    operation_id: str = "op-001",
    source: str = "test",
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=MUTATION_TIME,
        source=source,
    )


def can_symlink() -> bool:
    import os
    import tempfile

    tmp = tempfile.mkdtemp()
    try:
        link = os.path.join(tmp, "link")
        target = os.path.join(tmp, "target")
        Path(target).write_text("", encoding="utf-8")
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def find_entity_file(repo, entity_id: str) -> Path:
    from dnd_assistant.storage.markdown import parse
    from dnd_assistant.storage.paths import discover_entity_files

    for candidate in discover_entity_files(repo.vault_root):
        text = candidate.path.read_text(encoding="utf-8")
        parsed = parse(text)
        if parsed.entity.id == entity_id:
            return candidate.path
    raise AssertionError(f"Entity {entity_id!r} not found on disk")


def count_temp_files(directory: Path) -> int:
    count = 0
    for p in directory.iterdir():
        if p.name.startswith(".") and p.name.endswith(".tmp"):
            count += 1
    return count


def assert_vault_valid(repo) -> None:
    entities = repo.list_entities()
    seen_ids: set[str] = set()
    for doc in entities:
        assert doc.entity.id not in seen_ids, f"Duplicate EntityId: {doc.entity.id}"
        seen_ids.add(doc.entity.id)
        fetched = repo.get_entity(doc.entity.id)
        assert fetched.entity.id == doc.entity.id
        assert fetched.entity.type == doc.entity.type
