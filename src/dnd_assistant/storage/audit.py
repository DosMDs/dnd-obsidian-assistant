"""AuditRecord schema and AuditService — append-only audit logging for Vault operations.

AuditRecord
===========
A strict Pydantic model representing one audited Vault operation.

AuditService
============
A concrete, focused service that persists ``AuditRecord`` values as JSON
Lines (JSONL) in an append-only file.

Responsibility
--------------
- Persist audit records as JSONL.
- Provide read-back of all persisted records.
- Validate persisted data on read.

Must NOT
--------
- Modify entity files.
- Compute entity hashes.
- Calculate revisions.
- Decide create/patch/append semantics.
- Perform Vault entity writes.
- Call ``atomic_write_text`` for entity files.
- Resolve ``EntityId`` from filenames.
- Call models or tools.
- Implement locks or cross-process guarantees.
- Create parent directories.
- Implement rollback or transactional semantics.

Append-only invariant
---------------------
Once bytes have been passed to the filesystem, a later failure (e.g.
fsync failure) may leave a complete or partial appended line.  This
service does NOT truncate or rewrite the audit log in an attempt to
roll back an uncertain append — that would violate append-only
semantics and risk destroying already-persisted history.

Corrupted/partial audit tails are detected during ``read_all()``.
Automatic repair is not implemented in S3-04.

Deferred integration decision
-----------------------------
Before concrete repository write operations (S3-05/S3-06) are considered
complete, entity-write/audit consistency semantics must be explicitly
defined and tested.  This service is the independent audit primitive;
it does not solve the orchestration problem.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic.types import AwareDatetime

from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import StorageError

# ── AuditRecord schema ─────────────────────────────────────────────────────


class AuditRecord(BaseModel):
    """A single audited Vault operation.

    Each record captures one operation performed on the Vault, including
    the actor (source), the affected entity (if any), and optional
    before/after content hashes.
    """

    schema_version: Literal[1] = 1
    """Audit-log schema version for evolution detection."""

    operation_id: str
    """Unique identifier for this operation (caller-supplied)."""

    real_time: AwareDatetime
    """Real-world timestamp when the operation occurred (caller-supplied)."""

    session: str | None = None
    """Optional game-session identifier (e.g. ``\"S007\"``)."""

    operation: str
    """The operation performed (e.g. ``\"create\"``, ``\"patch\"``)."""

    entity_id: EntityId | None = None
    """Optional stable domain identifier of the affected entity."""

    before_hash: str | None = None
    """Optional hash of the entity content before the operation."""

    after_hash: str | None = None
    """Optional hash of the entity content after the operation."""

    source: str
    """Actor/mechanism that performed the operation (e.g. ``\"model_tool\"``).

    This is NOT domain ``Provenance``.  ``Provenance`` describes how
    campaign knowledge entered the system; ``source`` describes which
    application actor performed the Vault operation.
    """

    model_profile: str | None = None
    """Optional model profile identifier used for this operation."""

    prompt_version: str | None = None
    """Optional prompt version identifier used for this operation."""

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }
    """``extra="forbid"``: unknown fields are rejected.

    ``frozen=True``: records are immutable once created.
    """

    # ── Field validators ──────────────────────────────────────────────

    @field_validator("operation_id", "operation", "source")
    @classmethod
    def _validate_required_string(cls, value: str) -> str:
        return _validate_printable_nonempty(value, "operation_id/operation/source")

    @field_validator("session")
    @classmethod
    def _validate_optional_session(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_printable_nonempty(value, "session")

    @field_validator("before_hash", "after_hash")
    @classmethod
    def _validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_printable_nonempty(value, "before_hash/after_hash")

    @field_validator("model_profile", "prompt_version")
    @classmethod
    def _validate_optional_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_printable_nonempty(value, "model_profile/prompt_version")


# ── Shared string validation ────────────────────────────────────────────────


def _validate_printable_nonempty(value: str, field_name: str) -> str:
    """Validate that ``value`` is a non-empty printable string.

    Raises:
        ValueError: The value is empty, has leading/trailing whitespace,
            or contains non-printable characters.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError(f"{field_name} must not contain non-printable characters")
    return value


# ── AuditService ────────────────────────────────────────────────────────────


class AuditService:
    """Append-only audit-log service for Vault operations.

    Persists ``AuditRecord`` values as JSON Lines (JSONL) in an
    append-only file and provides read-back of all persisted records.

    The audit-log path is injected by the caller — this service does
    not choose a canonical filename or create parent directories.

    Args:
        log_path: Absolute path to the JSONL audit-log file.  The
            parent directory must already exist.

    Raises:
        StorageError: Path preconditions are violated.
    """

    def __init__(self, log_path: str | Path) -> None:
        self._log_path = _validate_log_path(log_path)

    @property
    def log_path(self) -> Path:
        """The absolute path to the audit-log file."""
        return self._log_path

    # ── Public API ─────────────────────────────────────────────────────

    def append(self, record: AuditRecord) -> None:
        """Append one ``AuditRecord`` to the audit log.

        The record is serialised as a single JSON line, appended to the
        log file, flushed, and fsynced before returning.

        Args:
            record: The ``AuditRecord`` to persist.

        Raises:
            StorageError: A filesystem error occurred during append.
        """
        line = _serialize_record(record)
        _append_line(self._log_path, line)

    def read_all(self) -> list[AuditRecord]:
        """Read all persisted audit records in append order.

        Returns an empty list if the log file does not exist.

        Returns:
            All ``AuditRecord`` values in physical append order.

        Raises:
            StorageError: The log file contains malformed JSON, an
                invalid ``AuditRecord``, or a blank line.
        """
        if not self._log_path.exists():
            return []
        return _read_all_records(self._log_path)


# ── Path validation ─────────────────────────────────────────────────────────


def _validate_log_path(log_path: str | Path) -> Path:
    """Validate audit-log path preconditions.

    Requirements:
    - Must be absolute.
    - Parent must already exist and be a directory.
    - Must not be an existing directory.
    - Must not be an existing symlink (including dangling/broken).

    Note:
        This is a local file-contract check, NOT Vault authorization.
        The caller/composition layer is responsible for supplying an
        authorised audit-log path within the Vault.

    Raises:
        StorageError: Any precondition is violated.
    """
    try:
        path = Path(log_path)
    except TypeError as exc:
        raise StorageError(
            "Audit log path must be a string or Path",
            cause=exc,
        ) from exc

    if not path.is_absolute():
        raise StorageError(f"Audit log path must be absolute, got: {path}")

    parent = path.parent

    if not parent.exists():
        raise StorageError(f"Audit log parent directory does not exist: {parent}")

    if not parent.is_dir():
        raise StorageError(f"Audit log parent is not a directory: {parent}")

    # Check symlink BEFORE exists() — Path.exists() follows links and
    # returns False for dangling/broken symlinks.
    if path.is_symlink():
        raise StorageError(f"Audit log path is a symlink, refusing to use: {path}")

    if path.exists() and path.is_dir():
        raise StorageError(f"Audit log path is an existing directory: {path}")

    return path


# ── Serialisation ───────────────────────────────────────────────────────────


def _serialize_record(record: AuditRecord) -> str:
    """Serialize an ``AuditRecord`` to a single JSON line.

    The output is a single JSON object followed by ``\\n``.

    Returns:
        A JSON string ending with ``\\n``.
    """
    data = record.model_dump(mode="json")
    line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return line + "\n"


# ── Append ──────────────────────────────────────────────────────────────────


def _append_line(log_path: Path, line: str) -> None:
    """Append a single JSON line to the audit log.

    Lifecycle::

        open (append) → write → flush → fsync → close

    Raises:
        StorageError: Open, write, flush or fsync failed.
    """
    try:
        with open(log_path, mode="a", encoding="utf-8", newline="") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise StorageError(
            f"Failed to append audit record to {log_path}",
            cause=exc,
        ) from exc


# ── Read-back ───────────────────────────────────────────────────────────────


def _read_all_records(log_path: Path) -> list[AuditRecord]:
    """Read and validate all audit records from the log file.

    Every non-empty line is validated as a complete ``AuditRecord``.
    Blank lines are treated as corruption.

    Args:
        log_path: Path to the JSONL audit-log file.

    Returns:
        All valid ``AuditRecord`` values in file order.

    Raises:
        StorageError: A line contains malformed JSON, an invalid
            ``AuditRecord``, or is a blank line.
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(
            f"Failed to read audit log: {log_path}",
            cause=exc,
        ) from exc

    records: list[AuditRecord] = []

    for line_no, raw_line in enumerate(text.splitlines(keepends=False), start=1):
        stripped = raw_line.strip()

        # Blank line (empty or whitespace-only) is corruption
        if not stripped:
            raise StorageError(f"Audit log corruption at line {line_no}: unexpected blank line")

        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"Audit log corruption at line {line_no}: malformed JSON",
                cause=exc,
            ) from exc

        if not isinstance(data, dict):
            raise StorageError(
                f"Audit log corruption at line {line_no}: expected JSON object, "
                f"got {type(data).__name__}"
            )

        try:
            record = AuditRecord.model_validate(data)
        except Exception as exc:
            raise StorageError(
                f"Audit log corruption at line {line_no}: invalid AuditRecord",
                cause=exc,
            ) from exc

        records.append(record)

    return records
