"""S13-02 application discovery policy tests: classification, report, service."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    FrontmatterStatus,
    SourceClass,
    VaultDiscoveryService,
    classify_source,
    probe_frontmatter,
)
from dnd_assistant.storage.vault_discovery import (
    DiscoveryIssue,
    DiscoveryIssueCode,
    DiscoveryLimits,
    InventoryEntry,
    SourceReadResult,
    VaultSourceInventory,
)

# ── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("Characters/NPCs/a.md", SourceClass.ENTITY_CANDIDATE),
        ("Locations/x.markdown", SourceClass.ENTITY_CANDIDATE),
        ("Quests/q.txt", SourceClass.ENTITY_CANDIDATE),
        ("Items/i.json", SourceClass.ENTITY_CANDIDATE),
        ("Sessions/S001/Session.md", SourceClass.SESSION_SOURCE),
        ("Campaign/Overview.md", SourceClass.USER_SOURCE),
        ("Events/event_1.md", SourceClass.USER_SOURCE),
        ("State/Active Quests.md", SourceClass.USER_SOURCE),
        ("State/World State.md", SourceClass.DERIVED),
        ("State/Recently Touched.md", SourceClass.DERIVED),
        ("State/.campaign-state-manifest.json", SourceClass.DERIVED),
        ("_system/campaign.yaml", SourceClass.APPLICATION_CONFIG),
        ("_system/world_time.json", SourceClass.APPLICATION_CONFIG),
        ("_system/raw/sessions/S001/events.jsonl", SourceClass.APPLICATION_RAW),
        ("_system/audit/audit.jsonl", SourceClass.APPLICATION_CONTROL),
        ("_system/changesets/x.proposal.json", SourceClass.APPLICATION_CONTROL),
        ("_system/migrations/note.md", SourceClass.APPLICATION_CONTROL),
        ("_system/indexes/entities.sqlite3", SourceClass.DERIVED),
        ("_system/cache/blob", SourceClass.DERIVED),
        ("_system/traces/trace.json", SourceClass.DERIVED),
        ("_system/other.json", SourceClass.APPLICATION_CONTROL),
        ("Characters/NPCs/map.png", SourceClass.UNSUPPORTED),
        ("Factions/logo.png", SourceClass.UNSUPPORTED),
        ("notes.weird", SourceClass.UNSUPPORTED),
    ],
)
def test_classify_source(relative_path: str, expected: SourceClass) -> None:
    assert classify_source(relative_path) is expected


# ── Frontmatter probe ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", FrontmatterStatus.ABSENT),
        ("# Body only\n", FrontmatterStatus.ABSENT),
        ("---\nkey: value\n---\nbody", FrontmatterStatus.PRESENT),
        ("---\nkey: [invalid, unclosed\n---\nbody", FrontmatterStatus.PRESENT),
        ("---\r\nkey: 1\r\n---\r\nbody", FrontmatterStatus.PRESENT),
        ("\ufeff---\nkey: 1\n---\n", FrontmatterStatus.PRESENT),
        ("---\nkey: value\n", FrontmatterStatus.UNTERMINATED),
        ("---\n", FrontmatterStatus.UNTERMINATED),
    ],
)
def test_probe_frontmatter(text: str, expected: FrontmatterStatus) -> None:
    assert probe_frontmatter(text) is expected


# ── Fake reader ──────────────────────────────────────────────────────────────


class _FakeReader:
    def __init__(
        self,
        entries: list[InventoryEntry],
        contents: Mapping[str, str | SourceReadResult],
        *,
        campaign_id: str = "camp_fake",
        issues: tuple[DiscoveryIssue, ...] = (),
        limits: DiscoveryLimits | None = None,
    ) -> None:
        self._entries = entries
        self._contents = contents
        self._campaign_id = campaign_id
        self._issues = issues
        self._limits = limits if limits is not None else DiscoveryLimits()

    @property
    def campaign_id(self) -> str:
        return self._campaign_id

    @property
    def limits(self) -> DiscoveryLimits:
        return self._limits

    def inventory(self) -> VaultSourceInventory:
        return VaultSourceInventory(
            campaign_id=self._campaign_id,
            entries=tuple(self._entries),
            issues=self._issues,
        )

    def read_text(self, relative_path: str) -> SourceReadResult:
        value = self._contents[relative_path]
        if isinstance(value, SourceReadResult):
            return value
        return SourceReadResult(value, None)


def _entry(relative_path: str, size: int = 4, extension: str = ".md") -> InventoryEntry:
    return InventoryEntry(relative_path=relative_path, extension=extension, size_bytes=size)


# ── Service behaviour ────────────────────────────────────────────────────────


def test_service_reads_eligible_and_leaves_application_owned_unread() -> None:
    entries = [
        _entry("Characters/NPCs/a.md"),
        _entry("Sessions/S001/Session.md"),
        _entry("Campaign/Overview.md"),
        _entry("_system/raw/sessions/S001/events.jsonl", extension=".jsonl"),
        _entry("_system/campaign.yaml", extension=".yaml"),
        _entry("State/World State.md"),
        _entry("Factions/logo.png", extension=".png"),
    ]
    contents = {
        "Characters/NPCs/a.md": "---\nid: npc_a\n---\nbody",
        "Sessions/S001/Session.md": "# Session\n",
        "Campaign/Overview.md": "# Overview\n",
    }
    report = VaultDiscoveryService(_FakeReader(entries, contents)).run()
    by_path = {e.relative_path: e for e in report.entries}

    assert by_path["Characters/NPCs/a.md"].content_status is ContentReadStatus.READ
    assert by_path["Characters/NPCs/a.md"].source_class is SourceClass.ENTITY_CANDIDATE
    assert by_path["Characters/NPCs/a.md"].frontmatter_status is FrontmatterStatus.PRESENT
    assert by_path["Sessions/S001/Session.md"].source_class is SourceClass.SESSION_SOURCE
    assert by_path["Campaign/Overview.md"].source_class is SourceClass.USER_SOURCE

    for path in (
        "_system/raw/sessions/S001/events.jsonl",
        "_system/campaign.yaml",
        "State/World State.md",
        "Factions/logo.png",
    ):
        assert by_path[path].content_status is ContentReadStatus.NOT_ELIGIBLE
        assert by_path[path].content_text is None
        assert by_path[path].frontmatter_status is FrontmatterStatus.NOT_EVALUATED


def test_frontmatter_probe_only_for_markdown() -> None:
    entries = [_entry("Campaign/data.json", extension=".json")]
    report = VaultDiscoveryService(_FakeReader(entries, {"Campaign/data.json": "---\n---\n"})).run()
    assert report.entries[0].content_status is ContentReadStatus.READ
    assert report.entries[0].frontmatter_status is FrontmatterStatus.NOT_EVALUATED


def test_failed_read_is_isolated_and_scan_continues() -> None:
    entries = [_entry("a.md"), _entry("b.md")]
    contents = {
        "a.md": SourceReadResult(None, DiscoveryIssue("a.md", DiscoveryIssueCode.INVALID_UTF8)),
        "b.md": "ok",
    }
    report = VaultDiscoveryService(_FakeReader(entries, contents)).run()
    by_path = {e.relative_path: e for e in report.entries}
    assert by_path["a.md"].content_status is ContentReadStatus.FAILED
    assert by_path["b.md"].content_status is ContentReadStatus.READ
    assert any(i.code is DiscoveryIssueCode.INVALID_UTF8 for i in report.issues)


def test_aggregate_limit_skips_deterministically() -> None:
    entries = [_entry("a.md", size=4), _entry("b.md", size=4), _entry("c.md", size=4)]
    contents = {"a.md": "aaaa", "b.md": "bbbb", "c.md": "cccc"}
    limits = DiscoveryLimits(max_total_content_bytes=8)
    report = VaultDiscoveryService(_FakeReader(entries, contents, limits=limits)).run()
    by_path = {e.relative_path: e for e in report.entries}
    assert by_path["a.md"].content_status is ContentReadStatus.READ
    assert by_path["b.md"].content_status is ContentReadStatus.READ
    assert by_path["c.md"].content_status is ContentReadStatus.SKIPPED
    assert any(i.code is DiscoveryIssueCode.AGGREGATE_LIMIT for i in report.issues)


def test_aggregate_limit_at_exact_bound_reads_all() -> None:
    entries = [_entry("a.md", size=4), _entry("b.md", size=4)]
    contents = {"a.md": "aaaa", "b.md": "bbbb"}
    limits = DiscoveryLimits(max_total_content_bytes=8)
    report = VaultDiscoveryService(_FakeReader(entries, contents, limits=limits)).run()
    assert all(entry.content_status is ContentReadStatus.READ for entry in report.entries)


def test_report_is_campaign_identified_and_ordered() -> None:
    entries = [_entry("z.md"), _entry("A.md"), _entry("б.md")]
    contents = {"z.md": "z", "A.md": "a", "б.md": "b"}
    report = VaultDiscoveryService(_FakeReader(entries, contents, campaign_id="camp_x")).run()
    assert report.campaign_id == "camp_x"
    paths = [e.relative_path for e in report.entries]
    assert paths == sorted(paths, key=lambda p: (p.casefold(), p))


def test_report_preserves_inventory_issues() -> None:
    injected = DiscoveryIssue("weird", DiscoveryIssueCode.UNSAFE_REDIRECT)
    report = VaultDiscoveryService(_FakeReader([], {}, issues=(injected,))).run()
    assert injected in report.issues
