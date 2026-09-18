"""S13-01 deterministic Vault initialization storage primitives.

This module owns the trusted filesystem layout, path authorization and
create-once publication for initializing the D&D Session Assistant layer
inside a selected Obsidian Vault.

Scope
=====

``dnd init`` is **structural initialization only**.  It never scans,
reads, parses or imports campaign notes; the only campaign file it reads is
the canonical ``_system/campaign.yaml`` configuration envelope.

Layout
======

A minimal managed topology is created (existing compatible directories are
preserved, never deleted):

    Sessions/
    _system/
    _system/raw/
    _system/raw/sessions/
    _system/audit/
    Characters/
    Characters/NPCs/
    Locations/
    Quests/
    Items/
    _system/campaign.yaml

``_system/campaign.yaml`` is the single authoritative initialization commit
marker.  ``world_time.json`` and all derived artifacts (FTS index, Campaign
State, caches, post-session artifacts) are deliberately **not** created.

Path policy
===========

- a selected Vault root that is itself a symlink/junction is resolved once
  to its physical authoritative root;
- every managed descendant component is checked for live/dangling symlinks
  and Windows junction/reparse redirects before every create/publish;
- ``mkdir(parents=True)`` is never used across unverified managed
  descendants.

Audit
=====

The initializer owns the ``vault.initialize`` intent/committed audit
lifecycle.  The ``_system/`` and ``_system/audit/`` directories are the
narrow unavoidable pre-audit bootstrap edge: they must exist before any
durable intent can be written.  This is documented, not pretended away.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

import ruamel.yaml
from pydantic import TypeAdapter

from dnd_assistant.domain.types import CampaignId
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.atomic import exclusive_atomic_write_text
from dnd_assistant.storage.audit import AuditContext, AuditPhase, AuditRecord
from dnd_assistant.storage.paths import _resolve_vault_root
from dnd_assistant.storage.types import EntityDirectory

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditService

# ── Canonical layout constants ───────────────────────────────────────────────

CAMPAIGN_CONFIG_FILENAME: Final[str] = "campaign.yaml"
"""Fixed canonical campaign configuration filename inside ``_system/``."""

CAMPAIGN_CONFIG_RELATIVE: Final[Path] = Path("_system") / CAMPAIGN_CONFIG_FILENAME
"""Canonical Vault-relative path of the initialization commit marker."""

_SYSTEM_RELATIVE: Final[Path] = Path("_system")
_AUDIT_RELATIVE: Final[Path] = Path("_system") / "audit"
_AUDIT_LOG_RELATIVE: Final[Path] = Path("_system") / "audit" / "audit.jsonl"

_INITIALIZE_OPERATION: Final[str] = "vault.initialize"
_INITIALIZE_SCHEMA_VERSION: Final[int] = 1


def _build_managed_directories() -> tuple[Path, ...]:
    """Return the ordered (parent-first) managed directory topology.

    Entity directories are derived from :class:`EntityDirectory` so the
    canonical entity mapping has a single owner.  Fixed runtime roots come
    first, then entity directories with their intermediate parents.
    """
    fixed: list[Path] = [
        Path("Sessions"),
        _SYSTEM_RELATIVE,
        Path("_system") / "raw",
        Path("_system") / "raw" / "sessions",
        _AUDIT_RELATIVE,
    ]
    entity: list[Path] = []
    for entity_directory in EntityDirectory:
        relative = Path(entity_directory.value)
        for parent in reversed(relative.parents):
            if parent == Path("."):
                continue
            if parent not in fixed and parent not in entity:
                entity.append(parent)
        if relative not in entity:
            entity.append(relative)
    return tuple(fixed) + tuple(entity)


MANAGED_DIRECTORIES: Final[tuple[Path, ...]] = _build_managed_directories()
"""Canonical, ordered managed directory topology (Vault-relative paths)."""


# ── YAML codec ───────────────────────────────────────────────────────────────


def _make_yaml() -> ruamel.yaml.YAML:
    """Create a fresh safe YAML instance (deterministic block output)."""
    yaml = ruamel.yaml.YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.indent(mapping=2, sequence=2, offset=0)
    return yaml


@dataclass(frozen=True, slots=True)
class CampaignConfigEnvelope:
    """The validated S13-01 core of ``_system/campaign.yaml``.

    Only ``schema_version`` and ``campaign_id`` are part of the S13-01
    contract.  Any additional keys are opaque, forward-compatible storage
    data: they are accepted and preserved but never claimed as semantically
    validated, and a valid existing config is never rewritten.
    """

    campaign_id: str


_CAMPAIGN_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(CampaignId)


def parse_campaign_config(text: str) -> CampaignConfigEnvelope:
    """Validate the S13-01 core of a ``campaign.yaml`` document.

    Raises:
        StorageError: The text is not a YAML mapping, ``schema_version`` is
            missing or not exactly integer ``1``, or ``campaign_id`` is
            missing/invalid.
    """
    try:
        raw: object = _make_yaml().load(text)
    except Exception as exc:
        raise StorageError("campaign.yaml is not valid YAML", cause=exc) from exc

    if not isinstance(raw, dict):
        raise StorageError(f"campaign.yaml root must be a mapping, got {type(raw).__name__}")

    for key in raw:
        if not isinstance(key, str):
            raise StorageError(f"campaign.yaml keys must be strings, got {type(key).__name__}")

    if "schema_version" not in raw:
        raise StorageError("campaign.yaml is missing 'schema_version'")
    schema_version = raw["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise StorageError("campaign.yaml 'schema_version' must be an integer")
    if schema_version != _INITIALIZE_SCHEMA_VERSION:
        raise StorageError(
            f"Unsupported campaign.yaml schema_version: {schema_version} "
            f"(expected {_INITIALIZE_SCHEMA_VERSION})"
        )

    if "campaign_id" not in raw:
        raise StorageError("campaign.yaml is missing 'campaign_id'")
    try:
        campaign_id = _CAMPAIGN_ID_ADAPTER.validate_python(raw["campaign_id"])
    except Exception as exc:
        raise StorageError("campaign.yaml 'campaign_id' is invalid", cause=exc) from exc

    return CampaignConfigEnvelope(campaign_id=campaign_id)


def serialize_new_campaign_config(campaign_id: str) -> str:
    """Serialize the minimum S13-01 config for a newly initialized Vault.

    Only ``schema_version`` and ``campaign_id`` are written; no campaign
    name, calendar, perspective or feature flag is inferred.
    """
    try:
        validated = _CAMPAIGN_ID_ADAPTER.validate_python(campaign_id)
    except Exception as exc:
        raise StorageError("campaign_id is invalid", cause=exc) from exc

    data: dict[str, object] = {
        "schema_version": _INITIALIZE_SCHEMA_VERSION,
        "campaign_id": validated,
    }
    buffer = io.StringIO()
    try:
        _make_yaml().dump(data, buffer)
    except Exception as exc:
        raise StorageError("Failed to serialize campaign.yaml", cause=exc) from exc
    return buffer.getvalue()


# ── Read-only report / mutating outcome ──────────────────────────────────────


class CampaignConfigState(StrEnum):
    """State of the canonical initialization commit marker."""

    ABSENT = "absent"
    VALID = "valid"


@dataclass(frozen=True, slots=True)
class VaultLayoutReport:
    """Read-only classification of the managed Vault topology."""

    config_state: CampaignConfigState
    campaign_id: str | None
    missing_directories: tuple[Path, ...]
    """Managed directories that do not exist yet (Vault-relative, ordered)."""


@dataclass(frozen=True, slots=True)
class VaultInitializationOutcome:
    """Result of a mutating initialization or layout-repair call."""

    campaign_id: str
    created_directories: tuple[Path, ...]
    published_config: bool


# ── Protocol ─────────────────────────────────────────────────────────────────


@runtime_checkable
class VaultInitializer(Protocol):
    """Structural contract for the concrete Vault initializer.

    The application layer depends on this protocol only; it never depends on
    ``AuditService`` or the concrete initializer.
    """

    def inspect(self) -> VaultLayoutReport: ...

    def commit_initialization(
        self,
        campaign_id: str,
        *,
        audit: AuditContext,
    ) -> VaultInitializationOutcome: ...

    def repair_layout(
        self,
        *,
        audit: AuditContext,
    ) -> VaultInitializationOutcome: ...


# ── Concrete initializer ─────────────────────────────────────────────────────


class ObsidianVaultInitializer:
    """Trusted filesystem initializer for a selected Obsidian Vault.

    Args:
        vault_root: The selected Vault root.  It must exist and be a
            directory.  A symlink/junction root is resolved once to its
            physical authoritative root.
        audit_service_factory: A zero-argument factory returning a ready
            ``AuditService``.  It is invoked only after the canonical
            ``_system/audit/`` directory exists, because ``AuditService``
            requires its parent directory to be present.

    Raises:
        StorageError: The Vault root is missing, not a directory, or cannot
            be resolved.
    """

    def __init__(
        self,
        vault_root: str | Path,
        audit_service_factory: Callable[[], AuditService],
    ) -> None:
        self._root = _resolve_vault_root(vault_root)
        self._audit_service_factory = audit_service_factory

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def vault_root(self) -> Path:
        """The resolved physical Vault root path."""
        return self._root

    @property
    def config_path(self) -> Path:
        """The canonical absolute ``_system/campaign.yaml`` path."""
        return self._root / CAMPAIGN_CONFIG_RELATIVE

    # ── Path authorization ────────────────────────────────────────────────

    def _authorize_relative(self, relative: Path) -> Path:
        """Authorize one Vault-relative managed path against redirects.

        Every existing component beneath the resolved root must not be a
        live/dangling symlink or a Windows junction/reparse redirect, and the
        resolved path must remain contained within the resolved root.

        Missing components are acceptable — the check only applies to
        components that already exist.

        Raises:
            StorageError: A component is a symlink/junction, or the resolved
                path escapes the Vault root.
        """
        accumulated = self._root
        for part in relative.parts:
            accumulated = accumulated / part
            if accumulated.is_symlink():
                raise StorageError(
                    f"Managed Vault path component is a symlink, rejected for safety: {accumulated}"
                )
            if accumulated.is_junction():
                raise StorageError(
                    f"Managed Vault path component is a junction/reparse "
                    f"redirect, rejected for safety: {accumulated}"
                )

        resolved = accumulated.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise StorageError(
                f"Managed Vault path resolves outside the Vault root: {resolved}"
            ) from None
        return accumulated

    def _ensure_directory(self, relative: Path) -> bool:
        """Ensure a managed directory exists, returning ``True`` if created.

        The path is reauthorized immediately before any mutation.  An
        existing path must be a real, non-redirecting directory.

        Raises:
            StorageError: The path is a symlink/junction, is not a directory,
                or could not be created.
        """
        path = self._authorize_relative(relative)

        if path.is_symlink() or path.is_junction():
            raise StorageError(
                f"Managed directory is a redirecting object, rejected for safety: {path}"
            )
        if path.exists():
            if not path.is_dir():
                raise StorageError(f"Managed directory path is not a directory: {path}")
            return False

        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            # Lost a creation race: authorize whatever now occupies the path.
            if path.is_symlink() or path.is_junction() or not path.is_dir():
                raise StorageError(
                    f"Managed directory appeared as an unsafe path: {path}"
                ) from None
            return False
        except OSError as exc:
            raise StorageError(f"Failed to create managed directory: {path}", cause=exc) from exc

        return True

    # ── Config read ───────────────────────────────────────────────────────

    def _read_exact_text(self, path: Path) -> str:
        """Read exact UTF-8 text with newline preservation."""
        try:
            with open(path, encoding="utf-8", newline="") as handle:
                return handle.read()
        except UnicodeDecodeError as exc:
            raise StorageError(f"campaign.yaml is not valid UTF-8: {path}", cause=exc) from exc
        except OSError as exc:
            raise StorageError(f"Failed to read campaign.yaml: {path}", cause=exc) from exc

    def _read_campaign_id(self) -> str:
        """Read and validate the existing canonical config.

        Raises:
            StorageError: The config is absent (caller error), is a redirect,
                is not a regular file, or its core is invalid.
        """
        path = self._authorize_relative(CAMPAIGN_CONFIG_RELATIVE)
        if path.is_symlink() or path.is_junction():
            raise StorageError(
                f"campaign.yaml is a redirecting object, rejected for safety: {path}"
            )
        if not path.exists():
            raise StorageError(f"campaign.yaml does not exist: {path}")
        if not path.is_file():
            raise StorageError(f"campaign.yaml is not a regular file: {path}")
        return parse_campaign_config(self._read_exact_text(path)).campaign_id

    # ── Inspect (read-only) ───────────────────────────────────────────────

    def inspect(self) -> VaultLayoutReport:
        """Classify the managed topology without mutating anything.

        Raises:
            StorageError: A managed path is a redirect, a file where a
                directory is expected, or escapes the Vault root; or an
                existing config is invalid.
        """
        if not self._root.is_dir():
            raise StorageError(f"Vault root is no longer a directory: {self._root}")

        missing: list[Path] = []
        for relative in MANAGED_DIRECTORIES:
            path = self._authorize_relative(relative)
            if path.is_symlink() or path.is_junction():
                raise StorageError(
                    f"Managed directory is a redirecting object, rejected for safety: {path}"
                )
            if path.exists():
                if not path.is_dir():
                    raise StorageError(
                        f"Managed directory path exists but is not a directory: {path}"
                    )
            else:
                missing.append(relative)

        config_path = self._authorize_relative(CAMPAIGN_CONFIG_RELATIVE)
        if config_path.is_symlink() or config_path.is_junction():
            raise StorageError(
                f"campaign.yaml is a redirecting object, rejected for safety: {config_path}"
            )
        if config_path.exists():
            if not config_path.is_file():
                raise StorageError(f"campaign.yaml is not a regular file: {config_path}")
            campaign_id = parse_campaign_config(self._read_exact_text(config_path)).campaign_id
            state = CampaignConfigState.VALID
        else:
            campaign_id = None
            state = CampaignConfigState.ABSENT

        return VaultLayoutReport(
            config_state=state,
            campaign_id=campaign_id,
            missing_directories=tuple(missing),
        )

    # ── Audit records ─────────────────────────────────────────────────────

    def _build_audit_record(
        self,
        audit: AuditContext,
        *,
        phase: AuditPhase,
    ) -> AuditRecord:
        return AuditRecord(
            operation_id=audit.operation_id,
            real_time=audit.real_time,
            session=None,
            operation=_INITIALIZE_OPERATION,
            entity_id=None,
            before_hash=None,
            after_hash=None,
            source=audit.source,
            phase=phase,
            model_profile=audit.model_profile,
            prompt_version=audit.prompt_version,
        )

    # ── Mutating operations ───────────────────────────────────────────────

    def commit_initialization(
        self,
        campaign_id: str,
        *,
        audit: AuditContext,
    ) -> VaultInitializationOutcome:
        """Initialize an uninitialized Vault and publish the config marker.

        Sequence:

        1. read-only preflight;
        2. bootstrap ``_system/`` and ``_system/audit/`` (narrow pre-audit
           edge) so audit is possible;
        3. durable ``vault.initialize`` intent;
        4. create remaining missing managed directories;
        5. atomically/exclusively publish ``campaign.yaml`` when absent;
        6. re-read/validate the committed config;
        7. committed audit record.

        A concurrent loser adopts the winner's configuration.  Audit hashes
        are deliberately omitted: a concurrent loser legitimately adopts the
        winner's identity, so a candidate-specific hash would be false.

        Raises:
            StorageError: Topology is unsafe, publication failed, or the
                committed marker could not be validated.
            ConflictError: The exclusive publication raced and the existing
                config is invalid.
        """
        self.inspect_or_bootstrap_preflight()

        created: list[Path] = []
        if self._ensure_directory(_SYSTEM_RELATIVE):
            created.append(_SYSTEM_RELATIVE)
        if self._ensure_directory(_AUDIT_RELATIVE):
            created.append(_AUDIT_RELATIVE)

        audit_service = self._audit_service_factory()
        audit_service.append(self._build_audit_record(audit, phase="intent"))

        for relative in MANAGED_DIRECTORIES:
            if relative in (_SYSTEM_RELATIVE, _AUDIT_RELATIVE):
                continue
            if relative in created:
                continue
            if self._ensure_directory(relative):
                created.append(relative)

        published = False
        self._authorize_relative(CAMPAIGN_CONFIG_RELATIVE)
        config_path = self.config_path
        if config_path.exists() or config_path.is_symlink() or config_path.is_junction():
            # Lost a race before publication: adopt the existing marker.
            self._read_campaign_id()
        else:
            content = serialize_new_campaign_config(campaign_id)
            try:
                exclusive_atomic_write_text(
                    target=config_path,
                    content=content,
                    validator=lambda candidate: parse_campaign_config(candidate),
                )
                published = True
            except ConflictError:
                # Another initializer published first; adopt its config.
                self._read_campaign_id()

        committed_id = self._read_campaign_id()

        try:
            audit_service.append(self._build_audit_record(audit, phase="committed"))
        except StorageError as exc:
            raise StorageError(
                "Vault initialization may already be committed, but the final "
                "audit record could not be written.  The canonical "
                "configuration marker is present; re-running `dnd init` will "
                "not overwrite it.",
                cause=exc,
            ) from exc

        return VaultInitializationOutcome(
            campaign_id=committed_id,
            created_directories=tuple(created),
            published_config=published,
        )

    def repair_layout(
        self,
        *,
        audit: AuditContext,
    ) -> VaultInitializationOutcome:
        """Complete a valid-but-partial initialized Vault.

        The existing config marker is authoritative and is never rewritten.
        Missing managed directories are created, audited as one logical
        initialization operation.

        Raises:
            StorageError: The config is invalid, topology is unsafe, or a
                mutation failed.
        """
        campaign_id = self._read_campaign_id()

        created: list[Path] = []
        if self._ensure_directory(_SYSTEM_RELATIVE):
            created.append(_SYSTEM_RELATIVE)
        if self._ensure_directory(_AUDIT_RELATIVE):
            created.append(_AUDIT_RELATIVE)

        audit_service = self._audit_service_factory()
        audit_service.append(self._build_audit_record(audit, phase="intent"))

        for relative in MANAGED_DIRECTORIES:
            if relative in (_SYSTEM_RELATIVE, _AUDIT_RELATIVE):
                continue
            if self._ensure_directory(relative):
                created.append(relative)

        # Re-read and validate: the marker must still be present and valid.
        committed_id = self._read_campaign_id()
        if committed_id != campaign_id:
            raise StorageError("campaign.yaml changed during layout repair")

        try:
            audit_service.append(self._build_audit_record(audit, phase="committed"))
        except StorageError as exc:
            raise StorageError(
                "Vault layout repair may already be committed, but the final "
                "audit record could not be written.  Re-running `dnd init` is "
                "safe.",
                cause=exc,
            ) from exc

        return VaultInitializationOutcome(
            campaign_id=committed_id,
            created_directories=tuple(created),
            published_config=False,
        )

    def inspect_or_bootstrap_preflight(self) -> None:
        """Read-only preflight for the initialization path.

        Validates the complete intended managed topology and the config
        state before any mutation.  Kept separate for clarity and to allow
        callers/tests to invoke preflight without mutation.
        """
        self.inspect()


__all__ = [
    "CAMPAIGN_CONFIG_FILENAME",
    "CAMPAIGN_CONFIG_RELATIVE",
    "MANAGED_DIRECTORIES",
    "CampaignConfigEnvelope",
    "CampaignConfigState",
    "ObsidianVaultInitializer",
    "VaultInitializationOutcome",
    "VaultInitializer",
    "VaultLayoutReport",
    "parse_campaign_config",
    "serialize_new_campaign_config",
]
