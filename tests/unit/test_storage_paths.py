"""Tests for Vault path safety and entity-file discovery (S3-02).

Covers:
- Canonical entity directory resolution
- Vault root validation (exists, is directory)
- Safe relative path acceptance
- Path traversal rejection (.., absolute paths, wrong directory)
- Recursive Markdown discovery
- Entity-type-scoped and all-types discovery
- Deterministic ordering
- Symlink safety (where OS supports it)
- Filesystem error translation
- DiscoveredEntityFile value semantics
- Import/boundary checks
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.paths import (
    DiscoveredEntityFile,
    _has_traversal,
    _resolve_vault_root,
    discover_entity_files,
    entity_directory,
    resolve_entity_path,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_vault(tmp_path: Path, subdirs: list[str] | None = None) -> Path:
    """Create a minimal Vault directory structure for testing."""
    vault = tmp_path / "vault"
    vault.mkdir()
    if subdirs:
        for sub in subdirs:
            (vault / sub).mkdir(parents=True, exist_ok=True)
    return vault


def _create_file(vault: Path, rel_path: str, content: str = "") -> Path:
    """Create a file inside the vault at the given relative path."""
    full = vault / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


# ── DiscoveredEntityFile tests ──────────────────────────────────────────────


class TestDiscoveredEntityFile:
    def test_construct(self) -> None:
        path = Path("/vault/Characters/NPCs/gandalf.md")
        d = DiscoveredEntityFile(entity_type=EntityType.NPC, path=path)
        assert d.entity_type == EntityType.NPC
        assert d.path == path

    def test_equality(self) -> None:
        p = Path("/vault/Characters/NPCs/gandalf.md")
        a = DiscoveredEntityFile(EntityType.NPC, p)
        b = DiscoveredEntityFile(EntityType.NPC, p)
        assert a == b
        assert not (a != b)

    def test_inequality_type(self) -> None:
        p = Path("/vault/Characters/NPCs/gandalf.md")
        a = DiscoveredEntityFile(EntityType.NPC, p)
        b = DiscoveredEntityFile(EntityType.LOCATION, p)
        assert a != b

    def test_inequality_path(self) -> None:
        a = DiscoveredEntityFile(EntityType.NPC, Path("/a.md"))
        b = DiscoveredEntityFile(EntityType.NPC, Path("/b.md"))
        assert a != b

    def test_hashable(self) -> None:
        p = Path("/vault/Characters/NPCs/gandalf.md")
        d = DiscoveredEntityFile(EntityType.NPC, p)
        s = {d}
        assert d in s

    def test_repr(self) -> None:
        d = DiscoveredEntityFile(EntityType.NPC, Path("/vault/g.md"))
        r = repr(d)
        assert "npc" in r
        assert "g.md" in r

    def test_not_equal_to_non_discovered(self) -> None:
        d = DiscoveredEntityFile(EntityType.NPC, Path("/x.md"))
        assert d != "not-a-discovered-file"
        assert d != 42


# ── _has_traversal tests ────────────────────────────────────────────────────


class TestHasTraversal:
    def test_simple_path_no_traversal(self) -> None:
        assert not _has_traversal(Path("Gandalf.md"))

    def test_nested_no_traversal(self) -> None:
        assert not _has_traversal(Path("Sword Coast/Neverwinter.md"))

    def test_dot_dot_rejected(self) -> None:
        assert _has_traversal(Path("../outside.md"))

    def test_nested_dot_dot_rejected(self) -> None:
        assert _has_traversal(Path("sub/../../outside.md"))

    def test_absolute_path_rejected(self) -> None:
        # On Windows, /absolute is not truly absolute (no drive letter),
        # but on POSIX it is.  Use a drive-letter absolute on Windows.
        p = Path("C:\\") / "absolute" / "path.md" if os.name == "nt" else Path("/absolute/path.md")
        assert _has_traversal(p)

    def test_unicode_no_traversal(self) -> None:
        assert not _has_traversal(Path("Земли/Эребор.md"))

    def test_spaces_no_traversal(self) -> None:
        assert not _has_traversal(Path("Sword Coast/Neverwinter.md"))


# ── _resolve_vault_root tests ───────────────────────────────────────────────


class TestResolveVaultRoot:
    def test_existing_directory_accepted(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        resolved = _resolve_vault_root(vault)
        assert resolved.is_absolute()
        assert resolved.exists()
        assert resolved.is_dir()

    def test_missing_root_rejected(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(StorageError, match="does not exist"):
            _resolve_vault_root(missing)

    def test_file_root_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "afile.txt"
        f.write_text("hello", encoding="utf-8")
        with pytest.raises(StorageError, match="must be a directory"):
            _resolve_vault_root(f)

    def test_string_path_accepted(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        resolved = _resolve_vault_root(str(vault))
        assert resolved.is_absolute()

    def test_resolved_path_is_canonical(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        resolved = _resolve_vault_root(vault)
        assert resolved.is_absolute()
        assert resolved.exists()


# ── entity_directory tests ──────────────────────────────────────────────────


class TestEntityDirectoryFn:
    @pytest.mark.parametrize(
        ("entity_type", "expected_rel"),
        [
            (EntityType.NPC, "Characters/NPCs"),
            (EntityType.LOCATION, "Locations"),
            (EntityType.QUEST, "Quests"),
            (EntityType.ITEM, "Items"),
        ],
    )
    def test_returns_canonical_directory(
        self, tmp_path: Path, entity_type: EntityType, expected_rel: str
    ) -> None:
        vault = _create_vault(tmp_path)
        result = entity_directory(vault, entity_type)
        assert result == (vault.resolve() / expected_rel).resolve()

    def test_rooted_under_vault(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        result = entity_directory(vault, EntityType.NPC)
        result.relative_to(vault.resolve())

    def test_invalid_vault_root_rejected(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(StorageError):
            entity_directory(missing, EntityType.NPC)


# ── resolve_entity_path tests ───────────────────────────────────────────────


class TestResolveEntityPath:
    def test_simple_relative_path(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        result = resolve_entity_path(vault, EntityType.NPC, "Gandalf.md")
        assert result.name == "Gandalf.md"
        assert result.suffix == ".md"
        result.relative_to(vault / "Characters/NPCs")

    def test_nested_relative_path(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Locations"])
        result = resolve_entity_path(vault, EntityType.LOCATION, "Sword Coast/Neverwinter.md")
        assert result.name == "Neverwinter.md"
        result.relative_to(vault / "Locations")

    def test_unicode_filename(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        result = resolve_entity_path(vault, EntityType.NPC, "Гэндальф.md")
        assert result.name == "Гэндальф.md"

    def test_spaces_in_path(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        result = resolve_entity_path(vault, EntityType.NPC, "Gandalf the Grey.md")
        assert result.name == "Gandalf the Grey.md"

    def test_traversal_dot_dot_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        with pytest.raises(StorageError, match="traversal"):
            resolve_entity_path(vault, EntityType.NPC, "../outside.md")

    def test_traversal_nested_dot_dot_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        with pytest.raises(StorageError, match="traversal"):
            resolve_entity_path(vault, EntityType.NPC, "sub/../../outside.md")

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        with pytest.raises(StorageError, match="traversal|outside|absolute"):
            resolve_entity_path(vault, EntityType.NPC, "/etc/passwd.md")

    def test_wrong_entity_directory_escape(self, tmp_path: Path) -> None:
        """NPC path must not resolve into Quests directory."""
        vault = _create_vault(tmp_path, ["Characters/NPCs", "Quests"])
        with pytest.raises(StorageError, match="traversal|outside"):
            resolve_entity_path(vault, EntityType.NPC, "../Quests/foo.md")

    def test_non_markdown_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        with pytest.raises(StorageError, match="Markdown"):
            resolve_entity_path(vault, EntityType.NPC, "gandalf.txt")

    def test_missing_vault_root_rejected(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(StorageError):
            resolve_entity_path(missing, EntityType.NPC, "foo.md")

    def test_uppercase_md_accepted(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        result = resolve_entity_path(vault, EntityType.NPC, "Gandalf.MD")
        assert result.suffix.casefold() == ".md"


# ── discover_entity_files tests ─────────────────────────────────────────────


class TestDiscoverEntityFiles:
    def test_finds_markdown_files(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        _create_file(vault, "Characters/NPCs/gandalf.md")
        _create_file(vault, "Characters/NPCs/frodo.md")
        results = discover_entity_files(vault, EntityType.NPC)
        assert len(results) == 2
        assert all(r.entity_type == EntityType.NPC for r in results)

    def test_ignores_non_markdown(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        _create_file(vault, "Characters/NPCs/gandalf.md")
        _create_file(vault, "Characters/NPCs/notes.txt")
        _create_file(vault, "Characters/NPCs/data.json")
        results = discover_entity_files(vault, EntityType.NPC)
        assert len(results) == 1
        assert results[0].path.name == "gandalf.md"

    def test_scans_nested_subdirectories(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Locations"])
        _create_file(vault, "Locations/Sword Coast/Neverwinter.md")
        _create_file(vault, "Locations/Sword Coast/Waterdeep.md")
        _create_file(vault, "Locations/Barovia.md")
        results = discover_entity_files(vault, EntityType.LOCATION)
        assert len(results) == 3

    def test_scans_only_requested_type(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs", "Locations"])
        _create_file(vault, "Characters/NPCs/gandalf.md")
        _create_file(vault, "Characters/NPCs/frodo.md")
        _create_file(vault, "Locations/Neverwinter.md")
        results = discover_entity_files(vault, EntityType.NPC)
        assert len(results) == 2
        assert all(r.entity_type == EntityType.NPC for r in results)

    def test_all_types_discovery(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs", "Locations", "Quests", "Items"])
        _create_file(vault, "Characters/NPCs/gandalf.md")
        _create_file(vault, "Locations/Neverwinter.md")
        _create_file(vault, "Quests/ring.md")
        _create_file(vault, "Items/one_ring.md")
        results = discover_entity_files(vault)
        assert len(results) == 4
        types_found = {r.entity_type for r in results}
        assert types_found == {
            EntityType.NPC,
            EntityType.LOCATION,
            EntityType.QUEST,
            EntityType.ITEM,
        }

    def test_ignores_unrelated_vault_directories(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs", "Campaign", "Sessions", "Lore"])
        _create_file(vault, "Characters/NPCs/gandalf.md")
        _create_file(vault, "Campaign/notes.md")
        _create_file(vault, "Sessions/session_1.md")
        _create_file(vault, "Lore/history.md")
        results = discover_entity_files(vault)
        assert len(results) == 1
        assert results[0].entity_type == EntityType.NPC

    def test_missing_entity_directory_yields_no_candidates(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)  # no subdirectories at all
        results = discover_entity_files(vault, EntityType.NPC)
        assert results == []

    def test_missing_all_directories_yields_empty(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        results = discover_entity_files(vault)
        assert results == []

    def test_entity_directory_as_file_raises_error(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        (vault / "Characters").mkdir()
        _create_file(vault, "Characters/NPCs")  # file, not a dir
        with pytest.raises(StorageError, match="not a directory"):
            discover_entity_files(vault, EntityType.NPC)

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        # Create files in reverse alphabetical order
        _create_file(vault, "Characters/NPCs/zaphod.md")
        _create_file(vault, "Characters/NPCs/arthur.md")
        _create_file(vault, "Characters/NPCs/trillian.md")
        _create_file(vault, "Characters/NPCs/ford.md")
        results = discover_entity_files(vault, EntityType.NPC)
        names = [r.path.name for r in results]
        assert names == sorted(names, key=str.casefold), f"Expected sorted order, got: {names}"

    def test_deterministic_ordering_across_types(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path, ["Characters/NPCs", "Locations", "Quests", "Items"])
        _create_file(vault, "Items/ring.md")
        _create_file(vault, "Characters/NPCs/gandalf.md")
        _create_file(vault, "Locations/barovia.md")
        _create_file(vault, "Quests/adventure.md")
        r1 = discover_entity_files(vault)
        r2 = discover_entity_files(vault)
        assert [c.path for c in r1] == [c.path for c in r2]

    def test_filename_not_entity_id(self, tmp_path: Path) -> None:
        """Discovery returns candidates; EntityId is NOT inferred from filename."""
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        _create_file(vault, "Characters/NPCs/any-name.md")
        results = discover_entity_files(vault, EntityType.NPC)
        assert len(results) == 1
        # DiscoveredEntityFile has no entity_id attribute
        assert not hasattr(results[0], "entity_id")

    def test_deterministic_ordering_tie_breaker(self, tmp_path: Path) -> None:
        """Verify sort-key tuple structure for deterministic tie-breaking.

        The sort key must be (casefolded_path, exact_path) so that
        case-distinct paths on case-sensitive filesystems have a
        deterministic secondary key.

        On case-insensitive filesystems (Windows) we cannot create
        case-distinct files, so we verify the sort-key contract by
        inspecting the sort lambda in the source.
        """
        import inspect

        from dnd_assistant.storage.paths import discover_entity_files as _def

        source = inspect.getsource(_def)
        # The sort key must reference both casefold and exact path
        assert "casefold()" in source
        # The sort key must be a tuple (not a single value)
        # Look for the pattern: key=lambda c: (..., ...)
        assert "lambda c: (" in source


# ── Symlink safety tests ────────────────────────────────────────────────────


def _can_symlink() -> bool:
    """Check whether the test environment can actually create symlinks."""
    if not hasattr(os, "symlink"):
        return False
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "target"
            target.write_text("x", encoding="utf-8")
            link = Path(d) / "link"
            os.symlink(str(target), str(link))
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _can_symlink(),
    reason="OS/environment does not support symlinks",
)
class TestSymlinkSafety:
    def test_directory_symlink_not_traversed(self, tmp_path: Path) -> None:
        """Symlinked directory outside Vault must not be traversed."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret", encoding="utf-8")

        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        link_dir = vault / "Characters/NPCs" / "external"
        os.symlink(str(outside), str(link_dir), target_is_directory=True)

        results = discover_entity_files(vault, EntityType.NPC)
        # The symlinked directory should not be traversed
        names = [r.path.name for r in results]
        assert "secret.md" not in names

    def test_file_symlink_not_returned(self, tmp_path: Path) -> None:
        """Symlinked file outside Vault must not be returned."""
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "evil.md"
        outside_file.write_text("evil", encoding="utf-8")

        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        link_file = vault / "Characters/NPCs" / "evil.md"
        os.symlink(str(outside_file), str(link_file))

        results = discover_entity_files(vault, EntityType.NPC)
        names = [r.path.name for r in results]
        assert "evil.md" not in names

    def test_symlink_does_not_escape_entity_directory(self, tmp_path: Path) -> None:
        """Symlink must not allow discovery into another entity dir."""
        vault = _create_vault(tmp_path, ["Characters/NPCs", "Quests"])
        _create_file(vault, "Quests/secret_quest.md")
        link_dir = vault / "Characters/NPCs" / "to_quests"
        os.symlink(str(vault / "Quests"), str(link_dir), target_is_directory=True)

        results = discover_entity_files(vault, EntityType.NPC)
        names = [r.path.name for r in results]
        assert "secret_quest.md" not in names


@pytest.mark.skipif(
    not _can_symlink(),
    reason="OS/environment does not support symlinks",
)
class TestCanonicalDirectorySymlinkRejection:
    """Canonical entity-directory symlink must be rejected (S3-02 correction)."""

    def test_entity_directory_rejects_direct_symlink_to_outside(self, tmp_path: Path) -> None:
        """Locations symlinked to outside -> entity_directory raises StorageError."""
        vault = _create_vault(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(str(outside), str(vault / "Locations"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            entity_directory(vault, EntityType.LOCATION)

    def test_discovery_rejects_direct_symlink_to_outside(self, tmp_path: Path) -> None:
        """Locations symlinked to outside -> discovery rejects."""
        vault = _create_vault(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "evil.md").write_text("evil", encoding="utf-8")
        os.symlink(str(outside), str(vault / "Locations"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            discover_entity_files(vault, EntityType.LOCATION)

    def test_entity_directory_rejects_symlink_to_another_entity_dir(self, tmp_path: Path) -> None:
        """Locations symlinked to Quests -> entity_directory raises StorageError."""
        vault = _create_vault(tmp_path, ["Quests"])
        os.symlink(str(vault / "Quests"), str(vault / "Locations"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            entity_directory(vault, EntityType.LOCATION)

    def test_discovery_rejects_symlink_to_another_entity_dir(self, tmp_path: Path) -> None:
        """Locations symlinked to Quests -> discovery rejects."""
        vault = _create_vault(tmp_path, ["Quests"])
        _create_file(vault, "Quests/quest.md")
        os.symlink(str(vault / "Quests"), str(vault / "Locations"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            discover_entity_files(vault, EntityType.LOCATION)

    def test_parent_symlink_rejected_for_npc(self, tmp_path: Path) -> None:
        """Characters symlinked to outside -> NPC entity_directory raises StorageError."""
        vault = _create_vault(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "NPCs").mkdir()
        os.symlink(str(outside), str(vault / "Characters"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            entity_directory(vault, EntityType.NPC)

    def test_parent_symlink_rejected_for_npc_discovery(self, tmp_path: Path) -> None:
        """Characters symlinked to outside -> NPC discovery raises StorageError."""
        vault = _create_vault(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "NPCs").mkdir()
        (outside / "NPCs" / "evil.md").write_text("evil", encoding="utf-8")
        os.symlink(str(outside), str(vault / "Characters"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            discover_entity_files(vault, EntityType.NPC)

    def test_parent_symlink_to_another_vault_dir_rejected(self, tmp_path: Path) -> None:
        """Characters symlinked to Locations inside vault -> NPC rejected."""
        vault = _create_vault(tmp_path, ["Locations"])
        os.symlink(str(vault / "Locations"), str(vault / "Characters"), target_is_directory=True)

        with pytest.raises(StorageError, match="symlink"):
            entity_directory(vault, EntityType.NPC)


# ── Filesystem error translation tests ──────────────────────────────────────


class TestFilesystemErrors:
    def test_discovery_unreadable_directory_raises_storage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate a filesystem error during directory iteration."""
        vault = _create_vault(tmp_path, ["Characters/NPCs"])
        _create_file(vault, "Characters/NPCs/gandalf.md")

        original_iters = Path.iterdir

        def broken_iterdir(self: Path) -> object:
            if "NPCs" in str(self):
                raise OSError(13, "Permission denied", str(self))
            return original_iters(self)

        monkeypatch.setattr(Path, "iterdir", broken_iterdir)

        with pytest.raises(StorageError):
            discover_entity_files(vault, EntityType.NPC)


# ── Import / boundary tests ─────────────────────────────────────────────────


def test_paths_module_importable() -> None:
    from dnd_assistant.storage import paths  # noqa: F401


def test_paths_api_reexported() -> None:
    from dnd_assistant.storage import (  # noqa: F401
        DiscoveredEntityFile,
        discover_entity_files,
        entity_directory,
        resolve_entity_path,
    )


@pytest.mark.usefixtures("restore_dnd_assistant_modules")
class TestPathsImportBoundaries:
    """Clean-import boundary tests for storage/paths."""

    def test_does_not_import_models(self) -> None:
        """Verify storage/paths does not trigger model imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

        import dnd_assistant.storage.paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
        assert not mod_names, f"storage/paths imported model modules: {mod_names}"

    def test_does_not_import_retrieval(self) -> None:
        """Verify storage/paths does not trigger retrieval imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

        import dnd_assistant.storage.paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.retrieval")}
        assert not mod_names, f"storage/paths imported retrieval modules: {mod_names}"

    def test_does_not_import_tools(self) -> None:
        """Verify storage/paths does not trigger tool imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]

        import dnd_assistant.storage.paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.tools")}
        assert not mod_names, f"storage/paths imported tool modules: {mod_names}"


def test_paths_does_not_import_markdown_codec() -> None:
    """S3-02 must not import or use the Markdown codec.

    We check the source of paths.py directly rather than relying on
    sys.modules state (which is affected by storage.__init__ importing
    both paths and markdown).
    """
    import inspect

    from dnd_assistant.storage import paths as paths_module

    source = inspect.getsource(paths_module)
    # The module should not reference markdown parse/serialize functions
    assert "from dnd_assistant.storage.markdown" not in source
    assert "import markdown" not in source
    # It should reference types (EntityDirectory) which is fine
    assert "from dnd_assistant.storage.types" in source
