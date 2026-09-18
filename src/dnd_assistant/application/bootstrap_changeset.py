"""S13-03 deterministic bootstrap ChangeSet producer.

Turns a validated bootstrap extraction plus the read-only canonical projection
into a bounded, immutable Stage-10 :class:`ChangeSet` proposal -- or an explicit
``NO_CHANGES`` result -- without any model call, filesystem write, review,
approval or apply authority.

Supported operations:

- ``create_entity`` for genuine ``BootstrapEntityCandidate`` records, using
  Python-owned canonical defaults and a deterministic campaign-scoped
  ``EntityId`` allocator;
- ``append_fact`` for an existing bindable canonical entity when a claim has no
  unresolved reference and exactly one unique canonical target.

``update_entity`` is deliberately unsupported: the accepted extraction exposes
no typed canonical field-update semantic, and deriving one from prose would put
language understanding inside deterministic Python.

Trust boundary: no model-supplied canonical id exists at all; targets come from
deterministic exact type-constrained name/alias resolution over bindable
canonical entities; conflicting canonical identities and SYSTEM/DM entities
participate only in duplicate prevention; every non-empty proposal must pass
the existing Stage-10 ``validate_changeset`` preflight against the read-only
projection.  This module persists nothing (persistence is a separate service).

This module belongs to the application layer and must not import from:
    storage at runtime (protocol/types only under ``TYPE_CHECKING``), models,
    ollama, pydantic_ai, tools, cli, or the player SearchService/EntityResolver.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from dnd_assistant.application.bootstrap_binding import (
    BootstrapExactIndex,
    any_type_exact_matches,
    build_bootstrap_index,
    lookup_bindable,
    resolve_exact_target,
)
from dnd_assistant.application.bootstrap_canonical import CanonicalStateSnapshot
from dnd_assistant.application.bootstrap_entity_id import allocate_bootstrap_entity_id
from dnd_assistant.application.bootstrap_result import (
    BootstrapMappingOutcome,
    BootstrapMappingResult,
    BootstrapOperationProvenance,
    BootstrapUnresolved,
    BootstrapUnresolvedReason,
)
from dnd_assistant.application.changeset_review import compute_changeset_fingerprint
from dnd_assistant.application.changeset_validation import validate_changeset
from dnd_assistant.domain.bootstrap_extraction import (
    BootstrapClaimKind,
    BootstrapExtraction,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeOperation,
    ChangeSet,
    CreateEntityOperation,
    ProposalProvenance,
)
from dnd_assistant.domain.types import (
    EntityId,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.retrieval.exact_matching import normalize_exact_text

if TYPE_CHECKING:
    from dnd_assistant.domain.types import Sha256Fingerprint

# ── Python-owned create defaults ──────────────────────────────────────────

BOOTSTRAP_MAPPING_VERSION: Final[str] = "bootstrap-mapping-v1"
"""Explicit producer contract version bound into the proposal identity."""

CREATE_DEFAULT_STATUS: Final[str] = "unknown"
CREATE_DEFAULT_VISIBILITY: Final[Visibility] = Visibility.DM
CREATE_DEFAULT_KNOWLEDGE: Final[KnowledgeStatus] = KnowledgeStatus.INFERRED

_APPENDABLE_CLAIM_KINDS: Final[frozenset[BootstrapClaimKind]] = frozenset(
    {BootstrapClaimKind.FACT, BootstrapClaimKind.EVENT}
)


# ── Errors ────────────────────────────────────────────────────────────────


class BootstrapChangeFailureReason(StrEnum):
    """Bounded, stable classification of a hard producer failure."""

    INVALID_REQUEST = "invalid_request"
    CHANGESET_PREFLIGHT_FAILED = "changeset_preflight_failed"


class BootstrapChangeError(DndAssistantError):
    """Raised when bootstrap ChangeSet production fails closed."""

    def __init__(
        self,
        reason: BootstrapChangeFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason


# ── Expected ambiguity / omission diagnostics ─────────────────────────────
# Result/unresolved vocabulary lives in ``bootstrap_result``; the producer
# emits it.  ``ChangeSetFingerprint`` is imported below for the result type.


# ── Helpers ───────────────────────────────────────────────────────────────


def _body_contains_fact(body: str, fact: str) -> bool:
    bullet = f"- {fact}"
    for raw_line in body.split("\n"):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if line == bullet:
            return True
    return False


def _normalized(value: str) -> str:
    return normalize_exact_text(value)


def _proposal_id(
    campaign_id: str,
    input_fingerprint: Sha256Fingerprint,
    model_profile: str | None,
) -> str:
    import hashlib
    import json

    material = {
        "producer_version": BOOTSTRAP_MAPPING_VERSION,
        "campaign_id": campaign_id,
        "input_fingerprint": input_fingerprint.digest,
        "model_profile": model_profile,
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"cs_bootstrap_{digest[:32]}"


def _candidate_name_groups(
    extraction: BootstrapExtraction,
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for candidate in extraction.candidates:
        groups.setdefault(_normalized(candidate.display_name), []).append(candidate.candidate_id)
    return groups


def _conflict_group_counts(extraction: BootstrapExtraction) -> dict[str, int]:
    counts: dict[str, int] = {}
    for claim in extraction.claims:
        if claim.conflict_group is not None:
            counts[claim.conflict_group] = counts.get(claim.conflict_group, 0) + 1
    return counts


# ── Public entrypoint ─────────────────────────────────────────────────────


def produce_bootstrap_changeset(
    snapshot: CanonicalStateSnapshot,
    extraction: BootstrapExtraction,
    *,
    campaign_id: str,
    input_fingerprint: Sha256Fingerprint,
    model_profile: str | None,
    prompt_version: str,
) -> BootstrapMappingResult:
    """Produce an in-memory Stage-10 proposal or an explicit ``NO_CHANGES``.

    Read-only: the only preflight interaction is the pure read projection.  No
    canonical state is mutated and nothing is persisted.
    """
    index = build_bootstrap_index(snapshot)
    unresolved: list[BootstrapUnresolved] = []
    name_groups = _candidate_name_groups(extraction)
    conflict_counts = _conflict_group_counts(extraction)

    creates, create_provenance = _build_creates(
        extraction,
        index=index,
        campaign_id=campaign_id,
        name_groups=name_groups,
        unresolved=unresolved,
    )
    appends, append_provenance = _build_appends(
        extraction,
        index=index,
        conflict_counts=conflict_counts,
        unresolved=unresolved,
    )

    operations: list[ChangeOperation] = [*creates, *appends]
    if not operations:
        return BootstrapMappingResult(
            outcome=BootstrapMappingOutcome.NO_CHANGES,
            unresolved=tuple(unresolved),
        )

    provenance = ProposalProvenance(
        provenance=Provenance.BOOTSTRAP,
        model_profile=model_profile,
        prompt_version=prompt_version,
    )
    changeset = ChangeSet(
        changeset_id=_proposal_id(campaign_id, input_fingerprint, model_profile),
        provenance=provenance,
        session_ref=None,
        operations=tuple(operations),
    )

    result = validate_changeset(changeset, snapshot)
    if not result.valid:
        codes = ", ".join(issue.code.value for issue in result.issues)
        raise BootstrapChangeError(
            BootstrapChangeFailureReason.CHANGESET_PREFLIGHT_FAILED,
            f"Produced bootstrap ChangeSet {changeset.changeset_id!r} failed preflight: {codes}",
        )

    raw_provenance = [*create_provenance, *append_provenance]
    operation_provenance = tuple(
        BootstrapOperationProvenance(
            operation_index=position,
            operation_kind=item.operation_kind,
            candidate_ids=item.candidate_ids,
            claim_ids=item.claim_ids,
            source_refs=item.source_refs,
        )
        for position, item in enumerate(raw_provenance)
    )

    return BootstrapMappingResult(
        outcome=BootstrapMappingOutcome.PROPOSAL,
        unresolved=tuple(unresolved),
        operation_provenance=operation_provenance,
        changeset=changeset,
        changeset_fingerprint=compute_changeset_fingerprint(changeset),
    )


def _build_creates(
    extraction: BootstrapExtraction,
    *,
    index: BootstrapExactIndex,
    campaign_id: str,
    name_groups: dict[str, list[str]],
    unresolved: list[BootstrapUnresolved],
) -> tuple[list[ChangeOperation], list[BootstrapOperationProvenance]]:
    creates: list[ChangeOperation] = []
    provenance: list[BootstrapOperationProvenance] = []
    emitted_ids: dict[str, str] = {}
    allocation_claims: dict[EntityId, list[str]] = {}

    allocated: dict[str, EntityId] = {}
    for candidate in extraction.candidates:
        allocated[candidate.candidate_id] = allocate_bootstrap_entity_id(
            campaign_id, candidate.entity_type, candidate.display_name
        )
        allocation_claims.setdefault(allocated[candidate.candidate_id], []).append(
            candidate.candidate_id
        )

    for candidate in extraction.candidates:
        allocated_id = allocated[candidate.candidate_id]
        normalized_name = _normalized(candidate.display_name)

        if len(name_groups.get(normalized_name, ())) > 1:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.CANDIDATE_NAME_CONFLICT,
                    detail=(
                        f"Candidate name {candidate.display_name!r} is claimed by multiple "
                        "new candidates (possibly across types); refusing to choose"
                    ),
                    candidate_id=candidate.candidate_id,
                    source_refs=candidate.source_refs,
                )
            )
            continue

        claimants = allocation_claims[allocated_id]
        if len(claimants) > 1:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.ENTITY_ID_COLLISION,
                    detail=(
                        "Candidates "
                        + ", ".join(repr(cid) for cid in claimants)
                        + " allocate the same entity id; refusing to choose one"
                    ),
                    candidate_id=candidate.candidate_id,
                    entity_ids=(allocated_id,),
                    source_refs=candidate.source_refs,
                )
            )
            continue

        existing = lookup_bindable(index, allocated_id)
        if existing is not None:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.DUPLICATE_EXISTING_ENTITY,
                    detail=f"Allocated entity id {allocated_id!r} already exists canonically",
                    candidate_id=candidate.candidate_id,
                    entity_ids=(allocated_id,),
                    source_refs=candidate.source_refs,
                )
            )
            continue

        if allocated_id in emitted_ids:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.ENTITY_ID_COLLISION,
                    detail=f"Allocated entity id {allocated_id!r} already emitted in this proposal",
                    candidate_id=candidate.candidate_id,
                    entity_ids=(allocated_id,),
                    source_refs=candidate.source_refs,
                )
            )
            continue

        matches = any_type_exact_matches(index, candidate.display_name)
        if len(matches) == 1:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.DUPLICATE_EXISTING_ENTITY,
                    detail=(
                        f"Candidate name {candidate.display_name!r} exactly matches an existing "
                        "canonical identity; refusing to create a duplicate"
                    ),
                    candidate_id=candidate.candidate_id,
                    entity_ids=matches,
                    source_refs=candidate.source_refs,
                )
            )
            continue
        if len(matches) > 1:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.AMBIGUOUS_EXACT_MATCH,
                    detail=(
                        f"Candidate name {candidate.display_name!r} exactly matches multiple "
                        "canonical identities; refusing to create"
                    ),
                    candidate_id=candidate.candidate_id,
                    entity_ids=matches,
                    source_refs=candidate.source_refs,
                )
            )
            continue

        emitted_ids[allocated_id] = candidate.candidate_id
        creates.append(
            CreateEntityOperation(
                entity_id=allocated_id,
                type=candidate.entity_type,
                name=candidate.display_name,
                status=CREATE_DEFAULT_STATUS,
                visibility=CREATE_DEFAULT_VISIBILITY,
                knowledge_status=CREATE_DEFAULT_KNOWLEDGE,
                created_session=None,
                last_seen_session=None,
                tags=(),
            )
        )
        provenance.append(
            BootstrapOperationProvenance(
                operation_index=-1,
                operation_kind="create_entity",
                candidate_ids=(candidate.candidate_id,),
                source_refs=candidate.source_refs,
            )
        )

    return creates, provenance


def _build_appends(
    extraction: BootstrapExtraction,
    *,
    index: BootstrapExactIndex,
    conflict_counts: dict[str, int],
    unresolved: list[BootstrapUnresolved],
) -> tuple[list[ChangeOperation], list[BootstrapOperationProvenance]]:
    appends: list[ChangeOperation] = []
    provenance: list[BootstrapOperationProvenance] = []
    projected_increment: dict[EntityId, int] = {}
    emitted_facts: set[tuple[EntityId, str]] = set()

    for claim in extraction.claims:
        if claim.kind not in _APPENDABLE_CLAIM_KINDS:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.UNSUPPORTED_CLAIM_KIND,
                    detail=f"Claim kind {claim.kind.value!r} is not appendable in S13-03",
                    claim_id=claim.claim_id,
                    source_refs=claim.source_refs,
                )
            )
            continue

        if claim.conflict_group is not None and conflict_counts.get(claim.conflict_group, 0) > 1:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.CONFLICTING_SOURCE_CLAIMS,
                    detail=(
                        f"Claim belongs to conflict group {claim.conflict_group!r}; "
                        "conflicting evidence is never silently chosen"
                    ),
                    claim_id=claim.claim_id,
                    source_refs=claim.source_refs,
                )
            )
            continue

        targets: list[str] = []
        has_unresolved = False
        for reference in claim.references:
            resolved = resolve_exact_target(index, reference.text, reference.entity_type)
            if len(resolved) == 1:
                if resolved[0] not in targets:
                    targets.append(resolved[0])
                continue
            has_unresolved = True
            detail = (
                f"Reference {reference.text!r} matched multiple canonical entities"
                if len(resolved) > 1
                else f"Reference {reference.text!r} did not resolve to a canonical entity"
            )
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.UNRESOLVED_REFERENCE,
                    detail=detail,
                    claim_id=claim.claim_id,
                    entity_ids=tuple(resolved),
                    source_refs=reference.source_refs,
                )
            )

        if len(targets) == 0:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.NO_CANONICAL_TARGET,
                    detail="Claim has no trusted canonical target",
                    claim_id=claim.claim_id,
                    source_refs=claim.source_refs,
                )
            )
            continue
        if len(targets) > 1:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.UNSUPPORTED_MULTI_TARGET,
                    detail="Claim resolves to more than one canonical target",
                    claim_id=claim.claim_id,
                    entity_ids=tuple(targets),
                    source_refs=claim.source_refs,
                )
            )
            continue
        if has_unresolved:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.UNRESOLVED_REFERENCE,
                    detail="Claim has an unresolved reference; whole claim omitted",
                    claim_id=claim.claim_id,
                    source_refs=claim.source_refs,
                )
            )
            continue

        target = targets[0]
        view = lookup_bindable(index, target)
        if view is None:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.NO_CANONICAL_TARGET,
                    detail="Resolved target is not a bindable canonical entity",
                    claim_id=claim.claim_id,
                    entity_ids=(target,),
                    source_refs=claim.source_refs,
                )
            )
            continue

        if view.document.entity.visibility is Visibility.SYSTEM:
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.SYSTEM_ENTITY_EXCLUDED,
                    detail="SYSTEM entities are not mutable targets in S13-03",
                    claim_id=claim.claim_id,
                    entity_ids=(target,),
                    source_refs=claim.source_refs,
                )
            )
            continue

        fact = claim.text
        if (target, fact) in emitted_facts or _body_contains_fact(view.document.body, fact):
            unresolved.append(
                BootstrapUnresolved(
                    reason=BootstrapUnresolvedReason.DUPLICATE_FACT,
                    detail="Exact fact already present in the entity body or already proposed",
                    claim_id=claim.claim_id,
                    entity_ids=(target,),
                    source_refs=claim.source_refs,
                )
            )
            continue

        expected_revision = view.revision + projected_increment.get(target, 0)
        appends.append(
            AppendFactOperation(
                entity_id=target,
                expected_revision=expected_revision,
                fact=fact,
            )
        )
        projected_increment[target] = projected_increment.get(target, 0) + 1
        emitted_facts.add((target, fact))
        provenance.append(
            BootstrapOperationProvenance(
                operation_index=-1,
                operation_kind="append_fact",
                claim_ids=(claim.claim_id,),
                source_refs=claim.source_refs,
            )
        )

    return appends, provenance


__all__ = [
    "BOOTSTRAP_MAPPING_VERSION",
    "CREATE_DEFAULT_KNOWLEDGE",
    "CREATE_DEFAULT_STATUS",
    "CREATE_DEFAULT_VISIBILITY",
    "BootstrapChangeError",
    "BootstrapChangeFailureReason",
    "BootstrapMappingOutcome",
    "BootstrapMappingResult",
    "BootstrapOperationProvenance",
    "BootstrapUnresolved",
    "BootstrapUnresolvedReason",
    "produce_bootstrap_changeset",
]
