"""S10-05 Vault-backed ChangeSet workflow-artifact store.

Implements the ``ChangeSetStore`` protocol for raw Stage-10 proposal and
approval artifacts persisted under a dedicated non-entity namespace::

    <vault>/_system/changesets/<changeset_id>.proposal.json
    <vault>/_system/changesets/<changeset_id>.approval.json

These artifacts are **workflow/control state**, not campaign entities.  They do
not live in an entity directory and are never a second campaign Source of
Truth.  The Obsidian Vault remains the only campaign Source of Truth.

The storage layer deals only in an opaque ``changeset_id`` path key and an
opaque UTF-8 text payload.  Serialization, fingerprint binding and workflow
policy are application concerns; this module does not import domain or
application ChangeSet types and does not interpret the payload.

Safety properties:

- Vault root and ``_system`` topology are validated and revalidated;
- ``changeset_id`` is validated as exactly one safe path component (no
  separators, ``.``/``..``, traversal, Windows-invalid characters, trailing
  dot/space or reserved device names);
- symlinked components and artifact leaves are rejected;
- new artifacts are created exclusively (no silent overwrite);
- writes and reads are exact UTF-8 with newline preservation;
- malformed I/O becomes ``StorageError``; a missing required artifact becomes
  ``NotFoundError``.

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
_CHANGESETS_DIR = "changesets"
_PROPOSAL_SUFFIX = ".proposal.json"
_APPROVAL_SUFFIX = ".approval.json"


# ── ChangeSetStore protocol ────────────────────────────────────────────────


@runtime_checkable
class ChangeSetStore(Protocol):
    """Protocol for persisted ChangeSet workflow/control artifacts.

    This protocol owns safe persistence of raw Stage-10 proposal and approval
    artifacts under a dedicated non-entity Vault namespace.  It is a separate
    persistence aggregate from ``VaultRepository`` — ChangeSet
    proposal/approval artifacts are workflow/control state, not campaign
    entities, and do not live in an entity directory.

    The storage layer deals only in an opaque ``changeset_id`` path key and an
    opaque UTF-8 text payload.  Serialization, fingerprint binding, workflow
    policy and schema interpretation are application concerns; this protocol
    must not depend on domain/application ChangeSet types.

    All create operations are exclusive: an existing artifact is never silently
    overwritten (``ConflictError``).  Required reads of missing artifacts raise
    ``NotFoundError``; the ``*_if_present`` variants return ``None``.
    """

    def create_proposal(self, changeset_id: str, content: str) -> None:
        """Exclusively create a proposal artifact.

        Raises:
            ConflictError: A proposal artifact already exists for this id.
            StorageError: The id is unsafe or a filesystem error occurred.
        """
        ...

    def read_proposal(self, changeset_id: str) -> str:
        """Read a proposal artifact.

        Raises:
            NotFoundError: No proposal artifact exists for this id.
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        ...

    def read_proposal_if_present(self, changeset_id: str) -> str | None:
        """Read a proposal artifact, returning ``None`` when absent.

        Raises:
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        ...

    def create_approval(self, changeset_id: str, content: str) -> None:
        """Exclusively create an approval artifact.

        Raises:
            ConflictError: An approval artifact already exists for this id.
            StorageError: The id is unsafe or a filesystem error occurred.
        """
        ...

    def read_approval(self, changeset_id: str) -> str:
        """Read an approval artifact.

        Raises:
            NotFoundError: No approval artifact exists for this id.
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        ...

    def read_approval_if_present(self, changeset_id: str) -> str | None:
        """Read an approval artifact, returning ``None`` when absent.

        Raises:
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        ...


# ── Exact UTF-8 I/O helpers ────────────────────────────────────────────────


def _exclusive_create_text(path: Path, content: str) -> None:
    """Create ``path`` exclusively and write exact UTF-8 ``content``.

    The file is created with exclusive semantics (``open(..., "x")``), so an
    existing artifact is never overwritten.

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
        raise ConflictError(f"Artifact already exists: {path.name}") from None
    except OSError as exc:
        # Best-effort cleanup of a partially written new file.  An existing
        # file can never reach here because "x" fails before writing.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise StorageError(f"Failed to create artifact: {path}", cause=exc) from exc


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
        raise NotFoundError(f"Artifact not found: {path.name}") from None
    except UnicodeDecodeError as exc:
        raise StorageError(f"Invalid UTF-8 in artifact: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to read artifact: {path}", cause=exc) from exc


# ── ObsidianChangeSetStore ─────────────────────────────────────────────────


class ObsidianChangeSetStore:
    """Filesystem-backed implementation of the ``ChangeSetStore`` protocol.

    Stores raw proposal/approval text artifacts under
    ``<vault>/_system/changesets/``.  Payloads are opaque to this class.

    Args:
        vault_root: The root directory of the Obsidian Vault.  It must exist,
            be a directory, and contain a real ``_system`` directory.

    Raises:
        StorageError: The Vault root or ``_system`` topology is invalid.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self._vault_root = _resolve_vault_root(vault_root)
        self._system_dir = self._vault_root / _SYSTEM_DIR
        self._changesets_dir = self._system_dir / _CHANGESETS_DIR
        self._validate_system_topology()

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    @property
    def changesets_dir(self) -> Path:
        """The absolute ``_system/changesets/`` namespace directory."""
        return self._changesets_dir

    # ── Topology ──────────────────────────────────────────────────────────

    def _validate_system_topology(self) -> None:
        """Validate that the ``_system`` subtree is present and symlink-safe.

        Raises:
            StorageError: ``_system`` is missing/not a directory/is a symlink,
                ``_system/changesets`` is a symlink or a non-directory, or a
                resolved path escapes the Vault root.
        """
        system = self._system_dir

        # Symlink identity is checked before exists(): a dangling symlink has
        # is_symlink() == True but exists() == False.
        if system.is_symlink():
            raise StorageError(f"_system directory is a symlink, rejected for safety: {system}")

        if not system.exists():
            raise StorageError(f"Canonical _system directory does not exist: {system}")

        if not system.is_dir():
            raise StorageError(f"_system path is not a directory: {system}")

        changesets = self._changesets_dir
        if changesets.is_symlink():
            raise StorageError(
                f"_system/changesets directory is a symlink, rejected for safety: {changesets}"
            )
        if changesets.exists() and not changesets.is_dir():
            raise StorageError(f"_system/changesets path is not a directory: {changesets}")

        try:
            system.resolve(strict=False).relative_to(self._vault_root)
        except ValueError:
            raise StorageError(f"_system resolves outside the Vault root: {system}") from None

    def _ensure_changesets_dir(self) -> Path:
        """Return the canonical changesets directory, creating it on demand.

        Raises:
            StorageError: The namespace is unsafe or could not be created.
        """
        self._validate_system_topology()
        changesets = self._changesets_dir

        if changesets.is_symlink():
            raise StorageError(
                f"_system/changesets directory is a symlink, rejected for safety: {changesets}"
            )

        if changesets.exists():
            return changesets

        try:
            changesets.mkdir(exist_ok=False)
        except FileExistsError:
            # Concurrent creation is acceptable only if topology is now safe.
            if changesets.is_symlink() or not changesets.is_dir():
                raise StorageError(
                    f"_system/changesets appeared as an unsafe path: {changesets}"
                ) from None
        except OSError as exc:
            raise StorageError(
                f"Failed to create changesets directory: {changesets}", cause=exc
            ) from exc

        self._validate_system_topology()
        return changesets

    def _artifact_path(self, changeset_id: str, suffix: str) -> Path:
        """Resolve one artifact path with component and containment safety.

        Raises:
            StorageError: The ``changeset_id`` is not a safe path component,
                the resolved artifact escapes the namespace, or the leaf is a
                symlink.
        """
        validate_path_component(changeset_id, label="changeset_id")

        path = self._changesets_dir / f"{changeset_id}{suffix}"

        resolved_dir = self._changesets_dir.resolve(strict=False)
        try:
            path.resolve(strict=False).relative_to(resolved_dir)
        except ValueError:
            raise StorageError(
                f"Artifact resolves outside the changesets namespace: {path}"
            ) from None

        if path.is_symlink():
            raise StorageError(f"Artifact leaf is a symlink, rejected for safety: {path}")

        return path

    # ── Create operations ─────────────────────────────────────────────────

    def create_proposal(self, changeset_id: str, content: str) -> None:
        """Exclusively create a proposal artifact.

        Raises:
            ConflictError: A proposal artifact already exists for this id.
            StorageError: The id is unsafe or a filesystem error occurred.
        """
        path = self._artifact_path(changeset_id, _PROPOSAL_SUFFIX)
        self._ensure_changesets_dir()
        _exclusive_create_text(path, content)

    def create_approval(self, changeset_id: str, content: str) -> None:
        """Exclusively create an approval artifact.

        Raises:
            ConflictError: An approval artifact already exists for this id.
            StorageError: The id is unsafe or a filesystem error occurred.
        """
        path = self._artifact_path(changeset_id, _APPROVAL_SUFFIX)
        self._ensure_changesets_dir()
        _exclusive_create_text(path, content)

    # ── Read operations ───────────────────────────────────────────────────

    def read_proposal(self, changeset_id: str) -> str:
        """Read a proposal artifact.

        Raises:
            NotFoundError: No proposal artifact exists for this id.
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        content = self.read_proposal_if_present(changeset_id)
        if content is None:
            raise NotFoundError(f"Proposal artifact not found: {changeset_id!r}")
        return content

    def read_proposal_if_present(self, changeset_id: str) -> str | None:
        """Read a proposal artifact, returning ``None`` when absent.

        Raises:
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        return self._read(changeset_id, _PROPOSAL_SUFFIX)

    def read_approval(self, changeset_id: str) -> str:
        """Read an approval artifact.

        Raises:
            NotFoundError: No approval artifact exists for this id.
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        content = self.read_approval_if_present(changeset_id)
        if content is None:
            raise NotFoundError(f"Approval artifact not found: {changeset_id!r}")
        return content

    def read_approval_if_present(self, changeset_id: str) -> str | None:
        """Read an approval artifact, returning ``None`` when absent.

        Raises:
            StorageError: The id is unsafe or the artifact is unreadable.
        """
        return self._read(changeset_id, _APPROVAL_SUFFIX)

    # ── Shared read ───────────────────────────────────────────────────────

    def _read(self, changeset_id: str, suffix: str) -> str | None:
        """Read one artifact, returning ``None`` when it does not exist."""
        self._validate_system_topology()
        path = self._artifact_path(changeset_id, suffix)

        if path.is_symlink():
            raise StorageError(f"Artifact leaf is a symlink, rejected for safety: {path}")

        if not path.exists():
            return None

        if not path.is_file():
            raise StorageError(f"Artifact is not a regular file: {path}")

        return _read_exact_text(path)


__all__ = ["ChangeSetStore", "ObsidianChangeSetStore"]
