"""S12-03 Campaign State materialization, rebuild, inspection and read.

Orchestrates the accepted materialization contract over the trusted
``DerivedStateStore`` boundary:

```text
canonical sources
  -> S12-02 build
  -> deterministic render candidate
  -> fresh pre-publication re-derivation (same config)
  -> fingerprint comparison gate
  -> trusted store publication (manifest last)
```

Read-time verification is **re-render based**: manifest hashes alone are not a
trust anchor.  A generation is only ``CURRENT`` when a fresh source derivation
has a matching source fingerprint **and** the deterministically re-rendered
expected bytes equal every stored managed artifact.  This detects coordinated
manual edits where a user changes both the Markdown and the corresponding
manifest hash.

The materialization service contains no filesystem access: it never joins
paths, opens files or inspects symlinks.  All physical concerns belong to the
injected store.

This module belongs to the application layer and must not import from:
    storage (runtime), models, ollama, pydantic_ai, tools, cli, retrieval,
    pathlib, os, hashlib, json
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.campaign_state_render import (
    ARTIFACT_ORDER,
    CAMPAIGN_STATE_RENDER_VERSION,
    LOGICAL_ARTIFACT_PATHS,
    CampaignStateManifestError,
    CampaignStateManifestOutdatedError,
    artifact_bytes_hash,
    build_manifest,
    parse_manifest,
    render_campaign_state_artifacts,
    serialize_manifest,
)
from dnd_assistant.application.campaign_state_source import (
    CampaignStateSourceError,
    build_campaign_state,
)
from dnd_assistant.domain.calendar import CalendarDefinition
from dnd_assistant.domain.campaign_state import (
    CampaignState,
    CampaignStateArtifact,
    DerivedStateManifest,
)
from dnd_assistant.domain.types import Sha256Fingerprint
from dnd_assistant.errors import DndAssistantError, NotFoundError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.storage.derived_state import DerivedStateStore
    from dnd_assistant.storage.types import (
        SessionMetadataRepository,
        VaultRepository,
        WorldTimeRepository,
    )

# ── Status / results ──────────────────────────────────────────────────────


class CampaignStateStatus(StrEnum):
    """Read-time classification of a materialized Campaign State generation."""

    MISSING = "missing"
    """No manifest and no managed artifacts exist."""

    OUTDATED = "outdated"
    """A recognized generation with an unsupported schema/renderer version."""

    CORRUPT = "corrupt"
    """Malformed manifest, inventory mismatch, hash mismatch, symlink/missing
    managed file, or bytes that do not match the deterministic re-render."""

    UNVERIFIABLE = "unverifiable"
    """Canonical sources are temporarily unreadable/invalid; freshness cannot
    be established."""

    STALE = "stale"
    """Structurally valid generation whose source fingerprint differs from a
    fresh derivation (canonical projection inputs changed)."""

    CURRENT = "current"
    """Structurally valid generation whose fingerprint matches a fresh
    derivation and whose stored bytes equal the deterministic re-render."""


class CampaignStateRebuildStatus(StrEnum):
    """Outcome of a rebuild/materialization request."""

    PUBLISHED = "published"
    ALREADY_CURRENT = "already_current"


@dataclass(frozen=True, slots=True)
class CampaignStateInspection:
    """Result of a non-failing read-time inspection."""

    status: CampaignStateStatus
    manifest: DerivedStateManifest | None = None
    state: CampaignState | None = None
    input_fingerprint: Sha256Fingerprint | None = None
    detail: str | None = None
    cause: Exception | None = None


@dataclass(frozen=True, slots=True)
class CampaignStateReadResult:
    """A verified CURRENT generation with its typed, freshly derived state."""

    state: CampaignState
    manifest: DerivedStateManifest
    input_fingerprint: Sha256Fingerprint


@dataclass(frozen=True, slots=True)
class CampaignStateRebuildResult:
    """Outcome of a rebuild/materialization request."""

    status: CampaignStateRebuildStatus
    state: CampaignState
    input_fingerprint: Sha256Fingerprint
    manifest: DerivedStateManifest


# ── Errors ────────────────────────────────────────────────────────────────


class CampaignStateSourceChangedError(DndAssistantError):
    """Canonical sources changed between the initial and fresh pre-publication
    derivations.  Publication aborted; no managed file was written."""


class CampaignStateStaleError(DndAssistantError):
    """The materialized generation is stale relative to current sources."""


class CampaignStateReadError(StorageError):
    """Fail-closed read error carrying the non-CURRENT integrity status."""

    def __init__(
        self,
        status: CampaignStateStatus,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.status = status


# ── Stored-generation structural validation ───────────────────────────────


@dataclass(frozen=True, slots=True)
class _StoredGeneration:
    """Structurally valid stored generation with exact artifact bytes."""

    manifest: DerivedStateManifest
    artifacts: dict[CampaignStateArtifact, bytes]


def _read_and_validate_stored(
    store: DerivedStateStore,
) -> tuple[_StoredGeneration | None, CampaignStateStatus | None, str | None]:
    """Validate stored topology, manifest, inventory and exact hashes.

    Returns ``(generation, None, None)`` when the stored generation is
    structurally valid; otherwise ``(None, status, detail)``.

    Unsafe topology/symlink conditions are **not** normalized into an ordinary
    status: ``StorageError`` from the store propagates fail-closed.
    """
    manifest_text = store.read_manifest_text()
    if manifest_text is None:
        if any(store.read_artifact_bytes(artifact) is not None for artifact in ARTIFACT_ORDER):
            return None, CampaignStateStatus.CORRUPT, "artifacts present without a manifest"
        return None, CampaignStateStatus.MISSING, None

    try:
        manifest = parse_manifest(manifest_text)
    except CampaignStateManifestOutdatedError as exc:
        return None, CampaignStateStatus.OUTDATED, str(exc)
    except CampaignStateManifestError as exc:
        return None, CampaignStateStatus.CORRUPT, str(exc)

    if manifest.render_version != CAMPAIGN_STATE_RENDER_VERSION:
        return (
            None,
            CampaignStateStatus.OUTDATED,
            f"render_version {manifest.render_version!r} does not match "
            f"{CAMPAIGN_STATE_RENDER_VERSION!r}",
        )

    expected_paths = {LOGICAL_ARTIFACT_PATHS[artifact] for artifact in ARTIFACT_ORDER}
    manifest_paths = {artifact.relative_path for artifact in manifest.artifacts}
    if manifest_paths != expected_paths:
        return (
            None,
            CampaignStateStatus.CORRUPT,
            "manifest artifact inventory does not match the expected artifact set",
        )

    hash_by_path = {
        artifact.relative_path: artifact.content_hash for artifact in manifest.artifacts
    }
    stored: dict[CampaignStateArtifact, bytes] = {}
    for artifact in ARTIFACT_ORDER:
        logical = LOGICAL_ARTIFACT_PATHS[artifact]
        data = store.read_artifact_bytes(artifact)
        if data is None:
            return None, CampaignStateStatus.CORRUPT, f"missing managed artifact: {logical}"
        if artifact_bytes_hash(data) != hash_by_path[logical]:
            return None, CampaignStateStatus.CORRUPT, f"artifact hash mismatch: {logical}"
        stored[artifact] = data

    return _StoredGeneration(manifest=manifest, artifacts=stored), None, None


def _check_freshness(
    stored: _StoredGeneration,
    expected_state: CampaignState,
) -> tuple[CampaignStateStatus, str | None]:
    """Compare a structurally valid generation against a fresh derivation."""
    if stored.manifest.input_fingerprint != expected_state.input_fingerprint:
        return CampaignStateStatus.STALE, "source fingerprint differs from fresh derivation"

    expected_texts = render_campaign_state_artifacts(expected_state)
    for artifact in ARTIFACT_ORDER:
        if stored.artifacts[artifact] != expected_texts[artifact].encode("utf-8"):
            return (
                CampaignStateStatus.CORRUPT,
                f"artifact bytes differ from the deterministic render: {artifact.value}",
            )
    return CampaignStateStatus.CURRENT, None


def _verify_materialized(
    store: DerivedStateStore,
    expected_state: CampaignState,
) -> tuple[CampaignStateStatus, DerivedStateManifest | None, str | None]:
    """Full verification of the stored generation against a fresh witness."""
    stored, failure, detail = _read_and_validate_stored(store)
    if failure is not None:
        return failure, None, detail
    assert stored is not None
    status, freshness_detail = _check_freshness(stored, expected_state)
    return status, stored.manifest, freshness_detail


# ── Rebuild ───────────────────────────────────────────────────────────────


def rebuild_campaign_state(
    *,
    vault_repository: VaultRepository,
    session_repository: SessionMetadataRepository,
    world_time_repository: WorldTimeRepository,
    derived_state_store: DerivedStateStore,
    recent_session_limit: int,
    calendar_definition: CalendarDefinition | None = None,
) -> CampaignStateRebuildResult:
    """Materialize the Campaign State projection with a pre-publication gate.

    Sequence:

    1. initial S12-02 build;
    2. deterministic render of the candidate artifacts;
    3. fresh S12-02 build with exactly the same derivation configuration;
    4. fingerprint mismatch -> abort (``CampaignStateSourceChangedError``),
       zero managed-file mutation;
    5. fingerprint match -> the fresh build is the accepted source witness;
    6. inspect the existing generation against the witness; if fully current,
       return ``ALREADY_CURRENT`` without writing;
    7. otherwise publish the candidate artifacts and write the manifest last.

    No cross-repository atomic snapshot is claimed: canonical sources may still
    change during publication, so read-time freshness verification remains
    mandatory.

    Raises:
        CampaignStateSourceChangedError: The pre-publication fingerprint gate
            failed.
        CampaignStateSourceError: The initial/fresh derivation failed closed.
        StorageError: Repository corruption or an unsafe/failed store write.
    """
    initial = build_campaign_state(
        vault_repository=vault_repository,
        session_repository=session_repository,
        world_time_repository=world_time_repository,
        recent_session_limit=recent_session_limit,
        calendar_definition=calendar_definition,
    )
    candidate_texts = render_campaign_state_artifacts(initial.state)
    candidate_manifest = build_manifest(initial.state, candidate_texts)
    manifest_text = serialize_manifest(candidate_manifest)

    fresh = build_campaign_state(
        vault_repository=vault_repository,
        session_repository=session_repository,
        world_time_repository=world_time_repository,
        recent_session_limit=recent_session_limit,
        calendar_definition=calendar_definition,
    )
    if fresh.state.input_fingerprint != initial.state.input_fingerprint:
        raise CampaignStateSourceChangedError(
            "Canonical Campaign State sources changed between the initial build "
            "and the fresh pre-publication derivation; publication aborted"
        )

    witness_texts = render_campaign_state_artifacts(fresh.state)
    if witness_texts != candidate_texts:
        raise StorageError(
            "Non-deterministic Campaign State render: the source fingerprint matched "
            "but the rendered artifacts differed"
        )

    status, manifest, _detail = _verify_materialized(derived_state_store, fresh.state)
    if status is CampaignStateStatus.CURRENT and manifest is not None:
        return CampaignStateRebuildResult(
            status=CampaignStateRebuildStatus.ALREADY_CURRENT,
            state=fresh.state,
            input_fingerprint=fresh.state.input_fingerprint,
            manifest=manifest,
        )

    derived_state_store.publish(candidate_texts, manifest_text)
    return CampaignStateRebuildResult(
        status=CampaignStateRebuildStatus.PUBLISHED,
        state=initial.state,
        input_fingerprint=initial.state.input_fingerprint,
        manifest=candidate_manifest,
    )


# ── Inspect / read ────────────────────────────────────────────────────────


def inspect_campaign_state(
    *,
    vault_repository: VaultRepository,
    session_repository: SessionMetadataRepository,
    world_time_repository: WorldTimeRepository,
    derived_state_store: DerivedStateStore,
    recent_session_limit: int,
    calendar_definition: CalendarDefinition | None = None,
) -> CampaignStateInspection:
    """Inspect the materialized generation without raising for ordinary
    MISSING/STALE/CORRUPT/OUTDATED/UNVERIFIABLE outcomes.

    Verification order: safe topology, manifest/schema/render/inventory,
    exact stored hashes, fresh derivation, fingerprint comparison, then
    deterministic re-render byte comparison.

    Raises:
        StorageError: Unsafe topology or a failed store read (fail closed).
    """
    stored, failure, detail = _read_and_validate_stored(derived_state_store)
    if failure is not None:
        return CampaignStateInspection(status=failure, detail=detail)

    assert stored is not None
    manifest = stored.manifest

    try:
        build = build_campaign_state(
            vault_repository=vault_repository,
            session_repository=session_repository,
            world_time_repository=world_time_repository,
            recent_session_limit=recent_session_limit,
            calendar_definition=calendar_definition,
        )
    except (CampaignStateSourceError, StorageError) as exc:
        return CampaignStateInspection(
            status=CampaignStateStatus.UNVERIFIABLE,
            manifest=manifest,
            input_fingerprint=manifest.input_fingerprint,
            detail="Canonical sources could not be re-derived for verification",
            cause=exc,
        )

    status, freshness_detail = _check_freshness(stored, build.state)
    if status is CampaignStateStatus.STALE:
        return CampaignStateInspection(
            status=status,
            manifest=manifest,
            state=build.state,
            input_fingerprint=build.state.input_fingerprint,
            detail=freshness_detail,
        )
    if status is CampaignStateStatus.CORRUPT:
        return CampaignStateInspection(
            status=status,
            manifest=manifest,
            detail=freshness_detail,
        )
    return CampaignStateInspection(
        status=CampaignStateStatus.CURRENT,
        manifest=manifest,
        state=build.state,
        input_fingerprint=build.state.input_fingerprint,
    )


def read_current_campaign_state(
    *,
    vault_repository: VaultRepository,
    session_repository: SessionMetadataRepository,
    world_time_repository: WorldTimeRepository,
    derived_state_store: DerivedStateStore,
    recent_session_limit: int,
    calendar_definition: CalendarDefinition | None = None,
) -> CampaignStateReadResult:
    """Return the verified CURRENT Campaign State, or fail closed.

    Raises:
        NotFoundError: No managed generation exists (``MISSING``).
        CampaignStateStaleError: The generation is stale relative to sources.
        CampaignStateReadError: The generation is corrupt/outdated/unverifiable
            (a ``StorageError`` carrying the exact status).
    """
    inspection = inspect_campaign_state(
        vault_repository=vault_repository,
        session_repository=session_repository,
        world_time_repository=world_time_repository,
        derived_state_store=derived_state_store,
        recent_session_limit=recent_session_limit,
        calendar_definition=calendar_definition,
    )

    if inspection.status is CampaignStateStatus.CURRENT:
        assert inspection.state is not None and inspection.manifest is not None
        return CampaignStateReadResult(
            state=inspection.state,
            manifest=inspection.manifest,
            input_fingerprint=inspection.state.input_fingerprint,
        )

    if inspection.status is CampaignStateStatus.MISSING:
        raise NotFoundError("Campaign State has not been materialized")

    if inspection.status is CampaignStateStatus.STALE:
        raise CampaignStateStaleError(
            inspection.detail or "Campaign State is stale relative to current sources"
        )

    raise CampaignStateReadError(
        inspection.status,
        inspection.detail or f"Campaign State is not current: {inspection.status.value}",
        cause=inspection.cause,
    )


__all__ = [
    "CampaignStateInspection",
    "CampaignStateReadError",
    "CampaignStateReadResult",
    "CampaignStateRebuildResult",
    "CampaignStateRebuildStatus",
    "CampaignStateSourceChangedError",
    "CampaignStateStaleError",
    "CampaignStateStatus",
    "inspect_campaign_state",
    "read_current_campaign_state",
    "rebuild_campaign_state",
]
