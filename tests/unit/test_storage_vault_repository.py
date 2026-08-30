"""Tests for ObsidianVaultRepository (S3-05).

Covers:
- Repository construction (path/audit validation)
- get_entity / list_entities success paths
- Corruption handling (malformed files, type mismatch, duplicates)
- create_entity lifecycle (audit intent -> atomic write -> committed)
- Failure semantics (corrupt audit, intent failure, write failure, committed-audit failure)
- Filename generation policy
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest import mock

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.markdown import serialize
from dnd_assistant.storage.paths import entity_directory
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_entity(
    entity_id: str = "npc-gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
) -> Entity:
    return Entity(
        id=cast(EntityId, entity_id),
        type=entity_type,
        name=name,
        status="alive",
        visibility="player",
        knowledge_status="confirmed",
        created_at=datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC),
        revision=cast(Revision, 1),
    )


def _make_document(
    entity_id: str = "npc-gandalf",
    entity_type: EntityType = EntityType.NPC,
    name: str = "Gandalf",
    body: str = "",
    extra: dict[str, object] | None = None,
) -> VaultDocument:
    return VaultDocument(
        entity=_make_entity(entity_id=entity_id, entity_type=entity_type, name=name),
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
    """Create a minimal Vault with _system/audit/ and canonical entity dirs.

    Returns (vault_root, audit_service, audit_log_path).
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    # Create _system/audit/
    audit_dir = vault_root / "_system" / "audit"
    audit_dir.mkdir(parents=True)

    audit_log = audit_dir / "audit.jsonl"
    audit_service = AuditService(audit_log)

    # Create canonical entity directories
    for entity_type in EntityType:
        edir = entity_directory(vault_root, entity_type)
        edir.mkdir(parents=True)

    return vault_root, audit_service, audit_log


def _can_symlink() -> bool:
    """Check whether the OS/environment supports symlinks."""
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


# ═════════════════════════════════════════════════════════════════════════════
# Repository construction
# ═════════════════════════════════════════════════════════════════════════════


class TestRepositoryConstruction:
    """ObsidianVaultRepository constructor validation."""

    def test_valid_vault_and_audit(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        assert repo.vault_root == vault_root.resolve()
        assert repo.audit_service is audit_service

    def test_invalid_vault_root_missing(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        missing = tmp_path / "nonexistent"
        with pytest.raises(StorageError, match="must be an existing directory"):
            ObsidianVaultRepository(missing, audit_service)

    def test_audit_log_outside_vault_rejected(self, tmp_path: Path) -> None:
        vault_root, _, _ = _setup_vault(tmp_path)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_log = outside_dir / "audit.jsonl"
        bad_service = AuditService(outside_log)
        with pytest.raises(StorageError, match="outside the Vault root"):
            ObsidianVaultRepository(vault_root, bad_service)

    def test_audit_log_outside_system_audit_rejected(self, tmp_path: Path) -> None:
        vault_root, _, _ = _setup_vault(tmp_path)
        wrong_dir = vault_root / "other"
        wrong_dir.mkdir()
        wrong_log = wrong_dir / "audit.jsonl"
        bad_service = AuditService(wrong_log)
        with pytest.raises(StorageError, match="must be beneath"):
            ObsidianVaultRepository(vault_root, bad_service)

    def test_missing_system_audit_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        import shutil

        shutil.rmtree(str(vault_root / "_system"))
        with pytest.raises(StorageError, match="does not exist"):
            ObsidianVaultRepository(vault_root, audit_service)


# ═════════════════════════════════════════════════════════════════════════════
# Read / list — success
# ═════════════════════════════════════════════════════════════════════════════


class TestReadListSuccess:
    """Successful read and list operations."""

    def test_empty_vault_returns_empty_list(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        assert repo.list_entities() == []

    def test_list_empty_by_type(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        assert repo.list_entities(entity_type=EntityType.NPC) == []

    def test_one_npc(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))

        result = repo.list_entities()
        assert len(result) == 1
        assert result[0].entity.id == "npc-gandalf"

    def test_all_four_types(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        docs = [
            _make_document(entity_id="npc-001", entity_type=EntityType.NPC),
            _make_document(entity_id="loc-001", entity_type=EntityType.LOCATION),
            _make_document(entity_id="qst-001", entity_type=EntityType.QUEST),
            _make_document(entity_id="itm-001", entity_type=EntityType.ITEM),
        ]
        for i, doc in enumerate(docs):
            repo.create_entity(doc, audit=_make_audit_context(f"op-{i:03d}"))

        all_entities = repo.list_entities()
        assert len(all_entities) == 4

    def test_type_filtered_list(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-001", entity_type=EntityType.NPC),
            audit=_make_audit_context("op-001"),
        )
        repo.create_entity(
            _make_document(entity_id="loc-001", entity_type=EntityType.LOCATION),
            audit=_make_audit_context("op-002"),
        )

        npcs = repo.list_entities(entity_type=EntityType.NPC)
        assert len(npcs) == 1
        assert npcs[0].entity.id == "npc-001"

        locs = repo.list_entities(entity_type=EntityType.LOCATION)
        assert len(locs) == 1
        assert locs[0].entity.id == "loc-001"

    def test_unicode_entity_and_body(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = _make_document(
            entity_id="персонаж-001",
            name="Гэндальф",
            body="## Описание\nСерый маг.\n",
        )
        repo.create_entity(doc, audit=_make_audit_context("op-001"))

        result = repo.get_entity("персонаж-001")
        assert result.entity.name == "Гэндальф"
        assert result.body == "## Описание\nСерый маг.\n"

    def test_extra_frontmatter_preserved(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = _make_document(
            entity_id="npc-frodo",
            extra={"race": "Hobbit", "age": 50},
        )
        repo.create_entity(doc, audit=_make_audit_context("op-001"))

        result = repo.get_entity("npc-frodo")
        assert result.extra_frontmatter.get("race") == "Hobbit"
        assert result.extra_frontmatter.get("age") == 50

    def test_get_entity_by_exact_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))

        result = repo.get_entity("npc-gandalf")
        assert result.entity.id == "npc-gandalf"

    def test_get_entity_renamed_file_still_found(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))

        # Rename the file (simulate user renaming in Obsidian)
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        files = list(npc_dir.iterdir())
        assert len(files) == 1
        new_name = npc_dir / "renamed-gandalf.md"
        files[0].rename(new_name)

        # Must still find by ID
        result = repo.get_entity("npc-gandalf")
        assert result.entity.id == "npc-gandalf"

    def test_get_entity_not_found(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        with pytest.raises(NotFoundError):
            repo.get_entity("nonexistent")

    def test_get_entity_invalid_id_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        with pytest.raises(ValidationError):
            repo.get_entity("")

    def test_no_filename_lookup(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = _make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=_make_audit_context("op-001"))

        # A filename-like string must not be found
        with pytest.raises(NotFoundError):
            repo.get_entity("entity-")


# ═════════════════════════════════════════════════════════════════════════════
# Corruption handling
# ═════════════════════════════════════════════════════════════════════════════


class TestCorruptionHandling:
    """Behaviour when persisted files are malformed or inconsistent."""

    def test_malformed_frontmatter_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        bad_file = npc_dir / "bad.md"
        bad_file.write_text("not frontmatter", encoding="utf-8")

        with pytest.raises(StorageError, match="Malformed"):
            repo.list_entities()

    def test_invalid_entity_schema_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        bad_file = npc_dir / "bad.md"
        bad_file.write_text(
            "---\nid: npc-bad\nname: Bad\n---\nbody\n",
            encoding="utf-8",
        )

        with pytest.raises(StorageError, match="Malformed"):
            repo.list_entities()

    def test_directory_type_mismatch_raises_storage_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        loc_dir = entity_directory(vault_root, EntityType.LOCATION)
        mismatch_file = loc_dir / "fake.md"
        mismatch_file.write_text(
            "---\n"
            'id: "npc-mismatch"\n'
            'type: "npc"\n'
            'name: "Mismatch"\n'
            'status: "alive"\n'
            'visibility: "player"\n'
            'knowledge_status: "confirmed"\n'
            'created_at: "2026-08-30T10:00:00+00:00"\n'
            'updated_at: "2026-08-30T10:00:00+00:00"\n'
            "revision: 1\n"
            "---\nbody\n",
            encoding="utf-8",
        )

        with pytest.raises(StorageError, match="type mismatch"):
            repo.list_entities()

    def test_duplicate_id_across_types_raises_conflict(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="dup-001", entity_type=EntityType.NPC),
            audit=_make_audit_context("op-001"),
        )

        loc_dir = entity_directory(vault_root, EntityType.LOCATION)
        dup_file = loc_dir / "dup.md"
        dup_file.write_text(
            "---\n"
            'id: "dup-001"\n'
            'type: "location"\n'
            'name: "Duplicate"\n'
            'status: "active"\n'
            'visibility: "player"\n'
            'knowledge_status: "confirmed"\n'
            'created_at: "2026-08-30T10:00:00+00:00"\n'
            'updated_at: "2026-08-30T10:00:00+00:00"\n'
            "revision: 1\n"
            "---\nbody\n",
            encoding="utf-8",
        )

        with pytest.raises(ConflictError, match="Duplicate"):
            repo.list_entities()

    def test_duplicate_id_in_same_type_raises_conflict(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="dup-001", entity_type=EntityType.NPC),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        dup_file = npc_dir / "dup2.md"
        dup_file.write_text(
            "---\n"
            'id: "dup-001"\n'
            'type: "npc"\n'
            'name: "Duplicate"\n'
            'status: "alive"\n'
            'visibility: "player"\n'
            'knowledge_status: "confirmed"\n'
            'created_at: "2026-08-30T10:00:00+00:00"\n'
            'updated_at: "2026-08-30T10:00:00+00:00"\n'
            "revision: 1\n"
            "---\nbody\n",
            encoding="utf-8",
        )

        with pytest.raises(ConflictError, match="Duplicate"):
            repo.list_entities()

    def test_type_filtered_list_still_detects_global_duplicate(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="dup-001", entity_type=EntityType.NPC),
            audit=_make_audit_context("op-001"),
        )

        loc_dir = entity_directory(vault_root, EntityType.LOCATION)
        dup_file = loc_dir / "dup.md"
        dup_file.write_text(
            "---\n"
            'id: "dup-001"\n'
            'type: "location"\n'
            'name: "Duplicate"\n'
            'status: "active"\n'
            'visibility: "player"\n'
            'knowledge_status: "confirmed"\n'
            'created_at: "2026-08-30T10:00:00+00:00"\n'
            'updated_at: "2026-08-30T10:00:00+00:00"\n'
            "revision: 1\n"
            "---\nbody\n",
            encoding="utf-8",
        )

        with pytest.raises(ConflictError, match="Duplicate"):
            repo.list_entities(entity_type=EntityType.NPC)


# ═════════════════════════════════════════════════════════════════════════════
# Create entity — duplicate / conflict
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateEntityDuplicate:
    """create_entity duplicate detection."""

    def test_duplicate_yaml_id_raises_conflict(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        with pytest.raises(ConflictError, match="already exists"):
            repo.create_entity(
                _make_document(entity_id="npc-gandalf"),
                audit=_make_audit_context("op-002"),
            )

    def test_no_target_overwritten_on_duplicate(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        files_before = set(npc_dir.iterdir())

        with pytest.raises(ConflictError):
            repo.create_entity(
                _make_document(entity_id="npc-gandalf"),
                audit=_make_audit_context("op-002"),
            )

        files_after = set(npc_dir.iterdir())
        assert files_after == files_before

    def test_audit_intent_not_written_for_duplicate(self, tmp_path: Path) -> None:
        vault_root, audit_service, audit_log = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        with pytest.raises(ConflictError):
            repo.create_entity(
                _make_document(entity_id="npc-gandalf"),
                audit=_make_audit_context("op-002"),
            )

        records = audit_service.read_all()
        assert len(records) == 2  # Only the first create's intent + committed


# ═════════════════════════════════════════════════════════════════════════════
# Create entity — filename policy
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateEntityFilename:
    """Filename generation policy."""

    def test_generated_filename_is_md(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        files = list(npc_dir.iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".md"

    def test_generated_filename_is_safe_ascii(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        filename = next(npc_dir.iterdir()).name
        assert filename.isascii()

    def test_filename_not_entity_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        filename = next(npc_dir.iterdir()).name
        assert "gandalf" not in filename

    def test_filename_not_display_name(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf", name="Gandalf the Grey"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        filename = next(npc_dir.iterdir()).name
        assert "Gandalf" not in filename

    def test_filename_starts_with_entity_prefix(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        filename = next(npc_dir.iterdir()).name
        assert filename.startswith("entity-")

    def test_manual_rename_does_not_break_get_entity(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        old_file = next(npc_dir.iterdir())
        new_file = npc_dir / "my-custom-name.md"
        old_file.rename(new_file)

        result = repo.get_entity("npc-gandalf")
        assert result.entity.id == "npc-gandalf"

    def test_collision_regenerates_filename(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        npc_dir = entity_directory(vault_root, EntityType.NPC)

        # Pre-create a valid entity file that will collide
        first_doc = _make_document(entity_id="npc-other", name="Other")
        first_text = serialize(first_doc)
        (npc_dir / "entity-first.md").write_text(first_text, encoding="utf-8")

        # Create another entity — filename collision is handled internally
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        files = list(npc_dir.iterdir())
        assert len(files) == 2  # pre-existing + created


# ═════════════════════════════════════════════════════════════════════════════
# Create entity — audit lifecycle
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateEntityAuditLifecycle:
    """Audit records emitted during successful create."""

    def test_exactly_two_audit_records(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert len(records) == 2

    def test_same_operation_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert records[0].operation_id == "op-001"
        assert records[1].operation_id == "op-001"

    def test_operation_is_create_entity(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert records[0].operation == "create_entity"
        assert records[1].operation == "create_entity"

    def test_first_is_intent_second_is_committed(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert records[0].phase == "intent"
        assert records[1].phase == "committed"

    def test_both_have_same_entity_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert records[0].entity_id == "npc-gandalf"
        assert records[1].entity_id == "npc-gandalf"

    def test_before_hash_is_none(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert records[0].before_hash is None
        assert records[1].before_hash is None

    def test_same_after_hash(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        records = audit_service.read_all()
        assert records[0].after_hash is not None
        assert records[0].after_hash == records[1].after_hash

    def test_same_context_metadata(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        ctx = _make_audit_context(operation_id="op-001", source="my_test")
        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=ctx,
        )

        records = audit_service.read_all()
        assert records[0].source == "my_test"
        assert records[1].source == "my_test"


# ═════════════════════════════════════════════════════════════════════════════
# Create entity — failure semantics
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateEntityFailureSemantics:
    """Failure behaviour during create_entity lifecycle."""

    def test_operation_id_reuse_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        repo.create_entity(
            _make_document(entity_id="npc-gandalf"),
            audit=_make_audit_context("op-001"),
        )

        with pytest.raises(ConflictError, match="already been used"):
            repo.create_entity(
                _make_document(entity_id="npc-frodo"),
                audit=_make_audit_context("op-001"),
            )

    def test_corrupt_audit_preflight_aborts_create(self, tmp_path: Path) -> None:
        vault_root, audit_service, audit_log = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        audit_log.write_text("not json\n", encoding="utf-8")

        with pytest.raises(StorageError, match="corruption"):
            repo.create_entity(
                _make_document(entity_id="npc-gandalf"),
                audit=_make_audit_context("op-001"),
            )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        assert list(npc_dir.iterdir()) == []

    def test_intent_append_failure_aborts_create(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        def _broken_append(*args: object, **kwargs: object) -> None:
            raise StorageError("append failed")

        with mock.patch.object(audit_service, "append", _broken_append):
            with pytest.raises(StorageError):
                repo.create_entity(
                    _make_document(entity_id="npc-gandalf"),
                    audit=_make_audit_context("op-001"),
                )

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        assert list(npc_dir.iterdir()) == []

    def test_entity_write_failure_leaves_intent(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        # Make os.replace fail so that atomic_write_text raises StorageError.
        # The intent record is written before the atomic write, so it persists.
        import os as os_mod

        with mock.patch.object(os_mod, "replace", side_effect=OSError(5, "Input/output error")):
            with pytest.raises(StorageError):
                repo.create_entity(
                    _make_document(entity_id="npc-gandalf"),
                    audit=_make_audit_context("op-001"),
                )

        records = audit_service.read_all()
        assert len(records) == 1
        assert records[0].phase == "intent"

        npc_dir = entity_directory(vault_root, EntityType.NPC)
        assert list(npc_dir.iterdir()) == []

    def test_committed_audit_failure_entity_still_exists(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        call_count = 0
        original_append = audit_service.append

        def _fail_on_second_append(record: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise StorageError("committed append failed")
            original_append(record)

        with mock.patch.object(audit_service, "append", side_effect=_fail_on_second_append):
            with pytest.raises(StorageError, match="audit finalization failed"):
                repo.create_entity(
                    _make_document(entity_id="npc-gandalf"),
                    audit=_make_audit_context("op-001"),
                )

        # Entity file still exists
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        files = list(npc_dir.iterdir())
        assert len(files) == 1

        # Intent record remains
        records = audit_service.read_all()
        assert len(records) == 1
        assert records[0].phase == "intent"

        # Entity is still readable
        result = repo.get_entity("npc-gandalf")
        assert result.entity.id == "npc-gandalf"


# ═════════════════════════════════════════════════════════════════════════════
# Boundary tests
# ═════════════════════════════════════════════════════════════════════════════


class TestVaultRepositoryBoundaries:
    """Module boundary checks."""

    def test_module_importable(self) -> None:
        import dnd_assistant.storage.vault_repository  # noqa: F401

    def test_re_exported(self) -> None:
        from dnd_assistant.storage import ObsidianVaultRepository  # noqa: F401

    def test_no_models_import(self) -> None:
        import dnd_assistant.storage.vault_repository as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.models" not in content

    def test_no_retrieval_import(self) -> None:
        import dnd_assistant.storage.vault_repository as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.retrieval" not in content

    def test_no_tools_import(self) -> None:
        import dnd_assistant.storage.vault_repository as mod

        source = str(mod.__file__)
        with open(source, encoding="utf-8") as f:
            content = f.read()
        assert "from dnd_assistant.tools" not in content
