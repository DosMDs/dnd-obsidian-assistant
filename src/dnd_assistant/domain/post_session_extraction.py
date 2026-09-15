"""Stage-11 structured extraction domain schemas (S11-03).

Defines the immutable, strict typed contract for the *untrusted* semantic
extraction produced by the heavy post-session model.

This is deliberately **not** a ChangeSet and **not** a canonical campaign
fact.  It is a representation of what the model believes happened, suitable
for later deterministic entity binding (S11-05) and Summary/Recap rendering
(S11-04).  It therefore contains:

- no revision, no operation kind, no apply policy;
- no canonical ``EntityId`` for newly discovered entities;
- untrusted visibility / knowledge *hints* only;
- mandatory per-claim/mention/candidate evidence event references.

Python-owned values (``session_ref``, ``input_fingerprint``, processor/prompt
versions) are attached by the application policy and are never requested from
the model.

This module belongs to the domain layer and must not import from:
    storage, application, models, tools, retrieval, cli, ollama, pydantic_ai,
    pathlib, os, hashlib
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, BeforeValidator, Field

from dnd_assistant.domain.types import EntityType

# ── Schema version ────────────────────────────────────────────────────────

POST_SESSION_EXTRACTION_SCHEMA_VERSION: Final[int] = 1
"""Explicit structured-extraction schema contract version.

Independent of the package version and of ``PreparedInputIdentity`` schema.
A breaking contract change must introduce a new explicit value; it is never
implicitly tracked through package or prepared-input versions.
"""

# ── Project-owned structural bounds ───────────────────────────────────────
#
# Fail-closed ceilings declared on the schema itself, so a syntactically
# validated object can never be unbounded.  Cross-reference and total-size
# bounds are additionally enforced by the application semantic validator.

MAX_CLAIMS: Final[int] = 200
MAX_CLAIM_TEXT_CHARS: Final[int] = 4000
MAX_CLAIM_EVIDENCE_REFS: Final[int] = 20
MAX_ENTITY_MENTIONS_PER_CLAIM: Final[int] = 20
MAX_ENTITY_MENTIONS: Final[int] = 400
MAX_ENTITY_CANDIDATES: Final[int] = 100
MAX_CANDIDATE_NAME_CHARS: Final[int] = 200
MAX_CANDIDATE_ATTRIBUTES: Final[int] = 20
MAX_CANDIDATE_ATTRIBUTE_KEY_CHARS: Final[int] = 100
MAX_CANDIDATE_ATTRIBUTE_VALUE_CHARS: Final[int] = 500
MAX_REFERENCE_TOKEN_CHARS: Final[int] = 200


# ── String validators ─────────────────────────────────────────────────────


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


# ── Annotated bounded value types ─────────────────────────────────────────

BoundedToken = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_REFERENCE_TOKEN_CHARS, description="Bounded non-empty token"),
]

# Constrain the string branch, then union with ``None``.  Applying
# ``max_length`` to the ``str | None`` union itself makes an explicit JSON
# ``null`` fail structured validation, which is incorrect for an optional
# model-output field.
OptionalBoundedToken = BoundedToken | None

BoundedClaimText = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_CLAIM_TEXT_CHARS, description="Bounded claim text"),
]

BoundedName = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_CANDIDATE_NAME_CHARS, description="Bounded display name"),
]

BoundedAttributeKey = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_CANDIDATE_ATTRIBUTE_KEY_CHARS),
]

BoundedAttributeValue = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_CANDIDATE_ATTRIBUTE_VALUE_CHARS),
]

# ── Untrusted hint enums ──────────────────────────────────────────────────


class ExtractionVisibilityHint(StrEnum):
    """Model-proposed visibility classification (untrusted hint).

    Distinct from canonical ``Visibility``.  Python never treats this as
    authoritative and it never overrides canonical entity visibility.
    """

    PLAYER = "player"
    DM = "dm"
    UNCERTAIN = "uncertain"


class ExtractionKnowledgeHint(StrEnum):
    """Model-proposed knowledge/confidence classification (untrusted hint).

    Deliberately distinct from canonical ``KnowledgeStatus``; the two are
    never interchangeable.
    """

    CONFIRMED = "confirmed"
    REPORTED = "reported"
    RUMOR = "rumor"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"


class ClaimKind(StrEnum):
    """Coarse semantic category of a claim (untrusted hint for S11-05)."""

    EVENT = "event"
    FACT = "fact"
    RELATIONSHIP = "relationship"
    OTHER = "other"


# ── Extraction models ─────────────────────────────────────────────────────


class ExtractedAttribute(BaseModel):
    """A bounded key/value attribute of a new-entity candidate."""

    key: BoundedAttributeKey
    value: BoundedAttributeValue

    model_config = {"frozen": True, "extra": "forbid"}


class ExtractedEntityMention(BaseModel):
    """A claim's reference to an entity.

    ``candidate_entity_id`` is a raw, untrusted string.  It is never treated
    as canonical unless Python validates it against the prepared-input entity
    bindings (existence + canonical type match).
    """

    mention_id: BoundedToken
    text: BoundedName
    entity_type: EntityType
    candidate_entity_id: OptionalBoundedToken = None
    evidence_event_ids: tuple[BoundedToken, ...] = Field(
        min_length=1,
        max_length=MAX_CLAIM_EVIDENCE_REFS,
    )

    model_config = {"frozen": True, "extra": "forbid"}


class ExtractedEntityCandidate(BaseModel):
    """A candidate new entity; never a canonical entity.

    Carries no final ``EntityId``, no create operation and no revision.  The
    trusted ID allocation and duplicate prevention belong to S11-05.
    """

    candidate_id: BoundedToken
    display_name: BoundedName
    entity_type: EntityType
    evidence_event_ids: tuple[BoundedToken, ...] = Field(
        min_length=1,
        max_length=MAX_CLAIM_EVIDENCE_REFS,
    )
    attributes: tuple[ExtractedAttribute, ...] = Field(
        default=(),
        max_length=MAX_CANDIDATE_ATTRIBUTES,
    )
    summary: BoundedClaimText | None = None

    model_config = {"frozen": True, "extra": "forbid"}


class ExtractedClaim(BaseModel):
    """One evidence-bound semantic claim about the session."""

    claim_id: BoundedToken
    kind: ClaimKind = ClaimKind.OTHER
    text: BoundedClaimText
    evidence_event_ids: tuple[BoundedToken, ...] = Field(
        min_length=1,
        max_length=MAX_CLAIM_EVIDENCE_REFS,
    )
    entity_mentions: tuple[ExtractedEntityMention, ...] = Field(
        default=(),
        max_length=MAX_ENTITY_MENTIONS_PER_CLAIM,
    )
    visibility_hint: ExtractionVisibilityHint = ExtractionVisibilityHint.UNCERTAIN
    knowledge_hint: ExtractionKnowledgeHint = ExtractionKnowledgeHint.UNCERTAIN

    model_config = {"frozen": True, "extra": "forbid"}


class PostSessionExtraction(BaseModel):
    """The complete untrusted structured extraction for one session.

    ``extra="forbid"`` structurally prevents any ready-to-apply ChangeSet
    operation or revision field from entering the contract.
    """

    schema_version: int = Field(ge=0)
    claims: tuple[ExtractedClaim, ...] = Field(default=(), max_length=MAX_CLAIMS)
    entity_candidates: tuple[ExtractedEntityCandidate, ...] = Field(
        default=(),
        max_length=MAX_ENTITY_CANDIDATES,
    )

    model_config = {"frozen": True, "extra": "forbid"}


__all__ = [
    "BoundedAttributeKey",
    "BoundedAttributeValue",
    "BoundedClaimText",
    "BoundedName",
    "BoundedToken",
    "ClaimKind",
    "ExtractedAttribute",
    "ExtractedClaim",
    "ExtractedEntityCandidate",
    "ExtractedEntityMention",
    "ExtractionKnowledgeHint",
    "ExtractionVisibilityHint",
    "MAX_CANDIDATE_ATTRIBUTES",
    "MAX_CANDIDATE_ATTRIBUTE_KEY_CHARS",
    "MAX_CANDIDATE_ATTRIBUTE_VALUE_CHARS",
    "MAX_CANDIDATE_NAME_CHARS",
    "MAX_CLAIMS",
    "MAX_CLAIM_EVIDENCE_REFS",
    "MAX_CLAIM_TEXT_CHARS",
    "MAX_ENTITY_CANDIDATES",
    "MAX_ENTITY_MENTIONS",
    "MAX_ENTITY_MENTIONS_PER_CLAIM",
    "MAX_REFERENCE_TOKEN_CHARS",
    "POST_SESSION_EXTRACTION_SCHEMA_VERSION",
    "PostSessionExtraction",
]
