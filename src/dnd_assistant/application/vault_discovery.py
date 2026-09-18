"""S13-02 existing-Vault discovery application policy.

This module owns the deterministic, filesystem-free classification and report
contract for discovering existing campaign source material.  It consumes the
trusted read-only storage capability and never opens, reads or parses Vault
files itself.

Boundaries
==========

- The initialized-Vault precondition and campaign identity are validated by the
  storage capability using the S13-01 campaign-config contract; this module
  only consumes the validated ``campaign_id``.
- Path/source classification is **not** semantic or canonical validation.  A
  file under a managed entity directory is an :attr:`SourceClass.ENTITY_CANDIDATE`,
  not a proven canonical ``Entity``.  Canonical Entity validation remains owned
  by the existing repository/mapping contract.
- The accepted source extensions are opaque bounded text containers only; no
  JSON/YAML/CSV/HTML parser runs here.
- The discovery result is ephemeral.  It is returned to the caller (S13-03) as
  bounded text plus metadata; the caller receives no filesystem authority.

This module belongs to the application layer and must not import from:
    cli, models, tools, retrieval, ollama, pydantic_ai, textual.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.storage.derived_state import ARTIFACT_FILENAMES, MANIFEST_FILENAME
from dnd_assistant.storage.types import EntityDirectory
from dnd_assistant.storage.vault_discovery import (
    DiscoveryIssue,
    DiscoveryIssueCode,
    VaultSourceReader,
)

# ── Source extension policy ──────────────────────────────────────────────────

TEXT_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".csv",
        ".html",
        ".htm",
    }
)
"""Accepted opaque UTF-8 text containers (no semantic parser is applied)."""

_MARKDOWN_SOURCE_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown"})

_ENTITY_PREFIXES: tuple[tuple[str, ...], ...] = tuple(
    tuple(directory.value.split("/")) for directory in EntityDirectory
)
"""Canonical entity-directory prefixes from the storage-owned mapping."""

_DERIVED_STATE_LEAVES: frozenset[str] = frozenset(ARTIFACT_FILENAMES.values()) | {MANIFEST_FILENAME}
"""Physical Campaign State leaves owned by ``storage.derived_state``."""

_APPLICATION_CONTROL_NAMESPACES: frozenset[str] = frozenset({"audit", "changesets", "migrations"})
_APPLICATION_DERIVED_NAMESPACES: frozenset[str] = frozenset({"indexes", "cache", "traces"})


# ── Enumerations ─────────────────────────────────────────────────────────────


class SourceClass(StrEnum):
    """Path-based source classification (never canonical validation)."""

    ENTITY_CANDIDATE = "entity_candidate"
    """Text source in a managed entity directory; NOT a validated Entity."""

    SESSION_SOURCE = "session_source"
    """Text source under the canonical ``Sessions/`` tree."""

    USER_SOURCE = "user_source"
    """Arbitrary user-authored text source outside managed namespaces."""

    APPLICATION_CONFIG = "application_config"
    """Application configuration (``_system/campaign.yaml``, world time)."""

    APPLICATION_RAW = "application_raw"
    """Application-owned raw session evidence (``_system/raw/``)."""

    APPLICATION_CONTROL = "application_control"
    """Application workflow/control state (audit, ChangeSets, migrations)."""

    DERIVED = "derived"
    """Rebuildable derived application output (indexes, cache, Campaign State)."""

    UNSUPPORTED = "unsupported"
    """Binary/unknown material: inventoried but never content-read."""


class ContentReadStatus(StrEnum):
    """Outcome of the bounded content phase for one inventoried source."""

    READ = "read"
    NOT_ELIGIBLE = "not_eligible"
    SKIPPED = "skipped"
    FAILED = "failed"


class FrontmatterStatus(StrEnum):
    """Structural frontmatter probe result; never YAML validation."""

    ABSENT = "absent"
    PRESENT = "present"
    UNTERMINATED = "unterminated"
    NOT_EVALUATED = "not_evaluated"


_ELIGIBLE_SOURCE_CLASSES: frozenset[SourceClass] = frozenset(
    {SourceClass.ENTITY_CANDIDATE, SourceClass.SESSION_SOURCE, SourceClass.USER_SOURCE}
)


# ── Report types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    """One discovered source with its bounded, ephemeral content state."""

    relative_path: str
    source_class: SourceClass
    extension: str
    size_bytes: int
    content_status: ContentReadStatus
    frontmatter_status: FrontmatterStatus
    content_text: str | None


@dataclass(frozen=True, slots=True)
class VaultDiscoveryReport:
    """Deterministic, ordered, ephemeral discovery result for S13-03.

    The report carries Vault-relative POSIX paths, classification metadata and
    bounded text only.  It carries no absolute filesystem path and grants no
    filesystem traversal authority.
    """

    campaign_id: str
    entries: tuple[DiscoveredSource, ...]
    issues: tuple[DiscoveryIssue, ...]


# ── Pure policy helpers ──────────────────────────────────────────────────────


def probe_frontmatter(text: str) -> FrontmatterStatus:
    """Structurally probe for a ``---`` frontmatter block.

    Only structural states are claimed.  A block with valid delimiters but
    invalid YAML is still :attr:`FrontmatterStatus.PRESENT`; S13-02 runs no
    YAML parser and never reports YAML validation failures.
    """
    if not isinstance(text, str):
        return FrontmatterStatus.NOT_EVALUATED

    body = text.lstrip("\ufeff")
    if body.startswith("---\n"):
        index = 4
    elif body.startswith("---\r\n"):
        index = 5
    else:
        return FrontmatterStatus.ABSENT

    length = len(body)
    while index <= length:
        line_end = body.find("\n", index)
        if line_end == -1:
            if body[index:].strip() == "---":
                return FrontmatterStatus.PRESENT
            break
        if body[index:line_end].rstrip("\r").strip() == "---":
            return FrontmatterStatus.PRESENT
        index = line_end + 1
    return FrontmatterStatus.UNTERMINATED


def _extension(parts: tuple[str, ...]) -> str:
    """Return the casefolded final extension, or an empty string."""
    name = parts[-1]
    dot = name.rfind(".")
    if dot <= 0:
        return ""
    return name[dot:].casefold()


def _under_entity_directory(parts: tuple[str, ...]) -> bool:
    """Return whether a path is under a canonical managed entity directory."""
    for prefix in _ENTITY_PREFIXES:
        if len(parts) > len(prefix) and parts[: len(prefix)] == prefix:
            return True
    return False


def classify_source(relative_path: str) -> SourceClass:
    """Classify one Vault-relative POSIX path deterministically.

    Application-owned ``_system``/``State`` namespaces take precedence over the
    extension policy, so raw/audit/ChangeSet/derived files are never treated as
    bootstrap source merely because their extension is text-readable.
    """
    parts = tuple(relative_path.split("/"))
    extension = _extension(parts)
    first = parts[0]

    if first == "_system":
        if len(parts) >= 2 and parts[1] == "raw":
            return SourceClass.APPLICATION_RAW
        if len(parts) >= 2 and parts[1] in _APPLICATION_CONTROL_NAMESPACES:
            return SourceClass.APPLICATION_CONTROL
        if len(parts) >= 2 and parts[1] in _APPLICATION_DERIVED_NAMESPACES:
            return SourceClass.DERIVED
        if len(parts) == 2 and parts[1] in {"campaign.yaml", "world_time.json"}:
            return SourceClass.APPLICATION_CONFIG
        return SourceClass.APPLICATION_CONTROL

    if first == "State":
        if len(parts) == 2 and parts[1] in _DERIVED_STATE_LEAVES:
            return SourceClass.DERIVED
        if extension in TEXT_SOURCE_EXTENSIONS:
            return SourceClass.USER_SOURCE
        return SourceClass.UNSUPPORTED

    if extension not in TEXT_SOURCE_EXTENSIONS:
        return SourceClass.UNSUPPORTED
    if _under_entity_directory(parts):
        return SourceClass.ENTITY_CANDIDATE
    if first == "Sessions":
        return SourceClass.SESSION_SOURCE
    return SourceClass.USER_SOURCE


# ── Service ──────────────────────────────────────────────────────────────────


class VaultDiscoveryService:
    """Deterministic application service producing a discovery report.

    Args:
        reader: The trusted read-only storage capability that validated the
            initialized-Vault precondition and exposes metadata/content.
    """

    def __init__(self, reader: VaultSourceReader) -> None:
        self._reader = reader

    def run(self) -> VaultDiscoveryReport:
        """Inventory, classify and boundedly read eligible sources.

        Content is read in the deterministic Vault-relative casefold + exact
        order, so aggregate-limit decisions are repeatable.  Per-file and
        aggregate limits produce explicit ``SKIPPED``/issue states; only the
        storage inventory-entry ceiling is fatal.
        """
        inventory = self._reader.inventory()
        max_total = self._reader.limits.max_total_content_bytes

        entries: list[DiscoveredSource] = []
        issues: list[DiscoveryIssue] = list(inventory.issues)
        total_bytes = 0

        for item in inventory.entries:
            source_class = classify_source(item.relative_path)
            status = ContentReadStatus.NOT_ELIGIBLE
            frontmatter = FrontmatterStatus.NOT_EVALUATED
            text: str | None = None

            if source_class in _ELIGIBLE_SOURCE_CLASSES:
                if total_bytes + item.size_bytes > max_total:
                    status = ContentReadStatus.SKIPPED
                    issues.append(
                        DiscoveryIssue(item.relative_path, DiscoveryIssueCode.AGGREGATE_LIMIT)
                    )
                else:
                    result = self._reader.read_text(item.relative_path)
                    if result.issue is not None:
                        issues.append(result.issue)
                        if result.issue.code is DiscoveryIssueCode.SKIPPED_OVERSIZE:
                            status = ContentReadStatus.SKIPPED
                        else:
                            status = ContentReadStatus.FAILED
                    else:
                        text = result.text
                        status = ContentReadStatus.READ
                        if text is not None:
                            total_bytes += len(text.encode("utf-8"))
                            if item.extension in _MARKDOWN_SOURCE_EXTENSIONS:
                                frontmatter = probe_frontmatter(text)

            entries.append(
                DiscoveredSource(
                    relative_path=item.relative_path,
                    source_class=source_class,
                    extension=item.extension,
                    size_bytes=item.size_bytes,
                    content_status=status,
                    frontmatter_status=frontmatter,
                    content_text=text,
                )
            )

        entries.sort(key=lambda entry: (entry.relative_path.casefold(), entry.relative_path))
        issues.sort(
            key=lambda issue: (
                issue.relative_path.casefold(),
                issue.relative_path,
                issue.code.value,
            )
        )
        return VaultDiscoveryReport(
            campaign_id=inventory.campaign_id,
            entries=tuple(entries),
            issues=tuple(issues),
        )


__all__ = [
    "TEXT_SOURCE_EXTENSIONS",
    "ContentReadStatus",
    "DiscoveredSource",
    "FrontmatterStatus",
    "SourceClass",
    "VaultDiscoveryReport",
    "VaultDiscoveryService",
    "classify_source",
    "probe_frontmatter",
]
