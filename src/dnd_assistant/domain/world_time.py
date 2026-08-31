"""CurrentWorldTime domain schema.

Defines the canonical typed representation of the campaign's persisted
current game time.

This module belongs to the domain layer and must not import from:
    storage, models, retrieval, tools, application, cli, ollama

``CurrentWorldTime`` is a strict immutable Pydantic model representing
the persisted current world tick with optimistic concurrency revision.
It does NOT own calendar arithmetic — that remains in ``CalendarService``
(ADR-0003, ADR-0004).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.types import Revision

# ── CurrentWorldTime ─────────────────────────────────────────────────────────


class CurrentWorldTime(BaseModel):
    """Canonical persisted current game time.

    This model represents the canonical current-world-time state as
    persisted in the Vault.  It stores only the ``WorldTick`` scalar;
    ``GameDate`` is always derived through ``CalendarService`` arithmetic.

    The model is immutable (``frozen=True``) and rejects unknown fields
    (``extra="forbid"``).

    Attributes:
        schema_version: Schema version for migration detection (always 1).
        type: Fixed discriminator ``"world_time"``.
        current_world_tick: The canonical current world tick (signed int
            minutes relative to campaign epoch).
        revision: Optimistic concurrency revision counter (integer >= 1).
    """

    schema_version: Literal[1] = 1
    type: Literal["world_time"] = "world_time"
    current_world_tick: WorldTick
    revision: Revision

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }
