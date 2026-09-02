"""Concrete entity read tools: search_entities and get_entity.

These tools expose existing deterministic Python retrieval/storage behaviour
through the ToolRegistry/ToolExecutor contracts.  They are strictly read-only.

Dependency direction:
    domain, retrieval, storage read protocols, errors, tools core contracts
    ↓
    this module

Must NOT depend on:
    models, Ollama, Fast Agent, CLI, post-session processor, ChangeSet,
    provider-specific schemas
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.types import EntityId, EntityType, Visibility
from dnd_assistant.errors import NotFoundError, StorageError, ValidationError
from dnd_assistant.retrieval.types import MatchKind, SearchQuery
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)

if TYPE_CHECKING:
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.storage.types import VaultRepository


# ── search_entities input schema ──────────────────────────────────────────


class SearchEntitiesInput(BaseModel):
    """Validated input for the ``search_entities`` tool.

    Reuses the accepted ``SearchQuery`` validation for ``text`` and
    ``entity_types``.  Additional validation is applied at this tool
    boundary.
    """

    text: str
    """Search query text.  Must be non-empty, printable, strict string."""

    entity_types: set[EntityType] | None = None
    """Optional filter by entity type(s).  ``None`` means no type filter."""

    limit: int = Field(default=20, strict=True, ge=1)
    """Maximum number of results to return (must be >= 1)."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("text must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be empty or whitespace-only")
        if not value.isprintable():
            raise ValueError("text must not contain non-printable characters")
        return value


# ── search_entities output schema ─────────────────────────────────────────


class EntitySearchResult(BaseModel):
    """A single search result with enough context for agent consumption."""

    entity_id: EntityId
    entity_type: EntityType
    name: str
    status: str
    match_kind: MatchKind
    score: float | None = None

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class SearchEntitiesOutput(BaseModel):
    """Ordered list of search results."""

    results: list[EntitySearchResult]

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── get_entity input schema ───────────────────────────────────────────────


class GetEntityInput(BaseModel):
    """Validated input for the ``get_entity`` tool.

    Accepts only a stable ``EntityId``.  No free-text resolution.
    """

    entity_id: EntityId

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── get_entity output schema ──────────────────────────────────────────────


class GetEntityOutput(BaseModel):
    """Full entity document with canonical fields and Markdown body.

    ``extra_frontmatter`` is intentionally excluded from this initial
    tool DTO (deferred — S7-01 does not yet have an accepted stable
    model-facing serialisation contract for arbitrary unknown YAML
    values).
    """

    entity: Entity
    body: str

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Tool definitions ──────────────────────────────────────────────────────


_SEARCH_ENTITIES_DEFINITION = ToolDefinition(
    name="search_entities",
    description="Search campaign entities by text query with optional type filter",
    input_schema=SearchEntitiesInput,
    output_schema=SearchEntitiesOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_GET_ENTITY_DEFINITION = ToolDefinition(
    name="get_entity",
    description="Retrieve a single campaign entity by its stable ID",
    input_schema=GetEntityInput,
    output_schema=GetEntityOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)


# ── Handlers ──────────────────────────────────────────────────────────────


def _search_entities_handler(
    input_model: SearchEntitiesInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> SearchEntitiesOutput:
    """Execute a search query and return hydrated results.

    Flow:
    1. Delegate to SearchService (player-visibility gate).
    2. Hydrate only returned IDs through VaultRepository.
    3. Fail closed on identity/visibility inconsistency.
    4. Preserve SearchService ordering.
    """
    # 1. Construct SearchQuery reusing existing retrieval validation.
    query = SearchQuery(
        text=input_model.text,
        entity_types=input_model.entity_types,
    )

    # 2. Search through the visibility gate.
    hits = search_service.search(query, limit=input_model.limit)

    # 3. Hydrate results, preserving order.
    results: list[EntitySearchResult] = []
    for hit in hits:
        doc = repository.get_entity(hit.entity_id)

        # Fail-closed consistency check.
        if doc.entity.id != hit.entity_id:
            raise StorageError(
                f"Entity ID mismatch: SearchService returned {hit.entity_id!r}, "
                f"repository returned {doc.entity.id!r}"
            )
        if doc.entity.visibility != Visibility.PLAYER:
            raise StorageError(
                f"Entity {hit.entity_id!r} has visibility "
                f"{doc.entity.visibility.value!r}, expected 'player'"
            )

        results.append(
            EntitySearchResult(
                entity_id=doc.entity.id,
                entity_type=doc.entity.type,
                name=doc.entity.name,
                status=doc.entity.status,
                match_kind=hit.match_kind,
                score=hit.score,
            )
        )

    return SearchEntitiesOutput(results=results)


def _get_entity_handler(
    input_model: GetEntityInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> GetEntityOutput:
    """Retrieve a single entity by stable ID through the visibility gate.

    Flow:
    1. SearchService.get_by_id — player-visibility gate.
    2. None → generic NotFoundError (no leak of hidden-vs-missing).
    3. Hydrate through VaultRepository.
    4. Fail-closed consistency check.
    """
    entity_id = input_model.entity_id

    # 1. Visibility gate.
    hit = search_service.get_by_id(entity_id)
    if hit is None:
        raise NotFoundError(f"Entity '{entity_id}' not found or not accessible")

    # 2. Hydrate through repository.
    doc = repository.get_entity(hit.entity_id)

    # 3. Fail-closed consistency check.
    if doc.entity.id != hit.entity_id:
        raise StorageError(
            f"Entity ID mismatch: SearchService returned {hit.entity_id!r}, "
            f"repository returned {doc.entity.id!r}"
        )
    if doc.entity.visibility != Visibility.PLAYER:
        raise StorageError(
            f"Entity {hit.entity_id!r} has visibility "
            f"{doc.entity.visibility.value!r}, expected 'player'"
        )

    return GetEntityOutput(entity=doc.entity, body=doc.body)


# ── Registration API ──────────────────────────────────────────────────────


def register_entity_read_tools(
    registry: object,
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> None:
    """Register entity read tools on a ``ToolRegistry``.

    Registers exactly ``search_entities`` and ``get_entity`` with
    their definitions and wired handlers.

    Args:
        registry: A ``ToolRegistry`` instance.
        search_service: A ``SearchService`` implementation (the
            player-visibility gate).
        repository: A ``VaultRepository`` implementation for entity
            document hydration.

    Raises:
        ValidationError: The registry is not a ToolRegistry or the
            handler wiring is invalid.
        ConflictError: A tool with the same name is already registered.
    """
    # Duck-type check: must have a ``register`` method.
    if not hasattr(registry, "register"):
        raise ValidationError("registry must be a ToolRegistry instance")

    def _make_search_handler(
        input_model: SearchEntitiesInput,
        context: ExecutionContext,
    ) -> SearchEntitiesOutput:
        return _search_entities_handler(
            input_model, context, search_service=search_service, repository=repository
        )

    def _make_get_handler(
        input_model: GetEntityInput,
        context: ExecutionContext,
    ) -> GetEntityOutput:
        return _get_entity_handler(
            input_model, context, search_service=search_service, repository=repository
        )

    registry.register(_SEARCH_ENTITIES_DEFINITION, _make_search_handler)
    registry.register(_GET_ENTITY_DEFINITION, _make_get_handler)
