"""Foundational domain types for D&D Session Assistant.

This module defines the primitive value types used across the domain layer:

- EntityType: the kind of campaign entity (npc, location, quest, item).
- KnowledgeStatus: epistemic state of entity knowledge.
- Visibility: which actor can see the information.
- Provenance: how the information entered the system.
- EntityId: a stable, validated domain identifier.
- Revision: optimistic concurrency revision counter.
- Sha256Fingerprint: validated self-describing SHA-256 hash value.
- RelativeArtifactPath: validated logical relative artifact path.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


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


def make_revision(value: object) -> Revision:
    """Validate a ``Revision`` value.

    ``Revision`` is an ``Annotated`` alias and therefore not directly
    callable.  This domain-owned constructor preserves the canonical
    validation semantics (strict ``int`` >= 1, ``bool`` rejected) so that
    callers can construct a typed revision without repeating the rules.
    """
    if isinstance(value, bool):
        raise ValueError("Revision must not be a bool")
    if not isinstance(value, int):
        raise ValueError(f"Revision must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"Revision must be >= 1, got {value}")
    return value


# ── Sha256Fingerprint ─────────────────────────────────────────────────────

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class Sha256Fingerprint(BaseModel):
    """Self-describing SHA-256 content/input hash.

    Generic foundational value type shared across derived-canonicity
    boundaries (ChangeSet proposal digests, post-session prepared-input
    fingerprints and Stage-12 source-snapshot identity).  It contains no
    filesystem path and no provider/model data.
    """

    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=_DIGEST_PATTERN)

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── RelativeArtifactPath ──────────────────────────────────────────────────


def _validate_logical_relative_path(value: str) -> str:
    """Validate a logical relative artifact path.

    This is a *logical* identifier used in durable provenance/inventory data,
    not a filesystem path.  Absolute paths, backslashes and parent-directory
    traversal are rejected.  The value carries no filesystem authority.
    """
    if not isinstance(value, str):
        raise ValueError("relative path must be a string")
    if not value:
        raise ValueError("relative path must not be empty")
    if value.strip() != value:
        raise ValueError("relative path must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("relative path must not contain non-printable characters")
    if value.startswith("/"):
        raise ValueError("relative path must not be absolute")
    if "\\" in value:
        raise ValueError("relative path must use '/' separators only")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("relative path must not contain empty, '.', or '..' segments")
    return value


RelativeArtifactPath = Annotated[
    str,
    BeforeValidator(_validate_logical_relative_path),
    Field(description="Logical relative artifact path (no traversal/absolute)"),
]
"""A validated logical relative artifact path.

It is *not* a filesystem path: absolute paths, backslashes and parent-directory
traversal are rejected, and it carries no filesystem authority.
"""
