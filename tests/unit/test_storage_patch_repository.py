"""Repository-level tests for patch_entity (S3-06).

Covers:
- Optimistic concurrency (revision checking)
- Individual field changes
- Immutable fields unchanged
- Body preservation
- Extra-frontmatter preservation
- Filename/path preservation
- Audit lifecycle
- Failure semantics (conflict, intent, write, committed-audit)
- Concurrent/manual edit detection
- Integration cycle (create -> get -> patch -> get)
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest import mock

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.paths import entity_directory
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository


def _make_entity(
    entity_id: str = "npc-gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
    revision: int = 1,
) -> Entity:
    ts = datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC)
    return Entity(
        id=cast(EntityId, entity_id),
        type=entity_type,
        name=name,
        status="alive",
        visibility="player",
        knowledge_status="confirmed",
        created_at=ts,
        updated_at=ts,
        revision=cast(Revision, revision),
    )


def _make_document(
    entity_id: str = "npc-gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
    body: str = "",
    extra: dict[str, object] | None = None,
    revision: int = 1,
) -> VaultDocument:
    return VaultDocument(
        entity=_make_entity(
            entity_id=entity_id,
            entity_type=entity_type,
            name=name,
            revision=revision,
        ),
        extra_frontmatter=extra,
        body=body,
    )


def _make_audit_context(
    operation_id: str = "op-001",
    source: str = "test",
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC),
        source=source,
    )


def _setup_vault(tmp_path: Path) -> tuple[Path, AuditService, Path]:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    audit_dir = vault_root / "_system" / "audit"
    audit_dir.mkdir(parents=True)
    audit_log = audit_dir / "audit.jsonl"
    audit_service = AuditService(audit_log)
    for entity_type in EntityType:
        edir = entity_directory(vault_root, entity_type)
        edir.mkdir(parents=True)
    return vault_root, audit_service, audit_log


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — optimistic concurrency
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityOptimisticConcurrency:
    """Revision checking during patch."""

    def test_revision_1_to_2(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.revision == 2
        assert result.entity.name == "Gandalf the White"

    def test_revision_n_to_n_plus_1(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf v2"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf v3"),
            expected_revision=2,
            audit=_make_audit_context("op-003"),
        )
        assert result.entity.revision == 3
        assert result.entity.name == "Gandalf v3"

    def test_stale_expected_revision_raises_conflict(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        with pytest.raises(ConflictError, match="Revision mismatch"):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Stale"),
                expected_revision=999,
                audit=_make_audit_context("op-002"),
            )

    def test_stale_conflict_produces_zero_new_audit_records(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        records_before = len(audit_service.read_all())
        with pytest.raises(ConflictError):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Stale"),
                expected_revision=999,
                audit=_make_audit_context("op-002"),
            )
        assert len(audit_service.read_all()) == records_before

    def test_bool_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision=True,
                audit=_make_audit_context("op-002"),
            )

    def test_string_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision="1",
                audit=_make_audit_context("op-002"),
            )

    def test_zero_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision=0,
                audit=_make_audit_context("op-002"),
            )

    def test_negative_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision=-1,
                audit=_make_audit_context("op-002"),
            )

    def test_revision_validation_cause_preserved(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError) as exc:
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision=True,
                audit=_make_audit_context("op-002"),
            )
        assert exc.value.__cause__ is not None


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — field changes
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityFieldChanges:
    """Individual field changes via patch."""

    def test_patch_name(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf", name="Gandalf"),
            audit=_make_audit_context("op-001"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.name == "Gandalf the White"

    def test_patch_status(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(status="retired"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.status == "retired"

    def test_patch_visibility(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(visibility="dm"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.visibility == "dm"

    def test_patch_knowledge_status(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(knowledge_status="inferred"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.knowledge_status == "inferred"

    def test_patch_created_session(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(created_session="S007"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.created_session == "S007"

    def test_patch_clear_created_session(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(created_session="S007"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(created_session=None),
            expected_revision=2,
            audit=_make_audit_context("op-003"),
        )
        assert result.entity.created_session is None

    def test_patch_last_seen_session(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(last_seen_session="S014"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.last_seen_session == "S014"

    def test_patch_clear_last_seen_session(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(last_seen_session="S014"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(last_seen_session=None),
            expected_revision=2,
            audit=_make_audit_context("op-003"),
        )
        assert result.entity.last_seen_session is None

    def test_patch_tags(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(tags=["wizard", "istari"]),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.tags == ["wizard", "istari"]

    def test_patch_tags_replace(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(tags=["wizard"]),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(tags=["maia"]),
            expected_revision=2,
            audit=_make_audit_context("op-003"),
        )
        assert result.entity.tags == ["maia"]


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — immutable fields unchanged
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityImmutableFields:
    """Immutable fields must remain unchanged after patch."""

    def test_id_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.id == "npc-gandalf"

    def test_type_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf", entity_type=EntityType.NPC),
            audit=_make_audit_context("op-001"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.type == EntityType.NPC

    def test_created_at_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        created = datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC)
        doc = VaultDocument(
            entity=Entity(
                id=cast(EntityId, "npc-gandalf"),
                type=EntityType.NPC,
                name="Gandalf",
                status="alive",
                visibility="player",
                knowledge_status="confirmed",
                created_at=created,
                updated_at=created,
                revision=cast(Revision, 1),
            ),
        )
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.created_at == created

    def test_schema_version_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.schema_version == 1


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — body preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityBodyPreservation:
    """Markdown body must remain unchanged after patch."""

    BODY_LF = "## Description\nGandalf is a wizard.\n"
    BODY_CRLF = "## Description\r\nGandalf is a wizard.\r\n"
    BODY_MIXED = "## Description\nGandalf is a wizard.\r\nMore text\n"
    BODY_UNICODE = "## Описание\nГэндальф — серый маг.\n"
    BODY_NO_TRAILING = "## Description\nGandalf is a wizard."
    BODY_TRAILING = "## Description\nGandalf is a wizard.\n"

    def _patch_and_check(self, tmp_path: Path, body: str) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf", body=body),
            audit=_make_audit_context("op-001"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.body == body

    def test_lf_body_preserved(self, tmp_path: Path) -> None:
        self._patch_and_check(tmp_path, self.BODY_LF)

    def test_crlf_body_preserved(self, tmp_path: Path) -> None:
        self._patch_and_check(tmp_path, self.BODY_CRLF)

    def test_mixed_newlines_preserved(self, tmp_path: Path) -> None:
        self._patch_and_check(tmp_path, self.BODY_MIXED)

    def test_unicode_body_preserved(self, tmp_path: Path) -> None:
        self._patch_and_check(tmp_path, self.BODY_UNICODE)

    def test_no_trailing_newline_preserved(self, tmp_path: Path) -> None:
        self._patch_and_check(tmp_path, self.BODY_NO_TRAILING)

    def test_trailing_newline_preserved(self, tmp_path: Path) -> None:
        self._patch_and_check(tmp_path, self.BODY_TRAILING)


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — extra frontmatter preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityExtraFrontmatter:
    """Extra frontmatter keys must survive patch."""

    def test_extra_keys_survive(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(
                entity_id="npc-gandalf", extra={"aliases": ["Mithrandir"], "faction": "Istari"}
            ),
            audit=_make_audit_context("op-001"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.extra_frontmatter.get("aliases") == ["Mithrandir"]
        assert result.extra_frontmatter.get("faction") == "Istari"

    def test_multiple_extra_keys_survive(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(
                entity_id="npc-gandalf",
                extra={"age": 24000, "home": "Valinor", "title": "White Rider"},
            ),
            audit=_make_audit_context("op-001"),
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(status="retired"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.extra_frontmatter.get("age") == 24000
        assert result.extra_frontmatter.get("home") == "Valinor"
        assert result.extra_frontmatter.get("title") == "White Rider"


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — filename/path preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityFilenamePreservation:
    """Filename and path must remain unchanged after patch."""

    def test_same_path_remains(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        files_before = set(npc_dir.iterdir())
        assert len(files_before) == 1
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        files_after = set(npc_dir.iterdir())
        assert files_after == files_before

    def test_custom_filename_preserved(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        old_file = next(npc_dir.iterdir())
        custom_path = npc_dir / "my-custom-name.md"
        old_file.rename(custom_path)
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert custom_path.exists()
        assert not old_file.exists()

    def test_no_new_file_created(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert len(list(npc_dir.iterdir())) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — updated_at and revision metadata
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityUpdatedAt:
    """updated_at and revision metadata during patch."""

    def test_updated_at_is_audit_real_time(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        patch_time = datetime(2026, 8, 30, 14, 30, 0, tzinfo=UTC)
        ctx = AuditContext(operation_id="op-002", real_time=patch_time, source="test")
        result = repo.patch_entity(
            "npc-gandalf", EntityPatch(name="Updated"), expected_revision=1, audit=ctx
        )
        assert result.entity.updated_at == patch_time

    def test_updated_at_differs_from_created_at(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.updated_at != result.entity.created_at

    def test_revision_increments_once(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.revision == 2


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — audit lifecycle
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityAuditLifecycle:
    """Audit records emitted during successful patch."""

    def test_exactly_two_audit_records(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        # 2 from create + 2 from patch = 4
        assert len(records) == 4

    def test_audit_operation_is_patch_entity(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert len(patch_records) == 2
        assert patch_records[0].phase == "intent"
        assert patch_records[1].phase == "committed"

    def test_same_operation_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert patch_records[0].operation_id == "op-002"
        assert patch_records[1].operation_id == "op-002"

    def test_same_entity_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert patch_records[0].entity_id == "npc-gandalf"
        assert patch_records[1].entity_id == "npc-gandalf"

    def test_same_before_hash(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert patch_records[0].before_hash is not None
        assert patch_records[0].before_hash == patch_records[1].before_hash

    def test_same_after_hash(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert patch_records[0].after_hash is not None
        assert patch_records[0].after_hash == patch_records[1].after_hash

    def test_before_hash_differs_from_after_hash(self, tmp_path: Path) -> None:
        """Hash must change because revision/updated_at necessarily change."""
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Updated"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert patch_records[0].before_hash != patch_records[0].after_hash

    def test_same_context_metadata(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        ctx = AuditContext(
            operation_id="op-002",
            real_time=datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC),
            source="my_tool",
        )
        repo.patch_entity(
            "npc-gandalf", EntityPatch(name="Updated"), expected_revision=1, audit=ctx
        )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert patch_records[0].source == "my_tool"
        assert patch_records[1].source == "my_tool"


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — failure semantics
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityFailureSemantics:
    """Failure behaviour during patch_entity lifecycle."""

    def test_invalid_entity_id_raises_validation_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        with pytest.raises(ValidationError):
            repo.patch_entity(
                "",
                EntityPatch(name="Bad"),
                expected_revision=1,
                audit=_make_audit_context("op-001"),
            )

    def test_not_found_raises_not_found_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        with pytest.raises(NotFoundError):
            repo.patch_entity(
                "npc-nonexistent",
                EntityPatch(name="Bad"),
                expected_revision=1,
                audit=_make_audit_context("op-001"),
            )

    def test_operation_id_reuse_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        repo.create_entity(
            _make_document(entity_id="npc-frodo"), audit=_make_audit_context("op-002")
        )
        with pytest.raises(ConflictError, match="already been used"):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision=1,
                audit=_make_audit_context("op-002"),
            )

    def test_corrupt_audit_preflight_aborts_patch(self, tmp_path: Path) -> None:
        vault_root, audit_service, audit_log = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        audit_log.write_text("not json\n", encoding="utf-8")
        with pytest.raises(StorageError, match="corruption"):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Bad"),
                expected_revision=1,
                audit=_make_audit_context("op-002"),
            )

    def test_intent_append_failure_aborts_patch(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )

        def _broken_append(*args: object, **kwargs: object) -> None:
            raise StorageError("append failed")

        with mock.patch.object(audit_service, "append", _broken_append):
            with pytest.raises(StorageError):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Bad"),
                    expected_revision=1,
                    audit=_make_audit_context("op-002"),
                )

    def test_entity_write_failure_leaves_intent(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        import os as os_mod

        with mock.patch.object(os_mod, "replace", side_effect=OSError(5, "Input/output error")):
            with pytest.raises(StorageError):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Updated"),
                    expected_revision=1,
                    audit=_make_audit_context("op-002"),
                )
        records = audit_service.read_all()
        patch_records = [r for r in records if r.operation == "patch_entity"]
        assert len(patch_records) == 1
        assert patch_records[0].phase == "intent"

    def test_committed_audit_failure_entity_still_exists(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        original_append = audit_service.append

        def _fail_on_patch_committed(record: object) -> None:
            if (
                getattr(record, "phase", None) == "committed"
                and getattr(record, "operation", None) == "patch_entity"
            ):
                raise StorageError("committed append failed")
            original_append(record)

        with mock.patch.object(audit_service, "append", side_effect=_fail_on_patch_committed):
            with pytest.raises(StorageError, match="audit finalization failed"):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Updated"),
                    expected_revision=1,
                    audit=_make_audit_context("op-002"),
                )
        result = repo.get_entity("npc-gandalf")
        assert result.entity.name == "Updated"

    def test_committed_audit_failure_preserves_cause(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        original_append = audit_service.append
        original_storage_error = StorageError("committed append failed")

        def _fail_on_committed(record: object) -> None:
            if (
                getattr(record, "phase", None) == "committed"
                and getattr(record, "operation", None) == "patch_entity"
            ):
                raise original_storage_error
            original_append(record)

        with mock.patch.object(audit_service, "append", side_effect=_fail_on_committed):
            with pytest.raises(StorageError) as exc:
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Updated"),
                    expected_revision=1,
                    audit=_make_audit_context("op-002"),
                )
        assert exc.value.__cause__ is original_storage_error


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — concurrent/manual edit detection
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityConcurrentEdit:
    """Detection of concurrent or manual edits between intent and write."""

    def test_manual_edit_without_revision_change_detected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        entity_file = next(npc_dir.iterdir())
        # Inject a manual edit after the intent audit record is written
        # by intercepting the second append call (intent is first patch append)
        original_append = audit_service.append

        def _intercept_and_edit(record: object) -> None:
            original_append(record)
            if (
                getattr(record, "phase", None) == "intent"
                and getattr(record, "operation", None) == "patch_entity"
            ):
                current = entity_file.read_text(encoding="utf-8")
                modified = current.replace("Gandalf", "Gandalf-Edited")
                entity_file.write_text(modified, encoding="utf-8")

        with mock.patch.object(audit_service, "append", side_effect=_intercept_and_edit):
            with pytest.raises(ConflictError, match="content changed"):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Updated"),
                    expected_revision=1,
                    audit=_make_audit_context("op-002"),
                )
        # Original manual edit must remain
        assert "Gandalf-Edited" in entity_file.read_text(encoding="utf-8")

    def test_manual_edit_with_revision_change_detected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"), audit=_make_audit_context("op-001")
        )
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        entity_file = next(npc_dir.iterdir())
        original_append = audit_service.append

        def _intercept_and_edit(record: object) -> None:
            original_append(record)
            if (
                getattr(record, "phase", None) == "intent"
                and getattr(record, "operation", None) == "patch_entity"
            ):
                current = entity_file.read_text(encoding="utf-8")
                modified = current.replace("revision: 1", "revision: 2")
                entity_file.write_text(modified, encoding="utf-8")

        with mock.patch.object(audit_service, "append", side_effect=_intercept_and_edit):
            with pytest.raises(ConflictError, match="revision changed"):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Updated"),
                    expected_revision=1,
                    audit=_make_audit_context("op-002"),
                )
        assert "revision: 2" in entity_file.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# Patch entity — integration cycle
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchEntityIntegration:
    """Full integration cycle: create -> get -> patch -> get."""

    def test_create_get_patch_get(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(
            entity_id="npc-gandalf", name="Gandalf", body="## Notes\nImportant NPC.\n"
        )
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        before = repo.get_entity("npc-gandalf")
        assert before.entity.name == "Gandalf"
        assert before.entity.revision == 1
        result = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White", status="ascended"),
            expected_revision=1,
            audit=_make_audit_context("op-002"),
        )
        assert result.entity.name == "Gandalf the White"
        assert result.entity.status == "ascended"
        assert result.entity.revision == 2
        assert result.body == "## Notes\nImportant NPC.\n"
        after = repo.get_entity("npc-gandalf")
        assert after.entity.name == "Gandalf the White"
        assert after.entity.revision == 2
