"""Atomic text-write primitive for Vault entity persistence.

This module provides the low-level ``atomic_write_text`` function that
writes a UTF-8 text string to a target file using an atomic-replacement
lifecycle::

    candidate content
        ↓
    create unique temporary sibling
        ↓
    write UTF-8 text + flush + fsync
        ↓
    close file descriptor
        ↓
    validate candidate content
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
* an existing target symlink (including dangling/broken) is rejected with
  ``StorageError``;
* ``target`` must be an absolute path.

Validator contract
------------------

``atomic_write_text`` accepts a required ``validator`` callback that:

* runs AFTER the temporary file has been flushed, fsynced and closed;
* runs BEFORE ``os.replace``;
* may return any value (the return value is ignored);
* may raise any exception.

If the validator raises any exception, the temporary file is cleaned up and
the exception propagates **unchanged** — it is never translated to
``StorageError``, even if the exception is an ``OSError``.

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

from dnd_assistant.errors import StorageError

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
    3. Flush Python's buffered writer and ``os.fsync`` the file descriptor.
    4. Close the temporary file (via context-manager exit).
    5. Call ``validator(content)`` — may raise to abort replacement.
    6. ``os.replace(temp_path, target_path)`` — atomic replacement.

    Args:
        target: The destination file path (must be absolute).
        content: The UTF-8 text content to write.
        validator: A callable that receives the full ``content`` string
            after the temporary file has been flushed, fsynced and closed
            but before ``os.replace``.  Raise to abort the write.

    Raises:
        StorageError: A filesystem or path precondition error occurred.
        *: Propagated unchanged from ``validator``.
    """
    target_path = _validate_target(target)
    temp_path: Path | None = None

    try:
        temp_path = _create_temp(target_path)
        _write_and_fsync(temp_path, content)
        # validator runs outside any OSError-translation boundary so its
        # exceptions (including OSError) propagate unchanged.
        validator(content)
        _os_replace(str(temp_path), str(target_path))
    except StorageError:
        raise
    except Exception:
        _cleanup_temp(temp_path)
        raise
    finally:
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

    # Check symlink identity BEFORE exists() — Path.exists() follows the
    # link and returns False for dangling/broken symlinks, so a dangling
    # symlink would otherwise pass through undetected.
    if target_path.is_symlink():
        raise StorageError(f"Target path is a symlink, refusing to replace: {target_path}")

    if target_path.exists():
        if target_path.is_dir():
            raise StorageError(
                f"Target path is an existing directory, refusing to replace: {target_path}"
            )

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


def _write_and_fsync(temp_path: Path, content: str) -> None:
    """Write ``content`` to ``temp_path``, flush and fsync.

    Uses ``newline=""`` to prevent Python from translating ``\\n`` to
    ``\\r\\n`` on Windows.  The file descriptor is closed by the
    context manager on exit, making the temp file safe for
    ``os.replace`` on Windows.

    Lifecycle within this helper::

        open → write → flush → fsync → close

    Raises:
        StorageError: Write, flush or fsync failed.
    """
    try:
        with open(temp_path, mode="w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise StorageError(
            f"Failed to write/flush/fsync temporary file: {temp_path}",
            cause=exc,
        ) from exc


def _os_replace(src: str, dst: str) -> None:
    """Atomic ``os.replace`` with ``OSError`` → ``StorageError`` translation.

    Raises:
        StorageError: Replacement failed.
    """
    try:
        os.replace(src, dst)
    except OSError as exc:
        raise StorageError(
            f"Failed to atomically replace {dst} with {src}",
            cause=exc,
        ) from exc


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
