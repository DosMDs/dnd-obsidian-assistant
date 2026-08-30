"""Concrete Obsidian Vault repository — create, read, and list entities.

This module implements the first concrete filesystem-backed Vault repository
slice for Stage 3.  It composes:

- path safety/discovery (S3-02, ``paths.py``);
- Markdown codec (S3-01, ``markdown.py``);
- atomic writes (S3-03, ``atomic.py``);
- audit persistence (S3-04, ``audit.py``).

Full ``VaultRepository`` structural conformance is reached after S3-07
(``append_entity_fact`` is implemented).
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from pydantic import TypeAdapter

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Revision
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.audit import AuditContext, AuditRecord, AuditService
from dnd_assistant.storage.markdown import parse, serialize
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.paths import discover_entity_files, entity_directory, resolve_entity_path
from dnd_assistant.storage.types import VaultDocument

# ── EntityId runtime validator ────────────────────────────────────────────────

_ENTITY_ID_ADAPTER = TypeAdapter(EntityId)
"""TypeAdapter for canonical EntityId runtime validation."""

_REVISION_ADAPTER = TypeAdapter(Revision)
"""TypeAdapter for canonical Revision runtime validation."""

# ── Constants ───────────────────────────────────────────────────────────────

_MAX_FILENAME_ATTEMPTS = 32
"""Maximum attempts to generate a non-colliding entity filename."""

_AUDIT_SYSTEM_DIR = "_system"
_AUDIT_DIR = "audit"
"""Expected audit directory path components beneath the Vault root."""

# ── Internal result type ────────────────────────────────────────────────────


class _StoredEntity:
    """An entity file that has been read, parsed, and validated.

    Retains the exact text and its SHA-256 hash so that callers
    (e.g. ``patch_entity``) can compute before-hashes without
    re-reading the file.

    Also retains the entity-relative path within the canonical type
    directory so that mutation-time path reauthorization can verify
    the stored location is still authorised under current filesystem
    topology.
    """

    def __init__(
        self,
        path: Path,
        directory_type: EntityType,
        document: VaultDocument,
        exact_text: str,
        vault_root: Path | None = None,
    ) -> None:
        self._path = path
        self._directory_type = directory_type
        self._document = document
        self._exact_text = exact_text
        self._hash = _content_hash(exact_text)
        # Store entity-relative path for mutation-time reauthorization.
        # The path is relative to the canonical entity directory for this type.
        if vault_root is not None:
            from dnd_assistant.storage.paths import entity_directory

            try:
                canon_dir = entity_directory(vault_root, directory_type)
                self._relative_path = path.relative_to(canon_dir)
            except (ValueError, StorageError):
                self._relative_path = Path(path.name)
        else:
            self._relative_path = Path(path.name)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def directory_type(self) -> EntityType:
        return self._directory_type

    @property
    def document(self) -> VaultDocument:
        return self._document

    @property
    def entity_id(self) -> str:
        return self._document.entity.id

    @property
    def exact_text(self) -> str:
        """The exact UTF-8 text of the persisted file."""
        return self._exact_text

    @property
    def content_hash(self) -> str:
        """SHA-256 hex digest of the exact persisted text."""
        return self._hash

    @property
    def relative_path(self) -> Path:
        """Entity-relative path within the canonical type directory.

        Used for mutation-time path reauthorization.
        """
        return self._relative_path


# ── Hash helper ─────────────────────────────────────────────────────────────


def _content_hash(text: str) -> str:
    """SHA-256 hash of the exact UTF-8 content.

    Args:
        text: The exact serialised document text.

    Returns:
        Hex digest of the SHA-256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Fact validation ─────────────────────────────────────────────────────────


def _validate_fact(fact: object) -> str:
    """Validate a fact string for ``append_entity_fact``.

    Contract:
    - must be a ``str``;
    - non-empty;
    - no leading/trailing whitespace;
    - printable Unicode (no control characters, no newlines);
    - no embedded newline/control characters.

    Args:
        fact: The fact value to validate.

    Returns:
        The validated fact string.

    Raises:
        ValidationError: The value does not satisfy the fact contract.
    """
    if not isinstance(fact, str):
        raise ValidationError(f"Fact must be a string, got {type(fact).__name__}")
    if not fact:
        raise ValidationError("Fact must not be empty")
    if fact.strip() != fact:
        raise ValidationError("Fact must not have leading or trailing whitespace")
    if not fact.isprintable():
        raise ValidationError("Fact must not contain non-printable characters")
    return fact


# ── Body fact appender ──────────────────────────────────────────────────────


def _append_fact_to_body(body: str, fact: str) -> str:
    """Append one Markdown bullet fact to an existing body.

    Policy:
    - Existing body remains an exact character-for-character prefix.
    - If body is empty: return ``"- <fact>\\n"`` (LF).
    - If body ends with ``\\r\\n``: append using ``\\r\\n``.
    - If body ends with ``\\n``: append using ``\\n``.
    - If body ends with lone ``\\r``: append using ``\\r``.
    - If body has no trailing line ending: infer separator from the
      most recently observable line ending (CRLF wins over LF), then
      ``separator + "- <fact>" + separator``.
    - No extra blank paragraph unless already present.

    Args:
        body: The existing Markdown body text.
        fact: The validated fact string.

    Returns:
        The new body with the fact appended.
    """
    bullet = f"- {fact}"

    if not body:
        return f"{bullet}\n"

    if body.endswith("\r\n"):
        return f"{body}{bullet}\r\n"

    if body.endswith("\n"):
        return f"{body}{bullet}\n"

    if body.endswith("\r"):
        return f"{body}{bullet}\r"

    # No trailing line ending — infer separator from most recent line ending
    # The rightmost \n represents the most recent LF-capable line ending.
    # If it is immediately preceded by \r, the actual sequence is CRLF.
    last_lf = body.rfind("\n")
    if last_lf == -1:
        separator = "\n"
    elif last_lf > 0 and body[last_lf - 1] == "\r":
        separator = "\r\n"
    else:
        separator = "\n"

    return f"{body}{separator}{bullet}{separator}"


# ── Filename generation ─────────────────────────────────────────────────────


def _generate_entity_filename() -> str:
    """Generate an opaque, safe, ASCII-only entity filename.

    The filename is NOT derived from ``EntityId`` or display name.
    Format: ``entity-<uuid4hex>.md``
    """
    return f"entity-{uuid.uuid4().hex}.md"


# ── Exact text reader ───────────────────────────────────────────────────────


def _read_exact_text(path: Path) -> str:
    """Read a file's text content with exact newline preservation.

    Uses ``newline=""`` to prevent Python from translating ``\\n`` to
    ``\\r\\n`` on Windows.

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
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"Invalid UTF-8 in entity file: {path}",
            cause=exc,
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"Failed to read entity file: {path}",
            cause=exc,
        ) from exc


# ── Snapshot builder ────────────────────────────────────────────────────────


def _build_snapshot(vault_root: Path) -> list[_StoredEntity]:
    """Build a clean snapshot of all persisted entities.

    Discovers, reads, parses, and validates every entity-file candidate
    in the Vault.  Raises ``StorageError`` on any corruption, type/directory
    mismatch, or duplicate ``EntityId``.

    Args:
        vault_root: The resolved Vault root path.

    Returns:
        A list of ``_StoredEntity`` values, one per valid file.

    Raises:
        StorageError: A persisted file is malformed, has a type/directory
            mismatch, or a duplicate ``EntityId`` is detected.
    """
    candidates = discover_entity_files(vault_root)
    stored: list[_StoredEntity] = []

    for candidate in candidates:
        text = _read_exact_text(candidate.path)

        try:
            document = parse(text)
        except ValidationError as exc:
            raise StorageError(
                f"Malformed persisted entity file: {candidate.path}",
                cause=exc,
            ) from exc

        # Directory/type consistency check
        if document.entity.type != candidate.entity_type:
            raise StorageError(
                f"Entity type mismatch in {candidate.path}: "
                f"YAML type is {document.entity.type.value!r}, "
                f"but file is in {candidate.entity_type.value!r} directory"
            )

        stored.append(
            _StoredEntity(
                path=candidate.path,
                directory_type=candidate.entity_type,
                document=document,
                exact_text=text,
                vault_root=vault_root,
            )
        )

    # Global duplicate EntityId detection
    seen: dict[str, list[Path]] = {}
    for se in stored:
        if se.entity_id in seen:
            seen[se.entity_id].append(se.path)
        else:
            seen[se.entity_id] = [se.path]

    duplicates = {eid: paths for eid, paths in seen.items() if len(paths) > 1}
    if duplicates:
        parts = []
        for eid, paths in duplicates.items():
            parts.append(f"EntityId {eid!r} in: {', '.join(str(p) for p in paths)}")
        raise ConflictError(f"Duplicate EntityId(s) detected: {'; '.join(parts)}")

    return stored


# ── Mutation environment validation ──────────────────────────────────────────


def _validate_mutation_environment(
    vault_root: Path,
    audit_service: AuditService,
) -> None:
    """Validate the current mutation environment is still safe.

    Called before every mutation to ensure the audit path topology has
    not been compromised since repository construction.

    Required checks:

    1. audit log path still belongs beneath ``<vault_root>/_system/audit/``;
    2. no parent path component of the audit log has become a symlink;
    3. audit log itself is not a symlink (including dangling);
    4. canonical ``_system/audit/`` directory still exists and is a real
       directory.

    Reads (``get_entity``, ``list_entities``) are intentionally independent
    of audit availability and do NOT call this helper.

    Args:
        vault_root: The resolved Vault root path.
        audit_service: The audit service whose log path to validate.

    Raises:
        StorageError: The mutation environment is unsafe.
    """
    audit_log_path = audit_service.log_path

    # 1. Verify audit log path is still lexically beneath vault_root
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

    # 2. Inspect each existing path component beneath vault_root for symlinks
    expected_audit_dir = vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR
    accumulated = vault_root
    for part in relative.parts[:-1]:  # exclude filename
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Audit path component became a symlink after construction, "
                f"rejected for safety: {accumulated}"
            )

    # 3. Audit log itself must not be a symlink
    if audit_log_path.is_symlink():
        raise StorageError(f"Audit log path became a symlink after construction: {audit_log_path}")

    # 4. Canonical _system/audit/ directory must still exist and be a real dir
    if not expected_audit_dir.is_dir():
        raise StorageError(f"Canonical audit directory no longer exists: {expected_audit_dir}")


# ── Entity path reauthorization ──────────────────────────────────────────────


def _reauthorize_entity_path(
    vault_root: Path,
    directory_type: EntityType,
    relative_path: Path,
) -> Path:
    """Reauthorize a stored entity path against current filesystem topology.

    Uses ``storage.paths.resolve_entity_path`` to verify the path is still
    a valid, authorized entity path of the expected type under the Vault.

    Args:
        vault_root: The resolved Vault root path.
        directory_type: The expected ``EntityType``.
        relative_path: The entity-relative path within the canonical type
            directory (as stored in ``_StoredEntity._relative_path``).

    Returns:
        The resolved absolute path.

    Raises:
        StorageError: The path is no longer authorized (symlink redirect,
            traversal, outside entity directory, etc.).
    """
    from dnd_assistant.storage.paths import resolve_entity_path

    return resolve_entity_path(vault_root, directory_type, relative_path)


# ── Audit path validation ────────────────────────────────────────────────────


def _validate_audit_path(vault_root: Path, audit_log_path: Path) -> None:
    """Verify the audit log path belongs beneath ``<vault_root>/_system/audit/``.

    Validation ordering:

    1. vault_root is already canonical/resolved.
    2. Verify the audit log is lexically beneath vault_root enough to
       derive its raw relative components.
    3. Reject ANY raw relative component equal to ``..`` before resolving.
    4. Establish canonical ``expected_audit_dir = vault_root / _system / audit``.
    5. Inspect all existing components beneath vault_root that lead to the
       audit log parent — reject symlinked components BEFORE ``.resolve()``
       erases symlink identity.
    6. Resolve the audit log path with ``strict=False``.
    7. Verify the resolved path is inside the resolved Vault root.
    8. Verify the resolved path is inside the resolved canonical
       ``_system/audit/`` directory.

    Args:
        vault_root: The resolved Vault root path.
        audit_log_path: The absolute audit-log file path.

    Raises:
        StorageError: The audit log is outside the Vault, outside
            ``_system/audit/``, or a symlink is detected in the path.
    """
    # 1. vault_root is already canonical/resolved (set in __init__).

    # 2. Verify lexical containment — enough to extract raw relative components.
    try:
        relative = audit_log_path.relative_to(vault_root)
    except ValueError:
        raise StorageError(f"Audit log path is outside the Vault root: {audit_log_path}") from None

    # 3. Reject ANY raw relative component equal to ".." before resolving.
    for part in relative.parts:
        if part == "..":
            raise StorageError(
                f"Audit log path contains parent-directory traversal ('..'): {audit_log_path}"
            )

    # 4. Establish canonical expected audit directory.
    expected_audit_dir = vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR

    # 5. Inspect all existing path components beneath vault_root that lead
    #    to the audit log parent.  Reject symlinked components BEFORE
    #    .resolve() erases symlink identity.
    accumulated = vault_root
    for part in relative.parts[:-1]:  # exclude the filename itself
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Audit path component is a symlink, rejected for safety: {accumulated}"
            )

    # 6. Resolve the audit log path with strict=False.
    resolved = audit_log_path.resolve(strict=False)

    # 7. Verify resolved path is inside resolved Vault root.
    try:
        resolved.relative_to(vault_root)
    except ValueError:
        raise StorageError(
            f"Audit log path resolves outside the Vault root: {audit_log_path}"
        ) from None

    # 8. Verify resolved path is inside resolved canonical _system/audit/.
    resolved_audit_dir = expected_audit_dir.resolve(strict=False)
    try:
        resolved.relative_to(resolved_audit_dir)
    except ValueError:
        raise StorageError(
            f"Audit log path must be beneath {expected_audit_dir}, "
            f"got: {audit_log_path} (resolved: {resolved})"
        ) from None


# ── EntityId runtime validation ─────────────────────────────────────────────


def _validate_entity_id_input(entity_id: str) -> str:
    """Validate an externally supplied entity_id at runtime.

    Delegates to the canonical ``EntityId`` type via ``TypeAdapter``.
    Invalid input raises ``ValidationError`` rather than producing a fake
    ``NotFoundError``.

    Args:
        entity_id: The identifier to validate.

    Returns:
        The validated identifier (same value).

    Raises:
        ValidationError: The value is not a valid ``EntityId``.
    """
    try:
        validated = _ENTITY_ID_ADAPTER.validate_python(entity_id)
    except Exception as exc:
        raise ValidationError(
            f"Invalid EntityId: {entity_id}",
            cause=exc,
        ) from exc
    return validated


def _validate_revision_input(revision: object) -> int:
    """Validate an externally supplied revision at runtime.

    Delegates to the canonical ``Revision`` type via ``TypeAdapter``.
    Invalid input raises ``ValidationError`` with the Pydantic cause
    preserved.

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


# ── Shared mutation commit helper ───────────────────────────────────────────


def _commit_entity_mutation(
    target: _StoredEntity,
    candidate_document: VaultDocument,
    *,
    audit: AuditContext,
    operation: str,
    audit_service: AuditService,
    vault_root: Path | None = None,
) -> VaultDocument:
    """Commit an entity mutation with audit intent, second check, atomic write,
    verified read-back, and committed audit.

    This is the shared mutation core used by both ``patch_entity`` and
    ``append_entity_fact``.  It owns:

    - serialization;
    - before/after hashes;
    - audit intent;
    - second optimistic check (re-read target, verify revision + hash);
    - ``atomic_write_text`` with parse validator;
    - verified read-back (hash, id, type, revision, updated_at, body);
    - committed audit;
    - common failure semantics.

    Args:
        target: The ``_StoredEntity`` to mutate (must already be validated).
        candidate_document: The desired new ``VaultDocument``.
        audit: Audit context for this mutation.
        operation: The operation name for audit records.
        audit_service: The audit service for persisting records.

    Returns:
        The persisted ``VaultDocument`` after the mutation.

    Raises:
        ConflictError: Revision or content changed between intent and write.
        StorageError: A filesystem or audit operation failed.
    """
    validated_id = target.entity_id
    stored_revision = target.document.entity.revision
    stored_entity = target.document.entity

    # Serialize
    serialized = serialize(candidate_document)

    # Compute before/after hashes
    before_hash = target.content_hash
    after_hash = _content_hash(serialized)

    # Append audit intent record
    intent_record = AuditRecord(
        operation_id=audit.operation_id,
        real_time=audit.real_time,
        operation=operation,
        entity_id=validated_id,
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
    # After durable intent, revalidate environment and target path before
    # any filesystem operation on the entity.

    # a. Mutation environment is still safe (if vault_root provided)
    if vault_root is not None:
        _validate_mutation_environment(vault_root, audit_service)

    # b. Reauthorize target path against current filesystem topology
    if vault_root is not None:
        _reauthorize_entity_path(
            vault_root,
            target.directory_type,
            target.relative_path,
        )

    # Second optimistic check — re-read target file
    try:
        current_text = _read_exact_text(target.path)
    except StorageError as exc:
        raise StorageError(
            f"Target file became unreadable for operation {audit.operation_id}: {target.path}",
            cause=exc,
        ) from exc

    current_hash = _content_hash(current_text)

    try:
        current_doc = parse(current_text)
    except ValidationError as exc:
        raise StorageError(
            f"Target file became unparseable for operation {audit.operation_id}: {target.path}",
            cause=exc,
        ) from exc

    current_revision = current_doc.entity.revision
    if current_revision != stored_revision:
        raise ConflictError(
            f"Entity {validated_id!r} revision changed after intent: "
            f"expected {stored_revision}, got {current_revision}"
        )

    if current_hash != before_hash:
        raise ConflictError(
            f"Entity {validated_id!r} content changed after intent "
            f"(hash mismatch) for operation {audit.operation_id}"
        )

    # Atomic write with parse validator
    target_path = target.path
    atomic_write_text(
        target=target_path,
        content=serialized,
        validator=lambda c: parse(c),
    )

    # Re-read and verify persisted content
    try:
        persisted_text = _read_exact_text(target_path)
    except StorageError as exc:
        raise StorageError(
            f"Mutation committed but read-back failed for operation {audit.operation_id}: {exc}"
        ) from exc

    persisted_hash = _content_hash(persisted_text)
    if persisted_hash != after_hash:
        raise StorageError(
            f"Mutation committed but hash verification failed for "
            f"operation {audit.operation_id}: "
            f"expected {after_hash}, got {persisted_hash}"
        )

    try:
        persisted_doc = parse(persisted_text)
    except ValidationError as exc:
        raise StorageError(
            f"Mutation committed but re-parsed document is invalid "
            f"for operation {audit.operation_id}",
            cause=exc,
        ) from exc

    # Verify id, type, revision, updated_at
    if persisted_doc.entity.id != validated_id:
        raise StorageError(
            f"Mutation committed but entity ID changed for operation {audit.operation_id}"
        )
    if persisted_doc.entity.type != stored_entity.type:
        raise StorageError(
            f"Mutation committed but entity type changed for operation {audit.operation_id}"
        )
    if persisted_doc.entity.revision != stored_revision + 1:
        raise StorageError(
            f"Mutation committed but revision is {persisted_doc.entity.revision}, "
            f"expected {stored_revision + 1} for operation {audit.operation_id}"
        )
    if persisted_doc.entity.updated_at != audit.real_time:
        raise StorageError(
            f"Mutation committed but updated_at mismatch for operation {audit.operation_id}"
        )

    # Append committed audit record
    committed_record = AuditRecord(
        operation_id=audit.operation_id,
        real_time=audit.real_time,
        operation=operation,
        entity_id=validated_id,
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
            f"Entity mutation committed but audit finalization failed "
            f"for operation {audit.operation_id}.  "
            f"The mutated entity file exists at {target_path}.  "
            f"An intent audit record is present.",
            cause=exc,
        ) from exc

    return persisted_doc


# ── ObsidianVaultRepository ─────────────────────────────────────────────────


class ObsidianVaultRepository:
    """Concrete Vault repository backed by an Obsidian Markdown Vault.

    Owns entity filesystem operations: create, read, list.  Uses atomic
    writes (S3-03), Markdown codec (S3-01), path safety (S3-02), and
    audit logging (S3-04).

    Full ``VaultRepository`` structural conformance is reached after
    S3-07 (``append_entity_fact`` is implemented).

    Args:
        vault_root: The root directory of the Obsidian Vault.
        audit_service: The audit service for logging mutations.

    Raises:
        StorageError: The Vault root is invalid, the audit path is
            misconfigured, or the ``_system/audit/`` directory is missing.
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

        # Validate audit path belongs to this Vault
        _validate_audit_path(self._vault_root, audit_service.log_path)

        # Verify the canonical _system/audit/ directory exists
        expected_audit_dir = self._vault_root / _AUDIT_SYSTEM_DIR / _AUDIT_DIR
        if not expected_audit_dir.is_dir():
            raise StorageError(f"Canonical audit directory does not exist: {expected_audit_dir}")

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    @property
    def audit_service(self) -> AuditService:
        """The injected audit service."""
        return self._audit_service

    # ── Snapshot ────────────────────────────────────────────────────────

    def _snapshot(self) -> list[_StoredEntity]:
        """Build a clean snapshot of all persisted entities.

        Raises:
            StorageError: Corruption, type/directory mismatch, or
                duplicate ``EntityId`` detected.
        """
        return _build_snapshot(self._vault_root)

    # ── get_entity ──────────────────────────────────────────────────────

    def get_entity(self, entity_id: str) -> VaultDocument:
        """Retrieve an entity document by its stable YAML ``EntityId``.

        Args:
            entity_id: The stable domain identifier.

        Returns:
            The matching ``VaultDocument``.

        Raises:
            ValidationError: The ``entity_id`` is not a valid
                ``EntityId`` string.
            NotFoundError: No entity with the given ID exists.
            StorageError: A persisted file is malformed, has a
                type/directory mismatch, or a duplicate ``EntityId``
                is detected.
        """
        validated_id = _validate_entity_id_input(entity_id)

        snapshot = self._snapshot()
        for se in snapshot:
            if se.entity_id == validated_id:
                return se.document

        raise NotFoundError(f"Entity not found: {validated_id}")

    # ── list_entities ───────────────────────────────────────────────────

    def list_entities(
        self,
        entity_type: EntityType | None = None,
    ) -> list[VaultDocument]:
        """List entity documents in the Vault.

        Args:
            entity_type: Optional filter by entity type.  When ``None``,
                all entity types are returned.

        Returns:
            A list of matching ``VaultDocument`` values.  Returns an
            empty list when no entities match.

        Raises:
            StorageError: A persisted file is malformed, has a
                type/directory mismatch, or a duplicate ``EntityId``
                is detected.
        """
        snapshot = self._snapshot()

        if entity_type is not None:
            return [se.document for se in snapshot if se.directory_type == entity_type]
        return [se.document for se in snapshot]

    # ── Internal helpers ────────────────────────────────────────────────

    def _generate_unique_path(self, target_dir: Path) -> Path:
        """Generate a unique non-colliding entity file path.

        Args:
            target_dir: The target entity directory.

        Returns:
            A ``Path`` to a non-existing file in ``target_dir``.

        Raises:
            StorageError: All filename candidates collided.
        """
        for _attempt in range(_MAX_FILENAME_ATTEMPTS):
            filename = _generate_entity_filename()
            candidate = target_dir / filename
            # A filename is NOT free if it exists OR if it is a symlink
            # (including dangling/broken symlinks where exists() returns False).
            if not candidate.exists() and not candidate.is_symlink():
                return candidate

        raise StorageError(
            f"Failed to generate a unique filename in {target_dir} "
            f"after {_MAX_FILENAME_ATTEMPTS} attempts"
        )

    def _check_audit_health(self, operation_id: str) -> None:
        """Verify the audit log is readable and operation_id is unique.

        Args:
            operation_id: The operation ID to check for reuse.

        Raises:
            StorageError: The audit log is corrupt or unreadable.
            ConflictError: The ``operation_id`` already exists in the
                audit log.
        """
        try:
            existing = self._audit_service.read_all()
        except StorageError:
            raise  # Propagate corrupt audit log as-is

        for record in existing:
            if record.operation_id == operation_id:
                raise ConflictError(
                    f"Operation ID {operation_id!r} has already been used in the audit log"
                )

    # ── create_entity ───────────────────────────────────────────────────

    def create_entity(
        self,
        document: VaultDocument,
        *,
        audit: AuditContext,
    ) -> VaultDocument:
        """Persist a new entity document in the Vault.

        The create lifecycle:

        1. Validate repository/audit state (audit log readable).
        2. Discover and parse existing entities (global duplicate check).
        3. Serialize the candidate document.
        4. Compute ``after_hash``.
        5. Choose a safe storage filename.
        6. Append audit ``intent`` record.
        7. Atomic write.
        8. Re-read and verify persisted content.
        9. Append audit ``committed`` record.
        10. Return the persisted ``VaultDocument``.

        Args:
            document: The entity document to create.  Must have a unique
                ``EntityId`` that does not already exist in the Vault.
            audit: Audit context for this mutation.

        Returns:
            The persisted document as stored.

        Raises:
            ConflictError: An entity with the same ``EntityId`` already
                exists, or the ``operation_id`` has already been used.
            StorageError: The write or audit operation failed.
        """
        entity_type = document.entity.type
        entity_id = document.entity.id

        # 0. Validate mutation environment is still safe
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # 1. Validate audit log is readable and operation_id is unique
        self._check_audit_health(audit.operation_id)

        # 2. Build snapshot (detects duplicates globally)
        snapshot = self._snapshot()
        for se in snapshot:
            if se.entity_id == entity_id:
                raise ConflictError(f"Entity with ID {entity_id!r} already exists")

        # 3. Serialize
        serialized = serialize(document)

        # 4. Compute hash
        after = _content_hash(serialized)

        # 5. Choose safe filename
        target_dir = entity_directory(self._vault_root, entity_type)
        if not target_dir.is_dir():
            raise StorageError(f"Canonical entity directory does not exist: {target_dir}")

        target = self._generate_unique_path(target_dir)

        # 6. Append intent audit record
        intent_record = AuditRecord(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="create_entity",
            entity_id=entity_id,
            before_hash=None,
            after_hash=after,
            source=audit.source,
            session=audit.session,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="intent",
        )
        self._audit_service.append(intent_record)

        # ── Second create pre-write check ──────────────────────────────
        # After durable intent but before atomic write, re-verify all
        # preconditions that could have changed since the initial snapshot.

        # a. Mutation environment is still safe
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # b. Target path is still authorized under the canonical entity dir
        try:
            reauthorized = resolve_entity_path(
                self._vault_root,
                entity_type,
                target.relative_to(entity_directory(self._vault_root, entity_type)),
            )
        except (ValueError, StorageError) as exc:
            raise StorageError(
                f"Create target path is no longer authorized for "
                f"operation {audit.operation_id}: {target}",
                cause=exc,
            ) from exc

        if reauthorized != target:
            raise StorageError(
                f"Create target path resolved to a different location for "
                f"operation {audit.operation_id}: expected {target}, got {reauthorized}"
            )

        # c. Target path must still NOT exist
        if target.exists():
            raise ConflictError(
                f"Create target path became occupied after intent for "
                f"operation {audit.operation_id}: {target}"
            )

        # d. Target path must NOT be a symlink (including dangling)
        if target.is_symlink():
            raise ConflictError(
                f"Create target path became a symlink after intent for "
                f"operation {audit.operation_id}: {target}"
            )

        # e. Fresh snapshot — no duplicate EntityId appeared
        fresh_snapshot = self._snapshot()
        for se in fresh_snapshot:
            if se.entity_id == entity_id:
                raise ConflictError(
                    f"Entity with ID {entity_id!r} appeared after intent for "
                    f"operation {audit.operation_id}"
                )

        # 7. Atomic write
        atomic_write_text(
            target=target,
            content=serialized,
            validator=lambda c: parse(c),
        )

        # 8. Re-read and verify
        try:
            persisted_text = _read_exact_text(target)
        except StorageError as exc:
            raise StorageError(
                f"Entity write committed but read-back failed for "
                f"operation {audit.operation_id}: {exc}"
            ) from exc

        persisted_hash = _content_hash(persisted_text)
        if persisted_hash != after:
            raise StorageError(
                f"Entity write committed but hash verification failed for "
                f"operation {audit.operation_id}: "
                f"expected {after}, got {persisted_hash}"
            )

        try:
            persisted_doc = parse(persisted_text)
        except ValidationError as exc:
            raise StorageError(
                f"Entity write committed but re-parsed document is invalid "
                f"for operation {audit.operation_id}",
                cause=exc,
            ) from exc

        # 9. Append committed audit record
        committed_record = AuditRecord(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="create_entity",
            entity_id=entity_id,
            before_hash=None,
            after_hash=after,
            source=audit.source,
            session=audit.session,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="committed",
        )
        try:
            self._audit_service.append(committed_record)
        except StorageError as exc:
            raise StorageError(
                f"Entity mutation committed but audit finalization failed "
                f"for operation {audit.operation_id}.  "
                f"The entity file exists at {target}.  "
                f"An intent audit record is present.",
                cause=exc,
            ) from exc

        # 10. Return persisted document
        return persisted_doc

    # ── patch_entity ───────────────────────────────────────────────────

    def patch_entity(
        self,
        entity_id: str,
        patch: EntityPatch,
        *,
        expected_revision: object,
        audit: AuditContext,
    ) -> VaultDocument:
        """Patch an existing entity's editable fields.

        The patch lifecycle:

        1. Validate inputs (entity_id, expected_revision, patch).
        2. Validate repository/audit state (audit log readable).
        3. Build clean global snapshot.
        4. Find target entity by exact EntityId.
        5. Check expected_revision against stored revision.
        6. Construct the patched Entity through full validation.
        7. Serialize the patched document.
        8. Compute before/after hashes.
        9. Append audit ``intent`` record.
        10. Second optimistic check (re-read target, verify revision+hash).
        11. Atomic write with parse validator.
        12. Re-read and verify persisted content.
        13. Append audit ``committed`` record.
        14. Return the persisted ``VaultDocument``.

        Args:
            entity_id: The stable domain identifier of the entity to patch.
            patch: The typed partial update DTO.
            expected_revision: The revision the caller last observed.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``VaultDocument`` after the patch.

        Raises:
            ValidationError: The ``entity_id``, ``expected_revision``, or
                ``patch`` is invalid.
            NotFoundError: No entity with the given ID exists.
            ConflictError: The stored revision does not match
                ``expected_revision``, or the ``operation_id`` has already
                been used.
            StorageError: A filesystem or audit operation failed.
        """
        # 1. Validate inputs
        validated_id = _validate_entity_id_input(entity_id)
        validated_revision = _validate_revision_input(expected_revision)

        # 2. Validate mutation environment is still safe
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # 3. Validate audit log is readable and operation_id is unique
        self._check_audit_health(audit.operation_id)

        # 3. Build snapshot (detects duplicates/corruption globally)
        snapshot = self._snapshot()

        # 4. Find target entity by exact EntityId
        target: _StoredEntity | None = None
        for se in snapshot:
            if se.entity_id == validated_id:
                target = se
                break

        if target is None:
            raise NotFoundError(f"Entity not found: {validated_id}")

        stored_entity = target.document.entity
        stored_revision = stored_entity.revision

        # 5. Check expected_revision against stored revision
        if stored_revision != validated_revision:
            raise ConflictError(
                f"Revision mismatch for entity {validated_id!r}: "
                f"expected {validated_revision}, stored {stored_revision}"
            )

        # 6. Construct the patched Entity through full validation
        entity_data = stored_entity.model_dump()
        # Apply only fields actually present in the patch
        for field_name in patch.model_fields_set:
            value = getattr(patch, field_name)
            if field_name == "tags" and value is not None:
                # Tags is a list — replace entirely
                entity_data[field_name] = list(value)
            elif field_name in ("created_session", "last_seen_session"):
                # Nullable fields: explicit None means clear
                entity_data[field_name] = value
            else:
                entity_data[field_name] = value

        # Repository-owned mutation metadata
        new_revision = stored_revision + 1
        entity_data["revision"] = new_revision
        entity_data["updated_at"] = audit.real_time

        try:
            new_entity = Entity.model_validate(entity_data)
        except Exception as exc:
            raise ValidationError(
                f"Patched entity validation failed for {validated_id!r}",
                cause=exc,
            ) from exc

        # 7. Construct the patched document
        patched_document = VaultDocument(
            entity=new_entity,
            extra_frontmatter=target.document.extra_frontmatter,
            body=target.document.body,
        )

        # 8-14. Delegate to shared mutation commit helper
        return _commit_entity_mutation(
            target=target,
            candidate_document=patched_document,
            audit=audit,
            operation="patch_entity",
            audit_service=self._audit_service,
            vault_root=self._vault_root,
        )

    # ── append_entity_fact ─────────────────────────────────────────────

    def append_entity_fact(
        self,
        entity_id: str,
        *,
        expected_revision: object,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        """Append a fact/note to an entity's Markdown body.

        The append lifecycle:

        1. Validate inputs (entity_id, expected_revision, fact).
        2. Validate repository/audit state (audit log readable).
        3. Build clean global snapshot.
        4. Find target entity by exact EntityId.
        5. Check expected_revision against stored revision.
        6. Construct the new body by appending one Markdown bullet.
        7. Construct the candidate Entity through full validation.
        8-14. Delegate to shared mutation commit helper.

        Args:
            entity_id: The stable domain identifier of the entity.
            expected_revision: The revision the caller last observed.
            fact: The fact text to append (validated: non-empty, printable,
                no leading/trailing whitespace, no newlines/controls).
            audit: Audit context for this mutation.

        Returns:
            The persisted ``VaultDocument`` after the append.

        Raises:
            ValidationError: The ``entity_id``, ``expected_revision``, or
                ``fact`` is invalid.
            NotFoundError: No entity with the given ID exists.
            ConflictError: The stored revision does not match
                ``expected_revision``, or the ``operation_id`` has already
                been used.
            StorageError: A filesystem or audit operation failed.
        """
        # 1. Validate inputs
        validated_id = _validate_entity_id_input(entity_id)
        validated_revision = _validate_revision_input(expected_revision)
        validated_fact = _validate_fact(fact)

        # 2. Validate mutation environment is still safe
        _validate_mutation_environment(self._vault_root, self._audit_service)

        # 3. Validate audit log is readable and operation_id is unique
        self._check_audit_health(audit.operation_id)

        # 3. Build snapshot (detects duplicates/corruption globally)
        snapshot = self._snapshot()

        # 4. Find target entity by exact EntityId
        target: _StoredEntity | None = None
        for se in snapshot:
            if se.entity_id == validated_id:
                target = se
                break

        if target is None:
            raise NotFoundError(f"Entity not found: {validated_id}")

        stored_entity = target.document.entity
        stored_revision = stored_entity.revision

        # 5. Check expected_revision against stored revision
        if stored_revision != validated_revision:
            raise ConflictError(
                f"Revision mismatch for entity {validated_id!r}: "
                f"expected {validated_revision}, stored {stored_revision}"
            )

        # 6. Construct the new body by appending one Markdown bullet
        new_body = _append_fact_to_body(target.document.body, validated_fact)

        # 7. Construct the candidate Entity through full validation
        entity_data = stored_entity.model_dump()
        entity_data["revision"] = stored_revision + 1
        entity_data["updated_at"] = audit.real_time

        try:
            new_entity = Entity.model_validate(entity_data)
        except Exception as exc:
            raise ValidationError(
                f"Appended entity validation failed for {validated_id!r}",
                cause=exc,
            ) from exc

        candidate_document = VaultDocument(
            entity=new_entity,
            extra_frontmatter=target.document.extra_frontmatter,
            body=new_body,
        )

        # 8-14. Delegate to shared mutation commit helper
        return _commit_entity_mutation(
            target=target,
            candidate_document=candidate_document,
            audit=audit,
            operation="append_entity_fact",
            audit_service=self._audit_service,
            vault_root=self._vault_root,
        )
