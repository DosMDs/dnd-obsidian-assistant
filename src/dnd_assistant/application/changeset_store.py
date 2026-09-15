"""S10-05 ChangeSet proposal/approval persistence services.

Application-layer persistence policy for the Stage-10 workflow artifacts.  This
module owns the *meaning* of the persisted bytes and the workflow invariants
around them; the storage layer owns *safe placement* behind the
``ChangeSetStore`` protocol:

    proposal  write: canonical_changeset_bytes(changeset).decode("utf-8") + "\\n"
    proposal  read : json parse -> ChangeSet.model_validate(...)
    approval  write: deterministic json.dumps(approval.model_dump(mode="json")) + "\\n"
    approval  read : json parse -> ChangeSetApproval.model_validate(...)

Invariants:

- a persisted proposal round-trips so that
  ``compute_changeset_fingerprint(loaded) == compute_changeset_fingerprint(original)``,
  including the ``EntityFieldUpdate`` "omitted nullable field" versus
  "explicit None" distinction;
- proposal identity is immutable: an existing artifact with the same
  ``changeset_id`` and an identical fingerprint is idempotent, a different
  fingerprint is a ``ConflictError``, and malformed persisted content is a
  ``StorageError``;
- an approval artifact may only be written when it is bound to an **existing**
  persisted proposal with the same ``changeset_id`` and the exact persisted
  fingerprint (mandatory binding rule, applies to APPROVED and REJECTED);
- the approval artifact is immutable in S10-05: identical re-persist is
  idempotent, any differing field is a ``ConflictError``.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, cli, tools, retrieval, or a concrete
    ``ObsidianChangeSetStore`` implementation.  Only the ``ChangeSetStore``
    protocol is referenced (``TYPE_CHECKING``).
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING

from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    canonical_changeset_bytes,
    compute_changeset_fingerprint,
)
from dnd_assistant.domain.changeset import ChangeSet
from dnd_assistant.errors import ConflictError, StorageError, ValidationError

if TYPE_CHECKING:
    from dnd_assistant.storage.changeset_store import ChangeSetStore

# ── Persist outcomes ───────────────────────────────────────────────────────


class ProposalPersistOutcome(StrEnum):
    """Result of persisting a ChangeSet proposal artifact."""

    CREATED = "created"
    ALREADY_PRESENT = "already_present"


class ApprovalPersistOutcome(StrEnum):
    """Result of persisting a ChangeSet approval artifact."""

    CREATED = "created"
    ALREADY_PRESENT = "already_present"


# ── Proposal serialization ─────────────────────────────────────────────────


def serialize_proposal(changeset: ChangeSet) -> str:
    """Serialize a proposal to its canonical persisted text form.

    The text is exactly the S10-03 canonical proposal bytes decoded as UTF-8
    plus one trailing newline, so the persisted content contains no review
    metadata, approval data or timestamps.
    """
    return canonical_changeset_bytes(changeset).decode("utf-8") + "\n"


def deserialize_proposal(text: str) -> ChangeSet:
    """Parse persisted proposal text into a validated ``ChangeSet``.

    Raises:
        StorageError: The persisted text is malformed JSON, not a JSON object,
            or fails ``ChangeSet`` validation.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError("Persisted ChangeSet proposal is malformed JSON", cause=exc) from exc

    if not isinstance(data, dict):
        raise StorageError("Persisted ChangeSet proposal is not a JSON object")

    try:
        return ChangeSet.model_validate(data)
    except Exception as exc:
        raise StorageError("Persisted ChangeSet proposal is invalid", cause=exc) from exc


def parse_changeset_document(text: str) -> ChangeSet:
    """Parse an external/user-supplied ChangeSet JSON document.

    Unlike :func:`deserialize_proposal` (which validates trusted persisted
    artifacts and reports ``StorageError``), this reports an invalid user
    document as ``ValidationError``.

    Raises:
        ValidationError: The document is malformed JSON, not a JSON object, or
            fails ``ChangeSet`` validation.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError("ChangeSet document is malformed JSON", cause=exc) from exc

    if not isinstance(data, dict):
        raise ValidationError("ChangeSet document must be a JSON object")

    try:
        return ChangeSet.model_validate(data)
    except Exception as exc:
        raise ValidationError("ChangeSet document is invalid", cause=exc) from exc


# ── Approval serialization ─────────────────────────────────────────────────


def serialize_approval(approval: ChangeSetApproval) -> str:
    """Serialize an approval to deterministic JSON text plus one newline."""
    payload = approval.model_dump(mode="json")
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def deserialize_approval(text: str) -> ChangeSetApproval:
    """Parse persisted approval text into a validated ``ChangeSetApproval``.

    Raises:
        StorageError: The persisted text is malformed JSON, not a JSON object,
            or fails ``ChangeSetApproval`` validation.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError("Persisted ChangeSet approval is malformed JSON", cause=exc) from exc

    if not isinstance(data, dict):
        raise StorageError("Persisted ChangeSet approval is not a JSON object")

    try:
        return ChangeSetApproval.model_validate(data)
    except Exception as exc:
        raise StorageError("Persisted ChangeSet approval is invalid", cause=exc) from exc


# ── Proposal persistence policy ────────────────────────────────────────────


def persist_proposal(store: ChangeSetStore, changeset: ChangeSet) -> ProposalPersistOutcome:
    """Persist a proposal with immutable, idempotent policy.

    Semantics:

    - absent              -> exclusive create; ``CREATED``
    - identical fingerprint -> no write; ``ALREADY_PRESENT``
    - same id, different fingerprint -> ``ConflictError``
    - present but malformed -> ``StorageError``

    Raises:
        ConflictError: A proposal with the same id but different content exists.
        StorageError: A malformed persisted artifact or a filesystem error.
    """
    existing_text = store.read_proposal_if_present(changeset.changeset_id)

    if existing_text is None:
        store.create_proposal(changeset.changeset_id, serialize_proposal(changeset))
        return ProposalPersistOutcome.CREATED

    existing_changeset = deserialize_proposal(existing_text)
    if existing_changeset.changeset_id != changeset.changeset_id:
        raise ConflictError(
            f"Persisted proposal id {existing_changeset.changeset_id!r} does not match "
            f"key {changeset.changeset_id!r}"
        )

    if compute_changeset_fingerprint(existing_changeset) == compute_changeset_fingerprint(
        changeset
    ):
        return ProposalPersistOutcome.ALREADY_PRESENT

    raise ConflictError(
        f"A proposal for ChangeSet {changeset.changeset_id!r} already exists with different content"
    )


def load_proposal(store: ChangeSetStore, changeset_id: str) -> ChangeSet:
    """Load and validate a persisted proposal.

    Raises:
        NotFoundError: No proposal artifact exists for ``changeset_id``.
        StorageError: The artifact is unreadable or malformed.
    """
    return deserialize_proposal(store.read_proposal(changeset_id))


# ── Approval persistence policy ────────────────────────────────────────────


def persist_approval(store: ChangeSetStore, approval: ChangeSetApproval) -> ApprovalPersistOutcome:
    """Persist an immutable approval bound to an existing persisted proposal.

    The mandatory binding rule is enforced before any write:

    1. the persisted proposal for ``approval.changeset_id`` must exist;
    2. its id must match the approval's id;
    3. its fingerprint must equal ``approval.fingerprint``.

    Semantics:

    - absent                -> exclusive create; ``CREATED``
    - existing exactly equal -> no write; ``ALREADY_PRESENT``
    - any differing field    -> ``ConflictError``

    Raises:
        NotFoundError: No persisted proposal exists for the approval id.
        ValidationError: The approval is not bound to the persisted proposal.
        ConflictError: A different approval already exists (immutable).
        StorageError: A malformed persisted artifact or a filesystem error.
    """
    proposal = load_proposal(store, approval.changeset_id)

    if approval.changeset_id != proposal.changeset_id:
        raise ValidationError(
            f"Approval ChangeSet id {approval.changeset_id!r} does not match the persisted proposal"
        )

    if approval.fingerprint != compute_changeset_fingerprint(proposal):
        raise ValidationError(
            f"Approval for ChangeSet {approval.changeset_id!r} is not bound to the "
            f"persisted proposal fingerprint"
        )

    existing_text = store.read_approval_if_present(approval.changeset_id)
    if existing_text is None:
        store.create_approval(approval.changeset_id, serialize_approval(approval))
        return ApprovalPersistOutcome.CREATED

    existing_approval = deserialize_approval(existing_text)
    if existing_approval == approval:
        return ApprovalPersistOutcome.ALREADY_PRESENT

    raise ConflictError(
        f"An approval for ChangeSet {approval.changeset_id!r} already exists and is immutable"
    )


def load_approval(store: ChangeSetStore, changeset_id: str) -> ChangeSetApproval:
    """Load and validate a persisted approval.

    Raises:
        NotFoundError: No approval artifact exists for ``changeset_id``.
        StorageError: The artifact is unreadable or malformed.
    """
    return deserialize_approval(store.read_approval(changeset_id))


__all__ = [
    "ApprovalPersistOutcome",
    "ProposalPersistOutcome",
    "deserialize_approval",
    "deserialize_proposal",
    "load_approval",
    "load_proposal",
    "parse_changeset_document",
    "persist_approval",
    "persist_proposal",
    "serialize_approval",
    "serialize_proposal",
]
