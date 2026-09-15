"""S11-05 internal deterministic exact entity binding primitives.

This module provides a focused, read-only, model-free exact-matching policy over
current canonical ``VaultRepository`` documents for post-session ChangeSet
production.  It is deliberately **not** the player-facing retrieval service:

- exact stable id, exact canonical name and exact canonical alias only;
- no fuzzy, no FTS, no substring, no ranking;
- entity-type constrained name/alias binding for mutation targets;
- any-type name/alias conflict detection for candidate duplicate prevention;
- full prepared-vs-current projection comparison for stale detection.

It imports only the pure ``retrieval.exact_matching`` normalization/alias
helpers.  It never imports or uses ``SearchService``, ``EntityResolver``,
``VaultSearchService``, ``SearchHit`` or ``SearchQuery``; the player-visibility
policy is not reused.

This module belongs to the application layer and must not import from:
    storage (only ``TYPE_CHECKING`` protocol/type hints), models, ollama,
    pydantic_ai, tools, cli
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dnd_assistant.domain.post_session import PreparedEntityProjection
from dnd_assistant.domain.types import EntityId, EntityType
from dnd_assistant.retrieval.exact_matching import (
    extract_exact_aliases,
    normalize_exact_text,
)

if TYPE_CHECKING:
    from dnd_assistant.storage.types import VaultDocument

__all__ = [
    "ExactMatchIndex",
    "any_type_exact_matches",
    "build_exact_index",
    "prepared_projection_matches",
    "resolve_mention_targets",
]


def _append_unique[KeyT](
    mapping: dict[KeyT, list[str]],
    key: KeyT,
    entity_id: EntityId,
) -> None:
    bucket = mapping.setdefault(key, [])
    if entity_id not in bucket:
        bucket.append(entity_id)


@dataclass(frozen=True)
class ExactMatchIndex:
    """Read-only exact index built from one current canonical Vault snapshot."""

    documents: Mapping[EntityId, VaultDocument]
    ids_by_type_name: Mapping[tuple[EntityType, str], tuple[EntityId, ...]]
    ids_by_type_alias: Mapping[tuple[EntityType, str], tuple[EntityId, ...]]
    ids_by_name_any: Mapping[str, tuple[EntityId, ...]]
    ids_by_alias_any: Mapping[str, tuple[EntityId, ...]]


def build_exact_index(documents: Sequence[VaultDocument]) -> ExactMatchIndex:
    """Build a deterministic exact index over current canonical documents.

    Bucket values preserve first-occurrence order and are deduplicated.  The
    index carries no player-visibility filtering: SYSTEM entities remain visible
    so duplicate creation can never bypass them.
    """
    by_id: dict[EntityId, VaultDocument] = {}
    type_name: dict[tuple[EntityType, str], list[str]] = {}
    type_alias: dict[tuple[EntityType, str], list[str]] = {}
    name_any: dict[str, list[str]] = {}
    alias_any: dict[str, list[str]] = {}

    for document in documents:
        entity = document.entity
        by_id[entity.id] = document

        normalized_name = normalize_exact_text(entity.name)
        _append_unique(type_name, (entity.type, normalized_name), entity.id)
        _append_unique(name_any, normalized_name, entity.id)

        for alias in extract_exact_aliases(document.extra_frontmatter.get("aliases")):
            normalized_alias = normalize_exact_text(alias)
            _append_unique(type_alias, (entity.type, normalized_alias), entity.id)
            _append_unique(alias_any, normalized_alias, entity.id)

    return ExactMatchIndex(
        documents=by_id,
        ids_by_type_name={k: tuple(v) for k, v in type_name.items()},
        ids_by_type_alias={k: tuple(v) for k, v in type_alias.items()},
        ids_by_name_any={k: tuple(v) for k, v in name_any.items()},
        ids_by_alias_any={k: tuple(v) for k, v in alias_any.items()},
    )


def resolve_mention_targets(
    index: ExactMatchIndex,
    text: str,
    entity_type: EntityType,
) -> tuple[EntityId, ...]:
    """Resolve a mention by exact name then exact alias, constrained by type.

    Returns the distinct matching ``EntityId`` values (possibly empty, possibly
    more than one when ambiguous).  Name matches take precedence over alias
    matches.  A name/alias belonging only to another ``EntityType`` yields no
    match.  Fuzzy/FTS matching is never performed.
    """
    normalized = normalize_exact_text(text)
    name_ids = index.ids_by_type_name.get((entity_type, normalized))
    if name_ids:
        return name_ids
    return index.ids_by_type_alias.get((entity_type, normalized), ())


def any_type_exact_matches(index: ExactMatchIndex, text: str) -> tuple[EntityId, ...]:
    """Return any-type exact name/alias matches for duplicate prevention.

    Used only for candidate duplicate detection: a model-declared "new" entity
    must never bypass an exact collision, even across entity types or against a
    SYSTEM entity.  Results are deduplicated and order-stable.
    """
    normalized = normalize_exact_text(text)
    matches: list[str] = []
    for entity_id in index.ids_by_name_any.get(normalized, ()):
        if entity_id not in matches:
            matches.append(entity_id)
    for entity_id in index.ids_by_alias_any.get(normalized, ()):
        if entity_id not in matches:
            matches.append(entity_id)
    return tuple(matches)


def prepared_projection_matches(
    document: VaultDocument,
    projection: PreparedEntityProjection,
) -> bool:
    """Return whether current canonical state exactly matches the prepared view.

    Compares ``id``, ``type``, ``revision``, ``name``, ``status``,
    ``visibility``, ``knowledge_status``, ``tags`` and the full body.  A
    mismatch means the extraction context is stale even if the numeric revision
    was not changed by an external editor.
    """
    entity = document.entity
    return (
        entity.id == projection.id
        and entity.type == projection.type
        and entity.revision == projection.revision
        and entity.name == projection.name
        and entity.status == projection.status
        and entity.visibility == projection.visibility
        and entity.knowledge_status == projection.knowledge_status
        and tuple(entity.tags) == projection.tags
        and document.body == projection.body_projection
    )
