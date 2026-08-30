"""Repository-level tests for append_entity_fact (S3-07).

Covers:
- Fact validation
- Body rendering (empty, LF, CRLF, no trailing, Unicode, mixed)
- Entity metadata preservation (id, type, name, revision, updated_at, etc.)
- Extra-frontmatter preservation
- File/path preservation (same file, renamed file)
- Audit lifecycle (intent + committed, operation name, hashes)
- Optimistic concurrency (revision checking, stale, repeated)
- Failure semantics (invalid input, not found, conflict, intent/write/audit failure)
- Concurrent/manual edit detection
- Cross-operation integration (create -> append -> patch -> append)
- Runtime VaultRepository structural conformance
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
from dnd_assistant.storage.paths import entity_directory
from dnd_assistant.storage.types import VaultDocument, VaultRepository
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

# ── Helpers ─────────────────────────────────────────────────────────────────


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
# Fact validation
# ═════════════════════════════════════════════════════════════════════════════


class TestFactValidation:
    """Fact input validation for append_entity_fact."""

    def test_normal_ascii_accepted(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="Vargos lied about the eastern gate.",
            audit=_make_audit_context("op-002"),
        )
        assert "- Vargos lied about the eastern gate." in result.body

    def test_unicode_accepted(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="\u041d\u043e\u0441\u0438\u0442 \u0441\u0435\u0440\u0435\u0431\u0440\u044f\u043d\u044b\u0439 \u0430\u043c\u0443\u043b\u0435\u0442.",
            audit=_make_audit_context("op-002"),
        )
        assert (
            "\u041d\u043e\u0441\u0438\u0442 \u0441\u0435\u0440\u0435\u0431\u0440\u044f\u043d\u044b\u0439 \u0430\u043c\u0443\u043b\u0435\u0442."
            in result.body
        )

    def test_special_chars_accepted(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="Seen near Caf\u00e9 de l'\u00c9toile.",
            audit=_make_audit_context("op-002"),
        )
        assert "- Seen near Caf\u00e9 de l'\u00c9toile." in result.body

    def test_empty_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="empty"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="",
                audit=_make_audit_context("op-002"),
            )

    def test_whitespace_only_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="whitespace"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="   ",
                audit=_make_audit_context("op-002"),
            )

    def test_leading_whitespace_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="whitespace"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="  leading space",
                audit=_make_audit_context("op-002"),
            )

    def test_trailing_whitespace_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="whitespace"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="trailing space ",
                audit=_make_audit_context("op-002"),
            )

    def test_newline_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="non-printable"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="fact\nsecond fact",
                audit=_make_audit_context("op-002"),
            )

    def test_crlf_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="non-printable"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="fact\r\nsecond fact",
                audit=_make_audit_context("op-002"),
            )

    def test_tab_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="non-printable"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="fact\twith tab",
                audit=_make_audit_context("op-002"),
            )

    def test_non_string_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError, match="string"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact=123,  # type: ignore[arg-type]
                audit=_make_audit_context("op-002"),
            )


# ═════════════════════════════════════════════════════════════════════════════
# Body rendering
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactBodyRendering:
    """Markdown body rendering after append."""

    def test_empty_body(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body=""), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.body == "- Fact\n"

    def test_lf_trailing(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body="Existing\n"), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.body == "Existing\n- Fact\n"

    def test_crlf_trailing(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body="Existing\r\n"), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.body == "Existing\r\n- Fact\r\n"

    def test_no_trailing_newline(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body="Existing"), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.body.startswith("Existing")
        assert "- Fact" in result.body

    def test_existing_blank_line(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body="Existing\n\n"), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.body == "Existing\n\n- Fact\n"

    def test_unicode_body_and_fact(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(
                body="## \u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435\n\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444.\n"
            ),
            audit=_make_audit_context("op-001"),
        )
        result = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="\u041d\u043e\u0441\u0438\u0442 \u0430\u043c\u0443\u043b\u0435\u0442.",
            audit=_make_audit_context("op-002"),
        )
        assert (
            result.body
            == "## \u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435\n\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444.\n- \u041d\u043e\u0441\u0438\u0442 \u0430\u043c\u0443\u043b\u0435\u0442.\n"
        )

    def test_old_body_exact_prefix(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        body = "## Notes\nImportant NPC.\n"
        repo.create_entity(_make_document(body=body), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="New fact", audit=_make_audit_context("op-002")
        )
        assert result.body[: len(body)] == body

    def test_fact_appears_exactly_once(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="Single fact.",
            audit=_make_audit_context("op-002"),
        )
        assert result.body.count("Single fact.") == 1


# ═════════════════════════════════════════════════════════════════════════════
# Entity metadata preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactEntityMetadata:
    """Entity fields preserved after append."""

    def test_id_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.id == "npc-gandalf"

    def test_type_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.type == EntityType.NPC

    def test_name_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(name="Gandalf"), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.name == "Gandalf"

    def test_status_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.status == "alive"

    def test_visibility_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.visibility == "player"

    def test_knowledge_status_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.knowledge_status == "confirmed"

    def test_created_session_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document()
        doc.entity.created_session = "S001"
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.created_session == "S001"

    def test_last_seen_session_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document()
        doc.entity.last_seen_session = "S002"
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.last_seen_session == "S002"

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
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.created_at == created

    def test_schema_version_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.schema_version == 1

    def test_tags_unchanged(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        doc = _make_document()
        doc.entity.tags = ["wizard", "istari"]
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.tags == ["wizard", "istari"]

    def test_revision_incremented(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.revision == 2

    def test_updated_at_is_audit_real_time(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        append_time = datetime(2026, 8, 30, 14, 30, 0, tzinfo=UTC)
        ctx = AuditContext(operation_id="op-002", real_time=append_time, source="test")
        result = repo.append_entity_fact("npc-gandalf", expected_revision=1, fact="Fact", audit=ctx)
        assert result.entity.updated_at == append_time

    def test_updated_at_differs_from_created_at(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.updated_at != result.entity.created_at


# ═════════════════════════════════════════════════════════════════════════════
# Extra frontmatter preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactExtraFrontmatter:
    """Extra frontmatter keys must survive append."""

    def test_extra_keys_survive(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(
                entity_id="npc-gandalf",
                extra={"aliases": ["Mithrandir"], "faction": "Istari"},
            ),
            audit=_make_audit_context("op-001"),
        )
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.extra_frontmatter.get("aliases") == ["Mithrandir"]
        assert result.extra_frontmatter.get("faction") == "Istari"

    def test_nested_extra_survives(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            _make_document(
                entity_id="npc-gandalf",
                extra={"custom": {"key": "value", "nested": [1, 2, 3]}},
            ),
            audit=_make_audit_context("op-001"),
        )
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.extra_frontmatter.get("custom") == {"key": "value", "nested": [1, 2, 3]}


# ═════════════════════════════════════════════════════════════════════════════
# File/path preservation
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactFilenamePreservation:
    """Filename and path must remain unchanged after append."""

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
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
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
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
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
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert len(list(npc_dir.iterdir())) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Audit lifecycle
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactAuditLifecycle:
    """Audit records emitted during successful append."""

    def test_exactly_two_audit_records(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        assert len(records) == 4  # 2 create + 2 append

    def test_audit_operation_is_append_entity_fact(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert len(append_records) == 2
        assert append_records[0].phase == "intent"
        assert append_records[1].phase == "committed"

    def test_same_operation_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert append_records[0].operation_id == "op-002"
        assert append_records[1].operation_id == "op-002"

    def test_same_entity_id(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert append_records[0].entity_id == "npc-gandalf"
        assert append_records[1].entity_id == "npc-gandalf"

    def test_same_before_hash(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert append_records[0].before_hash is not None
        assert append_records[0].before_hash == append_records[1].before_hash

    def test_same_after_hash(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert append_records[0].after_hash is not None
        assert append_records[0].after_hash == append_records[1].after_hash

    def test_before_hash_differs_from_after_hash(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert append_records[0].before_hash != append_records[0].after_hash

    def test_same_context_metadata(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        ctx = AuditContext(
            operation_id="op-002",
            real_time=datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC),
            source="my_tool",
        )
        repo.append_entity_fact("npc-gandalf", expected_revision=1, fact="Fact", audit=ctx)
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert append_records[0].source == "my_tool"
        assert append_records[1].source == "my_tool"


# ═════════════════════════════════════════════════════════════════════════════
# Optimistic concurrency
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactOptimisticConcurrency:
    """Revision checking during append."""

    def test_revision_1_to_2(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
        )
        assert result.entity.revision == 2

    def test_revision_n_to_n_plus_1(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="Fact 1", audit=_make_audit_context("op-002")
        )
        result = repo.append_entity_fact(
            "npc-gandalf", expected_revision=2, fact="Fact 2", audit=_make_audit_context("op-003")
        )
        assert result.entity.revision == 3

    def test_stale_expected_revision_raises_conflict(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ConflictError, match="Revision mismatch"):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=999,
                fact="Fact",
                audit=_make_audit_context("op-002"),
            )

    def test_stale_conflict_produces_zero_new_audit_records(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        records_before = len(audit_service.read_all())
        with pytest.raises(ConflictError):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=999,
                fact="Fact",
                audit=_make_audit_context("op-002"),
            )
        assert len(audit_service.read_all()) == records_before

    def test_bool_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=True,
                fact="Fact",
                audit=_make_audit_context("op-002"),
            )

    def test_string_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision="1",
                fact="Fact",
                audit=_make_audit_context("op-002"),
            )

    def test_zero_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.append_entity_fact(
                "npc-gandalf", expected_revision=0, fact="Fact", audit=_make_audit_context("op-002")
            )

    def test_negative_revision_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        with pytest.raises(ValidationError):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=-1,
                fact="Fact",
                audit=_make_audit_context("op-002"),
            )

    def test_repeated_append_with_new_revision(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        r1 = repo.append_entity_fact(
            "npc-gandalf", expected_revision=1, fact="First", audit=_make_audit_context("op-002")
        )
        assert r1.entity.revision == 2
        r2 = repo.append_entity_fact(
            "npc-gandalf", expected_revision=2, fact="Second", audit=_make_audit_context("op-003")
        )
        assert r2.entity.revision == 3
        with pytest.raises(ConflictError):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="Stale",
                audit=_make_audit_context("op-004"),
            )


# ═════════════════════════════════════════════════════════════════════════════
# Failure semantics
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactFailureSemantics:
    """Failure behaviour during append_entity_fact lifecycle."""

    def test_invalid_entity_id_raises_validation_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        with pytest.raises(ValidationError):
            repo.append_entity_fact(
                "", expected_revision=1, fact="Fact", audit=_make_audit_context("op-001")
            )

    def test_not_found_raises_not_found_error(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        with pytest.raises(NotFoundError):
            repo.append_entity_fact(
                "npc-nonexistent",
                expected_revision=1,
                fact="Fact",
                audit=_make_audit_context("op-001"),
            )

    def test_operation_id_reuse_rejected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        repo.create_entity(
            _make_document(entity_id="npc-frodo"), audit=_make_audit_context("op-002")
        )
        with pytest.raises(ConflictError, match="already been used"):
            repo.append_entity_fact(
                "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
            )

    def test_corrupt_audit_preflight_aborts_append(self, tmp_path: Path) -> None:
        vault_root, audit_service, audit_log = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        audit_log.write_text("not json\n", encoding="utf-8")
        with pytest.raises(StorageError, match="corruption"):
            repo.append_entity_fact(
                "npc-gandalf", expected_revision=1, fact="Fact", audit=_make_audit_context("op-002")
            )

    def test_intent_append_failure_aborts_append(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))

        def _broken_append(*args: object, **kwargs: object) -> None:
            raise StorageError("append failed")

        with mock.patch.object(audit_service, "append", _broken_append):
            with pytest.raises(StorageError):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="Fact",
                    audit=_make_audit_context("op-002"),
                )

    def test_entity_write_failure_leaves_intent(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        import os as os_mod

        with mock.patch.object(os_mod, "replace", side_effect=OSError(5, "Input/output error")):
            with pytest.raises(StorageError):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="Fact",
                    audit=_make_audit_context("op-002"),
                )
        records = audit_service.read_all()
        append_records = [r for r in records if r.operation == "append_entity_fact"]
        assert len(append_records) == 1
        assert append_records[0].phase == "intent"

    def test_committed_audit_failure_entity_still_has_fact(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        original_append = audit_service.append

        def _fail_on_append_committed(record: object) -> None:
            if (
                getattr(record, "phase", None) == "committed"
                and getattr(record, "operation", None) == "append_entity_fact"
            ):
                raise StorageError("committed append failed")
            original_append(record)

        with mock.patch.object(audit_service, "append", side_effect=_fail_on_append_committed):
            with pytest.raises(StorageError, match="audit finalization failed"):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="New fact",
                    audit=_make_audit_context("op-002"),
                )
        result = repo.get_entity("npc-gandalf")
        assert "New fact" in result.body
        assert result.entity.revision == 2

    def test_committed_audit_failure_preserves_cause(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(), audit=_make_audit_context("op-001"))
        original_append = audit_service.append
        original_storage_error = StorageError("committed append failed")

        def _fail_on_committed(record: object) -> None:
            if (
                getattr(record, "phase", None) == "committed"
                and getattr(record, "operation", None) == "append_entity_fact"
            ):
                raise original_storage_error
            original_append(record)

        with mock.patch.object(audit_service, "append", side_effect=_fail_on_committed):
            with pytest.raises(StorageError) as exc:
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="Fact",
                    audit=_make_audit_context("op-002"),
                )
        assert exc.value.__cause__ is original_storage_error


# ═════════════════════════════════════════════════════════════════════════════
# Concurrent / manual edit detection
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactConcurrentEdit:
    """Detection of concurrent or manual edits between intent and write."""

    def test_manual_edit_without_revision_change_detected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body="Original\n"), audit=_make_audit_context("op-001"))
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        entity_file = next(npc_dir.iterdir())
        original_append = audit_service.append

        def _intercept_and_edit(record: object) -> None:
            original_append(record)
            if (
                getattr(record, "phase", None) == "intent"
                and getattr(record, "operation", None) == "append_entity_fact"
            ):
                current = entity_file.read_text(encoding="utf-8")
                modified = current.replace("Original", "Original-Edited")
                entity_file.write_text(modified, encoding="utf-8")

        with mock.patch.object(audit_service, "append", side_effect=_intercept_and_edit):
            with pytest.raises(ConflictError, match="content changed"):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="Fact",
                    audit=_make_audit_context("op-002"),
                )
        assert "Original-Edited" in entity_file.read_text(encoding="utf-8")

    def test_manual_edit_with_revision_change_detected(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(_make_document(body="Original\n"), audit=_make_audit_context("op-001"))
        npc_dir = entity_directory(vault_root, EntityType.NPC)
        entity_file = next(npc_dir.iterdir())
        original_append = audit_service.append

        def _intercept_and_edit(record: object) -> None:
            original_append(record)
            if (
                getattr(record, "phase", None) == "intent"
                and getattr(record, "operation", None) == "append_entity_fact"
            ):
                current = entity_file.read_text(encoding="utf-8")
                modified = current.replace("revision: 1", "revision: 2")
                entity_file.write_text(modified, encoding="utf-8")

        with mock.patch.object(audit_service, "append", side_effect=_intercept_and_edit):
            with pytest.raises(ConflictError, match="revision changed"):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="Fact",
                    audit=_make_audit_context("op-002"),
                )
        assert "revision: 2" in entity_file.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# Cross-operation integration
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactIntegration:
    """Full integration cycle: create -> append -> patch -> append."""

    def test_create_append_patch_append(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)

        # create
        doc = _make_document(
            entity_id="npc-gandalf",
            name="Gandalf",
            body="## Notes\n",
        )
        repo.create_entity(doc, audit=_make_audit_context("op-001"))
        assert repo.get_entity("npc-gandalf").entity.revision == 1

        # append
        r1 = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=1,
            fact="First fact.",
            audit=_make_audit_context("op-002"),
        )
        assert r1.entity.revision == 2
        assert "First fact." in r1.body

        # patch
        from dnd_assistant.storage.patch import EntityPatch

        r2 = repo.patch_entity(
            "npc-gandalf",
            EntityPatch(name="Gandalf the White"),
            expected_revision=2,
            audit=_make_audit_context("op-003"),
        )
        assert r2.entity.revision == 3
        assert r2.entity.name == "Gandalf the White"

        # append again
        r3 = repo.append_entity_fact(
            "npc-gandalf",
            expected_revision=3,
            fact="Second fact.",
            audit=_make_audit_context("op-004"),
        )
        assert r3.entity.revision == 4
        assert "First fact." in r3.body
        assert "Second fact." in r3.body
        assert r3.entity.name == "Gandalf the White"

        # final get
        final = repo.get_entity("npc-gandalf")
        assert final.entity.revision == 4
        assert "First fact." in final.body
        assert "Second fact." in final.body


# ═════════════════════════════════════════════════════════════════════════════
# Protocol conformance
# ═════════════════════════════════════════════════════════════════════════════


class TestAppendFactProtocolConformance:
    """Runtime VaultRepository structural conformance."""

    def test_isinstance_vault_repository(self, tmp_path: Path) -> None:
        vault_root, audit_service, _ = _setup_vault(tmp_path)
        repo = ObsidianVaultRepository(vault_root, audit_service)
        assert isinstance(repo, VaultRepository)
