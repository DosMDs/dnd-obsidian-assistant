"""Base Entity domain model.

Defines the canonical common Entity schema shared by all campaign
entity types (NPC, location, quest, item).

Type-specific fields (e.g. current_location, faction, priority) are
deliberately excluded from this base model. They belong in specialised
sub-models or repository-level parsing logic in a later stage.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field
from pydantic.types import AwareDatetime

from dnd_assistant.domain.types import (
    EntityId,
    EntityType,
    KnowledgeStatus,
    Revision,
    Visibility,
)

# ── Field-level validators ────────────────────────────────────────────────


def _validate_name(value: str) -> str:
    """Validate a human-readable display name.

    Requirements:
    - strict string
    - non-empty
    - whitespace-only rejected
    - leading/trailing whitespace rejected
    - printable Unicode allowed
    - control/non-printable characters rejected
    """
    if not isinstance(value, str):
        raise ValueError("name must be a string")
    if not value:
        raise ValueError("name must not be empty")
    if value.strip() != value:
        raise ValueError("name must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("name must not contain non-printable characters")
    return value


def _validate_status(value: str) -> str:
    """Validate a status string.

    Requirements:
    - non-empty
    - no surrounding whitespace
    - printable
    - Unicode-compatible
    """
    if not isinstance(value, str):
        raise ValueError("status must be a string")
    if not value:
        raise ValueError("status must not be empty")
    if value.strip() != value:
        raise ValueError("status must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("status must not contain non-printable characters")
    return value


def _validate_session_ref(value: str | None) -> str | None:
    """Validate an optional session reference string.

    When present: non-empty, no surrounding whitespace, printable.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("session reference must be a string or None")
    if not value:
        raise ValueError("session reference must not be empty")
    if value.strip() != value:
        raise ValueError("session reference must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("session reference must not contain non-printable characters")
    return value


def _validate_tag(value: str) -> str:
    """Validate a single tag string.

    Requirements:
    - non-empty
    - not whitespace-only
    - no surrounding whitespace
    - printable
    - Unicode-compatible
    """
    if not isinstance(value, str):
        raise ValueError("each tag must be a string")
    if not value:
        raise ValueError("tag must not be empty")
    if value.strip() != value:
        raise ValueError("tag must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("tag must not contain non-printable characters")
    return value


# ── Annotated field types ─────────────────────────────────────────────────

NameStr = Annotated[
    str,
    BeforeValidator(_validate_name),
    Field(description="Human-readable display name"),
]

StatusStr = Annotated[
    str,
    BeforeValidator(_validate_status),
    Field(description="Entity lifecycle status (type-specific vocabulary)"),
]

SessionRef = Annotated[
    str | None,
    BeforeValidator(_validate_session_ref),
    Field(
        default=None,
        description="Optional session identifier (e.g. S007, S014)",
    ),
]

TagStr = Annotated[
    str,
    BeforeValidator(_validate_tag),
    Field(description="A single tag string"),
]


# ── Entity model ──────────────────────────────────────────────────────────


class Entity(BaseModel):
    """Canonical common Entity schema.

    Fields shared by all campaign entity types.  Type-specific fields
    are not part of this base model.
    """

    schema_version: Literal[1] = 1
    """Schema version for migration detection.  Currently always 1."""

    id: EntityId
    """Stable domain identifier, independent of display name and filename."""

    type: EntityType
    """The kind of campaign entity (npc, location, quest, item)."""

    name: NameStr
    """Human-readable display name."""

    status: StatusStr
    """Entity lifecycle status.

    Vocabulary is type-specific (e.g. ``"alive"`` for NPC,
    ``"active"`` for quest).  Base Entity validates only that the
    value is a non-empty printable string.
    """

    visibility: Visibility
    """Which actor can see this entity's information."""

    knowledge_status: KnowledgeStatus
    """Epistemic state: how confident or well-sourced the information is."""

    created_session: SessionRef = None
    """Session in which this entity was first observed."""

    last_seen_session: SessionRef = None
    """Most recent session in which this entity was observed."""

    created_at: AwareDatetime
    """Real-world timestamp when this entity record was created."""

    updated_at: AwareDatetime
    """Real-world timestamp when this entity record was last updated."""

    revision: Revision
    """Optimistic concurrency revision counter (integer >= 1)."""

    tags: list[TagStr] = Field(default_factory=list)
    """Arbitrary string tags for classification/filtering.

    Order is preserved.  Duplicates are not automatically removed.
    """

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }
    """``extra="forbid"``: unknown fields are rejected.

    This is the strictest policy appropriate for validating the Base
    Entity schema itself.  It does not define Stage 3 Vault-repository
    parsing behaviour, where unknown YAML frontmatter keys may need
    different treatment.
    """
