"""S13-03 Vault-backed bootstrap mapping evidence store.

Implements the ``BootstrapEvidenceStore`` protocol for immutable, non-canonical
bootstrap mapping evidence artifacts persisted under a dedicated workflow/control
namespace::

    <vault>/_system/bootstrap/<changeset_id>.mapping.json

These artifacts are **workflow/control state**, not campaign entities and not a
second campaign Source of Truth.  S13-02 classifies ``_system/bootstrap/**`` as
``APPLICATION_CONTROL``, so persisted evidence can never become bootstrap input.

The storage layer deals only in an opaque ``changeset_id`` path key and an
opaque UTF-8 text payload.  Serialization and evidence policy are application
concerns; this module does not import domain or application ChangeSet types and
does not interpret the payload.

It deliberately reuses a separate namespace rather than the Stage-10
``_system/changesets`` one: the evidence is bootstrap-specific and must not be
mistaken for a proposal or approval.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from dnd_assistant.errors import ConflictError, NotFoundError, StorageError
from dnd_assistant.storage.paths import _resolve_vault_root, validate_path_component

# ── Canonical layout ───────────────────────────────────────────────────────

_SYSTEM_DIR = "_system"
_BOOTSTRAP_DIR = "bootstrap"
_EVIDENCE_SUFFIX = ".mapping.json"


# ── Protocol ───────────────────────────────────────────────────────────────


@runtime_checkable
class BootstrapEvidenceStore(Protocol):
    """Protocol for persisted bootstrap mapping evidence artifacts.

    All create operations are exclusive: an existing artifact is never silently
    overwritten (``ConflictError``).  Required reads of missing artifacts raise
    ``NotFoundError``; the ``*_if_present`` variant returns ``None``.
    """

    def create_evidence(self, changeset_id: str, content: str) -> None:
        """Exclusively create an evidence artifact.

        Raises:
            ConflictError: An evidence artifact already exists for this id.
            StorageError: The id is unsafe or a filesystem error occurred.
        """
        ...

    def read_evidence_if_present(self, changeset_id: str) -> str | None:
        """Read an evidence artifact, returning ``None`` when absent.

        Raises:
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        ...


# ── Exact UTF-8 I/O helpers ────────────────────────────────────────────────


def _exclusive_create_text(path: Path, content: str) -> None:
    """Create ``path`` exclusively and write exact UTF-8 ``content``.

    Raises:
        ConflictError: The artifact already exists.
        StorageError: A filesystem error occurred.
    """
    try:
        with open(path, mode="x", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise ConflictError(f"Bootstrap evidence already exists: {path.name}") from None
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise StorageError(f"Failed to create bootstrap evidence: {path}", cause=exc) from exc


def _read_exact_text(path: Path) -> str:
    """Read exact UTF-8 text from ``path`` with newline preservation.

    Raises:
        NotFoundError: The artifact disappeared after the existence check.
        StorageError: The artifact is unreadable or invalid UTF-8.
    """
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        raise NotFoundError(f"Bootstrap evidence not found: {path.name}") from None
    except UnicodeDecodeError as exc:
        raise StorageError(f"Invalid UTF-8 in bootstrap evidence: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to read bootstrap evidence: {path}", cause=exc) from exc


# ── ObsidianBootstrapEvidenceStore ─────────────────────────────────────────


class ObsidianBootstrapEvidenceStore:
    """Filesystem-backed implementation of ``BootstrapEvidenceStore``.

    Args:
        vault_root: The root directory of the Obsidian Vault.  It must exist,
            be a directory, and contain a real ``_system`` directory.

    Raises:
        StorageError: The Vault root or ``_system`` topology is invalid.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self._vault_root = _resolve_vault_root(vault_root)
        self._system_dir = self._vault_root / _SYSTEM_DIR
        self._bootstrap_dir = self._system_dir / _BOOTSTRAP_DIR
        self._validate_system_topology()

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    @property
    def bootstrap_dir(self) -> Path:
        """The absolute ``_system/bootstrap/`` namespace directory."""
        return self._bootstrap_dir

    # ── Topology ──────────────────────────────────────────────────────────

    def _validate_system_topology(self) -> None:
        """Validate that the ``_system`` subtree is present and symlink-safe."""
        system = self._system_dir
        if system.is_symlink():
            raise StorageError(f"_system directory is a symlink, rejected for safety: {system}")
        if not system.exists():
            raise StorageError(f"Canonical _system directory does not exist: {system}")
        if not system.is_dir():
            raise StorageError(f"_system path is not a directory: {system}")

        bootstrap = self._bootstrap_dir
        if bootstrap.is_symlink():
            raise StorageError(
                f"_system/bootstrap directory is a symlink, rejected for safety: {bootstrap}"
            )
        if bootstrap.exists() and not bootstrap.is_dir():
            raise StorageError(f"_system/bootstrap path is not a directory: {bootstrap}")

        try:
            system.resolve(strict=False).relative_to(self._vault_root)
        except ValueError:
            raise StorageError(f"_system resolves outside the Vault root: {system}") from None

    def _ensure_bootstrap_dir(self) -> Path:
        """Return the canonical bootstrap directory, creating it on demand."""
        self._validate_system_topology()
        bootstrap = self._bootstrap_dir
        if bootstrap.is_symlink():
            raise StorageError(
                f"_system/bootstrap directory is a symlink, rejected for safety: {bootstrap}"
            )
        if bootstrap.exists():
            return bootstrap
        try:
            bootstrap.mkdir(exist_ok=False)
        except FileExistsError:
            if bootstrap.is_symlink() or not bootstrap.is_dir():
                raise StorageError(
                    f"_system/bootstrap appeared as an unsafe path: {bootstrap}"
                ) from None
        except OSError as exc:
            raise StorageError(
                f"Failed to create bootstrap directory: {bootstrap}", cause=exc
            ) from exc
        self._validate_system_topology()
        return bootstrap

    def _artifact_path(self, changeset_id: str) -> Path:
        """Resolve the evidence path with component and containment safety."""
        validate_path_component(changeset_id, label="changeset_id")
        path = self._bootstrap_dir / f"{changeset_id}{_EVIDENCE_SUFFIX}"
        resolved_dir = self._bootstrap_dir.resolve(strict=False)
        try:
            path.resolve(strict=False).relative_to(resolved_dir)
        except ValueError:
            raise StorageError(
                f"Bootstrap evidence resolves outside the bootstrap namespace: {path}"
            ) from None
        if path.is_symlink():
            raise StorageError(f"Bootstrap evidence leaf is a symlink: {path}")
        return path

    # ── Operations ────────────────────────────────────────────────────────

    def create_evidence(self, changeset_id: str, content: str) -> None:
        """Exclusively create an evidence artifact.

        Raises:
            ConflictError: An evidence artifact already exists for this id.
            StorageError: The id is unsafe or a filesystem error occurred.
        """
        path = self._artifact_path(changeset_id)
        self._ensure_bootstrap_dir()
        _exclusive_create_text(path, content)

    def read_evidence_if_present(self, changeset_id: str) -> str | None:
        """Read an evidence artifact, returning ``None`` when absent."""
        self._validate_system_topology()
        path = self._artifact_path(changeset_id)
        if path.is_symlink():
            raise StorageError(f"Bootstrap evidence leaf is a symlink: {path}")
        if not path.exists():
            return None
        if not path.is_file():
            raise StorageError(f"Bootstrap evidence is not a regular file: {path}")
        return _read_exact_text(path)


__all__ = ["BootstrapEvidenceStore", "ObsidianBootstrapEvidenceStore"]
