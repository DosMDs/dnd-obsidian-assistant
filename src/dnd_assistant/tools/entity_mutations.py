"""Concrete entity mutation tools: patch_entity, append_entity_fact.

These tools expose the accepted entity mutation capabilities through the
ToolRegistry/ToolExecutor contracts while preserving:

- stable-ID-only writes;
- player-visibility authorization through SearchService.get_by_id();
- caller-supplied optimistic revision;
- exact AuditContext passthrough;
- VaultRepository ownership of persistence/audit/revision;
- zero fuzzy or ambiguous write resolution.

Dependency direction:
    domain.entity, domain.types, retrieval service/types,
    storage VaultRepository, storage patch, errors, tools core contracts
    ↓
    this module

Must NOT depend on:
    models, Ollama, Fast Agent, CLI, post-session processor, ChangeSet,
    provider-specific schemas, application

Critical invariants:
    Tool Layer does not write Vault files directly.
    Tool Layer does not calculate revision increments.
    Tool Layer does not write audit records.
    Tool Layer does not render Markdown body content.
    Tool Layer does not resolve ambiguous entity references.
    The Vault remains the only Source of Truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, field_validator
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, Revision
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

if TYPE_CHECKING:
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.storage.types import VaultRepository


# ── Fact validation ────────────────────────────────────────────────────────────


def _validate_fact(value: object) -> str:
    """Validate a fact string for ``append_entity_fact``.

    Contract:
    - must be a ``str``;
    - non-empty;
    - no leading/trailing whitespace;
    - printable Unicode (no control characters, no newlines);
    - no embedded newline/control characters.

    Args:
        value: The fact value to validate.

    Returns:
        The validated fact string.

    Raises:
        ValidationError: The value does not satisfy the fact contract.
    """
    if not isinstance(value, str):
        raise ValueError("fact must be a string")
    if not value:
        raise ValueError("fact must not be empty")
    if value.strip() != value:
        raise ValueError("fact must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("fact must not contain non-printable characters")
    return value


# ── Authorization helper ───────────────────────────────────────────────────────


def _authorize_mutation(
    entity_id: EntityId,
    search_service: SearchService,
) -> None:
    """Authorize a mutation target through SearchService player-visibility gate.

    Only ``Visibility.PLAYER`` entities may be mutated.  Hidden (DM, SYSTEM)
    and missing entities produce the same generic ``NotFoundError``.

    Args:
        entity_id: The stable domain identifier of the target entity.
        search_service: The ``SearchService`` to use for authorization.

    Raises:
        NotFoundError: Entity not found or not accessible (generic).
        StorageError: SearchService returned a hit for a different entity ID.
    """
    hit = search_service.get_by_id(entity_id)
    if hit is None:
        raise NotFoundError("Entity not found or not accessible")

    # Fail-closed: the returned hit must match the requested ID.
    if hit.entity_id != entity_id:
        raise StorageError("Entity mutation authorization consistency check failed")


# ── patch_entity input/output ───────────────────────────────────────────────────


class PatchEntityInput(BaseModel):
    """Validated input for the ``patch_entity`` tool.

    Accepts only a stable ``EntityId``, a caller-supplied ``expected_revision``
    for optimistic concurrency, and a canonical ``EntityPatch``.

    No free-text reference, name, alias, or search query is accepted.
    """

    entity_id: EntityId
    """The stable domain identifier of the entity to patch."""

    expected_revision: Revision
    """The revision the caller last observed (mandatory, never optional)."""

    patch: EntityPatch
    """The typed partial update DTO using canonical editable fields."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class PatchEntityOutput(BaseModel):
    """Output for the ``patch_entity`` tool.

    Returns the canonical ``Entity`` and Markdown ``body`` as persisted
    by the repository.  ``extra_frontmatter``, filesystem path, and raw
    YAML are intentionally excluded.
    """

    entity: Entity
    """The canonical persisted Entity after the patch."""

    body: str
    """The Markdown body text (unchanged by patch)."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── append_entity_fact input/output ─────────────────────────────────────────────


class AppendEntityFactInput(BaseModel):
    """Validated input for the ``append_entity_fact`` tool.

    Accepts only a stable ``EntityId``, a caller-supplied ``expected_revision``,
    and a validated ``fact`` string.

    No free-text reference, name, alias, or search query is accepted.
    """

    entity_id: EntityId
    """The stable domain identifier of the entity."""

    expected_revision: Revision
    """The revision the caller last observed (mandatory, never optional)."""

    fact: str
    """The fact text to append.  Validated: non-empty, printable,
    no leading/trailing whitespace, no newlines/control characters."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    @field_validator("fact")
    @classmethod
    def _validate_fact_field(cls, value: object) -> str:
        return _validate_fact(value)


class AppendEntityFactOutput(BaseModel):
    """Output for the ``append_entity_fact`` tool.

    Returns the canonical ``Entity`` and Markdown ``body`` as persisted
    by the repository.  The body includes the appended fact rendered as
    a Markdown bullet by the repository.
    """

    entity: Entity
    """The canonical persisted Entity after the append."""

    body: str
    """The Markdown body text with the appended fact rendered by the repository."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Tool definitions ────────────────────────────────────────────────────────────


_PATCH_ENTITY_DEFINITION = ToolDefinition(
    name="patch_entity",
    description="Patch editable fields of a campaign entity by its stable ID. "
    "Requires the caller-supplied expected_revision for optimistic concurrency. "
    "Only player-visible entities may be patched.",
    input_schema=PatchEntityInput,
    output_schema=PatchEntityOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_APPEND_ENTITY_FACT_DEFINITION = ToolDefinition(
    name="append_entity_fact",
    description="Append a fact to a campaign entity's Markdown body by its stable ID. "
    "Requires the caller-supplied expected_revision for optimistic concurrency. "
    "Only player-visible entities may be modified.",
    input_schema=AppendEntityFactInput,
    output_schema=AppendEntityFactOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)


# ── Handlers ────────────────────────────────────────────────────────────────────


def _patch_entity_handler(
    input_model: PatchEntityInput,
    context: ExecutionContext,
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> PatchEntityOutput:
    """Patch editable fields of a campaign entity.

    Canonical flow:
    1. SearchService.get_by_id — player-visibility authorization.
    2. None or mismatched ID -> generic error, no mutation.
    3. Delegate to VaultRepository.patch_entity with caller-supplied revision.
    4. Verify returned document entity ID matches requested ID.
    5. Return typed output.

    Raises:
        NotFoundError: Entity not found or not accessible.
        ConflictError: Stale expected_revision.
        StorageError: Authorization consistency failure or repository error.
        ValidationError: Invalid input.
    """
    requested_id = input_model.entity_id

    # 1. Player-visibility authorization.
    _authorize_mutation(requested_id, search_service)

    # 2. Delegate to repository with caller-supplied expected_revision.
    document = repository.patch_entity(
        requested_id,
        input_model.patch,
        expected_revision=input_model.expected_revision,
        audit=context.audit,
    )

    # 3. Verify returned document entity ID matches requested ID.
    if document.entity.id != requested_id:
        raise StorageError("Entity mutation consistency check failed")

    return PatchEntityOutput(entity=document.entity, body=document.body)


def _append_entity_fact_handler(
    input_model: AppendEntityFactInput,
    context: ExecutionContext,
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> AppendEntityFactOutput:
    """Append a fact to a campaign entity's Markdown body.

    Canonical flow:
    1. SearchService.get_by_id — player-visibility authorization.
    2. None or mismatched ID -> generic error, no mutation.
    3. Delegate to VaultRepository.append_entity_fact with caller-supplied
       revision and validated fact.
    4. Verify returned document entity ID matches requested ID.
    5. Return typed output.

    The repository owns Markdown bullet rendering, not the Tool Layer.

    Raises:
        NotFoundError: Entity not found or not accessible.
        ConflictError: Stale expected_revision.
        StorageError: Authorization consistency failure or repository error.
        ValidationError: Invalid input.
    """
    requested_id = input_model.entity_id

    # 1. Player-visibility authorization.
    _authorize_mutation(requested_id, search_service)

    # 2. Delegate to repository with caller-supplied expected_revision.
    document = repository.append_entity_fact(
        requested_id,
        expected_revision=input_model.expected_revision,
        fact=input_model.fact,
        audit=context.audit,
    )

    # 3. Verify returned document entity ID matches requested ID.
    if document.entity.id != requested_id:
        raise StorageError("Entity mutation consistency check failed")

    return AppendEntityFactOutput(entity=document.entity, body=document.body)


# ── Registration API ────────────────────────────────────────────────────────────


def register_entity_mutation_tools(
    registry: ToolRegistry,
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> None:
    """Register entity mutation tools on a ``ToolRegistry``.

    Registers exactly ``patch_entity`` and ``append_entity_fact`` with
    their definitions and wired handlers.

    Args:
        registry: A ``ToolRegistry`` instance.
        search_service: A ``SearchService`` implementation (the
            player-visibility gate for mutation authorization).
        repository: A ``VaultRepository`` implementation for entity
            mutation.

    Raises:
        ValidationError: The registry is not a ToolRegistry.
        ConflictError: A tool with the same name is already registered.
    """
    if not isinstance(registry, ToolRegistry):
        raise ValidationError("registry must be a ToolRegistry instance")

    def _make_patch_handler(
        input_model: PatchEntityInput,
        context: ExecutionContext,
    ) -> PatchEntityOutput:
        return _patch_entity_handler(
            input_model,
            context,
            search_service=search_service,
            repository=repository,
        )

    def _make_append_handler(
        input_model: AppendEntityFactInput,
        context: ExecutionContext,
    ) -> AppendEntityFactOutput:
        return _append_entity_fact_handler(
            input_model,
            context,
            search_service=search_service,
            repository=repository,
        )

    registry.register(_PATCH_ENTITY_DEFINITION, _make_patch_handler)
    registry.register(_APPEND_ENTITY_FACT_DEFINITION, _make_append_handler)
