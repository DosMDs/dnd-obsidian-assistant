"""Vault path safety and entity-file discovery.

This module provides the trusted path-resolution and entity-file
candidate discovery layer used by VaultRepository.  It enforces:

- canonical Vault entity-directory resolution via ``EntityDirectory``;
- safe normalisation of entity paths (no ``..`` traversal, no escape
  from the Vault root, no escape from approved entity directories);
- restriction to approved MVP entity directories;
- safe recursive discovery of Markdown entity-file candidates;
- symlink-safe discovery behaviour;
- deterministic discovery ordering;
- storage-level filesystem error translation.

S3-02 discovers **safe candidate file paths only**.  It does NOT:

- open, read, or parse Markdown files;
- validate YAML frontmatter;
- extract ``EntityId`` from filenames or file contents;
- compare YAML ``type`` to directory;
- detect duplicate ``EntityId`` values;
- return ``VaultDocument`` or ``Entity``.

Those responsibilities belong to S3-05 (repository read/list).

Usage::

    from dnd_assistant.storage.paths import discover_entity_files

    candidates = discover_entity_files(vault_root)
    for c in candidates:
        print(c.entity_type, c.path)
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.types import EntityDirectory

# ── Public result type ──────────────────────────────────────────────────────


class DiscoveredEntityFile:
    """A filesystem Markdown candidate discovered in a canonical entity directory.

    This is a discovery-only result.  It does NOT contain:

    - ``EntityId`` (stable ID is independent of filename);
    - a parsed ``Entity`` or ``VaultDocument``;
    - any file contents.

    Those require reading and parsing the file, which belongs to S3-05.
    """

    def __init__(self, entity_type: EntityType, path: Path) -> None:
        self._entity_type = entity_type
        self._path = path

    @property
    def entity_type(self) -> EntityType:
        """The canonical entity type for the directory this file was found in."""
        return self._entity_type

    @property
    def path(self) -> Path:
        """Absolute resolved path to the Markdown file."""
        return self._path

    def __repr__(self) -> str:
        return f"DiscoveredEntityFile(type={self._entity_type.value!r}, path={str(self._path)!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DiscoveredEntityFile):
            return NotImplemented
        return self._entity_type == other._entity_type and self._path == other._path

    def __hash__(self) -> int:
        return hash((self._entity_type, self._path))


# ── Vault root resolution ───────────────────────────────────────────────────


def _resolve_vault_root(vault_root: str | Path) -> Path:
    """Normalise and validate the Vault root directory.

    Returns a canonical absolute resolved ``Path``.

    Raises:
        StorageError: The path does not exist, is not a directory,
            or cannot be resolved.
    """
    try:
        path = Path(vault_root)
    except TypeError as exc:
        raise StorageError(
            "Vault root must be a string or Path",
            cause=exc,
        ) from exc

    if not path.exists():
        raise StorageError(f"Vault root does not exist: {path}")

    if not path.is_dir():
        raise StorageError(f"Vault root must be a directory, got a file: {path}")

    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise StorageError(
            f"Failed to resolve Vault root path: {path}",
            cause=exc,
        ) from exc

    return resolved


# ── Safe canonical entity-directory resolution ──────────────────────────────


def _resolve_entity_directory(root: Path, entity_type: EntityType) -> Path:
    """Safely resolve a canonical entity directory path.

    Derives the relative path from ``EntityDirectory``, checks that no
    existing path component beneath ``root`` is a symlink, resolves the
    resulting path, and verifies containment within ``root``.

    Missing path components are acceptable — the check only applies to
    components that already exist on the filesystem.

    Args:
        root: An already-resolved canonical Vault root path.
        entity_type: The entity type whose canonical directory to resolve.

    Returns:
        The safe canonical absolute path to the entity directory.

    Raises:
        StorageError: An existing path component beneath ``root`` is a
            symlink, or the resolved path escapes ``root``.
    """
    directory = EntityDirectory.for_type(entity_type)
    relative = Path(directory.value)

    # Inspect each existing path component beneath root before resolving.
    # This catches symlinks that would be erased by .resolve().
    accumulated = root
    for part in relative.parts:
        accumulated = accumulated / part
        if accumulated.exists() and accumulated.is_symlink():
            raise StorageError(
                f"Canonical entity directory path component is a symlink, "
                f"rejected for safety: {accumulated}"
            )

    resolved = accumulated.resolve(strict=False)

    # Verify containment within vault root
    try:
        resolved.relative_to(root)
    except ValueError:
        raise StorageError(
            f"Entity directory resolves outside the Vault root: {resolved}"
        ) from None

    return resolved


def entity_directory(
    vault_root: str | Path,
    entity_type: EntityType,
) -> Path:
    """Return the canonical Vault directory path for an ``EntityType``.

    The returned path is an absolute resolved path rooted under
    ``vault_root``.

    Raises:
        StorageError: The vault_root is invalid, the entity directory
            contains a symlink, or the path cannot be resolved.
    """
    root = _resolve_vault_root(vault_root)
    return _resolve_entity_directory(root, entity_type)


# ── Path traversal safety ───────────────────────────────────────────────────


def _has_traversal(path: Path) -> bool:
    """Check whether *any* component of ``path`` is a parent traversal.

    Rejects ``..``, platform-equivalent parent references, and absolute
    paths embedded within a relative path.

    This is a structural check on the path string as supplied, not a
    resolved-path containment check.
    """
    # Reject absolute paths outright when used as relative components
    if path.is_absolute():
        return True

    # Check every part for parent traversal
    for part in path.parts:
        if part == "..":
            return True

    return False


def resolve_entity_path(
    vault_root: str | Path,
    entity_type: EntityType,
    relative_path: str | Path,
) -> Path:
    """Resolve a relative entity Markdown path safely.

    The supplied ``relative_path`` must be a relative path underneath
    the canonical entity directory for ``entity_type``.  It may include
    nested subdirectories for human Vault organisation.

    Args:
        vault_root: The root directory of the Obsidian Vault.
        entity_type: The canonical entity type.
        relative_path: A relative path to an entity Markdown file within
            the entity's canonical directory.

    Returns:
        The absolute resolved path to the entity file.

    Raises:
        StorageError: The path contains ``..`` traversal, is absolute,
            resolves outside the entity directory, resolves outside the
            Vault root, or is not a Markdown file.
    """
    root = _resolve_vault_root(vault_root)
    canonical_dir = _resolve_entity_directory(root, entity_type)

    supplied = Path(relative_path)

    # Reject traversal components structurally
    if _has_traversal(supplied):
        raise StorageError(f"Path contains parent-directory traversal ('..'): {relative_path}")

    # Reject absolute paths
    if supplied.is_absolute():
        raise StorageError(f"Path must be relative, got absolute path: {relative_path}")

    # Resolve the candidate path
    candidate = (canonical_dir / supplied).resolve(strict=False)

    # Must be inside the canonical entity directory
    try:
        candidate.relative_to(canonical_dir)
    except ValueError:
        raise StorageError(
            f"Path resolves outside the canonical entity directory: {relative_path}"
        ) from None

    # Must be inside the Vault root
    try:
        candidate.relative_to(root)
    except ValueError:
        raise StorageError(f"Path resolves outside the Vault root: {relative_path}") from None

    # Must be a Markdown file
    if candidate.suffix.casefold() != ".md":
        raise StorageError(f"Entity path must be a Markdown (.md) file, got: {candidate.suffix}")

    return candidate


# ── Entity file discovery ───────────────────────────────────────────────────


def _discover_in_directory(
    directory: Path,
    entity_type: EntityType,
    vault_root: Path,
) -> list[DiscoveredEntityFile]:
    """Recursively discover Markdown entity-file candidates in ``directory``.

    This function does NOT follow symlinked directories and does NOT
    return symlinked files.  It only returns regular ``.md`` files.

    Args:
        directory: The canonical entity directory to scan (must already
            be resolved and validated).
        entity_type: The ``EntityType`` for this directory.
        vault_root: The resolved Vault root (used for containment check).

    Returns:
        A deterministically ordered list of discovered candidates.
    """
    if not directory.exists():
        return []

    if not directory.is_dir():
        raise StorageError(f"Expected entity directory is not a directory: {directory}")

    candidates: list[DiscoveredEntityFile] = []

    try:
        for entry in directory.iterdir():
            if entry.is_dir():
                # Recurse into subdirectories (but not symlinks)
                if not entry.is_symlink():
                    candidates.extend(_discover_in_directory(entry, entity_type, vault_root))
            elif entry.is_file() and not entry.is_symlink():
                if entry.suffix.casefold() == ".md":
                    candidates.append(
                        DiscoveredEntityFile(
                            entity_type=entity_type,
                            path=entry.resolve(strict=False),
                        )
                    )
    except OSError as exc:
        raise StorageError(
            f"Failed to read entity directory: {directory}",
            cause=exc,
        ) from exc

    return candidates


def discover_entity_files(
    vault_root: str | Path,
    entity_type: EntityType | None = None,
) -> list[DiscoveredEntityFile]:
    """Discover Markdown entity-file candidates in the Vault.

    Scans the canonical entity directories under ``vault_root`` for
    ``.md`` files.  Discovery is recursive within each entity directory
    but does NOT follow symlinks.

    Args:
        vault_root: The root directory of the Obsidian Vault.
        entity_type: If specified, only scan the canonical directory for
            this entity type.  If ``None``, scan all four MVP entity
            directories.

    Returns:
        A deterministically ordered list of discovered candidates.
        Returns an empty list when no candidates are found.

    Raises:
        StorageError: The vault_root is invalid, or a filesystem error
            occurs during discovery.
    """
    root = _resolve_vault_root(vault_root)

    if entity_type is not None:
        directories: list[tuple[EntityType, Path]] = [
            (entity_type, _resolve_entity_directory(root, entity_type)),
        ]
    else:
        directories = []
        for ed in EntityDirectory:
            # Map EntityDirectory member back to EntityType by name
            et = EntityType[ed.name]
            directories.append((et, _resolve_entity_directory(root, et)))

    all_candidates: list[DiscoveredEntityFile] = []

    for et, directory in directories:
        all_candidates.extend(_discover_in_directory(directory, et, root))

    # Deterministic ordering: sort by Vault-relative POSIX path.
    # Primary key: casefolded path (case-insensitive).
    # Secondary key: exact path (deterministic tie-breaker for
    # case-distinct paths on case-sensitive filesystems).
    all_candidates.sort(
        key=lambda c: (
            c.path.relative_to(root).as_posix().casefold(),
            c.path.relative_to(root).as_posix(),
        )
    )

    return all_candidates
