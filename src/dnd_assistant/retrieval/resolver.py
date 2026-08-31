"""Concrete deterministic entity resolver.

``SearchEntityResolver`` implements the ``EntityResolver`` protocol by
consuming the provider-independent ``SearchService`` contract.

It converts free-text entity references into explicit outcomes:

- ``Resolved`` — a single unique high-confidence candidate (exact ID,
  exact name, or exact alias).
- ``Ambiguous`` — one or more plausible candidates exist, but a unique
  confident resolution cannot be made.
- ``NotFound`` — no candidate exists.

The resolver is deterministic, read-only, and does not depend on
Ollama, ModelGateway, storage internals, or filesystem access.
"""

from __future__ import annotations

from collections.abc import Sequence

from dnd_assistant.domain.types import EntityType
from dnd_assistant.errors import ValidationError
from dnd_assistant.retrieval.service import SearchService
from dnd_assistant.retrieval.types import (
    Ambiguous,
    MatchKind,
    NotFound,
    ResolutionOutcome,
    Resolved,
    SearchHit,
    SearchQuery,
)

# ── Internal candidate limit ────────────────────────────────────────────────
#
# The resolver needs more than one candidate to detect ambiguity.
# This limit matches the SearchService default of 20.
# It is intentionally not public configuration.

_CANDIDATE_LIMIT = 20


# ── High-confidence match kinds ─────────────────────────────────────────────
#
# Only exact matches are eligible for automatic resolution.
# Fuzzy and FTS matches always produce Ambiguous.

_HIGH_CONFIDENCE_KINDS: frozenset[MatchKind] = frozenset(
    {
        MatchKind.EXACT_ID,
        MatchKind.EXACT_NAME,
        MatchKind.EXACT_ALIAS,
    }
)


# ── Concrete resolver ───────────────────────────────────────────────────────


class SearchEntityResolver:
    """Concrete ``EntityResolver`` implementation using ``SearchService``.

    The resolver converts a free-text entity reference into an explicit
    ``ResolutionOutcome`` by delegating candidate discovery to the injected
    ``SearchService``.

    Resolution policy (conservative MVP):

    * Zero candidates → ``NotFound``.
    * Exactly one candidate with ``EXACT_ID``, ``EXACT_NAME``, or
      ``EXACT_ALIAS`` → ``Resolved``.
    * Exactly one candidate with ``FUZZY_NAME`` or ``FTS`` → ``Ambiguous``.
    * Two or more candidates → ``Ambiguous``.

    No numeric confidence threshold is used.  Fuzzy and FTS matches are
    never automatically resolved, regardless of score.

    The resolver is read-only.  It does not mutate the Vault, access the
    filesystem, or depend on Ollama/ModelGateway.
    """

    def __init__(self, search_service: SearchService) -> None:
        self._search_service = search_service

    def resolve(
        self,
        reference: str,
        *,
        entity_type: EntityType | None = None,
    ) -> ResolutionOutcome:
        """Resolve a free-text reference to an entity.

        Args:
            reference: The free-text reference (name, alias, partial name).
            entity_type: Optional type filter to narrow resolution scope.

        Returns:
            ``Resolved`` if the resolver confidently identifies one unique
            entity.
            ``Ambiguous`` if one or more plausible candidates exist but a
            unique confident resolution cannot be made.
            ``NotFound`` if no candidate exists.

        Raises:
            ValidationError: The reference is empty, whitespace-only, or
                contains non-printable characters.
        """
        # Validate input by reusing SearchQuery's Pydantic validation.
        # This enforces the same rules: non-empty, printable, strict string.
        try:
            query = SearchQuery(
                text=reference,
                entity_types={entity_type} if entity_type is not None else None,
            )
        except (ValueError, ValidationError) as exc:
            raise ValidationError(
                str(exc),
                cause=exc if isinstance(exc, ValidationError) else None,
            ) from exc

        # Delegate candidate discovery to the search service.
        hits: Sequence[SearchHit] = self._search_service.search(
            query,
            limit=_CANDIDATE_LIMIT,
        )

        # Zero candidates → NotFound
        if not hits:
            return NotFound(query=reference)

        # Exactly one candidate
        if len(hits) == 1:
            hit = hits[0]
            if hit.match_kind in _HIGH_CONFIDENCE_KINDS:
                return Resolved(
                    entity_id=hit.entity_id,
                    match_kind=hit.match_kind,
                )
            # Single fuzzy or FTS candidate → Ambiguous
            return Ambiguous(candidates=list(hits))

        # Two or more candidates → Ambiguous
        return Ambiguous(candidates=list(hits))


__all__: list[str] = [
    "SearchEntityResolver",
]
