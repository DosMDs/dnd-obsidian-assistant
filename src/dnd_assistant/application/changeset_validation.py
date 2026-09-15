"""S10-02 pure ChangeSet validation and whole-batch preflight.

Provides a single side-effect-free entry point, :func:`validate_changeset`,
that evaluates an already structurally valid Stage-10 :class:`ChangeSet`
against repository state and reports every ordinary semantic failure as
immutable, language-neutral data.

The validator reads the Vault through the ``VaultRepository`` protocol only.
It never mutates the repository, writes audit records or touches the
filesystem.  Whole-batch semantics are modelled with an in-memory projection:

    actual repository state
    + operations processed in order
    -> projected entity/revision state

Repository/programmer failures (corrupt Vault, duplicate persisted IDs,
filesystem errors) are not proposal semantics; they propagate as the existing
project errors raised by the repository.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, cli, tools, pathlib, os
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
    UpdateEntityOperation,
)

if TYPE_CHECKING:
    from dnd_assistant.storage.types import VaultRepository

# ── Validation issue contract ─────────────────────────────────────────────


class ValidationIssueCode(StrEnum):
    """Canonical, language-neutral codes for preflight failures."""

    CREATE_TARGET_EXISTS = "create_target_exists"
    """A ``create_entity`` targets an EntityId already present in the Vault."""

    DUPLICATE_CREATE = "duplicate_create"
    """A ``create_entity`` repeats an EntityId already targeted by an earlier
    create command in the batch, whether or not that earlier command succeeded."""

    TARGET_NOT_FOUND = "target_not_found"
    """An ``update_entity``/``append_fact`` target does not exist in repository
    state or from an earlier create in the same ChangeSet."""

    REVISION_CONFLICT = "revision_conflict"
    """``expected_revision`` does not equal the projected current revision."""


class ValidationIssue(BaseModel):
    """One deterministic preflight problem for one operation.

    ``message`` is a non-authoritative human diagnostic; ``code`` is the
    stable contract consumed by review/apply layers.
    """

    code: ValidationIssueCode
    operation_index: int = Field(ge=0)
    message: str
    entity_id: str | None = None

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class ChangeSetValidationResult(BaseModel):
    """Immutable whole-batch preflight outcome.

    ``issues`` is deterministically ordered by ``operation_index``.  ``valid``
    is derived so it can never disagree with the collected issues.
    """

    issues: tuple[ValidationIssue, ...] = ()

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }

    @property
    def valid(self) -> bool:
        """True when no semantic issue was found."""
        return not self.issues


# ── Projection ────────────────────────────────────────────────────────────


def _base_projection(repository: VaultRepository) -> dict[str, int]:
    """Read one repository snapshot into ``{entity_id: revision}``.

    This is the only repository interaction the validator performs.
    """
    projection: dict[str, int] = {}
    for document in repository.list_entities():
        projection[document.entity.id] = document.entity.revision
    return projection


def _validate_create(
    operation: CreateEntityOperation,
    index: int,
    projection: dict[str, int],
    seen_create_ids: set[str],
) -> ValidationIssue | None:
    """Validate a create against repository snapshot and batch creates.

    Command history (``seen_create_ids``) is independent of the projected
    entity/revision state: an invalid create does not advance ``projection``,
    but it still counts as a previous create command for later duplicate
    diagnosis in the same ChangeSet.
    """
    entity_id = operation.entity_id

    if entity_id in seen_create_ids:
        return ValidationIssue(
            code=ValidationIssueCode.DUPLICATE_CREATE,
            operation_index=index,
            message=f"Entity {entity_id!r} is created more than once in this ChangeSet",
            entity_id=entity_id,
        )

    seen_create_ids.add(entity_id)

    if entity_id in projection:
        return ValidationIssue(
            code=ValidationIssueCode.CREATE_TARGET_EXISTS,
            operation_index=index,
            message=f"Entity {entity_id!r} already exists in the Vault",
            entity_id=entity_id,
        )

    projection[entity_id] = 1
    return None


def _validate_revision_guarded(
    operation: UpdateEntityOperation | AppendFactOperation,
    index: int,
    projection: dict[str, int],
) -> ValidationIssue | None:
    """Validate an update/append target and advance the projection on success."""
    entity_id = operation.entity_id

    if entity_id not in projection:
        return ValidationIssue(
            code=ValidationIssueCode.TARGET_NOT_FOUND,
            operation_index=index,
            message=(
                f"Entity {entity_id!r} does not exist in repository state "
                "or from an earlier create in this ChangeSet"
            ),
            entity_id=entity_id,
        )

    current_revision = projection[entity_id]
    if operation.expected_revision != current_revision:
        return ValidationIssue(
            code=ValidationIssueCode.REVISION_CONFLICT,
            operation_index=index,
            message=(
                f"Expected revision {operation.expected_revision} for entity "
                f"{entity_id!r}, but projected revision is {current_revision}"
            ),
            entity_id=entity_id,
        )

    projection[entity_id] = current_revision + 1
    return None


# ── Public entry point ────────────────────────────────────────────────────


def validate_changeset(
    changeset: ChangeSet,
    repository: VaultRepository,
) -> ChangeSetValidationResult:
    """Validate an entire ChangeSet without performing any mutation.

    Operations are processed in order into an in-memory projection of entity
    revisions.  The projected revision rule mirrors the repository's canonical
    ``+1`` rule, so same-batch dependencies resolve deterministically.

    Args:
        changeset: The structurally valid proposal to preflight.
        repository: Trusted read source for current Vault state.

    Returns:
        A frozen :class:`ChangeSetValidationResult` whose ``issues`` are
        ordered by ``operation_index``.
    """
    projection = _base_projection(repository)
    seen_create_ids: set[str] = set()

    issues: list[ValidationIssue] = []
    for index, operation in enumerate(changeset.operations):
        if isinstance(operation, CreateEntityOperation):
            issue = _validate_create(operation, index, projection, seen_create_ids)
        else:
            issue = _validate_revision_guarded(operation, index, projection)

        if issue is not None:
            issues.append(issue)

    issues.sort(key=lambda issue: issue.operation_index)
    return ChangeSetValidationResult(issues=tuple(issues))
