"""Concrete world-time mutation tools: set_world_time, advance_world_time.

These tools expose the accepted canonical current-world-time mutation
capabilities through the ToolRegistry/ToolExecutor contracts.  They are
thin adapters over two already accepted Python authorities:

    WorldTimeRepository
        -> persistence
        -> optimistic concurrency
        -> revision increment
        -> atomic write
        -> audit

    CalendarService
        -> deterministic elapsed-time arithmetic

Dependency direction:
    domain.calendar, domain.world_time, domain.types,
    storage WorldTimeRepository contract, storage AuditContext typing,
    errors, tools core contracts
    ↓
    this module

Must NOT depend on:
    models, Ollama, Fast Agent, CLI, retrieval, application, ChangeSet,
    post-session processor, provider-specific schemas

Critical invariants:
    Tool Layer does not write world_time.json directly.
    Tool Layer does not calculate revision increments.
    Tool Layer does not write audit.jsonl.
    Tool Layer does not calculate elapsed-time arithmetic independently.
    Tool Layer does not create an in-memory authoritative clock.
    The Vault remains the only Source of Truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.calendar import CalendarService, GameDate, WorldTick
from dnd_assistant.domain.types import Revision
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

if TYPE_CHECKING:
    from dnd_assistant.storage.types import WorldTimeRepository


# ── set_world_time input/output ────────────────────────────────────────────────


class SetWorldTimeInput(BaseModel):
    """Validated input for the ``set_world_time`` tool.

    ``expected_revision=None`` means initialize only — the tool will call
    ``initialize_current_world_time()`` and never overwrite existing state.

    ``expected_revision=N`` (where N is a Revision >= 1) means update
    existing state using optimistic concurrency — the tool will call
    ``set_current_world_time()`` and fail if the stored revision does not
    match.
    """

    world_tick: WorldTick
    """The canonical world tick to set."""

    expected_revision: Revision | None = None
    """``None`` = initialize only; a supplied revision = optimistic update."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class SetWorldTimeOutput(BaseModel):
    """Output for the ``set_world_time`` tool.

    Contains the canonical persisted current world time, the derived
    human/calendar date, and the identity of the calendar used for derivation.
    """

    world_time: CurrentWorldTime
    """Canonical persisted current world time with optimistic-concurrency revision."""

    game_date: GameDate
    """Derived human/calendar date from CalendarService.tick_to_date()."""

    calendar_id: str
    """Identity of the calendar used for date derivation."""

    model_config = {"extra": "forbid", "from_attributes": True}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── advance_world_time input/output ────────────────────────────────────────────


class AdvanceWorldTimeInput(BaseModel):
    """Validated input for the ``advance_world_time`` tool.

    ``minutes`` is a strict signed integer — negative, zero, and positive
    values are accepted.  ``expected_revision`` is mandatory: the caller
    must advance from a state revision it has actually observed.
    """

    minutes: int = Field(strict=True)
    """Signed integer number of game minutes to advance (negative for backward)."""

    expected_revision: Revision
    """The revision the caller last observed (mandatory, never optional)."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class AdvanceWorldTimeOutput(BaseModel):
    """Output for the ``advance_world_time`` tool.

    Contains the canonical persisted current world time after advancement,
    the derived human/calendar date, and the identity of the calendar used
    for derivation.
    """

    world_time: CurrentWorldTime
    """Canonical persisted current world time after advancement."""

    game_date: GameDate
    """Derived human/calendar date from CalendarService.tick_to_date()."""

    calendar_id: str
    """Identity of the calendar used for date derivation."""

    model_config = {"extra": "forbid", "from_attributes": True}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Tool definitions ───────────────────────────────────────────────────────────


_SET_WORLD_TIME_DEFINITION = ToolDefinition(
    name="set_world_time",
    description="Set the canonical current world tick. "
    "Use expected_revision=None to initialize uninitialized state; "
    "use expected_revision=N to update existing state with optimistic concurrency",
    input_schema=SetWorldTimeInput,
    output_schema=SetWorldTimeOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.WORLD_TIME_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_ADVANCE_WORLD_TIME_DEFINITION = ToolDefinition(
    name="advance_world_time",
    description="Advance the canonical current world tick by a signed number of game minutes. "
    "Requires the caller-supplied expected_revision for optimistic concurrency",
    input_schema=AdvanceWorldTimeInput,
    output_schema=AdvanceWorldTimeOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.WORLD_TIME_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)


# ── Handlers ───────────────────────────────────────────────────────────────────


def _set_world_time_handler(
    input_model: SetWorldTimeInput,
    context: ExecutionContext,
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> SetWorldTimeOutput:
    """Set the canonical current world time.

    Two-mode state machine:

    ``expected_revision is None``
        -> call ``initialize_current_world_time()``
        -> existing state => ConflictError
        -> never overwrite

    ``expected_revision is Revision``
        -> call ``set_current_world_time()``
        -> missing state => NotFoundError
        -> stale revision => ConflictError

    Flow:
    1. Delegate to the appropriate repository method based on
       ``expected_revision``.
    2. Derive GameDate from CalendarService using the persisted result.
    3. Return typed result with calendar identity.

    Raises:
        ConflictError: State already exists (initialize) or revision mismatch
            (update).
        NotFoundError: No world_time.json exists (update path).
        StorageError: Storage corruption or filesystem error.
    """
    if input_model.expected_revision is None:
        state = world_time_repository.initialize_current_world_time(
            input_model.world_tick,
            audit=context.audit,
        )
    else:
        state = world_time_repository.set_current_world_time(
            input_model.world_tick,
            expected_revision=input_model.expected_revision,
            audit=context.audit,
        )

    game_date = calendar_service.tick_to_date(state.current_world_tick)
    return SetWorldTimeOutput.model_validate(
        {
            "world_time": state.model_dump(mode="python"),
            "game_date": game_date,
            "calendar_id": calendar_service.definition.calendar_id,
        }
    )


def _advance_world_time_handler(
    input_model: AdvanceWorldTimeInput,
    context: ExecutionContext,
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> AdvanceWorldTimeOutput:
    """Advance the canonical current world time by signed game minutes.

    Canonical flow:
    1. Read canonical CurrentWorldTime from WorldTimeRepository.
    2. Calculate candidate WorldTick using CalendarService.advance_world_time.
    3. Persist through WorldTimeRepository.set_current_world_time with
       the caller-supplied expected_revision (not current.revision).
    4. Derive GameDate from the persisted result.
    5. Return typed result.

    Raises:
        NotFoundError: World time has not been initialized.
        ConflictError: Revision mismatch (stale caller state).
        ValidationError: CalendarService arithmetic validation failure.
        StorageError: Storage corruption or filesystem error.
    """
    current = world_time_repository.get_current_world_time()

    try:
        new_tick = calendar_service.advance_world_time(
            current.current_world_tick,
            minutes=input_model.minutes,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), cause=exc) from exc

    state = world_time_repository.set_current_world_time(
        new_tick,
        expected_revision=input_model.expected_revision,
        audit=context.audit,
    )

    game_date = calendar_service.tick_to_date(state.current_world_tick)
    return AdvanceWorldTimeOutput.model_validate(
        {
            "world_time": state.model_dump(mode="python"),
            "game_date": game_date,
            "calendar_id": calendar_service.definition.calendar_id,
        }
    )


# ── Registration API ───────────────────────────────────────────────────────────


def register_world_time_mutation_tools(
    registry: ToolRegistry,
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> None:
    """Register world-time mutation tools on a ``ToolRegistry``.

    Registers exactly ``set_world_time`` and ``advance_world_time`` with
    their definitions and wired handlers.

    Args:
        registry: A ``ToolRegistry`` instance.
        world_time_repository: A ``WorldTimeRepository`` implementation.
        calendar_service: A ``CalendarService`` implementation.

    Raises:
        ValidationError: The registry is not a ToolRegistry.
        ConflictError: A tool with the same name is already registered.
    """
    if not isinstance(registry, ToolRegistry):
        raise ValidationError("registry must be a ToolRegistry instance")

    def _make_set_world_time_handler(
        input_model: SetWorldTimeInput,
        context: ExecutionContext,
    ) -> SetWorldTimeOutput:
        return _set_world_time_handler(
            input_model,
            context,
            world_time_repository=world_time_repository,
            calendar_service=calendar_service,
        )

    def _make_advance_world_time_handler(
        input_model: AdvanceWorldTimeInput,
        context: ExecutionContext,
    ) -> AdvanceWorldTimeOutput:
        return _advance_world_time_handler(
            input_model,
            context,
            world_time_repository=world_time_repository,
            calendar_service=calendar_service,
        )

    registry.register(_SET_WORLD_TIME_DEFINITION, _make_set_world_time_handler)
    registry.register(_ADVANCE_WORLD_TIME_DEFINITION, _make_advance_world_time_handler)
