"""S13-03 application-owned bootstrap extraction protocol and validation.

Owns:

- the bounded, trusted bootstrap extraction **request** derived from a prepared
  batch (never substitutable field-by-field by a caller);
- the provider-neutral ``BootstrapExtractionModel`` protocol;
- stable extraction failure reasons;
- post-framework **semantic** validation of the untrusted typed extraction;
- deterministic merge of multiple batch extractions.

Trust model
───────────

The model may return a syntactically valid ``BootstrapExtraction``.  That is
**not** semantic acceptance.  This module validates it against the trusted
batch request before it can be consumed by the mapping producer:

- every source reference must be one Python supplied in the request;
- duplicate candidate/claim/reference ids are rejected;
- the extraction is bounded in total text size;
- the schema cannot represent a canonical ``EntityId``, revision or path at all.

Binding to canonical entities happens later, deterministically, in the mapping
producer.  This module performs no repository access and no model call itself.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from pydantic import BaseModel, Field, field_validator

from dnd_assistant.application.bootstrap_input import (
    BootstrapBatch,
    BootstrapInputProjection,
)
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapClaim,
    BootstrapEntityCandidate,
    BootstrapEntityReference,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import Sha256Fingerprint
from dnd_assistant.errors import ModelError

# ── Project-owned semantic bounds ─────────────────────────────────────────

MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS: Final[int] = 500_000
"""Maximum summed character length of all extraction text, enforced in Python."""


# ── Errors ────────────────────────────────────────────────────────────────


class BootstrapExtractionFailureReason(StrEnum):
    """Bounded, stable classification of a bootstrap extraction failure."""

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_INVOCATION_FAILED = "model_invocation_failed"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    INVALID_SOURCE_REFERENCE = "invalid_source_reference"
    DUPLICATE_CANDIDATE_ID = "duplicate_candidate_id"
    DUPLICATE_CLAIM_ID = "duplicate_claim_id"
    DUPLICATE_REFERENCE_ID = "duplicate_reference_id"
    OUTPUT_BOUNDS_EXCEEDED = "output_bounds_exceeded"


class BootstrapExtractionError(ModelError):
    """Raised when bootstrap extraction fails closed (never ambiguity)."""

    def __init__(
        self,
        reason: BootstrapExtractionFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason


# ── Trusted request construction ──────────────────────────────────────────


def _validate_nonempty(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must be a non-empty string")
    return value


class BootstrapExtractionRequest(BaseModel):
    """Immutable, application-owned model-visible extraction request."""

    campaign_id: str
    input_fingerprint: Sha256Fingerprint
    batch_id: str
    context_text: str
    expected_source_refs: tuple[str, ...] = ()
    processor_version: str
    prompt_version: str
    extraction_schema_version: int = Field(ge=0)

    model_config = {"frozen": True, "extra": "forbid"}

    @field_validator("campaign_id", "batch_id", "processor_version", "prompt_version")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        return _validate_nonempty(value)

    @field_validator("context_text")
    @classmethod
    def _context_non_empty(cls, value: str) -> str:
        return _validate_nonempty(value)

    @field_validator("expected_source_refs")
    @classmethod
    def _refs_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("expected_source_refs must contain non-empty strings")
        return value


def build_bootstrap_extraction_request(
    projection: BootstrapInputProjection,
    batch: BootstrapBatch,
    *,
    processor_version: str,
    prompt_version: str,
    extraction_schema_version: int = BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
) -> BootstrapExtractionRequest:
    """Derive a trusted request for one prepared batch."""
    if extraction_schema_version != BOOTSTRAP_EXTRACTION_SCHEMA_VERSION:
        raise BootstrapExtractionError(
            BootstrapExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION,
            f"Extraction schema version {extraction_schema_version} is unsupported; "
            f"expected {BOOTSTRAP_EXTRACTION_SCHEMA_VERSION}",
        )
    if not batch.request_text.strip():
        raise BootstrapExtractionError(
            BootstrapExtractionFailureReason.INVALID_REQUEST,
            "Bootstrap batch text is empty; refusing to build an extraction request",
        )
    return BootstrapExtractionRequest(
        campaign_id=projection.campaign_id,
        input_fingerprint=projection.input_fingerprint,
        batch_id=batch.batch_id,
        context_text=batch.request_text,
        expected_source_refs=batch.source_refs,
        processor_version=processor_version,
        prompt_version=prompt_version,
        extraction_schema_version=extraction_schema_version,
    )


# ── Model protocol ────────────────────────────────────────────────────────


class BootstrapExtractionModel(Protocol):
    """Provider-neutral bootstrap structured-extraction boundary.

    Implementations expose no project/action tools and perform exactly one
    bounded structured extraction per call.  A deterministic fake can implement
    this protocol without any provider/framework dependency.
    """

    def extract(self, request: BootstrapExtractionRequest) -> BootstrapExtraction:
        """Perform one bounded structured extraction over ``request``."""
        ...


# ── Semantic validation ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ValidatedBootstrapExtraction:
    """Semantically accepted extraction (sanitized source references)."""

    extraction: BootstrapExtraction


def _normalize_source_refs(
    refs: Sequence[str], allowed: frozenset[str], owner: str
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref not in allowed:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.INVALID_SOURCE_REFERENCE,
                f"{owner} references source {ref!r} that is not present in the request",
            )
        if ref not in seen:
            seen.add(ref)
            result.append(ref)
    return tuple(result)


def _validate_total_size(extraction: BootstrapExtraction) -> None:
    total = 0
    for candidate in extraction.candidates:
        total += len(candidate.display_name)
        if candidate.summary is not None:
            total += len(candidate.summary)
        for attribute in candidate.attributes:
            total += len(attribute.key) + len(attribute.value)
        total += sum(len(ref) for ref in candidate.source_refs)
        if total > MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED,
                f"Extraction total text exceeds {MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS} characters",
            )
    for claim in extraction.claims:
        total += len(claim.text)
        total += sum(len(ref) for ref in claim.source_refs)
        for reference in claim.references:
            total += len(reference.text)
            total += sum(len(ref) for ref in reference.source_refs)
        if total > MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.OUTPUT_BOUNDS_EXCEEDED,
                f"Extraction total text exceeds {MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS} characters",
            )


def validate_bootstrap_extraction(
    extraction: BootstrapExtraction,
    request: BootstrapExtractionRequest,
) -> ValidatedBootstrapExtraction:
    """Semantically validate framework output against the trusted request.

    Runs **after** framework syntactic/structured-output validation.  Raises
    ``BootstrapExtractionError`` on any violation; never mutates the campaign.
    """
    if extraction.schema_version != BOOTSTRAP_EXTRACTION_SCHEMA_VERSION:
        raise BootstrapExtractionError(
            BootstrapExtractionFailureReason.UNSUPPORTED_SCHEMA_VERSION,
            f"Model returned extraction schema version {extraction.schema_version}; "
            f"expected {BOOTSTRAP_EXTRACTION_SCHEMA_VERSION}",
        )

    _validate_total_size(extraction)
    allowed = frozenset(request.expected_source_refs)

    seen_candidates: set[str] = set()
    seen_claims: set[str] = set()
    sanitized_candidates: list[BootstrapEntityCandidate] = []
    sanitized_claims: list[BootstrapClaim] = []

    for candidate in extraction.candidates:
        if candidate.candidate_id in seen_candidates:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.DUPLICATE_CANDIDATE_ID,
                f"Duplicate candidate_id {candidate.candidate_id!r}",
            )
        seen_candidates.add(candidate.candidate_id)
        sanitized_candidates.append(
            candidate.model_copy(
                update={
                    "source_refs": _normalize_source_refs(
                        candidate.source_refs,
                        allowed,
                        f"Candidate {candidate.candidate_id}",
                    )
                }
            )
        )

    seen_refs: set[str] = set()
    for claim in extraction.claims:
        if claim.claim_id in seen_claims:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.DUPLICATE_CLAIM_ID,
                f"Duplicate claim_id {claim.claim_id!r}",
            )
        seen_claims.add(claim.claim_id)

        sanitized_references: list[BootstrapEntityReference] = []
        for reference in claim.references:
            if reference.reference_id in seen_refs:
                raise BootstrapExtractionError(
                    BootstrapExtractionFailureReason.DUPLICATE_REFERENCE_ID,
                    f"Duplicate reference_id {reference.reference_id!r}",
                )
            seen_refs.add(reference.reference_id)
            sanitized_references.append(
                reference.model_copy(
                    update={
                        "source_refs": _normalize_source_refs(
                            reference.source_refs,
                            allowed,
                            f"Reference {reference.reference_id}",
                        )
                    }
                )
            )

        sanitized_claims.append(
            claim.model_copy(
                update={
                    "source_refs": _normalize_source_refs(
                        claim.source_refs,
                        allowed,
                        f"Claim {claim.claim_id}",
                    ),
                    "references": tuple(sanitized_references),
                }
            )
        )

    sanitized = extraction.model_copy(
        update={
            "candidates": tuple(sanitized_candidates),
            "claims": tuple(sanitized_claims),
        }
    )
    return ValidatedBootstrapExtraction(extraction=sanitized)


def run_bootstrap_extraction(
    model: BootstrapExtractionModel,
    request: BootstrapExtractionRequest,
) -> ValidatedBootstrapExtraction:
    """Run one bounded batch extraction and semantically validate its output."""
    extraction = model.extract(request)
    if not isinstance(extraction, BootstrapExtraction):
        raise BootstrapExtractionError(
            BootstrapExtractionFailureReason.INVALID_STRUCTURED_OUTPUT,
            f"Model returned an unexpected output type: {type(extraction).__name__}",
        )
    return validate_bootstrap_extraction(extraction, request)


# ── Deterministic batch merge ─────────────────────────────────────────────


def merge_bootstrap_extractions(
    extractions: Sequence[BootstrapExtraction],
) -> BootstrapExtraction:
    """Merge validated batch extractions in deterministic batch order.

    Candidate/claim/reference ids must be globally unique across batches; a
    collision fails closed rather than silently renaming model output.
    """
    candidates: list[BootstrapEntityCandidate] = []
    claims: list[BootstrapClaim] = []
    seen_candidates: set[str] = set()
    seen_claims: set[str] = set()
    seen_refs: set[str] = set()

    for extraction in extractions:
        for candidate in extraction.candidates:
            if candidate.candidate_id in seen_candidates:
                raise BootstrapExtractionError(
                    BootstrapExtractionFailureReason.DUPLICATE_CANDIDATE_ID,
                    f"Duplicate candidate_id {candidate.candidate_id!r} across batches",
                )
            seen_candidates.add(candidate.candidate_id)
            candidates.append(candidate)
        for claim in extraction.claims:
            if claim.claim_id in seen_claims:
                raise BootstrapExtractionError(
                    BootstrapExtractionFailureReason.DUPLICATE_CLAIM_ID,
                    f"Duplicate claim_id {claim.claim_id!r} across batches",
                )
            seen_claims.add(claim.claim_id)
            for reference in claim.references:
                if reference.reference_id in seen_refs:
                    raise BootstrapExtractionError(
                        BootstrapExtractionFailureReason.DUPLICATE_REFERENCE_ID,
                        f"Duplicate reference_id {reference.reference_id!r} across batches",
                    )
                seen_refs.add(reference.reference_id)
            claims.append(claim)

    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=tuple(candidates),
        claims=tuple(claims),
    )


__all__ = [
    "MAX_BOOTSTRAP_EXTRACTION_TOTAL_CHARS",
    "BootstrapExtractionError",
    "BootstrapExtractionFailureReason",
    "BootstrapExtractionModel",
    "BootstrapExtractionRequest",
    "ValidatedBootstrapExtraction",
    "build_bootstrap_extraction_request",
    "merge_bootstrap_extractions",
    "run_bootstrap_extraction",
    "validate_bootstrap_extraction",
]
