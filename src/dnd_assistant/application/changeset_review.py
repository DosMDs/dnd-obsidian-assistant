"""S10-03 ChangeSet review, canonical serialization and fingerprint binding.

Application-layer human-review contracts for a validated Stage-10
:class:`ChangeSet`.  This module turns an immutable proposal into a
deterministic, language-neutral review representation and binds an explicit
approval/rejection decision to the exact proposal content:

    ChangeSet
    -> fresh validate_changeset(...)      (S10-02, read-only)
    -> ChangeSetReview                    (proposal-only inspection DTO)
    -> canonical ChangeSet bytes
    -> SHA-256 ChangeSetFingerprint
    -> ChangeSetApproval                  (explicit decision, content-bound)

Ownership: canonical proposal serialization, fingerprinting, review DTOs,
approval/rejection DTOs and reviewer identity validation are **application
concerns**.  The immutable domain ``ChangeSet`` stays proposal data only.

Scope boundaries (deliberately not implemented here):

- no Vault mutation, no apply orchestration, no ``EntityPatch`` mapping, no
  ``AuditContext`` construction, no revision mutation and no rollback;
- no proposal/approval persistence (that is S10-05);
- no Russian CLI rendering (that is S10-05);
- no formatter is provided; review DTOs remain language-neutral.

TOCTOU scope distinction: the fingerprint binds the **ChangeSet content**, so it
detects a proposal that was modified or swapped after human review.  It does
**not** protect against Vault entity state changing after review.  Vault-state
drift remains S10-04's responsibility via a fresh preflight plus the
repository's optimistic revision enforcement.  Content binding is therefore not
apply authority.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os
``hashlib`` is used intentionally here: hashing is an application review concern
owned by S10-03.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from dnd_assistant.application.changeset_validation import (
    EntityReadSource,
    validate_changeset,
)
from dnd_assistant.domain.changeset import (
    ChangeOperation,
    ChangeSet,
    ChangeSetId,
    CreateEntityOperation,
    ProposalProvenance,
)
from dnd_assistant.domain.entity import SessionRef
from dnd_assistant.errors import ValidationError

# ── Reviewer identity / optional reason ───────────────────────────────────


def _validate_reviewer(value: str) -> str:
    """Validate an opaque reviewer identifier.

    Requirements: strict string, non-empty, no leading/trailing whitespace,
    printable Unicode.  No user/account/authentication semantics.
    """
    if not isinstance(value, str):
        raise ValueError("reviewer must be a string")
    if not value:
        raise ValueError("reviewer must not be empty")
    if value.strip() != value:
        raise ValueError("reviewer must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("reviewer must not contain non-printable characters")
    return value


def _validate_optional_reason(value: str | None) -> str | None:
    """Validate an optional review reason.

    ``None`` is allowed.  When present: strict string, non-empty, no
    surrounding whitespace, printable Unicode.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("reason must be a string or None")
    if not value:
        raise ValueError("reason must not be empty")
    if value.strip() != value:
        raise ValueError("reason must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("reason must not contain non-printable characters")
    return value


ReviewerId = Annotated[
    str,
    BeforeValidator(_validate_reviewer),
    Field(description="Opaque non-empty printable reviewer identifier"),
]
"""Minimal validated reviewer identifier (no authentication framework)."""

OptionalReasonStr = Annotated[
    str | None,
    BeforeValidator(_validate_optional_reason),
    Field(default=None, description="Optional printable review reason"),
]

# ── Canonical serialization / fingerprint ─────────────────────────────────

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


def canonical_changeset_bytes(changeset: ChangeSet) -> bytes:
    """Serialize a ChangeSet to deterministic canonical UTF-8 bytes.

    The serialized content is the exact proposal: ``schema_version``,
    ``changeset_id``, ``provenance``, ``session_ref`` and the ordered
    ``operations``.  It excludes review metadata, approval/reviewer data,
    repository state, current values, timestamps and filesystem data, because
    none of those exist on the immutable domain ``ChangeSet``.

    Determinism guarantees:

    - operation order is preserved (it is the apply order);
    - JSON object keys are sorted, so dict insertion order is irrelevant;
    - compact separators make the result independent of pretty-printing;
    - enums and tuples are normalized to JSON values/arrays via ``mode="json"``;
    - Unicode is preserved and encoded as UTF-8; no normalization is applied;
    - ``exclude_unset=False`` keeps aggregate/operation defaults while
      ``EntityFieldUpdate``'s own serializer still omits unset update fields,
      preserving the "unset" versus "explicit None" distinction.
    """
    payload = changeset.model_dump(mode="json", exclude_unset=False)
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


class ChangeSetFingerprint(BaseModel):
    """Self-describing content hash of an exact ChangeSet proposal."""

    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=_DIGEST_PATTERN)

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


def compute_changeset_fingerprint(changeset: ChangeSet) -> ChangeSetFingerprint:
    """Compute the lowercase-hex SHA-256 fingerprint of ``changeset`` content."""
    digest = hashlib.sha256(canonical_changeset_bytes(changeset)).hexdigest()
    return ChangeSetFingerprint(digest=digest)


# ── Review representation ─────────────────────────────────────────────────


class ReviewItem(BaseModel):
    """One inspected proposal operation, retaining the typed domain operation.

    The domain operation is the single source of truth; derived read-only
    properties expose the scalars a reviewer needs.  No repository current-state
    snapshot is held here.
    """

    operation_index: int = Field(ge=0)
    operation: ChangeOperation

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }

    @property
    def kind(self) -> str:
        """The operation kind (``create_entity``/``update_entity``/``append_fact``)."""
        return self.operation.kind

    @property
    def entity_id(self) -> str:
        """The targeted entity identifier."""
        return self.operation.entity_id

    @property
    def expected_revision(self) -> int | None:
        """The revision precondition, or ``None`` for a create operation."""
        if isinstance(self.operation, CreateEntityOperation):
            return None
        return self.operation.expected_revision


class ChangeSetReview(BaseModel):
    """Immutable, proposal-only inspection representation of a valid ChangeSet."""

    changeset_id: ChangeSetId
    fingerprint: ChangeSetFingerprint
    provenance: ProposalProvenance
    session_ref: SessionRef = None
    items: tuple[ReviewItem, ...] = Field(min_length=1)

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


# ── Approval / rejection ──────────────────────────────────────────────────


class ReviewDecision(StrEnum):
    """Explicit human review outcome.  No default is applied."""

    APPROVED = "approved"
    REJECTED = "rejected"


class ChangeSetApproval(BaseModel):
    """Immutable review decision bound to exact proposal identity and content.

    ``decision`` and ``reviewer`` are mandatory; there is no default approval.
    A rejected decision is a distinct enum member and can never be mistaken for
    an approval.
    """

    changeset_id: ChangeSetId
    fingerprint: ChangeSetFingerprint
    decision: ReviewDecision
    reviewer: ReviewerId
    reason: OptionalReasonStr = None

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }

    @property
    def is_approved(self) -> bool:
        """True only for an explicit ``APPROVED`` decision."""
        return self.decision is ReviewDecision.APPROVED

    def matches_approved_changeset(self, changeset: ChangeSet) -> bool:
        """Check content binding only; this is **not** apply authority.

        True when the decision is ``APPROVED`` and both the ChangeSet id and the
        fingerprint match ``changeset`` exactly.  This predicate deliberately
        does not read repository state, perform writes, or replace S10-04's
        fresh preflight and repository optimistic revision enforcement.  A
        matching result only means the approval was issued for this exact
        proposal content, not that applying it is currently safe.
        """
        return (
            self.is_approved
            and self.changeset_id == changeset.changeset_id
            and self.fingerprint == compute_changeset_fingerprint(changeset)
        )


# ── Builder ───────────────────────────────────────────────────────────────


def build_changeset_review(
    changeset: ChangeSet,
    repository: EntityReadSource,
) -> ChangeSetReview:
    """Build a proposal-only review after a fresh whole-batch preflight.

    Calls :func:`validate_changeset` exactly once against current repository
    state.  If the proposal is not valid, raises the existing project
    :class:`ValidationError` and produces no review, so an invalid proposal can
    never yield an approvable review.

    Args:
        changeset: The structurally valid proposal to review.
        repository: Trusted read source for current Vault state (read-only).

    Returns:
        A frozen :class:`ChangeSetReview` whose items map 1:1 to the ChangeSet
        operations in apply order.

    Raises:
        ValidationError: The ChangeSet failed whole-batch preflight.
    """
    result = validate_changeset(changeset, repository)
    if not result.valid:
        codes = ", ".join(issue.code.value for issue in result.issues)
        raise ValidationError(
            f"ChangeSet {changeset.changeset_id!r} failed preflight and cannot be reviewed: {codes}"
        )

    return ChangeSetReview(
        changeset_id=changeset.changeset_id,
        fingerprint=compute_changeset_fingerprint(changeset),
        provenance=changeset.provenance,
        session_ref=changeset.session_ref,
        items=tuple(
            ReviewItem(operation_index=index, operation=operation)
            for index, operation in enumerate(changeset.operations)
        ),
    )
