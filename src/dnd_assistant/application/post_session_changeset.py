"""S11-05 deterministic post-session ChangeSet producer.

Turns an accepted S11-03 extraction plus its S11-02 prepared input into a
bounded, immutable Stage-10 :class:`ChangeSet` proposal -- or an explicit
``NO_CHANGES`` result -- without any model call, filesystem write, review,
approval or apply authority.

Supported operations:

- ``create_entity`` for genuine ``ExtractedEntityCandidate`` records, using
  Python-owned canonical defaults and a deterministic candidate-scoped
  ``EntityId`` allocator;
- ``append_fact`` for an existing prepared entity when the claim has zero
  unresolved mentions and exactly one unique canonical target.

``update_entity`` is deliberately unsupported: the accepted extraction exposes
no typed canonical field-update semantic, and deriving one from prose would put
language understanding inside deterministic Python.

Trust boundary: targets come from trusted S11-03 id bindings plus exact
type-constrained name/alias resolution; nothing is rebound from model text, no
fuzzy/FTS binding is used, a full prepared-vs-current projection comparison
rejects stale context without rebasing, and every non-empty proposal must pass
the existing Stage-10 ``validate_changeset`` preflight.  This module persists
nothing (persistence is S11-06).

This module belongs to the application layer and must not import from:
    storage at runtime (protocol/types only under ``TYPE_CHECKING``), models,
    ollama, pydantic_ai, tools, cli, or the player SearchService/EntityResolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.changeset_review import (
    ChangeSetFingerprint,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_validation import validate_changeset
from dnd_assistant.application.entity_id_allocator import (
    allocate_candidate_entity_id,
)
from dnd_assistant.application.post_session_binding import (
    ExactMatchIndex,
    any_type_exact_matches,
    build_exact_index,
    prepared_projection_matches,
    resolve_mention_targets,
)
from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_extraction import (
    AcceptedPostSessionExtraction,
    ExtractionProvenance,
)
from dnd_assistant.application.post_session_provenance import (
    extraction_binding_mismatches,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeOperation,
    ChangeSet,
    CreateEntityOperation,
    ProposalProvenance,
)
from dnd_assistant.domain.post_session import (
    FailureCategory,
    PostSessionAttemptId,
    PreparedEntityProjection,
)
from dnd_assistant.domain.post_session_extraction import ClaimKind
from dnd_assistant.domain.types import (
    EntityId,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.retrieval.exact_matching import normalize_exact_text

if TYPE_CHECKING:
    from dnd_assistant.storage.types import VaultRepository

# ── Python-owned create defaults ──────────────────────────────────────────

CREATE_DEFAULT_STATUS: Final[str] = "unknown"
CREATE_DEFAULT_VISIBILITY: Final[Visibility] = Visibility.DM
CREATE_DEFAULT_KNOWLEDGE: Final[KnowledgeStatus] = KnowledgeStatus.INFERRED

_APPENDABLE_CLAIM_KINDS: Final[frozenset[ClaimKind]] = frozenset({ClaimKind.FACT, ClaimKind.EVENT})

_ATTEMPT_ID_ADAPTER: TypeAdapter[PostSessionAttemptId] = TypeAdapter(PostSessionAttemptId)


# ── Errors ────────────────────────────────────────────────────────────────


class PostSessionChangeFailureReason(StrEnum):
    """Bounded, stable classification of a hard producer failure."""

    INVALID_REQUEST = "invalid_request"
    INVALID_ATTEMPT_ID = "invalid_attempt_id"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    CHANGESET_PREFLIGHT_FAILED = "changeset_preflight_failed"


def _failure_category_for(reason: PostSessionChangeFailureReason) -> FailureCategory:
    if reason is PostSessionChangeFailureReason.PROVENANCE_MISMATCH:
        return FailureCategory.FINGERPRINT_MISMATCH
    if reason is PostSessionChangeFailureReason.CHANGESET_PREFLIGHT_FAILED:
        return FailureCategory.INTERNAL_ERROR
    return FailureCategory.INVALID_OUTPUT


class PostSessionChangeError(DndAssistantError):
    """Raised when ChangeSet production fails closed (never ambiguity)."""

    def __init__(
        self,
        reason: PostSessionChangeFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason

    def to_failure_category(self) -> FailureCategory:
        """Return the durable ``FailureCategory`` for this failure."""
        return _failure_category_for(self.reason)


# ── Expected ambiguity / omission diagnostics ─────────────────────────────


class PostSessionChangeUnresolvedReason(StrEnum):
    """Bounded, stable reasons a claim/candidate produced no mutation."""

    NO_CANONICAL_TARGET = "no_canonical_target"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    UNSUPPORTED_CLAIM_KIND = "unsupported_claim_kind"
    UNSUPPORTED_MULTI_TARGET = "unsupported_multi_target"
    TARGET_NOT_IN_PREPARED_CONTEXT = "target_not_in_prepared_context"
    STALE_PREPARED_ENTITY = "stale_prepared_entity"
    SYSTEM_ENTITY_EXCLUDED = "system_entity_excluded"
    DUPLICATE_FACT = "duplicate_fact"
    DUPLICATE_EXISTING_ENTITY = "duplicate_existing_entity"
    AMBIGUOUS_EXACT_MATCH = "ambiguous_exact_match"
    ENTITY_ID_COLLISION = "entity_id_collision"


@dataclass(frozen=True)
class PostSessionChangeUnresolved:
    """One deterministic omission/diagnostic, retaining source linkage."""

    reason: PostSessionChangeUnresolvedReason
    detail: str
    claim_id: str | None = None
    mention_id: str | None = None
    candidate_id: str | None = None
    candidate_entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PostSessionOperationProvenance:
    """In-memory claim/candidate/evidence linkage for one emitted operation."""

    operation_index: int
    operation_kind: str
    claim_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    evidence_event_ids: tuple[str, ...] = ()


class PostSessionChangeOutcome(StrEnum):
    """Terminal producer outcome."""

    PROPOSAL = "proposal"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True)
class PostSessionChangePlanResult:
    """In-memory producer result for S11-06 orchestration.

    Invariant:

    - ``PROPOSAL`` requires a non-empty ``changeset`` and its fingerprint;
    - ``NO_CHANGES`` requires ``changeset is None`` and no fingerprint.
    """

    outcome: PostSessionChangeOutcome
    provenance: ExtractionProvenance
    attempt_id: str
    unresolved: tuple[PostSessionChangeUnresolved, ...] = ()
    operation_provenance: tuple[PostSessionOperationProvenance, ...] = ()
    changeset: ChangeSet | None = None
    changeset_fingerprint: ChangeSetFingerprint | None = None

    def __post_init__(self) -> None:
        if self.outcome is PostSessionChangeOutcome.PROPOSAL:
            if self.changeset is None or self.changeset_fingerprint is None:
                raise ValueError("PROPOSAL requires changeset and changeset_fingerprint")
        elif self.changeset is not None or self.changeset_fingerprint is not None:
            raise ValueError("NO_CHANGES requires changeset and changeset_fingerprint to be None")


# ── Helpers ───────────────────────────────────────────────────────────────


def _body_contains_fact(body: str, fact: str) -> bool:
    """Exact-line detection of an existing rendered fact bullet."""
    bullet = f"- {fact}"
    for raw_line in body.split("\n"):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if line == bullet:
            return True
    return False


def _normalized(value: str) -> str:
    return normalize_exact_text(value)


def _resolve_create_conflict(
    index: ExactMatchIndex,
    *,
    allocated_id: EntityId,
    entity_type_name: str,
    display_name: str,
) -> PostSessionChangeUnresolved | None:
    """Return a duplicate/collision diagnostic for a candidate, or ``None``."""
    existing = index.documents.get(allocated_id)
    if existing is not None:
        same = existing.entity.type.value == entity_type_name and _normalized(
            existing.entity.name
        ) == _normalized(display_name)
        if same:
            return PostSessionChangeUnresolved(
                reason=PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY,
                detail=(
                    f"Allocated entity id {allocated_id!r} already exists with matching "
                    "canonical identity"
                ),
                candidate_entity_ids=(allocated_id,),
            )
        return PostSessionChangeUnresolved(
            reason=PostSessionChangeUnresolvedReason.ENTITY_ID_COLLISION,
            detail=(
                f"Allocated entity id {allocated_id!r} already exists with different "
                "canonical identity"
            ),
            candidate_entity_ids=(allocated_id,),
        )

    matches = any_type_exact_matches(index, display_name)
    if len(matches) == 1:
        return PostSessionChangeUnresolved(
            reason=PostSessionChangeUnresolvedReason.DUPLICATE_EXISTING_ENTITY,
            detail=(
                f"Candidate name {display_name!r} exactly matches an existing entity "
                "(any type); refusing to create a duplicate"
            ),
            candidate_entity_ids=matches,
        )
    if len(matches) > 1:
        return PostSessionChangeUnresolved(
            reason=PostSessionChangeUnresolvedReason.AMBIGUOUS_EXACT_MATCH,
            detail=(
                f"Candidate name {display_name!r} exactly matches multiple existing "
                "entities; refusing to create"
            ),
            candidate_entity_ids=matches,
        )
    return None


def _perform_preflight(
    changeset: ChangeSet,
    repository: VaultRepository,
) -> None:
    result = validate_changeset(changeset, repository)
    if not result.valid:
        codes = ", ".join(issue.code.value for issue in result.issues)
        raise PostSessionChangeError(
            PostSessionChangeFailureReason.CHANGESET_PREFLIGHT_FAILED,
            f"Produced ChangeSet {changeset.changeset_id!r} failed Stage-10 preflight: {codes}",
        )


# ── Public entrypoint ─────────────────────────────────────────────────────


def produce_post_session_changeset(
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
    *,
    attempt_id: str,
    repository: VaultRepository,
) -> PostSessionChangePlanResult:
    """Produce an in-memory Stage-10 proposal or an explicit NO_CHANGES result.

    Read-only: the only repository interactions are ``list_entities`` (binding
    snapshot) and the read-only Stage-10 preflight.  Nothing is persisted.

    Raises:
        PostSessionChangeError: Invalid attempt id, provenance mismatch, or a
            produced proposal failing Stage-10 preflight.
        StorageError: Repository corruption (propagated, fail closed).
    """
    try:
        validated_attempt_id = _ATTEMPT_ID_ADAPTER.validate_python(attempt_id)
    except PydanticValidationError as exc:
        raise PostSessionChangeError(
            PostSessionChangeFailureReason.INVALID_ATTEMPT_ID,
            f"Trusted attempt id {attempt_id!r} is not a valid PostSessionAttemptId",
            cause=exc,
        ) from exc

    mismatches = extraction_binding_mismatches(prepared, accepted)
    if mismatches:
        raise PostSessionChangeError(
            PostSessionChangeFailureReason.PROVENANCE_MISMATCH,
            "Accepted extraction does not belong to the prepared input: " + ", ".join(mismatches),
        )

    identity = prepared.identity
    session_ref = identity.session.id
    unresolved: list[PostSessionChangeUnresolved] = []

    documents = repository.list_entities()
    index = build_exact_index(documents)
    prepared_by_id = {entity.id: entity for entity in identity.entities}

    creates, create_provenance = _build_creates(
        accepted,
        session_ref=session_ref,
        index=index,
        unresolved=unresolved,
    )
    appends, append_provenance = _build_appends(
        accepted,
        prepared_by_id=prepared_by_id,
        index=index,
        unresolved=unresolved,
    )

    operations: list[ChangeOperation] = [*creates, *appends]
    if not operations:
        return PostSessionChangePlanResult(
            outcome=PostSessionChangeOutcome.NO_CHANGES,
            provenance=accepted.provenance,
            attempt_id=validated_attempt_id,
            unresolved=tuple(unresolved),
        )

    provenance = ProposalProvenance(
        provenance=Provenance.MODEL_INFERENCE,
        model_profile=accepted.provenance.model_profile,
        prompt_version=accepted.provenance.prompt_version,
    )
    changeset = ChangeSet(
        changeset_id=f"cs_{session_ref}_{validated_attempt_id}",
        provenance=provenance,
        session_ref=session_ref,
        operations=tuple(operations),
    )

    _perform_preflight(changeset, repository)

    raw_provenance = [*create_provenance, *append_provenance]
    operation_provenance = tuple(
        PostSessionOperationProvenance(
            operation_index=index,
            operation_kind=item.operation_kind,
            claim_ids=item.claim_ids,
            candidate_ids=item.candidate_ids,
            evidence_event_ids=item.evidence_event_ids,
        )
        for index, item in enumerate(raw_provenance)
    )

    return PostSessionChangePlanResult(
        outcome=PostSessionChangeOutcome.PROPOSAL,
        provenance=accepted.provenance,
        attempt_id=validated_attempt_id,
        unresolved=tuple(unresolved),
        operation_provenance=operation_provenance,
        changeset=changeset,
        changeset_fingerprint=compute_changeset_fingerprint(changeset),
    )


def _build_creates(
    accepted: AcceptedPostSessionExtraction,
    *,
    session_ref: str,
    index: ExactMatchIndex,
    unresolved: list[PostSessionChangeUnresolved],
) -> tuple[list[ChangeOperation], list[PostSessionOperationProvenance]]:
    """Build create operations in candidate order, or record diagnostics."""
    creates: list[ChangeOperation] = []
    provenance: list[PostSessionOperationProvenance] = []
    emitted_names: dict[str, str] = {}

    allocated: dict[str, EntityId] = {}
    allocation_claims: dict[EntityId, list[str]] = {}
    for candidate in accepted.validated.extraction.entity_candidates:
        allocated[candidate.candidate_id] = allocate_candidate_entity_id(
            session_ref, candidate.entity_type, candidate.display_name
        )
        allocation_claims.setdefault(allocated[candidate.candidate_id], []).append(
            candidate.candidate_id
        )

    for candidate in accepted.validated.extraction.entity_candidates:
        allocated_id = allocated[candidate.candidate_id]

        claimants = allocation_claims[allocated_id]
        if len(claimants) > 1:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.ENTITY_ID_COLLISION,
                    detail=(
                        "Candidates "
                        + ", ".join(repr(cid) for cid in claimants)
                        + " allocate the same entity id; refusing to choose one"
                    ),
                    candidate_id=candidate.candidate_id,
                    candidate_entity_ids=(allocated_id,),
                )
            )
            continue

        conflict = _resolve_create_conflict(
            index,
            allocated_id=allocated_id,
            entity_type_name=candidate.entity_type.value,
            display_name=candidate.display_name,
        )
        if conflict is not None:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=conflict.reason,
                    detail=conflict.detail,
                    candidate_id=candidate.candidate_id,
                    candidate_entity_ids=conflict.candidate_entity_ids,
                )
            )
            continue

        normalized_name = _normalized(candidate.display_name)
        if normalized_name in emitted_names:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.AMBIGUOUS_EXACT_MATCH,
                    detail=(
                        f"Candidate name {candidate.display_name!r} duplicates another "
                        "candidate in this proposal"
                    ),
                    candidate_id=candidate.candidate_id,
                )
            )
            continue
        emitted_names[normalized_name] = candidate.candidate_id

        creates.append(
            CreateEntityOperation(
                entity_id=allocated_id,
                type=candidate.entity_type,
                name=candidate.display_name,
                status=CREATE_DEFAULT_STATUS,
                visibility=CREATE_DEFAULT_VISIBILITY,
                knowledge_status=CREATE_DEFAULT_KNOWLEDGE,
                created_session=session_ref,
                last_seen_session=session_ref,
                tags=(),
            )
        )
        provenance.append(
            PostSessionOperationProvenance(
                operation_index=-1,
                operation_kind="create_entity",
                candidate_ids=(candidate.candidate_id,),
                evidence_event_ids=candidate.evidence_event_ids,
            )
        )

    return creates, provenance


def _build_appends(
    accepted: AcceptedPostSessionExtraction,
    *,
    prepared_by_id: dict[EntityId, PreparedEntityProjection],
    index: ExactMatchIndex,
    unresolved: list[PostSessionChangeUnresolved],
) -> tuple[list[ChangeOperation], list[PostSessionOperationProvenance]]:
    """Build append operations in claim order, or record diagnostics."""
    validated = accepted.validated
    trusted_targets: dict[tuple[str, str], EntityId] = {
        (mention.claim_id, mention.mention_id): mention.entity_id
        for mention in validated.resolved_mentions
    }

    appends: list[ChangeOperation] = []
    provenance: list[PostSessionOperationProvenance] = []
    projected_increment: dict[EntityId, int] = {}
    emitted_facts: set[tuple[EntityId, str]] = set()

    for claim in validated.extraction.claims:
        if claim.kind not in _APPENDABLE_CLAIM_KINDS:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.UNSUPPORTED_CLAIM_KIND,
                    detail=f"Claim kind {claim.kind.value!r} is not appendable in S11-05",
                    claim_id=claim.claim_id,
                )
            )
            continue

        targets: list[EntityId] = []
        has_unresolved = False
        for mention in claim.entity_mentions:
            trusted = trusted_targets.get((claim.claim_id, mention.mention_id))
            if trusted is not None and trusted not in targets:
                targets.append(trusted)
                continue
            resolved = resolve_mention_targets(index, mention.text, mention.entity_type)
            if len(resolved) == 1:
                if resolved[0] not in targets:
                    targets.append(resolved[0])
                continue
            has_unresolved = True
            detail = (
                f"Mention {mention.text!r} matched multiple canonical entities"
                if len(resolved) > 1
                else f"Mention {mention.text!r} did not resolve to a canonical entity"
            )
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.UNRESOLVED_REFERENCE,
                    detail=detail,
                    claim_id=claim.claim_id,
                    mention_id=mention.mention_id,
                    candidate_entity_ids=tuple(resolved),
                )
            )

        if len(targets) == 0:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.NO_CANONICAL_TARGET,
                    detail="Claim has no trusted canonical target",
                    claim_id=claim.claim_id,
                )
            )
            continue
        if len(targets) > 1:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.UNSUPPORTED_MULTI_TARGET,
                    detail="Claim resolves to more than one canonical target",
                    claim_id=claim.claim_id,
                    candidate_entity_ids=tuple(targets),
                )
            )
            continue
        if has_unresolved:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.UNRESOLVED_REFERENCE,
                    detail="Claim has an unresolved mention; whole claim omitted",
                    claim_id=claim.claim_id,
                )
            )
            continue

        target = targets[0]
        projection = prepared_by_id.get(target)
        if projection is None:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.TARGET_NOT_IN_PREPARED_CONTEXT,
                    detail="Resolved target is not part of the prepared entity context",
                    claim_id=claim.claim_id,
                    candidate_entity_ids=(target,),
                )
            )
            continue

        document = index.documents.get(target)
        if document is None or not prepared_projection_matches(document, projection):
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.STALE_PREPARED_ENTITY,
                    detail="Current canonical entity state no longer matches the prepared projection",
                    claim_id=claim.claim_id,
                    candidate_entity_ids=(target,),
                )
            )
            continue

        if document.entity.visibility is Visibility.SYSTEM:
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.SYSTEM_ENTITY_EXCLUDED,
                    detail="SYSTEM entities are not mutable targets in S11-05",
                    claim_id=claim.claim_id,
                    candidate_entity_ids=(target,),
                )
            )
            continue

        fact = claim.text
        if (target, fact) in emitted_facts or _body_contains_fact(document.body, fact):
            unresolved.append(
                PostSessionChangeUnresolved(
                    reason=PostSessionChangeUnresolvedReason.DUPLICATE_FACT,
                    detail="Exact fact already present in the entity body or already proposed",
                    claim_id=claim.claim_id,
                    candidate_entity_ids=(target,),
                )
            )
            continue

        expected_revision = projection.revision + projected_increment.get(target, 0)
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
            PostSessionOperationProvenance(
                operation_index=-1,
                operation_kind="append_fact",
                claim_ids=(claim.claim_id,),
                evidence_event_ids=claim.evidence_event_ids,
            )
        )

    return appends, provenance


__all__ = [
    "CREATE_DEFAULT_KNOWLEDGE",
    "CREATE_DEFAULT_STATUS",
    "CREATE_DEFAULT_VISIBILITY",
    "PostSessionChangeError",
    "PostSessionChangeFailureReason",
    "PostSessionChangeOutcome",
    "PostSessionChangePlanResult",
    "PostSessionChangeUnresolved",
    "PostSessionChangeUnresolvedReason",
    "PostSessionOperationProvenance",
    "produce_post_session_changeset",
]
