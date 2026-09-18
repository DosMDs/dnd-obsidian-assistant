"""S13-02 read-only Vault source discovery storage capability.

This module owns the trusted filesystem mechanics for discovering and
boundedly reading existing campaign source material inside an already
initialized Obsidian Vault.  It is the only S13-02 component that touches the
filesystem.

Scope
=====

Discovery is **strictly read-only** with respect to canonical campaign state:

- it never creates, mutates, deletes or audits anything;
- it never follows symlinks, junctions or reparse redirects below the resolved
  Vault root;
- it never leaves the resolved Vault root.

Initialization precondition
===========================

A Vault is a valid discovery input only when it carries a valid
``_system/campaign.yaml`` initialized by S13-01.  This module validates that
precondition using the existing S13-01 campaign-config contract and exposes the
validated ``campaign_id`` upward.  The application layer consumes the typed
result and never opens or parses the marker itself.

Two phases
==========

``inventory()`` performs a safe, deterministic, bounded stat-only traversal
(relative path, extension, size).  ``read_text()`` performs a bounded exact
UTF-8 read for one already-inventoried relative path.  Filesystem discovery is
never conflated with campaign semantic mapping.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai, textual.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.paths import _resolve_vault_root
from dnd_assistant.storage.vault_initialization import (
    CAMPAIGN_CONFIG_RELATIVE,
    parse_campaign_config,
)

# ── Resource bounds ──────────────────────────────────────────────────────────

MAX_INVENTORY_ENTRIES: Final[int] = 20_000
"""Hard ceiling on inventoried files.  Overflow is a fatal resource failure."""

MAX_CONTENT_FILE_BYTES: Final[int] = 1_048_576
"""Maximum bytes read from a single source (1 MiB)."""

MAX_TOTAL_CONTENT_BYTES: Final[int] = 67_108_864
"""Maximum aggregate bytes read across a single discovery run (64 MiB)."""

MAX_DEPTH: Final[int] = 32
"""Maximum directory nesting depth below the resolved Vault root."""


@dataclass(frozen=True, slots=True)
class DiscoveryLimits:
    """Deterministic, testable resource bounds for one discovery run.

    ``max_content_file_bytes`` and ``max_inventory_entries`` are enforced by
    this storage capability.  ``max_total_content_bytes`` is enforced by the
    application content phase, which owns the aggregate read decision.
    """

    max_inventory_entries: int = MAX_INVENTORY_ENTRIES
    max_content_file_bytes: int = MAX_CONTENT_FILE_BYTES
    max_total_content_bytes: int = MAX_TOTAL_CONTENT_BYTES
    max_depth: int = MAX_DEPTH


# ── Exclusion policy ─────────────────────────────────────────────────────────

_EXCLUDED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset({".obsidian", ".git"})
_EXCLUDED_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {".DS_Store", "Thumbs.db", "desktop.ini", ".git"}
)
_EXCLUDED_FILE_SUFFIXES: Final[tuple[str, ...]] = (".tmp", ".swp", ".bak")


def _is_excluded_name(name: str, *, is_directory: bool) -> bool:
    """Return whether a directory entry is architectural infrastructure.

    Policy:

    - ``.obsidian``/``.git`` and any hidden directory are excluded with their
      whole subtree;
    - known OS metadata and editor temp/backup files are excluded;
    - other hidden *files* are **not** blanket-excluded, so explicitly known
      application artifacts such as the hidden Campaign State manifest are
      still discovered and classified deterministically by the caller.
    """
    if name in _EXCLUDED_DIRECTORY_NAMES:
        return True
    if is_directory and name.startswith("."):
        return True
    if name in _EXCLUDED_FILE_NAMES:
        return True
    if name.startswith("~") or name.endswith("~"):
        return True
    lowered = name.casefold()
    return any(lowered.endswith(suffix) for suffix in _EXCLUDED_FILE_SUFFIXES)


# ── Result types ─────────────────────────────────────────────────────────────


class DiscoveryIssueCode(StrEnum):
    """Deterministic, machine-readable reason a path or read is not clean."""

    UNSAFE_REDIRECT = "unsafe_redirect"
    INVALID_UTF8 = "invalid_utf8"
    UNREADABLE = "unreadable"
    DISAPPEARED = "disappeared"
    NOT_A_REGULAR_FILE = "not_a_regular_file"
    SKIPPED_OVERSIZE = "skipped_oversize"
    DEPTH_LIMIT = "depth_limit"
    AGGREGATE_LIMIT = "aggregate_limit"
    CASE_ALIAS = "case_alias"


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    """An isolated discovery/read problem for one Vault-relative path.

    Issues are non-fatal for the run except for the inventory-entry ceiling,
    which raises ``StorageError`` and produces no report.
    """

    relative_path: str
    code: DiscoveryIssueCode


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """Stat-only inventory record for one regular, non-redirecting file."""

    relative_path: str
    extension: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SourceReadResult:
    """Outcome of one bounded UTF-8 read."""

    text: str | None
    issue: DiscoveryIssue | None


@dataclass(frozen=True, slots=True)
class VaultSourceInventory:
    """Deterministic, ordered inventory of a validated initialized Vault."""

    campaign_id: str
    entries: tuple[InventoryEntry, ...]
    issues: tuple[DiscoveryIssue, ...]


def _order_key(relative_path: str) -> tuple[str, str]:
    """Canonical deterministic ordering: casefold, then exact path."""
    return (relative_path.casefold(), relative_path)


# ── Reader protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class VaultSourceReader(Protocol):
    """Trusted read-only source capability consumed by the application layer."""

    @property
    def campaign_id(self) -> str: ...

    @property
    def limits(self) -> DiscoveryLimits: ...

    def inventory(self) -> VaultSourceInventory: ...

    def read_text(self, relative_path: str) -> SourceReadResult:
        """Boundedly read one Vault-relative path as exact UTF-8.

        This is a Vault-bounded primitive: it enforces path syntax, redirect
        rejection and Vault containment only.  Inventory membership, source
        eligibility and the exclusion policy are the caller's responsibility.
        """
        ...


# ── Relative-path helper ─────────────────────────────────────────────────────


def _relative_parts(relative_path: str) -> tuple[str, ...] | None:
    """Return safe Vault-relative components, or ``None`` when unsafe."""
    if not isinstance(relative_path, str) or not relative_path:
        return None
    if "\\" in relative_path or relative_path.startswith("/"):
        return None
    parts = tuple(relative_path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        return None
    return parts


# ── Concrete reader ──────────────────────────────────────────────────────────


class ObsidianVaultSourceReader:
    """Read-only discovery capability over an initialized Obsidian Vault.

    Args:
        vault_root: The selected Vault root.  A symlink/junction root is
            resolved once to its physical authoritative root.
        limits: Optional resource bounds; defaults to :class:`DiscoveryLimits`.

    Raises:
        StorageError: The Vault root is missing/not a directory, or the
            ``_system/campaign.yaml`` initialization precondition is not met.
    """

    def __init__(self, vault_root: str | Path, limits: DiscoveryLimits | None = None) -> None:
        self._root = _resolve_vault_root(vault_root)
        self._limits = limits if limits is not None else DiscoveryLimits()
        self._campaign_id = self._read_campaign_marker()

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def vault_root(self) -> Path:
        """The resolved physical Vault root path."""
        return self._root

    @property
    def campaign_id(self) -> str:
        """The validated campaign identity from ``_system/campaign.yaml``."""
        return self._campaign_id

    @property
    def limits(self) -> DiscoveryLimits:
        """The resource bounds for this reader."""
        return self._limits

    # ── Initialization precondition ───────────────────────────────────────

    def _authorize_marker(self) -> Path:
        """Authorize the canonical campaign marker path against redirects."""
        accumulated = self._root
        for part in CAMPAIGN_CONFIG_RELATIVE.parts:
            accumulated = accumulated / part
            if accumulated.is_symlink() or accumulated.is_junction():
                raise StorageError(
                    f"campaign.yaml path component is a redirecting object, "
                    f"rejected for safety: {accumulated}"
                )
        resolved = accumulated.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise StorageError(
                f"campaign.yaml resolves outside the Vault root: {resolved}"
            ) from None
        return accumulated

    def _read_campaign_marker(self) -> str:
        """Validate the S13-01 initialized-Vault precondition.

        Raises:
            StorageError: The marker is absent, not a regular file, unreadable
                or invalid; the Vault is not a valid discovery input.
        """
        path = self._authorize_marker()
        if not path.exists():
            raise StorageError(
                "Vault is not initialized: _system/campaign.yaml is absent; "
                "run `dnd init` before discovery"
            )
        if not path.is_file():
            raise StorageError(f"campaign.yaml is not a regular file: {path}")
        try:
            text = _read_utf8_text(path)
        except StorageError as exc:
            raise StorageError(f"Failed to read campaign.yaml: {path}", cause=exc) from exc
        return parse_campaign_config(text).campaign_id

    # ── Phase 1: inventory ────────────────────────────────────────────────

    def inventory(self) -> VaultSourceInventory:
        """Deterministically inventory regular, non-redirecting files.

        Raises:
            StorageError: The Vault root disappeared, the root could not be
                read, or the inventory-entry ceiling was exceeded.  A ceiling
                overflow is fatal and yields no partial inventory.
        """
        if not self._root.is_dir():
            raise StorageError(f"Vault root is no longer a directory: {self._root}")

        entries: list[InventoryEntry] = []
        issues: list[DiscoveryIssue] = []
        count = 0

        for entry in self._walk(issues):
            count += 1
            if count > self._limits.max_inventory_entries:
                raise StorageError(
                    f"Vault source inventory exceeded {self._limits.max_inventory_entries} "
                    f"entries at {entry.relative_path}; raise the limit explicitly or "
                    f"reduce the Vault"
                )
            entries.append(entry)

        issues.extend(self._case_alias_issues(entries))
        entries.sort(key=lambda item: _order_key(item.relative_path))
        issues.sort(key=lambda issue: (_order_key(issue.relative_path), issue.code.value))
        return VaultSourceInventory(
            campaign_id=self._campaign_id,
            entries=tuple(entries),
            issues=tuple(issues),
        )

    def _walk(self, issues: list[DiscoveryIssue]) -> Iterator[InventoryEntry]:
        """Yield inventoried files, recording isolated traversal issues.

        Traversal is iterative (no recursion), never follows symlinks or
        junctions, and records isolated issues for redirects, depth limits,
        unreadable subdirectories and non-regular files.  A root read error is
        fatal.
        """
        stack: list[tuple[Path, str]] = [(self._root, "")]
        while stack:
            directory, rel_dir = stack.pop()
            try:
                with os.scandir(directory) as scandir:
                    raw_entries = list(scandir)
            except OSError:
                if rel_dir == "":
                    raise StorageError(f"Failed to read Vault root: {directory}") from None
                issues.append(DiscoveryIssue(rel_dir, DiscoveryIssueCode.UNREADABLE))
                continue

            for entry in raw_entries:
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_directory = False
                if _is_excluded_name(entry.name, is_directory=is_directory):
                    continue
                relative = f"{rel_dir}/{entry.name}" if rel_dir else entry.name

                if self._is_redirect(entry.path):
                    issues.append(DiscoveryIssue(relative, DiscoveryIssueCode.UNSAFE_REDIRECT))
                    continue

                if is_directory:
                    child_depth = relative.count("/") + 1
                    if child_depth >= self._limits.max_depth:
                        issues.append(DiscoveryIssue(relative, DiscoveryIssueCode.DEPTH_LIMIT))
                        continue
                    stack.append((Path(entry.path), relative))
                    continue

                try:
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    is_file = False
                if not is_file:
                    issues.append(DiscoveryIssue(relative, DiscoveryIssueCode.NOT_A_REGULAR_FILE))
                    continue

                size = self._safe_size(relative)
                if size is None:
                    issues.append(DiscoveryIssue(relative, DiscoveryIssueCode.UNREADABLE))
                    continue
                yield InventoryEntry(
                    relative_path=relative,
                    extension=Path(entry.name).suffix.casefold(),
                    size_bytes=size,
                )

    @staticmethod
    def _is_redirect(path: str) -> bool:
        """Return whether a directory entry is a symlink or junction."""
        candidate = Path(path)
        try:
            if candidate.is_symlink():
                return True
            return candidate.is_junction()
        except OSError:
            return True

    def _safe_size(self, relative: str) -> int | None:
        """Return the size of a regular file, or ``None`` on failure."""
        full = self._root / relative
        try:
            info = full.stat()
        except OSError:
            return None
        if not stat.S_ISREG(info.st_mode):
            return None
        return info.st_size

    def _case_alias_issues(self, entries: list[InventoryEntry]) -> list[DiscoveryIssue]:
        """Detect case-insensitive path collisions deterministically."""
        groups: dict[str, list[str]] = {}
        for entry in entries:
            groups.setdefault(entry.relative_path.casefold(), []).append(entry.relative_path)
        issues: list[DiscoveryIssue] = []
        for paths in groups.values():
            if len(paths) > 1:
                for path in paths:
                    issues.append(DiscoveryIssue(path, DiscoveryIssueCode.CASE_ALIAS))
        return issues

    # ── Phase 2: bounded read ─────────────────────────────────────────────

    def read_text(self, relative_path: str) -> SourceReadResult:
        """Boundedly read one Vault-relative path as exact UTF-8.

        This is a Vault-bounded primitive: it enforces path syntax, redirect
        rejection and Vault containment, but does **not** verify that the path
        was inventoried or is source-eligible; that policy belongs to the
        application layer.

        The path is re-authorized against redirects and containment before the
        read (best-effort TOCTOU fail-closed check).  The read never follows
        symlinks on platforms exposing ``O_NOFOLLOW``; on platforms without it,
        the pre-open redirect check is the residual best-effort guard.
        """
        parts = _relative_parts(relative_path)
        if parts is None:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.UNSAFE_REDIRECT)
            )

        current = self._root
        for part in parts:
            current = current / part
            if self._is_redirect(str(current)):
                return SourceReadResult(
                    None, DiscoveryIssue(relative_path, DiscoveryIssueCode.UNSAFE_REDIRECT)
                )

        try:
            resolved = current.resolve(strict=False)
            resolved.relative_to(self._root)
        except (OSError, ValueError):
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.UNSAFE_REDIRECT)
            )

        try:
            info = current.stat()
        except FileNotFoundError:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.DISAPPEARED)
            )
        except OSError:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.UNREADABLE)
            )

        if not stat.S_ISREG(info.st_mode):
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.NOT_A_REGULAR_FILE)
            )
        if info.st_size > self._limits.max_content_file_bytes:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.SKIPPED_OVERSIZE)
            )

        try:
            text = _read_utf8_text(current)
        except StorageError as exc:
            code = (
                DiscoveryIssueCode.INVALID_UTF8
                if isinstance(exc.__cause__, UnicodeDecodeError)
                else DiscoveryIssueCode.UNREADABLE
            )
            return SourceReadResult(None, DiscoveryIssue(relative_path, code))

        if len(text.encode("utf-8")) > self._limits.max_content_file_bytes:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.SKIPPED_OVERSIZE)
            )
        return SourceReadResult(text, None)


# ── Exact UTF-8 read helper ──────────────────────────────────────────────────


def _read_utf8_text(path: Path) -> str:
    """Read exact UTF-8 text with newline preservation, never following links.

    Uses ``O_NOFOLLOW`` where the platform exposes it so a symlink substituted
    between the pre-check and the open still fails closed.

    Raises:
        StorageError: The file is unreadable or not valid UTF-8.  A
            ``UnicodeDecodeError`` cause distinguishes the latter.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise StorageError(f"Source file disappeared: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to open source file: {path}", cause=exc) from exc

    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise StorageError(f"Source file is not valid UTF-8: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to read source file: {path}", cause=exc) from exc


__all__ = [
    "MAX_CONTENT_FILE_BYTES",
    "MAX_DEPTH",
    "MAX_INVENTORY_ENTRIES",
    "MAX_TOTAL_CONTENT_BYTES",
    "DiscoveryIssue",
    "DiscoveryIssueCode",
    "DiscoveryLimits",
    "InventoryEntry",
    "ObsidianVaultSourceReader",
    "SourceReadResult",
    "VaultSourceInventory",
    "VaultSourceReader",
]
