"""S12-03 trusted Obsidian derived-state store for Campaign State.

Persists the materialized Campaign State projection as human-readable,
player-facing Markdown under ``<vault>/State/`` plus a derived manifest::

    <vault>/State/World State.md
    <vault>/State/Recently Touched.md
    <vault>/State/.campaign-state-manifest.json

These files are **derived storage only**.  The Obsidian Vault remains the only
campaign Source of Truth; deleting every managed Campaign State file loses no
canonical information and rebuild restores the projection from source
evidence.

Filesystem authority:

- physical destinations are derived exclusively from the trusted
  ``CampaignStateArtifact`` allowlist in :data:`ARTIFACT_FILENAMES` and the
  fixed manifest name; manifest ``RelativeArtifactPath`` values are never
  resolved or joined to the filesystem;
- the ``State/`` directory is created exactly (never an arbitrary tree) and is
  always required to be a real, non-redirecting directory contained inside the
  resolved Vault root; symlinks and Windows directory junctions / redirecting
  reparse points are rejected wherever a directory object is encountered;
- managed leaves must be regular non-symlink, non-junction files; unrelated user
  files under ``State/`` are preserved and never swept;
- each artifact is written with the shared atomic text primitive and the
  manifest is written **last** as the generation commit marker.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai.
``dnd_assistant.domain`` is imported only for the trusted artifact-kind enum.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.paths import _resolve_vault_root

# ── Canonical physical layout ─────────────────────────────────────────────

_STATE_DIR: Final[str] = "State"
MANIFEST_FILENAME: Final[str] = ".campaign-state-manifest.json"
"""Fixed physical manifest filename inside ``State/`` (never manifest-supplied)."""

ARTIFACT_FILENAMES: Final[dict[CampaignStateArtifact, str]] = {
    CampaignStateArtifact.WORLD_STATE: "World State.md",
    CampaignStateArtifact.RECENTLY_TOUCHED: "Recently Touched.md",
}
"""Trusted fixed physical filename for every managed artifact slot."""

_ARTIFACT_ORDER: Final[tuple[CampaignStateArtifact, ...]] = (
    CampaignStateArtifact.WORLD_STATE,
    CampaignStateArtifact.RECENTLY_TOUCHED,
)


def artifact_filename(artifact: CampaignStateArtifact) -> str:
    """Return the trusted physical filename for an artifact slot."""
    filename = ARTIFACT_FILENAMES.get(artifact)
    if filename is None:
        raise StorageError(f"Unsupported artifact kind: {artifact!r}")
    return filename


# ── Protocol ──────────────────────────────────────────────────────────────


@runtime_checkable
class DerivedStateStore(Protocol):
    """Trusted persistence boundary for the derived Campaign State generation.

    The store deals only in opaque UTF-8 text payloads and the typed artifact
    allowlist.  Manifest content, artifact semantics, source identity and
    verification policy are application concerns.
    """

    def read_manifest_text(self) -> str | None:
        """Read the exact manifest text, or ``None`` when it does not exist.

        Raises:
            StorageError: The State topology or a managed leaf is unsafe
                (symlink, non-regular file, escape), or a read failed.
        """
        ...

    def read_artifact_bytes(self, artifact: CampaignStateArtifact) -> bytes | None:
        """Read exact artifact bytes, or ``None`` when it does not exist.

        Raises:
            StorageError: The artifact kind/path is unsafe or a read failed.
        """
        ...

    def publish(
        self,
        artifacts: Mapping[CampaignStateArtifact, str],
        manifest_text: str,
    ) -> None:
        """Atomically replace all managed artifacts, then the manifest last.

        ``artifacts`` must cover the exact trusted artifact set.

        Raises:
            StorageError: The payload set is incomplete/extra, the topology is
                unsafe, the payload contains CR characters, or a write failed.
        """
        ...


# ── ObsidianDerivedStateStore ─────────────────────────────────────────────


class ObsidianDerivedStateStore:
    """Filesystem-backed :class:`DerivedStateStore` under ``<vault>/State/``.

    Args:
        vault_root: The root directory of the Obsidian Vault.  It must exist
            and be a directory.

    Raises:
        StorageError: The Vault root is invalid.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self._vault_root = _resolve_vault_root(vault_root)

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def vault_root(self) -> Path:
        """The resolved Vault root path."""
        return self._vault_root

    @property
    def state_dir(self) -> Path:
        """The lexical ``<vault>/State`` path (not created)."""
        return self._vault_root / _STATE_DIR

    # ── Topology ──────────────────────────────────────────────────────────

    def _authorize_existing_state_dir(self, state: Path) -> Path:
        """Fully authorize an existing ``State/`` directory, or fail closed.

        The single authoritative topology check shared by the read and write
        paths.  An existing ``State/`` must be a real, non-redirecting directory
        whose resolved location is contained within the trusted resolved Vault
        root.  Symlinks, Windows directory junctions / redirecting reparse
        points, non-directories and out-of-Vault resolutions are all rejected.

        Raises:
            StorageError: Any topology requirement is violated.
        """
        # Redirect identity is checked before exists(): a dangling symlink or
        # junction may report exists() == False while still redirecting.
        if state.is_symlink():
            raise StorageError(f"State directory is a symlink, rejected for safety: {state}")
        if state.is_junction():
            raise StorageError(
                "State directory is a directory junction/reparse redirect, "
                f"rejected for safety: {state}"
            )
        if not state.exists():
            raise StorageError(f"State path does not exist: {state}")
        if not state.is_dir():
            raise StorageError(f"State path is not a directory: {state}")
        try:
            state.resolve(strict=False).relative_to(self._vault_root)
        except ValueError:
            raise StorageError(
                f"State directory resolves outside the Vault root: {state}"
            ) from None
        return state

    def _resolve_existing_state_dir(self) -> Path | None:
        """Return the fully authorized existing ``State/`` directory, or ``None``.

        Raises:
            StorageError: ``State`` exists but is unsafe (symlink, junction,
                non-directory, or resolves outside the Vault root).
        """
        state = self.state_dir
        # Redirect identity is checked before exists(): a dangling symlink or
        # junction may report exists() == False while still redirecting.
        if state.is_symlink() or state.is_junction():
            return self._authorize_existing_state_dir(state)
        if not state.exists():
            return None
        return self._authorize_existing_state_dir(state)

    def _ensure_state_dir(self) -> Path:
        """Return the fully authorized ``State/`` directory, creating it if absent.

        State-absent state machine::

            State absent
            -> ensure the candidate itself is not an existing redirecting object
            -> mkdir exact State/
            -> full existing-State authorization

        State exists
            -> full existing-State authorization

        Raises:
            StorageError: The Vault root vanished, the topology is unsafe, or
                creation failed.
        """
        if not self._vault_root.is_dir():
            raise StorageError(f"Vault root is no longer a directory: {self._vault_root}")

        state = self.state_dir

        # Existing redirecting object (symlink/junction, live or dangling) or an
        # existing normal path: run the full existing-State authorization.
        if state.is_symlink() or state.is_junction() or state.exists():
            return self._authorize_existing_state_dir(state)

        try:
            state.mkdir(exist_ok=False)
        except FileExistsError:
            # Lost a creation race: authorize whatever object now occupies the path.
            return self._authorize_existing_state_dir(state)
        except OSError as exc:
            raise StorageError(f"Failed to create State directory: {state}", cause=exc) from exc

        return self._authorize_existing_state_dir(state)

    def _safe_leaf(self, state: Path, filename: str) -> Path:
        """Return a validated managed leaf path (never a symlink/junction).

        Raises:
            StorageError: The leaf is a symlink (live or dangling) or a
                directory junction/reparse redirect.
        """
        leaf = state / filename
        if leaf.is_symlink():
            raise StorageError(f"Managed State leaf is a symlink, rejected: {leaf}")
        if leaf.is_junction():
            raise StorageError(f"Managed State leaf is a junction, rejected: {leaf}")
        return leaf

    # ── Read ──────────────────────────────────────────────────────────────

    def read_manifest_text(self) -> str | None:
        """Read the exact manifest text, or ``None`` when absent."""
        state = self._resolve_existing_state_dir()
        if state is None:
            return None
        leaf = self._safe_leaf(state, MANIFEST_FILENAME)
        if not leaf.exists():
            return None
        if not leaf.is_file():
            raise StorageError(f"Managed manifest is not a regular file: {leaf}")
        return _read_exact_text(leaf)

    def read_artifact_bytes(self, artifact: CampaignStateArtifact) -> bytes | None:
        """Read exact artifact bytes, or ``None`` when absent."""
        filename = artifact_filename(artifact)
        state = self._resolve_existing_state_dir()
        if state is None:
            return None
        leaf = self._safe_leaf(state, filename)
        if not leaf.exists():
            return None
        if not leaf.is_file():
            raise StorageError(f"Managed artifact is not a regular file: {leaf}")
        return _read_exact_bytes(leaf)

    # ── Publish ───────────────────────────────────────────────────────────

    def publish(
        self,
        artifacts: Mapping[CampaignStateArtifact, str],
        manifest_text: str,
    ) -> None:
        """Atomically replace managed artifacts, then the manifest last.

        The ``State/`` parent is reauthorized immediately before each managed
        replacement; a parent substituted between writes (e.g. by a symlink)
        fails closed before the next write.
        """
        if not isinstance(manifest_text, str):
            raise StorageError("Manifest content must be a string")

        expected = set(ARTIFACT_FILENAMES)
        if set(artifacts) != expected:
            missing = sorted(a.value for a in expected - set(artifacts))
            extra = sorted(str(a) for a in set(artifacts) - expected)
            raise StorageError(
                f"Managed artifact payload set mismatch (missing={missing}, extra={extra})"
            )

        # Validate the complete payload before touching the filesystem so an
        # invalid candidate cannot create a partial generation directory.
        _validate_text_content(manifest_text)
        for artifact in _ARTIFACT_ORDER:
            text = artifacts[artifact]
            if not isinstance(text, str):
                raise StorageError(f"Artifact content must be a string: {artifact.value!r}")
            _validate_text_content(text)

        # Mutation-time reauthorization discipline: the managed parent is
        # reauthorized immediately before *every* managed replacement, so a
        # ``State/`` substituted with a symlink between managed writes fails
        # closed before the next write and no later artifact/manifest is
        # written through the substituted parent.  This does not create a
        # filesystem transaction and does not eliminate every OS-level TOCTOU
        # race.
        for artifact in _ARTIFACT_ORDER:
            state = self._ensure_state_dir()
            leaf = self._safe_leaf(state, artifact_filename(artifact))
            atomic_write_text(
                target=leaf,
                content=artifacts[artifact],
                validator=_validate_text_content,
            )

        # The manifest is the generation commit marker and is written last,
        # with its own fresh parent reauthorization.
        state = self._ensure_state_dir()
        manifest_leaf = self._safe_leaf(state, MANIFEST_FILENAME)
        atomic_write_text(
            target=manifest_leaf,
            content=manifest_text,
            validator=_validate_text_content,
        )


# ── Exact I/O helpers ─────────────────────────────────────────────────────


def _validate_text_content(content: str) -> None:
    """Reject CR characters so persisted files stay LF-only.

    Raises:
        StorageError: The candidate content contains a carriage return.
    """
    if "\r" in content:
        raise StorageError("Derived-state content must use LF newlines only")


def _read_exact_text(path: Path) -> str:
    """Read exact UTF-8 text with newline preservation."""
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise StorageError(f"Derived-state file contains invalid UTF-8: {path}", cause=exc) from exc
    except OSError as exc:
        raise StorageError(f"Failed to read derived-state file: {path}", cause=exc) from exc


def _read_exact_bytes(path: Path) -> bytes:
    """Read exact bytes from a managed file."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StorageError(f"Failed to read derived-state file: {path}", cause=exc) from exc


__all__ = [
    "ARTIFACT_FILENAMES",
    "MANIFEST_FILENAME",
    "DerivedStateStore",
    "ObsidianDerivedStateStore",
    "artifact_filename",
]
