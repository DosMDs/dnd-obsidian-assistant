"""S11-04 in-memory Summary/Recap rendering boundary.

Owns:

- the two **structurally distinct** application request types
  ``SummaryRenderRequest`` and ``RecapRenderRequest`` (the Recap request type
  cannot carry unresolved references, new-entity candidates, DM/SYSTEM entity
  projections or canonical entity bodies);
- pure deterministic model-visible serializers for each request;
- the provider-neutral ``PostSessionRenderingModel`` protocol;
- complete prepared/extraction provenance binding verified before any model
  call;
- stable rendering failure reasons and their mapping to the durable
  ``FailureCategory`` vocabulary;
- the public entrypoints ``generate_summary`` / ``generate_recap``.

Summary and Recap are **presentation over the accepted S11-03 extraction**,
never a second extraction pass.  The Recap model never receives DM/SYSTEM
entity material or excluded claim text: Python constructs the player-safe
request before the renderer is invoked.

Nothing is persisted here.  Both success and failure are in-memory.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, or a concrete storage
    implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, field_validator

from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_extraction import (
    AcceptedPostSessionExtraction,
    ModelExecutionIdentity,
)
from dnd_assistant.application.post_session_visibility import (
    RecapClaimProjection,
    RecapEntityRef,
    RecapFilterResult,
    SummaryCandidateProjection,
    SummaryClaimProjection,
    SummaryEntityRef,
    SummaryFilterResult,
    SummaryUnresolvedReferenceProjection,
    project_recap,
    project_summary,
)
from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.post_session import (
    ArtifactKind,
    FailureCategory,
    Sha256Fingerprint,
)
from dnd_assistant.domain.post_session_artifacts import (
    MAX_RENDER_BODY_CHARS,
    POST_SESSION_RENDER_SCHEMA_VERSION,
    PostSessionRenderOutput,
    RenderOutcome,
)
from dnd_assistant.domain.post_session_extraction import (
    POST_SESSION_EXTRACTION_SCHEMA_VERSION,
)
from dnd_assistant.errors import ModelError
from dnd_assistant.prompts.post_session_recap_v1 import POST_SESSION_RECAP_PROMPT_ID
from dnd_assistant.prompts.post_session_summary_v1 import POST_SESSION_SUMMARY_PROMPT_ID

MAX_RENDER_INPUT_CHARS: Final[int] = 200_000
"""Fail-closed ceiling for a serialized model-visible render request."""


# ── Errors ────────────────────────────────────────────────────────────────


class RenderingFailureReason(StrEnum):
    """Bounded, stable classification of a rendering failure."""

    PROVENANCE_MISMATCH = "provenance_mismatch"
    INVALID_REQUEST = "invalid_request"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_INVOCATION_FAILED = "model_invocation_failed"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    UNSUPPORTED_RENDER_SCHEMA = "unsupported_render_schema"
    EMPTY_OUTPUT = "empty_output"
    OUTPUT_BOUNDS_EXCEEDED = "output_bounds_exceeded"


def _failure_category_for(reason: RenderingFailureReason) -> FailureCategory:
    """Map a rendering reason to the durable processing failure vocabulary."""
    if reason is RenderingFailureReason.MODEL_UNAVAILABLE:
        return FailureCategory.MODEL_UNAVAILABLE
    if reason is RenderingFailureReason.MODEL_TIMEOUT:
        return FailureCategory.MODEL_TIMEOUT
    if reason is RenderingFailureReason.PROVENANCE_MISMATCH:
        return FailureCategory.FINGERPRINT_MISMATCH
    return FailureCategory.INVALID_OUTPUT


class PostSessionRenderingError(ModelError):
    """Raised when post-session Summary/Recap rendering fails closed."""

    def __init__(
        self,
        reason: RenderingFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason

    def to_failure_category(self) -> FailureCategory:
        """Return the durable ``FailureCategory`` for this failure."""
        return _failure_category_for(self.reason)


# ── Request validation helpers ────────────────────────────────────────────


def _validate_nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


# ── Structurally distinct request types ───────────────────────────────────


class _RenderRequestBase(BaseModel):
    """Shared Python-owned provenance/identity fields for a render request."""

    session_ref: str
    input_fingerprint: Sha256Fingerprint
    processor_version: str
    render_prompt_version: str
    render_schema_version: int
    world_tick_start: WorldTick
    world_tick_end: WorldTick
    real_started_at: AwareDatetime
    real_finished_at: AwareDatetime

    model_config = {"frozen": True, "extra": "forbid"}

    @field_validator("session_ref", "processor_version", "render_prompt_version")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        return _validate_nonempty(value, "field")


class SummaryRenderRequest(_RenderRequestBase):
    """GM/internal rendering request.

    May carry DM-visible canonical entities, unresolved references and
    new-entity candidates, but never SYSTEM entities (structurally excluded by
    ``SummaryEntityRef``) and never canonical entity bodies.
    """

    artifact_kind: Literal["summary"] = "summary"
    claims: tuple[SummaryClaimProjection, ...] = ()
    entities: tuple[SummaryEntityRef, ...] = ()
    unresolved_references: tuple[SummaryUnresolvedReferenceProjection, ...] = ()
    entity_candidates: tuple[SummaryCandidateProjection, ...] = ()


class RecapRenderRequest(_RenderRequestBase):
    """Player-safe rendering request.

    Structurally limited to player-authorized claims and player-visible entity
    references.  It has no field capable of carrying unresolved references,
    new-entity candidates, DM/SYSTEM entity projections, canonical entity
    bodies, the full accepted extraction or the full prepared context.
    """

    artifact_kind: Literal["recap"] = "recap"
    claims: tuple[RecapClaimProjection, ...] = ()
    entities: tuple[RecapEntityRef, ...] = ()


# ── Provider-neutral protocol ─────────────────────────────────────────────


class PostSessionRenderingModel(Protocol):
    """Provider-neutral Summary/Recap rendering boundary.

    Implementations expose no project/action tools and perform exactly one
    bounded structured render per call.  A deterministic fake can implement
    this protocol without any provider/framework dependency.
    """

    def render(
        self,
        request: SummaryRenderRequest | RecapRenderRequest,
    ) -> PostSessionRenderOutput:
        """Render one artifact request into a bounded structured output."""
        ...


# ── Deterministic model-visible serialization ─────────────────────────────


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def serialize_summary_request(request: SummaryRenderRequest) -> str:
    """Serialize the internal Summary model-visible payload deterministically."""
    return _canonical_json(request.model_dump(mode="json"))


def serialize_recap_request(request: RecapRenderRequest) -> str:
    """Serialize the player-safe Recap model-visible payload deterministically."""
    return _canonical_json(request.model_dump(mode="json"))


def _ensure_bounded(serialized: str, artifact: str) -> None:
    if len(serialized) > MAX_RENDER_INPUT_CHARS:
        raise PostSessionRenderingError(
            RenderingFailureReason.OUTPUT_BOUNDS_EXCEEDED,
            f"{artifact} render input exceeds {MAX_RENDER_INPUT_CHARS} characters",
        )


# ── Request construction (internal only) ──────────────────────────────────


def build_summary_render_request(
    prepared: PreparedPostSessionInput,
    summary: SummaryFilterResult,
) -> SummaryRenderRequest:
    """Build the internal Summary request from accepted input + projection."""
    identity = prepared.identity
    return SummaryRenderRequest(
        session_ref=identity.session.id,
        input_fingerprint=prepared.fingerprint,
        processor_version=identity.processor_version,
        render_prompt_version=POST_SESSION_SUMMARY_PROMPT_ID,
        render_schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
        world_tick_start=identity.calendar.world_tick_start,
        world_tick_end=identity.calendar.world_tick_end,
        real_started_at=identity.session.real_started_at,
        real_finished_at=identity.session.real_finished_at,
        claims=summary.claims,
        entities=summary.entities,
        unresolved_references=summary.unresolved_references,
        entity_candidates=summary.entity_candidates,
    )


def build_recap_render_request(
    prepared: PreparedPostSessionInput,
    recap: RecapFilterResult,
) -> RecapRenderRequest:
    """Build the player-safe Recap request from accepted input + projection."""
    identity = prepared.identity
    return RecapRenderRequest(
        session_ref=identity.session.id,
        input_fingerprint=prepared.fingerprint,
        processor_version=identity.processor_version,
        render_prompt_version=POST_SESSION_RECAP_PROMPT_ID,
        render_schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
        world_tick_start=identity.calendar.world_tick_start,
        world_tick_end=identity.calendar.world_tick_end,
        real_started_at=identity.session.real_started_at,
        real_finished_at=identity.session.real_finished_at,
        claims=recap.claims,
        entities=recap.entities,
    )


# ── Provenance and result ─────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderingProvenance:
    """Python-owned provenance exposed to S11-06 for durable recording."""

    artifact_kind: ArtifactKind
    session_ref: str
    input_fingerprint: Sha256Fingerprint
    processor_version: str
    render_prompt_version: str
    render_schema_version: int
    model_profile: str | None = None
    model: str | None = None
    provider: str | None = None


@dataclass(frozen=True)
class RenderedPostSessionArtifact:
    """In-memory rendered artifact (S11-04 persists nothing).

    Invariant:

    - ``RenderOutcome.RENDERED`` requires non-empty ``content``;
    - ``RenderOutcome.EMPTY`` requires ``content is None`` (no model call was
      made and no empty string is used as a successful render).
    """

    provenance: RenderingProvenance
    outcome: RenderOutcome
    content: str | None

    def __post_init__(self) -> None:
        if self.outcome is RenderOutcome.RENDERED:
            if not isinstance(self.content, str) or not self.content:
                raise ValueError("RENDERED artifact requires non-empty str content")
        elif self.outcome is RenderOutcome.EMPTY:
            if self.content is not None:
                raise ValueError("EMPTY artifact requires content=None")


def _verify_provenance(
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
) -> None:
    """Fail closed unless the accepted extraction belongs to this input.

    Verifies session identity, input fingerprint, processor version,
    extraction prompt version and both extraction schema-version declarations.
    """
    provenance = accepted.provenance
    identity = prepared.identity

    mismatches: list[str] = []
    if provenance.session_ref != identity.session.id:
        mismatches.append("session_ref")
    if provenance.input_fingerprint != prepared.fingerprint:
        mismatches.append("input_fingerprint")
    if provenance.processor_version != identity.processor_version:
        mismatches.append("processor_version")
    if provenance.prompt_version != identity.prompt_version:
        mismatches.append("prompt_version")
    if provenance.extraction_schema_version != POST_SESSION_EXTRACTION_SCHEMA_VERSION:
        mismatches.append("extraction_schema_version")
    if accepted.validated.extraction.schema_version != POST_SESSION_EXTRACTION_SCHEMA_VERSION:
        mismatches.append("extraction.schema_version")

    if mismatches:
        raise PostSessionRenderingError(
            RenderingFailureReason.PROVENANCE_MISMATCH,
            "Accepted extraction does not belong to the prepared input: " + ", ".join(mismatches),
        )


def _provenance(
    artifact_kind: ArtifactKind,
    prepared: PreparedPostSessionInput,
    model_identity: ModelExecutionIdentity | None,
) -> RenderingProvenance:
    identity = model_identity or ModelExecutionIdentity()
    prompt_version = (
        POST_SESSION_SUMMARY_PROMPT_ID
        if artifact_kind is ArtifactKind.SUMMARY
        else POST_SESSION_RECAP_PROMPT_ID
    )
    return RenderingProvenance(
        artifact_kind=artifact_kind,
        session_ref=prepared.identity.session.id,
        input_fingerprint=prepared.fingerprint,
        processor_version=prepared.identity.processor_version,
        render_prompt_version=prompt_version,
        render_schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
        model_profile=identity.profile,
        model=identity.model,
        provider=identity.provider,
    )


def _validate_render_output(output: object) -> str:
    """Validate an untrusted render output and return its bounded body."""
    if not isinstance(output, PostSessionRenderOutput):
        raise PostSessionRenderingError(
            RenderingFailureReason.INVALID_STRUCTURED_OUTPUT,
            f"Model returned an unexpected output type: {type(output).__name__}",
        )
    if output.schema_version != POST_SESSION_RENDER_SCHEMA_VERSION:
        raise PostSessionRenderingError(
            RenderingFailureReason.UNSUPPORTED_RENDER_SCHEMA,
            f"Render schema version {output.schema_version} is unsupported; "
            f"expected {POST_SESSION_RENDER_SCHEMA_VERSION}",
        )
    body = output.body
    if not body.strip():
        raise PostSessionRenderingError(
            RenderingFailureReason.EMPTY_OUTPUT,
            "Model returned an empty rendering body",
        )
    if len(body) > MAX_RENDER_BODY_CHARS:
        raise PostSessionRenderingError(
            RenderingFailureReason.OUTPUT_BOUNDS_EXCEEDED,
            f"Render body exceeds {MAX_RENDER_BODY_CHARS} characters",
        )
    return body


# ── Public entrypoints ────────────────────────────────────────────────────


def generate_summary(
    model: PostSessionRenderingModel,
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
    *,
    model_identity: ModelExecutionIdentity | None = None,
) -> RenderedPostSessionArtifact:
    """Render the GM/internal Summary from accepted evidence.

    Raises:
        PostSessionRenderingError: Provenance mismatch (before any model
            call), model/framework failure, or invalid rendering output.
    """
    _verify_provenance(prepared, accepted)
    summary = project_summary(prepared, accepted)
    request = build_summary_render_request(prepared, summary)
    serialized = serialize_summary_request(request)
    _ensure_bounded(serialized, "Summary")
    output = model.render(request)
    body = _validate_render_output(output)
    return RenderedPostSessionArtifact(
        provenance=_provenance(ArtifactKind.SUMMARY, prepared, model_identity),
        outcome=RenderOutcome.RENDERED,
        content=body,
    )


def generate_recap(
    model: PostSessionRenderingModel,
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
    *,
    model_identity: ModelExecutionIdentity | None = None,
) -> RenderedPostSessionArtifact:
    """Render the player-facing Recap from the deterministic safe projection.

    If the projection contains no player-safe claim, this makes **no** model
    call and returns a deterministic ``EMPTY`` result with ``content=None``.

    Raises:
        PostSessionRenderingError: Provenance mismatch (before any model
            call), model/framework failure, or invalid rendering output.
    """
    _verify_provenance(prepared, accepted)
    recap = project_recap(prepared, accepted)
    provenance = _provenance(ArtifactKind.RECAP, prepared, model_identity)
    if not recap.claims:
        return RenderedPostSessionArtifact(
            provenance=provenance,
            outcome=RenderOutcome.EMPTY,
            content=None,
        )
    request = build_recap_render_request(prepared, recap)
    serialized = serialize_recap_request(request)
    _ensure_bounded(serialized, "Recap")
    output = model.render(request)
    body = _validate_render_output(output)
    return RenderedPostSessionArtifact(
        provenance=provenance,
        outcome=RenderOutcome.RENDERED,
        content=body,
    )


__all__ = [
    "MAX_RENDER_INPUT_CHARS",
    "PostSessionRenderingError",
    "PostSessionRenderingModel",
    "RecapRenderRequest",
    "RenderedPostSessionArtifact",
    "RenderingFailureReason",
    "RenderingProvenance",
    "SummaryRenderRequest",
    "build_recap_render_request",
    "build_summary_render_request",
    "generate_recap",
    "generate_summary",
    "serialize_recap_request",
    "serialize_summary_request",
]
