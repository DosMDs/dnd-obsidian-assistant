"""Concrete world-time read tools: get_world_time, world_tick_to_date, game_date_to_world_tick, time_between_world_ticks.

These tools expose the accepted persisted current-world-time read contract and
deterministic CalendarService read surface through the ToolRegistry/ToolExecutor
contracts.  They are strictly read-only.

Dependency direction:
    domain.calendar, domain.world_time, storage world-time read contract,
    errors, tools core contracts
    ↓
    this module

Must NOT depend on:
    models, Ollama, Fast Agent, CLI, retrieval, application, ChangeSet,
    post-session processor, provider-specific schemas

Critical invariant:
    Persisted current time belongs only to WorldTimeRepository.
    Calendar/date arithmetic belongs only to CalendarService.
    GameDate is always derived from canonical WorldTick.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.calendar import CalendarService, GameDate, WorldTick
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)

if TYPE_CHECKING:
    from dnd_assistant.storage.types import WorldTimeRepository


# ── get_world_time input/output ──────────────────────────────────────────────


class GetWorldTimeInput(BaseModel):
    """Validated input for the ``get_world_time`` tool.

    No fields — empty input only.  No user-supplied world_tick, revision,
    game_date, or calendar_id.
    """

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class GetWorldTimeOutput(BaseModel):
    """Output for the ``get_world_time`` tool.

    Contains the canonical persisted current world time, the derived
    human/calendar date, and the identity of the calendar used for derivation.
    """

    world_time: CurrentWorldTime
    """Canonical persisted current world time with optimistic-concurrency revision."""

    game_date: GameDate
    """Derived human/calendar date from CalendarService.tick_to_date()."""

    calendar_id: str
    """Identity of the calendar used for date derivation."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── world_tick_to_date input/output ──────────────────────────────────────────


class WorldTickToDateInput(BaseModel):
    """Validated input for the ``world_tick_to_date`` tool.

    Accepts a canonical ``WorldTick`` for pure deterministic date conversion.
    """

    world_tick: WorldTick

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class WorldTickToDateOutput(BaseModel):
    """Output for the ``world_tick_to_date`` tool.

    Contains the derived ``GameDate`` and the calendar identity.
    """

    game_date: GameDate
    """The canonical GameDate derived from the input WorldTick."""

    calendar_id: str
    """Identity of the calendar used for conversion."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── game_date_to_world_tick input/output ─────────────────────────────────────


class GameDateToWorldTickInput(BaseModel):
    """Validated input for the ``game_date_to_world_tick`` tool.

    Accepts a canonical ``GameDate`` for pure deterministic reverse conversion.
    A structurally valid GameDate may still be invalid for the injected
    calendar definition (unknown month, day beyond month length, etc.).
    """

    game_date: GameDate

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class GameDateToWorldTickOutput(BaseModel):
    """Output for the ``game_date_to_world_tick`` tool.

    Contains the canonical ``WorldTick`` and the calendar identity.
    """

    world_tick: WorldTick
    """The canonical WorldTick derived from the input GameDate."""

    calendar_id: str
    """Identity of the calendar used for conversion."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── time_between_world_ticks input/output ────────────────────────────────────


class TimeBetweenWorldTicksInput(BaseModel):
    """Validated input for the ``time_between_world_ticks`` tool.

    Accepts two canonical ``WorldTick`` values for signed minute arithmetic.
    """

    start_tick: WorldTick
    """The starting world tick."""

    end_tick: WorldTick
    """The ending world tick."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class TimeBetweenWorldTicksOutput(BaseModel):
    """Output for the ``time_between_world_ticks`` tool.

    Contains the signed minute difference between the two ticks.
    Positive means end_tick is after start_tick; negative means end_tick
    is before start_tick; zero means same tick.
    """

    minutes: int = Field(strict=True)
    """Signed integer difference in game minutes."""

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Tool definitions ─────────────────────────────────────────────────────────


_GET_WORLD_TIME_DEFINITION = ToolDefinition(
    name="get_world_time",
    description="Return the canonical persisted current world time with derived game date",
    input_schema=GetWorldTimeInput,
    output_schema=GetWorldTimeOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_WORLD_TICK_TO_DATE_DEFINITION = ToolDefinition(
    name="world_tick_to_date",
    description="Convert a canonical WorldTick to its GameDate using the configured calendar",
    input_schema=WorldTickToDateInput,
    output_schema=WorldTickToDateOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_GAME_DATE_TO_WORLD_TICK_DEFINITION = ToolDefinition(
    name="game_date_to_world_tick",
    description="Convert a GameDate to its canonical WorldTick using the configured calendar",
    input_schema=GameDateToWorldTickInput,
    output_schema=GameDateToWorldTickOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_TIME_BETWEEN_WORLD_TICKS_DEFINITION = ToolDefinition(
    name="time_between_world_ticks",
    description="Return the signed number of game minutes between two WorldTick values",
    input_schema=TimeBetweenWorldTicksInput,
    output_schema=TimeBetweenWorldTicksOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)


# ── Handlers ─────────────────────────────────────────────────────────────────


def _get_world_time_handler(
    input_model: GetWorldTimeInput,  # noqa: ARG001
    context: ExecutionContext,  # noqa: ARG001
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> GetWorldTimeOutput:
    """Return the canonical persisted current world time with derived game date.

    Flow:
    1. Read canonical persisted state from WorldTimeRepository.
    2. Derive GameDate from CalendarService.
    3. Return typed result with calendar identity.

    Raises:
        NotFoundError: World time has not been initialized.
        StorageError: Storage corruption or filesystem error.
    """
    world_time = world_time_repository.get_current_world_time()
    game_date = calendar_service.tick_to_date(world_time.current_world_tick)
    return GetWorldTimeOutput(
        world_time=world_time,
        game_date=game_date,
        calendar_id=calendar_service.definition.calendar_id,
    )


def _world_tick_to_date_handler(
    input_model: WorldTickToDateInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    calendar_service: CalendarService,
) -> WorldTickToDateOutput:
    """Convert a canonical WorldTick to its GameDate.

    Pure deterministic CalendarService read.  Does NOT access
    WorldTimeRepository.
    """
    game_date = calendar_service.tick_to_date(input_model.world_tick)
    return WorldTickToDateOutput(
        game_date=game_date,
        calendar_id=calendar_service.definition.calendar_id,
    )


def _game_date_to_world_tick_handler(
    input_model: GameDateToWorldTickInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    calendar_service: CalendarService,
) -> GameDateToWorldTickOutput:
    """Convert a GameDate to its canonical WorldTick.

    Pure deterministic CalendarService read.  Does NOT access
    WorldTimeRepository.

    Definition-dependent invalid dates (unknown month, day beyond month
    length, etc.) raise ``ValueError`` from CalendarService, which is
    translated to project ``ValidationError`` at this boundary.
    """
    try:
        world_tick = calendar_service.date_to_tick(input_model.game_date)
    except ValueError as exc:
        raise ValidationError(str(exc), cause=exc) from exc

    return GameDateToWorldTickOutput(
        world_tick=world_tick,
        calendar_id=calendar_service.definition.calendar_id,
    )


def _time_between_world_ticks_handler(
    input_model: TimeBetweenWorldTicksInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    calendar_service: CalendarService,
) -> TimeBetweenWorldTicksOutput:
    """Return the signed number of game minutes between two WorldTick values.

    Pure deterministic CalendarService read.  Does NOT access
    WorldTimeRepository.  CalendarService remains the arithmetic authority.
    """
    minutes = calendar_service.time_until(
        input_model.start_tick,
        input_model.end_tick,
    )
    return TimeBetweenWorldTicksOutput(minutes=minutes)


# ── Registration API ─────────────────────────────────────────────────────────


def register_world_time_read_tools(
    registry: ToolRegistry,
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> None:
    """Register world-time read tools on a ``ToolRegistry``.

    Registers exactly ``get_world_time``, ``world_tick_to_date``,
    ``game_date_to_world_tick``, and ``time_between_world_ticks`` with their
    definitions and wired handlers.

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

    def _make_get_world_time_handler(
        input_model: GetWorldTimeInput,
        context: ExecutionContext,
    ) -> GetWorldTimeOutput:
        return _get_world_time_handler(
            input_model,
            context,
            world_time_repository=world_time_repository,
            calendar_service=calendar_service,
        )

    def _make_world_tick_to_date_handler(
        input_model: WorldTickToDateInput,
        context: ExecutionContext,
    ) -> WorldTickToDateOutput:
        return _world_tick_to_date_handler(
            input_model,
            context,
            calendar_service=calendar_service,
        )

    def _make_game_date_to_world_tick_handler(
        input_model: GameDateToWorldTickInput,
        context: ExecutionContext,
    ) -> GameDateToWorldTickOutput:
        return _game_date_to_world_tick_handler(
            input_model,
            context,
            calendar_service=calendar_service,
        )

    def _make_time_between_world_ticks_handler(
        input_model: TimeBetweenWorldTicksInput,
        context: ExecutionContext,
    ) -> TimeBetweenWorldTicksOutput:
        return _time_between_world_ticks_handler(
            input_model,
            context,
            calendar_service=calendar_service,
        )

    registry.register(_GET_WORLD_TIME_DEFINITION, _make_get_world_time_handler)
    registry.register(_WORLD_TICK_TO_DATE_DEFINITION, _make_world_tick_to_date_handler)
    registry.register(_GAME_DATE_TO_WORLD_TICK_DEFINITION, _make_game_date_to_world_tick_handler)
    registry.register(_TIME_BETWEEN_WORLD_TICKS_DEFINITION, _make_time_between_world_ticks_handler)
