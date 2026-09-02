"""Tests for world-time mutation tool contracts: DTO validation and registration metadata.

Covers:
- Registration metadata (names, permission, side effects, session modes)
- SetWorldTimeInput validation
- SetWorldTimeOutput validation
- AdvanceWorldTimeInput validation
- AdvanceWorldTimeOutput validation
- Registration API
"""

from __future__ import annotations

import pytest

from dnd_assistant.domain.calendar import CalendarDefinition, CalendarMonth, GameDate, WorldTick
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ConflictError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import Permission, SessionMode, SideEffect
from dnd_assistant.tools.world_time_mutations import (
    AdvanceWorldTimeInput,
    AdvanceWorldTimeOutput,
    SetWorldTimeInput,
    SetWorldTimeOutput,
    register_world_time_mutation_tools,
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


# ═══════════════════════════════════════════════════════════════════════════
# Registration metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationMetadata:
    def test_set_world_time_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("set_world_time")
        assert definition.name == "set_world_time"

    def test_advance_world_time_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("advance_world_time")
        assert definition.name == "advance_world_time"

    def test_both_have_write_permission(self, registered_registry: ToolRegistry) -> None:
        for name in ("set_world_time", "advance_world_time"):
            definition = registered_registry.get_definition(name)
            assert definition.permission == Permission.WRITE

    def test_both_have_world_time_mutation_side_effect(
        self, registered_registry: ToolRegistry
    ) -> None:
        expected = frozenset({SideEffect.WORLD_TIME_MUTATION})
        for name in ("set_world_time", "advance_world_time"):
            definition = registered_registry.get_definition(name)
            assert definition.side_effects == expected

    def test_both_allow_both_session_modes(self, registered_registry: ToolRegistry) -> None:
        expected = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
        for name in ("set_world_time", "advance_world_time"):
            definition = registered_registry.get_definition(name)
            assert definition.allowed_session_modes == expected

    def test_set_world_time_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("set_world_time")
        assert definition.input_schema is SetWorldTimeInput
        assert definition.output_schema is SetWorldTimeOutput

    def test_advance_world_time_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("advance_world_time")
        assert definition.input_schema is AdvanceWorldTimeInput
        assert definition.output_schema is AdvanceWorldTimeOutput

    def test_deterministic_registry_listing(self, registered_registry: ToolRegistry) -> None:
        names = [d.name for d in registered_registry.list_definitions()]
        assert names == [
            "advance_world_time",
            "set_world_time",
        ]

    def test_registration_count(self, registered_registry: ToolRegistry) -> None:
        assert len(registered_registry) == 2


# ═══════════════════════════════════════════════════════════════════════════
# SetWorldTimeInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestSetWorldTimeInputValidation:
    def test_negative_tick_valid(self) -> None:
        inp = SetWorldTimeInput(world_tick=-100)
        assert inp.world_tick == -100
        assert inp.expected_revision is None

    def test_zero_tick_valid(self) -> None:
        inp = SetWorldTimeInput(world_tick=0)
        assert inp.world_tick == 0
        assert inp.expected_revision is None

    def test_positive_tick_valid(self) -> None:
        inp = SetWorldTimeInput(world_tick=1000)
        assert inp.world_tick == 1000
        assert inp.expected_revision is None

    def test_expected_revision_omitted_is_none(self) -> None:
        inp = SetWorldTimeInput(world_tick=500)
        assert inp.expected_revision is None

    def test_expected_revision_explicit_none(self) -> None:
        inp = SetWorldTimeInput(world_tick=500, expected_revision=None)
        assert inp.expected_revision is None

    def test_expected_revision_one_accepted(self) -> None:
        inp = SetWorldTimeInput(world_tick=500, expected_revision=1)
        assert inp.expected_revision == 1

    def test_expected_revision_large_accepted(self) -> None:
        inp = SetWorldTimeInput(world_tick=500, expected_revision=42)
        assert inp.expected_revision == 42

    def test_bool_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=True)  # type: ignore[arg-type]

    def test_float_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=1.5)  # type: ignore[arg-type]

    def test_string_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick="100")  # type: ignore[arg-type]

    def test_revision_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=500, expected_revision=0)

    def test_revision_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=500, expected_revision=-1)

    def test_revision_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=500, expected_revision=True)  # type: ignore[arg-type]

    def test_revision_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=500, expected_revision="1")  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SetWorldTimeInput(world_tick=100, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# SetWorldTimeOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestSetWorldTimeOutputValidation:
    def test_valid_output(self) -> None:
        world_time = CurrentWorldTime(
            current_world_tick=WorldTick(1000),
            revision=1,
        )
        game_date = GameDate(year=0, month="Hammer", day=1)
        output = SetWorldTimeOutput(
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
            SetWorldTimeOutput(  # type: ignore[call-arg]
                world_time=world_time,
                game_date=game_date,
                calendar_id="test",
                unknown="x",
            )

    def test_world_time_string_rejected(self) -> None:
        game_date = GameDate(year=0, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            SetWorldTimeOutput(  # type: ignore[arg-type]
                world_time="bad",
                game_date=game_date,
                calendar_id="test",
            )

    def test_game_date_string_rejected(self) -> None:
        world_time = CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
        with pytest.raises(ValidationError):
            SetWorldTimeOutput(  # type: ignore[arg-type]
                world_time=world_time,
                game_date="bad",
                calendar_id="test",
            )


# ═══════════════════════════════════════════════════════════════════════════
# AdvanceWorldTimeInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestAdvanceWorldTimeInputValidation:
    def test_positive_minutes_valid(self) -> None:
        inp = AdvanceWorldTimeInput(minutes=120, expected_revision=1)
        assert inp.minutes == 120
        assert inp.expected_revision == 1

    def test_negative_minutes_valid(self) -> None:
        inp = AdvanceWorldTimeInput(minutes=-30, expected_revision=1)
        assert inp.minutes == -30

    def test_zero_minutes_valid(self) -> None:
        inp = AdvanceWorldTimeInput(minutes=0, expected_revision=1)
        assert inp.minutes == 0

    def test_large_minutes_valid(self) -> None:
        inp = AdvanceWorldTimeInput(minutes=10**9, expected_revision=1)
        assert inp.minutes == 10**9

    def test_bool_minutes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=True, expected_revision=1)  # type: ignore[arg-type]

    def test_float_minutes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=1.5, expected_revision=1)  # type: ignore[arg-type]

    def test_string_minutes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes="120", expected_revision=1)  # type: ignore[arg-type]

    def test_expected_revision_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=10, expected_revision=0)

    def test_expected_revision_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=10, expected_revision=-1)

    def test_expected_revision_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=10, expected_revision=True)  # type: ignore[arg-type]

    def test_expected_revision_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=10, expected_revision="1")  # type: ignore[arg-type]

    def test_expected_revision_none_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(minutes=10, expected_revision=None)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdvanceWorldTimeInput(  # type: ignore[call-arg]
                minutes=10, expected_revision=1, unknown="x"
            )


# ═══════════════════════════════════════════════════════════════════════════
# AdvanceWorldTimeOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestAdvanceWorldTimeOutputValidation:
    def test_valid_output(self) -> None:
        world_time = CurrentWorldTime(
            current_world_tick=WorldTick(1000),
            revision=2,
        )
        game_date = GameDate(year=0, month="Hammer", day=1)
        output = AdvanceWorldTimeOutput(
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
            AdvanceWorldTimeOutput(  # type: ignore[call-arg]
                world_time=world_time,
                game_date=game_date,
                calendar_id="test",
                unknown="x",
            )

    def test_world_time_string_rejected(self) -> None:
        game_date = GameDate(year=0, month="Hammer", day=1)
        with pytest.raises(ValidationError):
            AdvanceWorldTimeOutput(  # type: ignore[arg-type]
                world_time="bad",
                game_date=game_date,
                calendar_id="test",
            )

    def test_game_date_string_rejected(self) -> None:
        world_time = CurrentWorldTime(current_world_tick=WorldTick(0), revision=1)
        with pytest.raises(ValidationError):
            AdvanceWorldTimeOutput(  # type: ignore[arg-type]
                world_time=world_time,
                game_date="bad",
                calendar_id="test",
            )


# ═══════════════════════════════════════════════════════════════════════════
# Registration API
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationAPI:
    def test_non_toolregistry_rejected(self) -> None:
        with pytest.raises(ValidationError, match="registry must be a ToolRegistry"):
            register_world_time_mutation_tools(
                registry="not-a-registry",  # type: ignore[arg-type]
                world_time_repository=FakeWorldTimeRepository(),
                calendar_service=FakeCalendarService(),
            )

    def test_duplicate_registration_rejected(self, registry: ToolRegistry) -> None:
        register_world_time_mutation_tools(
            registry,
            world_time_repository=FakeWorldTimeRepository(),
            calendar_service=FakeCalendarService(),
        )
        with pytest.raises(ConflictError, match="already registered"):
            register_world_time_mutation_tools(
                registry,
                world_time_repository=FakeWorldTimeRepository(),
                calendar_service=FakeCalendarService(),
            )


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(registry: ToolRegistry) -> ToolRegistry:
    register_world_time_mutation_tools(
        registry,
        world_time_repository=FakeWorldTimeRepository(),
        calendar_service=FakeCalendarService(),
    )
    return registry
