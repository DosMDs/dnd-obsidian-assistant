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
(relative path, extension, size).  ``read_text(relative_path, max_bytes)``
performs an exact UTF-8 read that is bounded at read time by the supplied
effective budget (``min`` of the per-file limit and the remaining aggregate
budget) plus a one-byte overflow sentinel.  Filesystem discovery is never
conflated with campaign semantic mapping.

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
"""Hard ceiling on filesystem entries encountered by traversal (files, \
directories, redirects, excluded and non-regular entries).  Overflow is a \
fatal resource failure with no partial report."""

MAX_CONTENT_FILE_BYTES: Final[int] = 1_048_576
"""Maximum bytes retained from a single source (1 MiB)."""

MAX_TOTAL_CONTENT_BYTES: Final[int] = 67_108_864
"""Maximum aggregate bytes retained across a single discovery run (64 MiB)."""

MAX_DEPTH: Final[int] = 32
"""Maximum directory nesting depth below the resolved Vault root."""

_MAX_MARKER_BYTES: Final[int] = 65_536
"""Bounded read budget for the trusted ``_system/campaign.yaml`` marker.

Deliberately independent of the source-content budget so a low per-source
limit cannot make a valid initialized Vault look unreadable.
"""


@dataclass(frozen=True, slots=True)
class DiscoveryLimits:
    """Deterministic, testable resource bounds for one discovery run.

    ``max_inventory_entries`` and the per-read budget are enforced by this
    storage capability.  ``max_total_content_bytes`` is enforced by the
    application content phase, which passes the remaining aggregate budget into
    :meth:`ObsidianVaultSourceReader.read_text` as the effective read cap.
    """

    max_inventory_entries: int = MAX_INVENTORY_ENTRIES
    max_content_file_bytes: int = MAX_CONTENT_FILE_BYTES
    max_total_content_bytes: int = MAX_TOTAL_CONTENT_BYTES
    max_depth: int = MAX_DEPTH


# ── Exclusion policy ─────────────────────────────────────────────────────────

_EXCLUDED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset({".obsidian", ".git"})
_EXCLUDED_FILE_NAMES: Final[frozenset[str]] = frozenset(
    name.casefold() for name in (".DS_Store", "Thumbs.db", "desktop.ini", ".git")
)
_EXCLUDED_FILE_SUFFIXES: Final[tuple[str, ...]] = (".tmp", ".swp", ".bak")


def _is_excluded_name(name: str, *, is_directory: bool) -> bool:
    """Return whether a directory entry is architectural infrastructure.

    Policy:

    - ``.obsidian``/``.git`` and any hidden directory are excluded with their
      whole subtree (casefold-equivalent names included);
    - known OS metadata and editor temp/backup files are excluded;
    - other hidden *files* are **not** blanket-excluded, so explicitly known
      application artifacts such as the hidden Campaign State manifest are
      still discovered and classified deterministically by the caller.
    """
    folded = name.casefold()
    if folded in _EXCLUDED_DIRECTORY_NAMES:
        return True
    if is_directory and name.startswith("."):
        return True
    if folded in _EXCLUDED_FILE_NAMES:
        return True
    if name.startswith("~") or name.endswith("~"):
        return True
    return any(folded.endswith(suffix) for suffix in _EXCLUDED_FILE_SUFFIXES)


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

    def read_text(self, relative_path: str, max_bytes: int | None = None) -> SourceReadResult:
        """Boundedly read one Vault-relative path as exact UTF-8.

        ``max_bytes`` is the effective read budget (the caller passes the
        ``min`` of the per-file limit and the remaining aggregate budget).  At
        most ``max_bytes`` bytes are retained; one extra sentinel byte is read
        only to detect overflow, which returns ``SKIPPED_OVERSIZE`` with no
        text.  This is a Vault-bounded primitive: inventory membership, source
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
            text = self._read_bounded_text(path, _MAX_MARKER_BYTES)
        except StorageError as exc:
            raise StorageError(f"Failed to read campaign.yaml: {path}", cause=exc) from exc
        return parse_campaign_config(text).campaign_id

    # ── Phase 1: inventory ────────────────────────────────────────────────

    def inventory(self) -> VaultSourceInventory:
        """Deterministically inventory regular, non-redirecting files.

        The ``max_inventory_entries`` ceiling bounds filesystem entries
        encountered by traversal (including directories, redirects, excluded
        and non-regular entries), not only successfully inventoried files.

        Raises:
            StorageError: The Vault root disappeared, the root could not be
                read, or the traversal-entry ceiling was exceeded.  A ceiling
                overflow is fatal and yields no partial inventory.
        """
        if not self._root.is_dir():
            raise StorageError(f"Vault root is no longer a directory: {self._root}")

        entries: list[InventoryEntry] = []
        issues: list[DiscoveryIssue] = []

        for entry in self._walk(issues):
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

        Traversal is iterative (no recursion), never materializes a directory
        with ``list()``, never follows symlinks or junctions, and records
        isolated issues for redirects, depth limits, unreadable subdirectories
        and non-regular files.  Every encountered directory entry counts
        against ``max_inventory_entries``; overflow raises ``StorageError``
        with no partial report.  A root read error is fatal.
        """
        stack: list[tuple[Path, str]] = [(self._root, "")]
        encountered = 0
        while stack:
            directory, rel_dir = stack.pop()

            if rel_dir != "":
                problem = self._authorize_directory(directory, rel_dir)
                if problem is not None:
                    issues.append(problem)
                    continue

            try:
                scandir = os.scandir(directory)
            except OSError:
                if rel_dir == "":
                    raise StorageError(f"Failed to read Vault root: {directory}") from None
                issues.append(DiscoveryIssue(rel_dir, DiscoveryIssueCode.UNREADABLE))
                continue

            with scandir:
                for entry in scandir:
                    encountered += 1
                    if encountered > self._limits.max_inventory_entries:
                        raise StorageError(
                            f"Vault source traversal exceeded "
                            f"{self._limits.max_inventory_entries} encountered entries at "
                            f"{rel_dir or '.'}; raise the limit explicitly or reduce the Vault"
                        )

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
                        issues.append(
                            DiscoveryIssue(relative, DiscoveryIssueCode.NOT_A_REGULAR_FILE)
                        )
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

    def _authorize_directory(self, directory: Path, relative: str) -> DiscoveryIssue | None:
        """Re-authorize a descendant directory immediately before descent.

        Redirect identity and containment are re-checked at pop time, after the
        entry was pushed, so a directory replaced between discovery steps is not
        descended.  This narrows but cannot atomically eliminate the OS-level
        TOCTOU window between this check and ``os.scandir``.
        """
        try:
            if directory.is_symlink() or directory.is_junction():
                return DiscoveryIssue(relative, DiscoveryIssueCode.UNSAFE_REDIRECT)
            if not directory.is_dir():
                return DiscoveryIssue(relative, DiscoveryIssueCode.UNREADABLE)
            directory.resolve(strict=False).relative_to(self._root)
        except (OSError, ValueError):
            return DiscoveryIssue(relative, DiscoveryIssueCode.UNSAFE_REDIRECT)
        return None

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

    def _read_bounded_text(self, path: Path, budget: int) -> str:
        """Read exact UTF-8 text, bounded by ``budget`` bytes.

        Raises:
            StorageError: The file is unreadable, exceeds ``budget``, or is not
                valid UTF-8 (a ``UnicodeDecodeError`` cause distinguishes the
                latter).
        """
        bounded = _read_bounded(path, budget)
        if bounded.overflow:
            raise StorageError(f"File exceeds read budget ({budget} bytes): {path}")
        try:
            return bounded.data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StorageError(f"File is not valid UTF-8: {path}", cause=exc) from exc

    # ── Phase 2: bounded read ─────────────────────────────────────────────

    def read_text(self, relative_path: str, max_bytes: int | None = None) -> SourceReadResult:
        """Boundedly read one Vault-relative path as exact UTF-8.

        ``max_bytes`` is the effective read budget (the application passes the
        ``min`` of the per-file limit and the remaining aggregate budget).  The
        read is bounded at read time: at most ``budget`` bytes are retained and
        one sentinel byte is read only to detect overflow, which returns
        ``SKIPPED_OVERSIZE`` with no text.  The pre-read ``stat()`` is only an
        optimization and is never the safety bound.

        This is a Vault-bounded primitive: it enforces path syntax, redirect
        rejection and Vault containment, but does **not** verify that the path
        was inventoried or is source-eligible; that policy belongs to the
        application layer.

        The path is re-authorized against redirects and containment before the
        read (best-effort TOCTOU fail-closed check).  The read never follows
        symlinks on platforms exposing ``O_NOFOLLOW``; on platforms without it,
        the pre-open redirect check is the residual best-effort guard.
        """
        budget = self._limits.max_content_file_bytes if max_bytes is None else max_bytes
        budget = min(budget, self._limits.max_content_file_bytes)
        if budget < 0:
            budget = 0

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
        # Optimization only: a declared size over either ceiling is already an
        # explicit skip.  The bounded read below is the actual safety bound.
        if info.st_size > self._limits.max_content_file_bytes or info.st_size > budget:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.SKIPPED_OVERSIZE)
            )

        try:
            bounded = _read_bounded(current, budget)
        except StorageError as exc:
            code = (
                DiscoveryIssueCode.DISAPPEARED
                if isinstance(exc.__cause__, FileNotFoundError)
                else DiscoveryIssueCode.UNREADABLE
            )
            return SourceReadResult(None, DiscoveryIssue(relative_path, code))

        if bounded.overflow:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.SKIPPED_OVERSIZE)
            )
        try:
            text = bounded.data.decode("utf-8")
        except UnicodeDecodeError:
            return SourceReadResult(
                None, DiscoveryIssue(relative_path, DiscoveryIssueCode.INVALID_UTF8)
            )
        return SourceReadResult(text, None)


# ── Bounded exact UTF-8 read primitives ──────────────────────────────────────

_OVERFLOW_SENTINEL_BYTES: Final[int] = 1
"""Minimum extra byte read to distinguish "fits exactly" from "exceeds"."""


@dataclass(frozen=True, slots=True)
class _BoundedRead:
    """Raw bounded-read outcome: bytes plus whether the budget was exceeded."""

    data: bytes
    overflow: bool


def _read_bounded(path: Path, budget: int) -> _BoundedRead:
    """Read at most ``budget`` bytes, or ``budget + 1`` when it overflows.

    Never reads a source to EOF before enforcing its byte ceiling: the loop
    stops after ``budget + 1`` bytes, so a file that grows between ``stat()``
    and the read still cannot cause an unbounded allocation.  Exact newline
    bytes are preserved (binary read; decoding is the caller's responsibility).
    Uses ``O_NOFOLLOW`` where the platform exposes it.

    Raises:
        StorageError: The file disappeared, could not be opened, or a read
            failed.  A ``FileNotFoundError`` cause distinguishes disappearance.
    """
    effective = budget if budget > 0 else 0
    limit = effective + _OVERFLOW_SENTINEL_BYTES
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise StorageError(f"Source file disappeared: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to open source file: {path}", cause=exc) from exc

    chunks: list[bytes] = []
    remaining = limit
    try:
        while remaining > 0:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError as exc:
        raise StorageError(f"Failed to read source file: {path}", cause=exc) from exc
    finally:
        os.close(descriptor)

    data = b"".join(chunks)
    return _BoundedRead(data=data, overflow=len(data) > effective)


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
