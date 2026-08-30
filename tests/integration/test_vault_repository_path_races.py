"""S3-08 integration tests: dynamic path safety, create-race hardening,
and mutation-time reauthorization.

Covers:
- Audit directory replaced by symlink after construction
- Audit file replaced by symlink after construction
- Canonical entity directory replaced by symlink before mutation
- Nested parent redirect
- Target symlink redirect after intent
- Create race: target becomes occupied after intent (ConflictError)
- Create race: duplicate EntityId appears after intent (ConflictError)
- Patch/append: mutation-time environment revalidation
- Temp-file cleanup verification
- Stable-target identity (S3-08 final correction)
- Nested-parent redirect with same-type-dir symlink
- Target-file symlink redirect inside canonical directory
"""

from __future__ import annotations

import os
import os as _os_mod
from pathlib import Path
from unittest import mock

import pytest

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.patch import EntityPatch
from tests.integration.helpers import (
    can_symlink,
    count_temp_files,
    find_entity_file,
    make_audit_context,
    make_document,
)

# ═════════════════════════════════════════════════════════════════════════════
# 1. Audit directory replaced by symlink after construction
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditDirectorySymlinkAfterConstruction:
    """Repository must detect audit path becoming unsafe after construction."""

    def test_audit_dir_replaced_by_symlink_rejected(self, vault_root, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        audit_dir = vault_root / "_system" / "audit"
        outside_dir = vault_root.parent / "outside_audit"
        outside_dir.mkdir()
        outside_log = outside_dir / "audit.jsonl"
        outside_log.write_text("", encoding="utf-8")

        import shutil

        shutil.rmtree(audit_dir)
        os.symlink(str(outside_dir), str(audit_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.create_entity(
                make_document(entity_id="npc-gandalf"),
                audit=make_audit_context("op-001"),
            )

    def test_audit_file_replaced_by_symlink_rejected(
        self, vault_root, audit_service, audit_log_path
    ) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        audit_log_path.unlink(missing_ok=True)
        outside_file = vault_root.parent / "outside_audit.jsonl"
        outside_file.write_text("", encoding="utf-8")
        os.symlink(str(outside_file), str(audit_log_path))

        with pytest.raises(StorageError):
            repo.create_entity(
                make_document(entity_id="npc-gandalf"),
                audit=make_audit_context("op-001"),
            )

    def test_audit_dir_symlink_blocks_patch(self, vault_root, audit_service) -> None:
        """Patch also detects audit dir symlink via mutation-time validation."""
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            make_document(entity_id="npc-gandalf"),
            audit=make_audit_context("op-001"),
        )

        audit_dir = vault_root / "_system" / "audit"
        outside_dir = vault_root.parent / "outside_audit2"
        outside_dir.mkdir()

        import shutil

        shutil.rmtree(audit_dir)
        os.symlink(str(outside_dir), str(audit_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.patch_entity(
                "npc-gandalf",
                EntityPatch(name="Gandalf v2"),
                expected_revision=1,
                audit=make_audit_context("op-002"),
            )

    def test_audit_dir_symlink_blocks_append(self, vault_root, audit_service) -> None:
        """Append also detects audit dir symlink via mutation-time validation."""
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            make_document(entity_id="npc-gandalf"),
            audit=make_audit_context("op-001"),
        )

        audit_dir = vault_root / "_system" / "audit"
        outside_dir = vault_root.parent / "outside_audit3"
        outside_dir.mkdir()

        import shutil

        shutil.rmtree(audit_dir)
        os.symlink(str(outside_dir), str(audit_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.append_entity_fact(
                "npc-gandalf",
                expected_revision=1,
                fact="New fact",
                audit=make_audit_context("op-002"),
            )


# ═════════════════════════════════════════════════════════════════════════════
# 2. Canonical entity directory replaced by symlink before mutation
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityDirectorySymlinkAfterConstruction:
    """Repository must detect entity directory becoming unsafe."""

    def test_entity_dir_replaced_by_symlink(self, vault_root, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        npc_dir = vault_root / "Characters" / "NPCs"
        outside_dir = vault_root.parent / "outside_npcs"
        outside_dir.mkdir()
        outside_entity = outside_dir / "entity-test.md"
        outside_entity.write_text("---\nid: npc-outside\n---\n", encoding="utf-8")

        import shutil

        shutil.rmtree(npc_dir)
        os.symlink(str(outside_dir), str(npc_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.list_entities()

    def test_get_entity_rejects_symlinked_dir(self, vault_root, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)
        repo.create_entity(
            make_document(entity_id="npc-gandalf"),
            audit=make_audit_context("op-001"),
        )

        npc_dir = vault_root / "Characters" / "NPCs"
        outside_dir = vault_root.parent / "outside_npcs2"
        outside_dir.mkdir()

        import shutil

        shutil.rmtree(npc_dir)
        os.symlink(str(outside_dir), str(npc_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.get_entity("npc-gandalf")


# ═════════════════════════════════════════════════════════════════════════════
# 3. Nested parent redirect
# ═════════════════════════════════════════════════════════════════════════════


class TestNestedParentRedirect:
    """Nested entity directory parent replaced by symlink."""

    def test_nested_parent_symlink_rejected(self, vault_root, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        nested_dir = vault_root / "Characters" / "NPCs" / "Allies"
        nested_dir.mkdir(parents=True)

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = make_document(entity_id="npc-ally")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        outside_dir = vault_root.parent / "outside_allies"
        outside_dir.mkdir()

        import shutil

        shutil.rmtree(nested_dir)
        os.symlink(str(outside_dir), str(nested_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.patch_entity(
                "npc-ally",
                EntityPatch(name="Ally v2"),
                expected_revision=1,
                audit=make_audit_context("op-002"),
            )

    def test_nested_parent_symlink_blocks_append(self, vault_root, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        nested_dir = vault_root / "Characters" / "NPCs" / "Fellowship"
        nested_dir.mkdir(parents=True)

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        doc = make_document(entity_id="npc-frodo")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        outside_dir = vault_root.parent / "outside_fellowship"
        outside_dir.mkdir()

        import shutil

        shutil.rmtree(nested_dir)
        os.symlink(str(outside_dir), str(nested_dir), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.append_entity_fact(
                "npc-frodo",
                expected_revision=1,
                fact="Ring bearer",
                audit=make_audit_context("op-002"),
            )


# ═════════════════════════════════════════════════════════════════════════════
# 4. Target symlink redirect after intent
# ═════════════════════════════════════════════════════════════════════════════


class TestTargetSymlinkAfterIntent:
    """Target replaced by symlink after intent must be detected."""

    def test_target_becomes_symlink_after_intent(self, repo, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        from dnd_assistant.storage.vault_repository import (
            _read_exact_text as real_read,
        )

        call_count = [0]

        def _replace_with_symlink(path):
            call_count[0] += 1
            if call_count[0] == 2:
                other_file = entity_file.parent / "other.md"
                other_file.write_text("other content", encoding="utf-8")
                entity_file.unlink()
                os.symlink(str(other_file), str(entity_file))
            return real_read(path)

        with mock.patch(
            "dnd_assistant.storage.vault_repository._read_exact_text",
            side_effect=_replace_with_symlink,
        ):
            with pytest.raises((StorageError, ConflictError)):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

    def test_target_symlink_after_intent_append(self, repo, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        from dnd_assistant.storage.vault_repository import (
            _read_exact_text as real_read,
        )

        call_count = [0]

        def _replace_with_symlink(path):
            call_count[0] += 1
            if call_count[0] == 2:
                other_file = entity_file.parent / "other_append.md"
                other_file.write_text("other content", encoding="utf-8")
                entity_file.unlink()
                os.symlink(str(other_file), str(entity_file))
            return real_read(path)

        with mock.patch(
            "dnd_assistant.storage.vault_repository._read_exact_text",
            side_effect=_replace_with_symlink,
        ):
            with pytest.raises((StorageError, ConflictError)):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="New fact",
                    audit=make_audit_context("op-002"),
                )


# ═════════════════════════════════════════════════════════════════════════════
# 5. Create race: target becomes occupied after intent
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateRaceOccupiedTarget:
    """Generated target becomes occupied after intent.

    The second pre-write check must detect that the target path became
    a regular file after the intent was durably appended.
    """

    def test_target_occupied_after_intent_rejected(self, repo, audit_service, vault_root) -> None:
        """Create detects target occupied after intent via second pre-write check.

        Strategy: wrap AuditService.append to intercept the intent phase,
        then create a regular file at the generated target path.
        """
        doc = make_document(entity_id="npc-race-occupy")

        # Track the generated target path
        target_paths: list = []
        original_gen_path = repo._generate_unique_path

        def _wrapped_gen_path(target_dir):
            path = original_gen_path(target_dir)
            target_paths.append(path)
            return path

        # Wrap audit_service.append to create file after intent
        real_append = audit_service.append
        after_intent = [False]

        def _append_and_occupy(record):
            real_append(record)
            if record.phase == "intent" and not after_intent[0]:
                after_intent[0] = True
                if target_paths:
                    target_paths[-1].write_text("---\nid: intruder\n---\n", encoding="utf-8")

        with (
            mock.patch.object(repo, "_generate_unique_path", side_effect=_wrapped_gen_path),
            mock.patch.object(audit_service, "append", side_effect=_append_and_occupy),
        ):
            with pytest.raises(ConflictError):
                repo.create_entity(doc, audit=make_audit_context("op-race-occupy"))

        # Verify: unrelated file is untouched
        npc_dir = vault_root / "Characters" / "NPCs"
        intruder_file = None
        for p in npc_dir.iterdir():
            if p.name.startswith("entity-") and p.suffix == ".md":
                text = p.read_text(encoding="utf-8")
                if "id: intruder" in text:
                    intruder_file = p
                    break
        assert intruder_file is not None, "Intruder entity should exist on disk"
        assert intruder_file.read_text(encoding="utf-8") == ("---\nid: intruder\n---\n"), (
            "Intruder file must be unchanged"
        )

        # Verify: intent exists, committed absent
        records = audit_service.read_all()
        intents = [r for r in records if r.phase == "intent"]
        assert len(intents) == 1
        assert intents[0].entity_id == "npc-race-occupy"
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 0

        # Verify: no entity with the losing ID exists
        from dnd_assistant.storage.markdown import parse

        for p in npc_dir.iterdir():
            if p.suffix == ".md" and p != intruder_file:
                text = p.read_text(encoding="utf-8")
                parsed = parse(text)
                assert parsed.entity.id != "npc-race-occupy", (
                    f"Losing entity should not exist, found at {p}"
                )

    def test_target_becomes_symlink_after_intent_rejected(
        self, repo, audit_service, vault_root
    ) -> None:
        """Create detects target became a symlink after intent."""
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        doc = make_document(entity_id="npc-race-symlink")

        target_paths: list = []
        original_gen_path = repo._generate_unique_path

        def _wrapped_gen_path(target_dir):
            path = original_gen_path(target_dir)
            target_paths.append(path)
            return path

        real_append = audit_service.append
        after_intent = [False]

        def _append_and_symlink(record):
            real_append(record)
            if record.phase == "intent" and not after_intent[0]:
                after_intent[0] = True
                if target_paths:
                    # Create a real file, then replace with symlink
                    real_file = target_paths[-1].parent / "real_target.md"
                    real_file.write_text("real content", encoding="utf-8")
                    os.symlink(str(real_file), str(target_paths[-1]))

        with (
            mock.patch.object(repo, "_generate_unique_path", side_effect=_wrapped_gen_path),
            mock.patch.object(audit_service, "append", side_effect=_append_and_symlink),
        ):
            with pytest.raises(ConflictError):
                repo.create_entity(doc, audit=make_audit_context("op-race-symlink"))

        # Verify: intent exists, committed absent
        records = audit_service.read_all()
        intents = [r for r in records if r.phase == "intent" and r.entity_id == "npc-race-symlink"]
        assert len(intents) == 1
        committed = [
            r for r in records if r.phase == "committed" and r.entity_id == "npc-race-symlink"
        ]
        assert len(committed) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 6. Create race: duplicate EntityId after intent
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateRaceDuplicateEntityId:
    """Duplicate EntityId appears after intent.

    The second pre-write check must detect that another entity with the
    same EntityId appeared after the intent was durably appended.
    """

    def test_duplicate_id_appears_after_intent(self, repo, audit_service, vault_root) -> None:
        """Create detects duplicate EntityId via fresh snapshot after intent."""
        doc = make_document(entity_id="npc-dup-race")

        real_append = audit_service.append
        after_intent = [False]

        def _append_and_create_duplicate(record):
            real_append(record)
            if record.phase == "intent" and not after_intent[0]:
                after_intent[0] = True
                # Create another entity with the SAME EntityId under a different filename
                from dnd_assistant.storage.markdown import serialize

                npc_dir = vault_root / "Characters" / "NPCs"
                dup_file = npc_dir / "entity-dup-other.md"
                dup_doc = make_document(entity_id="npc-dup-race", name="Duplicate")
                dup_text = serialize(dup_doc)
                dup_file.write_text(dup_text, encoding="utf-8")

        with mock.patch.object(audit_service, "append", side_effect=_append_and_create_duplicate):
            with pytest.raises(ConflictError):
                repo.create_entity(doc, audit=make_audit_context("op-dup-race"))

        # Verify: external entity remains untouched
        npc_dir = vault_root / "Characters" / "NPCs"
        dup_file = npc_dir / "entity-dup-other.md"
        assert dup_file.exists(), "External entity must still exist"
        assert "id: npc-dup-race" in dup_file.read_text(encoding="utf-8")

        # Verify: planned create target does NOT exist (no second file with same ID)
        from dnd_assistant.storage.markdown import parse

        count = 0
        for p in npc_dir.iterdir():
            if p.suffix == ".md":
                text = p.read_text(encoding="utf-8")
                parsed = parse(text)
                if parsed.entity.id == "npc-dup-race":
                    count += 1
        assert count == 1, f"Expected exactly 1 entity with ID npc-dup-race, found {count}"

        # Verify: intent exists, committed absent
        records = audit_service.read_all()
        intents = [r for r in records if r.phase == "intent" and r.entity_id == "npc-dup-race"]
        assert len(intents) == 1
        committed = [r for r in records if r.phase == "committed" and r.entity_id == "npc-dup-race"]
        assert len(committed) == 0

    def test_duplicate_id_detected_at_create_time(self, repo) -> None:
        """Normal duplicate detection still works."""
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        with pytest.raises(ConflictError, match="already exists"):
            repo.create_entity(
                make_document(entity_id="npc-gandalf"),
                audit=make_audit_context("op-002"),
            )


# ═════════════════════════════════════════════════════════════════════════════
# 7. Temp-file cleanup verification
# ═════════════════════════════════════════════════════════════════════════════


class TestTempFileCleanup:
    """Verify no temp files remain after failures."""

    def test_no_temp_files_after_create_failure(self, repo, vault_root) -> None:
        doc = make_document(entity_id="npc-gandalf")

        with mock.patch.object(
            _os_mod,
            "replace",
            side_effect=StorageError("Simulated failure"),
        ):
            with pytest.raises(StorageError):
                repo.create_entity(doc, audit=make_audit_context("op-001"))

        assert count_temp_files(vault_root) == 0

    def test_no_temp_files_after_patch_failure(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        with mock.patch.object(
            _os_mod,
            "replace",
            side_effect=StorageError("Simulated failure"),
        ):
            with pytest.raises(StorageError):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        assert count_temp_files(entity_file.parent) == 0

    def test_no_temp_files_after_append_failure(self, repo) -> None:
        doc = make_document(entity_id="npc-gandalf")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")

        with mock.patch.object(
            _os_mod,
            "replace",
            side_effect=StorageError("Simulated failure"),
        ):
            with pytest.raises(StorageError):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="New fact",
                    audit=make_audit_context("op-002"),
                )

        assert count_temp_files(entity_file.parent) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 8. Stable-target identity (S3-08 final correction)
# ═════════════════════════════════════════════════════════════════════════════


class TestStableTargetIdentity:
    """Reauthorization must enforce equality, not just containment.

    These tests verify that ``_reauthorize_entity_path`` rejects a resolved
    path that differs from the originally selected path, even when both
    files are valid normal files under the same canonical entity directory.
    """

    def test_different_file_under_same_directory_rejected(self, vault_root) -> None:
        """Two valid normal files under the same entity directory.

        ``relative_path`` is ``Allies/entity.md`` but ``expected_path``
        points to ``Other/entity.md``.  The resolved current path
        (``Allies/entity.md``) differs from ``expected_path``, so
        ``StorageError`` must be raised.
        """
        from dnd_assistant.domain.types import EntityType
        from dnd_assistant.storage.vault_repository import (
            _reauthorize_entity_path,
        )

        npc_dir = vault_root / "Characters" / "NPCs"
        allies = npc_dir / "Allies"
        allies.mkdir()
        other = npc_dir / "Other"
        other.mkdir()

        allies_file = allies / "entity.md"
        allies_file.write_text("---\nid: npc-ally\n---\n", encoding="utf-8")
        other_file = other / "entity.md"
        other_file.write_text("---\nid: npc-other\n---\n", encoding="utf-8")

        relative_path = Path("Allies/entity.md")
        # expected_path is a *different* file from what relative_path resolves to
        expected_path = other_file.resolve(strict=False)

        from dnd_assistant.errors import StorageError as _StorageError

        with pytest.raises(_StorageError):
            _reauthorize_entity_path(
                vault_root=vault_root,
                directory_type=EntityType.NPC,
                relative_path=relative_path,
                expected_path=expected_path,
            )

    def test_same_file_under_same_directory_accepted(self, vault_root) -> None:
        """Same file resolves to itself — must succeed."""
        from dnd_assistant.domain.types import EntityType
        from dnd_assistant.storage.vault_repository import (
            _reauthorize_entity_path,
        )

        npc_dir = vault_root / "Characters" / "NPCs"
        allies = npc_dir / "Allies"
        allies.mkdir()

        entity_file = allies / "entity.md"
        entity_file.write_text("---\nid: npc-ally\n---\n", encoding="utf-8")

        relative_path = Path("Allies/entity.md")
        expected_path = entity_file.resolve(strict=False)

        result = _reauthorize_entity_path(
            vault_root=vault_root,
            directory_type=EntityType.NPC,
            relative_path=relative_path,
            expected_path=expected_path,
        )

        assert result == expected_path

    def test_nested_entity_relative_path_preserved(self, vault_root) -> None:
        """Nested entity path like ``Allies/Subgroup/entity.md`` must be
        preserved exactly and still work for reauthorization."""
        from dnd_assistant.domain.types import EntityType
        from dnd_assistant.storage.vault_repository import (
            _reauthorize_entity_path,
        )

        npc_dir = vault_root / "Characters" / "NPCs"
        allies = npc_dir / "Allies" / "Subgroup"
        allies.mkdir(parents=True)

        entity_file = allies / "entity.md"
        entity_file.write_text("---\nid: npc-deep\n---\n", encoding="utf-8")

        relative_path = Path("Allies/Subgroup/entity.md")
        expected_path = entity_file.resolve(strict=False)

        result = _reauthorize_entity_path(
            vault_root=vault_root,
            directory_type=EntityType.NPC,
            relative_path=relative_path,
            expected_path=expected_path,
        )

        assert result == expected_path


# ═════════════════════════════════════════════════════════════════════════════
# 9. Nested-parent redirect (symlink-capable)
# ═════════════════════════════════════════════════════════════════════════════


class TestNestedParentRedirectStableTarget:
    """Nested entity directory parent replaced by symlink to another
    directory inside the same canonical entity type directory.

    This proves that containment alone is not sufficient — the
    reauthorization must also enforce physical storage-target identity.
    """

    def test_nested_parent_redirect_to_same_type_dir_rejected(
        self, vault_root, audit_service
    ) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        allies = vault_root / "Characters" / "NPCs" / "Allies"
        allies.mkdir(parents=True)

        doc = make_document(entity_id="npc-ally")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-ally")
        original_text = entity_file.read_text(encoding="utf-8")

        other = vault_root / "Characters" / "NPCs" / "Other"
        other.mkdir(parents=True)
        other_file = other / entity_file.name
        other_file.write_text(original_text, encoding="utf-8")

        import shutil

        shutil.rmtree(allies)
        os.symlink(str(other), str(allies), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.patch_entity(
                "npc-ally",
                EntityPatch(name="Ally v2"),
                expected_revision=1,
                audit=make_audit_context("op-002"),
            )

        assert other_file.read_text(encoding="utf-8") == original_text

        records = audit_service.read_all()
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 0

        intents = [r for r in records if r.phase == "intent"]
        assert len(intents) == 1

    def test_nested_parent_redirect_blocks_append(self, vault_root, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        from dnd_assistant.storage.vault_repository import (
            ObsidianVaultRepository,
        )

        repo = ObsidianVaultRepository(vault_root, audit_service)

        allies = vault_root / "Characters" / "NPCs" / "Allies"
        allies.mkdir(parents=True)

        doc = make_document(entity_id="npc-ally", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-ally")
        original_text = entity_file.read_text(encoding="utf-8")

        other = vault_root / "Characters" / "NPCs" / "Other"
        other.mkdir(parents=True)
        other_file = other / entity_file.name
        other_file.write_text(original_text, encoding="utf-8")

        import shutil

        shutil.rmtree(allies)
        os.symlink(str(other), str(allies), target_is_directory=True)

        with pytest.raises(StorageError):
            repo.append_entity_fact(
                "npc-ally",
                expected_revision=1,
                fact="New fact",
                audit=make_audit_context("op-002"),
            )

        assert other_file.read_text(encoding="utf-8") == original_text

        records = audit_service.read_all()
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 10. Target-file symlink redirect inside canonical directory
# ═════════════════════════════════════════════════════════════════════════════


class TestTargetFileSymlinkRedirect:
    """Target file replaced after intent by a symlink to another file
    inside the same canonical type directory.

    This proves that outside-Vault containment alone would not prove
    stable target identity — the symlink points to a file that is
    *inside* the canonical entity directory.
    """

    def test_target_file_symlink_redirect_after_intent(self, repo, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_text = entity_file.read_text(encoding="utf-8")

        redirect_target = entity_file.parent / "redirect_target.md"
        redirect_target.write_text(original_text, encoding="utf-8")

        from dnd_assistant.storage.vault_repository import (
            _read_exact_text as real_read,
        )

        call_count = [0]

        def _replace_with_internal_symlink(path):
            call_count[0] += 1
            if call_count[0] == 2:
                entity_file.unlink()
                os.symlink(str(redirect_target), str(entity_file))
            return real_read(path)

        with mock.patch(
            "dnd_assistant.storage.vault_repository._read_exact_text",
            side_effect=_replace_with_internal_symlink,
        ):
            with pytest.raises((StorageError, ConflictError)):
                repo.patch_entity(
                    "npc-gandalf",
                    EntityPatch(name="Gandalf v2"),
                    expected_revision=1,
                    audit=make_audit_context("op-002"),
                )

        assert redirect_target.read_text(encoding="utf-8") == original_text

        records = audit_service.read_all()
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 0

    def test_target_file_symlink_redirect_after_intent_append(self, repo, audit_service) -> None:
        if not can_symlink():
            pytest.skip("Symlinks not supported on this platform")

        doc = make_document(entity_id="npc-gandalf", body="Body\n")
        repo.create_entity(doc, audit=make_audit_context("op-001"))

        entity_file = find_entity_file(repo, "npc-gandalf")
        original_text = entity_file.read_text(encoding="utf-8")

        redirect_target = entity_file.parent / "redirect_target_append.md"
        redirect_target.write_text(original_text, encoding="utf-8")

        from dnd_assistant.storage.vault_repository import (
            _read_exact_text as real_read,
        )

        call_count = [0]

        def _replace_with_internal_symlink(path):
            call_count[0] += 1
            if call_count[0] == 2:
                entity_file.unlink()
                os.symlink(str(redirect_target), str(entity_file))
            return real_read(path)

        with mock.patch(
            "dnd_assistant.storage.vault_repository._read_exact_text",
            side_effect=_replace_with_internal_symlink,
        ):
            with pytest.raises((StorageError, ConflictError)):
                repo.append_entity_fact(
                    "npc-gandalf",
                    expected_revision=1,
                    fact="New fact",
                    audit=make_audit_context("op-002"),
                )

        assert redirect_target.read_text(encoding="utf-8") == original_text

        records = audit_service.read_all()
        committed = [r for r in records if r.phase == "committed"]
        assert len(committed) == 0
