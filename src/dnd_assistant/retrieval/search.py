"""Concrete exact, fuzzy, and FTS search implementation for the retrieval layer.

``VaultSearchService`` implements the ``SearchService`` protocol using
the VaultRepository read contracts for exact stable-ID, exact canonical
name, exact alias, fuzzy canonical-name, and FTS lexical matching.

This module depends on storage read contracts (``VaultRepository``,
``VaultDocument``) but not on storage implementation internals
(filesystem paths, atomic writes, audit mutation).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from dnd_assistant.domain.types import EntityId, EntityType, Visibility
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.retrieval.types import MatchKind, SearchHit, SearchQuery
from dnd_assistant.storage.types import VaultDocument, VaultRepository

if TYPE_CHECKING:
    from dnd_assistant.retrieval.lexical import LexicalIndex

# ── Exact-text normalisation ────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Normalise text for exact name/alias comparison and fuzzy
    canonical-name comparison.

    Applies, in order:
    1. Strip surrounding whitespace.
    2. Unicode NFC normalisation.
    3. Unicode ``casefold()``.

    This is a conservative deterministic policy.
    It does **not** implement transliteration, punctuation stripping,
    accent stripping, token sorting, or word reordering.
    """
    return unicodedata.normalize("NFC", text.strip()).casefold()


# ── Alias extraction ────────────────────────────────────────────────────────


def _extract_aliases(document: VaultDocument) -> list[str]:
    """Extract eligible alias strings from a ``VaultDocument``.

    Reads ``extra_frontmatter["aliases"]`` with fail-closed parsing:

    * ``aliases`` missing or ``None`` → no aliases.
    * ``aliases`` is a ``list`` / ``tuple`` → inspect each entry:
      - strict ``str`` entry, printable, non-empty after strip → eligible.
      - non-string, non-printable, empty/whitespace-only → ignored.
    * ``aliases`` is a scalar ``str`` → malformed, no aliases (do NOT
      iterate characters).
    * ``aliases`` is a ``dict`` / other mapping → malformed, no aliases.

    Duplicate alias values for a single entity are collapsed.
    """
    raw = document.extra_frontmatter.get("aliases")
    if raw is None:
        return []

    if isinstance(raw, (list, tuple)):
        seen: set[str] = set()
        result: list[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                continue
            if not entry.isprintable():
                continue
            stripped = entry.strip()
            if not stripped:
                continue
            if stripped not in seen:
                seen.add(stripped)
                result.append(stripped)
        return result

    # Scalar string, dict, or other unexpected type → malformed
    return []


# ── Eligibility helpers ─────────────────────────────────────────────────────


def _is_player_visible(document: VaultDocument) -> bool:
    """Return ``True`` if the entity is player-visible."""
    return document.entity.visibility == Visibility.PLAYER


def _is_eligible_type(document: VaultDocument, entity_types: set[EntityType] | None) -> bool:
    """Return ``True`` if the entity type passes the optional filter.

    ``None`` or empty set means all MVP entity types are eligible.
    """
    if not entity_types:
        return True
    return document.entity.type in entity_types


# ── Limit validation ────────────────────────────────────────────────────────


def _validate_limit(limit: object) -> int:
    """Validate that *limit* is a strict positive integer >= 1.

    Raises ``ValidationError`` for invalid values.
    """
    if isinstance(limit, bool):
        raise ValidationError("limit must not be a bool")
    if not isinstance(limit, int):
        raise ValidationError(f"limit must be an integer, got {type(limit).__name__}")
    if limit < 1:
        raise ValidationError(f"limit must be >= 1, got {limit}")
    return limit


# ── Concrete search service ─────────────────────────────────────────────────


class VaultSearchService:
    """Concrete ``SearchService`` implementation using ``VaultRepository``.

    Provides exact stable-ID, exact canonical name, exact alias, fuzzy
    canonical-name, and FTS lexical retrieval with player-visibility
    enforcement, entity-type filtering, and deterministic ordering.

    Fuzzy matching uses RapidFuzz ``fuzz.ratio`` on normalised
    (strip → NFC → casefold) canonical names only.  Aliases and
    ``EntityId`` values are not fuzzy-matched.

    The FTS tier uses a ``LexicalIndex`` (optional).  When no index is
    configured, the FTS tier is unavailable and returns no results.

    This service is read-only.  It does not mutate the Vault, access the
    filesystem directly, or depend on Ollama/ModelGateway.
    """

    def __init__(
        self,
        repository: VaultRepository,
        lexical_index: LexicalIndex | None = None,
    ) -> None:
        self._repository = repository
        self._lexical_index = lexical_index

    # ── get_by_id ───────────────────────────────────────────────────────

    def get_by_id(self, entity_id: EntityId) -> SearchHit | None:
        """Look up a single entity by its stable ``EntityId``.

        Returns ``None`` for:
        * missing entities
        * entities with ``Visibility.DM`` or ``Visibility.SYSTEM``

        Repository integrity failures (``StorageError``, corrupt data)
        propagate unchanged.
        """
        try:
            doc = self._repository.get_entity(entity_id)
        except NotFoundError:
            return None

        if not _is_player_visible(doc):
            return None

        return SearchHit(
            entity_id=entity_id,
            match_kind=MatchKind.EXACT_ID,
        )

    # ── search ──────────────────────────────────────────────────────────

    def search(self, query: SearchQuery, *, limit: int = 20) -> Sequence[SearchHit]:
        """Execute a tiered search over campaign entities.

        Operates in deterministic tiers:
        1. ``EXACT_ID`` — literal stable-ID match.
        2. ``EXACT_NAME`` — normalised canonical name match.
        3. ``EXACT_ALIAS`` — normalised alias match.
        4. ``FUZZY_NAME`` — fuzzy canonical name match via RapidFuzz.
        5. ``FTS`` — lexical full-text search via SQLite FTS5.

        Returns candidates only from the **highest-precedence non-empty
        tier**.  Visibility and entity-type filtering are applied before
        tier selection.
        """
        _validate_limit(limit)

        # Gather all eligible documents once.
        eligible = self._eligible_documents(query.entity_types)

        # Tier 1: EXACT_ID
        id_matches = self._match_exact_id(eligible, query.text)
        if id_matches:
            return self._finalise(id_matches, limit)

        # Tier 2: EXACT_NAME
        name_matches = self._match_exact_name(eligible, query.text)
        if name_matches:
            return self._finalise(name_matches, limit)

        # Tier 3: EXACT_ALIAS
        alias_matches = self._match_exact_alias(eligible, query.text)
        if alias_matches:
            return self._finalise(alias_matches, limit)

        # Tier 4: FUZZY_NAME
        fuzzy_matches = self._match_fuzzy_name(eligible, query.text)
        if fuzzy_matches:
            return self._finalise_fuzzy(fuzzy_matches, limit)

        # Tier 5: FTS
        if self._lexical_index is not None:
            # Verify freshness against ALL repository documents (not just
            # the filtered eligible set), because the index fingerprint
            # was computed from the full Vault snapshot.
            try:
                all_docs = list(self._repository.list_entities())
                self._lexical_index.verify_freshness(all_docs)
            except StorageError:
                raise

            fts_hits = self._lexical_index.search(query.text, limit=limit)
            if fts_hits:
                # Filter by current eligibility (visibility + type already
                # applied via eligible set; verify EntityId membership)
                eligible_ids = {d.entity.id for d in eligible}
                filtered = [h for h in fts_hits if h.entity_id in eligible_ids]
                if filtered:
                    return [
                        SearchHit(
                            entity_id=h.entity_id,
                            match_kind=MatchKind.FTS,
                            score=h.score,
                        )
                        for h in filtered[:limit]
                    ]

        return []

    # ── Internal helpers ────────────────────────────────────────────────

    def _eligible_documents(self, entity_types: set[EntityType] | None) -> list[VaultDocument]:
        """Return all player-visible documents matching the type filter."""
        result: list[VaultDocument] = []
        for doc in self._repository.list_entities():
            if not _is_player_visible(doc):
                continue
            if not _is_eligible_type(doc, entity_types):
                continue
            result.append(doc)
        return result

    @staticmethod
    def _match_exact_id(
        documents: list[VaultDocument], query: str
    ) -> list[tuple[VaultDocument, MatchKind]]:
        """Find documents whose stable ID equals *query* literally."""
        hits: list[tuple[VaultDocument, MatchKind]] = []
        for doc in documents:
            # EntityId is a validated string; compare literally.
            if doc.entity.id == query:
                hits.append((doc, MatchKind.EXACT_ID))
        return hits

    @staticmethod
    def _match_exact_name(
        documents: list[VaultDocument], query: str
    ) -> list[tuple[VaultDocument, MatchKind]]:
        """Find documents whose canonical name matches *query* after
        normalisation."""
        normalised_query = _normalize_text(query)
        hits: list[tuple[VaultDocument, MatchKind]] = []
        for doc in documents:
            if _normalize_text(doc.entity.name) == normalised_query:
                hits.append((doc, MatchKind.EXACT_NAME))
        return hits

    @staticmethod
    def _match_exact_alias(
        documents: list[VaultDocument], query: str
    ) -> list[tuple[VaultDocument, MatchKind]]:
        """Find documents whose alias matches *query* after normalisation."""
        normalised_query = _normalize_text(query)
        hits: list[tuple[VaultDocument, MatchKind]] = []
        for doc in documents:
            aliases = _extract_aliases(doc)
            if any(_normalize_text(a) == normalised_query for a in aliases):
                hits.append((doc, MatchKind.EXACT_ALIAS))
        return hits

    @staticmethod
    def _match_fuzzy_name(
        documents: list[VaultDocument], query: str
    ) -> list[tuple[VaultDocument, float]]:
        """Find documents whose canonical name fuzzy-matches *query*.

        Normalises both query and canonical name (strip → NFC → casefold)
        before computing ``rapidfuzz.fuzz.ratio``.

        Returns only candidates with ``score > 0.0``.
        """
        normalised_query = _normalize_text(query)
        hits: list[tuple[VaultDocument, float]] = []
        for doc in documents:
            normalised_name = _normalize_text(doc.entity.name)
            score = fuzz.ratio(normalised_query, normalised_name)
            if score > 0.0:
                hits.append((doc, float(score)))
        return hits

    @staticmethod
    def _finalise(candidates: list[tuple[VaultDocument, MatchKind]], limit: int) -> list[SearchHit]:
        """Sort deterministically by ``EntityId`` and apply limit.

        Each entity appears at most once (the input list already
        contains at most one entry per entity).
        """
        candidates.sort(key=lambda pair: pair[0].entity.id)
        return [
            SearchHit(entity_id=doc.entity.id, match_kind=kind) for doc, kind in candidates[:limit]
        ]

    @staticmethod
    def _finalise_fuzzy(
        candidates: list[tuple[VaultDocument, float]], limit: int
    ) -> list[SearchHit]:
        """Sort fuzzy candidates by score descending, then EntityId ascending, and apply limit."""
        candidates.sort(key=lambda pair: (-pair[1], pair[0].entity.id))
        return [
            SearchHit(entity_id=doc.entity.id, match_kind=MatchKind.FUZZY_NAME, score=score)
            for doc, score in candidates[:limit]
        ]


__all__: list[str] = [
    "VaultSearchService",
]
