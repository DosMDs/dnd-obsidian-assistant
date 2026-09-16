"""S11-06 immutable per-attempt post-session artifact storage.

Implements the ``PostSessionArtifactStore`` protocol for the durable,
immutable, per-attempt workflow artifacts::

    <vault>/_system/raw/sessions/<session_id>/processing/attempts/<attempt_id>/summary.md
    .../recap.md
    .../workflow.json

This module also owns the atomic **attempt claim**: the per-attempt directory is
created with ``mkdir(exist_ok=False)`` so that exactly one racer can own a
same-attempt execution.  The claim is synchronization/ownership infrastructure
only -- it is **not** processing-state authority (the append-only ledger is).
A claim directory that has no matching ``attempt_started`` ledger event is
uncertain pre-start evidence and makes that attempt id unusable (a new attempt
id is required); orphan claims are never deleted automatically.

Like the Stage-10 ``_system/changesets`` artifacts, these are workflow/control
state, not campaign entities and not audit-log records.  The storage layer deals
only in an opaque UTF-8 text payload and an opaque validated path key; artifact
semantics and hashing are application concerns.

Safety properties:

- Vault root and session-runtime topology are validated and revalidated;
- all paths are derived from a validated ``session_id`` + ``att_<32hex>``
  attempt id (no caller-supplied path, no traversal, no escape);
- symlinked components and artifact leaves are rejected;
- the attempt directory is created exclusively and never overwritten;
- artifacts are created exclusively (or accepted byte-identically) and never
  rewritten or truncated; a differing existing artifact is ``ConflictError``;
- reads are exact UTF-8 with newline preservation and fail closed on symlinks,
  directories or non-UTF-8 content.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai.
``dnd_assistant.domain`` is imported only for the durable artifact-kind enum.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from dnd_assistant.domain.post_session import PersistedArtifactKind
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.paths import _resolve_vault_root
from dnd_assistant.storage.session_paths import resolve_session_storage_paths

# ── Canonical layout ───────────────────────────────────────────────────────

_PROCESSING_DIR = "processing"
_ATTEMPTS_DIR = "attempts"

_ARTIFACT_FILENAMES: dict[PersistedArtifactKind, str] = {
    PersistedArtifactKind.SUMMARY: "summary.md",
    PersistedArtifactKind.RECAP: "recap.md",
    PersistedArtifactKind.WORKFLOW: "workflow.json",
}

_ATTEMPT_ID_RE = re.compile(r"^att_[0-9a-f]{32}$")


def _validate_attempt_id(attempt_id: str) -> str:
    """Validate a trusted attempt id as a single safe path component."""
    if not isinstance(attempt_id, str):
        raise StorageError("Attempt id must be a string")
    if not _ATTEMPT_ID_RE.match(attempt_id):
        raise StorageError("Attempt id must match att_<32 lowercase hex characters>")
    return attempt_id


# ── Protocol and result ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArtifactWriteResult:
    """Result of persisting one immutable artifact.

    ``created`` is ``True`` when a new artifact was written and ``False`` when
    an identical artifact already existed.  ``relative_path`` is the logical
    Vault-relative path (POSIX separators) recorded in the processing ledger.
    """

    created: bool
    relative_path: str


@runtime_checkable
class PostSessionArtifactStore(Protocol):
    """Protocol for the immutable per-attempt artifact store and claim."""

    def claim_attempt(self, session_id: str, attempt_id: str) -> bool:
        """Atomically claim the per-attempt directory.

        Returns ``True`` when this caller created the claim and ``False`` when
        it already existed.  ``False`` means the attempt is not owned by this
        caller and must not proceed.

        Raises:
            StorageError: The session/attempt id or path is unsafe, or the
                filesystem operation failed.
        """
        ...

    def persist_artifact(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
        text: str,
    ) -> ArtifactWriteResult:
        """Immutably persist one artifact.

        Requires an already-claimed attempt directory.  An absent artifact is
        exclusively created and verified; an existing byte-identical artifact
        is accepted without writing; a differing artifact is ``ConflictError``.

        Raises:
            ConflictError: An artifact for this slot already exists with
                different bytes.
            StorageError: The attempt is unclaimed/unsafe, or I/O failed.
        """
        ...

    def read_artifact_if_present(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> str | None:
        """Read an artifact, or ``None`` when it has not been created.

        Raises:
            StorageError: The path is unsafe or the artifact is unreadable.
        """
        ...

    def artifact_exists(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> bool:
        """Whether a regular artifact file exists for this slot.

        Raises:
            StorageError: The path is unsafe.
        """
        ...

    def expected_relative_path(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> str:
        """Return the logical Vault-relative path this slot maps to.

        Raises:
            StorageError: The path is unsafe.
        """
        ...


# ── ObsidianPostSessionArtifactStore ───────────────────────────────────────


class ObsidianPostSessionArtifactStore:
    """Filesystem-backed immutable per-attempt artifact store.

    Args:
        vault_root: The root directory of the Obsidian Vault.  It must exist,
            be a directory and contain a real ``_system/raw/sessions`` subtree.

    Raises:
        StorageError: The Vault root or session-runtime topology is invalid.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self._vault_root = _resolve_vault_root(vault_root)
        self._validate_topology()

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    # ── Topology ──────────────────────────────────────────────────────────

    def _validate_topology(self) -> None:
        relative_parts = (
            ("_system",),
            ("_system", "raw"),
            ("_system", "raw", "sessions"),
        )
        for parts in relative_parts:
            path = self._vault_root.joinpath(*parts)
            if path.is_symlink():
                raise StorageError(f"Session artifact path is a symlink, rejected: {path}")
            if not path.exists():
                raise StorageError(f"Session artifact root does not exist: {path}")
            if not path.is_dir():
                raise StorageError(f"Session artifact root is not a directory: {path}")
            try:
                path.resolve(strict=False).relative_to(self._vault_root)
            except ValueError:
                raise StorageError(
                    f"Session artifact root resolves outside the Vault root: {path}"
                ) from None

    def _raw_dir(self, session_id: str) -> Path:
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        raw_dir = paths.raw_dir
        if raw_dir.is_symlink():
            raise StorageError(f"Raw session directory is a symlink, rejected: {raw_dir}")
        if not raw_dir.exists():
            raise StorageError(f"Session {session_id!r} does not exist: {raw_dir}")
        if not raw_dir.is_dir():
            raise StorageError(f"Raw session path is not a directory: {raw_dir}")
        return raw_dir

    def _processing_dir(self, session_id: str) -> Path:
        processing = self._raw_dir(session_id) / _PROCESSING_DIR
        if processing.is_symlink():
            raise StorageError(f"Processing directory is a symlink, rejected: {processing}")
        return processing

    def _attempts_dir(self, session_id: str) -> Path:
        attempts = self._processing_dir(session_id) / _ATTEMPTS_DIR
        if attempts.is_symlink():
            raise StorageError(f"Attempts directory is a symlink, rejected: {attempts}")
        return attempts

    def _attempt_dir(self, session_id: str, attempt_id: str) -> Path:
        attempt = self._attempts_dir(session_id) / _validate_attempt_id(attempt_id)
        if attempt.is_symlink():
            raise StorageError(f"Attempt directory is a symlink, rejected: {attempt}")
        return attempt

    @staticmethod
    def _ensure_safe_dir(path: Path) -> None:
        """Create ``path`` if absent; require a safe directory if present."""
        if path.is_symlink():
            raise StorageError(f"Path is a symlink, rejected for safety: {path}")
        if path.exists():
            if not path.is_dir():
                raise StorageError(f"Path exists but is not a directory: {path}")
            return
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_dir():
                raise StorageError(f"Path appeared as an unsafe directory: {path}") from None
        except OSError as exc:
            raise StorageError(f"Failed to create directory: {path}", cause=exc) from exc
        if path.is_symlink() or not path.is_dir():
            raise StorageError(f"Path is not a safe directory: {path}")

    # ── Claim ─────────────────────────────────────────────────────────────

    def claim_attempt(self, session_id: str, attempt_id: str) -> bool:
        """Atomically claim the per-attempt directory (see protocol)."""
        _validate_attempt_id(attempt_id)
        self._validate_topology()
        self._ensure_safe_dir(self._processing_dir(session_id))
        self._ensure_safe_dir(self._attempts_dir(session_id))

        attempt = self._attempt_dir(session_id, attempt_id)
        if attempt.is_symlink():
            raise StorageError(f"Attempt directory is a symlink, rejected: {attempt}")
        if attempt.exists():
            if not attempt.is_dir():
                raise StorageError(f"Attempt path exists but is not a directory: {attempt}")
            return False
        try:
            attempt.mkdir(exist_ok=False)
        except FileExistsError:
            if attempt.is_symlink() or not attempt.is_dir():
                raise StorageError(
                    f"Attempt path appeared as an unsafe directory: {attempt}"
                ) from None
            return False
        except OSError as exc:
            raise StorageError(f"Failed to claim attempt directory: {attempt}", cause=exc) from exc
        return True

    # ── Persist ───────────────────────────────────────────────────────────

    def _required_attempt_dir(self, session_id: str, attempt_id: str) -> Path:
        """Return the already-claimed attempt directory or fail closed."""
        self._validate_topology()
        attempt = self._attempt_dir(session_id, attempt_id)
        if attempt.is_symlink():
            raise StorageError(f"Attempt directory is a symlink, rejected: {attempt}")
        if not attempt.exists():
            raise StorageError(f"Attempt directory has not been claimed: {attempt}")
        if not attempt.is_dir():
            raise StorageError(f"Attempt path is not a directory: {attempt}")
        return attempt

    def _artifact_path(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> Path:
        filename = _ARTIFACT_FILENAMES.get(artifact_kind)
        if filename is None:
            raise StorageError(f"Unsupported artifact kind: {artifact_kind!r}")
        return self._required_attempt_dir(session_id, attempt_id) / filename

    def _relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self._vault_root).as_posix()
        except ValueError:
            raise StorageError(f"Artifact path escapes the Vault root: {path}") from None

    def persist_artifact(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
        text: str,
    ) -> ArtifactWriteResult:
        """Immutably persist one artifact (see protocol)."""
        if not isinstance(text, str):
            raise StorageError("Artifact content must be a string")

        path = self._artifact_path(session_id, attempt_id, artifact_kind)
        relative = self._relative_path(path)

        if path.is_symlink():
            raise StorageError(f"Artifact leaf is a symlink, rejected: {path}")

        if path.exists():
            if not path.is_file():
                raise StorageError(f"Artifact path is not a regular file: {path}")
            if _read_exact_text(path) == text:
                return ArtifactWriteResult(created=False, relative_path=relative)
            raise ConflictError(f"Artifact already exists with different content: {relative}")

        try:
            with open(path, mode="x", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            # Lost a concurrent create race; re-check for an identical artifact.
            if path.is_symlink() or not path.is_file():
                raise StorageError(f"Artifact appeared as an unsafe path: {path}") from None
            if _read_exact_text(path) == text:
                return ArtifactWriteResult(created=False, relative_path=relative)
            raise ConflictError(
                f"Artifact already exists with different content: {relative}"
            ) from None
        except OSError as exc:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError(f"Failed to create artifact: {path}", cause=exc) from exc

        if _read_exact_text(path) != text:
            raise StorageError(f"Artifact read-back verification failed: {path}")
        return ArtifactWriteResult(created=True, relative_path=relative)

    # ── Read ──────────────────────────────────────────────────────────────

    def read_artifact_if_present(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> str | None:
        """Read an artifact, or ``None`` when absent (see protocol)."""
        attempt = self._attempt_dir(session_id, attempt_id)
        if not attempt.exists():
            return None
        path = self._artifact_path(session_id, attempt_id, artifact_kind)
        if path.is_symlink():
            raise StorageError(f"Artifact leaf is a symlink, rejected: {path}")
        if not path.exists():
            return None
        if not path.is_file():
            raise StorageError(f"Artifact path is not a regular file: {path}")
        return _read_exact_text(path)

    def artifact_exists(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> bool:
        """Whether a regular artifact file exists (see protocol)."""
        path = self._artifact_dir_for_read(session_id, attempt_id)
        if path is None:
            return False
        leaf = path / _ARTIFACT_FILENAMES[artifact_kind]
        if leaf.is_symlink():
            raise StorageError(f"Artifact leaf is a symlink, rejected: {leaf}")
        return leaf.exists() and leaf.is_file()

    def expected_relative_path(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: PersistedArtifactKind,
    ) -> str:
        """Return the logical Vault-relative path this slot maps to."""
        filename = _ARTIFACT_FILENAMES.get(artifact_kind)
        if filename is None:
            raise StorageError(f"Unsupported artifact kind: {artifact_kind!r}")
        attempt = self._attempt_dir(session_id, attempt_id)
        return self._relative_path(attempt / filename)

    def _artifact_dir_for_read(self, session_id: str, attempt_id: str) -> Path | None:
        attempt = self._attempt_dir(session_id, attempt_id)
        if not attempt.exists() or not attempt.is_dir():
            return None
        return attempt


def _read_exact_text(path: Path) -> str:
    """Read exact UTF-8 text with newline preservation."""
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise StorageError(f"Artifact contains invalid UTF-8: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to read artifact: {path}", cause=exc) from exc


__all__ = [
    "ArtifactWriteResult",
    "ObsidianPostSessionArtifactStore",
    "PostSessionArtifactStore",
]
