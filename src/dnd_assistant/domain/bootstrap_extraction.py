"""S13-03 existing-campaign bootstrap structured-extraction domain schemas.

Defines the immutable, strict typed contract for the *untrusted* semantic
extraction produced by the bootstrap heavy model over already-discovered
existing-campaign source material.

This is deliberately **not** a ChangeSet and **not** a canonical campaign fact.
It represents what the model believes an existing campaign's source documents
describe, for later deterministic Python-owned binding and ChangeSet
production.  It therefore contains:

- no revision, no operation kind, no apply policy;
- no canonical ``EntityId`` at all: the model never emits, copies or selects a
  canonical identity, not even an optional one;
- mandatory per-item source references to the Python-supplied source tokens;
- bounded free text and bounded key/value attributes only.

Python-owned values (``campaign_id``, ``input_fingerprint``, processor/prompt
versions and the source-reference universe) are attached by the application
policy and are never requested from the model.

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

BOOTSTRAP_EXTRACTION_SCHEMA_VERSION: Final[int] = 1
"""Explicit bootstrap structured-extraction schema contract version.

Independent of the package version and of the semantic input fingerprint.  A
breaking contract change must introduce a new explicit value; it is never
implicitly tracked through package or fingerprint versions.
"""

# ── Project-owned structural bounds ───────────────────────────────────────
#
# Fail-closed ceilings declared on the schema itself, so a syntactically
# validated object can never be unbounded.  Cross-reference and total-size
# bounds are additionally enforced by the application semantic validator.

MAX_BOOTSTRAP_CANDIDATES: Final[int] = 500
MAX_BOOTSTRAP_CLAIMS: Final[int] = 500
MAX_BOOTSTRAP_REFERENCES_PER_CLAIM: Final[int] = 20
MAX_BOOTSTRAP_REFERENCES: Final[int] = 1000
MAX_SOURCE_REFS_PER_ITEM: Final[int] = 20
MAX_BOOTSTRAP_NAME_CHARS: Final[int] = 200
MAX_BOOTSTRAP_CLAIM_TEXT_CHARS: Final[int] = 4000
MAX_BOOTSTRAP_ATTRIBUTE_KEY_CHARS: Final[int] = 100
MAX_BOOTSTRAP_ATTRIBUTE_VALUE_CHARS: Final[int] = 500
MAX_BOOTSTRAP_CONFLICT_GROUP_CHARS: Final[int] = 200
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

BoundedSourceRef = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(
        max_length=MAX_REFERENCE_TOKEN_CHARS,
        description="Python-supplied source reference token present in the request",
    ),
]

BoundedName = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_BOOTSTRAP_NAME_CHARS, description="Bounded display name"),
]

BoundedClaimText = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_BOOTSTRAP_CLAIM_TEXT_CHARS, description="Bounded claim text"),
]

BoundedAttributeKey = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_BOOTSTRAP_ATTRIBUTE_KEY_CHARS),
]

BoundedAttributeValue = Annotated[
    str,
    BeforeValidator(_validate_nonempty_printable),
    Field(max_length=MAX_BOOTSTRAP_ATTRIBUTE_VALUE_CHARS),
]

OptionalConflictGroup = (
    Annotated[
        str,
        BeforeValidator(_validate_nonempty_printable),
        Field(max_length=MAX_BOOTSTRAP_CONFLICT_GROUP_CHARS),
    ]
    | None
)


# ── Untrusted semantic enum ───────────────────────────────────────────────


class BootstrapClaimKind(StrEnum):
    """Coarse semantic category of a bootstrap claim (untrusted hint)."""

    FACT = "fact"
    EVENT = "event"
    RELATIONSHIP = "relationship"
    OTHER = "other"


# ── Extraction models ─────────────────────────────────────────────────────


class BootstrapAttribute(BaseModel):
    """A bounded key/value attribute of a candidate new entity."""

    key: BoundedAttributeKey
    value: BoundedAttributeValue

    model_config = {"frozen": True, "extra": "forbid"}


class BootstrapEntityCandidate(BaseModel):
    """A candidate new campaign entity; never a canonical entity.

    Carries no final ``EntityId``, no canonical type authority beyond the MVP
    enum, no create operation and no revision.  Trusted identity allocation and
    duplicate prevention belong to the application mapping layer.
    """

    candidate_id: BoundedToken
    display_name: BoundedName
    entity_type: EntityType
    source_refs: tuple[BoundedSourceRef, ...] = Field(
        min_length=1,
        max_length=MAX_SOURCE_REFS_PER_ITEM,
    )
    attributes: tuple[BootstrapAttribute, ...] = Field(default=(), max_length=20)
    summary: BoundedClaimText | None = None

    model_config = {"frozen": True, "extra": "forbid"}


class BootstrapEntityReference(BaseModel):
    """A claim's reference to an entity by observed text and claimed type.

    The model never emits, copies or selects a canonical ``EntityId``.  Python
    binds ``text`` + ``entity_type`` deterministically against the recognized
    canonical projection; an unbound reference stays unresolved.
    """

    reference_id: BoundedToken
    text: BoundedName
    entity_type: EntityType
    source_refs: tuple[BoundedSourceRef, ...] = Field(
        min_length=1,
        max_length=MAX_SOURCE_REFS_PER_ITEM,
    )

    model_config = {"frozen": True, "extra": "forbid"}


class BootstrapClaim(BaseModel):
    """One source-bound semantic claim about the existing campaign."""

    claim_id: BoundedToken
    kind: BootstrapClaimKind = BootstrapClaimKind.OTHER
    text: BoundedClaimText
    source_refs: tuple[BoundedSourceRef, ...] = Field(
        min_length=1,
        max_length=MAX_SOURCE_REFS_PER_ITEM,
    )
    references: tuple[BootstrapEntityReference, ...] = Field(
        default=(),
        max_length=MAX_BOOTSTRAP_REFERENCES_PER_CLAIM,
    )
    conflict_group: OptionalConflictGroup = None
    """Untrusted grouping label: claims sharing a non-null group are treated by
    Python as mutually conflicting evidence and are never turned into
    canonical mutations."""

    model_config = {"frozen": True, "extra": "forbid"}


class BootstrapExtraction(BaseModel):
    """The complete untrusted structured extraction for one bootstrap batch.

    ``extra="forbid"`` structurally prevents any ready-to-apply ChangeSet
    operation, revision, filesystem path or canonical ``EntityId`` from
    entering the contract.
    """

    schema_version: int = Field(ge=0)
    candidates: tuple[BootstrapEntityCandidate, ...] = Field(
        default=(),
        max_length=MAX_BOOTSTRAP_CANDIDATES,
    )
    claims: tuple[BootstrapClaim, ...] = Field(default=(), max_length=MAX_BOOTSTRAP_CLAIMS)

    model_config = {"frozen": True, "extra": "forbid"}


__all__ = [
    "BOOTSTRAP_EXTRACTION_SCHEMA_VERSION",
    "MAX_BOOTSTRAP_ATTRIBUTE_KEY_CHARS",
    "MAX_BOOTSTRAP_ATTRIBUTE_VALUE_CHARS",
    "MAX_BOOTSTRAP_CANDIDATES",
    "MAX_BOOTSTRAP_CLAIMS",
    "MAX_BOOTSTRAP_CLAIM_TEXT_CHARS",
    "MAX_BOOTSTRAP_CONFLICT_GROUP_CHARS",
    "MAX_BOOTSTRAP_NAME_CHARS",
    "MAX_BOOTSTRAP_REFERENCES",
    "MAX_BOOTSTRAP_REFERENCES_PER_CLAIM",
    "MAX_REFERENCE_TOKEN_CHARS",
    "MAX_SOURCE_REFS_PER_ITEM",
    "BootstrapAttribute",
    "BootstrapClaim",
    "BootstrapClaimKind",
    "BootstrapEntityCandidate",
    "BootstrapEntityReference",
    "BootstrapExtraction",
    "BoundedAttributeKey",
    "BoundedAttributeValue",
    "BoundedClaimText",
    "BoundedName",
    "BoundedSourceRef",
    "BoundedToken",
    "OptionalConflictGroup",
]
