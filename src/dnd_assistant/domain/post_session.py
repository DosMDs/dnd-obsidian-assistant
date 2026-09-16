"""Stage-11 post-session processing domain schemas.

Defines the immutable, strict typed contracts that establish the durable
post-session processing foundations required before any model execution:

- ``PostSessionAttemptId`` / ``LedgerEventId`` — opaque trusted identities;
- ``Sha256Fingerprint`` — self-describing content hash value;
- ``PreparedInputIdentity`` — the canonical full prepared-input projection
  whose serialization is fingerprinted (architecture correction C1);
- ``ProcessingLedgerEvent`` — the append-only processing-ledger event union
  (architecture correction C4).

These schemas are **proposal/evidence data only**.  Fingerprint calculation,
eligibility policy, ledger serialization and persistence are application /
storage concerns and deliberately do not appear here.  This module contains no
filesystem path, no model/provider-specific data and no persistence DTO.

This module belongs to the domain layer and must not import from:
    storage, application, models, tools, retrieval, cli, ollama,
    pathlib, os, hashlib
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, JsonValue
from pydantic.types import AwareDatetime

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Revision,
    Visibility,
)

# ── Field-level validators ────────────────────────────────────────────────

_ATTEMPT_ID_PATTERN = r"^att_[0-9a-f]{32}$"
_LEDGER_EVENT_ID_PATTERN = r"^le_[0-9a-f]{32}$"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"

_ATTEMPT_ID_RE = re.compile(_ATTEMPT_ID_PATTERN)
_LEDGER_EVENT_ID_RE = re.compile(_LEDGER_EVENT_ID_PATTERN)

_MAX_MESSAGE_LENGTH = 2000


def _validate_attempt_id(value: str) -> str:
    """Validate an opaque trusted processing-attempt identifier.

    Requirements: strict string, lowercase ``att_`` prefix followed by
    exactly 32 lowercase hex characters.  The value is deliberately opaque:
    no semantic information may be decoded from it, and it is safe as a
    single filesystem path component and inside a future ``changeset_id``.
    """
    if not isinstance(value, str):
        raise ValueError("PostSessionAttemptId must be a string")
    if not _ATTEMPT_ID_RE.match(value):
        raise ValueError("PostSessionAttemptId must match att_<32 lowercase hex characters>")
    return value


def _validate_ledger_event_id(value: str) -> str:
    """Validate an opaque append-only ledger event identifier."""
    if not isinstance(value, str):
        raise ValueError("LedgerEventId must be a string")
    if not _LEDGER_EVENT_ID_RE.match(value):
        raise ValueError("LedgerEventId must match le_<32 lowercase hex characters>")
    return value


def _validate_nonempty_printable(value: str) -> str:
    """Validate a strict non-empty printable string."""
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    if not value:
        raise ValueError("value must not be empty")
    if value.strip() != value:
        raise ValueError("value must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("value must not contain non-printable characters")
    return value


def _validate_optional_nonempty_printable(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_nonempty_printable(value)


def _validate_bounded_message(value: str) -> str:
    """Validate a bounded printable failure message.

    The message is canonical durable evidence: it must never contain a
    traceback or arbitrary multi-line secret material.  Non-printable
    characters (including newlines) are rejected and the length is bounded.
    """
    value = _validate_nonempty_printable(value)
    if len(value) > _MAX_MESSAGE_LENGTH:
        raise ValueError(f"message must be at most {_MAX_MESSAGE_LENGTH} characters")
    return value


def _validate_relative_path(value: str) -> str:
    """Validate a logical relative artifact path.

    This is a *logical* path segment used in durable provenance, not a
    filesystem path.  Absolute paths, backslashes and parent-directory
    traversal are rejected.  The value carries no filesystem authority.
    """
    value = _validate_nonempty_printable(value)
    if value.startswith("/"):
        raise ValueError("relative path must not be absolute")
    if "\\" in value:
        raise ValueError("relative path must use '/' separators only")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("relative path must not contain empty, '.', or '..' segments")
    return value


# ── Annotated value types ─────────────────────────────────────────────────


PostSessionAttemptId = Annotated[
    str,
    BeforeValidator(_validate_attempt_id),
    Field(description="Opaque trusted attempt identity (att_<32 hex>)"),
]

LedgerEventId = Annotated[
    str,
    BeforeValidator(_validate_ledger_event_id),
    Field(description="Opaque append-only ledger event identity (le_<32 hex>)"),
]

NonEmptyStr = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(description="Strict non-empty printable string"),
]

OptionalNonEmptyStr = Annotated[
    str | None,
    BeforeValidator(_validate_optional_nonempty_printable),
    Field(default=None, description="Optional non-empty printable string"),
]

BoundedMessageStr = Annotated[
    str,
    BeforeValidator(_validate_bounded_message),
    Field(description="Bounded printable failure message (no newlines/traceback)"),
]

RelativeArtifactPath = Annotated[
    str,
    BeforeValidator(_validate_relative_path),
    Field(description="Logical relative artifact path (no traversal/absolute)"),
]

# ── Fingerprint value type ────────────────────────────────────────────────


class Sha256Fingerprint(BaseModel):
    """Self-describing content hash of an exact canonical byte sequence.

    Used for the prepared-input fingerprint (C1) and for the ChangeSet
    proposal digest / artifact content hash recorded in ledger provenance.
    It contains no path and no provider data.
    """

    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=_DIGEST_PATTERN)

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


InputFingerprint = Sha256Fingerprint
"""Deterministic identity of the full prepared processing input (C1)."""

# ── Processing enums ──────────────────────────────────────────────────────


class ProcessingOutcome(StrEnum):
    """Terminal outcome of a successful processing attempt.

    The distinction concerns **campaign-change proposal production**, not
    whether Summary/Recap/workflow artifacts exist (they exist for both).
    """

    PRODUCED = "produced"
    """Processing produced and persisted a Stage-10 campaign-change proposal."""

    NO_CHANGES = "no_changes"
    """Processing completed without any valid campaign change operations."""


class ProcessingPhase(StrEnum):
    """Bounded orchestration phase recorded on a failure."""

    ELIGIBILITY = "eligibility"
    INPUT_ASSEMBLY = "input_assembly"
    EXTRACTION = "extraction"
    VALIDATION = "validation"
    RENDERING = "rendering"
    PERSISTENCE = "persistence"


class FailureCategory(StrEnum):
    """Coarse, stable failure classification for durable evidence."""

    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    INVALID_OUTPUT = "invalid_output"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    STORAGE_ERROR = "storage_error"
    ARTIFACT_CONFLICT = "artifact_conflict"
    PROPOSAL_CONFLICT = "proposal_conflict"
    INTERNAL_ERROR = "internal_error"


class ArtifactKind(StrEnum):
    """Render-facing artifact kinds (S11-04 Summary/Recap rendering).

    Deliberately limited to the two model-rendered artifacts.  It is the type
    of :class:`dnd_assistant.application.post_session_rendering.RenderingProvenance.artifact_kind`
    and of the S11-04 render APIs, so a workflow-evidence artifact can never be
    mistaken for a render output.
    """

    SUMMARY = "summary"
    RECAP = "recap"


class PersistedArtifactKind(StrEnum):
    """Durable per-attempt artifact slots recorded in the processing ledger.

    A superset of :class:`ArtifactKind` that additionally covers the
    machine-readable workflow-evidence artifact.  The JSON values of the
    overlapping members are byte-identical to :class:`ArtifactKind`
    (``"summary"`` / ``"recap"``), so previously persisted S11-01 ledger lines
    parse without migration and re-serialize unchanged.
    """

    SUMMARY = "summary"
    RECAP = "recap"
    WORKFLOW = "workflow"


# ── Prepared-input projections ────────────────────────────────────────────


class PreparedSessionProjection(BaseModel):
    """Deterministic projection of the completed session record.

    Contains only durable, canonical session facts.  It carries no
    filesystem path and no legacy processing field.
    """

    id: str
    status: NonEmptyStr
    real_started_at: AwareDatetime
    real_finished_at: AwareDatetime
    world_tick_start: WorldTick
    world_tick_end: WorldTick
    revision: Revision
    touched_entities: tuple[EntityId, ...] = ()

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class PreparedRawEvent(BaseModel):
    """Deterministic projection of one ordered raw session event."""

    event_id: NonEmptyStr
    real_time: AwareDatetime
    world_tick: WorldTick
    type: NonEmptyStr
    extra_fields: dict[str, JsonValue] = Field(default_factory=dict)

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class PreparedEntityProjection(BaseModel):
    """Deterministic projection of one referenced entity snapshot.

    ``body_projection`` is the complete canonical body supplied by the
    assembler; the assembler fails closed rather than truncating a body, so
    no lossy marker is produced here.  No filesystem path is present.
    """

    id: EntityId
    type: EntityType
    revision: Revision
    name: NonEmptyStr
    status: NonEmptyStr
    visibility: Visibility
    knowledge_status: KnowledgeStatus
    tags: tuple[NonEmptyStr, ...] = ()
    body_projection: str = ""

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class PreparedContextProjection(BaseModel):
    """The exact deterministic prepared-input document.

    Represented as the canonical deterministic text assembled by S11-02.
    It is intentionally a plain string so no speculative structure is
    committed ahead of context assembly.
    """

    text: str = ""

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class PreparedCalendarProjection(BaseModel):
    """Deterministic calendar projection.

    No canonical ``CalendarDefinition`` source exists yet, so only the raw
    world-tick span is projected.  No game date is fabricated.
    """

    world_tick_start: WorldTick
    world_tick_end: WorldTick

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class PreparedInputIdentity(BaseModel):
    """Canonical full prepared processing input (C1).

    The serialized form of this model is exactly what ``input_fingerprint``
    binds.  Ordering is explicit (tuples), absent values serialize
    deterministically, and no attempt identity, wall-clock attempt time,
    model output, model profile or framework state is present.
    """

    schema_version: Literal[2] = 2
    processor_version: NonEmptyStr
    prompt_version: NonEmptyStr
    session: PreparedSessionProjection
    raw_events: tuple[PreparedRawEvent, ...] = ()
    entities: tuple[PreparedEntityProjection, ...] = ()
    context: PreparedContextProjection = Field(default_factory=PreparedContextProjection)
    calendar: PreparedCalendarProjection

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── Processing ledger events (C4) ─────────────────────────────────────────


class _LedgerEventBase(BaseModel):
    """Common immutable fields for every processing-ledger event."""

    schema_version: Literal[1] = 1
    event_id: LedgerEventId
    attempt_id: PostSessionAttemptId
    session_ref: NonEmptyStr
    real_time: AwareDatetime

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class AttemptStarted(_LedgerEventBase):
    """A durable execution attempt began."""

    event_kind: Literal["attempt_started"] = "attempt_started"
    input_fingerprint: InputFingerprint
    processor_version: NonEmptyStr
    prompt_version: NonEmptyStr
    model_profile: OptionalNonEmptyStr = None


class ArtifactPersisted(_LedgerEventBase):
    """One immutable per-attempt artifact was persisted."""

    event_kind: Literal["artifact_persisted"] = "artifact_persisted"
    artifact_kind: PersistedArtifactKind
    relative_path: RelativeArtifactPath
    content_hash: Sha256Fingerprint


class ProposalPersisted(_LedgerEventBase):
    """A Stage-10 ChangeSet proposal was persisted for this attempt."""

    event_kind: Literal["proposal_persisted"] = "proposal_persisted"
    changeset_id: NonEmptyStr
    changeset_fingerprint: Sha256Fingerprint


class AttemptCompleted(_LedgerEventBase):
    """The attempt reached a terminal successful outcome."""

    event_kind: Literal["attempt_completed"] = "attempt_completed"
    outcome: ProcessingOutcome


class AttemptFailed(_LedgerEventBase):
    """The attempt reached a terminal failed outcome."""

    event_kind: Literal["attempt_failed"] = "attempt_failed"
    phase: ProcessingPhase
    failure_category: FailureCategory
    message: BoundedMessageStr


class AttemptSuperseded(_LedgerEventBase):
    """The attempt was explicitly superseded by a later attempt."""

    event_kind: Literal["attempt_superseded"] = "attempt_superseded"
    superseded_by_attempt_id: PostSessionAttemptId
    reason: NonEmptyStr


ProcessingLedgerEvent = Annotated[
    AttemptStarted
    | ArtifactPersisted
    | ProposalPersisted
    | AttemptCompleted
    | AttemptFailed
    | AttemptSuperseded,
    Field(discriminator="event_kind"),
]
"""Versioned append-only processing-ledger event union (C4).

Unknown ``event_kind`` values and unsupported ``schema_version`` values fail
validation; there is no generic fallback.
"""

__all__ = [
    "ArtifactKind",
    "ArtifactPersisted",
    "AttemptCompleted",
    "AttemptFailed",
    "AttemptStarted",
    "AttemptSuperseded",
    "BoundedMessageStr",
    "FailureCategory",
    "InputFingerprint",
    "LedgerEventId",
    "NonEmptyStr",
    "OptionalNonEmptyStr",
    "PersistedArtifactKind",
    "PostSessionAttemptId",
    "PreparedCalendarProjection",
    "PreparedContextProjection",
    "PreparedEntityProjection",
    "PreparedInputIdentity",
    "PreparedRawEvent",
    "PreparedSessionProjection",
    "ProcessingLedgerEvent",
    "ProcessingOutcome",
    "ProcessingPhase",
    "ProposalPersisted",
    "RelativeArtifactPath",
    "Sha256Fingerprint",
]
