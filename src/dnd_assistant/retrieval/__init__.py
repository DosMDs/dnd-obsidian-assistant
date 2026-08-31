"""Retrieval layer: exact/fuzzy/FTS search and entity resolution.

This package provides read-only retrieval contracts and types for
campaign entity search and reference resolution.

Sub-modules
-----------
types/       — Canonical retrieval types (MatchKind, SearchQuery, SearchHit,
               Resolved, Ambiguous, NotFound, ResolutionOutcome).
service/     — SearchService and EntityResolver protocols.
"""

from dnd_assistant.retrieval.service import EntityResolver, SearchService
from dnd_assistant.retrieval.types import (
    Ambiguous,
    MatchKind,
    NotFound,
    ResolutionOutcome,
    Resolved,
    SearchHit,
    SearchQuery,
)

__all__: list[str] = [
    "Ambiguous",
    "EntityResolver",
    "MatchKind",
    "NotFound",
    "Resolved",
    "ResolutionOutcome",
    "SearchHit",
    "SearchQuery",
    "SearchService",
]
