"""S13-03 filesystem-free canonical candidate recognition types.

Pure recognition result types shared by the storage parse helper and the
application canonical projection.  This module imports no Markdown/YAML codec
and performs no I/O, so the application layer can consume recognition outcomes
without pulling a YAML parser into its runtime.

This module belongs to the storage layer and must not import from:
    application, models, tools, retrieval, cli, ollama, pydantic_ai
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.types import EntityDirectory, VaultDocument

# ── Path → canonical entity type ──────────────────────────────────────────

_ENTITY_TYPE_BY_PREFIX: dict[tuple[str, ...], EntityType] = {
    tuple(part.casefold() for part in directory.value.split("/")): EntityType[directory.name]
    for directory in EntityDirectory
}
"""Casefolded canonical entity-directory prefixes mapped to their ``EntityType``."""


def expected_entity_type(relative_path: str) -> EntityType | None:
    """Return the canonical entity type implied by a Vault-relative path.

    Reserved entity-directory namespaces are matched casefold-equivalently,
    consistent with the S13-02 classification policy.  Returns ``None`` when
    the path is not under a managed canonical entity directory.
    """
    parts = tuple(part.casefold() for part in relative_path.split("/"))
    for prefix, entity_type in _ENTITY_TYPE_BY_PREFIX.items():
        if len(parts) > len(prefix) and parts[: len(prefix)] == prefix:
            return entity_type
    return None


def is_managed_entity_namespace_path(relative_path: str) -> bool:
    """Return whether a path is inside, equal to, or an ancestor of a managed
    canonical entity namespace.

    A discovery issue on such a path can hide regular canonical entity files
    from recognition, so it makes canonical identity coverage incomplete.
    """
    parts = tuple(part.casefold() for part in relative_path.split("/"))
    if not parts or parts == ("",):
        return False
    for prefix in _ENTITY_TYPE_BY_PREFIX:
        if len(parts) >= len(prefix) and parts[: len(prefix)] == prefix:
            return True
        if len(prefix) >= len(parts) and prefix[: len(parts)] == parts:
            return True
    return False


# ── Result types ──────────────────────────────────────────────────────────


class CanonicalCandidateOutcome(StrEnum):
    """Deterministic canonical-recognition outcome for one source candidate."""

    CANONICAL = "canonical"
    """Parsed, validated and located in the canonical directory for its type."""

    MALFORMED = "malformed"
    """Not parseable as a canonical entity document; no identity is claimed."""

    TYPE_DIRECTORY_MISMATCH = "type_directory_mismatch"
    """Parsed reliably, but the YAML type does not match the directory type."""

    NOT_IN_ENTITY_DIRECTORY = "not_in_entity_directory"
    """Defensive: the logical path is not under a managed entity directory."""


@dataclass(frozen=True, slots=True)
class CanonicalCandidate:
    """Recognition result for one already-read ``ENTITY_CANDIDATE`` source.

    ``document`` and the identity fields are populated only when canonical
    parsing succeeded.  ``MALFORMED`` candidates carry no identity at all so
    the application cannot invent one.
    """

    relative_path: str
    expected_type: EntityType | None
    outcome: CanonicalCandidateOutcome
    document: VaultDocument | None = None
    entity_id: str | None = None
    entity_type: EntityType | None = None
    display_name: str | None = None
    revision: int | None = None


__all__ = [
    "CanonicalCandidate",
    "CanonicalCandidateOutcome",
    "expected_entity_type",
    "is_managed_entity_namespace_path",
]
