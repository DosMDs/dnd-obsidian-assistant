"""Foundational domain types for D&D Session Assistant.

This module defines the primitive value types used across the domain layer:

- EntityType: the kind of campaign entity (npc, location, quest, item).
- KnowledgeStatus: epistemic state of entity knowledge.
- Visibility: which actor can see the information.
- Provenance: how the information entered the system.
- EntityId: a stable, validated domain identifier.
- Revision: optimistic concurrency revision counter.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator, Field


class EntityType(StrEnum):
    """The kind of campaign entity.

    MVP values only: npc, location, quest, item.
    """

    NPC = "npc"
    LOCATION = "location"
    QUEST = "quest"
    ITEM = "item"


class KnowledgeStatus(StrEnum):
    """Epistemic state of entity knowledge.

    Represents how confident or well-sourced the information is.
    """

    CONFIRMED = "confirmed"
    REPORTED = "reported"
    RUMOR = "rumor"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class Visibility(StrEnum):
    """Which actor can see the information.

    Architecture-level visibility: player, dm, system.
    """

    PLAYER = "player"
    DM = "dm"
    SYSTEM = "system"


class Provenance(StrEnum):
    """How the information entered the system.

    Tracks the origin mechanism, not the specific provider/model name.
    """

    MANUAL = "manual"
    SESSION = "session"
    BOOTSTRAP = "bootstrap"
    IMPORT = "import"
    MODEL_INFERENCE = "model_inference"


# ── EntityId ──────────────────────────────────────────────────────────────


def _validate_entity_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("EntityId must be a string")
    if not value:
        raise ValueError("EntityId must not be empty")
    if value.strip() != value:
        raise ValueError("EntityId must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("EntityId must not contain non-printable characters")
    return value


EntityId = Annotated[
    str,
    BeforeValidator(_validate_entity_id),
    Field(
        description="A stable domain identifier independent of display name, filename and filesystem path",
    ),
]
"""A stable domain identifier.

EntityId is a validated string that:
- must not be empty;
- must not consist only of whitespace;
- must not have leading or trailing whitespace;
- must not contain non-printable characters;
- accepts printable Unicode characters;
- is independent of display name, filename, and filesystem path.

Usage in a Pydantic model::

    class MyModel(BaseModel):
        entity_id: EntityId
"""


# ── Revision ──────────────────────────────────────────────────────────────

Revision = Annotated[
    int,
    Field(
        ge=1,
        strict=True,
        description="Optimistic concurrency revision counter (integer >= 1)",
    ),
]
"""An optimistic concurrency revision counter.

- Must be an integer >= 1.
- Strict mode: ``True`` and ``False`` are rejected (Python bool is int).
- Coercion from strings (e.g. ``"1"``) is rejected.
"""
