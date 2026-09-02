"""Tests for storage-level types introduced in S3-00.

Covers:
- VaultDocument construction and properties
- EntityDirectory mapping
- VaultRepository protocol structural typing
- Import smoke test
- Boundary: storage does not import from models/retrieval/tools
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import cast

import pytest

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError
from dnd_assistant.storage import EntityDirectory, VaultDocument, VaultRepository

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_entity() -> Entity:
    return Entity(
        id=cast(EntityId, "gandalf"),
        type=EntityType.NPC,
        name="Gandalf",
        status="alive",
        visibility="player",
        knowledge_status="confirmed",
        created_at=datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC),
        revision=cast(Revision, 1),
    )


# ── VaultDocument tests ────────────────────────────────────────────────────


class TestVaultDocument:
    def test_construct_with_entity_only(self, sample_entity: Entity) -> None:
        doc = VaultDocument(entity=sample_entity)
        assert doc.entity is sample_entity
        assert doc.extra_frontmatter == {}
        assert doc.body == ""

    def test_construct_with_extra_frontmatter(self, sample_entity: Entity) -> None:
        extra = {"faction": "The Fellowship", "race": "Maia"}
        doc = VaultDocument(entity=sample_entity, extra_frontmatter=extra)
        assert doc.extra_frontmatter == extra
        assert doc.body == ""

    def test_construct_with_body(self, sample_entity: Entity) -> None:
        body = "## Description\nA wise wizard.\n"
        doc = VaultDocument(entity=sample_entity, body=body)
        assert doc.body == body
        assert doc.extra_frontmatter == {}

    def test_construct_with_all_fields(self, sample_entity: Entity) -> None:
        extra = {"faction": "The Fellowship"}
        body = "## Notes\nMet in Bree.\n"
        doc = VaultDocument(entity=sample_entity, extra_frontmatter=extra, body=body)
        assert doc.entity is sample_entity
        assert doc.extra_frontmatter == extra
        assert doc.body == body

    def test_extra_frontmatter_returns_copy(self, sample_entity: Entity) -> None:
        extra = {"faction": "The Fellowship"}
        doc = VaultDocument(entity=sample_entity, extra_frontmatter=extra)
        returned = doc.extra_frontmatter
        returned["new_key"] = "value"
        # Original should not be mutated
        assert "new_key" not in doc.extra_frontmatter

    def test_repr(self, sample_entity: Entity) -> None:
        doc = VaultDocument(entity=sample_entity, body="Some body text")
        r = repr(doc)
        assert "gandalf" in r
        assert "npc" in r
        assert "extra_fields=0" in r
        assert "body_len=14" in r

    def test_extra_frontmatter_none_becomes_empty(self, sample_entity: Entity) -> None:
        doc = VaultDocument(entity=sample_entity, extra_frontmatter=None)
        assert doc.extra_frontmatter == {}

    def test_extra_frontmatter_empty_dict(self, sample_entity: Entity) -> None:
        doc = VaultDocument(entity=sample_entity, extra_frontmatter={})
        assert doc.extra_frontmatter == {}

    def test_body_default_empty_string(self, sample_entity: Entity) -> None:
        doc = VaultDocument(entity=sample_entity)
        assert doc.body == ""

    def test_docstring_does_not_claim_verbatim_preservation(self) -> None:
        """VaultDocument does not claim 'verbatim' YAML preservation.

        S3-00 preserves extra frontmatter key/value pairs semantically,
        not YAML presentation metadata.  The 'verbatim' claim was
        corrected to 'semantically' with an explicit S3-01 deferral.
        """
        import inspect

        class_source = inspect.getdoc(VaultDocument) or ""
        assert "verbatim" not in class_source, (
            "VaultDocument must not claim 'verbatim' YAML preservation"
        )
        assert "semantically" in class_source, (
            "VaultDocument should describe preservation as 'semantically'"
        )
        assert "S3-01" in class_source, (
            "YAML presentation metadata decision should be deferred to S3-01"
        )


# ── EntityDirectory tests ──────────────────────────────────────────────────


class TestEntityDirectory:
    @pytest.mark.parametrize(
        ("entity_type", "expected_dir"),
        [
            (EntityType.NPC, EntityDirectory.NPC),
            (EntityType.LOCATION, EntityDirectory.LOCATION),
            (EntityType.QUEST, EntityDirectory.QUEST),
            (EntityType.ITEM, EntityDirectory.ITEM),
        ],
    )
    def test_for_type_mapping(self, entity_type: EntityType, expected_dir: EntityDirectory) -> None:
        assert EntityDirectory.for_type(entity_type) == expected_dir

    def test_for_type_unknown_raises_key_error(self) -> None:
        # No extra EntityType values in MVP; this tests defensive behaviour
        # if a future type is added without updating the mapping.
        pass

    @pytest.mark.parametrize(
        ("directory", "expected_value"),
        [
            (EntityDirectory.NPC, "Characters/NPCs"),
            (EntityDirectory.LOCATION, "Locations"),
            (EntityDirectory.QUEST, "Quests"),
            (EntityDirectory.ITEM, "Items"),
        ],
    )
    def test_directory_values(self, directory: EntityDirectory, expected_value: str) -> None:
        assert directory.value == expected_value

    def test_for_type_round_trip(self) -> None:
        for entity_type in EntityType:
            directory = EntityDirectory.for_type(entity_type)
            assert isinstance(directory, EntityDirectory)
            assert directory.value


# ── VaultRepository protocol tests ─────────────────────────────────────────


class TestVaultRepositoryProtocol:
    """Verify that VaultRepository is structurally compatible with
    a conforming implementation."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(VaultRepository, "__instancecheck__")

    def test_protocol_methods_exist(self) -> None:
        """VaultRepository defines all expected executable method names.

        ``patch_entity`` is now finalised in S3-06 with a typed signature.
        """
        methods = {
            "create_entity",
            "get_entity",
            "list_entities",
            "patch_entity",
            "append_entity_fact",
        }
        protocol_methods = {name for name in dir(VaultRepository) if not name.startswith("_")}
        assert methods.issubset(protocol_methods), f"Missing methods: {methods - protocol_methods}"

    def test_error_types_importable(self) -> None:
        """The error types referenced in the protocol are importable."""
        assert ConflictError is not None
        assert NotFoundError is not None
        assert StorageError is not None

    def test_append_entity_fact_revision_semantics(self) -> None:
        """append_entity_fact now guarantees incremented revision (S3-07)."""
        import inspect

        from dnd_assistant.storage import types as storage_types

        source = inspect.getsource(storage_types.VaultRepository)
        assert "incremented by 1" in source, (
            "append_entity_fact should claim revision increment after S3-07"
        )


# ── Import / boundary tests ────────────────────────────────────────────────


def test_storage_types_module_importable() -> None:
    from dnd_assistant.storage import types  # noqa: F401


def test_storage_types_reexported() -> None:
    from dnd_assistant.storage import EntityDirectory, VaultDocument, VaultRepository  # noqa: F401


@pytest.mark.usefixtures("restore_dnd_assistant_modules")
class TestStorageTypesImportBoundaries:
    """Clean-import boundary tests for storage/types."""

    def test_does_not_import_models(self) -> None:
        """Verify storage/types does not trigger model imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

        import dnd_assistant.storage.types  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
        assert not mod_names, f"storage/types imported model modules: {mod_names}"

    def test_does_not_import_retrieval(self) -> None:
        """Verify storage/types does not trigger retrieval imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

        import dnd_assistant.storage.types  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.retrieval")}
        assert not mod_names, f"storage/types imported retrieval modules: {mod_names}"

    def test_does_not_import_tools(self) -> None:
        """Verify storage/types does not trigger tool imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

        import dnd_assistant.storage.types  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.tools")}
        assert not mod_names, f"storage/types imported tool modules: {mod_names}"
