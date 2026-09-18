"""S13-03 deterministic exact binding over the canonical projection.

Exact-only, model-free binding policy for bootstrap ChangeSet production:

- exact type-constrained canonical name, then exact type-constrained alias;
- any-type exact name/alias over *bindable and conflicting* identities for
  duplicate prevention;
- no fuzzy, no FTS, no substring, no ranking, and no player-facing retrieval
  service.

Reuses only the pure ``retrieval.exact_matching`` normalization/alias grammar.
It never imports or uses ``SearchService``, ``EntityResolver``,
``VaultSearchService``, ``SearchHit`` or ``SearchQuery``.

This module belongs to the application layer and must not import from:
    storage (only ``TYPE_CHECKING``), models, ollama, pydantic_ai, tools, cli.
"""

from __future__ import annotations

from dataclasses import dataclass

from dnd_assistant.application.bootstrap_canonical import (
    CanonicalEntityView,
    CanonicalStateSnapshot,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.retrieval.exact_matching import normalize_exact_text

__all__ = [
    "BootstrapExactIndex",
    "any_type_exact_matches",
    "build_bootstrap_index",
    "lookup_bindable",
    "resolve_exact_target",
]


@dataclass(frozen=True, slots=True)
class BootstrapExactIndex:
    """Deterministic exact index over one read-only canonical projection."""

    by_id: dict[str, CanonicalEntityView]
    conflicting_ids: frozenset[str]
    ids_by_type_name: dict[tuple[EntityType, str], tuple[str, ...]]
    ids_by_type_alias: dict[tuple[EntityType, str], tuple[str, ...]]
    ids_by_name_any: dict[str, tuple[str, ...]]
    ids_by_alias_any: dict[str, tuple[str, ...]]


def _append_unique[KeyT](mapping: dict[KeyT, list[str]], key: KeyT, entity_id: str) -> None:
    bucket = mapping.setdefault(key, [])
    if entity_id not in bucket:
        bucket.append(entity_id)


def build_bootstrap_index(snapshot: CanonicalStateSnapshot) -> BootstrapExactIndex:
    """Build a deterministic exact index over bindable and conflicting identities.

    Bindable entities populate the type-constrained name/alias maps used for
    trusted targets.  Conflicting identities are included in the any-type maps
    so duplicate creation can never bypass a reliably parsed canonical identity.
    """
    by_id: dict[str, CanonicalEntityView] = {}
    type_name: dict[tuple[EntityType, str], list[str]] = {}
    type_alias: dict[tuple[EntityType, str], list[str]] = {}
    name_any: dict[str, list[str]] = {}
    alias_any: dict[str, list[str]] = {}

    for view in snapshot.bindable:
        by_id[view.entity_id] = view
        _append_unique(type_name, (view.entity_type, view.normalized_name), view.entity_id)
        _append_unique(name_any, view.normalized_name, view.entity_id)
        for alias in view.normalized_aliases:
            _append_unique(type_alias, (view.entity_type, alias), view.entity_id)
            _append_unique(alias_any, alias, view.entity_id)

    for conflict in snapshot.conflicts:
        _append_unique(name_any, conflict.normalized_name, conflict.entity_id)
        for alias in conflict.normalized_aliases:
            _append_unique(alias_any, alias, conflict.entity_id)

    conflicting_ids = frozenset(conflict.entity_id for conflict in snapshot.conflicts)

    return BootstrapExactIndex(
        by_id=by_id,
        conflicting_ids=conflicting_ids,
        ids_by_type_name={k: tuple(v) for k, v in type_name.items()},
        ids_by_type_alias={k: tuple(v) for k, v in type_alias.items()},
        ids_by_name_any={k: tuple(v) for k, v in name_any.items()},
        ids_by_alias_any={k: tuple(v) for k, v in alias_any.items()},
    )


def resolve_exact_target(
    index: BootstrapExactIndex,
    text: str,
    entity_type: EntityType,
) -> tuple[str, ...]:
    """Resolve a reference by exact type-constrained name, then exact alias.

    Returns the distinct bindable ``EntityId`` values (possibly empty, possibly
    more than one when ambiguous).  Name matches take precedence over alias
    matches.  Conflicting identities never authorize a target.
    """
    normalized = normalize_exact_text(text)
    name_ids = index.ids_by_type_name.get((entity_type, normalized))
    if name_ids:
        return name_ids
    return index.ids_by_type_alias.get((entity_type, normalized), ())


def any_type_exact_matches(index: BootstrapExactIndex, text: str) -> tuple[str, ...]:
    """Return any-type exact name/alias matches for duplicate prevention.

    Includes conflicting canonical identities and SYSTEM/DM entities so a
    model-declared "new" entity can never bypass an exact canonical collision.
    Results are deduplicated and order-stable.
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


def lookup_bindable(index: BootstrapExactIndex, entity_id: str) -> CanonicalEntityView | None:
    """Return the bindable view for an exact stable id, or ``None``."""
    return index.by_id.get(entity_id)
