"""S11-04 deterministic Summary/Recap visibility projection (model-free).

This module owns the trusted, deterministic projection of an accepted S11-03
extraction into the two renderer inputs:

- ``project_summary`` — GM/internal human projection.  Player- and DM-visible
  canonical entities are eligible; a claim referencing any SYSTEM canonical
  entity is excluded **whole** (SYSTEM material is not human-Summary material).
- ``project_recap`` — player-safe projection.  A claim is eligible only when
  the untrusted ``visibility_hint`` is PLAYER **and** it has at least one
  canonical resolved entity binding **and** every referenced canonical entity
  is ``Visibility.PLAYER`` **and** it carries no unresolved reference.

The Recap algorithm is fail-safe and whole-claim: a claim referencing a
non-player or unknown entity, or carrying an unresolved reference, is excluded
entirely; the entity name is never redacted out of surrounding text.

``ExtractionVisibilityHint`` is an untrusted restrictive signal.  It is never
canonical ``Visibility``; canonical prepared entity visibility always
outranks it.  An unresolved reference never enters the Recap projection, and a
new-entity candidate never enters the Recap projection.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, or a concrete storage
    implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

from dnd_assistant.application.post_session_extraction import (
    ResolvedEntityMention,
    UnresolvedEntityReference,
    UnresolvedReferenceReason,
)
from dnd_assistant.domain.post_session_extraction import (
    ClaimKind,
    ExtractionKnowledgeHint,
    ExtractionVisibilityHint,
)
from dnd_assistant.domain.types import EntityId, EntityType, Visibility

if TYPE_CHECKING:
    from dnd_assistant.application.post_session_context import PreparedPostSessionInput
    from dnd_assistant.application.post_session_extraction import (
        AcceptedPostSessionExtraction,
    )

# ── Player-safe / internal entity projections ─────────────────────────────


class RecapEntityRef(BaseModel):
    """Minimum canonical entity metadata admitted to the Recap renderer.

    Contains no body, no status, no knowledge status and no canonical
    visibility (only player-visible entities are ever constructed here).
    """

    entity_id: EntityId
    name: str
    entity_type: EntityType

    model_config = {"frozen": True, "extra": "forbid"}


class SummaryEntityRef(BaseModel):
    """Canonical entity metadata admitted to the internal Summary renderer.

    SYSTEM entities are structurally excluded: constructing a
    ``SummaryEntityRef`` with ``Visibility.SYSTEM`` fails validation, so SYSTEM
    entity metadata cannot reach the Summary model input.
    """

    entity_id: EntityId
    name: str
    entity_type: EntityType
    visibility: Visibility

    model_config = {"frozen": True, "extra": "forbid"}

    @field_validator("visibility")
    @classmethod
    def _not_system(cls, value: Visibility) -> Visibility:
        if value is Visibility.SYSTEM:
            raise ValueError("SYSTEM entities are not eligible for the human Summary projection")
        return value


# ── Claim projections ─────────────────────────────────────────────────────


class RecapClaimProjection(BaseModel):
    """A player-authorized claim rendered to the Recap model.

    Deliberately excludes visibility hints (authorization already proven),
    unresolved references and candidates.
    """

    claim_id: str
    kind: ClaimKind
    text: str
    knowledge_hint: ExtractionKnowledgeHint

    model_config = {"frozen": True, "extra": "forbid"}


class SummaryClaimProjection(BaseModel):
    """An accepted claim rendered to the internal Summary model."""

    claim_id: str
    kind: ClaimKind
    text: str
    visibility_hint: ExtractionVisibilityHint
    knowledge_hint: ExtractionKnowledgeHint
    entities: tuple[SummaryEntityRef, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


class SummaryUnresolvedReferenceProjection(BaseModel):
    """Structurally distinct non-canonical unresolved reference (Summary only)."""

    claim_id: str
    mention_id: str
    text: str
    entity_type: EntityType
    reason: UnresolvedReferenceReason

    model_config = {"frozen": True, "extra": "forbid"}


class SummaryCandidateProjection(BaseModel):
    """Structurally distinct non-canonical new-entity candidate (Summary only)."""

    candidate_id: str
    display_name: str
    entity_type: EntityType
    summary: str | None = None

    model_config = {"frozen": True, "extra": "forbid"}


# ── Diagnostics ───────────────────────────────────────────────────────────


class RecapExclusionReason(StrEnum):
    """Bounded, stable reason a claim is not Recap-eligible."""

    VISIBILITY_HINT_NOT_PLAYER = "visibility_hint_not_player"
    CONTAINS_UNRESOLVED_REFERENCE = "contains_unresolved_reference"
    NO_CANONICAL_PLAYER_SAFE_EVIDENCE = "no_canonical_player_safe_evidence"
    REFERENCES_NON_PLAYER_ENTITY = "references_non_player_entity"
    REFERENCES_UNAVAILABLE_ENTITY = "references_unavailable_entity"


class SummaryExclusionReason(StrEnum):
    """Bounded, stable reason a claim is not human-Summary-eligible."""

    REFERENCES_SYSTEM_ENTITY = "references_system_entity"
    REFERENCES_UNAVAILABLE_ENTITY = "references_unavailable_entity"


@dataclass(frozen=True)
class RecapExclusion:
    """One excluded Recap claim.  Carries ids and a reason only, never text."""

    claim_id: str
    reason: RecapExclusionReason


@dataclass(frozen=True)
class SummaryExclusion:
    """One excluded Summary claim.  Carries ids and a reason only, never text."""

    claim_id: str
    reason: SummaryExclusionReason


@dataclass(frozen=True)
class RecapFilterResult:
    """Deterministic player-safe Recap projection plus diagnostics."""

    claims: tuple[RecapClaimProjection, ...]
    entities: tuple[RecapEntityRef, ...]
    included_claim_ids: tuple[str, ...]
    excluded: tuple[RecapExclusion, ...]


@dataclass(frozen=True)
class SummaryFilterResult:
    """Deterministic internal Summary projection plus diagnostics."""

    claims: tuple[SummaryClaimProjection, ...]
    entities: tuple[SummaryEntityRef, ...]
    unresolved_references: tuple[SummaryUnresolvedReferenceProjection, ...]
    entity_candidates: tuple[SummaryCandidateProjection, ...]
    included_claim_ids: tuple[str, ...]
    excluded: tuple[SummaryExclusion, ...]


# ── Indexing helpers ──────────────────────────────────────────────────────


def _resolved_by_claim(
    mentions: tuple[ResolvedEntityMention, ...],
) -> dict[str, dict[str, ResolvedEntityMention]]:
    index: dict[str, dict[str, ResolvedEntityMention]] = {}
    for mention in mentions:
        index.setdefault(mention.claim_id, {})[mention.mention_id] = mention
    return index


# ── Recap projection ──────────────────────────────────────────────────────


def project_recap(
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
) -> RecapFilterResult:
    """Build the deterministic player-safe Recap projection.

    Pure and model-free.  Excludes whole claims that cannot be proven
    player-safe; never redacts a hidden entity name.
    """
    validated = accepted.validated
    prepared_entities = {entity.id: entity for entity in prepared.identity.entities}
    resolved_index = _resolved_by_claim(validated.resolved_mentions)
    unresolved_claim_ids = {ref.claim_id for ref in validated.unresolved_references}

    included: list[RecapClaimProjection] = []
    entity_order: list[str] = []
    entity_map: dict[str, RecapEntityRef] = {}
    excluded: list[RecapExclusion] = []

    for claim in validated.extraction.claims:
        if claim.visibility_hint is not ExtractionVisibilityHint.PLAYER:
            excluded.append(
                RecapExclusion(claim.claim_id, RecapExclusionReason.VISIBILITY_HINT_NOT_PLAYER)
            )
            continue
        if claim.claim_id in unresolved_claim_ids:
            excluded.append(
                RecapExclusion(claim.claim_id, RecapExclusionReason.CONTAINS_UNRESOLVED_REFERENCE)
            )
            continue

        mentions = resolved_index.get(claim.claim_id, {})
        if not mentions:
            excluded.append(
                RecapExclusion(
                    claim.claim_id, RecapExclusionReason.NO_CANONICAL_PLAYER_SAFE_EVIDENCE
                )
            )
            continue

        claim_refs: list[RecapEntityRef] = []
        exclusion: RecapExclusionReason | None = None
        for mention in mentions.values():
            entity = prepared_entities.get(mention.entity_id)
            if entity is None:
                exclusion = RecapExclusionReason.REFERENCES_UNAVAILABLE_ENTITY
                break
            if entity.visibility is not Visibility.PLAYER:
                exclusion = RecapExclusionReason.REFERENCES_NON_PLAYER_ENTITY
                break
            ref = RecapEntityRef(
                entity_id=entity.id,
                name=entity.name,
                entity_type=entity.type,
            )
            claim_refs.append(ref)

        if exclusion is not None:
            excluded.append(RecapExclusion(claim.claim_id, exclusion))
            continue

        for ref in claim_refs:
            if ref.entity_id not in entity_map:
                entity_map[ref.entity_id] = ref
                entity_order.append(ref.entity_id)

        included.append(
            RecapClaimProjection(
                claim_id=claim.claim_id,
                kind=claim.kind,
                text=claim.text,
                knowledge_hint=claim.knowledge_hint,
            )
        )

    return RecapFilterResult(
        claims=tuple(included),
        entities=tuple(entity_map[entity_id] for entity_id in entity_order),
        included_claim_ids=tuple(claim.claim_id for claim in included),
        excluded=tuple(excluded),
    )


# ── Summary projection ────────────────────────────────────────────────────


def project_summary(
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
) -> SummaryFilterResult:
    """Build the deterministic GM/internal Summary projection.

    Pure and model-free.  Excludes whole claims referencing SYSTEM (or
    unavailable) canonical entities; keeps unresolved references and
    new-entity candidates as structurally distinct non-canonical material.
    """
    validated = accepted.validated
    prepared_entities = {entity.id: entity for entity in prepared.identity.entities}
    resolved_index = _resolved_by_claim(validated.resolved_mentions)
    unresolved_by_claim: dict[str, list[UnresolvedEntityReference]] = {}
    for ref in validated.unresolved_references:
        unresolved_by_claim.setdefault(ref.claim_id, []).append(ref)

    included: list[SummaryClaimProjection] = []
    unresolved_out: list[SummaryUnresolvedReferenceProjection] = []
    entity_order: list[str] = []
    entity_map: dict[str, SummaryEntityRef] = {}
    excluded: list[SummaryExclusion] = []

    for claim in validated.extraction.claims:
        refs: list[SummaryEntityRef] = []
        exclusion: SummaryExclusionReason | None = None
        for mention in resolved_index.get(claim.claim_id, {}).values():
            entity = prepared_entities.get(mention.entity_id)
            if entity is None:
                exclusion = SummaryExclusionReason.REFERENCES_UNAVAILABLE_ENTITY
                break
            if entity.visibility is Visibility.SYSTEM:
                exclusion = SummaryExclusionReason.REFERENCES_SYSTEM_ENTITY
                break
            refs.append(
                SummaryEntityRef(
                    entity_id=entity.id,
                    name=entity.name,
                    entity_type=entity.type,
                    visibility=entity.visibility,
                )
            )

        if exclusion is not None:
            excluded.append(SummaryExclusion(claim.claim_id, exclusion))
            continue

        for ref in refs:
            if ref.entity_id not in entity_map:
                entity_map[ref.entity_id] = ref
                entity_order.append(ref.entity_id)

        included.append(
            SummaryClaimProjection(
                claim_id=claim.claim_id,
                kind=claim.kind,
                text=claim.text,
                visibility_hint=claim.visibility_hint,
                knowledge_hint=claim.knowledge_hint,
                entities=tuple(refs),
            )
        )

        for ref in unresolved_by_claim.get(claim.claim_id, ()):
            unresolved_out.append(
                SummaryUnresolvedReferenceProjection(
                    claim_id=ref.claim_id,
                    mention_id=ref.mention_id,
                    text=ref.text,
                    entity_type=ref.entity_type,
                    reason=ref.reason,
                )
            )

    candidates = tuple(
        SummaryCandidateProjection(
            candidate_id=candidate.candidate_id,
            display_name=candidate.display_name,
            entity_type=candidate.entity_type,
            summary=candidate.summary,
        )
        for candidate in validated.extraction.entity_candidates
    )

    return SummaryFilterResult(
        claims=tuple(included),
        entities=tuple(entity_map[entity_id] for entity_id in entity_order),
        unresolved_references=tuple(unresolved_out),
        entity_candidates=candidates,
        included_claim_ids=tuple(claim.claim_id for claim in included),
        excluded=tuple(excluded),
    )


__all__ = [
    "RecapClaimProjection",
    "RecapEntityRef",
    "RecapExclusion",
    "RecapExclusionReason",
    "RecapFilterResult",
    "SummaryCandidateProjection",
    "SummaryClaimProjection",
    "SummaryEntityRef",
    "SummaryExclusion",
    "SummaryExclusionReason",
    "SummaryFilterResult",
    "SummaryUnresolvedReferenceProjection",
    "project_recap",
    "project_summary",
]
