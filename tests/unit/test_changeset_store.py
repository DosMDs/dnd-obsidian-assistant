"""Unit tests for the S10-05 Vault-backed ChangeSet artifact store.

Covers exclusive create, exact reads, conflict/missing semantics, path-component
safety (traversal, separators, Windows-invalid/reserved/trailing names), symlink
rejection, namespace containment and deterministic filenames.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dnd_assistant.errors import ConflictError, NotFoundError, StorageError
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore

PROPOSAL_TEXT = '{"hello":"proposal"}\n'
APPROVAL_TEXT = '{"hello":"approval"}\n'


def _make_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


def _can_symlink(tmp_path: Path, target: Path, link: Path, *, is_dir: bool) -> bool:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
        return True
    except (OSError, NotImplementedError):
        return False


# ── Composition / topology ─────────────────────────────────────────────────


class TestConstruction:
    def test_missing_vault_root(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError):
            ObsidianChangeSetStore(tmp_path / "does-not-exist")

    def test_missing_system_dir(self, tmp_path: Path) -> None:
        root = tmp_path / "vault"
        root.mkdir()
        with pytest.raises(StorageError):
            ObsidianChangeSetStore(root)

    def test_valid_vault(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        store = ObsidianChangeSetStore(root)
        assert store.vault_root == root.resolve(strict=False)
        assert store.changesets_dir == root / "_system" / "changesets"


# ── Proposal create/read ───────────────────────────────────────────────────


class TestProposalArtifacts:
    def test_exclusive_create_then_exact_read(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))

        store.create_proposal("cs-1", PROPOSAL_TEXT)

        assert store.read_proposal("cs-1") == PROPOSAL_TEXT
        assert store.read_proposal_if_present("cs-1") == PROPOSAL_TEXT

    def test_duplicate_create_conflicts(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))
        store.create_proposal("cs-1", PROPOSAL_TEXT)

        with pytest.raises(ConflictError):
            store.create_proposal("cs-1", PROPOSAL_TEXT)

        assert store.read_proposal("cs-1") == PROPOSAL_TEXT

    def test_read_if_present_absent_is_none(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))
        assert store.read_proposal_if_present("cs-missing") is None

    def test_missing_required_read_raises(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))
        with pytest.raises(NotFoundError):
            store.read_proposal("cs-missing")

    def test_deterministic_filename(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        store = ObsidianChangeSetStore(root)
        store.create_proposal("cs-1", PROPOSAL_TEXT)

        assert (root / "_system" / "changesets" / "cs-1.proposal.json").is_file()


# ── Approval create/read ───────────────────────────────────────────────────


class TestApprovalArtifacts:
    def test_exclusive_create_then_exact_read(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))

        store.create_approval("cs-1", APPROVAL_TEXT)

        assert store.read_approval("cs-1") == APPROVAL_TEXT
        assert store.read_approval_if_present("cs-1") == APPROVAL_TEXT
        assert store.read_proposal_if_present("cs-1") is None

    def test_duplicate_create_conflicts(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))
        store.create_approval("cs-1", APPROVAL_TEXT)

        with pytest.raises(ConflictError):
            store.create_approval("cs-1", APPROVAL_TEXT)

        assert store.read_approval("cs-1") == APPROVAL_TEXT

    def test_read_if_present_absent_is_none(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))
        assert store.read_approval_if_present("cs-missing") is None

    def test_missing_required_read_raises(self, tmp_path: Path) -> None:
        store = ObsidianChangeSetStore(_make_vault(tmp_path))
        with pytest.raises(NotFoundError):
            store.read_approval("cs-missing")

    def test_deterministic_filename(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        store = ObsidianChangeSetStore(root)
        store.create_approval("cs-1", APPROVAL_TEXT)

        assert (root / "_system" / "changesets" / "cs-1.approval.json").is_file()


# ── Path-component safety ──────────────────────────────────────────────────


UNSAFE_IDS = [
    pytest.param("../escape", id="traversal"),
    pytest.param("..", id="dotdot"),
    pytest.param(".", id="dot"),
    pytest.param("a/b", id="forward-slash"),
    pytest.param("a\\b", id="backslash"),
    pytest.param("con", id="windows-reserved-con"),
    pytest.param("NUL.json", id="windows-reserved-nul"),
    pytest.param("a:b", id="windows-invalid-colon"),
    pytest.param("a?b", id="windows-invalid-question"),
    pytest.param("trailing.", id="trailing-dot"),
    pytest.param("trailing ", id="trailing-space"),
    pytest.param(" lead", id="leading-space"),
]


class TestPathSafety:
    @pytest.mark.parametrize("unsafe_id", UNSAFE_IDS)
    def test_unsafe_id_rejected_and_no_artifact_created(
        self, tmp_path: Path, unsafe_id: str
    ) -> None:
        root = _make_vault(tmp_path)
        store = ObsidianChangeSetStore(root)
        changesets = root / "_system" / "changesets"

        with pytest.raises(StorageError):
            store.create_proposal(unsafe_id, PROPOSAL_TEXT)
        with pytest.raises(StorageError):
            store.create_approval(unsafe_id, APPROVAL_TEXT)

        existing = sorted(changesets.iterdir()) if changesets.exists() else []
        assert existing == []

    def test_artifact_stays_inside_namespace(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        store = ObsidianChangeSetStore(root)
        store.create_proposal("cs-1", PROPOSAL_TEXT)

        artifact = root / "_system" / "changesets" / "cs-1.proposal.json"
        assert artifact.is_file()
        assert artifact.resolve(strict=False).parent == store.changesets_dir.resolve(strict=False)

    def test_symlink_component_rejected(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        real = tmp_path / "real-changesets"
        real.mkdir()
        if not _can_symlink(tmp_path, real, root / "_system" / "changesets", is_dir=True):
            pytest.skip("symlink not supported")

        with pytest.raises(StorageError):
            ObsidianChangeSetStore(root)

    def test_symlink_artifact_leaf_rejected(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        store = ObsidianChangeSetStore(root)
        changesets = root / "_system" / "changesets"
        changesets.mkdir()
        target = tmp_path / "outside.json"
        target.write_text("{}", encoding="utf-8")
        if not _can_symlink(tmp_path, target, changesets / "cs-1.proposal.json", is_dir=False):
            pytest.skip("symlink not supported")

        with pytest.raises(StorageError):
            store.create_proposal("cs-1", PROPOSAL_TEXT)
        with pytest.raises(StorageError):
            store.read_proposal("cs-1")
