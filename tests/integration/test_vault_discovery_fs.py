"""S13-02 integration tests over real filesystem Vaults.

Uses copied golden-Vault fixtures and purpose-built temporary Vaults.  The
repository golden fixture is never mutated in place.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    DiscoveredSource,
    FrontmatterStatus,
    SourceClass,
    VaultDiscoveryReport,
    VaultDiscoveryService,
)
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.vault_discovery import (
    DiscoveryIssueCode,
    DiscoveryLimits,
    ObsidianVaultSourceReader,
)
from dnd_assistant.storage.vault_initialization import serialize_new_campaign_config

GOLDEN_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "golden_test_vault"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_vault(tmp_path: Path, campaign_id: str = "camp_it") -> Path:
    root = tmp_path / "Vault"
    (root / "_system").mkdir(parents=True)
    (root / "_system" / "campaign.yaml").write_text(
        serialize_new_campaign_config(campaign_id), encoding="utf-8"
    )
    return root


def _write_text(root: Path, relative: str, text: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _tree_snapshot(root: Path) -> dict[str, tuple[str, str | None, int | None]]:
    snapshot: dict[str, tuple[str, str | None, int | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative] = ("dir", None, path.stat().st_mtime_ns)
        elif path.is_file():
            info = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[relative] = ("file", digest, info.st_mtime_ns)
    return snapshot


def _run(root: Path, limits: DiscoveryLimits | None = None) -> VaultDiscoveryReport:
    reader = ObsidianVaultSourceReader(root, limits)
    return VaultDiscoveryService(reader).run()


def _by_path(report: VaultDiscoveryReport) -> dict[str, DiscoveredSource]:
    return {entry.relative_path: entry for entry in report.entries}


def _try_junction(target: Path, link: Path) -> bool:
    """Attempt to create a directory junction/symlink; return success."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0 and link.exists()
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


# ── Golden Vault ─────────────────────────────────────────────────────────────


class TestGoldenVaultDiscovery:
    def test_classifies_known_golden_material(self, tmp_path: Path) -> None:
        root = tmp_path / "golden"
        shutil.copytree(GOLDEN_VAULT, root)
        report = _run(root)
        entries = _by_path(report)

        assert report.campaign_id == "camp_golden_001"

        npc = entries["Characters/NPCs/01-npc_varos.md"]
        assert npc.source_class is SourceClass.ENTITY_CANDIDATE
        assert npc.content_status is ContentReadStatus.READ
        assert npc.frontmatter_status is FrontmatterStatus.PRESENT
        assert npc.content_text is not None and "npc_varos" in npc.content_text

        session = entries["Sessions/S001/Session.md"]
        assert session.source_class is SourceClass.SESSION_SOURCE
        assert session.content_status is ContentReadStatus.READ
        assert session.frontmatter_status is FrontmatterStatus.PRESENT

        overview = entries["Campaign/Overview.md"]
        assert overview.source_class is SourceClass.USER_SOURCE
        assert overview.frontmatter_status is FrontmatterStatus.ABSENT

        raw = entries["_system/raw/sessions/S001/events.jsonl"]
        assert raw.source_class is SourceClass.APPLICATION_RAW
        assert raw.content_status is ContentReadStatus.NOT_ELIGIBLE
        assert raw.content_text is None

        marker = entries["_system/campaign.yaml"]
        assert marker.source_class is SourceClass.APPLICATION_CONFIG
        assert marker.content_status is ContentReadStatus.NOT_ELIGIBLE

        # Legacy user-authored State pages are user source, not current derived.
        assert entries["State/Active Quests.md"].source_class is SourceClass.USER_SOURCE

    def test_report_contains_no_absolute_paths(self, tmp_path: Path) -> None:
        root = tmp_path / "golden"
        shutil.copytree(GOLDEN_VAULT, root)
        report = _run(root)
        for entry in report.entries:
            assert not Path(entry.relative_path).is_absolute()
            assert "\\" not in entry.relative_path


# ── Zero-write evidence ──────────────────────────────────────────────────────


class TestZeroWrite:
    def test_discovery_leaves_vault_bytes_and_mtimes_unchanged(self, tmp_path: Path) -> None:
        root = tmp_path / "golden"
        shutil.copytree(GOLDEN_VAULT, root)
        audit_path = root / "_system" / "audit" / "audit.jsonl"
        before_tree = _tree_snapshot(root)
        before_audit = audit_path.read_bytes()

        report = _run(root)
        assert report.entries

        assert _tree_snapshot(root) == before_tree
        assert audit_path.read_bytes() == before_audit

    def test_discovery_creates_no_new_paths(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "note.md", "x")
        before = set(_tree_snapshot(root))
        _run(root)
        assert set(_tree_snapshot(root)) == before


# ── Fault isolation ──────────────────────────────────────────────────────────


class TestFaultIsolation:
    def test_invalid_utf8_is_isolated_and_scan_continues(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "good.md", "# good\n")
        (root / "bad.md").write_bytes(b"\xff\xfe\x00\x81")
        report = _run(root)
        entries = _by_path(report)
        assert entries["good.md"].content_status is ContentReadStatus.READ
        assert entries["bad.md"].content_status is ContentReadStatus.FAILED
        assert any(i.code is DiscoveryIssueCode.INVALID_UTF8 for i in report.issues)

    def test_binary_and_unknown_extensions_are_inventory_only(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")
        _write_text(root, "archive.weird", "data")
        report = _run(root)
        entries = _by_path(report)
        for name in ("image.png", "archive.weird"):
            assert entries[name].source_class is SourceClass.UNSUPPORTED
            assert entries[name].content_status is ContentReadStatus.NOT_ELIGIBLE
            assert entries[name].content_text is None

    def test_unterminated_frontmatter_is_structural_not_yaml_failure(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "broken.md", "---\nkey: [unclosed\nno closing delimiter\n")
        report = _run(root)
        entry = _by_path(report)["broken.md"]
        assert entry.content_status is ContentReadStatus.READ
        assert entry.frontmatter_status is FrontmatterStatus.UNTERMINATED

    def test_invalid_yaml_with_valid_delimiters_remains_present(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "malformed.md", "---\n\t*: : :\n---\nbody\n")
        entry = _by_path(_run(root))["malformed.md"]
        assert entry.frontmatter_status is FrontmatterStatus.PRESENT


# ── Symlink / junction / outside-Vault safety ────────────────────────────────


class TestFilesystemRedirectSafety:
    def test_symlink_is_not_followed_and_secret_never_read(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        secret = tmp_path / "outside-secret.md"
        secret.write_text("TOP_SECRET", encoding="utf-8")
        link = root / "escape.md"
        try:
            os.symlink(secret, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink capability unavailable")

        report = _run(root)
        assert all(entry.content_text != "TOP_SECRET" for entry in report.entries)
        assert "escape.md" not in _by_path(report)
        assert any(
            i.relative_path == "escape.md" and i.code is DiscoveryIssueCode.UNSAFE_REDIRECT
            for i in report.issues
        )

    def test_directory_junction_is_not_descended(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        outside = tmp_path / "outside-dir"
        outside.mkdir()
        (outside / "secret.md").write_text("TOP_SECRET", encoding="utf-8")
        link = root / "linked"
        if not _try_junction(outside, link):
            pytest.skip("junction/symlink capability unavailable")

        report = _run(root)
        assert "linked/secret.md" not in _by_path(report)
        assert any(
            i.relative_path == "linked" and i.code is DiscoveryIssueCode.UNSAFE_REDIRECT
            for i in report.issues
        )
        assert all(entry.content_text != "TOP_SECRET" for entry in report.entries)


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_two_runs_are_equal_with_mixed_case_and_cyrillic(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        for name in ["Я.md", "б.md", "B.md", "a.md", "Campaign/Ёж.md", "Characters/NPCs/Ёж.md"]:
            _write_text(root, name, "x")
        first = _run(root)
        second = _run(root)
        assert first == second
        paths = [entry.relative_path for entry in first.entries]
        assert paths == sorted(paths, key=lambda p: (p.casefold(), p))


# ── Resource bounds ──────────────────────────────────────────────────────────


class TestResourceBounds:
    def test_entry_overflow_is_fatal_with_no_partial_report(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        for index in range(6):
            _write_text(root, f"note{index}.md", "x")
        reader = ObsidianVaultSourceReader(root, DiscoveryLimits(max_inventory_entries=3))
        service = VaultDiscoveryService(reader)
        with pytest.raises(StorageError, match="exceeded"):
            service.run()

    def test_aggregate_limit_marks_remaining_sources_skipped(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "a.md", "aaaa")
        _write_text(root, "b.md", "bbbb")
        report = _run(root, DiscoveryLimits(max_total_content_bytes=4))
        statuses = {entry.content_status for entry in report.entries if entry.extension == ".md"}
        assert ContentReadStatus.SKIPPED in statuses
        assert any(i.code is DiscoveryIssueCode.AGGREGATE_LIMIT for i in report.issues)

    def test_per_file_oversize_is_skipped_without_failure(self, tmp_path: Path) -> None:
        root = _make_vault(tmp_path)
        _write_text(root, "big.txt", "0123456789")
        report = _run(root, DiscoveryLimits(max_content_file_bytes=4))
        entry = _by_path(report)["big.txt"]
        assert entry.content_status is ContentReadStatus.SKIPPED
        assert any(i.code is DiscoveryIssueCode.SKIPPED_OVERSIZE for i in report.issues)
