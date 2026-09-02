"""Tests for session mutation tool contracts: DTO validation and registration metadata.

Covers:
- Registration metadata (names, permission, side effects, session modes)
- StartSessionInput/Output validation
- RecordEventInput/Output validation
- RecordNoteInput/Output validation
- EndSessionInput/Output validation
- Registration API
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_mutations import (
    EndSessionInput,
    EndSessionOutput,
    RecordEventInput,
    RecordEventOutput,
    RecordNoteInput,
    RecordNoteOutput,
    StartSessionInput,
    StartSessionOutput,
    register_session_mutation_tools,
)
from dnd_assistant.tools.session_reads import SessionEventResult
from dnd_assistant.tools.types import Permission, SessionMode, SideEffect

# ── Shared test data ──────────────────────────────────────────────────────────

_NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _make_session(session_id: str = "S001", status: str = "active") -> Session:
    return Session(
        id=session_id,
        type="session",
        status=status,
        real_started_at=_NOW,
        real_finished_at=None,
        world_tick_start=WorldTick(1000),
        world_tick_end=None,
        processed=False,
        processed_model_profile=None,
        revision=1,
    )


# ── Fake services for registration tests ──────────────────────────────────────


class FakeRuntimeService:
    """Minimal fake implementing SessionRuntimeService protocol."""

    def __init__(self) -> None:
        self._active: Session | None = None

    def set_active_session(self, session: Session | None) -> None:
        self._active = session

    def get_active_session(self) -> Session | None:
        return self._active

    def start_session(self, *, audit: object) -> Session:
        return _make_session()

    def record_event(
        self, event_type: str, *, extra_fields: object = None, audit: object = None
    ) -> object:
        return _make_raw_event(event_type, extra_fields)

    def record_note(self, text: str, *, audit: object = None) -> object:
        return _make_raw_event("note", {"text": text})

    def end_session(self, *, touched_entity_ids: object = (), audit: object = None) -> Session:
        return _make_session(status="completed")


def _make_raw_event(event_type: str, extra_fields: object = None) -> object:
    """Create a minimal RawSessionEvent-like object."""
    from types import SimpleNamespace

    return SimpleNamespace(
        event_id="evt_001",
        real_time=_NOW,
        world_tick=WorldTick(1000),
        type=event_type,
        extra_fields=dict(extra_fields) if extra_fields else {},
    )


class FakeRecoveryService:
    """Minimal fake implementing SessionRecoveryService protocol."""

    def __init__(self) -> None:
        self._has_issues = False
        self._inspect_calls = 0
        self._repair_audit_calls = 0
        self._cleanup_calls = 0
        self._repair_event_calls = 0

    def set_has_issues(self, value: bool) -> None:
        self._has_issues = value

    @property
    def inspect_calls(self) -> int:
        return self._inspect_calls

    @property
    def repair_audit_calls(self) -> int:
        return self._repair_audit_calls

    @property
    def cleanup_calls(self) -> int:
        return self._cleanup_calls

    @property
    def repair_event_calls(self) -> int:
        return self._repair_event_calls

    def inspect_runtime(self) -> object:
        self._inspect_calls += 1
        from types import SimpleNamespace

        return SimpleNamespace(has_issues=self._has_issues, issues=[])

    def repair_audit_tail(self, *, audit: object = None) -> object:
        self._repair_audit_calls += 1
        return None

    def cleanup_partial_start(self, session_id: str, *, audit: object = None) -> object:
        self._cleanup_calls += 1
        return None

    def repair_event_tail(self, session_id: str, *, audit: object = None) -> object:
        self._repair_event_calls += 1
        return None


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(registry: ToolRegistry) -> ToolRegistry:
    register_session_mutation_tools(
        registry,
        runtime_service=FakeRuntimeService(),
        recovery_service=FakeRecoveryService(),
    )
    return registry


# ═══════════════════════════════════════════════════════════════════════════════
# Registration metadata
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegistrationMetadata:
    def test_start_session_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("start_session")
        assert definition.name == "start_session"

    def test_record_event_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("record_event")
        assert definition.name == "record_event"

    def test_record_note_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("record_note")
        assert definition.name == "record_note"

    def test_end_session_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("end_session")
        assert definition.name == "end_session"

    def test_all_have_write_permission(self, registered_registry: ToolRegistry) -> None:
        for name in ("start_session", "record_event", "record_note", "end_session"):
            definition = registered_registry.get_definition(name)
            assert definition.permission == Permission.WRITE

    def test_all_have_session_mutation_side_effect(self, registered_registry: ToolRegistry) -> None:
        expected = frozenset({SideEffect.SESSION_MUTATION})
        for name in ("start_session", "record_event", "record_note", "end_session"):
            definition = registered_registry.get_definition(name)
            assert definition.side_effects == expected

    def test_start_session_mode_no_active_only(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("start_session")
        assert definition.allowed_session_modes == frozenset({SessionMode.NO_ACTIVE_SESSION})

    def test_record_event_mode_active_only(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("record_event")
        assert definition.allowed_session_modes == frozenset({SessionMode.ACTIVE_SESSION})

    def test_record_note_mode_active_only(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("record_note")
        assert definition.allowed_session_modes == frozenset({SessionMode.ACTIVE_SESSION})

    def test_end_session_mode_active_only(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("end_session")
        assert definition.allowed_session_modes == frozenset({SessionMode.ACTIVE_SESSION})

    def test_start_session_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("start_session")
        assert definition.input_schema is StartSessionInput
        assert definition.output_schema is StartSessionOutput

    def test_record_event_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("record_event")
        assert definition.input_schema is RecordEventInput
        assert definition.output_schema is RecordEventOutput

    def test_record_note_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("record_note")
        assert definition.input_schema is RecordNoteInput
        assert definition.output_schema is RecordNoteOutput

    def test_end_session_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("end_session")
        assert definition.input_schema is EndSessionInput
        assert definition.output_schema is EndSessionOutput

    def test_deterministic_registry_listing(self, registered_registry: ToolRegistry) -> None:
        names = [d.name for d in registered_registry.list_definitions()]
        assert names == [
            "end_session",
            "record_event",
            "record_note",
            "start_session",
        ]

    def test_registration_count(self, registered_registry: ToolRegistry) -> None:
        assert len(registered_registry) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# StartSessionInput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartSessionInputValidation:
    def test_empty_input_valid(self) -> None:
        inp = StartSessionInput()
        assert inp.model_dump() == {}

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StartSessionInput(unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
# StartSessionOutput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartSessionOutputValidation:
    def test_with_session(self) -> None:
        session = _make_session()
        output = StartSessionOutput(session=session)
        assert output.session is session

    def test_extra_fields_rejected(self) -> None:
        session = _make_session()
        with pytest.raises(ValidationError):
            StartSessionOutput(session=session, unknown="x")  # type: ignore[call-arg]

    def test_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StartSessionOutput(session="not-a-session")  # type: ignore[arg-type]

    def test_incomplete_dict_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StartSessionOutput(session={"id": "incomplete"})  # type: ignore[arg-type]

    def test_none_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StartSessionOutput(session=None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# RecordEventInput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordEventInputValidation:
    def test_valid_input(self) -> None:
        inp = RecordEventInput(event_type="item_acquired")
        assert inp.event_type == "item_acquired"
        assert inp.extra_fields is None

    def test_valid_input_with_extra_fields(self) -> None:
        inp = RecordEventInput(
            event_type="combat",
            extra_fields={"damage": 15, "target": "goblin"},
        )
        assert inp.event_type == "combat"
        assert inp.extra_fields == {"damage": 15, "target": "goblin"}

    def test_unicode_event_type_accepted(self) -> None:
        inp = RecordEventInput(event_type="событие")
        assert inp.event_type == "событие"

    def test_empty_event_type_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            RecordEventInput(event_type="")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            RecordEventInput(event_type="   ")

    def test_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            RecordEventInput(event_type="  event")

    def test_trailing_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            RecordEventInput(event_type="event  ")

    def test_control_characters_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-printable"):
            RecordEventInput(event_type="bad\x00event")

    def test_non_string_event_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordEventInput(event_type=123)  # type: ignore[arg-type]

    def test_extra_fields_none_accepted(self) -> None:
        inp = RecordEventInput(event_type="test", extra_fields=None)
        assert inp.extra_fields is None

    def test_empty_dict_accepted(self) -> None:
        inp = RecordEventInput(event_type="test", extra_fields={})
        assert inp.extra_fields == {}

    def test_nested_json_values_accepted(self) -> None:
        inp = RecordEventInput(
            event_type="test",
            extra_fields={
                "bool": True,
                "int": 42,
                "float": 3.14,
                "string": "hello",
                "list": [1, 2, 3],
                "dict": {"nested": "value"},
                "null": None,
            },
        )
        assert inp.extra_fields["bool"] is True
        assert inp.extra_fields["int"] == 42

    def test_non_json_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordEventInput(
                event_type="test",
                extra_fields={"bad": object()},  # type: ignore[dict-item]
            )

    def test_extra_top_level_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordEventInput(event_type="test", unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
# RecordEventOutput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordEventOutputValidation:
    def test_valid_output(self) -> None:
        event = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="item_acquired",
            extra_fields={"item": "sword"},
        )
        output = RecordEventOutput(event=event)
        assert output.event.event_id == "evt_001"

    def test_extra_fields_rejected(self) -> None:
        event = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="test",
            extra_fields={},
        )
        with pytest.raises(ValidationError):
            RecordEventOutput(event=event, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
# RecordNoteInput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordNoteInputValidation:
    def test_valid_input(self) -> None:
        inp = RecordNoteInput(text="The party entered the dungeon")
        assert inp.text == "The party entered the dungeon"

    def test_unicode_text_accepted(self) -> None:
        inp = RecordNoteInput(text="Партия вошла в подземелье")
        assert inp.text == "Партия вошла в подземелье"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            RecordNoteInput(text="")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            RecordNoteInput(text="   ")

    def test_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            RecordNoteInput(text="  leading")

    def test_trailing_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            RecordNoteInput(text="trailing  ")

    def test_control_characters_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-printable"):
            RecordNoteInput(text="bad\x00text")

    def test_non_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordNoteInput(text=123)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordNoteInput(text="hello", unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
# RecordNoteOutput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordNoteOutputValidation:
    def test_valid_output(self) -> None:
        event = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="note",
            extra_fields={"text": "Hello"},
        )
        output = RecordNoteOutput(event=event)
        assert output.event.type == "note"

    def test_extra_fields_rejected(self) -> None:
        event = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="note",
            extra_fields={},
        )
        with pytest.raises(ValidationError):
            RecordNoteOutput(event=event, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
# EndSessionInput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndSessionInputValidation:
    def test_omitted_touched_ids_empty(self) -> None:
        inp = EndSessionInput()
        assert inp.touched_entity_ids == []

    def test_explicit_empty_list(self) -> None:
        inp = EndSessionInput(touched_entity_ids=[])
        assert inp.touched_entity_ids == []

    def test_valid_entity_ids(self) -> None:
        inp = EndSessionInput(touched_entity_ids=["npc_varos", "loc_dungeon"])
        assert inp.touched_entity_ids == ["npc_varos", "loc_dungeon"]

    def test_printable_unicode_entity_id(self) -> None:
        inp = EndSessionInput(touched_entity_ids=["npc_варг"])
        assert inp.touched_entity_ids == ["npc_варг"]

    def test_input_order_preserved(self) -> None:
        inp = EndSessionInput(touched_entity_ids=["b", "a", "c"])
        assert inp.touched_entity_ids == ["b", "a", "c"]

    def test_duplicate_ids_not_removed_by_tool(self) -> None:
        inp = EndSessionInput(touched_entity_ids=["a", "a"])
        assert inp.touched_entity_ids == ["a", "a"]

    def test_empty_entity_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=[""])

    def test_whitespace_entity_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=["   "])

    def test_leading_whitespace_entity_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=["  leading"])

    def test_trailing_whitespace_entity_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=["trailing  "])

    def test_control_char_entity_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=["bad\x00id"])

    def test_non_string_in_list_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=[123])  # type: ignore[list-item]

    def test_non_list_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids="not-a-list")  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionInput(touched_entity_ids=[], unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
# EndSessionOutput validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndSessionOutputValidation:
    def test_with_session(self) -> None:
        session = _make_session(status="completed")
        output = EndSessionOutput(session=session)
        assert output.session is session

    def test_extra_fields_rejected(self) -> None:
        session = _make_session(status="completed")
        with pytest.raises(ValidationError):
            EndSessionOutput(session=session, unknown="x")  # type: ignore[call-arg]

    def test_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionOutput(session="not-a-session")  # type: ignore[arg-type]

    def test_incomplete_dict_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionOutput(session={"id": "incomplete"})  # type: ignore[arg-type]

    def test_none_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EndSessionOutput(session=None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# Registration API
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegistrationAPI:
    def test_register_with_invalid_registry_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ToolRegistry"):
            register_session_mutation_tools(
                "not_a_registry",  # type: ignore[arg-type]
                runtime_service=FakeRuntimeService(),
                recovery_service=FakeRecoveryService(),
            )

    def test_duplicate_registration_rejected(
        self,
        registry: ToolRegistry,
    ) -> None:
        register_session_mutation_tools(
            registry,
            runtime_service=FakeRuntimeService(),
            recovery_service=FakeRecoveryService(),
        )
        with pytest.raises(DndAssistantError, match="already registered"):
            register_session_mutation_tools(
                registry,
                runtime_service=FakeRuntimeService(),
                recovery_service=FakeRecoveryService(),
            )
