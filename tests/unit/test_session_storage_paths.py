"""Unit tests for S6-00 session storage path/layout safety.

Covers:
- ``SessionStoragePaths`` value semantics
- Valid layout resolution for a canonical session ID
- Unicode session ID support
- Invalid session ID rejection (empty, whitespace, traversal, path chars,
  Windows-invalid characters, trailing dot/space, reserved device names)
- Vault root validation (missing, file, invalid type)
- Symlink safety for session/raw path components
- No-mutation invariant (resolver is read-only)
- Import/boundary checks
"""

from __future__ import annotations

import os
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.session_paths import (
    SessionStoragePaths,
    resolve_session_storage_paths,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_vault(tmp_path: Path) -> Path:
    """Create a minimal Vault directory structure for testing."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def _create_vault_with_session_dirs(tmp_path: Path) -> Path:
    """Create a Vault with session storage directories."""
    vault = _create_vault(tmp_path)
    (vault / "Sessions").mkdir(parents=True, exist_ok=True)
    (vault / "_system" / "raw" / "sessions").mkdir(parents=True, exist_ok=True)
    return vault


# ── SessionStoragePaths value semantics ──────────────────────────────────────


class TestSessionStoragePathsValue:
    """Verify SessionStoragePaths is a proper immutable value object."""

    def test_construct(self) -> None:
        paths = SessionStoragePaths(
            session_dir=Path("/vault/Sessions/S006"),
            session_md=Path("/vault/Sessions/S006/Session.md"),
            raw_dir=Path("/vault/_system/raw/sessions/S006"),
            raw_metadata=Path("/vault/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/vault/_system/raw/sessions/S006/events.jsonl"),
        )
        assert paths.session_dir == Path("/vault/Sessions/S006")
        assert paths.session_md == Path("/vault/Sessions/S006/Session.md")
        assert paths.raw_dir == Path("/vault/_system/raw/sessions/S006")
        assert paths.raw_metadata == Path("/vault/_system/raw/sessions/S006/metadata.json")
        assert paths.raw_events == Path("/vault/_system/raw/sessions/S006/events.jsonl")

    def test_equality(self) -> None:
        a = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        b = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        assert a == b
        assert not (a != b)

    def test_inequality(self) -> None:
        a = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        b = SessionStoragePaths(
            session_dir=Path("/v/S007"),
            session_md=Path("/v/S007/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S007"),
            raw_metadata=Path("/v/_system/raw/sessions/S007/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S007/events.jsonl"),
        )
        assert a != b

    def test_hashable(self) -> None:
        paths = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        s = {paths}
        assert paths in s

    def test_not_equal_to_non_session_paths(self) -> None:
        paths = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        assert paths != "not-a-path-object"
        assert paths != 42

    def test_repr(self) -> None:
        paths = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        r = repr(paths)
        assert "SessionStoragePaths" in r
        assert "S006" in r

    def test_frozen_immutable(self) -> None:
        """Assignment to any field must raise FrozenInstanceError."""
        paths = SessionStoragePaths(
            session_dir=Path("/v/S006"),
            session_md=Path("/v/S006/Session.md"),
            raw_dir=Path("/v/_system/raw/sessions/S006"),
            raw_metadata=Path("/v/_system/raw/sessions/S006/metadata.json"),
            raw_events=Path("/v/_system/raw/sessions/S006/events.jsonl"),
        )
        with pytest.raises(FrozenInstanceError):
            paths.session_dir = Path("/other")  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            paths.session_md = Path("/other")  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            paths.raw_dir = Path("/other")  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            paths.raw_metadata = Path("/other")  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            paths.raw_events = Path("/other")  # type: ignore[misc]


# ── Valid layout ─────────────────────────────────────────────────────────────


class TestValidLayout:
    """Verify exact expected paths for a valid session ID."""

    def test_canonical_s006(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        paths = resolve_session_storage_paths(vault, "S006")

        assert paths.session_dir.is_absolute()
        assert paths.session_md.is_absolute()
        assert paths.raw_dir.is_absolute()
        assert paths.raw_metadata.is_absolute()
        assert paths.raw_events.is_absolute()

        paths.session_dir.relative_to(vault.resolve())
        paths.session_md.relative_to(vault.resolve())
        paths.raw_dir.relative_to(vault.resolve())
        paths.raw_metadata.relative_to(vault.resolve())
        paths.raw_events.relative_to(vault.resolve())

        assert paths.session_dir == (vault.resolve() / "Sessions" / "S006")
        assert paths.session_md == (vault.resolve() / "Sessions" / "S006" / "Session.md")
        assert paths.raw_dir == (vault.resolve() / "_system" / "raw" / "sessions" / "S006")
        assert paths.raw_metadata == (
            vault.resolve() / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        )
        assert paths.raw_events == (
            vault.resolve() / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        )

    def test_another_session_id(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        paths = resolve_session_storage_paths(vault, "S014")
        assert paths.session_dir == (vault.resolve() / "Sessions" / "S014")
        assert paths.raw_dir == (vault.resolve() / "_system" / "raw" / "sessions" / "S014")

    def test_missing_session_dirs_ok(self, tmp_path: Path) -> None:
        """Missing session/raw directories are acceptable — resolver does not create them."""
        vault = _create_vault(tmp_path)
        paths = resolve_session_storage_paths(vault, "S006")
        assert paths.session_dir == (vault.resolve() / "Sessions" / "S006")
        assert paths.raw_dir == (vault.resolve() / "_system" / "raw" / "sessions" / "S006")


# ── Unicode session ID ───────────────────────────────────────────────────────


class TestUnicodeSessionId:
    """Safe printable Unicode session IDs must be supported."""

    def test_cyrillic_id(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        session_id = "\u0421\u0435\u0441\u0441\u0438\u044f_01"
        paths = resolve_session_storage_paths(vault, session_id)
        assert paths.session_dir == (vault.resolve() / "Sessions" / session_id)
        assert paths.raw_dir == (vault.resolve() / "_system" / "raw" / "sessions" / session_id)

    def test_printable_unicode_with_dots(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        session_id = "S.014"
        paths = resolve_session_storage_paths(vault, session_id)
        assert paths.session_dir == (vault.resolve() / "Sessions" / session_id)


# ── Invalid session ID / path forms ──────────────────────────────────────────


class TestInvalidSessionId:
    """Parametrized rejection of unsafe session IDs."""

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            " ",
            ".",
            "..",
            "../S006",
            "S006/child",
            "S006\\child",
            " S006",
            "S006 ",
            " S006 ",
            "\tleading",
            "trailing\n",
            "with<angle",
            "with>angle",
            'with"quote',
            "with:colon",
            "with|pipe",
            "with?question",
            "with*star",
        ],
    )
    def test_rejects_invalid_ids(self, tmp_path: Path, invalid_id: str) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, invalid_id)

    def test_rejects_control_characters(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, "S00\x007")

    def test_rejects_trailing_dot(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, "S006.")

    def test_rejects_trailing_space(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, "S006 ")

    def test_rejects_non_string(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, 123)  # type: ignore[arg-type]


# ── Windows reserved device names ────────────────────────────────────────────


class TestWindowsReservedNames:
    """Windows reserved device names must be rejected even on non-Windows."""

    @pytest.mark.parametrize(
        "reserved",
        [
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        ],
    )
    def test_rejects_reserved_name(self, tmp_path: Path, reserved: str) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, reserved)

    @pytest.mark.parametrize(
        "reserved_variant",
        ["con", "Con", "CON", "nul", "NUL", "Nul", "COM1", "com1", "LPT1", "lpt1"],
    )
    def test_rejects_case_variants(self, tmp_path: Path, reserved_variant: str) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, reserved_variant)

    @pytest.mark.parametrize(
        "reserved_with_ext",
        ["CON.txt", "NUL.md", "COM1.json", "LPT1.yaml"],
    )
    def test_rejects_reserved_with_extension(self, tmp_path: Path, reserved_with_ext: str) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        with pytest.raises(StorageError):
            resolve_session_storage_paths(vault, reserved_with_ext)

    def test_accepts_con_in_middle(self, tmp_path: Path) -> None:
        """CON as part of a longer ID is acceptable."""
        vault = _create_vault_with_session_dirs(tmp_path)
        paths = resolve_session_storage_paths(vault, "S_CON_001")
        assert paths.session_dir == (vault.resolve() / "Sessions" / "S_CON_001")


# ── Vault root failures ──────────────────────────────────────────────────────


class TestVaultRootFailures:
    """Verify proper error handling for invalid Vault root arguments."""

    def test_missing_root(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(StorageError):
            resolve_session_storage_paths(missing, "S006")

    def test_root_is_file(self, tmp_path: Path) -> None:
        f = tmp_path / "afile.txt"
        f.write_text("hello", encoding="utf-8")
        with pytest.raises(StorageError):
            resolve_session_storage_paths(f, "S006")

    def test_invalid_root_type(self) -> None:
        with pytest.raises(StorageError):
            resolve_session_storage_paths(42, "S006")  # type: ignore[arg-type]


# ── Symlink safety ───────────────────────────────────────────────────────────


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
    """Symlinked session/raw path components must be rejected."""

    def test_sessions_symlink_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        outside = tmp_path / "outside_sessions"
        outside.mkdir()
        os.symlink(str(outside), str(vault / "Sessions"), target_is_directory=True)
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_raw_symlink_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        (vault / "Sessions").mkdir(parents=True)
        outside = tmp_path / "outside_raw"
        outside.mkdir()
        (outside / "sessions").mkdir()
        os.symlink(
            str(outside),
            str(vault / "_system" / "raw"),
            target_is_directory=True,
        )
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_session_id_component_symlink_rejected(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        (vault / "Sessions").mkdir()
        outside = tmp_path / "outside_session"
        outside.mkdir()
        os.symlink(
            str(outside),
            str(vault / "Sessions" / "S006"),
            target_is_directory=True,
        )
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_dangling_sessions_symlink_rejected(self, tmp_path: Path) -> None:
        """A dangling (broken) symlink in the Sessions subtree must be rejected."""
        vault = _create_vault(tmp_path)
        missing = tmp_path / "missing_target"
        os.symlink(str(missing), str(vault / "Sessions"), target_is_directory=True)
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_dangling_raw_symlink_rejected(self, tmp_path: Path) -> None:
        """A dangling (broken) symlink in the raw subtree must be rejected."""
        vault = _create_vault(tmp_path)
        (vault / "Sessions").mkdir(parents=True)
        missing = tmp_path / "missing_raw"
        os.symlink(
            str(missing),
            str(vault / "_system" / "raw"),
            target_is_directory=True,
        )
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_session_md_leaf_symlink_rejected(self, tmp_path: Path) -> None:
        """An existing Session.md that is a symlink must be rejected."""
        vault = _create_vault_with_session_dirs(tmp_path)
        session_dir = vault / "Sessions" / "S006"
        session_dir.mkdir(parents=True)
        target = tmp_path / "outside_session.md"
        target.write_text("", encoding="utf-8")
        os.symlink(str(target), str(session_dir / "Session.md"))
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_dangling_session_md_leaf_symlink_rejected(self, tmp_path: Path) -> None:
        """A dangling Session.md symlink must be rejected."""
        vault = _create_vault_with_session_dirs(tmp_path)
        session_dir = vault / "Sessions" / "S006"
        session_dir.mkdir(parents=True)
        missing = tmp_path / "missing_session.md"
        os.symlink(str(missing), str(session_dir / "Session.md"))
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_raw_metadata_leaf_symlink_rejected(self, tmp_path: Path) -> None:
        """An existing metadata.json that is a symlink must be rejected."""
        vault = _create_vault_with_session_dirs(tmp_path)
        raw_dir = vault / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir(parents=True)
        target = tmp_path / "outside_metadata.json"
        target.write_text("{}", encoding="utf-8")
        os.symlink(str(target), str(raw_dir / "metadata.json"))
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")

    def test_dangling_raw_metadata_leaf_symlink_rejected(self, tmp_path: Path) -> None:
        """A dangling metadata.json symlink must be rejected."""
        vault = _create_vault_with_session_dirs(tmp_path)
        raw_dir = vault / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir(parents=True)
        missing = tmp_path / "missing_metadata.json"
        os.symlink(str(missing), str(raw_dir / "metadata.json"))
        with pytest.raises(StorageError, match="symlink"):
            resolve_session_storage_paths(vault, "S006")


# ── No-mutation invariant ────────────────────────────────────────────────────


class TestNoMutation:
    """Resolver must not create any directories or files."""

    def test_no_directories_created(self, tmp_path: Path) -> None:
        vault = _create_vault(tmp_path)
        before = set(vault.rglob("*"))
        resolve_session_storage_paths(vault, "S006")
        after = set(vault.rglob("*"))
        assert before == after, "Resolver created filesystem entries"

    def test_no_files_created_with_existing_dirs(self, tmp_path: Path) -> None:
        vault = _create_vault_with_session_dirs(tmp_path)
        before = set(vault.rglob("*"))
        resolve_session_storage_paths(vault, "S006")
        after = set(vault.rglob("*"))
        assert before == after, "Resolver created filesystem entries"


# ── Import / boundary checks ─────────────────────────────────────────────────


def test_session_paths_module_importable() -> None:
    from dnd_assistant.storage.session_paths import (  # noqa: F401
        SessionStoragePaths,
        resolve_session_storage_paths,
    )


@pytest.mark.usefixtures("restore_dnd_assistant_modules")
class TestSessionPathsImportBoundaries:
    """Clean-import boundary tests for storage/session_paths."""

    def test_does_not_import_models(self) -> None:
        """Verify storage/session_paths does not trigger model imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        import dnd_assistant.storage.session_paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
        assert not mod_names, f"session_paths imported model modules: {mod_names}"

    def test_does_not_import_retrieval(self) -> None:
        """Verify storage/session_paths does not trigger retrieval imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        import dnd_assistant.storage.session_paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.retrieval")}
        assert not mod_names, f"session_paths imported retrieval modules: {mod_names}"

    def test_does_not_import_tools(self) -> None:
        """Verify storage/session_paths does not trigger tool imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        import dnd_assistant.storage.session_paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.tools")}
        assert not mod_names, f"session_paths imported tool modules: {mod_names}"

    def test_does_not_import_application(self) -> None:
        """Verify storage/session_paths does not trigger application imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        import dnd_assistant.storage.session_paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.application")}
        assert not mod_names, f"session_paths imported application modules: {mod_names}"

    def test_does_not_import_cli(self) -> None:
        """Verify storage/session_paths does not trigger CLI imports."""
        for key in list(sys.modules):
            if key.startswith("dnd_assistant"):
                del sys.modules[key]
        import dnd_assistant.storage.session_paths  # noqa: F401

        mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.cli")}
        assert not mod_names, f"session_paths imported CLI modules: {mod_names}"
