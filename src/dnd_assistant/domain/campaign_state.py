"""CampaignState v2 domain schema — Stage-12 derived-projection contract.

Defines the typed, deterministic **derived** Campaign State contract and its
supporting value/identity/manifest DTOs.  Campaign State is a materialized,
discardable projection of canonical campaign evidence; it is **not** a
canonical aggregate and never a canonical mutation input.

This module is pure schema/value data.  Canonical serialization and SHA-256
fingerprint computation are application concerns
(``dnd_assistant.application.campaign_state_identity``); persistence, source
collection and rendering belong to S12-02/S12-03.

Honest semantics: session ``touched_entities`` means only that an entity was
touched/referenced during a session.  It is projected as **recently touched**
and never interpreted as current location, active quest, important NPC, goal,
thread or deadline.  Fields without canonical evidence are omitted entirely.

This module belongs to the domain layer and must not import from:
    storage, models, retrieval, tools, application, cli, ollama,
    pydantic_ai, pathlib, os, hashlib
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    field_validator,
    model_validator,
)

from dnd_assistant.domain.calendar import GameDate, WorldTick
from dnd_assistant.domain.entity import NameStr
from dnd_assistant.domain.session import SessionId
from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    RelativeArtifactPath,
    Revision,
    Sha256Fingerprint,
    Visibility,
)

# ── Field-level validators ────────────────────────────────────────────────


def _validate_printable_nonempty(value: str) -> str:
    """Validate a non-empty printable string.

    Requirements: strict string, non-empty, no surrounding whitespace and
    printable Unicode.
    """
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    if not value:
        raise ValueError("value must not be empty")
    if value.strip() != value:
        raise ValueError("value must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("value must not contain non-printable characters")
    return value


PrintableNonEmptyStr = Annotated[
    str,
    BeforeValidator(_validate_printable_nonempty),
    Field(description="Non-empty printable string"),
]


# ── Canonical ordering helpers ────────────────────────────────────────────


def _key_of(item: object, key: str) -> object:
    """Extract a sort/duplicate key from a mapping or model instance."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _materialize(values: object) -> list[Any] | None:
    """Materialize any non-string iterable to a list, else ``None``.

    Non-sequence inputs (e.g. ``set``) must be normalized too, otherwise the
    canonicalization and mandatory-count guards could be bypassed.
    """
    if values is None or isinstance(values, (str, bytes)):
        return None
    if not isinstance(values, Iterable):
        return None
    return list(cast("Iterable[Any]", values))


def _canonicalize_records(values: object, key: str, label: str) -> object:
    """Return an id-keyed tuple sorted ascending with duplicates rejected.

    Ordering of these set-like records is semantically irrelevant, so the
    caller's ordering must not become part of projection identity.  Invalid
    item shapes are returned as a materialized list so normal field validation
    can report the error.
    """
    items = _materialize(values)
    if items is None:
        return values
    keys: list[str] = []
    for item in items:
        extracted = _key_of(item, key)
        if not isinstance(extracted, str):
            return items
        keys.append(extracted)
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label} must not contain duplicate {key!r} values")
    return tuple(sorted(items, key=lambda item: cast("str", _key_of(item, key))))


def _canonicalize_ids(values: object, label: str) -> object:
    """Return a sorted, duplicate-free tuple of raw id strings.

    Invalid item shapes are returned as a materialized list so normal field
    validation can report the error.
    """
    items = _materialize(values)
    if items is None:
        return values
    if not all(isinstance(item, str) for item in items):
        return items
    if len(set(items)) != len(items):
        raise ValueError(f"{label} must not contain duplicates")
    return tuple(sorted(items))


# ── Recently-touched entity reference ─────────────────────────────────────


class CampaignEntityReference(BaseModel):
    """A canonical entity referenced as recently touched during a session.

    Carries only the fields required for future materialization (name/type),
    deterministic visibility filtering (visibility), staleness/provenance
    (revision) and evidence provenance (source session ids).  It never copies
    a full ``Entity`` object.

    ``source_session_ids`` is evidence provenance and therefore mandatory:
    at least one session id, duplicate-free and in deterministic canonical
    (ascending) order.
    """

    entity_id: EntityId
    entity_type: EntityType
    name: NameStr
    visibility: Visibility
    revision: Revision
    source_session_ids: tuple[SessionId, ...]

    @field_validator("source_session_ids", mode="before")
    @classmethod
    def _canonicalize_source_sessions(cls, value: object) -> object:
        normalized = _canonicalize_ids(value, "source_session_ids")
        if isinstance(normalized, tuple) and not normalized:
            raise ValueError("source_session_ids must contain at least one session id")
        return normalized

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── Derived Campaign State ────────────────────────────────────────────────


class CampaignState(BaseModel):
    """Trusted internal derived Campaign State projection (schema v2).

    This is the in-memory materialized-projection contract.  It contains the
    projection identity (``input_fingerprint``), the canonical current world
    tick, an optional derived ``GameDate`` (present only when a
    ``CalendarDefinition`` was supplied; never fabricated) and the
    ``recently_touched`` reference projection.

    Legacy Stage-2 semantic fields (``current_location``, ``active_quests``,
    ``important_npcs``, ``party_goals``, ``unresolved_threads``,
    ``upcoming_deadlines``) and ``revision`` are deliberately absent: current
    canonical evidence does not establish those semantics, and a derived
    projection has no optimistic-concurrency writer.  ``extra="forbid"``
    rejects any v1 payload.
    """

    schema_version: Literal[2] = 2
    """Schema version for migration detection.  Stage-12 v2."""

    type: Literal["campaign_state"] = "campaign_state"
    """Fixed type discriminator."""

    input_fingerprint: Sha256Fingerprint
    """Source-snapshot identity of the exact canonical inputs."""

    current_world_tick: WorldTick
    """Canonical current world tick (required; world time is canonical)."""

    current_game_date: GameDate | None = None
    """Derived game date, present only when a calendar definition was supplied."""

    recently_touched: tuple[CampaignEntityReference, ...] = ()
    """Recent canonical entity references, honestly labeled as recently touched."""

    @field_validator("recently_touched", mode="before")
    @classmethod
    def _canonicalize_recently_touched(cls, value: object) -> object:
        return _canonicalize_records(value, "entity_id", "recently_touched")

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── Fingerprint input identity ────────────────────────────────────────────


class CampaignWorldTimeSource(BaseModel):
    """Canonical current-world-time source binding."""

    current_world_tick: WorldTick
    revision: Revision

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class CampaignSessionSource(BaseModel):
    """Canonical session source binding (completed session metadata)."""

    session_id: SessionId
    revision: Revision

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class CampaignStateInputIdentity(BaseModel):
    """Exact canonical input set bound by the Campaign State fingerprint.

    Represents a **source snapshot**: entity/session/world-time revisions are
    intentional identity inputs, so any source change (including a revision
    bump) changes the fingerprint.  Source-session bindings are the only
    acceptable session identity; raw session events are deliberately excluded
    because session metadata revision does not bind the event stream.

    Collection ordering is normalized (ascending, duplicate-free) so caller
    ordering never becomes part of identity.  The canonical serialization of
    this model is what the input fingerprint hashes.
    """

    schema_version: Literal[1] = 1
    derivation_version: PrintableNonEmptyStr
    world_time: CampaignWorldTimeSource
    sessions: tuple[CampaignSessionSource, ...] = ()
    entities: tuple[CampaignEntityReference, ...] = ()
    calendar_definition_fingerprint: Sha256Fingerprint | None = None
    """SHA-256 of the complete supplied ``CalendarDefinition`` (or None)."""

    @field_validator("sessions", mode="before")
    @classmethod
    def _canonicalize_sessions(cls, value: object) -> object:
        return _canonicalize_records(value, "session_id", "sessions")

    @field_validator("entities", mode="before")
    @classmethod
    def _canonicalize_entities(cls, value: object) -> object:
        return _canonicalize_records(value, "entity_id", "entities")

    @model_validator(mode="after")
    def _validate_session_provenance_subset(self) -> CampaignStateInputIdentity:
        session_ids = {source.session_id for source in self.sessions}
        for reference in self.entities:
            unknown = sorted(set(reference.source_session_ids) - session_ids)
            if unknown:
                raise ValueError(
                    "CampaignEntityReference.source_session_ids must be a subset of "
                    f"the identity sessions; unknown session ids: {unknown}"
                )
        return self

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── Derived-state manifest ────────────────────────────────────────────────


class DerivedStateArtifact(BaseModel):
    """One logical artifact in a materialized generation.

    ``relative_path`` is a logical inventory identifier (no filesystem
    authority); ``content_hash`` is the SHA-256 of the artifact's exact bytes.
    """

    relative_path: RelativeArtifactPath
    content_hash: Sha256Fingerprint

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class DerivedStateManifest(BaseModel):
    """Logical identity and artifact inventory of one materialized generation.

    The manifest binds the generation fingerprint and the rendered artifact
    inventory; it never contains filesystem paths, atomic-replace mechanics or
    physical write concerns (those belong to S12-03).  ``artifacts`` is
    set-like: ordering is canonicalized deterministically (ascending logical
    path, duplicate-free) and must contain at least one artifact so a stale or
    empty generation cannot masquerade as a real one.  This contract never adds
    the physical manifest file to ``artifacts``; manifest naming and location
    belong to S12-03.
    """

    schema_version: Literal[1] = 1
    state_schema_version: Literal[2] = 2
    input_fingerprint: Sha256Fingerprint
    artifacts: tuple[DerivedStateArtifact, ...]

    @field_validator("artifacts", mode="before")
    @classmethod
    def _canonicalize_artifacts(cls, value: object) -> object:
        normalized = _canonicalize_records(value, "relative_path", "artifacts")
        if isinstance(normalized, tuple) and not normalized:
            raise ValueError("artifacts must contain at least one artifact")
        return normalized

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


__all__ = [
    "CampaignEntityReference",
    "CampaignSessionSource",
    "CampaignState",
    "CampaignStateInputIdentity",
    "CampaignWorldTimeSource",
    "DerivedStateArtifact",
    "DerivedStateManifest",
    "PrintableNonEmptyStr",
]
