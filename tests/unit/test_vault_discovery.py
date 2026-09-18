"""S13-02 storage discovery tests: precondition, inventory, bounds, reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.vault_discovery import (
    DiscoveryIssueCode,
    DiscoveryLimits,
    ObsidianVaultSourceReader,
)
from dnd_assistant.storage.vault_initialization import serialize_new_campaign_config

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_vault(tmp_path: Path, campaign_id: str = "camp_test") -> Path:
    root = tmp_path / "Vault"
    (root / "_system").mkdir(parents=True)
    marker = root / "_system" / "campaign.yaml"
    marker.write_text(serialize_new_campaign_config(campaign_id), encoding="utf-8")
    return root


def _write_text(root: Path, relative: str, text: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_bytes(root: Path, relative: str, data: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _entry_paths(reader: ObsidianVaultSourceReader) -> set[str]:
    return {entry.relative_path for entry in reader.inventory().entries}


def _issue_codes(reader: ObsidianVaultSourceReader, relative: str) -> set[DiscoveryIssueCode]:
    return {issue.code for issue in reader.inventory().issues if issue.relative_path == relative}


def _case_sensitive_fs(tmp_path: Path) -> bool:
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    (probe / "a").write_text("x", encoding="utf-8")
    return not (probe / "A").exists()


def _try_symlink(source: Path, destination: Path, *, is_directory: bool = False) -> bool:
    try:
        os.symlink(source, destination, target_is_directory=is_directory)
        return True
    except (OSError, NotImplementedError):
        return False


# ── Initialization precondition ──────────────────────────────────────────────


class TestInitializedVaultPrecondition:
    def test_valid_marker_exposes_campaign_id(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path, campaign_id="camp_alpha")
        reader = ObsidianVaultSourceReader(root)
        assert reader.campaign_id == "camp_alpha"

    def test_missing_marker_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        with pytest.raises(StorageError, match="not initialized"):
            ObsidianVaultSourceReader(root)

    def test_invalid_marker_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        (root / "_system").mkdir(parents=True)
        (root / "_system" / "campaign.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        with pytest.raises(StorageError):
            ObsidianVaultSourceReader(root)

    def test_missing_root_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError):
            ObsidianVaultSourceReader(tmp_path / "missing")

    def test_file_root_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.write_text("not a directory", encoding="utf-8")
        with pytest.raises(StorageError):
            ObsidianVaultSourceReader(root)


# ── Inventory ────────────────────────────────────────────────────────────────


class TestInventory:
    def test_records_relative_posix_paths_and_extensions(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "Characters/NPCs/a.MD", "body")
        reader = ObsidianVaultSourceReader(root)
        entries = {e.relative_path: e for e in reader.inventory().entries}
        assert "Characters/NPCs/a.MD" in entries
        assert entries["Characters/NPCs/a.MD"].extension == ".md"
        assert entries["Characters/NPCs/a.MD"].size_bytes == 4

    def test_architectural_exclusions_are_absent(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, ".obsidian/app.json", "{}")
        _write_text(root, ".git/config", "x")
        _write_text(root, ".hidden/note.md", "x")
        _write_text(root, ".DS_Store", "x")
        _write_text(root, "Thumbs.db", "x")
        _write_text(root, "desktop.ini", "x")
        _write_text(root, "a.tmp", "x")
        _write_text(root, "a.swp", "x")
        _write_text(root, "a.bak", "x")
        _write_text(root, "~a.md", "x")
        _write_text(root, "a~", "x")
        _write_text(root, "keep.md", "x")
        paths = _entry_paths(ObsidianVaultSourceReader(root))
        assert "keep.md" in paths
        for excluded in (
            ".obsidian/app.json",
            ".git/config",
            ".hidden/note.md",
            ".DS_Store",
            "Thumbs.db",
            "desktop.ini",
            "a.tmp",
            "a.swp",
            "a.bak",
            "~a.md",
            "a~",
        ):
            assert excluded not in paths

    def test_known_hidden_state_manifest_is_not_blanket_excluded(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "State/.campaign-state-manifest.json", "{}")
        assert "State/.campaign-state-manifest.json" in _entry_paths(
            ObsidianVaultSourceReader(root)
        )

    def test_case_alias_issue_detected_on_case_sensitive_fs(self, tmp_path: Path) -> None:
        if not _case_sensitive_fs(tmp_path):
            pytest.skip("case-insensitive filesystem")
        root = _make_vault(tmp_path)
        _write_text(root, "Dup.md", "a")
        _write_text(root, "dup.md", "b")
        reader = ObsidianVaultSourceReader(root)
        issues = reader.inventory().issues
        assert {i.relative_path for i in issues if i.code is DiscoveryIssueCode.CASE_ALIAS} == {
            "Dup.md",
            "dup.md",
        }

    def test_deterministic_order_including_cyrillic(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        for name in ["Я.md", "б.md", "B.md", "a.md", "Ё.md"]:
            _write_text(root, name, "x")
        first = [e.relative_path for e in ObsidianVaultSourceReader(root).inventory().entries]
        second = [e.relative_path for e in ObsidianVaultSourceReader(root).inventory().entries]
        assert first == second
        assert first == sorted(first, key=lambda p: (p.casefold(), p))


# ── Bounds ───────────────────────────────────────────────────────────────────


class TestInventoryBounds:
    def test_entry_limit_is_fatal_with_no_partial_result(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        for index in range(3):
            _write_text(root, f"note{index}.md", "x")
        reader = ObsidianVaultSourceReader(root, DiscoveryLimits(max_inventory_entries=2))
        with pytest.raises(StorageError, match="exceeded"):
            reader.inventory()

    def test_depth_limit_isolates_deep_subtree(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "a/b/c/d/deep.md", "x")
        _write_text(root, "shallow.md", "x")
        reader = ObsidianVaultSourceReader(root, DiscoveryLimits(max_depth=2))
        result = reader.inventory()
        paths = {e.relative_path for e in result.entries}
        assert "shallow.md" in paths
        assert "a/b/c/d/deep.md" not in paths
        assert any(i.code is DiscoveryIssueCode.DEPTH_LIMIT for i in result.issues)

    def test_entry_limit_at_exact_bound_passes(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "a.md", "x")
        _write_text(root, "b.md", "x")
        default_count = len(ObsidianVaultSourceReader(root).inventory().entries)
        reader = ObsidianVaultSourceReader(
            root, DiscoveryLimits(max_inventory_entries=default_count)
        )
        assert len(reader.inventory().entries) == default_count

    def test_depth_limit_at_exact_bound_includes_file(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "a/b.md", "x")
        reader = ObsidianVaultSourceReader(root, DiscoveryLimits(max_depth=2))
        assert "a/b.md" in {e.relative_path for e in reader.inventory().entries}


# ── Bounded reads ────────────────────────────────────────────────────────────


class TestBoundedReads:
    def test_reads_exact_utf8_preserving_newlines(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_bytes(root, "Note.md", b"line1\r\nline2\n")
        result = ObsidianVaultSourceReader(root).read_text("Note.md")
        assert result.issue is None
        assert result.text == "line1\r\nline2\n"

    def test_invalid_utf8_is_isolated(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_bytes(root, "bad.md", b"\xff\xfe\x00\x81")
        result = ObsidianVaultSourceReader(root).read_text("bad.md")
        assert result.text is None
        assert result.issue is not None
        assert result.issue.code is DiscoveryIssueCode.INVALID_UTF8

    def test_oversize_source_is_skipped(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "big.txt", "0123456789")
        reader = ObsidianVaultSourceReader(root, DiscoveryLimits(max_content_file_bytes=4))
        result = reader.read_text("big.txt")
        assert result.text is None
        assert result.issue is not None
        assert result.issue.code is DiscoveryIssueCode.SKIPPED_OVERSIZE

    def test_disappeared_source_reported(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        path = _write_text(root, "gone.md", "x")
        reader = ObsidianVaultSourceReader(root)
        path.unlink()
        result = reader.read_text("gone.md")
        assert result.issue is not None
        assert result.issue.code is DiscoveryIssueCode.DISAPPEARED

    @pytest.mark.parametrize(
        "unsafe",
        ["../outside.md", "/etc/passwd", "a\\b.md", "a/../b.md", "", "a//b.md"],
    )
    def test_traversal_and_absolute_paths_rejected(self, tmp_path: Path, unsafe: str) -> None:
        root = _make_vault(tmp_path)
        result = ObsidianVaultSourceReader(root).read_text(unsafe)
        assert result.text is None
        assert result.issue is not None
        assert result.issue.code is DiscoveryIssueCode.UNSAFE_REDIRECT


# ── Symlink / redirect safety ────────────────────────────────────────────────


class TestRedirectSafety:
    def test_symlinked_file_not_followed(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        link = root / "link.md"
        if not _try_symlink(outside, link):
            pytest.skip("symlink capability unavailable")
        reader = ObsidianVaultSourceReader(root)
        assert "link.md" not in _entry_paths(reader)
        assert DiscoveryIssueCode.UNSAFE_REDIRECT in _issue_codes(reader, "link.md")
        result = reader.read_text("link.md")
        assert result.text is None
        assert result.issue is not None
        assert result.issue.code is DiscoveryIssueCode.UNSAFE_REDIRECT

    def test_symlinked_directory_not_descended(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "secret.md").write_text("secret", encoding="utf-8")
        link = root / "linked"
        if not _try_symlink(outside_dir, link, is_directory=True):
            pytest.skip("directory symlink capability unavailable")
        reader = ObsidianVaultSourceReader(root)
        assert "linked/secret.md" not in _entry_paths(reader)
        assert DiscoveryIssueCode.UNSAFE_REDIRECT in _issue_codes(reader, "linked")

    def test_dangling_symlink_is_safe_and_reported(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        link = root / "dangling.md"
        if not _try_symlink(tmp_path / "missing-target.md", link):
            pytest.skip("symlink capability unavailable")
        reader = ObsidianVaultSourceReader(root)
        assert "dangling.md" not in _entry_paths(reader)
        assert DiscoveryIssueCode.UNSAFE_REDIRECT in _issue_codes(reader, "dangling.md")

    def test_no_read_outside_vault_through_symlink(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("top secret", encoding="utf-8")
        link = root / "escape.md"
        if not _try_symlink(outside, link):
            pytest.skip("symlink capability unavailable")
        reader = ObsidianVaultSourceReader(root)
        # Discovery never yields the link; any direct read fails closed.
        result = reader.read_text("escape.md")
        assert result.text is None
        assert result.text != "top secret"

    def test_junction_branch_covered_without_os_capability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "linked/inside.md", "x")
        _write_text(root, "normal.md", "x")
        reader = ObsidianVaultSourceReader(root)
        junction_target = reader.vault_root / "linked"
        monkeypatch.setattr(Path, "is_junction", lambda self: self == junction_target)

        result = reader.inventory()
        paths = {e.relative_path for e in result.entries}
        assert "linked/inside.md" not in paths
        assert "normal.md" in paths
        assert any(
            i.relative_path == "linked" and i.code is DiscoveryIssueCode.UNSAFE_REDIRECT
            for i in result.issues
        )
