"""TimelineEvent domain schema.

Defines the canonical TimelineEvent model representing a noteworthy
occurrence on the campaign timeline.  Temporal precision is expressed
through TemporalCertainty and validated world_tick fields rather than
calendar dates (which belong to Stage 4).

This module belongs to the domain layer and must not import from:
    storage, models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from dnd_assistant.domain.types import EntityId, Revision, Visibility

# ── TemporalCertainty ───────────────────────────────────────────────────────


class TemporalCertainty(StrEnum):
    """Temporal/date precision for a TimelineEvent.

    Describes how precisely the event's timing is known, independent of
    epistemic knowledge status (confirmed/rumor etc.).
    """

    EXACT = "exact"
    APPROXIMATE = "approximate"
    RANGE = "range"
    UNKNOWN = "unknown"


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


def _validate_optional_printable_nonempty(value: str | None) -> str | None:
    """Validate an optional non-empty printable string.

    When present: strict string, non-empty, no surrounding whitespace,
    printable, control characters rejected.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("value must be a string or None")
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

OptionalPrintableNonEmptyStr = Annotated[
    str | None,
    BeforeValidator(_validate_optional_printable_nonempty),
    Field(
        default=None,
        description="Optional non-empty printable string",
    ),
]


# ── TimelineEvent model ─────────────────────────────────────────────────────


class TimelineEvent(BaseModel):
    """Canonical TimelineEvent schema.

    Represents a noteworthy occurrence on the campaign timeline with
    validated temporal precision expressed through world_tick fields
    and TemporalCertainty.

    Calendar arithmetic, GameDate conversion and CalendarService logic
    belong to Stage 4 and are not part of this schema.
    """

    schema_version: Literal[1] = 1
    """Schema version for migration detection.  Currently always 1."""

    id: EntityId
    """Stable domain identifier, independent of display name and filename."""

    type: Literal["timeline_event"] = "timeline_event"
    """Fixed entity type discriminator for Vault frontmatter."""

    name: PrintableNonEmptyStr
    """Human-readable event name."""

    status: PrintableNonEmptyStr
    """Event lifecycle status (e.g. ongoing, resolved, historical).

    Vocabulary is not yet fixed.  Base TimelineEvent validates only
    that the value is a non-empty printable string.
    """

    certainty: TemporalCertainty
    """Temporal precision of this event's timing."""

    importance: PrintableNonEmptyStr
    """Event importance/priority (e.g. major, minor, background).

    Vocabulary is not yet fixed.  Base TimelineEvent validates only
    that the value is a non-empty printable string.
    """

    world_tick: int | None = Field(default=None, strict=True)
    """Exact game-world tick when the event occurred.

    Required when certainty is ``exact``.  Must be None otherwise.
    """

    world_tick_min: int | None = Field(default=None, strict=True)
    """Earliest possible game-world tick (inclusive).

    Required when certainty is ``approximate`` or ``range``.
    Must be None when certainty is ``exact`` or ``unknown``.
    """

    world_tick_max: int | None = Field(default=None, strict=True)
    """Latest possible game-world tick (inclusive).

    Required when certainty is ``approximate`` or ``range``.
    Must be None when certainty is ``exact`` or ``unknown``.
    """

    location: OptionalPrintableNonEmptyStr = None
    """Optional location reference associated with this event."""

    visibility: Visibility
    """Which actor can see this event's information."""

    revision: Revision
    """Optimistic concurrency revision counter (integer >= 1)."""

    # ── Model-level validation ──────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_temporal_consistency(self) -> TimelineEvent:
        """Validate temporal field combinations against certainty."""
        certainty = self.certainty
        tick = self.world_tick
        tick_min = self.world_tick_min
        tick_max = self.world_tick_max

        if certainty == TemporalCertainty.EXACT:
            if tick is None:
                raise ValueError("world_tick is required when certainty is 'exact'")
            if tick_min is not None or tick_max is not None:
                raise ValueError(
                    "world_tick_min and world_tick_max must be None when certainty is 'exact'"
                )

        elif certainty == TemporalCertainty.APPROXIMATE:
            if tick is not None:
                raise ValueError("world_tick must be None when certainty is 'approximate'")
            if tick_min is None or tick_max is None:
                raise ValueError(
                    "world_tick_min and world_tick_max are required when certainty is 'approximate'"
                )
            if tick_min > tick_max:
                raise ValueError(
                    f"world_tick_min ({tick_min}) must not exceed world_tick_max ({tick_max})"
                )

        elif certainty == TemporalCertainty.RANGE:
            if tick is not None:
                raise ValueError("world_tick must be None when certainty is 'range'")
            if tick_min is None or tick_max is None:
                raise ValueError(
                    "world_tick_min and world_tick_max are required when certainty is 'range'"
                )
            if tick_min > tick_max:
                raise ValueError(
                    f"world_tick_min ({tick_min}) must not exceed world_tick_max ({tick_max})"
                )

        elif certainty == TemporalCertainty.UNKNOWN:
            if tick is not None or tick_min is not None or tick_max is not None:
                raise ValueError(
                    "world_tick, world_tick_min and world_tick_max "
                    "must all be None when certainty is 'unknown'"
                )

        return self

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }
    """``extra="forbid"``: unknown fields are rejected.

    This is the strictest policy appropriate for validating the
    TimelineEvent schema itself.  It does not define Stage 3
    Vault-repository parsing behaviour, where unknown YAML frontmatter
    keys may need different treatment.
    """
