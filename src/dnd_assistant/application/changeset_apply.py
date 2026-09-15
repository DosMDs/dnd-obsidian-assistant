"""S10-04 ChangeSet apply orchestration with revision/conflict safety.

Applies an **approved** Stage-10 :class:`ChangeSet` to the Vault through the
``VaultRepository`` protocol only.  The canonical lifecycle is:

    approved ChangeSet
    -> verify approval content binding   (S10-03)
    -> fresh validate_changeset(...)     (S10-02, read-only, fail-closed)
    -> complete preflight before any write
    -> apply operations strictly in order
    -> VaultRepository mutations only

Safety properties preserved here:

- ``VaultRepository`` remains the sole persistence authority; the applier never
  touches the filesystem and never chooses paths/filenames;
- whole-batch ``validate_changeset`` runs again immediately before the first
  write, so a proposal that was valid at review time is re-checked against
  current Vault state (fingerprint content binding does not replace it);
- per-operation ``expected_revision`` is passed unchanged; there is no rebase,
  no retry and no auto-merge;
- on the first write-time failure the applier stops and never attempts later
  operations; there is no rollback and no whole-ChangeSet transaction claim.

Trusted context: :class:`ChangeSetApplyContext` supplies the trusted audit
``source`` and ``real_time``.  Per-operation audit identifiers and the
session/model provenance are **derived from the reviewed proposal**, never from
caller overrides or model text.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, shutil,
    tempfile, subprocess
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field
from pydantic.types import AwareDatetime

from dnd_assistant.application.changeset_review import ChangeSetApproval
from dnd_assistant.application.changeset_validation import validate_changeset
from dnd_assistant.domain.changeset import (
    ChangeOperation,
    ChangeSet,
    ChangeSetId,
    CreateEntityOperation,
    EntityFieldUpdate,
    UpdateEntityOperation,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.errors import (
    ConflictError,
    NotFoundError,
    StorageError,
    ValidationError,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultDocument, VaultRepository

# ── Trusted apply context ─────────────────────────────────────────────────


def _validate_source(value: str) -> str:
    """Validate a trusted audit ``source`` string.

    Requirements: strict string, non-empty, no leading/trailing whitespace,
    printable Unicode.
    """
    if not isinstance(value, str):
        raise ValueError("source must be a string")
    if not value:
        raise ValueError("source must not be empty")
    if value.strip() != value:
        raise ValueError("source must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("source must not contain non-printable characters")
    return value


ApplySource = Annotated[
    str,
    BeforeValidator(_validate_source),
    Field(description="Trusted application actor that performs the Vault writes"),
]


class ChangeSetApplyContext(BaseModel):
    """Trusted apply-time context supplied by the caller.

    This is deliberately **not** a full ``AuditContext``: the applier derives
    the per-operation ``operation_id``, ``session``, ``model_profile`` and
    ``prompt_version`` from the reviewed proposal (see
    :func:`_per_operation_audit`).  Only the trusted actor ``source`` and the
    trusted apply ``real_time`` are accepted from the caller.
    """

    source: ApplySource
    """Trusted audit source (e.g. ``"changeset_apply"``); never model text."""

    real_time: AwareDatetime
    """Trusted apply timestamp used for repository mutations; no fake time."""

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }


# ── Apply result contracts ────────────────────────────────────────────────


class ApplyFailureCategory(StrEnum):
    """Typed category of the original repository failure (never generic)."""

    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    STORAGE = "storage"


class ChangeSetApplyOutcome(StrEnum):
    """Truthful whole-batch outcome.

    ``APPLIED``  every operation was written;
    ``PARTIAL``  at least one operation was written, then apply stopped;
    ``FAILED``   the first operation failed before any write.
    """

    APPLIED = "applied"
    PARTIAL = "partial"
    FAILED = "failed"


class ApplyFailure(BaseModel):
    """One write-time failure, preserving the original typed category/message."""

    operation_index: int = Field(ge=0)
    category: ApplyFailureCategory
    message: str
    entity_id: str | None = None

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class ChangeSetApplyResult(BaseModel):
    """Immutable apply outcome.

    ``remaining_operation_indices`` contains only operations that were never
    attempted (the failing operation is excluded and identified by
    ``failure.operation_index``).
    """

    changeset_id: ChangeSetId
    outcome: ChangeSetApplyOutcome
    applied_operation_indices: tuple[int, ...]
    remaining_operation_indices: tuple[int, ...]
    failure: ApplyFailure | None = None

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }

    @property
    def succeeded(self) -> bool:
        """True only when every operation was applied."""
        return self.outcome is ChangeSetApplyOutcome.APPLIED


# ── Per-operation audit / mapping helpers ─────────────────────────────────


def _per_operation_audit(
    changeset: ChangeSet,
    context: ChangeSetApplyContext,
    index: int,
) -> AuditContext:
    """Build the trusted per-operation audit context.

    The deterministic ``operation_id`` ``<changeset_id>:<index>`` reuses the
    repository's duplicate-operation guard so re-applying the same ChangeSet
    fails naturally (no ChangeSet ledger is introduced).
    """
    return AuditContext(
        operation_id=f"{changeset.changeset_id}:{index}",
        real_time=context.real_time,
        source=context.source,
        session=changeset.session_ref,
        model_profile=changeset.provenance.model_profile,
        prompt_version=changeset.provenance.prompt_version,
    )


def _build_create_document(
    operation: CreateEntityOperation,
    context: ChangeSetApplyContext,
) -> VaultDocument:
    """Map a create operation onto a trusted ``VaultDocument``.

    Application-owned fields (``revision``/timestamps) are supplied from trusted
    apply time; the repository chooses path/filename and renders the body.
    """
    entity = Entity(
        id=operation.entity_id,
        type=operation.type,
        name=operation.name,
        status=operation.status,
        visibility=operation.visibility,
        knowledge_status=operation.knowledge_status,
        created_session=operation.created_session,
        last_seen_session=operation.last_seen_session,
        tags=list(operation.tags),
        created_at=context.real_time,
        updated_at=context.real_time,
        revision=1,
    )
    return VaultDocument(entity=entity)


def _build_entity_patch(update: EntityFieldUpdate) -> EntityPatch:
    """Map the semantic allowlist onto ``storage.patch.EntityPatch`` explicitly.

    Only the seven accepted fields are copied, keyed by name from
    ``model_fields_set``.  Omitted fields stay omitted; an explicit ``None`` on
    the nullable session fields stays an explicit clear; ``tags`` is a full
    replacement list.  There is no ``model_dump`` splat and no reflection-driven
    parity mapping.
    """
    fields = update.model_fields_set
    patch_fields: dict[str, Any] = {}

    if "name" in fields:
        patch_fields["name"] = update.name
    if "status" in fields:
        patch_fields["status"] = update.status
    if "visibility" in fields:
        patch_fields["visibility"] = update.visibility
    if "knowledge_status" in fields:
        patch_fields["knowledge_status"] = update.knowledge_status
    if "created_session" in fields:
        patch_fields["created_session"] = update.created_session
    if "last_seen_session" in fields:
        patch_fields["last_seen_session"] = update.last_seen_session
    if "tags" in fields:
        tags = update.tags
        if tags is None:  # pragma: no cover - domain validator forbids explicit None
            raise ValidationError("tags cannot be explicitly cleared")
        patch_fields["tags"] = list(tags)

    return EntityPatch(**patch_fields)


def _apply_operation(
    operation: ChangeOperation,
    repository: VaultRepository,
    audit: AuditContext,
    context: ChangeSetApplyContext,
) -> None:
    """Dispatch one operation to the corresponding repository mutation."""
    if isinstance(operation, CreateEntityOperation):
        repository.create_entity(_build_create_document(operation, context), audit=audit)
    elif isinstance(operation, UpdateEntityOperation):
        repository.patch_entity(
            operation.entity_id,
            _build_entity_patch(operation.update),
            expected_revision=operation.expected_revision,
            audit=audit,
        )
    else:
        repository.append_entity_fact(
            operation.entity_id,
            expected_revision=operation.expected_revision,
            fact=operation.fact,
            audit=audit,
        )


def _categorize(error: Exception) -> ApplyFailureCategory:
    """Map an existing project error to its typed apply-failure category."""
    if isinstance(error, ConflictError):
        return ApplyFailureCategory.CONFLICT
    if isinstance(error, NotFoundError):
        return ApplyFailureCategory.NOT_FOUND
    if isinstance(error, StorageError):
        return ApplyFailureCategory.STORAGE
    return ApplyFailureCategory.VALIDATION


# ── Public entry point ────────────────────────────────────────────────────


def apply_changeset(
    changeset: ChangeSet,
    approval: ChangeSetApproval,
    repository: VaultRepository,
    *,
    context: ChangeSetApplyContext,
) -> ChangeSetApplyResult:
    """Apply an approved ChangeSet through the Vault repository only.

    Order of operations:

    1. verify the approval content binding (decision/id/fingerprint);
    2. run a fresh whole-batch ``validate_changeset`` against current state;
    3. apply operations strictly in order until the first write failure.

    Approval and preflight failures raise the existing :class:`ValidationError`
    with zero writes and no result.  A write-time repository failure stops apply
    and is returned as a structured :class:`ChangeSetApplyResult`; already
    applied writes remain and no later operation is attempted.

    Args:
        changeset: The reviewed proposal to apply.
        approval: The explicit, content-bound review decision.
        repository: Trusted persistence authority (only source of writes).
        context: Trusted apply ``source`` and ``real_time``.

    Returns:
        A frozen :class:`ChangeSetApplyResult`.

    Raises:
        ValidationError: The approval does not authorize this exact proposal,
            or the fresh whole-batch preflight found any issue.
    """
    if not approval.matches_approved_changeset(changeset):
        raise ValidationError(
            f"ChangeSet {changeset.changeset_id!r} is not approved for this exact content"
        )

    validation = validate_changeset(changeset, repository)
    if not validation.valid:
        codes = ", ".join(issue.code.value for issue in validation.issues)
        raise ValidationError(
            f"ChangeSet {changeset.changeset_id!r} failed fresh preflight and was not applied: {codes}"
        )

    total = len(changeset.operations)
    applied: list[int] = []

    for index, operation in enumerate(changeset.operations):
        audit = _per_operation_audit(changeset, context, index)
        try:
            _apply_operation(operation, repository, audit, context)
        except (ValidationError, NotFoundError, ConflictError, StorageError) as exc:
            outcome = ChangeSetApplyOutcome.PARTIAL if applied else ChangeSetApplyOutcome.FAILED
            return ChangeSetApplyResult(
                changeset_id=changeset.changeset_id,
                outcome=outcome,
                applied_operation_indices=tuple(applied),
                remaining_operation_indices=tuple(range(index + 1, total)),
                failure=ApplyFailure(
                    operation_index=index,
                    category=_categorize(exc),
                    message=str(exc),
                    entity_id=operation.entity_id,
                ),
            )
        applied.append(index)

    return ChangeSetApplyResult(
        changeset_id=changeset.changeset_id,
        outcome=ChangeSetApplyOutcome.APPLIED,
        applied_operation_indices=tuple(applied),
        remaining_operation_indices=(),
        failure=None,
    )


__all__ = [
    "ApplyFailure",
    "ApplyFailureCategory",
    "ChangeSetApplyContext",
    "ChangeSetApplyOutcome",
    "ChangeSetApplyResult",
    "apply_changeset",
]
