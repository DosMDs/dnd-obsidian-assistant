"""Concrete Obsidian world-time repository — read, initialize, and update.

This module implements the filesystem-backed ``WorldTimeRepository``
protocol for the canonical ``_system/world_time.json`` state file.

It composes:

- path safety (``_resolve_vault_root`` from ``paths.py``);
- atomic writes (``atomic_write_text``);
- audit persistence (``AuditService``, ``AuditRecord``).

This module belongs to the storage layer and must not import from:
    models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path

from pydantic import TypeAdapter

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.types import Revision
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.paths import _resolve_vault_root

# ── TypeAdapters for runtime validation ───────────────────────────────────────

_WORLD_TICK_ADAPTER = TypeAdapter(WorldTick)
"""TypeAdapter for canonical WorldTick runtime validation."""

_REVISION_ADAPTER = TypeAdapter(Revision)
"""TypeAdapter for canonical Revision runtime validation."""

# ── Constants ─────────────────────────────────────────────────────────────────

_WORLD_TIME_RELATIVE = Path("_system") / "world_time.json"
"""Canonical relative path for world_time.json beneath the Vault root."""

_AUDIT_SYSTEM_DIR = "_system"
_AUDIT_DIR = "audit"
"""Expected audit directory path components beneath the Vault root."""

# ── Hash helper ───────────────────────────────────────────────────────────────


def _content_hash(text: str) -> str:
    """SHA-256 hash of the exact UTF-8 content.

    Args:
        text: The exact serialised JSON text.

    Returns:
        Hex digest of the SHA-256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Serialization ─────────────────────────────────────────────────────────────


def _serialize(state: CurrentWorldTime) -> str:
    """Serialize a ``CurrentWorldTime`` to deterministic JSON.

    The output is UTF-8, valid JSON, with one final newline.

    Args:
        state: The ``CurrentWorldTime`` to serialize.

    Returns:
        A JSON string ending with ``\\n``.
    """
    data = state.model_dump(mode="json")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text + "\n"


def _deserialize(text: str) -> CurrentWorldTime:
    """Deserialize a ``CurrentWorldTime`` from JSON text.

    Args:
        text: The JSON text to parse.

    Returns:
        The validated ``CurrentWorldTime``.

    Raises:
        StorageError: The text is malformed JSON, has an invalid schema,
            or contains invalid field values.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(
            "world_time.json: malformed JSON",
            cause=exc,
        ) from exc

    if not isinstance(data, dict):
        raise StorageError(f"world_time.json: expected JSON object, got {type(data).__name__}")

    try:
        return CurrentWorldTime.model_validate(data)
    except Exception as exc:
        raise StorageError(
            "world_time.json: invalid CurrentWorldTime schema",
            cause=exc,
        ) from exc


# ── Path resolution ───────────────────────────────────────────────────────────


def _resolve_world_time_path(vault_root: str | Path) -> Path:
    """Resolve the canonical ``_system/world_time.json`` path.

    Validates the Vault root and returns the absolute canonical location.
    Does NOT create the file or its parent directory.

    Args:
        vault_root: The root directory of the Obsidian Vault.

    Returns:
        The absolute path to ``_system/world_time.json``.

    Raises:
        StorageError: The Vault root is invalid.
    """
    root = _resolve_vault_root(vault_root)
    return root / _WORLD_TIME_RELATIVE


# ── Mutation mode ─────────────────────────────────────────────────────────────


class _MutationMode(Enum):
    """Typed mode for ``_commit_mutation`` second-check semantics."""

    INITIALIZE = "initialize"
    """Expect the file to be absent before commit; a newly appeared regular
    file or symlink is a conflict."""

    UPDATE = "update"
    """Expect the file to exist with a known before-hash; content change
    between intent and write is a conflict."""


# ── World-time path reauthorization ───────────────────────────────────────────


def _reauthorize_world_time_path(vault_root: Path, world_time_path: Path) -> Path:
    """Reauthorize the canonical world-time path against current filesystem topology.

    Verifies that:
    - ``vault_root`` is still a valid canonical root;
    - the lexical relative path is exactly ``_system/world_time.json``;
    - ``_system`` is not a live or dangling symlink;
    - ``world_time.json`` is not a live or dangling symlink;
    - the resolved path remains under the Vault root;
    - the resolved path is the exact canonical location.

    A safe missing regular ``world_time.json`` leaf is allowed — the caller
    distinguishes that case from unsafe symlink conditions.

    Args:
        vault_root: The resolved Vault root path.
        world_time_path: The canonical absolute ``world_time.json`` path.

    Returns:
        The reauthorized canonical path (same as ``world_time_path`` on
        success).

    Raises:
        StorageError: Any topology check fails.
    """
    # 1. Vault root must still be a directory
    if not vault_root.is_dir():
        raise StorageError(f"Vault root is no longer a directory: {vault_root}")

    # 2. Lexical relative path must be exactly _system/world_time.json
    try:
        relative = world_time_path.relative_to(vault_root)
    except ValueError:
        raise StorageError(f"World-time path is not under Vault root: {world_time_path}") from None

    expected_relative = _WORLD_TIME_RELATIVE
    if relative != expected_relative:
        raise StorageError(
            f"World-time path is not the canonical location: "
            f"expected {expected_relative}, got {relative}"
        )

    # 3. Check _system component (must not be a symlink)
    system_path = vault_root / "_system"
    if system_path.is_symlink():
        raise StorageError(
            f"World-time _system/ component is a symlink, rejected for safety: {system_path}"
        )

    # 4. Check world_time.json leaf (must not be a symlink — live or dangling)
    if world_time_path.is_symlink():
        raise StorageError(
            f"World-time leaf path is a symlink, rejected for safety: {world_time_path}"
        )

    # 5. Resolve and verify containment under Vault root
    resolved = world_time_path.resolve(strict=False)
    try:
        resolved.relative_to(vault_root)
    except ValueError:
        raise StorageError(
            f"World-time path resolves outside the Vault root: {world_time_path} -> {resolved}"
        ) from None

    # 6. Resolved path must match the canonical location
    resolved_relative = resolved.relative_to(vault_root)
    if resolved_relative != expected_relative:
        raise StorageError(
            f"World-time path resolves to a non-canonical location: "
            f"expected {expected_relative}, got {resolved_relative}"
        )

    return world_time_path


# ── Audit path validation ─────────────────────────────────────────────────────


def _validate_audit_path(vault_root: Path, audit_log_path: Path) -> None:
    """Verify the audit log path belongs beneath ``<vault_root>/_system/audit/``.

    Args:
        vault_root: The resolved Vault root path.
        audit_log_path: The absolute audit-log file path.

    Raises:
        StorageError: The audit log is outside the Vault, outside
            ``_system/audit/``, or a symlink is detected in the path.
    """
    # Verify lexical containment
    try:
        relative = audit_log_path.relative_to(vault_root)
    except ValueError:
        raise StorageError(f"Audit log path is outside the Vault root: {audit_log_path}") from None

    # Reject parent traversal
    for part in relative.parts:
        if part == "..":
            raise StorageError(
                f"Audit log path contains parent-directory traversal ('..'): {audit_log_path}"
            )

    # Establish canonical expected audit directory
    expected_audit_dir = vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR

    # Inspect existing path components beneath vault_root for symlinks
    accumulated = vault_root
    for part in relative.parts[:-1]:  # exclude the filename
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Audit path component is a symlink, rejected for safety: {accumulated}"
            )

    # Resolve and verify containment
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


def _validate_mutation_environment(vault_root: Path, audit_service: AuditService) -> None:
    """Validate the current mutation environment is still safe.

    Called before every mutation to ensure the audit path topology has
    not been compromised since repository construction.

    Args:
        vault_root: The resolved Vault root path.
        audit_service: The audit service whose log path to validate.

    Raises:
        StorageError: The mutation environment is unsafe.
    """
    audit_log_path = audit_service.log_path

    # Verify audit log path is still lexically beneath vault_root
    try:
        relative = audit_log_path.relative_to(vault_root)
    except ValueError:
        raise StorageError(f"Audit log path is outside the Vault root: {audit_log_path}") from None

    for part in relative.parts:
        if part == "..":
            raise StorageError(
                f"Audit log path contains parent-directory traversal ('..'): {audit_log_path}"
            )

    # Inspect each existing path component beneath vault_root for symlinks
    expected_audit_dir = vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR
    accumulated = vault_root
    for part in relative.parts[:-1]:  # exclude filename
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Audit path component became a symlink after construction, "
                f"rejected for safety: {accumulated}"
            )

    # Audit log itself must not be a symlink
    if audit_log_path.is_symlink():
        raise StorageError(f"Audit log path became a symlink after construction: {audit_log_path}")

    # Canonical _system/audit/ directory must still exist and be a real dir
    if not expected_audit_dir.is_dir():
        raise StorageError(f"Canonical audit directory no longer exists: {expected_audit_dir}")


# ── Exact text reader ─────────────────────────────────────────────────────────


def _read_exact_text(path: Path) -> str:
    """Read a file's text content with exact newline preservation.

    Args:
        path: The file path to read.

    Returns:
        The exact text content.

    Raises:
        StorageError: The file could not be read or contains invalid UTF-8.
    """
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        raise  # Let caller translate to NotFoundError
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"Invalid UTF-8 in world_time.json: {path}",
            cause=exc,
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"Failed to read world_time.json: {path}",
            cause=exc,
        ) from exc


# ── Input validation helpers ──────────────────────────────────────────────────


def _validate_world_tick_input(world_tick: object) -> int:
    """Validate an externally supplied world_tick at runtime.

    Delegates to the canonical ``WorldTick`` type via ``TypeAdapter``.
    Invalid input raises ``ValidationError`` rather than producing a
    generic error.

    Args:
        world_tick: The value to validate.

    Returns:
        The validated tick integer.

    Raises:
        ValidationError: The value is not a valid ``WorldTick``.
    """
    try:
        validated = _WORLD_TICK_ADAPTER.validate_python(world_tick)
    except Exception as exc:
        raise ValidationError(
            f"Invalid WorldTick: {world_tick!r}",
            cause=exc,
        ) from exc
    return validated


def _validate_revision_input(revision: object) -> int:
    """Validate an externally supplied revision at runtime.

    Delegates to the canonical ``Revision`` type via ``TypeAdapter``.
    Invalid input raises ``ValidationError``.

    Args:
        revision: The revision value to validate.

    Returns:
        The validated revision integer.

    Raises:
        ValidationError: The value is not a valid ``Revision``.
    """
    try:
        validated = _REVISION_ADAPTER.validate_python(revision)
    except Exception as exc:
        raise ValidationError(
            f"Invalid Revision: {revision!r}",
            cause=exc,
        ) from exc
    return validated


# ── Shared mutation commit helper ─────────────────────────────────────────────


def _commit_mutation(
    world_time_path: Path,
    candidate: CurrentWorldTime,
    *,
    before_hash: str | None,
    mode: _MutationMode,
    audit: AuditContext,
    operation: str,
    vault_root: Path,
    audit_service: AuditService,
) -> CurrentWorldTime:
    """Commit a world-time mutation with audit intent, second check,
    atomic write, verified read-back, and committed audit.

    Args:
        world_time_path: The canonical ``world_time.json`` path.
        candidate: The desired new ``CurrentWorldTime``.
        before_hash: The hash of the content before mutation (``None``
            for initialize).
        mode: Mutation mode — ``INITIALIZE`` or ``UPDATE``.
        audit: Audit context for this mutation.
        operation: The operation name for audit records.
        vault_root: The resolved Vault root path.
        audit_service: The audit service for persisting records.

    Returns:
        The persisted ``CurrentWorldTime`` after the mutation.

    Raises:
        ConflictError: Content changed between intent and write.
        StorageError: A filesystem or audit operation failed.
    """
    # Serialize
    serialized = _serialize(candidate)

    # Compute after hash
    after_hash = _content_hash(serialized)

    # Append audit intent record
    intent_record = _build_audit_record(
        operation_id=audit.operation_id,
        real_time=audit.real_time,
        operation=operation,
        before_hash=before_hash,
        after_hash=after_hash,
        source=audit.source,
        session=audit.session,
        model_profile=audit.model_profile,
        prompt_version=audit.prompt_version,
        phase="intent",
    )
    audit_service.append(intent_record)

    # ── Mutation-time reauthorization ────────────────────────────────
    # After durable intent, revalidate environment and target path.

    # a. Mutation environment is still safe
    _validate_mutation_environment(vault_root, audit_service)

    # b. Reauthorize world_time.json path against current topology
    _reauthorize_world_time_path(vault_root, world_time_path)

    # c. Second check — verify content hasn't changed since intent
    if mode == _MutationMode.UPDATE:
        # Update: expect file to exist with matching hash
        try:
            with open(world_time_path, encoding="utf-8", newline="") as f:
                current_text = f.read()
        except OSError as exc:
            raise StorageError(
                f"world_time.json became unreadable for operation {audit.operation_id}: {world_time_path}",
                cause=exc,
            ) from exc

        current_hash = _content_hash(current_text)
        if current_hash != before_hash:
            raise ConflictError(
                f"world_time.json content changed after intent for operation {audit.operation_id}"
            )
    elif mode == _MutationMode.INITIALIZE:
        # Initialize: expect file to remain absent (safe missing)
        if world_time_path.is_symlink():
            raise StorageError(
                f"world_time.json became a symlink after intent for operation {audit.operation_id}"
            )
        if world_time_path.exists():
            raise ConflictError(
                f"world_time.json appeared after intent for operation {audit.operation_id}"
            )

    # Atomic write with candidate validator
    atomic_write_text(
        target=world_time_path,
        content=serialized,
        validator=lambda c: _deserialize(c),
    )

    # Re-read and verify persisted content
    try:
        with open(world_time_path, encoding="utf-8", newline="") as f:
            persisted_text = f.read()
    except OSError as exc:
        raise StorageError(
            f"Mutation committed but read-back failed for operation {audit.operation_id}: {exc}",
        ) from exc

    persisted_hash = _content_hash(persisted_text)
    if persisted_hash != after_hash:
        raise StorageError(
            f"Mutation committed but hash verification failed for "
            f"operation {audit.operation_id}: "
            f"expected {after_hash}, got {persisted_hash}"
        )

    try:
        persisted = _deserialize(persisted_text)
    except StorageError as exc:
        raise StorageError(
            f"Mutation committed but re-parsed state is invalid for operation {audit.operation_id}",
            cause=exc,
        ) from exc

    # Verify schema_version, type, current_world_tick, revision
    if persisted.schema_version != candidate.schema_version:
        raise StorageError(
            f"Mutation committed but schema_version changed for operation {audit.operation_id}"
        )
    if persisted.type != candidate.type:
        raise StorageError(
            f"Mutation committed but type changed for operation {audit.operation_id}"
        )
    if persisted.current_world_tick != candidate.current_world_tick:
        raise StorageError(
            f"Mutation committed but current_world_tick changed for operation {audit.operation_id}"
        )
    if persisted.revision != candidate.revision:
        raise StorageError(
            f"Mutation committed but revision changed for operation {audit.operation_id}: "
            f"expected {candidate.revision}, got {persisted.revision}"
        )

    # Append committed audit record
    committed_record = _build_audit_record(
        operation_id=audit.operation_id,
        real_time=audit.real_time,
        operation=operation,
        before_hash=before_hash,
        after_hash=after_hash,
        source=audit.source,
        session=audit.session,
        model_profile=audit.model_profile,
        prompt_version=audit.prompt_version,
        phase="committed",
    )
    try:
        audit_service.append(committed_record)
    except StorageError as exc:
        raise StorageError(
            f"World-time mutation committed but audit finalization failed "
            f"for operation {audit.operation_id}.  "
            f"The mutated file exists at {world_time_path}.  "
            f"An intent audit record is present.",
            cause=exc,
        ) from exc

    return persisted


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
    """Build an ``AuditRecord`` for a world-time mutation."""
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


# ── ObsidianWorldTimeRepository ───────────────────────────────────────────────


class ObsidianWorldTimeRepository:
    """Concrete world-time repository backed by ``_system/world_time.json``.

    Owns read, initialize-once, and optimistic-update operations for the
    canonical current-world-time state file.

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

        # Resolve canonical world_time.json path
        self._world_time_path = _resolve_world_time_path(self._vault_root)

        # Validate audit path belongs to this Vault
        _validate_audit_path(self._vault_root, audit_service.log_path)

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    @property
    def world_time_path(self) -> Path:
        """The canonical absolute path to ``_system/world_time.json``."""
        return self._world_time_path

    # ── Read ──────────────────────────────────────────────────────────────

    def get_current_world_time(self) -> CurrentWorldTime:
        """Read the canonical current world time.

        Returns:
            The validated ``CurrentWorldTime`` from the Vault.

        Raises:
            NotFoundError: No ``world_time.json`` exists.
            StorageError: The file is corrupt, malformed, or unreadable.
        """
        path = self._world_time_path

        # Reauthorize canonical topology before any read
        _reauthorize_world_time_path(self._vault_root, path)

        if not path.exists():
            raise NotFoundError(
                "world_time.json not found \u2014 current world time has not been initialized"
            )

        text = _read_exact_text(path)
        return _deserialize(text)

    # ── Initialize ────────────────────────────────────────────────────────

    def initialize_current_world_time(
        self,
        world_tick: object,
        *,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        """Initialize world time state with revision 1.

        This operation is valid only when no ``world_time.json`` exists.

        Args:
            world_tick: The canonical starting world tick.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``CurrentWorldTime`` with revision 1.

        Raises:
            ConflictError: State already exists (no silent overwrite).
            ValidationError: The ``world_tick`` is invalid.
            StorageError: A filesystem or audit operation failed.
        """
        # Validate world_tick
        validated_tick = _validate_world_tick_input(world_tick)

        # Validate mutation environment
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # Verify _system/ directory exists
        system_dir = self._vault_root / _AUDIT_SYSTEM_DIR
        if not system_dir.is_dir():
            raise StorageError(f"Canonical _system/ directory does not exist: {system_dir}")

        # Reauthorize canonical world-time path before existence decision
        path = self._world_time_path
        _reauthorize_world_time_path(self._vault_root, path)

        # Verify world_time.json does NOT already exist (safe missing only)
        if path.exists():
            raise ConflictError(
                "world_time.json already exists \u2014 use set_current_world_time to update"
            )

        # Build candidate state
        candidate = CurrentWorldTime(
            schema_version=1,
            type="world_time",
            current_world_tick=validated_tick,
            revision=1,
        )

        return _commit_mutation(
            world_time_path=path,
            candidate=candidate,
            before_hash=None,
            mode=_MutationMode.INITIALIZE,
            audit=audit,
            operation="world_time.initialize",
            vault_root=self._vault_root,
            audit_service=self._audit_service,
        )

    # ── Update ────────────────────────────────────────────────────────────

    def set_current_world_time(
        self,
        world_tick: object,
        *,
        expected_revision: object,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        """Update the current world time with optimistic concurrency.

        Args:
            world_tick: The new canonical world tick.
            expected_revision: The revision the caller last observed.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``CurrentWorldTime`` with incremented revision.

        Raises:
            NotFoundError: No ``world_time.json`` exists.
            ConflictError: The stored revision does not match
                ``expected_revision``.
            ValidationError: The ``world_tick`` or ``expected_revision``
                is invalid.
            StorageError: A filesystem or audit operation failed.
        """
        # Validate inputs
        validated_tick = _validate_world_tick_input(world_tick)
        validated_expected_revision = _validate_revision_input(expected_revision)

        # Validate mutation environment
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # Reauthorize canonical world-time path before initial read
        path = self._world_time_path
        _reauthorize_world_time_path(self._vault_root, path)

        if not path.exists():
            raise NotFoundError(
                "world_time.json not found \u2014 use initialize_current_world_time first"
            )

        current_text = _read_exact_text(path)
        current = _deserialize(current_text)
        before_hash = _content_hash(current_text)

        # Check revision
        if current.revision != validated_expected_revision:
            raise ConflictError(
                f"Revision mismatch for world_time: "
                f"expected {validated_expected_revision}, "
                f"stored {current.revision}"
            )

        # Build candidate state
        candidate = CurrentWorldTime(
            schema_version=1,
            type="world_time",
            current_world_tick=validated_tick,
            revision=current.revision + 1,
        )

        return _commit_mutation(
            world_time_path=path,
            candidate=candidate,
            before_hash=before_hash,
            mode=_MutationMode.UPDATE,
            audit=audit,
            operation="world_time.update",
            vault_root=self._vault_root,
            audit_service=self._audit_service,
        )
