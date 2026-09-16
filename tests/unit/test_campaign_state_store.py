"""S12-03 Obsidian derived-state store path/symlink/directory safety tests.

Covers exact managed-file ownership, directory creation, unrelated-file
preservation, payload-set enforcement, LF-only content, UTF-8 failure handling
and symlink safety for ``State/``, managed artifacts and the manifest.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from dnd_assistant.application.campaign_state_render import (
    ARTIFACT_ORDER,
    LOGICAL_ARTIFACT_PATHS,
)
from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.derived_state import (
    ARTIFACT_FILENAMES,
    MANIFEST_FILENAME,
    ObsidianDerivedStateStore,
    artifact_filename,
)
from tests.unit.campaign_state.helpers import make_vault

_MANIFEST = '{"schema_version":2}\n'


def _can_symlink() -> bool:
    import tempfile

    tmp = tempfile.mkdtemp()
    try:
        target = os.path.join(tmp, "target")
        link = os.path.join(tmp, "link")
        Path(target).write_text("", encoding="utf-8")
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _texts() -> dict[CampaignStateArtifact, str]:
    return {artifact: f"# {artifact.value}\n" for artifact in ARTIFACT_ORDER}


def _store(tmp_path: Path) -> ObsidianDerivedStateStore:
    return ObsidianDerivedStateStore(make_vault(tmp_path))


class TestLayoutContract:
    def test_logical_path_matches_trusted_filename(self) -> None:
        for artifact in ARTIFACT_ORDER:
            assert LOGICAL_ARTIFACT_PATHS[artifact] == f"State/{artifact_filename(artifact)}"

    def test_artifact_filenames_cover_exact_set(self) -> None:
        assert set(ARTIFACT_FILENAMES) == set(ARTIFACT_ORDER)


class TestMissing:
    def test_missing_manifest(self, tmp_path: Path) -> None:
        assert _store(tmp_path).read_manifest_text() is None

    def test_missing_artifacts(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        for artifact in ARTIFACT_ORDER:
            assert store.read_artifact_bytes(artifact) is None


class TestPublish:
    def test_publish_creates_state_and_files(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.publish(_texts(), _MANIFEST)
        state_dir = store.state_dir
        assert state_dir.is_dir()
        assert (state_dir / MANIFEST_FILENAME).read_text(encoding="utf-8") == _MANIFEST
        for artifact in ARTIFACT_ORDER:
            assert (state_dir / ARTIFACT_FILENAMES[artifact]).exists()

    def test_unrelated_user_file_preserved(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        state_dir = store.state_dir
        state_dir.mkdir()
        unrelated = state_dir / "My Notes.md"
        unrelated.write_text("player notes", encoding="utf-8")
        store.publish(_texts(), _MANIFEST)
        assert unrelated.read_text(encoding="utf-8") == "player notes"

    def test_empty_payload_set_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError):
            _store(tmp_path).publish({}, _MANIFEST)

    def test_extra_payload_rejected(self, tmp_path: Path) -> None:
        texts = _texts()
        texts[CampaignStateArtifact.RECENTLY_TOUCHED] = "x\n"
        # remove one to create both missing and extra relative to expected
        del texts[CampaignStateArtifact.WORLD_STATE]
        with pytest.raises(StorageError):
            _store(tmp_path).publish(texts, _MANIFEST)

    def test_cr_content_rejected(self, tmp_path: Path) -> None:
        texts = _texts()
        texts[CampaignStateArtifact.WORLD_STATE] = "a\r\nb\n"
        with pytest.raises(StorageError):
            _store(tmp_path).publish(texts, _MANIFEST)
        assert not (tmp_path / "vault" / "State").exists()

    def test_state_path_is_file_rejected(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        (tmp_path / "vault" / "State").write_text("i am a file", encoding="utf-8")
        with pytest.raises(StorageError):
            store.publish(_texts(), _MANIFEST)
        with pytest.raises(StorageError):
            store.read_manifest_text()


class TestReadFailures:
    def test_invalid_utf8_manifest_raises(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        state_dir = store.state_dir
        state_dir.mkdir()
        (state_dir / MANIFEST_FILENAME).write_bytes(b"\xff\xfe")
        with pytest.raises(StorageError):
            store.read_manifest_text()

    def test_artifact_is_directory_raises(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        state_dir = store.state_dir
        state_dir.mkdir()
        (state_dir / ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE]).mkdir()
        with pytest.raises(StorageError):
            store.read_artifact_bytes(CampaignStateArtifact.WORLD_STATE)


class TestSymlinkSafety:
    def test_state_dir_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        root = make_vault(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(str(outside), str(root / "State"))
        store = ObsidianDerivedStateStore(root)
        with pytest.raises(StorageError):
            store.read_manifest_text()
        with pytest.raises(StorageError):
            store.publish(_texts(), _MANIFEST)

    def test_artifact_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        store = _store(tmp_path)
        state_dir = store.state_dir
        state_dir.mkdir()
        target = tmp_path / "outside.md"
        target.write_text("outside", encoding="utf-8")
        os.symlink(
            str(target), str(state_dir / ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE])
        )
        with pytest.raises(StorageError):
            store.read_artifact_bytes(CampaignStateArtifact.WORLD_STATE)
        with pytest.raises(StorageError):
            store.publish(_texts(), _MANIFEST)
        assert target.read_text(encoding="utf-8") == "outside"

    def test_manifest_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        store = _store(tmp_path)
        state_dir = store.state_dir
        state_dir.mkdir()
        target = tmp_path / "outside.json"
        target.write_text(_MANIFEST, encoding="utf-8")
        os.symlink(str(target), str(state_dir / MANIFEST_FILENAME))
        with pytest.raises(StorageError):
            store.read_manifest_text()

    def test_dangling_artifact_symlink_rejected(self, tmp_path: Path) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        store = _store(tmp_path)
        state_dir = store.state_dir
        state_dir.mkdir()
        os.symlink(
            str(tmp_path / "nonexistent.md"),
            str(state_dir / ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE]),
        )
        with pytest.raises(StorageError):
            store.read_artifact_bytes(CampaignStateArtifact.WORLD_STATE)


class TestMutationTimeReauthorization:
    """``State/`` substituted between managed writes must fail closed."""

    @staticmethod
    def _substitute_after(
        monkeypatch: pytest.MonkeyPatch,
        store: ObsidianDerivedStateStore,
        trigger_name: str,
        outside: Path,
    ) -> None:
        import dnd_assistant.storage.derived_state as ds

        original = ds.atomic_write_text

        def hook(target, content, *, validator):
            result = original(target, content, validator=validator)
            if Path(target).name == trigger_name:
                shutil.rmtree(store.state_dir)
                os.symlink(str(outside), str(store.state_dir))
            return result

        monkeypatch.setattr(ds, "atomic_write_text", hook)

    def test_parent_substitution_before_second_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        store = _store(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        self._substitute_after(
            monkeypatch, store, ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE], outside
        )
        with pytest.raises(StorageError):
            store.publish(_texts(), _MANIFEST)
        assert list(outside.iterdir()) == []

    def test_parent_substitution_before_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not _can_symlink():
            pytest.skip("Environment does not support symlinks")
        store = _store(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        self._substitute_after(
            monkeypatch, store, ARTIFACT_FILENAMES[CampaignStateArtifact.RECENTLY_TOUCHED], outside
        )
        with pytest.raises(StorageError):
            store.publish(_texts(), _MANIFEST)
        assert list(outside.iterdir()) == []
        assert not (outside / MANIFEST_FILENAME).exists()
