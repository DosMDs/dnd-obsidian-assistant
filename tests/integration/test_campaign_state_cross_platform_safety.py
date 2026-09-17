"""S12-05 cross-platform derived-state topology safety.

Covers redirecting ``State/`` topologies that ``Path.is_symlink()`` alone does
not catch: Windows directory junctions / reparse redirects and resolved-path
containment.  Includes deterministic all-platform branch coverage (monkeypatched
``is_junction``/``resolve``) plus a real Windows junction test gated on host
capability created with a test-only ``cmd /c mklink /J`` (never ``shell=True``;
production never shells out).

Also analyses managed-leaf hard links under the current temp-file + ``os.replace``
semantics and documents Vault-root substitution parity with canonical storage.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
from pathlib import Path

import pytest

from dnd_assistant.application.campaign_state_render import ARTIFACT_ORDER
from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.derived_state import (
    ARTIFACT_FILENAMES,
    MANIFEST_FILENAME,
    ObsidianDerivedStateStore,
)
from tests.unit.campaign_state.helpers import make_vault

_MANIFEST = '{"schema_version":2}\n'
_WORLD = ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE]
_TOUCHED = ARTIFACT_FILENAMES[CampaignStateArtifact.RECENTLY_TOUCHED]


def _texts() -> dict[CampaignStateArtifact, str]:
    return {artifact: f"# {artifact.value}\n" for artifact in ARTIFACT_ORDER}


def _store(tmp_path: Path) -> ObsidianDerivedStateStore:
    return ObsidianDerivedStateStore(make_vault(tmp_path))


def _make_junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and link.is_junction()


# ── Deterministic all-platform junction-branch coverage ────────────────────


class TestJunctionBranchDeterministic:
    def _patch_state_junction(
        self, monkeypatch: pytest.MonkeyPatch, state: Path, value: bool = True
    ) -> None:
        real = pathlib.Path.is_junction

        def fake(self: pathlib.Path) -> bool:
            if str(self) == str(state):
                return value
            return real(self)

        monkeypatch.setattr(pathlib.Path, "is_junction", fake)

    def test_absent_state_with_junction_flag_fails_closed_before_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        state = store.state_dir
        self._patch_state_junction(monkeypatch, state)

        with pytest.raises(StorageError, match="junction"):
            store.publish(_texts(), _MANIFEST)
        with pytest.raises(StorageError, match="junction"):
            store.read_manifest_text()
        assert not state.exists()

    def test_mutation_time_junction_substitution_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dnd_assistant.storage.derived_state as ds

        store = _store(tmp_path)
        state = store.state_dir
        real_write = ds.atomic_write_text
        flags = {"junction": False}

        real_junction = pathlib.Path.is_junction

        def fake_junction(self: pathlib.Path) -> bool:
            if str(self) == str(state):
                return flags["junction"]
            return real_junction(self)

        monkeypatch.setattr(pathlib.Path, "is_junction", fake_junction)

        def hook(target, content, *, validator):
            result = real_write(target, content, validator=validator)
            if Path(target).name == _WORLD:
                # State/ becomes a junction immediately after the first artifact.
                flags["junction"] = True
            return result

        monkeypatch.setattr(ds, "atomic_write_text", hook)

        with pytest.raises(StorageError, match="junction"):
            store.publish(_texts(), _MANIFEST)
        # World State was written before the substitution; the next mutation-time
        # reauthorization fails closed, so Recently Touched and the manifest are
        # never written through the substituted parent.
        assert (state / _WORLD).exists()
        assert not (state / _TOUCHED).exists()
        assert not (state / MANIFEST_FILENAME).exists()

    def test_resolved_containment_rejection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        state = store.state_dir
        state.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        real_resolve = pathlib.Path.resolve

        def fake_resolve(self, *args: object, **kwargs: object) -> Path:
            if str(self) == str(state):
                return real_resolve(outside)
            return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(pathlib.Path, "resolve", fake_resolve)
        with pytest.raises(StorageError, match="outside the Vault root"):
            store.publish(_texts(), _MANIFEST)
        assert list(outside.iterdir()) == []

    def test_fileexists_race_branch_authorizes_winner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        state = store.state_dir
        real_mkdir = pathlib.Path.mkdir

        def racing_mkdir(self: pathlib.Path, *args: object, **kwargs: object) -> None:
            if str(self) == str(state):
                # The winner created a regular file where State should be.
                self.write_text("not a directory", encoding="utf-8")
                raise FileExistsError()
            return real_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(pathlib.Path, "mkdir", racing_mkdir)
        with pytest.raises(StorageError, match="not a directory"):
            store.publish(_texts(), _MANIFEST)


# ── Real Windows junction capability test ──────────────────────────────────


class TestRealWindowsJunction:
    def test_real_junction_state_rejected_and_no_escape(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        state = store.state_dir
        if not _make_junction(state, outside):
            pytest.skip("host cannot create a Windows directory junction")

        try:
            assert state.is_junction()
            assert not state.is_symlink()

            with pytest.raises(StorageError, match="junction"):
                store.read_manifest_text()
            with pytest.raises(StorageError, match="junction"):
                store.publish(_texts(), _MANIFEST)
            assert list(outside.iterdir()) == []
        finally:
            if state.is_junction():
                os.rmdir(state)

    def test_real_junction_redirect_inside_vault_still_rejected(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        inside_target = tmp_path / "vault" / "Inside State"
        inside_target.mkdir()
        state = store.state_dir
        if not _make_junction(state, inside_target):
            pytest.skip("host cannot create a Windows directory junction")

        try:
            # Containment alone would accept this (it resolves inside the Vault);
            # the junction check must still reject a redirecting object.
            with pytest.raises(StorageError, match="junction"):
                store.publish(_texts(), _MANIFEST)
            assert list(inside_target.iterdir()) == []
        finally:
            if state.is_junction():
                os.rmdir(state)

    def test_real_junction_at_artifact_leaf_rejected(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        state = store.state_dir
        state.mkdir()
        outside = tmp_path / "outside_leaf"
        outside.mkdir()
        leaf = state / _WORLD
        if not _make_junction(leaf, outside):
            pytest.skip("host cannot create a Windows directory junction")

        try:
            with pytest.raises(StorageError):
                store.read_artifact_bytes(CampaignStateArtifact.WORLD_STATE)
            with pytest.raises(StorageError):
                store.publish(_texts(), _MANIFEST)
        finally:
            if leaf.is_junction():
                os.rmdir(leaf)


# ── Hard-link semantics ────────────────────────────────────────────────────


class TestManagedLeafHardLink:
    def test_hard_linked_leaf_does_not_mutate_outside_inode(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        state = store.state_dir
        state.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("OUTSIDE ORIGINAL", encoding="utf-8")
        os.link(outside, state / _WORLD)

        store.publish(_texts(), _MANIFEST)

        # os.replace swaps the managed directory entry; the other hard-link name
        # keeps the original inode/content.  Hard links are therefore accepted.
        assert outside.read_text(encoding="utf-8") == "OUTSIDE ORIGINAL"
        managed = (state / _WORLD).read_text(encoding="utf-8")
        assert managed == _texts()[CampaignStateArtifact.WORLD_STATE]
        assert (state / MANIFEST_FILENAME).exists()


# ── Vault-root substitution parity (documented, not strengthened) ──────────


class TestVaultRootParity:
    def test_resolved_root_matches_canonical_resolution(self, tmp_path: Path) -> None:
        root = make_vault(tmp_path)
        store = ObsidianDerivedStateStore(root)
        # Same resolution contract as canonical storage (`_resolve_vault_root`).
        assert store.vault_root == root.resolve()

    def test_vault_root_vanished_fails_closed(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        shutil.rmtree(store.vault_root)
        with pytest.raises(StorageError, match="Vault root"):
            store.publish(_texts(), _MANIFEST)
