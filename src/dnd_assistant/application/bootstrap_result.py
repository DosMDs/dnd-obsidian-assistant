"""S13-03 bootstrap mapping result and unresolved diagnostics.

Pure in-memory result vocabulary shared by the bootstrap producer, mapping
orchestration, evidence policy and CLI presentation.  Contains no model,
filesystem or repository dependency.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.domain.changeset import ChangeSet

if TYPE_CHECKING:
    from dnd_assistant.application.changeset_review import ChangeSetFingerprint

__all__ = [
    "BootstrapMappingOutcome",
    "BootstrapMappingResult",
    "BootstrapOperationProvenance",
    "BootstrapUnresolved",
    "BootstrapUnresolvedReason",
]


class BootstrapUnresolvedReason(StrEnum):
    """Bounded, stable reasons a candidate/claim produced no mutation."""

    NO_CANONICAL_TARGET = "no_canonical_target"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    UNSUPPORTED_CLAIM_KIND = "unsupported_claim_kind"
    UNSUPPORTED_MULTI_TARGET = "unsupported_multi_target"
    AMBIGUOUS_EXACT_MATCH = "ambiguous_exact_match"
    DUPLICATE_EXISTING_ENTITY = "duplicate_existing_entity"
    ENTITY_ID_COLLISION = "entity_id_collision"
    CANONICAL_STATE_CONFLICT = "canonical_state_conflict"
    CANDIDATE_NAME_CONFLICT = "candidate_name_conflict"
    CONFLICTING_SOURCE_CLAIMS = "conflicting_source_claims"
    SYSTEM_ENTITY_EXCLUDED = "system_entity_excluded"
    STALE_CANONICAL_ENTITY = "stale_canonical_entity"
    DUPLICATE_FACT = "duplicate_fact"
    SOURCE_SKIPPED = "source_skipped"
    NON_CANONICAL_SOURCE = "non_canonical_source"
    CANONICAL_COVERAGE_INCOMPLETE = "canonical_coverage_incomplete"


@dataclass(frozen=True, slots=True)
class BootstrapUnresolved:
    """One deterministic omission/diagnostic, retaining source linkage."""

    reason: BootstrapUnresolvedReason
    detail: str
    candidate_id: str | None = None
    claim_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BootstrapOperationProvenance:
    """In-memory candidate/claim/evidence linkage for one emitted operation."""

    operation_index: int
    operation_kind: str
    candidate_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


class BootstrapMappingOutcome(StrEnum):
    """Terminal producer outcome."""

    PROPOSAL = "proposal"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True, slots=True)
class BootstrapMappingResult:
    """In-memory producer result for the mapping orchestration.

    Invariant:

    - ``PROPOSAL`` requires a non-empty ``changeset`` and its fingerprint;
    - ``NO_CHANGES`` requires ``changeset is None`` and no fingerprint.
    """

    outcome: BootstrapMappingOutcome
    unresolved: tuple[BootstrapUnresolved, ...] = ()
    operation_provenance: tuple[BootstrapOperationProvenance, ...] = ()
    changeset: ChangeSet | None = None
    changeset_fingerprint: ChangeSetFingerprint | None = None

    def __post_init__(self) -> None:
        if self.outcome is BootstrapMappingOutcome.PROPOSAL:
            if self.changeset is None or self.changeset_fingerprint is None:
                raise ValueError("PROPOSAL requires changeset and changeset_fingerprint")
        elif self.changeset is not None or self.changeset_fingerprint is not None:
            raise ValueError("NO_CHANGES requires changeset and changeset_fingerprint to be None")
