"""Raw session metadata persistence — ObsidianSessionMetadataRepository.

This module implements the filesystem-backed ``SessionMetadataRepository``
protocol for raw session metadata stored in:

    _system/raw/sessions/<session_id>/metadata.json

It composes:

- path safety (``resolve_session_storage_paths`` from ``session_paths.py``);
- atomic writes (``atomic_write_text``);
- audit persistence (``AuditService``, ``AuditRecord``).

This module belongs to the storage layer and must not import from:
    models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError
from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_paths import (
    resolve_session_storage_paths,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_AUDIT_SYSTEM_DIR = "_system"
_AUDIT_DIR = "audit"

# ── Session ID auto-allocation pattern ────────────────────────────────────────

_AUTO_ID_RE = re.compile(r"^S([0-9]+)$")

# ── Canonical Session field names (must never be overridden by extras) ────────

_CANONICAL_SESSION_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "id",
        "type",
        "status",
        "real_started_at",
        "real_finished_at",
        "world_tick_start",
        "world_tick_end",
        "processed",
        "processed_model_profile",
        "revision",
    }
)

# ── RawSessionMetadata ────────────────────────────────────────────────────────


class RawSessionMetadata:
    """Storage-level representation of raw session metadata.

    Wraps a validated canonical ``Session`` plus any unknown extra fields
    that were present in the JSON sidecar file.  Extra fields are preserved
    as-is but never interpreted as canonical ``Session`` fields.

    Args:
        session: The validated canonical ``Session``.
        extra_fields: Unknown fields from the raw JSON sidecar, preserved
            without interpretation.
    """

    def __init__(
        self,
        session: Session,
        extra_fields: dict[str, object] | None = None,
    ) -> None:
        self._session = session
        self._extra_fields = dict(extra_fields) if extra_fields else {}

    @property
    def session(self) -> Session:
        """The validated canonical ``Session``."""
        return self._session

    @property
    def extra_fields(self) -> dict[str, object]:
        """Unknown raw-sidecar fields preserved without interpretation.

        Returns a copy to prevent accidental mutation.
        """
        return dict(self._extra_fields)

    def __repr__(self) -> str:
        return (
            f"RawSessionMetadata(id={self._session.id!r}, "
            f"status={self._session.status!r}, "
            f"extra_fields={len(self._extra_fields)})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RawSessionMetadata):
            return NotImplemented
        return self._session == other._session and self._extra_fields == other._extra_fields

    def __hash__(self) -> int:
        # Session is not frozen, so hash on session id + extra fields
        return hash((self._session.id, frozenset(self._extra_fields.items())))


# ── Hash helper ───────────────────────────────────────────────────────────────


def _content_hash(text: str) -> str:
    """SHA-256 hash of the exact UTF-8 content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Serialization ─────────────────────────────────────────────────────────────


def _serialize(metadata: RawSessionMetadata) -> str:
    """Serialize ``RawSessionMetadata`` to deterministic JSON.

    The output is UTF-8, valid JSON, with one final newline.
    Canonical ``Session`` fields always win over extra fields.
    """
    session_data = metadata.session.model_dump(mode="json")
    merged = dict(session_data)
    for k, v in metadata.extra_fields.items():
        if k not in _CANONICAL_SESSION_FIELDS:
            merged[k] = v
    text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text + "\n"


def _deserialize(text: str, expected_id: str | None = None) -> RawSessionMetadata:
    """Deserialize ``RawSessionMetadata`` from JSON text.

    Args:
        text: The JSON text to parse.
        expected_id: If set, verify that the persisted ``session.id``
            matches this value.

    Returns:
        The validated ``RawSessionMetadata``.

    Raises:
        StorageError: The text is malformed JSON, has invalid canonical
            Session fields, or the session ID does not match the expected
            value.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(
            "session metadata: malformed JSON",
            cause=exc,
        ) from exc

    if not isinstance(data, dict):
        raise StorageError(f"session metadata: expected JSON object, got {type(data).__name__}")

    session_fields: dict[str, object] = {}
    extra_fields: dict[str, object] = {}
    for k, v in data.items():
        if k in _CANONICAL_SESSION_FIELDS:
            session_fields[k] = v
        else:
            extra_fields[k] = v

    try:
        session = Session.model_validate(session_fields)
    except Exception as exc:
        raise StorageError(
            "session metadata: invalid canonical Session fields",
            cause=exc,
        ) from exc

    if expected_id is not None and session.id != expected_id:
        raise StorageError(
            f"session metadata: id {session.id!r} does not match "
            f"expected directory name {expected_id!r}"
        )

    return RawSessionMetadata(session=session, extra_fields=extra_fields)


# ── Audit path validation ─────────────────────────────────────────────────────


def _validate_audit_path(vault_root: Path, audit_log_path: Path) -> None:
    """Verify the audit log path belongs beneath ``<vault_root>/_system/audit/``.

    Raises:
        StorageError: The audit log is outside the Vault, outside
            ``_system/audit/``, or a symlink is detected in the path.
    """
    try:
        relative = audit_log_path.relative_to(vault_root)
    except ValueError:
        raise StorageError(f"Audit log path is outside the Vault root: {audit_log_path}") from None

    for part in relative.parts:
        if part == "..":
            raise StorageError(
                f"Audit log path contains parent-directory traversal ('..'): {audit_log_path}"
            )

    expected_audit_dir = vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR

    accumulated = vault_root
    for part in relative.parts[:-1]:
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Audit path component is a symlink, rejected for safety: {accumulated}"
            )

    resolved = audit_log_path.resolve(strict=False)
    try:
        resolved.relative_to(vault_root)
    except ValueError:
        raise StorageError(
            f"Audit log path resolves outside the Vault root: {audit_log_path}"
        ) from None

    resolved_audit_dir = expected_audit_dir.resolve(strict=False)
    try:
        resolved.relative_to(resolved_audit_dir)
    except ValueError:
        raise StorageError(
            f"Audit log path must be beneath {expected_audit_dir}, "
            f"got: {audit_log_path} (resolved: {resolved})"
        ) from None


# ── Mutation environment validation ───────────────────────────────────────────


# ── Session runtime root validation ────────────────────────────────────────────

_SESSION_RUNTIME_ROOTS: tuple[str, ...] = (
    "Sessions",
    "_system",
    "_system/raw",
    "_system/raw/sessions",
    "_system/audit",
)


def _validate_session_runtime_roots(vault_root: Path) -> None:
    """Validate that canonical session runtime roots exist and are safe.

    Checks that each required root path:
    - is not a live or dangling symlink;
    - exists and is a directory;
    - resolves to a location beneath the canonical Vault root.

    Args:
        vault_root: The resolved Vault root path.

    Raises:
        StorageError: A root is missing, is a symlink, is a regular file,
            or resolves outside the Vault root.
    """
    for relative in _SESSION_RUNTIME_ROOTS:
        path = vault_root / relative

        # Check symlink identity FIRST — dangling symlinks have
        # is_symlink() == True but exists() == False.
        if path.is_symlink():
            raise StorageError(f"Session runtime root is a symlink, rejected for safety: {path}")

        if not path.exists():
            raise StorageError(f"Session runtime root does not exist: {path}")

        if not path.is_dir():
            raise StorageError(f"Session runtime root is not a directory: {path}")

        # Verify resolved path stays within vault root
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(vault_root)
        except ValueError:
            raise StorageError(
                f"Session runtime root resolves outside the Vault root: {path}"
            ) from None


# ── Exclusive-create for events.jsonl ─────────────────────────────────────────


def _create_exclusive_event_log(path: Path) -> None:
    """Create an empty ``events.jsonl`` file with exclusive-create semantics.

    The file is created only if it does not already exist.  Symlinks are
    rejected.  The file descriptor is flushed and fsynced before returning.

    Raises:
        ConflictError: The file already exists.
        StorageError: A filesystem error occurred.
    """
    if path.is_symlink():
        raise StorageError(f"events.jsonl is a symlink, rejected for safety: {path}")
    if path.exists():
        raise ConflictError(f"events.jsonl already exists: {path}")

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        try:
            os.fsync(fd)
        except OSError as exc:
            raise StorageError(
                f"Failed to fsync events.jsonl: {path}",
                cause=exc,
            ) from exc
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
    except FileExistsError:
        raise ConflictError(f"events.jsonl already exists: {path}") from None
    except OSError as exc:
        raise StorageError(
            f"Failed to create events.jsonl: {path}",
            cause=exc,
        ) from exc


# ── Audit record builder ──────────────────────────────────────────────────────


def _build_audit_record(
    *,
    operation_id: str,
    real_time,
    operation: str,
    before_hash: str | None,
    after_hash: str | None,
    source: str,
    session: str | None = None,
    model_profile: str | None = None,
    prompt_version: str | None = None,
    phase: str = "committed",
):
    """Build an ``AuditRecord`` for a session metadata mutation."""
    from dnd_assistant.storage.audit import AuditRecord

    return AuditRecord(
        operation_id=operation_id,
        real_time=real_time,
        operation=operation,
        entity_id=None,
        before_hash=before_hash,
        after_hash=after_hash,
        source=source,
        session=session,
        model_profile=model_profile,
        prompt_version=prompt_version,
        phase=phase,
    )


def _validate_mutation_environment(vault_root: Path, audit_service: AuditService) -> None:
    """Validate the current mutation environment is still safe.

    Raises:
        StorageError: The mutation environment is unsafe.
    """
    audit_log_path = audit_service.log_path

    try:
        relative = audit_log_path.relative_to(vault_root)
    except ValueError:
        raise StorageError(f"Audit log path is outside the Vault root: {audit_log_path}") from None

    for part in relative.parts:
        if part == "..":
            raise StorageError(
                f"Audit log path contains parent-directory traversal ('..'): {audit_log_path}"
            )

    expected_audit_dir = vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR
    accumulated = vault_root
    for part in relative.parts[:-1]:
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Audit path component became a symlink after construction, "
                f"rejected for safety: {accumulated}"
            )

    if audit_log_path.is_symlink():
        raise StorageError(f"Audit log path became a symlink after construction: {audit_log_path}")

    if not expected_audit_dir.is_dir():
        raise StorageError(f"Canonical audit directory no longer exists: {expected_audit_dir}")


# ── ObsidianSessionMetadataRepository ─────────────────────────────────────────


class ObsidianSessionMetadataRepository:
    """Concrete session metadata repository backed by ``_system/raw/sessions/``.

    Owns read, create, list, and active-session discovery operations for raw
    session metadata sidecar files.

    Args:
        vault_root: The root directory of the Obsidian Vault.
        audit_service: The audit service for logging mutations.

    Raises:
        StorageError: The Vault root is invalid, or the audit path is
            misconfigured.
    """

    def __init__(
        self,
        vault_root: str | Path,
        audit_service: AuditService,
    ) -> None:
        self._vault_root = Path(vault_root).resolve(strict=False)
        if not self._vault_root.is_dir():
            raise StorageError(f"Vault root must be an existing directory: {self._vault_root}")

        self._audit_service = audit_service

        _validate_audit_path(self._vault_root, audit_service.log_path)

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    # ── ID allocation ──────────────────────────────────────────────────────

    def allocate_next_session_id(self) -> str:
        """Allocate the next automatic session ID.

        Validates that canonical session runtime roots exist, then scans
        both ``Sessions/`` and ``_system/raw/sessions/`` for existing
        numeric IDs matching ``^S[0-9]+$`` and returns the next value
        formatted with minimum 3 digits.
        """
        _validate_session_runtime_roots(self._vault_root)
        occupied = self._discover_occupied_numeric_ids()

        if not occupied:
            return "S001"

        next_num = max(occupied) + 1
        return f"S{next_num:03d}"

    def _discover_occupied_numeric_ids(self) -> set[int]:
        """Discover occupied numeric session IDs from both session trees.

        Returns:
            A set of integer IDs (e.g. ``{1, 5}`` for S001 and S005).

        Raises:
            StorageError: A symlink or path-safety error occurred.
        """
        occupied: set[int] = set()
        vault_root = self._vault_root

        sessions_root = vault_root / "Sessions"
        raw_root = vault_root / "_system" / "raw" / "sessions"

        for parent in (sessions_root, raw_root):
            # Check symlink BEFORE exists() — dangling symlinks have
            # is_symlink() == True but exists() == False.
            if parent.is_symlink():
                raise StorageError(
                    f"Session parent directory is a symlink, rejected for safety: {parent}"
                )
            if not parent.exists():
                continue
            if not parent.is_dir():
                continue

            try:
                entries = list(parent.iterdir())
            except OSError as exc:
                raise StorageError(
                    f"Failed to list session directory: {parent}",
                    cause=exc,
                ) from exc

            for entry in entries:
                # Check symlink BEFORE is_dir — dangling symlinks have
                # is_symlink() == True but is_dir() == False.
                if entry.is_symlink():
                    raise StorageError(f"Session entry is a symlink, rejected for safety: {entry}")
                if not entry.is_dir():
                    continue
                m = _AUTO_ID_RE.match(entry.name)
                if m:
                    occupied.add(int(m.group(1)))

        return occupied

    # ── Create ─────────────────────────────────────────────────────────────

    def create_session(
        self,
        session: Session,
        *,
        audit: AuditContext,
    ) -> RawSessionMetadata:
        """Persist a new raw session metadata record.

        Creates session directories, initializes an empty ``events.jsonl``,
        and atomically writes ``metadata.json``.
        """
        _validate_session_runtime_roots(self._vault_root)
        session_id = session.id

        paths = resolve_session_storage_paths(self._vault_root, session_id)
        _validate_mutation_environment(self._vault_root, self._audit_service)

        candidate = RawSessionMetadata(session=session)
        serialized = _serialize(candidate)
        after_hash = _content_hash(serialized)

        # Audit intent
        intent_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.start",
            before_hash=None,
            after_hash=after_hash,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="intent",
        )
        self._audit_service.append(intent_record)

        # Reauthorize paths after durable intent
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # Check for existing session directories
        if paths.session_dir.exists():
            raise ConflictError(f"Session directory already exists: {paths.session_dir}")
        if paths.raw_dir.exists():
            raise ConflictError(f"Raw session directory already exists: {paths.raw_dir}")

        # Check leaf paths for pre-existing symlinks
        if paths.session_md.is_symlink():
            raise StorageError(f"Session.md is a symlink, rejected for safety: {paths.session_md}")
        if paths.raw_metadata.is_symlink():
            raise StorageError(
                f"metadata.json is a symlink, rejected for safety: {paths.raw_metadata}"
            )
        if paths.raw_events.is_symlink():
            raise StorageError(
                f"events.jsonl is a symlink, rejected for safety: {paths.raw_events}"
            )

        # Create session directories (leaf-only — canonical parents must already exist)
        try:
            paths.session_dir.mkdir(exist_ok=False)
        except FileExistsError:
            raise ConflictError(f"Session directory already exists: {paths.session_dir}") from None
        except OSError as exc:
            raise StorageError(
                f"Failed to create session directory: {paths.session_dir}",
                cause=exc,
            ) from exc

        try:
            paths.raw_dir.mkdir(exist_ok=False)
        except FileExistsError:
            raise ConflictError(f"Raw session directory already exists: {paths.raw_dir}") from None
        except OSError as exc:
            raise StorageError(
                f"Failed to create raw session directory: {paths.raw_dir}",
                cause=exc,
            ) from exc

        # Create empty events.jsonl with exclusive-create semantics
        _create_exclusive_event_log(paths.raw_events)

        # Atomic write metadata.json with parse validator
        atomic_write_text(
            target=paths.raw_metadata,
            content=serialized,
            validator=lambda c: _deserialize(c),
        )

        # Verified read-back
        persisted_text = _read_exact_text(paths.raw_metadata)
        persisted_hash = _content_hash(persisted_text)
        if persisted_hash != after_hash:
            raise StorageError(
                f"Session metadata mutation committed but hash verification failed "
                f"for operation {audit.operation_id}"
            )

        persisted = _deserialize(persisted_text, expected_id=session_id)

        # Verify persisted fields match candidate
        if persisted.session.id != session_id:
            raise StorageError(
                f"Session metadata mutation committed but id changed "
                f"for operation {audit.operation_id}"
            )
        if persisted.session.status != session.status:
            raise StorageError(
                f"Session metadata mutation committed but status changed "
                f"for operation {audit.operation_id}"
            )
        if persisted.session.world_tick_start != session.world_tick_start:
            raise StorageError(
                f"Session metadata mutation committed but world_tick_start changed "
                f"for operation {audit.operation_id}"
            )
        if persisted.session.revision != session.revision:
            raise StorageError(
                f"Session metadata mutation committed but revision changed "
                f"for operation {audit.operation_id}"
            )

        # Append committed audit record
        committed_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.start",
            before_hash=None,
            after_hash=after_hash,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="committed",
        )
        try:
            self._audit_service.append(committed_record)
        except StorageError as exc:
            raise StorageError(
                f"Session metadata mutation committed but audit finalization failed "
                f"for operation {audit.operation_id}.  "
                f"The mutated files exist in {paths.raw_dir}.  "
                f"An intent audit record is present.",
                cause=exc,
            ) from exc

        return persisted

    # ── Read ───────────────────────────────────────────────────────────────

    def get_session_metadata(
        self,
        session_id: str,
    ) -> RawSessionMetadata:
        """Read raw session metadata for a specific session."""
        _validate_session_runtime_roots(self._vault_root)
        paths = resolve_session_storage_paths(self._vault_root, session_id)

        if not paths.raw_metadata.exists():
            raise NotFoundError(f"Session metadata not found for {session_id}")

        text = _read_exact_text(paths.raw_metadata)
        return _deserialize(text, expected_id=session_id)

    # ── List ──────────────────────────────────────────────────────────────

    def list_session_metadata(self) -> list[RawSessionMetadata]:
        """List all raw session metadata records, sorted by session ID."""
        _validate_session_runtime_roots(self._vault_root)
        raw_root = self._vault_root / "_system" / "raw" / "sessions"

        # Check symlink identity BEFORE exists() — dangling symlinks have
        # is_symlink() == True but exists() == False.
        if raw_root.is_symlink():
            raise StorageError(
                f"Raw sessions directory is a symlink, rejected for safety: {raw_root}"
            )
        if not raw_root.exists():
            return []
        if not raw_root.is_dir():
            raise StorageError(f"Raw sessions path is not a directory: {raw_root}")

        try:
            entries = sorted(raw_root.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            raise StorageError(
                f"Failed to list raw sessions directory: {raw_root}",
                cause=exc,
            ) from exc

        results: list[RawSessionMetadata] = []
        for entry in entries:
            # Check symlink BEFORE is_dir — dangling symlinks have
            # is_symlink() == True but is_dir() == False.
            if entry.is_symlink():
                raise StorageError(f"Raw session entry is a symlink, rejected for safety: {entry}")
            if not entry.is_dir():
                continue

            # Use the canonical path resolver for safe path resolution
            paths = resolve_session_storage_paths(self._vault_root, entry.name)

            # Verify the resolved raw_dir matches the discovered entry
            if paths.raw_dir != entry.resolve(strict=False):
                raise StorageError(f"Raw session entry {entry.name} resolved path mismatch")

            # Reject leaf symlinks
            if paths.raw_metadata.is_symlink():
                raise StorageError(
                    f"metadata.json is a symlink, rejected for safety: {paths.raw_metadata}"
                )

            if not paths.raw_metadata.exists():
                raise StorageError(f"Raw session directory {entry.name} is missing metadata.json")

            text = _read_exact_text(paths.raw_metadata)
            meta = _deserialize(text, expected_id=entry.name)
            results.append(meta)

        return results

    # ── Active session ────────────────────────────────────────────────────

    def get_active_session(self) -> RawSessionMetadata | None:
        """Return the active session metadata, if exactly one exists.

        An active session is identified by ``session.status == \"active\"``.
        """
        all_meta = self.list_session_metadata()
        active = [m for m in all_meta if m.session.status == "active"]

        if len(active) == 0:
            return None
        if len(active) == 1:
            return active[0]

        raise ConflictError(
            f"Multiple active sessions found ({len(active)}): "
            + ", ".join(m.session.id for m in active)
        )


# ── Exact text reader ─────────────────────────────────────────────────────────


def _read_exact_text(path: Path) -> str:
    """Read a file's text content with exact newline preservation.

    Raises:
        StorageError: The file could not be read or contains invalid UTF-8.
    """
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        raise
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"Invalid UTF-8 in session metadata: {path}",
            cause=exc,
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"Failed to read session metadata: {path}",
            cause=exc,
        ) from exc
