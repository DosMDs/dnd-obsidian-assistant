"""Canonical retrieval-layer types for search and entity resolution.

This module defines the public contracts for the retrieval layer:

- ``MatchKind`` — provenance of how a search hit was obtained.
- ``SearchQuery`` — a typed retrieval query with optional filters.
- ``SearchHit`` — a single search result candidate.
- ``ResolutionOutcome`` — the explicit result of entity resolution.
- ``Resolved`` — a uniquely resolved entity.
- ``Ambiguous`` — multiple candidates could match.
- ``NotFound`` — no candidate matched.

These types belong to the retrieval layer and must not depend on:
    models, tools, application, cli, session runtime, Ollama
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from dnd_assistant.domain.types import EntityId, EntityType

# ── Match provenance ────────────────────────────────────────────────────────


class MatchKind(StrEnum):
    """How a search hit was obtained.

    Values are ordered by retrieval precedence:
    1. ``EXACT_ID`` — matched by stable ``EntityId``.
    2. ``EXACT_NAME`` — matched by canonical display name.
    3. ``EXACT_ALIAS`` — matched by an alias from frontmatter.
    4. ``FUZZY_NAME`` — matched by fuzzy/approximate name comparison.
    5. ``FTS`` — matched by SQLite FTS5 lexical search.

    This ordering is meaningful for deterministic candidate ranking:
    a more specific match kind should rank above a less specific one,
    regardless of the raw score/rank within each category.
    """

    EXACT_ID = "exact_id"
    EXACT_NAME = "exact_name"
    EXACT_ALIAS = "exact_alias"
    FUZZY_NAME = "fuzzy_name"
    FTS = "fts"


# ── Search query ────────────────────────────────────────────────────────────


def _validate_search_query(value: str) -> str:
    """Validate a search query string.

    Requirements:
    - strict string
    - non-empty after stripping (whitespace-only rejected)
    - printable Unicode allowed
    - control/non-printable characters rejected
    """
    if not isinstance(value, str):
        raise ValueError("query must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("query must not be empty or whitespace-only")
    if not value.isprintable():
        raise ValueError("query must not contain non-printable characters")
    return value


SearchQueryStr = Annotated[
    str,
    BeforeValidator(_validate_search_query),
    Field(description="Search query string (non-empty, printable)"),
]


class SearchQuery(BaseModel):
    """A typed retrieval query.

    The ``text`` field is the primary search input.  Optional
    ``entity_types`` filtering is supported for MVP entity types.

    The query is validated: empty, whitespace-only, and non-printable
    strings are rejected.

    Note:
        The ``entity_types`` filter is optional.  When ``None`` or empty,
        all entity types are searched.  When populated, only the specified
        types are included.
    """

    text: SearchQueryStr
    """The search text (non-empty, printable)."""

    entity_types: set[EntityType] | None = None
    """Optional filter by entity type(s).  ``None`` means no type filter."""

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }


# ── Search hit ──────────────────────────────────────────────────────────────


class SearchHit(BaseModel):
    """A single search result candidate.

    Each hit carries the matched entity's stable ``EntityId``,
    the ``MatchKind`` indicating how it was found, and an optional
    ``score`` whose semantics depend on ``match_kind``:

    - ``EXACT_ID``, ``EXACT_NAME``, ``EXACT_ALIAS``: score is always ``None``
      (exact matches have no meaningful ranking score).
    - ``FUZZY_NAME``: score is the RapidFuzz similarity ratio (0.0–100.0).
    - ``FTS``: score is the SQLite FTS5 rank (negative float, closer to 0
      means better match).

    Scores from different ``MatchKind`` values are **not directly
    comparable**.  Candidate ordering must first group by ``MatchKind``
    precedence, then by score within each group.
    """

    entity_id: EntityId
    """The stable domain identifier of the matched entity."""

    match_kind: MatchKind
    """How this hit was obtained (match provenance)."""

    score: float | None = None
    """Source-specific score/rank.

    ``None`` for exact matches.  Fuzzy similarity (0.0–100.0) for
    ``FUZZY_NAME``.  FTS rank (negative, closer to 0 better) for ``FTS``.
    """

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }


# ── Entity resolution outcomes ──────────────────────────────────────────────


class Resolved(BaseModel):
    """A uniquely resolved entity.

    Returned when the resolver identifies exactly one entity matching
    the input reference.
    """

    entity_id: EntityId
    """The stable domain identifier of the resolved entity."""

    match_kind: MatchKind
    """How the entity was resolved (match provenance)."""

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }


class Ambiguous(BaseModel):
    """Multiple candidates could match the input reference.

    Returned when the resolver cannot uniquely identify a single entity.
    The ``candidates`` field carries enough information for the caller
    (application/agent layer) to ask the user for clarification.

    This is a normal resolver outcome, not an error.
    """

    candidates: Sequence[SearchHit]
    """The candidate entities that could match.

    Ordered by descending confidence (most likely first).
    """

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }


class NotFound(BaseModel):
    """No entity matched the input reference.

    Returned when the resolver finds zero candidates.
    """

    query: str
    """The original query text that produced no results."""

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
    }


# ── Resolution outcome ──────────────────────────────────────────────────────


ResolutionOutcome = Resolved | Ambiguous | NotFound
"""The explicit result of entity resolution.

Exactly one of:
- ``Resolved`` — a single entity was uniquely identified.
- ``Ambiguous`` — multiple candidates matched; clarification needed.
- ``NotFound`` — no candidate matched.
"""


__all__: list[str] = [
    "Ambiguous",
    "MatchKind",
    "NotFound",
    "Resolved",
    "ResolutionOutcome",
    "SearchHit",
    "SearchQuery",
    "SearchQueryStr",
]
