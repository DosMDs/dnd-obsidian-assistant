"""Stage-11 application-owned extraction protocol and semantic validation (S11-03).

This module owns:

- the bounded, trusted extraction **request** derived from an accepted
  ``PreparedPostSessionInput`` (Correction 1);
- the provider-neutral ``PostSessionExtractionModel`` protocol;
- stable extraction failure reasons and their mapping to the durable
  ``FailureCategory`` vocabulary;
- post-framework **semantic** validation of the untrusted typed extraction.

Trust model
───────────

The model may return a syntactically valid ``PostSessionExtraction``.  That is
**not** semantic acceptance.  This module validates it against the exact
prepared input before it can be consumed by S11-04/S11-05:

- every evidence event id must exist in the prepared raw events;
- a claimed existing entity id is trusted only when it is selected in this
  prepared input **and** the declared type matches the canonical prepared type;
- unknown/non-selected ids never become canonical bindings;
- new-entity candidates never carry a final ``EntityId``.

The public entrypoint ``run_post_session_extraction`` accepts the accepted
``PreparedPostSessionInput`` and derives the request internally, so request
context, evidence references, entity bindings and version fields cannot be
independently substituted by a caller.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, or a concrete storage
    implementation (storage read protocols are referenced only under
    ``TYPE_CHECKING`` elsewhere in the layer).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from pydantic import BaseModel, Field, field_validator

from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.domain.post_session import FailureCategory, Sha256Fingerprint
from dnd_assistant.domain.post_session_extraction import (
    MAX_ENTITY_MENTIONS,
    MAX_ENTITY_MENTIONS_PER_CLAIM,
    POST_SESSION_EXTRACTION_SCHEMA_VERSION,
    ExtractedEntityMention,
    PostSessionExtraction,
)
from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.errors import ModelError

# ── Project-owned semantic bounds ─────────────────────────────────────────

MAX_EXTRACTION_TOTAL_CHARS: Final[int] = 500_000
"""Maximum summed character length of all extraction text, enforced in Python."""

_SUPPORTED_ENTITY_TYPES: Final[frozenset[EntityType]] = frozenset(EntityType)
"""MVP canonical entity types; no speculative domain expansion."""


# ── Errors ────────────────────────────────────────────────────────────────


class ExtractionFailureReason(StrEnum):
    """Bounded, stable classification of an extraction failure."""

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_INVOCATION_FAILED = "model_invocation_failed"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    INVALID_EVIDENCE_REFERENCE = "invalid_evidence_reference"
    UNSUPPORTED_ENTITY_TYPE = "unsupported_entity_type"
    DUPLICATE_CLAIM_ID = "duplicate_claim_id"
    DUPLICATE_MENTION_ID = "duplicate_mention_id"
    DUPLICATE_CANDIDATE_ID = "duplicate_candidate_id"
    CONTRADICTORY_BINDING = "contradictory_binding"
    OUTPUT_BOUNDS_EXCEEDED = "output_bounds_exceeded"


def _failure_category_for(reason: ExtractionFailureReason) -> FailureCategory:
    """Map an extraction reason to the durable processing failure vocabulary."""
    if reason is ExtractionFailureReason.MODEL_UNAVAILABLE:
        return FailureCategory.MODEL_UNAVAILABLE
    if reason is ExtractionFailureReason.MODEL_TIMEOUT:
        return FailureCategory.MODEL_TIMEOUT
    return FailureCategory.INVALID_OUTPUT


class PostSessionExtractionError(ModelError):
    """Raised when post-session extraction fails closed.

    Subclasses the existing ``ModelError`` hierarchy so callers may catch
    ``ModelError`` broadly while the stable ``reason`` remains available to
    S11-06 for durable evidence.
    """

    def __init__(
        self,
        reason: ExtractionFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason

    def to_failure_category(self) -> FailureCategory:
        """Return the durable ``FailureCategory`` for this failure."""
        return _failure_category_for(self.reason)


# ── Trusted request construction (Correction 1) ───────────────────────────


def _validate_nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _normalized_unique(values: Sequence[str]) -> tuple[str, ...]:
    """Order-preserving first-occurrence deduplication."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


class ExpectedEntityBinding(BaseModel):
    """Python-owned expected canonical binding for one selected entity.

    Derived from ``PreparedInputIdentity.entities``.  Provides literal
    canonical type binding so a model-declared type can be checked against the
    prepared entity type, not merely against an id string set.
    """

    entity_id: EntityId
    entity_type: EntityType

    model_config = {"frozen": True, "extra": "forbid"}


class PostSessionExtractionRequest(BaseModel):
    """Immutable application-owned extraction request.

    Built exclusively by ``build_post_session_extraction_request`` from an
    accepted ``PreparedPostSessionInput``.  It is the model-visible request
    and the Python-owned binding snapshot used by semantic validation.
    """

    session_ref: str
    input_fingerprint: Sha256Fingerprint
    context_text: str
    expected_event_ids: tuple[str, ...] = ()
    expected_entity_bindings: tuple[ExpectedEntityBinding, ...] = ()
    processor_version: str
    prompt_version: str
    extraction_schema_version: int = Field(ge=0)

    model_config = {"frozen": True, "extra": "forbid"}

    @field_validator("session_ref", "processor_version", "prompt_version")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _validate_nonempty(v, "field")

    @field_validator("context_text")
    @classmethod
    def _context_non_empty(cls, v: str) -> str:
        return _validate_nonempty(v, "context_text")

    @field_validator("expected_event_ids")
    @classmethod
    def _event_ids_non_empty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for event_id in v:
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError("expected_event_ids must contain non-empty strings")
        return v

    @property
    def expected_entity_ids(self) -> frozenset[str]:
        """The selected entity id set for set-membership checks."""
        return frozenset(binding.entity_id for binding in self.expected_entity_bindings)


def build_post_session_extraction_request(
    prepared: PreparedPostSessionInput,
    *,
    extraction_schema_version: int = POST_SESSION_EXTRACTION_SCHEMA_VERSION,
) -> PostSessionExtractionRequest:
    """Derive the trusted extraction request from accepted prepared input.

    Every field originates from the same fingerprinted input; no caller may
    substitute context, evidence ids, bindings or version fields independently.

    Raises:
        PostSessionExtractionError: An unsupported schema version or empty
            prepared context, before any model call.
    """
    if extraction_schema_version != POST_SESSION_EXTRACTION_SCHEMA_VERSION:
        raise PostSessionExtractionError(
            ExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION,
            f"Extraction schema version {extraction_schema_version} is unsupported; "
            f"expected {POST_SESSION_EXTRACTION_SCHEMA_VERSION}",
        )

    identity = prepared.identity
    context_text = identity.context.text
    if not context_text.strip():
        raise PostSessionExtractionError(
            ExtractionFailureReason.INVALID_REQUEST,
            "Prepared context text is empty; refusing to build an extraction request",
        )

    bindings = tuple(
        ExpectedEntityBinding(entity_id=entity.id, entity_type=entity.type)
        for entity in identity.entities
    )
    return PostSessionExtractionRequest(
        session_ref=identity.session.id,
        input_fingerprint=prepared.fingerprint,
        context_text=context_text,
        expected_event_ids=_normalized_unique([event.event_id for event in identity.raw_events]),
        expected_entity_bindings=bindings,
        processor_version=identity.processor_version,
        prompt_version=identity.prompt_version,
        extraction_schema_version=extraction_schema_version,
    )


# ── Model protocol ────────────────────────────────────────────────────────


class PostSessionExtractionModel(Protocol):
    """Provider-neutral heavy-model structured-extraction boundary.

    Implementations expose no project/action tools and perform exactly one
    bounded structured extraction per call.  A deterministic fake can
    implement this protocol without any provider/framework dependency.
    """

    def extract(self, request: PostSessionExtractionRequest) -> PostSessionExtraction:
        """Perform one bounded structured extraction over ``request``.

        Returns a syntactically typed but still untrusted extraction.  Raises
        ``PostSessionExtractionError`` on framework/provider failure.
        """
        ...


# ── Semantic validation results ───────────────────────────────────────────


class UnresolvedReferenceReason(StrEnum):
    """Why a model entity reference is not a trusted binding."""

    NO_CANDIDATE_ID = "no_candidate_id"
    NOT_IN_PREPARED_INPUT = "not_in_prepared_input"
    TYPE_MISMATCH = "type_mismatch"


@dataclass(frozen=True)
class ResolvedEntityMention:
    """A mention bound to a canonical prepared entity by Python."""

    claim_id: str
    mention_id: str
    entity_id: EntityId
    entity_type: EntityType


@dataclass(frozen=True)
class UnresolvedEntityReference:
    """A mention that must not be treated as a canonical binding."""

    claim_id: str
    mention_id: str
    text: str
    entity_type: EntityType
    reason: UnresolvedReferenceReason


@dataclass(frozen=True)
class ValidatedPostSessionExtraction:
    """Semantically accepted extraction plus Python-owned binding results.

    ``extraction`` is a sanitized copy: any ``candidate_entity_id`` that did
    not pass validation is cleared, so a fabricated id cannot survive in a
    field consumers might treat as trusted.
    """

    extraction: PostSessionExtraction
    resolved_mentions: tuple[ResolvedEntityMention, ...]
    unresolved_references: tuple[UnresolvedEntityReference, ...]


# ── Semantic validator ────────────────────────────────────────────────────


def _normalize_evidence(
    evidence_ids: Sequence[str],
    allowed_event_ids: frozenset[str],
    owner: str,
) -> tuple[str, ...]:
    """Validate and order-preserving deduplicate evidence references."""
    result: list[str] = []
    seen: set[str] = set()
    for event_id in evidence_ids:
        if event_id not in allowed_event_ids:
            raise PostSessionExtractionError(
                ExtractionFailureReason.INVALID_EVIDENCE_REFERENCE,
                f"{owner} references evidence event {event_id!r} that is not "
                f"present in the prepared input",
            )
        if event_id not in seen:
            seen.add(event_id)
            result.append(event_id)
    return tuple(result)


def _validate_total_size(extraction: PostSessionExtraction) -> None:
    """Enforce the Python-owned total text budget and global mention count."""
    total = 0
    mention_count = 0
    for claim in extraction.claims:
        total += len(claim.text)
        mention_count += len(claim.entity_mentions)
        for mention in claim.entity_mentions:
            total += len(mention.text)
        if total > MAX_EXTRACTION_TOTAL_CHARS:
            raise PostSessionExtractionError(
                ExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED,
                f"Extraction total text exceeds {MAX_EXTRACTION_TOTAL_CHARS} characters",
            )
    if mention_count > MAX_ENTITY_MENTIONS:
        raise PostSessionExtractionError(
            ExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED,
            f"Extraction mention count {mention_count} exceeds {MAX_ENTITY_MENTIONS}",
        )
    for candidate in extraction.entity_candidates:
        total += len(candidate.display_name)
        if candidate.summary is not None:
            total += len(candidate.summary)
        for attribute in candidate.attributes:
            total += len(attribute.key) + len(attribute.value)
        if total > MAX_EXTRACTION_TOTAL_CHARS:
            raise PostSessionExtractionError(
                ExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED,
                f"Extraction total text exceeds {MAX_EXTRACTION_TOTAL_CHARS} characters",
            )


def _bind_mention(
    claim_id: str,
    mention: ExtractedEntityMention,
    normalized_evidence: tuple[str, ...],
    bindings: dict[str, EntityType],
    resolved: list[ResolvedEntityMention],
    unresolved: list[UnresolvedEntityReference],
) -> ExtractedEntityMention:
    """Return a sanitized mention and record resolution outcome.

    The returned mention always carries the normalized ``evidence_event_ids``
    passed in (validated and deduplicated by the caller) and the sanitized
    ``candidate_entity_id``: a fabricated or type-mismatched id is cleared,
    while a trusted binding is preserved.
    """
    if mention.entity_type not in _SUPPORTED_ENTITY_TYPES:
        raise PostSessionExtractionError(
            ExtractionFailureReason.UNSUPPORTED_ENTITY_TYPE,
            f"Mention {mention.mention_id!r} declares unsupported type {mention.entity_type!r}",
        )

    candidate_id = mention.candidate_entity_id
    if candidate_id is None:
        unresolved.append(
            UnresolvedEntityReference(
                claim_id=claim_id,
                mention_id=mention.mention_id,
                text=mention.text,
                entity_type=mention.entity_type,
                reason=UnresolvedReferenceReason.NO_CANDIDATE_ID,
            )
        )
        return mention.model_copy(update={"evidence_event_ids": normalized_evidence})

    if candidate_id not in bindings:
        unresolved.append(
            UnresolvedEntityReference(
                claim_id=claim_id,
                mention_id=mention.mention_id,
                text=mention.text,
                entity_type=mention.entity_type,
                reason=UnresolvedReferenceReason.NOT_IN_PREPARED_INPUT,
            )
        )
        return mention.model_copy(
            update={"candidate_entity_id": None, "evidence_event_ids": normalized_evidence}
        )

    if bindings[candidate_id] is not mention.entity_type:
        unresolved.append(
            UnresolvedEntityReference(
                claim_id=claim_id,
                mention_id=mention.mention_id,
                text=mention.text,
                entity_type=mention.entity_type,
                reason=UnresolvedReferenceReason.TYPE_MISMATCH,
            )
        )
        return mention.model_copy(
            update={"candidate_entity_id": None, "evidence_event_ids": normalized_evidence}
        )

    resolved.append(
        ResolvedEntityMention(
            claim_id=claim_id,
            mention_id=mention.mention_id,
            entity_id=candidate_id,
            entity_type=mention.entity_type,
        )
    )
    return mention.model_copy(update={"evidence_event_ids": normalized_evidence})


def validate_post_session_extraction(
    extraction: PostSessionExtraction,
    request: PostSessionExtractionRequest,
) -> ValidatedPostSessionExtraction:
    """Semantically validate framework output against the trusted request.

    Runs **after** framework syntactic/structured-output validation.  Raises
    ``PostSessionExtractionError`` on any violation; never mutates the
    campaign or the prepared input.
    """
    if extraction.schema_version != POST_SESSION_EXTRACTION_SCHEMA_VERSION:
        raise PostSessionExtractionError(
            ExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION,
            f"Model returned extraction schema version {extraction.schema_version}; "
            f"expected {POST_SESSION_EXTRACTION_SCHEMA_VERSION}",
        )

    _validate_total_size(extraction)

    allowed_event_ids = frozenset(request.expected_event_ids)
    bindings: dict[str, EntityType] = {
        binding.entity_id: binding.entity_type for binding in request.expected_entity_bindings
    }

    seen_claim_ids: set[str] = set()
    seen_mention_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    resolved: list[ResolvedEntityMention] = []
    unresolved: list[UnresolvedEntityReference] = []
    sanitized_claims = []

    for claim in extraction.claims:
        if claim.claim_id in seen_claim_ids:
            raise PostSessionExtractionError(
                ExtractionFailureReason.DUPLICATE_CLAIM_ID,
                f"Duplicate claim_id {claim.claim_id!r}",
            )
        seen_claim_ids.add(claim.claim_id)

        evidence = _normalize_evidence(
            claim.evidence_event_ids,
            allowed_event_ids,
            f"Claim {claim.claim_id}",
        )
        if len(claim.entity_mentions) > MAX_ENTITY_MENTIONS_PER_CLAIM:
            raise PostSessionExtractionError(
                ExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED,
                f"Claim {claim.claim_id} has too many entity mentions",
            )

        sanitized_mentions = []
        for mention in claim.entity_mentions:
            if mention.mention_id in seen_mention_ids:
                raise PostSessionExtractionError(
                    ExtractionFailureReason.DUPLICATE_MENTION_ID,
                    f"Duplicate mention_id {mention.mention_id!r}",
                )
            seen_mention_ids.add(mention.mention_id)
            mention_evidence = _normalize_evidence(
                mention.evidence_event_ids,
                allowed_event_ids,
                f"Mention {mention.mention_id}",
            )
            sanitized_mentions.append(
                _bind_mention(
                    claim.claim_id,
                    mention,
                    mention_evidence,
                    bindings,
                    resolved,
                    unresolved,
                )
            )

        sanitized_claims.append(
            claim.model_copy(
                update={
                    "evidence_event_ids": evidence,
                    "entity_mentions": tuple(sanitized_mentions),
                }
            )
        )

    sanitized_candidates = []
    for candidate in extraction.entity_candidates:
        if candidate.candidate_id in seen_candidate_ids:
            raise PostSessionExtractionError(
                ExtractionFailureReason.DUPLICATE_CANDIDATE_ID,
                f"Duplicate candidate_id {candidate.candidate_id!r}",
            )
        seen_candidate_ids.add(candidate.candidate_id)
        if candidate.entity_type not in _SUPPORTED_ENTITY_TYPES:
            raise PostSessionExtractionError(
                ExtractionFailureReason.UNSUPPORTED_ENTITY_TYPE,
                f"Candidate {candidate.candidate_id!r} declares unsupported type "
                f"{candidate.entity_type!r}",
            )
        candidate_evidence = _normalize_evidence(
            candidate.evidence_event_ids,
            allowed_event_ids,
            f"Candidate {candidate.candidate_id}",
        )
        sanitized_candidates.append(
            candidate.model_copy(update={"evidence_event_ids": candidate_evidence})
        )

    sanitized = extraction.model_copy(
        update={
            "claims": tuple(sanitized_claims),
            "entity_candidates": tuple(sanitized_candidates),
        }
    )
    return ValidatedPostSessionExtraction(
        extraction=sanitized,
        resolved_mentions=tuple(resolved),
        unresolved_references=tuple(unresolved),
    )


# ── Provenance and policy entrypoint ──────────────────────────────────────


@dataclass(frozen=True)
class ModelExecutionIdentity:
    """Non-deterministic execution identity of the heavy model (operator data)."""

    profile: str | None = None
    model: str | None = None
    provider: str | None = None


@dataclass(frozen=True)
class ExtractionProvenance:
    """Provenance exposed to S11-06 for durable ledger recording."""

    session_ref: str
    input_fingerprint: Sha256Fingerprint
    processor_version: str
    prompt_version: str
    extraction_schema_version: int
    model_profile: str | None = None
    model: str | None = None
    provider: str | None = None


@dataclass(frozen=True)
class AcceptedPostSessionExtraction:
    """A semantically accepted extraction plus its provenance.

    In-memory only; S11-03 persists nothing.
    """

    validated: ValidatedPostSessionExtraction
    provenance: ExtractionProvenance


def run_post_session_extraction(
    model: PostSessionExtractionModel,
    prepared: PreparedPostSessionInput,
    *,
    model_identity: ModelExecutionIdentity | None = None,
) -> AcceptedPostSessionExtraction:
    """Run one bounded extraction for an accepted prepared input.

    The request is derived internally from ``prepared``; a caller cannot
    substitute context, evidence ids, entity bindings or version fields.

    Raises:
        PostSessionExtractionError: Invalid request, model/framework failure,
            or semantic validation failure.
    """
    request = build_post_session_extraction_request(prepared)
    extraction = model.extract(request)

    if not isinstance(extraction, PostSessionExtraction):
        raise PostSessionExtractionError(
            ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT,
            f"Model returned an unexpected output type: {type(extraction).__name__}",
        )

    validated = validate_post_session_extraction(extraction, request)
    identity = model_identity or ModelExecutionIdentity()
    provenance = ExtractionProvenance(
        session_ref=request.session_ref,
        input_fingerprint=request.input_fingerprint,
        processor_version=request.processor_version,
        prompt_version=request.prompt_version,
        extraction_schema_version=request.extraction_schema_version,
        model_profile=identity.profile,
        model=identity.model,
        provider=identity.provider,
    )
    return AcceptedPostSessionExtraction(validated=validated, provenance=provenance)


__all__ = [
    "AcceptedPostSessionExtraction",
    "ExpectedEntityBinding",
    "ExtractionFailureReason",
    "ExtractionProvenance",
    "MAX_EXTRACTION_TOTAL_CHARS",
    "ModelExecutionIdentity",
    "PostSessionExtractionError",
    "PostSessionExtractionModel",
    "PostSessionExtractionRequest",
    "ResolvedEntityMention",
    "UnresolvedEntityReference",
    "UnresolvedReferenceReason",
    "ValidatedPostSessionExtraction",
    "build_post_session_extraction_request",
    "run_post_session_extraction",
    "validate_post_session_extraction",
]
