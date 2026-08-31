"""Raw session event persistence — ObsidianSessionEventRepository.

This module implements the filesystem-backed ``SessionEventRepository``
protocol for raw session events stored in:

    _system/raw/sessions/<session_id>/events.jsonl

It composes:

- path safety (``resolve_session_storage_paths`` from ``session_paths.py``);
- append-only JSONL persistence;
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
from typing import TYPE_CHECKING

from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.session_paths import (
    resolve_session_storage_paths,
)

if TYPE_CHECKING:
    from pydantic.types import AwareDatetime

    from dnd_assistant.storage.audit import AuditContext, AuditService


# ── Constants ─────────────────────────────────────────────────────────────────

_AUDIT_SYSTEM_DIR = "_system"
_AUDIT_DIR = "audit"

# ── Event ID pattern ──────────────────────────────────────────────────────────

_EVENT_ID_RE = re.compile(r"^evt_([0-9]+)$")

# ── Canonical event field names (must never be overridden by extras) ──────────

_CANONICAL_EVENT_FIELDS: frozenset[str] = frozenset(
    {
        "event_id",
        "real_time",
        "world_tick",
        "type",
    }
)

# ── RawSessionEvent ───────────────────────────────────────────────────────────


class RawSessionEvent:
    """Storage-level representation of a raw session event.

    Wraps canonical core fields plus any event-specific extra top-level
    fields that were present in the JSONL record.  Extra fields are
    preserved as-is but never interpreted as canonical event fields.

    Args:
        event_id: The stable event identifier (e.g. ``"evt_001"``).
        real_time: Timezone-aware real-world timestamp.
        world_tick: The canonical game-world tick at recording time.
        type: The event type string (e.g. ``"note"``, ``"item_acquired"``).
        extra_fields: Event-specific top-level fields preserved without
            interpretation.
    """

    def __init__(
        self,
        event_id: str,
        real_time: AwareDatetime,
        world_tick: int,
        type: str,
        extra_fields: dict[str, object] | None = None,
    ) -> None:
        self._event_id = event_id
        self._real_time = real_time
        self._world_tick = world_tick
        self._type = type
        self._extra_fields = dict(extra_fields) if extra_fields else {}

    @property
    def event_id(self) -> str:
        """The stable event identifier."""
        return self._event_id

    @property
    def real_time(self) -> AwareDatetime:
        """Timezone-aware real-world timestamp."""
        return self._real_time

    @property
    def world_tick(self) -> int:
        """The canonical game-world tick at recording time."""
        return self._world_tick

    @property
    def type(self) -> str:
        """The event type string."""
        return self._type

    @property
    def extra_fields(self) -> dict[str, object]:
        """Event-specific top-level fields preserved without interpretation.

        Returns a copy to prevent accidental mutation.
        """
        return dict(self._extra_fields)

    def __repr__(self) -> str:
        return (
            f"RawSessionEvent(event_id={self._event_id!r}, "
            f"type={self._type!r}, "
            f"extra_fields={len(self._extra_fields)})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RawSessionEvent):
            return NotImplemented
        return (
            self._event_id == other._event_id
            and self._real_time == other._real_time
            and self._world_tick == other._world_tick
            and self._type == other._type
            and self._extra_fields == other._extra_fields
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._event_id,
                self._real_time,
                self._world_tick,
                self._type,
                frozenset(self._extra_fields.items()),
            )
        )


# ── Hash helper ───────────────────────────────────────────────────────────────


def _content_hash(text: str) -> str:
    """SHA-256 hash of the exact UTF-8 content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── JSON-compatible value validation ──────────────────────────────────────────


def _validate_json_value(value: object, path: str = "") -> None:
    """Validate that ``value`` is a JSON-compatible value recursively.

    Raises:
        StorageError: The value is not JSON-compatible.
    """
    if value is None:
        return
    if isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (
            value != value or value == float("inf") or value == float("-inf")
        ):
            raise StorageError(
                f"Extra field value at {path!r} is NaN or Infinity, rejected for standard JSON"
            )
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _validate_json_value(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise StorageError(
                    f"Extra field key at {path!r} must be a string, got {type(k).__name__}"
                )
            _validate_json_value(v, f"{path}.{k}")
        return
    raise StorageError(
        f"Extra field value at {path!r} is not JSON-compatible: got {type(value).__name__}"
    )


# ── Serialization ─────────────────────────────────────────────────────────────


def _serialize_event(event: RawSessionEvent) -> str:
    """Serialize a ``RawSessionEvent`` to a single JSON line.

    The output is a single JSON object followed by ``\\n``.
    Canonical event fields always win over extra fields.

    Returns:
        A JSON string ending with ``\\n``.
    """
    data: dict[str, object] = {
        "event_id": event.event_id,
        "real_time": event.real_time.isoformat(),
        "world_tick": event.world_tick,
        "type": event.type,
    }
    for k, v in event.extra_fields.items():
        if k not in _CANONICAL_EVENT_FIELDS:
            data[k] = v
    text = json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    )
    return text + "\n"


def _deserialize_event(text: str) -> RawSessionEvent:
    """Deserialize a ``RawSessionEvent`` from a single JSON line.

    Args:
        text: The JSON text to parse.

    Returns:
        The validated ``RawSessionEvent``.

    Raises:
        StorageError: The text is malformed JSON, has invalid canonical
            fields, or contains non-JSON-compatible extra values.
    """
    from datetime import datetime as _dt

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError("events.jsonl: malformed JSON", cause=exc) from exc

    if not isinstance(data, dict):
        raise StorageError(f"events.jsonl: expected JSON object, got {type(data).__name__}")

    # Validate event_id
    event_id_raw = data.get("event_id")
    if not isinstance(event_id_raw, str) or not event_id_raw:
        raise StorageError(f"events.jsonl: invalid event_id: {event_id_raw!r}")
    if event_id_raw.strip() != event_id_raw:
        raise StorageError(
            f"events.jsonl: event_id has leading or trailing whitespace: {event_id_raw!r}"
        )
    if not event_id_raw.isprintable():
        raise StorageError(
            f"events.jsonl: event_id contains non-printable characters: {event_id_raw!r}"
        )
    if not _EVENT_ID_RE.match(event_id_raw):
        raise StorageError(
            f"events.jsonl: event_id does not match expected format: {event_id_raw!r}"
        )

    # Validate real_time
    real_time_raw = data.get("real_time")
    if not isinstance(real_time_raw, str) or not real_time_raw:
        raise StorageError(f"events.jsonl: invalid real_time: {real_time_raw!r}")
    try:
        parsed_dt = _dt.fromisoformat(real_time_raw)
    except (ValueError, TypeError) as exc:
        raise StorageError(
            f"events.jsonl: invalid real_time format: {real_time_raw!r}",
            cause=exc,
        ) from exc
    if parsed_dt.tzinfo is None:
        raise StorageError(f"events.jsonl: real_time must be timezone-aware: {real_time_raw!r}")

    # Validate world_tick
    world_tick_raw = data.get("world_tick")
    if isinstance(world_tick_raw, bool) or not isinstance(world_tick_raw, int):
        raise StorageError(f"events.jsonl: invalid world_tick: {world_tick_raw!r}")

    # Validate type
    type_raw = data.get("type")
    if not isinstance(type_raw, str) or not type_raw:
        raise StorageError(f"events.jsonl: invalid type: {type_raw!r}")
    if type_raw.strip() != type_raw:
        raise StorageError(f"events.jsonl: type has leading or trailing whitespace: {type_raw!r}")
    if not type_raw.isprintable():
        raise StorageError(f"events.jsonl: type contains non-printable characters: {type_raw!r}")

    # Separate canonical fields from extras
    extra_fields: dict[str, object] = {}
    for k, v in data.items():
        if k not in _CANONICAL_EVENT_FIELDS:
            extra_fields[k] = v

    # Validate extra fields are JSON-compatible
    _validate_json_value(extra_fields)

    return RawSessionEvent(
        event_id=event_id_raw,
        real_time=parsed_dt,
        world_tick=world_tick_raw,
        type=type_raw,
        extra_fields=extra_fields,
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
            f"Invalid UTF-8 in events.jsonl: {path}",
            cause=exc,
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"Failed to read events.jsonl: {path}",
            cause=exc,
        ) from exc


# ── Strict JSONL parser ────────────────────────────────────────────────────────


def _parse_events_jsonl(text: str) -> list[RawSessionEvent]:
    """Parse a complete events.jsonl text into a list of RawSessionEvent.

    Every non-empty line must be a complete JSON object with valid canonical
    event fields.  Blank lines are treated as corruption.  The final line
    must be newline-terminated.

    Args:
        text: The complete events.jsonl UTF-8 text.

    Returns:
        A list of ``RawSessionEvent`` values in physical order.

    Raises:
        StorageError: Any line is malformed, missing canonical fields, or
            the final line is not newline-terminated.
    """
    if not text:
        return []

    if not text.endswith("\n"):
        raise StorageError("events.jsonl: final record is not newline-terminated")

    # Remove trailing newline for split; empty final line is the terminator
    lines = text.split("\n")
    # Last element after split("\n") of "a\nb\n" is ""
    if lines and lines[-1] == "":
        lines = lines[:-1]

    events: list[RawSessionEvent] = []
    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()

        # Blank line is corruption
        if not stripped:
            raise StorageError(f"events.jsonl corruption at line {line_no}: unexpected blank line")

        event = _deserialize_event(raw_line)
        events.append(event)

    return events


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

    Raises:
        StorageError: A root is missing, is a symlink, is a regular file,
            or resolves outside the Vault root.
    """
    for relative in _SESSION_RUNTIME_ROOTS:
        path = vault_root / relative

        if path.is_symlink():
            raise StorageError(f"Session runtime root is a symlink, rejected for safety: {path}")

        if not path.exists():
            raise StorageError(f"Session runtime root does not exist: {path}")

        if not path.is_dir():
            raise StorageError(f"Session runtime root is not a directory: {path}")

        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(vault_root)
        except ValueError:
            raise StorageError(
                f"Session runtime root resolves outside the Vault root: {path}"
            ) from None


# ── Event ID allocation ────────────────────────────────────────────────────────


def _allocate_event_id(events: list[RawSessionEvent]) -> str:
    """Allocate the next event ID for a session.

    Reads all existing valid events and computes ``max numeric event ID + 1``.
    If no events exist, returns ``"evt_001"``.

    Args:
        events: The current list of valid events (in physical order).

    Returns:
        The next event ID (e.g. ``"evt_002"``).

    Raises:
        StorageError: A duplicate event ID was found in the existing events.
    """
    seen_ids: set[str] = set()
    max_num = 0
    for ev in events:
        m = _EVENT_ID_RE.match(ev.event_id)
        if m:
            num = int(m.group(1))
            if ev.event_id in seen_ids:
                raise StorageError(f"Duplicate event ID in existing events: {ev.event_id}")
            seen_ids.add(ev.event_id)
            if num > max_num:
                max_num = num

    next_num = max_num + 1
    return f"evt_{next_num:03d}"


# ── Append-only primitive ──────────────────────────────────────────────────────


def _append_event_line(path: Path, encoded_line: bytes) -> None:
    """Append a single encoded JSON line to an events file.

    Uses ``os.open`` with ``O_APPEND`` to guarantee atomic appends at the
    OS level.  The line is written as a single ``os.write`` call and
    fsynced before returning.

    Args:
        path: The absolute path to ``events.jsonl``.
        encoded_line: The UTF-8-encoded JSON line (must end with ``\\n``).

    Raises:
        StorageError: Open, write, short write, or fsync failed.
    """
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_BINARY)
    except OSError as exc:
        raise StorageError(
            f"Failed to open events.jsonl for append: {path}",
            cause=exc,
        ) from exc

    try:
        written = os.write(fd, encoded_line)
        if written != len(encoded_line):
            raise StorageError(
                f"Short write to events.jsonl: wrote {written} of {len(encoded_line)} bytes"
            )
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
    """Build an ``AuditRecord`` for a session event append."""
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


# ── ObsidianSessionEventRepository ─────────────────────────────────────────────


class ObsidianSessionEventRepository:
    """Concrete session event repository backed by ``events.jsonl``.

    Owns append and read operations for raw session events in the
    ``_system/raw/sessions/<session_id>/events.jsonl`` file.

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

    # ── Read ──────────────────────────────────────────────────────────────

    def list_events(self, session_id: str) -> list[RawSessionEvent]:
        """Read all raw events for a session in physical order.

        Args:
            session_id: The session identifier.

        Returns:
            A list of ``RawSessionEvent`` values in physical append order.
            Returns an empty list for an empty events file.

        Raises:
            StorageError: The events file is corrupt, malformed, or the
                path is unsafe.
        """
        _validate_session_runtime_roots(self._vault_root)
        paths = resolve_session_storage_paths(self._vault_root, session_id)

        if not paths.raw_events.exists():
            raise StorageError(f"events.jsonl not found for session {session_id}")

        if paths.raw_events.is_dir():
            raise StorageError(f"events.jsonl is a directory: {paths.raw_events}")

        text = _read_exact_text(paths.raw_events)

        if not text:
            return []

        return _parse_events_jsonl(text)

    # ── Append ────────────────────────────────────────────────────────────

    def append_event(
        self,
        session_id: str,
        *,
        event_type: str,
        real_time: AwareDatetime,
        world_tick: int,
        extra_fields: dict[str, object] | None,
        audit: AuditContext,
    ) -> RawSessionEvent:
        """Append a raw event to the session's events.jsonl.

        Lifecycle:
        1. Validate session runtime roots.
        2. Resolve and validate event path.
        3. Read current events and validate consistency.
        4. Allocate event ID.
        5. Build candidate event.
        6. Serialize candidate.
        7. Compute before/after hashes.
        8. Append audit intent.
        9. Reauthorize paths after durable intent.
        10. Re-read exact current log and verify before hash unchanged.
        11. Append encoded line.
        12. Verify persisted result (read-back, hash, parse).
        13. Append committed audit.

        Args:
            session_id: The session identifier.
            event_type: The event type string.
            real_time: Timezone-aware real-world timestamp.
            world_tick: The canonical game-world tick.
            extra_fields: Event-specific top-level fields.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``RawSessionEvent``.

        Raises:
            StorageError: The events file is corrupt, unsafe, or an
                I/O error occurred.
            ConflictError: The events file changed between intent and
                append.
        """
        # 1. Validate session runtime roots
        _validate_session_runtime_roots(self._vault_root)

        # 2. Resolve and validate event path
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        _validate_mutation_environment(self._vault_root, self._audit_service)

        events_path = paths.raw_events

        # Validate events path
        if events_path.is_symlink():
            raise StorageError(f"events.jsonl is a symlink, rejected for safety: {events_path}")
        if not events_path.exists():
            raise StorageError(f"events.jsonl not found for session {session_id}")
        if events_path.is_dir():
            raise StorageError(f"events.jsonl is a directory: {events_path}")

        # 3. Read current events and validate consistency
        before_text = _read_exact_text(events_path)
        before_hash = _content_hash(before_text)

        existing_events = _parse_events_jsonl(before_text) if before_text else []

        # 4. Allocate event ID
        event_id = _allocate_event_id(existing_events)

        # 5. Build candidate event
        extra = dict(extra_fields) if extra_fields else {}
        # Reject canonical-field collision in extras
        for k in extra:
            if k in _CANONICAL_EVENT_FIELDS:
                raise StorageError(f"Extra field {k!r} collides with a canonical event field")

        # Validate extra fields are JSON-compatible
        _validate_json_value(extra)

        candidate = RawSessionEvent(
            event_id=event_id,
            real_time=real_time,
            world_tick=world_tick,
            type=event_type,
            extra_fields=extra,
        )

        # 6. Serialize candidate
        encoded_line = _serialize_event(candidate).encode("utf-8")
        after_text = before_text + encoded_line.decode("utf-8")
        after_hash = _content_hash(after_text)

        # 7. Append audit intent
        intent_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.event.append",
            before_hash=before_hash,
            after_hash=after_hash,
            source=audit.source,
            session=session_id,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
            phase="intent",
        )
        self._audit_service.append(intent_record)

        # 8. Reauthorize paths after durable intent
        paths = resolve_session_storage_paths(self._vault_root, session_id)
        _validate_mutation_environment(self._vault_root, self._audit_service)

        events_path = paths.raw_events

        # Revalidate events path
        if events_path.is_symlink():
            raise StorageError(f"events.jsonl became a symlink after intent: {events_path}")
        if not events_path.exists():
            raise StorageError(f"events.jsonl disappeared after intent: {events_path}")

        # 9. Re-read exact current log and verify before hash unchanged
        current_text = _read_exact_text(events_path)
        current_hash = _content_hash(current_text)

        if current_hash != before_hash:
            raise ConflictError(
                f"events.jsonl content changed after intent for operation {audit.operation_id}"
            )

        # 10. Append encoded line
        _append_event_line(events_path, encoded_line)

        # 11. Verify persisted result
        persisted_text = _read_exact_text(events_path)
        persisted_hash = _content_hash(persisted_text)

        if persisted_hash != after_hash:
            raise StorageError(
                f"Event append committed but hash verification failed for "
                f"operation {audit.operation_id}"
            )

        # Verify exact prefix invariant
        if not persisted_text.startswith(before_text):
            raise StorageError(
                f"Event append committed but prefix invariant violated for "
                f"operation {audit.operation_id}"
            )

        if persisted_text != before_text + encoded_line.decode("utf-8"):
            raise StorageError(
                f"Event append committed but exact content invariant violated for "
                f"operation {audit.operation_id}"
            )

        # Strictly parse all events and verify final event
        all_events = _parse_events_jsonl(persisted_text)
        if not all_events:
            raise StorageError(
                f"Event append committed but no events found in persisted file "
                f"for operation {audit.operation_id}"
            )

        persisted_event = all_events[-1]
        if persisted_event.event_id != candidate.event_id:
            raise StorageError(
                f"Event append committed but final event ID mismatch for "
                f"operation {audit.operation_id}"
            )

        # 12. Append committed audit
        committed_record = _build_audit_record(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            operation="session.event.append",
            before_hash=before_hash,
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
                f"Event append committed but audit finalization failed "
                f"for operation {audit.operation_id}.  "
                f"The event exists in {events_path}.  "
                f"An intent audit record is present.",
                cause=exc,
            ) from exc

        return persisted_event
