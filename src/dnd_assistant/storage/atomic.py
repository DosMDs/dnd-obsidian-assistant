"""Atomic text-write primitive for Vault entity persistence.

This module provides the low-level ``atomic_write_text`` function that
writes a UTF-8 text string to a target file using an atomic-replacement
lifecycle:

    candidate content
        ↓
    create unique temporary sibling
        ↓
    write UTF-8 text (exact newline preservation)
        ↓
    flush
        ↓
    fsync temporary file
        ↓
    validate candidate content
        ↓
    close temporary file
        ↓
    os.replace(temp, target)
        ↓
    target now contains complete new content

Key invariant
-------------

The target file is **never** directly rewritten in place.  If any failure
occurs before successful ``os.replace``:

* an existing target remains unchanged;
* a previously missing target remains missing;
* temporary files are cleaned up on a best-effort basis.

Target-path preconditions
-------------------------

The caller is responsible for supplying an already-authorised target path
(see S3-02 ``resolve_entity_path``).  This module validates immediate
filesystem assumptions only:

* ``target`` must resolve to a ``Path`` value;
* target parent directory must already exist and be a directory;
* target itself must not be an existing directory;
* an existing target symlink is rejected with ``StorageError``;
* ``target`` must be an absolute path.

Validator contract
------------------

``atomic_write_text`` accepts a required ``validator`` callback that:

* runs AFTER the temporary file has been flushed and fsynced;
* runs BEFORE ``os.replace``;
* may return any value (the return value is ignored);
* may raise a validation/domain exception.

If the validator raises ``dnd_assistant.errors.ValidationError`` (or any
other deliberate caller-supplied exception), the temporary file is cleaned
up and the exception propagates unchanged — it is **not** translated to
``StorageError``.

Usage::

    from dnd_assistant.storage.atomic import atomic_write_text

    atomic_write_text(
        target="/path/to/entity.md",
        content="---\\nid: my-entity\\n...",
        validator=lambda c: parse(c),
    )
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from dnd_assistant.errors import StorageError, ValidationError

# ── Public API ───────────────────────────────────────────────────────────────


def atomic_write_text(
    target: str | Path,
    content: str,
    *,
    validator: Callable[[str], object],
) -> None:
    """Atomically write ``content`` to ``target`` via a temporary sibling file.

    The write lifecycle is:

    1. Create a unique temporary file in the same directory as ``target``.
    2. Write ``content`` encoded as UTF-8 with exact newline preservation.
    3. Flush Python's buffered writer.
    4. ``os.fsync`` the temporary file descriptor.
    5. Call ``validator(content)`` — may raise to abort replacement.
    6. Close the temporary file.
    7. ``os.replace(temp_path, target)`` — atomic replacement.

    Args:
        target: The destination file path (must be absolute).
        content: The UTF-8 text content to write.
        validator: A callable that receives the full ``content`` string
            after the temporary file has been flushed and fsynced but
            before ``os.replace``.  Raise to abort the write.

    Raises:
        StorageError: A filesystem or path precondition error occurred.
        ValidationError: Propagated unchanged from ``validator``.
    """
    target_path = _validate_target(target)
    temp_path: Path | None = None

    try:
        temp_path = _create_temp(target_path)
        _write_content(temp_path, content)
        _flush_and_fsync(temp_path)
        validator(content)
        _close_temp(temp_path)
        os.replace(str(temp_path), str(target_path))
    except StorageError:
        _cleanup_temp(temp_path)
        raise
    except ValidationError:
        _cleanup_temp(temp_path)
        raise
    except OSError as exc:
        _cleanup_temp(temp_path)
        raise StorageError(
            f"Failed to atomically write {target_path}",
            cause=exc,
        ) from exc
    except BaseException:
        _cleanup_temp(temp_path)
        raise
    else:
        _cleanup_temp(temp_path)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _validate_target(target: str | Path) -> Path:
    """Validate target path preconditions.

    Returns a resolved absolute ``Path``.

    Raises:
        StorageError: Any precondition is violated.
    """
    try:
        target_path = Path(target)
    except TypeError as exc:
        raise StorageError(
            "Target path must be a string or Path",
            cause=exc,
        ) from exc

    if not target_path.is_absolute():
        raise StorageError(f"Target path must be absolute, got: {target_path}")

    parent = target_path.parent

    if not parent.exists():
        raise StorageError(f"Target parent directory does not exist: {parent}")

    if not parent.is_dir():
        raise StorageError(f"Target parent is not a directory: {parent}")

    if target_path.exists():
        if target_path.is_dir():
            raise StorageError(
                f"Target path is an existing directory, refusing to replace: {target_path}"
            )
        if target_path.is_symlink():
            raise StorageError(f"Target path is a symlink, refusing to replace: {target_path}")

    return target_path


def _create_temp(target: Path) -> Path:
    """Create a unique temporary file in the same directory as ``target``.

    Returns the ``Path`` to the temporary file.

    Raises:
        StorageError: Temporary file creation failed.
    """
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        os.close(fd)
        return Path(temp_name)
    except OSError as exc:
        raise StorageError(
            f"Failed to create temporary file beside {target}",
            cause=exc,
        ) from exc


def _write_content(temp_path: Path, content: str) -> None:
    """Write ``content`` to ``temp_path`` with UTF-8 and exact newline preservation.

    Uses ``newline=""`` to prevent Python from translating ``\\n`` to
    ``\\r\\n`` on Windows.

    Raises:
        StorageError: Write failed.
    """
    try:
        with open(temp_path, mode="w", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as exc:
        raise StorageError(
            f"Failed to write content to temporary file: {temp_path}",
            cause=exc,
        ) from exc


def _flush_and_fsync(temp_path: Path) -> None:
    """Flush and fsync the temporary file.

    Opens the file, flushes the Python buffer, then calls ``os.fsync``
    on the file descriptor.

    Raises:
        StorageError: Flush or fsync failed.
    """
    try:
        with open(temp_path, mode="ab") as f:
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise StorageError(
            f"Failed to flush/fsync temporary file: {temp_path}",
            cause=exc,
        ) from exc


def _close_temp(temp_path: Path) -> None:
    """Ensure the temporary file is closed before replacement.

    On Windows, ``os.replace`` fails if the file is still open.
    This is a no-op guard; the file should already be closed by
    context-manager exit in previous steps, but we explicitly
    re-open and close to be safe.
    """
    # The file is already closed by context-manager exit in
    # _write_content and _flush_and_fsync.  This is a safety
    # measure for any edge case where a descriptor might remain.
    try:
        fd = os.open(str(temp_path), os.O_RDONLY)
        os.close(fd)
    except OSError:
        pass  # Best-effort; the file may already be closed


def _cleanup_temp(temp_path: Path | None) -> None:
    """Remove the temporary file if it still exists.

    This is best-effort: cleanup failure must not mask the primary
    exception.
    """
    if temp_path is None:
        return
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass  # Best-effort; do not mask primary error
