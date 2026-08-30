"""CampaignState domain schema.

Defines the canonical CampaignState model representing a compact snapshot
of what is currently relevant to the campaign/player context.

This module belongs to the domain layer and must not import from:
    storage, models, retrieval, tools, application, cli, ollama

CampaignState primarily contains **references** (EntityId) rather than
duplicating full Entity, Quest, NPC, Location, or TimelineEvent objects.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from dnd_assistant.domain.types import EntityId, Revision

# ── Field-level validators ──────────────────────────────────────────────────


def _validate_printable_nonempty(value: str) -> str:
    """Validate a non-empty printable string.

    Requirements:
    - strict string
    - non-empty
    - whitespace-only rejected
    - leading/trailing whitespace rejected
    - printable Unicode allowed
    - control/non-printable characters rejected
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


# ── Annotated field types ───────────────────────────────────────────────────

PrintableNonEmptyStr = Annotated[
    str,
    BeforeValidator(_validate_printable_nonempty),
    Field(description="Non-empty printable string"),
]


# ── CampaignState model ─────────────────────────────────────────────────────


class CampaignState(BaseModel):
    """Compact snapshot of currently relevant campaign/player context.

    CampaignState represents what is currently relevant to the campaign
    or player context.  Detailed canonical data remains in Entity /
    TimelineEvent records.  This schema therefore primarily contains
    **references** (EntityId), not duplicated full objects.

    Calendar arithmetic, GameDate conversion, CampaignState persistence,
    state generation/update algorithms, ChangeSet application, and
    State/*.md handling belong to later stages and are not part of this
    schema.
    """

    schema_version: Literal[1] = 1
    """Schema version for migration detection.  Currently always 1."""

    type: Literal["campaign_state"] = "campaign_state"
    """Fixed entity type discriminator for Vault frontmatter."""

    current_location: EntityId | None = None
    """Optional reference to the canonical location Entity.

    Do not embed a Location model.  EntityType validation belongs to
    repository-aware layers.
    """

    active_quests: list[EntityId] = Field(default_factory=list)
    """References to canonical Quest entities.

    Do not embed Quest state or invent a Quest subtype/schema here.
    """

    party_goals: list[PrintableNonEmptyStr] = Field(default_factory=list)
    """Compact human-readable current objectives.

    Strict non-empty printable strings.  Cyrillic/Unicode supported.
    """

    important_npcs: list[EntityId] = Field(default_factory=list)
    """References to canonical NPC entities.

    NPC details/status remain canonical on their Entity records.
    """

    upcoming_deadlines: list[EntityId] = Field(default_factory=list)
    """References to canonical TimelineEvent records.

    Do not embed TimelineEvent models.  Calendar arithmetic to determine
    whether an event is actually upcoming belongs to later stages.
    """

    unresolved_threads: list[PrintableNonEmptyStr] = Field(default_factory=list)
    """Compact human-readable unresolved story-thread descriptions.

    Uses strings because ``thread`` is not an MVP EntityType and no
    Thread domain schema exists in Stage 2.  Do not introduce ThreadId
    or Thread schema.
    """

    revision: Revision
    """Optimistic concurrency revision counter (integer >= 1)."""

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }
    """``extra="forbid"``: unknown fields are rejected.

    This is the strictest policy appropriate for validating the
    CampaignState schema itself.  It does not define Stage 3 Vault-
    repository parsing behaviour, where unknown YAML frontmatter keys
    may need different treatment.
    """
