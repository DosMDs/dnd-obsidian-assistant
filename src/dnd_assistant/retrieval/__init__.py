"""Retrieval layer: exact/fuzzy/FTS search and entity resolution.

This package provides read-only retrieval contracts and types for
campaign entity search and reference resolution.

Sub-modules
-----------
types/       — Canonical retrieval types (MatchKind, SearchQuery, SearchHit,
               Resolved, Ambiguous, NotFound, ResolutionOutcome).
service/     — SearchService and EntityResolver protocols.
resolver/    — Concrete deterministic entity resolver.
lexical/     — Provider-independent LexicalIndex protocol.
index/       — SQLite FTS5 concrete lexical index implementation.
"""

from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.retrieval.lexical import LexicalHit, LexicalIndex
from dnd_assistant.retrieval.resolver import SearchEntityResolver
from dnd_assistant.retrieval.search import VaultSearchService
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
    "LexicalHit",
    "LexicalIndex",
    "MatchKind",
    "NotFound",
    "Resolved",
    "ResolutionOutcome",
    "SearchEntityResolver",
    "SearchHit",
    "SearchQuery",
    "SearchService",
    "SqliteFtsIndex",
    "VaultSearchService",
]
