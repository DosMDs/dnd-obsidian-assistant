"""S11-01 append-only processing-ledger storage.

Implements the ``PostSessionProcessingStore`` protocol for the durable,
append-only per-session processing ledger::

    <vault>/_system/raw/sessions/<session_id>/processing/ledger.jsonl

The ledger is durable session-local workflow/control evidence.  It is **not**
a campaign entity and it is **not** recorded in ``_system/audit/audit.jsonl``:
like the Stage-10 ``_system/changesets`` artifacts, it is append-only
provenance in its own right and carries no canonical Vault mutation.  This
keeps it outside global ``unresolved_audit_intent`` recovery, so it cannot
introduce a new R1-style global wedge.

The storage layer deals only in an opaque UTF-8 text payload.  Ledger event
parse/serialize/idempotency policy is an application concern; this module does
not import domain/application ledger types.

Safety properties:

- Vault root and ``_system/raw/sessions`` topology are validated and
  revalidated;
- the ledger path is derived deterministically from a validated ``session_id``
  (no caller-supplied path, no traversal, no escape);
- symlinked components and the ledger leaf are rejected;
- the ``processing/`` directory is created exclusively and never overwrites;
- appends preserve existing bytes exactly (never rewritten or truncated);
- reads are exact UTF-8 with newline preservation and fail closed on
  symlinks, directories, non-UTF-8 or unreadable content;
- a missing ledger reads as an explicit ``None`` (not-created state).

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.paths import _resolve_vault_root
from dnd_assistant.storage.session_paths import resolve_session_storage_paths

# ── Canonical layout ───────────────────────────────────────────────────────

_PROCESSING_DIR = "processing"
_LEDGER_FILE = "ledger.jsonl"


# ── Protocol ───────────────────────────────────────────────────────────────


@runtime_checkable
class PostSessionProcessingStore(Protocol):
    """Protocol for the durable, append-only processing ledger.

    The protocol owns safe placement of opaque UTF-8 ledger lines.  Event
    meaning, serialization, duplicate/idempotency policy and state folding are
    application concerns and are not part of this contract.
    """

    def append_ledger_line(self, session_id: str, content: str) -> None:
        """Append one complete ledger line to the session's ledger.

        Existing bytes are never rewritten or truncated.  The caller supplies
        one newline-terminated line.

        Raises:
            StorageError: The session id/path is unsafe, the session does not
                exist, or a filesystem error occurred.
        """
        ...

    def read_ledger_if_present(self, session_id: str) -> str | None:
        """Read the raw ledger text, or ``None`` when it has not been created.

        Raises:
            StorageError: The session id/path is unsafe, the session does not
                exist, or the ledger is a symlink/directory/non-UTF-8/unreadable.
        """
        ...

    def ledger_exists(self, session_id: str) -> bool:
        """Whether a regular ledger file currently exists for the session.

        Raises:
            StorageError: The session id/path is unsafe or the session does
                not exist.
        """
        ...


# ── ObsidianPostSessionProcessingStore ─────────────────────────────────────


class ObsidianPostSessionProcessingStore:
    """Filesystem-backed append-only processing-ledger store.

    Args:
        vault_root: The root directory of the Obsidian Vault.  It must exist,
            be a directory, and contain a real
            ``_system/raw/sessions`` directory.

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
        """Validate the ``_system/raw/sessions`` subtree is present/safe.

        Raises:
            StorageError: A required directory is missing, is a symlink, is not
                a directory, or resolves outside the Vault root.
        """
        relative_parts = (
            ("_system",),
            ("_system", "raw"),
            ("_system", "raw", "sessions"),
        )
        for parts in relative_parts:
            path = self._vault_root.joinpath(*parts)

            if path.is_symlink():
                raise StorageError(
                    f"Session processing path is a symlink, rejected for safety: {path}"
                )
            if not path.exists():
                raise StorageError(f"Session processing root does not exist: {path}")
            if not path.is_dir():
                raise StorageError(f"Session processing root is not a directory: {path}")

            try:
                path.resolve(strict=False).relative_to(self._vault_root)
            except ValueError:
                raise StorageError(
                    f"Session processing root resolves outside the Vault root: {path}"
                ) from None

    # ── Path resolution ───────────────────────────────────────────────────

    def _session_raw_dir(self, session_id: str) -> Path:
        """Resolve the validated raw session directory.

        Raises:
            StorageError: The session id is unsafe or the directory is missing,
                a symlink, or not a directory.
        """
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        raw_dir = paths.raw_dir

        if raw_dir.is_symlink():
            raise StorageError(
                f"Raw session directory is a symlink, rejected for safety: {raw_dir}"
            )
        if not raw_dir.exists():
            raise StorageError(f"Session {session_id!r} does not exist: {raw_dir}")
        if not raw_dir.is_dir():
            raise StorageError(f"Raw session path is not a directory: {raw_dir}")

        return raw_dir

    def _processing_dir(self, session_id: str) -> Path:
        """Return the (possibly not-yet-created) processing directory path."""
        processing = self._session_raw_dir(session_id) / _PROCESSING_DIR
        if processing.is_symlink():
            raise StorageError(
                f"Processing directory is a symlink, rejected for safety: {processing}"
            )
        return processing

    def _ledger_path(self, session_id: str) -> Path:
        """Return the validated ledger leaf path."""
        ledger = self._processing_dir(session_id) / _LEDGER_FILE
        if ledger.is_symlink():
            raise StorageError(f"Processing ledger is a symlink, rejected for safety: {ledger}")
        return ledger

    def _ensure_processing_dir(self, session_id: str) -> Path:
        """Create the processing directory if needed and return it safely.

        Raises:
            StorageError: The directory is unsafe or could not be created.
        """
        self._validate_topology()
        processing = self._processing_dir(session_id)

        if processing.exists():
            if not processing.is_dir():
                raise StorageError(f"Processing path exists but is not a directory: {processing}")
            return processing

        try:
            processing.mkdir(exist_ok=False)
        except FileExistsError:
            if processing.is_symlink() or not processing.is_dir():
                raise StorageError(
                    f"Processing directory appeared as an unsafe path: {processing}"
                ) from None
        except OSError as exc:
            raise StorageError(
                f"Failed to create processing directory: {processing}", cause=exc
            ) from exc

        if processing.is_symlink() or not processing.is_dir():
            raise StorageError(f"Processing directory is not a safe directory: {processing}")
        return processing

    # ── Append ────────────────────────────────────────────────────────────

    def append_ledger_line(self, session_id: str, content: str) -> None:
        """Append one complete newline-terminated ledger line.

        Raises:
            StorageError: The content is not newline-terminated, the path is
                unsafe, or a filesystem error occurred.
        """
        if not isinstance(content, str) or not content.endswith("\n"):
            raise StorageError("Processing ledger content must be a newline-terminated string")

        self._ensure_processing_dir(session_id)
        ledger = self._ledger_path(session_id)

        if ledger.exists() and not ledger.is_file():
            raise StorageError(f"Processing ledger is not a regular file: {ledger}")

        try:
            with open(ledger, mode="a", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise StorageError(
                f"Failed to append to processing ledger: {ledger}", cause=exc
            ) from exc

    # ── Read ──────────────────────────────────────────────────────────────

    def read_ledger_if_present(self, session_id: str) -> str | None:
        """Read the raw ledger text, or ``None`` when not created.

        Raises:
            StorageError: The path is unsafe or the ledger is unreadable.
        """
        processing = self._processing_dir(session_id)
        if not processing.exists():
            return None
        if not processing.is_dir():
            raise StorageError(f"Processing path is not a directory: {processing}")

        ledger = self._ledger_path(session_id)
        if not ledger.exists():
            return None
        if not ledger.is_file():
            raise StorageError(f"Processing ledger is not a regular file: {ledger}")

        try:
            with open(ledger, encoding="utf-8", newline="") as handle:
                return handle.read()
        except UnicodeDecodeError as exc:
            raise StorageError(
                f"Processing ledger contains invalid UTF-8: {ledger}", cause=exc
            ) from exc
        except OSError as exc:
            raise StorageError(f"Failed to read processing ledger: {ledger}", cause=exc) from exc

    def ledger_exists(self, session_id: str) -> bool:
        """Whether a regular ledger file currently exists for the session.

        Raises:
            StorageError: The path is unsafe or the ledger is a symlink.
        """
        processing = self._processing_dir(session_id)
        if not processing.exists() or not processing.is_dir():
            return False
        ledger = self._ledger_path(session_id)
        if ledger.is_symlink():
            raise StorageError(f"Processing ledger is a symlink, rejected for safety: {ledger}")
        return ledger.exists() and ledger.is_file()


__all__ = ["ObsidianPostSessionProcessingStore", "PostSessionProcessingStore"]
