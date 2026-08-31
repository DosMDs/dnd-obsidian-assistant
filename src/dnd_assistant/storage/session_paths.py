"""Session storage path/layout safety.

This module defines the deterministic, read-only contract for resolving
session storage paths within an Obsidian Vault.

It provides:

- ``SessionStoragePaths`` — an immutable value object holding the safe
  absolute paths for one session's storage locations.
- ``resolve_session_storage_paths`` — the typed resolver that validates
  the Vault root and session ID, then returns ``SessionStoragePaths``
  without creating any directories or files.

Sessions have two storage subtrees within a Vault:

1. **Sessions/<id>/** — canonical session Markdown (``Session.md``).
2. **_system/raw/sessions/<id>/** — raw session metadata and events.

This module belongs to the storage layer and must not import from:
    models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dnd_assistant.errors import StorageError
from dnd_assistant.storage.paths import _resolve_vault_root

# ── Public result type ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SessionStoragePaths:
    """Immutable value object holding safe absolute session storage paths.

    Instances returned by ``resolve_session_storage_paths()`` contain
    safe resolved paths under the validated Vault root.  No directories
    or files are created by this resolver.

    Attributes:
        session_dir: ``Sessions/<session_id>/``
        session_md: ``Sessions/<session_id>/Session.md``
        raw_dir: ``_system/raw/sessions/<session_id>/``
        raw_metadata: ``_system/raw/sessions/<session_id>/metadata.json``
        raw_events: ``_system/raw/sessions/<session_id>/events.jsonl``
    """

    session_dir: Path
    session_md: Path
    raw_dir: Path
    raw_metadata: Path
    raw_events: Path


# ── Session ID validation ────────────────────────────────────────────────────

# Windows reserved device names (case-insensitive, with or without extension)
_WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset(
    name.lower()
    for name in [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    ]
)

# Characters that are invalid in Windows filenames
_WINDOWS_INVALID_CHARS: frozenset[str] = frozenset('<>:"|?*')


def _validate_session_id_for_path(session_id: str) -> str:
    """Validate a session ID for safe use as a single directory component.

    This validation is stricter than the domain ``Session.id`` because
    storage paths must be safe on both Windows and macOS.

    Requirements:
    - must be a ``str``
    - non-empty
    - no leading or trailing whitespace
    - printable
    - must not be ``"."`` or ``".."``
    - must not contain ``/`` or ``\\``
    - must not contain any Windows-invalid filename characters (``<``, ``>``,
      ``:``, ``"``, ``|``, ``?``, ``*``)
    - must not end with ``.`` or `` `` (trailing dot/space unsafe on Windows)
    - must not be a Windows reserved device name (case-insensitive, with or
      without extension)

    Args:
        session_id: The session identifier to validate.

    Returns:
        The validated session ID (same value).

    Raises:
        StorageError: The session ID is not safe for use as a path component.
    """
    if not isinstance(session_id, str):
        raise StorageError(f"Session ID must be a string, got {type(session_id).__name__}")

    if not session_id:
        raise StorageError("Session ID must not be empty")

    if session_id.strip() != session_id:
        raise StorageError("Session ID must not have leading or trailing whitespace")

    if not session_id.isprintable():
        raise StorageError("Session ID must not contain non-printable characters")

    if session_id in (".", ".."):
        raise StorageError(f"Session ID must not be '.' or '..', got: {session_id!r}")

    if "/" in session_id:
        raise StorageError(f"Session ID must not contain '/', got: {session_id!r}")

    if "\\" in session_id:
        raise StorageError(f"Session ID must not contain '\\', got: {session_id!r}")

    # Reject Windows-invalid filename characters
    for ch in session_id:
        if ch in _WINDOWS_INVALID_CHARS:
            raise StorageError(f"Session ID must not contain character {ch!r}, got: {session_id!r}")

    # Trailing dot or space is unsafe on Windows
    if session_id.endswith("."):
        raise StorageError(f"Session ID must not end with '.', got: {session_id!r}")

    if session_id.endswith(" "):
        raise StorageError(f"Session ID must not end with space, got: {session_id!r}")

    # Windows reserved device names (case-insensitive, with or without extension)
    base = session_id.split(".")[0].lower() if "." in session_id else session_id.lower()
    if base in _WINDOWS_RESERVED_NAMES:
        raise StorageError(
            f"Session ID must not be a Windows reserved device name, got: {session_id!r}"
        )

    return session_id


# ── Path component symlink check ─────────────────────────────────────────────


def _check_component_symlinks(root: Path, relative: Path) -> Path:
    """Check existing path components beneath ``root`` for symlinks.

    Iterates over the parts of ``relative``, building each intermediate
    path and checking whether it is a symlink (dangling or live).
    Symlink identity is checked **before** ``exists()`` so that dangling
    symlinks are also rejected.  If any existing component is a symlink,
    raises ``StorageError``.

    Args:
        root: The resolved Vault root path.
        relative: A relative path whose components to inspect.

    Returns:
        The resolved absolute path.

    Raises:
        StorageError: An existing path component is a symlink, or the
            resolved path escapes ``root``.
    """
    accumulated = root
    for part in relative.parts:
        accumulated = accumulated / part
        # Check is_symlink() first — dangling symlinks have
        # is_symlink() == True but exists() == False.
        if accumulated.is_symlink():
            raise StorageError(
                f"Session storage path component is a symlink, rejected for safety: {accumulated}"
            )

    resolved = accumulated.resolve(strict=False)

    # Verify containment within vault root
    try:
        resolved.relative_to(root)
    except ValueError:
        raise StorageError(
            f"Session storage path resolves outside the Vault root: {resolved}"
        ) from None

    return resolved


def _check_leaf_symlinks(*paths: Path) -> None:
    """Check that none of the given leaf paths is an existing symlink.

    A leaf path (e.g. ``Session.md``, ``metadata.json``) that already
    exists as a symlink must be rejected even if all parent components
    are safe.

    Args:
        *paths: Leaf paths to inspect.

    Raises:
        StorageError: A leaf path exists and is a symlink.
    """
    for path in paths:
        if path.is_symlink():
            raise StorageError(
                f"Session storage leaf path is a symlink, rejected for safety: {path}"
            )


# ── Public resolver ──────────────────────────────────────────────────────────


def resolve_session_storage_paths(
    vault_root: str | Path,
    session_id: str,
) -> SessionStoragePaths:
    """Resolve safe session storage paths within a Vault.

    This is a pure, read-only resolver.  It validates the Vault root and
    session ID, then returns the expected paths without creating any
    directories or files.

    Args:
        vault_root: The root directory of the Obsidian Vault.
        session_id: The session identifier (validated for path safety).

    Returns:
        ``SessionStoragePaths`` with all absolute, resolved paths.

    Raises:
        StorageError: The Vault root is invalid, the session ID is not
            safe for filesystem use, or an existing path component is a
            symlink.
    """
    root = _resolve_vault_root(vault_root)
    validated_id = _validate_session_id_for_path(session_id)

    # Build relative paths for both session subtrees
    session_rel = Path("Sessions") / validated_id
    raw_rel = Path("_system") / "raw" / "sessions" / validated_id

    # Resolve with symlink checks
    session_dir = _check_component_symlinks(root, session_rel)
    raw_dir = _check_component_symlinks(root, raw_rel)

    # Construct leaf paths
    session_md = session_dir / "Session.md"
    raw_metadata = raw_dir / "metadata.json"
    raw_events = raw_dir / "events.jsonl"

    # Check leaf paths for existing symlinks (dangling or live)
    _check_leaf_symlinks(session_md, raw_metadata, raw_events)

    return SessionStoragePaths(
        session_dir=session_dir,
        session_md=session_md,
        raw_dir=raw_dir,
        raw_metadata=raw_metadata,
        raw_events=raw_events,
    )
