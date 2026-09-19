"""S13-03 application canonical projection over recognized entity candidates.

Turns the storage-owned, filesystem-free recognition of S13-02
``ENTITY_CANDIDATE`` sources into a deterministic read-only projection with two
explicit concepts:

- **bindable canonical entities** — reliably parsed, canonical, uniquely
  identified documents that may serve as ``append_fact`` targets;
- **conflicting canonical identities** — reliably parsed documents that are not
  bindable (duplicate canonical ``EntityId``, directory/type mismatch) but whose
  id/name/alias must still conservatively block new duplicate creation.

Malformed sources from which no identity can be safely obtained remain
unresolved evidence and contribute no identity guess.

The projection exposes only the narrow read/list surface required by ChangeSet
preflight.  It holds no filesystem authority and performs no I/O.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, or a concrete storage
    implementation (only the pure recognition types and storage ``TYPE_CHECKING``
    annotations).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    SourceClass,
    VaultDiscoveryReport,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.retrieval.exact_matching import (
    extract_exact_aliases,
    normalize_exact_text,
)
from dnd_assistant.storage.bootstrap_types import (
    CanonicalCandidate,
    CanonicalCandidateOutcome,
    is_managed_entity_namespace_path,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dnd_assistant.storage.types import VaultDocument

__all__ = [
    "CanonicalCandidateIssue",
    "CanonicalConflictReason",
    "CanonicalConflictView",
    "CanonicalCoverage",
    "CanonicalCoverageIssue",
    "CanonicalCoverageReason",
    "CanonicalEntityView",
    "CanonicalStateSnapshot",
    "assess_canonical_coverage",
    "build_canonical_snapshot",
]


class CanonicalConflictReason(StrEnum):
    """Why a reliably parsed document is not bindable but still blocking."""

    DUPLICATE_ENTITY_ID = "duplicate_entity_id"
    TYPE_DIRECTORY_MISMATCH = "type_directory_mismatch"


@dataclass(frozen=True, slots=True)
class CanonicalEntityView:
    """A bindable canonical entity recognized from an existing source."""

    entity_id: str
    entity_type: EntityType
    display_name: str
    revision: int
    relative_path: str
    normalized_name: str
    normalized_aliases: tuple[str, ...]
    document: VaultDocument


@dataclass(frozen=True, slots=True)
class CanonicalConflictView:
    """A reliably parsed but non-bindable canonical identity."""

    entity_id: str
    entity_type: EntityType
    display_name: str
    relative_path: str
    normalized_name: str
    normalized_aliases: tuple[str, ...]
    reason: CanonicalConflictReason


@dataclass(frozen=True, slots=True)
class CanonicalCandidateIssue:
    """A source candidate that yielded no reliable canonical identity."""

    relative_path: str
    outcome: CanonicalCandidateOutcome


@dataclass(frozen=True, slots=True)
class CanonicalStateSnapshot:
    """Read-only projection satisfying the ChangeSet preflight read surface.

    This is deliberately **not** a writable ``VaultRepository``.  It exposes
    only ``list_entities``; ChangeSet preflight against this snapshot is a
    proposal-consistency check, not proof that the strict filesystem repository
    can currently apply the proposal in a mixed historical Vault.
    """

    bindable: tuple[CanonicalEntityView, ...] = ()
    conflicts: tuple[CanonicalConflictView, ...] = ()
    issues: tuple[CanonicalCandidateIssue, ...] = ()

    def list_entities(
        self,
        entity_type: EntityType | None = None,
    ) -> list[VaultDocument]:
        """Return the bindable canonical documents visible to preflight."""
        if entity_type is None:
            return [view.document for view in self.bindable]
        return [view.document for view in self.bindable if view.entity_type is entity_type]


def _aliases(document: VaultDocument) -> tuple[str, ...]:
    return tuple(
        normalize_exact_text(alias)
        for alias in extract_exact_aliases(document.extra_frontmatter.get("aliases"))
    )


def _order_key(relative_path: str) -> tuple[str, str]:
    return (relative_path.casefold(), relative_path)


def build_canonical_snapshot(candidates: Sequence[CanonicalCandidate]) -> CanonicalStateSnapshot:
    """Build the read-only projection from recognized source candidates.

    A reliably parsed ``EntityId`` that appears in more than one candidate is a
    canonical-state conflict, and every occurrence becomes a non-bindable
    conflicting identity.  A parseable directory/type mismatch is likewise
    conflicting rather than bindable.  Malformed candidates produce an issue
    only.
    """
    grouped: dict[str, list[CanonicalCandidate]] = {}
    issues: list[CanonicalCandidateIssue] = []

    for candidate in candidates:
        if candidate.document is None or candidate.entity_id is None:
            issues.append(
                CanonicalCandidateIssue(
                    relative_path=candidate.relative_path,
                    outcome=candidate.outcome,
                )
            )
            continue
        grouped.setdefault(candidate.entity_id, []).append(candidate)

    bindable: list[CanonicalEntityView] = []
    conflicts: list[CanonicalConflictView] = []

    for entity_id, group in grouped.items():
        ordered = sorted(group, key=lambda item: _order_key(item.relative_path))
        if len(ordered) > 1:
            for candidate in ordered:
                conflicts.append(
                    _as_conflict(candidate, CanonicalConflictReason.DUPLICATE_ENTITY_ID)
                )
            continue

        candidate = ordered[0]
        if candidate.outcome is CanonicalCandidateOutcome.CANONICAL:
            document = candidate.document
            assert document is not None
            assert candidate.entity_type is not None
            assert candidate.display_name is not None
            assert candidate.revision is not None
            bindable.append(
                CanonicalEntityView(
                    entity_id=entity_id,
                    entity_type=candidate.entity_type,
                    display_name=candidate.display_name,
                    revision=candidate.revision,
                    relative_path=candidate.relative_path,
                    normalized_name=normalize_exact_text(candidate.display_name),
                    normalized_aliases=_aliases(document),
                    document=document,
                )
            )
        else:
            conflicts.append(
                _as_conflict(candidate, CanonicalConflictReason.TYPE_DIRECTORY_MISMATCH)
            )

    bindable.sort(key=lambda view: _order_key(view.relative_path))
    conflicts.sort(key=lambda view: _order_key(view.relative_path))
    issues.sort(key=lambda issue: _order_key(issue.relative_path))
    return CanonicalStateSnapshot(
        bindable=tuple(bindable),
        conflicts=tuple(conflicts),
        issues=tuple(issues),
    )


def _as_conflict(
    candidate: CanonicalCandidate,
    reason: CanonicalConflictReason,
) -> CanonicalConflictView:
    document = candidate.document
    assert document is not None
    assert candidate.entity_id is not None
    assert candidate.entity_type is not None
    assert candidate.display_name is not None
    return CanonicalConflictView(
        entity_id=candidate.entity_id,
        entity_type=candidate.entity_type,
        display_name=candidate.display_name,
        relative_path=candidate.relative_path,
        normalized_name=normalize_exact_text(candidate.display_name),
        normalized_aliases=_aliases(document),
        reason=reason,
    )


# ── Canonical coverage ────────────────────────────────────────────────────


class CanonicalCoverageReason(StrEnum):
    """Why canonical identity coverage cannot be fully established."""

    ENTITY_CANDIDATE_UNREADABLE = "entity_candidate_unreadable"
    """An ``ENTITY_CANDIDATE`` source could not be read, so an otherwise
    canonical entity may be hidden from recognition."""

    MANAGED_NAMESPACE_ISSUE = "managed_namespace_issue"
    """A discovery issue on a managed entity-namespace path can hide regular
    canonical files from the filesystem-free recognition step."""

    EXCLUDED_CANONICAL_PATH = "excluded_canonical_path"
    """An S13-02 exclusion inside (or equal to) a managed entity namespace can
    hide canonical ``.md`` files from the filesystem-free recognition step."""


@dataclass(frozen=True, slots=True)
class CanonicalCoverageIssue:
    """One reason canonical identity coverage is incomplete."""

    relative_path: str
    reason: CanonicalCoverageReason
    detail: str


@dataclass(frozen=True, slots=True)
class CanonicalCoverage:
    """Explicit coverage state derived from the S13-02 discovery report.

    When ``complete`` is false the canonical identity universe could not be
    fully established, so no create/append mutation may be authorized.
    """

    complete: bool
    issues: tuple[CanonicalCoverageIssue, ...] = ()


def assess_canonical_coverage(report: VaultDiscoveryReport) -> CanonicalCoverage:
    """Assess whether canonical identity coverage is complete.

    Consumes only the S13-02 report: no second filesystem traversal.  Coverage
    is complete exactly when no known S13-02 read/traversal/exclusion condition
    can hide a canonical ``.md`` entity from the report-derived recognition
    universe.  A skipped/failed ``ENTITY_CANDIDATE``, a discovery issue on a
    managed entity-namespace path, or an exclusion inside/equal to a managed
    namespace that could hide such a file makes coverage incomplete.  A
    skipped/failed ``USER_SOURCE``/``SESSION_SOURCE`` or a harmless exclusion
    (e.g. root ``.git``/``.obsidian`` or a non-``.md`` file) does not.
    """
    issues: list[CanonicalCoverageIssue] = []

    for entry in report.entries:
        if entry.source_class is not SourceClass.ENTITY_CANDIDATE:
            continue
        if entry.content_status is ContentReadStatus.READ and entry.content_text is not None:
            continue
        issues.append(
            CanonicalCoverageIssue(
                relative_path=entry.relative_path,
                reason=CanonicalCoverageReason.ENTITY_CANDIDATE_UNREADABLE,
                detail=(
                    "ENTITY_CANDIDATE content is unavailable "
                    f"({entry.content_status.value}); canonical identity coverage is incomplete"
                ),
            )
        )

    for issue in report.issues:
        if not is_managed_entity_namespace_path(issue.relative_path):
            continue
        issues.append(
            CanonicalCoverageIssue(
                relative_path=issue.relative_path,
                reason=CanonicalCoverageReason.MANAGED_NAMESPACE_ISSUE,
                detail=(
                    f"Discovery issue {issue.code.value!r} on a managed entity namespace can hide "
                    "canonical files; canonical identity coverage is incomplete"
                ),
            )
        )

    for excluded in report.excluded:
        if not is_managed_entity_namespace_path(excluded.relative_path):
            continue
        if not excluded.is_directory and not excluded.relative_path.casefold().endswith(".md"):
            continue
        kind = "directory" if excluded.is_directory else "Markdown file"
        issues.append(
            CanonicalCoverageIssue(
                relative_path=excluded.relative_path,
                reason=CanonicalCoverageReason.EXCLUDED_CANONICAL_PATH,
                detail=(
                    f"Excluded {kind} inside a managed entity namespace can hide canonical "
                    "entity files; canonical identity coverage is incomplete"
                ),
            )
        )

    issues.sort(
        key=lambda item: (item.relative_path.casefold(), item.relative_path, item.reason.value)
    )
    return CanonicalCoverage(complete=not issues, issues=tuple(issues))
