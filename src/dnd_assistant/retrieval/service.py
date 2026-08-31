"""Retrieval service contracts.

This module defines the typed protocols for the retrieval layer:

- ``SearchService`` — read-only search over campaign entities.
- ``EntityResolver`` — entity reference resolution with explicit outcomes.

Both protocols are runtime-checkable and depend only on domain and
retrieval-layer types.  They must not depend on:
    models, tools, application, cli, session runtime, Ollama
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.retrieval.types import (
    ResolutionOutcome,
    SearchHit,
    SearchQuery,
)


@runtime_checkable
class SearchService(Protocol):
    """Read-only search service for campaign entities.

    ``SearchService`` provides typed read-only retrieval over the
    canonical Vault.  It does not mutate the Vault, expose filesystem
    paths, or depend on Ollama/ModelGateway.

    **Player-visibility safety:**
    Only ``Visibility.PLAYER`` entities may be returned.
    ``Visibility.DM`` and ``Visibility.SYSTEM`` must never be returned
    by ``SearchService``, including exact stable-ID lookup via
    ``get_by_id``.  No visibility override is exposed at this layer.

    **Vault is Source of Truth:**
    The concrete implementation reads from the Vault directly (or
    from a derived index that is rebuildable from the Vault).  No
    retrieval result should contradict canonical Vault state.

    **No mutation:**
    ``SearchService`` is read-only.  It does not create, update, or
    delete campaign data.
    """

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        """Execute a search query and return matching candidates.

        Args:
            query: The typed search query (text + optional entity-type filter).
            limit: Maximum number of hits to return (must be >= 1).

        Returns:
            An ordered sequence of ``SearchHit`` candidates, sorted by
            descending relevance.  Empty sequence when no matches found.

        Raises:
            ValidationError: The query or limit is invalid.
        """
        ...

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        """Look up a single entity by its stable ``EntityId``.

        Args:
            entity_id: The stable domain identifier.

        Returns:
            A ``SearchHit`` if the entity exists and is player-visible,
            ``None`` otherwise.
        """
        ...


@runtime_checkable
class EntityResolver(Protocol):
    """Entity reference resolver with explicit outcomes.

    ``EntityResolver`` takes a free-text reference (entity name, alias,
    or partial name) and returns an explicit ``ResolutionOutcome``:

    - ``Resolved`` — the resolver confidently identifies one unique entity.
    - ``Ambiguous`` — one or more plausible candidates exist, but a unique
      confident resolution cannot be made; clarification is required.
    - ``NotFound`` — no candidate exists.

    **Ambiguity is a normal outcome.**
    The resolver must never silently guess.  When confidence is low or
    multiple candidates match, ``Ambiguous`` is returned with enough
    candidate information for the caller to ask the user for clarification.

    **Player-visibility safety:**
    Only ``Visibility.PLAYER`` entities may be returned.
    ``Visibility.DM`` and ``Visibility.SYSTEM`` must never appear
    in resolution results.

    **No LLM dependency:**
    Resolution is deterministic.  The resolver does not call Ollama or
    any model provider.
    """

    def resolve(
        self,
        reference: str,
        *,
        entity_type: EntityType | None = None,
    ) -> ResolutionOutcome:
        """Resolve a free-text reference to an entity.

        Args:
            reference: The free-text reference (name, alias, partial name).
                Must be non-empty after stripping.
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
        ...


__all__: list[str] = [
    "EntityResolver",
    "SearchService",
]
