"""Tests for world-time read tool contracts: DTO validation and registration metadata.

Covers:
- Registration metadata (names, permission, side effects, session modes)
- GetWorldTimeInput/Output validation
- WorldTickToDateInput/Output validation
- GameDateToWorldTickInput/Output validation
- TimeBetweenWorldTicksInput/Output validation
- Registration API
"""

from __future__ import annotations

import pytest

from dnd_assistant.domain.calendar import CalendarDefinition, CalendarMonth, GameDate, WorldTick
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ConflictError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import Permission, SessionMode
from dnd_assistant.tools.world_time_reads import (
    GameDateToWorldTickInput,
    GameDateToWorldTickOutput,
    GetWorldTimeInput,
    GetWorldTimeOutput,
    TimeBetweenWorldTicksInput,
    TimeBetweenWorldTicksOutput,
    WorldTickToDateInput,
    WorldTickToDateOutput,
    register_world_time_read_tools,
)

# ── Fake implementations for registration tests ───────────────────────────


class FakeWorldTimeRepository:
    """Minimal fake implementing WorldTimeRepository protocol for registration tests."""

    def __init__(self) -> None:
        self._state: CurrentWorldTime | None = None

    def set_state(self, state: CurrentWorldTime | None) -> None:
        self._state = state

    def get_current_world_time(self) -> CurrentWorldTime:
        if self._state is None:
            msg = "world_time.json not found"
            raise LookupError(msg)
        return self._state

    def initialize_current_world_time(self, *args: object, **kwargs: object) -> object:
        msg = "FakeWorldTimeRepository does not support initialize"
        raise NotImplementedError(msg)

    def set_current_world_time(self, *args: object, **kwargs: object) -> object:
        msg = "FakeWorldTimeRepository does not support set"
        raise NotImplementedError(msg)


class FakeCalendarService:
    """Minimal fake implementing CalendarService protocol for registration tests."""

    def __init__(self) -> None:
        self._definition = CalendarDefinition(
            calendar_id="test_calendar",
            epoch=GameDate(year=0, month="Hammer", day=1),
            months=(CalendarMonth(name="Hammer", days=30),),
        )

    @property
    def definition(self) -> CalendarDefinition:
        return self._definition

    def tick_to_date(self, tick: int) -> GameDate:
        return GameDate(year=0, month="Hammer", day=1, hour=0, minute=0)

    def date_to_tick(self, date: GameDate) -> int:
        return 0

    def time_until(self, start_tick: int, end_tick: int) -> int:
        return int(end_tick - start_tick)

    def advance_world_time(self, current_tick: int, *, minutes: int) -> int:
        return current_tick + minutes

    def events_between(self, events, start_tick, end_tick):
        return ()

    def events_near(self, events, event, *, radius):
        return ()

    def upcoming(self, events, current_tick, *, days):
        return ()

    def overdue_events(self, events, current_tick):
        return ()

    def time_until_event(self, current_tick, event):
        return None


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(registry: ToolRegistry) -> ToolRegistry:
    register_world_time_read_tools(
        registry,
        world_time_repository=FakeWorldTimeRepository(),
        calendar_service=FakeCalendarService(),
    )
    return registry


# ═══════════════════════════════════════════════════════════════════════════
# Registration metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationMetadata:
    def test_get_world_time_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_world_time")
        assert definition.name == "get_world_time"

    def test_world_tick_to_date_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("world_tick_to_date")
        assert definition.name == "world_tick_to_date"

    def test_game_date_to_world_tick_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("game_date_to_world_tick")
        assert definition.name == "game_date_to_world_tick"

    def test_time_between_world_ticks_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("time_between_world_ticks")
        assert definition.name == "time_between_world_ticks"

    def test_all_have_read_permission(self, registered_registry: ToolRegistry) -> None:
        for name in (
            "get_world_time",
            "world_tick_to_date",
            "game_date_to_world_tick",
            "time_between_world_ticks",
        ):
            definition = registered_registry.get_definition(name)
            assert definition.permission == Permission.READ

    def test_all_have_empty_side_effects(self, registered_registry: ToolRegistry) -> None:
        for name in (
            "get_world_time",
            "world_tick_to_date",
            "game_date_to_world_tick",
            "time_between_world_ticks",
        ):
            definition = registered_registry.get_definition(name)
            assert definition.side_effects == frozenset()

    def test_all_allow_both_session_modes(self, registered_registry: ToolRegistry) -> None:
        expected = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
        for name in (
            "get_world_time",
            "world_tick_to_date",
            "game_date_to_world_tick",
            "time_between_world_ticks",
        ):
            definition = registered_registry.get_definition(name)
            assert definition.allowed_session_modes == expected

    def test_get_world_time_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_world_time")
        assert definition.input_schema is GetWorldTimeInput
        assert definition.output_schema is GetWorldTimeOutput

    def test_world_tick_to_date_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("world_tick_to_date")
        assert definition.input_schema is WorldTickToDateInput
        assert definition.output_schema is WorldTickToDateOutput

    def test_game_date_to_world_tick_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("game_date_to_world_tick")
        assert definition.input_schema is GameDateToWorldTickInput
        assert definition.output_schema is GameDateToWorldTickOutput

    def test_time_between_world_ticks_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("time_between_world_ticks")
        assert definition.input_schema is TimeBetweenWorldTicksInput
        assert definition.output_schema is TimeBetweenWorldTicksOutput

    def test_deterministic_registry_listing(self, registered_registry: ToolRegistry) -> None:
        names = [d.name for d in registered_registry.list_definitions()]
        assert names == [
            "game_date_to_world_tick",
            "get_world_time",
            "time_between_world_ticks",
            "world_tick_to_date",
        ]

    def test_registration_count(self, registered_registry: ToolRegistry) -> None:
        assert len(registered_registry) == 4


# ═══════════════════════════════════════════════════════════════════════════
# GetWorldTimeInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetWorldTimeInputValidation:
    def test_empty_input_valid(self) -> None:
        inp = GetWorldTimeInput()
        assert inp.model_dump() == {}

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetWorldTimeInput(unknown="x")  # type: ignore[call-arg]

    def test_world_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetWorldTimeInput(world_tick=100)  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# GetWorldTimeOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetWorldTimeOutputValidation:
    def test_valid_output(self) -> None:
        world_time = CurrentWorldTime(
            current_world_tick=WorldTick(1000),
            revision=1,
        )
        game_date = GameDate(year=0, month="Hammer", day=1)
        output = GetWorldTimeOutput(
            world_time=world_time,
            game_date=game_date,
            calendar_id="test_calendar",
        )
        assert output.world_time == world_time
        assert output.game_date == game_date
        assert output.calendar_id == "test_calendar"

    def test_extra_fields_rejected(self) -> None:
        world_time = CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
        game_date = GameDate(year=0, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            GetWorldTimeOutput(  # type: ignore[call-arg]
                world_time=world_time,
                game_date=game_date,
                calendar_id="test",
                unknown="x",
            )

    def test_world_time_string_rejected(self) -> None:
        game_date = GameDate(year=0, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            GetWorldTimeOutput(  # type: ignore[arg-type]
                world_time="bad",
                game_date=game_date,
                calendar_id="test",
            )

    def test_game_date_string_rejected(self) -> None:
        world_time = CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
        with pytest.raises(ValidationError):
            GetWorldTimeOutput(  # type: ignore[arg-type]
                world_time=world_time,
                game_date="bad",
                calendar_id="test",
            )


# ═══════════════════════════════════════════════════════════════════════════
# WorldTickToDateInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestWorldTickToDateInputValidation:
    def test_negative_tick_valid(self) -> None:
        inp = WorldTickToDateInput(world_tick=-100)
        assert inp.world_tick == -100

    def test_zero_tick_valid(self) -> None:
        inp = WorldTickToDateInput(world_tick=0)
        assert inp.world_tick == 0

    def test_positive_tick_valid(self) -> None:
        inp = WorldTickToDateInput(world_tick=1000)
        assert inp.world_tick == 1000

    def test_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorldTickToDateInput(world_tick=True)  # type: ignore[arg-type]

    def test_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorldTickToDateInput(world_tick=1.5)  # type: ignore[arg-type]

    def test_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorldTickToDateInput(world_tick="100")  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorldTickToDateInput(world_tick=100, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# WorldTickToDateOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestWorldTickToDateOutputValidation:
    def test_valid_output(self) -> None:
        game_date = GameDate(year=0, month="Hammer", day=1)
        output = WorldTickToDateOutput(game_date=game_date, calendar_id="test")
        assert output.game_date == game_date
        assert output.calendar_id == "test"

    def test_extra_fields_rejected(self) -> None:
        game_date = GameDate(year=0, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            WorldTickToDateOutput(  # type: ignore[call-arg]
                game_date=game_date, calendar_id="test", unknown="x"
            )

    def test_game_date_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorldTickToDateOutput(game_date="bad", calendar_id="test")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# GameDateToWorldTickInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGameDateToWorldTickInputValidation:
    def test_valid_regular_date(self) -> None:
        game_date = GameDate(year=1492, month="Hammer", day=1)
        inp = GameDateToWorldTickInput(game_date=game_date)
        assert inp.game_date == game_date

    def test_valid_intercalary_date(self) -> None:
        game_date = GameDate(year=1492, intercalary_day="Midwinter")
        inp = GameDateToWorldTickInput(game_date=game_date)
        assert inp.game_date == game_date

    def test_extra_fields_rejected(self) -> None:
        game_date = GameDate(year=0, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            GameDateToWorldTickInput(game_date=game_date, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# GameDateToWorldTickOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGameDateToWorldTickOutputValidation:
    def test_valid_output(self) -> None:
        output = GameDateToWorldTickOutput(world_tick=WorldTick(500), calendar_id="test")
        assert output.world_tick == 500
        assert output.calendar_id == "test"

    def test_negative_tick_valid(self) -> None:
        output = GameDateToWorldTickOutput(world_tick=WorldTick(-100), calendar_id="test")
        assert output.world_tick == -100

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GameDateToWorldTickOutput(  # type: ignore[call-arg]
                world_tick=WorldTick(0), calendar_id="test", unknown="x"
            )

    def test_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GameDateToWorldTickOutput(world_tick=True, calendar_id="test")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# TimeBetweenWorldTicksInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeBetweenWorldTicksInputValidation:
    def test_valid_ticks(self) -> None:
        inp = TimeBetweenWorldTicksInput(start_tick=100, end_tick=200)
        assert inp.start_tick == 100
        assert inp.end_tick == 200

    def test_negative_ticks_valid(self) -> None:
        inp = TimeBetweenWorldTicksInput(start_tick=-100, end_tick=-50)
        assert inp.start_tick == -100
        assert inp.end_tick == -50

    def test_zero_ticks_valid(self) -> None:
        inp = TimeBetweenWorldTicksInput(start_tick=0, end_tick=0)
        assert inp.start_tick == 0
        assert inp.end_tick == 0

    def test_bool_start_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksInput(start_tick=True, end_tick=0)  # type: ignore[arg-type]

    def test_string_end_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksInput(start_tick=0, end_tick="100")  # type: ignore[arg-type]

    def test_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksInput(start_tick=0.5, end_tick=100)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksInput(start_tick=0, end_tick=0, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# TimeBetweenWorldTicksOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeBetweenWorldTicksOutputValidation:
    def test_positive_delta(self) -> None:
        output = TimeBetweenWorldTicksOutput(minutes=300)
        assert output.minutes == 300

    def test_negative_delta(self) -> None:
        output = TimeBetweenWorldTicksOutput(minutes=-150)
        assert output.minutes == -150

    def test_zero_delta(self) -> None:
        output = TimeBetweenWorldTicksOutput(minutes=0)
        assert output.minutes == 0

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksOutput(minutes=100, unknown="x")  # type: ignore[call-arg]

    def test_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksOutput(minutes=True)  # type: ignore[arg-type]

    def test_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksOutput(minutes=1.5)  # type: ignore[arg-type]

    def test_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimeBetweenWorldTicksOutput(minutes="100")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# Registration API
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationAPI:
    def test_non_toolregistry_rejected(self) -> None:
        with pytest.raises(ValidationError, match="registry must be a ToolRegistry"):
            register_world_time_read_tools(
                registry="not-a-registry",  # type: ignore[arg-type]
                world_time_repository=FakeWorldTimeRepository(),
                calendar_service=FakeCalendarService(),
            )

    def test_duplicate_registration_rejected(self, registry: ToolRegistry) -> None:
        register_world_time_read_tools(
            registry,
            world_time_repository=FakeWorldTimeRepository(),
            calendar_service=FakeCalendarService(),
        )
        with pytest.raises(ConflictError, match="already registered"):
            register_world_time_read_tools(
                registry,
                world_time_repository=FakeWorldTimeRepository(),
                calendar_service=FakeCalendarService(),
            )
