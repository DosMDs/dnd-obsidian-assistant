"""Session domain schema.

Defines the canonical Session model representing a single game session.
Sessions track real-world timestamps, game-world ticks, processing state,
and optimistic concurrency revision.

This module belongs to the domain layer and must not import from:
    storage, models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field
from pydantic.types import AwareDatetime

from dnd_assistant.domain.types import Revision

# ── Field-level validators ────────────────────────────────────────────────


def _validate_session_id(value: str) -> str:
    """Validate a session identifier string.

    Requirements:
    - strict string
    - non-empty
    - no surrounding whitespace
    - printable Unicode allowed
    - control/non-printable characters rejected
    """
    if not isinstance(value, str):
        raise ValueError("id must be a string")
    if not value:
        raise ValueError("id must not be empty")
    if value.strip() != value:
        raise ValueError("id must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("id must not contain non-printable characters")
    return value


def _validate_session_status(value: str) -> str:
    """Validate a session status string.

    Requirements:
    - strict string
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


def _validate_processed_model_profile(value: str | None) -> str | None:
    """Validate an optional processed-model-profile string.

    When present: strict string, non-empty, no surrounding whitespace,
    printable, control characters rejected.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("processed_model_profile must be a string or None")
    if not value:
        raise ValueError("processed_model_profile must not be empty")
    if value.strip() != value:
        raise ValueError("processed_model_profile must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("processed_model_profile must not contain non-printable characters")
    return value


# ── Annotated field types ─────────────────────────────────────────────────


SessionId = Annotated[
    str,
    BeforeValidator(_validate_session_id),
    Field(description="Session identifier (e.g. S014)"),
]

SessionStatusStr = Annotated[
    str,
    BeforeValidator(_validate_session_status),
    Field(description="Session lifecycle status (e.g. completed, active)"),
]

ProcessedModelProfile = Annotated[
    str | None,
    BeforeValidator(_validate_processed_model_profile),
    Field(
        default=None,
        description="Model profile used for post-session processing (e.g. post_session)",
    ),
]


# ── Session model ─────────────────────────────────────────────────────────


class Session(BaseModel):
    """Canonical Session schema.

    Represents a single game session with real-world timestamps,
    game-world tick range, processing state and optimistic concurrency
    revision.
    """

    schema_version: Literal[1] = 1
    """Schema version for migration detection.  Currently always 1."""

    id: SessionId
    """Session identifier (e.g. S014)."""

    type: Literal["session"] = "session"
    """Fixed entity type discriminator for Vault frontmatter."""

    status: SessionStatusStr
    """Session lifecycle status.

    Vocabulary is not yet fully fixed (e.g. ``"completed"``, ``"active"``).
    Base Session validates only that the value is a non-empty printable
    string.
    """

    real_started_at: AwareDatetime
    """Real-world timestamp when the session started (timezone-aware)."""

    real_finished_at: AwareDatetime | None = None
    """Real-world timestamp when the session finished.

    ``None`` when the session is still active / unfinished.
    """

    world_tick_start: int = Field(strict=True)
    """Game-world tick at session start (strict integer, no coercion)."""

    world_tick_end: int | None = Field(default=None, strict=True)
    """Game-world tick at session end.

    ``None`` when the session is still active / unfinished.
    """

    processed: bool = Field(default=False, strict=True)
    """Whether post-session processing has been completed.

    Strict boolean: string coercion (``"true"``, ``"false"``) rejected.
    """

    processed_model_profile: ProcessedModelProfile = None
    """Model profile used for post-session processing.

    ``None`` when not yet processed or profile not recorded.
    """

    revision: Revision
    """Optimistic concurrency revision counter (integer >= 1)."""

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }
    """``extra="forbid"``: unknown fields are rejected.

    This is the strictest policy appropriate for validating the Session
    schema itself.  It does not define Stage 3 Vault-repository parsing
    behaviour, where unknown YAML frontmatter keys may need different
    treatment.
    """
