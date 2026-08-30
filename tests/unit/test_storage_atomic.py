"""Tests for atomic text-write primitive (S3-03)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from dnd_assistant.errors import StorageError, ValidationError
from dnd_assistant.storage.atomic import atomic_write_text


def _make_target(tmp_path: Path, name: str = "target.md") -> Path:
    parent = tmp_path / "vault"
    parent.mkdir()
    return parent / name


def _can_symlink() -> bool:
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


class TestAtomicWriteSuccess:
    def test_create_missing_target(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "Hello, world!"
        atomic_write_text(target, content, validator=lambda c: None)
        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_replace_existing_target(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        target.write_text("OLD CONTENT", encoding="utf-8")
        new_content = "NEW CONTENT"
        atomic_write_text(target, new_content, validator=lambda c: None)
        assert target.read_text(encoding="utf-8") == new_content

    def test_unicode_preservation(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "Привет, мир! 日本語 Español العربية"
        atomic_write_text(target, content, validator=lambda c: None)
        assert target.read_text(encoding="utf-8") == content

    def test_lf_preservation(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "line1\nline2\nline3\n"
        atomic_write_text(target, content, validator=lambda c: None)
        assert target.read_text(encoding="utf-8") == content
        assert "\r\n" not in target.read_bytes().decode("utf-8")

    def test_crlf_preservation(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "line1\r\nline2\r\nline3\r\n"
        atomic_write_text(target, content, validator=lambda c: None)
        # Use read_bytes() to avoid text-mode newline translation on Windows
        assert target.read_bytes().decode("utf-8") == content

    def test_no_trailing_newline_modification(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "no trailing newline"
        atomic_write_text(target, content, validator=lambda c: None)
        assert target.read_text(encoding="utf-8") == content

    def test_trailing_newline_preserved(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "has trailing newline\n"
        atomic_write_text(target, content, validator=lambda c: None)
        assert target.read_text(encoding="utf-8") == content

    def test_mixed_newlines_preserved(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "lf\ncrlf\r\nlf\ncrlf\r\n"
        atomic_write_text(target, content, validator=lambda c: None)
        # Use read_bytes() to avoid text-mode newline translation on Windows
        assert target.read_bytes().decode("utf-8") == content

    def test_validator_called_with_content(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "validated content"
        recorded: list[str] = []

        def validator(c: str) -> None:
            recorded.append(c)

        atomic_write_text(target, content, validator=validator)
        assert recorded == [content]

    def test_no_temp_files_remain_after_success(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "cleanup test"
        atomic_write_text(target, content, validator=lambda c: None)
        parent_files = list(target.parent.iterdir())
        assert len(parent_files) == 1
        assert parent_files[0] == target

    def test_validator_return_value_ignored(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        content = "content"
        atomic_write_text(target, content, validator=lambda c: 42)
        assert target.read_text(encoding="utf-8") == content


class TestOperationOrdering:
    def test_fsync_before_validator_before_replace(self, tmp_path: Path) -> None:
        """Behaviourally verify fsync < validator < os.replace."""
        target = _make_target(tmp_path)
        content = "ordering test"
        events: list[str] = []
        original_fsync = os.fsync
        original_replace = os.replace

        def patched_fsync(fd: int) -> None:
            events.append("fsync")
            original_fsync(fd)

        def patched_replace(src: str, dst: str) -> None:
            events.append("replace")
            original_replace(src, dst)

        def validator(c: str) -> None:
            events.append("validator")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.fsync = patched_fsync  # type: ignore[attr-defined]
        atomic_mod.os.replace = patched_replace  # type: ignore[attr-defined]
        try:
            atomic_write_text(target, content, validator=validator)
        finally:
            atomic_mod.os.fsync = original_fsync
            atomic_mod.os.replace = original_replace

        assert events == ["fsync", "validator", "replace"]


class TestValidationFailure:
    def test_existing_target_unchanged(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        target.write_text("ORIGINAL", encoding="utf-8")
        with pytest.raises(ValidationError, match="invalid data"):
            atomic_write_text(
                target,
                "new content",
                validator=lambda c: (_ for _ in ()).throw(ValidationError("invalid data")),
            )
        assert target.read_text(encoding="utf-8") == "ORIGINAL"

    def test_missing_target_remains_absent(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        with pytest.raises(ValidationError, match="invalid"):
            atomic_write_text(
                target,
                "new content",
                validator=lambda c: (_ for _ in ()).throw(ValidationError("invalid")),
            )
        assert not target.exists()

    def test_validator_exception_propagates_unchanged(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        with pytest.raises(ValidationError) as exc_info:
            atomic_write_text(
                target,
                "content",
                validator=lambda c: (_ for _ in ()).throw(ValidationError("custom message")),
            )
        assert "custom message" in str(exc_info.value)

    def test_temp_file_removed_after_validation_failure(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        with pytest.raises(ValidationError):
            atomic_write_text(
                target,
                "content",
                validator=lambda c: (_ for _ in ()).throw(ValidationError("fail")),
            )
        parent_files = list(target.parent.iterdir())
        assert all(f == target for f in parent_files)


class TestFsyncFailure:
    def test_fsync_failure_raises_storage_error(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        original_fsync = os.fsync

        def failing_fsync(fd: int) -> None:
            raise OSError(5, "Input/output error during fsync")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.fsync = failing_fsync  # type: ignore[attr-defined]
        try:
            with pytest.raises(StorageError) as exc_info:
                atomic_write_text(target, "content", validator=lambda c: None)
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, OSError)
        finally:
            atomic_mod.os.fsync = original_fsync

    def test_fsync_failure_original_target_unchanged(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        target.write_text("ORIGINAL", encoding="utf-8")
        original_fsync = os.fsync

        def failing_fsync(fd: int) -> None:
            raise OSError(5, "fsync error")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.fsync = failing_fsync  # type: ignore[attr-defined]
        try:
            with pytest.raises(StorageError):
                atomic_write_text(target, "new content", validator=lambda c: None)
        finally:
            atomic_mod.os.fsync = original_fsync
        assert target.read_text(encoding="utf-8") == "ORIGINAL"

    def test_fsync_failure_temp_cleaned(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        original_fsync = os.fsync

        def failing_fsync(fd: int) -> None:
            raise OSError(5, "fsync error")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.fsync = failing_fsync  # type: ignore[attr-defined]
        try:
            with pytest.raises(StorageError):
                atomic_write_text(target, "content", validator=lambda c: None)
        finally:
            atomic_mod.os.fsync = original_fsync
        parent_files = list(target.parent.iterdir())
        assert all(f == target for f in parent_files)


class TestReplaceFailure:
    def test_replace_failure_raises_storage_error(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        original_replace = os.replace

        def failing_replace(src: str, dst: str) -> None:
            raise OSError(30, "Read-only file system")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.replace = failing_replace  # type: ignore[attr-defined]
        try:
            with pytest.raises(StorageError) as exc_info:
                atomic_write_text(target, "content", validator=lambda c: None)
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, OSError)
        finally:
            atomic_mod.os.replace = original_replace

    def test_replace_failure_original_target_unchanged(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        target.write_text("ORIGINAL", encoding="utf-8")
        original_replace = os.replace

        def failing_replace(src: str, dst: str) -> None:
            raise OSError(30, "Read-only file system")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.replace = failing_replace  # type: ignore[attr-defined]
        try:
            with pytest.raises(StorageError):
                atomic_write_text(target, "new content", validator=lambda c: None)
        finally:
            atomic_mod.os.replace = original_replace
        assert target.read_text(encoding="utf-8") == "ORIGINAL"

    def test_replace_failure_temp_cleaned(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        original_replace = os.replace

        def failing_replace(src: str, dst: str) -> None:
            raise OSError(30, "Read-only file system")

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.replace = failing_replace  # type: ignore[attr-defined]
        try:
            with pytest.raises(StorageError):
                atomic_write_text(target, "content", validator=lambda c: None)
        finally:
            atomic_mod.os.replace = original_replace
        parent_files = list(target.parent.iterdir())
        assert all(f == target for f in parent_files)


class TestTempFailure:
    def test_write_failure_raises_storage_error(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        # Patch tempfile.mkstemp to raise OSError, simulating temp creation failure.
        with mock.patch("tempfile.mkstemp", side_effect=OSError(28, "No space left on device")):
            with pytest.raises(StorageError) as exc_info:
                atomic_write_text(target, "content", validator=lambda c: None)
            assert exc_info.value.__cause__ is not None

    def test_write_failure_original_target_unchanged(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path)
        target.write_text("ORIGINAL", encoding="utf-8")
        with mock.patch("tempfile.mkstemp", side_effect=OSError(28, "No space left on device")):
            with pytest.raises(StorageError):
                atomic_write_text(target, "content", validator=lambda c: None)
        assert target.read_text(encoding="utf-8") == "ORIGINAL"


class TestPathState:
    def test_missing_parent_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "nonexistent" / "target.md"
        with pytest.raises(StorageError, match="parent directory does not exist"):
            atomic_write_text(target, "content", validator=lambda c: None)

    def test_parent_regular_file_rejected(self, tmp_path: Path) -> None:
        parent = tmp_path / "not_a_dir"
        parent.write_text("I am a file", encoding="utf-8")
        target = parent / "target.md"
        with pytest.raises(StorageError, match="not a directory"):
            atomic_write_text(target, "content", validator=lambda c: None)

    def test_target_directory_rejected(self, tmp_path: Path) -> None:
        parent = tmp_path / "vault"
        parent.mkdir()
        target_dir = parent / "subdir"
        target_dir.mkdir()
        with pytest.raises(StorageError, match="existing directory"):
            atomic_write_text(target_dir, "content", validator=lambda c: None)

    def test_target_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        parent = tmp_path / "vault"
        parent.mkdir()
        real_target = parent / "real.md"
        real_target.write_text("real", encoding="utf-8")
        symlink = parent / "link.md"
        os.symlink(str(real_target), str(symlink))
        with pytest.raises(StorageError, match="symlink"):
            atomic_write_text(symlink, "content", validator=lambda c: None)
        assert real_target.read_text(encoding="utf-8") == "real"

    def test_relative_path_rejected(self, tmp_path: Path) -> None:
        target = Path("relative/path.md")
        with pytest.raises(StorageError, match="absolute"):
            atomic_write_text(target, "content", validator=lambda c: None)


class TestSameDirectoryTemp:
    def test_temp_in_same_parent_as_target(self, tmp_path: Path) -> None:
        """Verify temp file is created in the same parent as target."""
        target = _make_target(tmp_path)
        recorded: list[Path] = []
        original_replace = os.replace

        def recording_replace(src: str, dst: str) -> None:
            recorded.append(Path(src))
            original_replace(src, dst)

        import dnd_assistant.storage.atomic as atomic_mod

        atomic_mod.os.replace = recording_replace  # type: ignore[attr-defined]
        try:
            atomic_write_text(target, "content", validator=lambda c: None)
        finally:
            atomic_mod.os.replace = original_replace
        assert len(recorded) == 1
        assert recorded[0].parent == target.parent


def test_atomic_module_importable() -> None:
    from dnd_assistant.storage import atomic  # noqa: F401


def test_atomic_write_text_reexported() -> None:
    from dnd_assistant.storage import atomic_write_text  # noqa: F401


def test_atomic_does_not_import_domain_entity() -> None:
    import dnd_assistant.storage.atomic as atomic_mod

    src = Path(atomic_mod.__file__).read_text(encoding="utf-8")
    assert "dnd_assistant.domain.entity" not in src


def test_atomic_does_not_import_markdown() -> None:
    import dnd_assistant.storage.atomic as atomic_mod

    src = Path(atomic_mod.__file__).read_text(encoding="utf-8")
    assert "dnd_assistant.storage.markdown" not in src


def test_atomic_does_not_import_models() -> None:
    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]
    import dnd_assistant.storage.atomic  # noqa: F401

    mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
    assert not mod_names, f"atomic imported model modules: {mod_names}"


def test_atomic_does_not_import_retrieval() -> None:
    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]
    import dnd_assistant.storage.atomic  # noqa: F401

    mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.retrieval")}
    assert not mod_names, f"atomic imported retrieval modules: {mod_names}"


def test_atomic_does_not_import_tools() -> None:
    for key in list(sys.modules):
        if key.startswith("dnd_assistant"):
            del sys.modules[key]
    import dnd_assistant.storage.atomic  # noqa: F401

    mod_names = {m for m in sys.modules if m.startswith("dnd_assistant.tools")}
    assert not mod_names, f"atomic imported tool modules: {mod_names}"
