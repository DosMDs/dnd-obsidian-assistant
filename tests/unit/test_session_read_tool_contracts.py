"""Tests for session read tool contracts: DTO validation and registration metadata.

Covers:
- Registration metadata (names, permission, side effects, session modes)
- GetActiveSessionInput/Output validation
- GetSessionInput/Output validation
- ListSessionsInput/Output validation
- ListSessionEventsInput/Output validation
- SessionEventResult validation
- Registration API
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_reads import (
    GetActiveSessionInput,
    GetActiveSessionOutput,
    GetSessionInput,
    GetSessionOutput,
    ListSessionEventsInput,
    ListSessionEventsOutput,
    ListSessionsInput,
    ListSessionsOutput,
    SessionEventResult,
    register_session_read_tools,
)
from dnd_assistant.tools.types import (
    Permission,
    SessionMode,
)

# ── Shared test data ──────────────────────────────────────────────────────

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


# ── Fake implementations for registration tests ───────────────────────────


class FakeRuntimeService:
    """Minimal fake implementing SessionRuntimeService protocol."""

    def __init__(self) -> None:
        self._active: Session | None = None

    def set_active_session(self, session: Session | None) -> None:
        self._active = session

    def get_active_session(self) -> Session | None:
        return self._active


class FakeSessionRepository:
    """Minimal fake implementing SessionMetadataRepository protocol."""

    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}

    def add_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    def get_session_metadata(self, session_id: str) -> object:
        return self._sessions.get(session_id)

    def list_session_metadata(self) -> list[object]:
        return list(self._sessions.values())

    def get_active_session(self) -> object | None:
        active = [
            s for s in self._sessions.values() if hasattr(s, "status") and s.status == "active"
        ]
        if len(active) == 0:
            return None
        if len(active) == 1:
            return active[0]
        return None

    def allocate_next_session_id(self) -> str:
        return "S999"


class FakeEventRepository:
    """Minimal fake implementing SessionEventRepository protocol."""

    def __init__(self) -> None:
        self._events: list[object] = []

    def set_events(self, events: list[object]) -> None:
        self._events = events

    def list_events(self, session_id: str) -> list[object]:
        return self._events

    def append_event(self, *args: object, **kwargs: object) -> object:
        msg = "FakeEventRepository does not support writes"
        raise NotImplementedError(msg)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def registered_registry(
    registry: ToolRegistry,
) -> ToolRegistry:
    register_session_read_tools(
        registry,
        runtime_service=FakeRuntimeService(),
        session_repository=FakeSessionRepository(),
        event_repository=FakeEventRepository(),
    )
    return registry


# ═══════════════════════════════════════════════════════════════════════════
# Registration metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationMetadata:
    def test_get_active_session_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_active_session")
        assert definition.name == "get_active_session"

    def test_get_session_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_session")
        assert definition.name == "get_session"

    def test_list_sessions_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("list_sessions")
        assert definition.name == "list_sessions"

    def test_list_session_events_name(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("list_session_events")
        assert definition.name == "list_session_events"

    def test_all_have_read_permission(self, registered_registry: ToolRegistry) -> None:
        for name in ("get_active_session", "get_session", "list_sessions", "list_session_events"):
            definition = registered_registry.get_definition(name)
            assert definition.permission == Permission.READ

    def test_all_have_empty_side_effects(self, registered_registry: ToolRegistry) -> None:
        for name in ("get_active_session", "get_session", "list_sessions", "list_session_events"):
            definition = registered_registry.get_definition(name)
            assert definition.side_effects == frozenset()

    def test_all_allow_both_session_modes(self, registered_registry: ToolRegistry) -> None:
        expected = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
        for name in ("get_active_session", "get_session", "list_sessions", "list_session_events"):
            definition = registered_registry.get_definition(name)
            assert definition.allowed_session_modes == expected

    def test_get_active_session_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("get_active_session")
        assert definition.input_schema is GetActiveSessionInput
        assert definition.output_schema is GetActiveSessionOutput

    def test_get_session_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("get_session")
        assert definition.input_schema is GetSessionInput
        assert definition.output_schema is GetSessionOutput

    def test_list_sessions_has_correct_schemas(self, registered_registry: ToolRegistry) -> None:
        definition = registered_registry.get_definition("list_sessions")
        assert definition.input_schema is ListSessionsInput
        assert definition.output_schema is ListSessionsOutput

    def test_list_session_events_has_correct_schemas(
        self, registered_registry: ToolRegistry
    ) -> None:
        definition = registered_registry.get_definition("list_session_events")
        assert definition.input_schema is ListSessionEventsInput
        assert definition.output_schema is ListSessionEventsOutput

    def test_deterministic_registry_listing(self, registered_registry: ToolRegistry) -> None:
        names = [d.name for d in registered_registry.list_definitions()]
        assert names == [
            "get_active_session",
            "get_session",
            "list_session_events",
            "list_sessions",
        ]

    def test_registration_count(self, registered_registry: ToolRegistry) -> None:
        assert len(registered_registry) == 4


# ═══════════════════════════════════════════════════════════════════════════
# GetActiveSessionInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetActiveSessionInputValidation:
    def test_empty_input_valid(self) -> None:
        inp = GetActiveSessionInput()
        assert inp.model_dump() == {}

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetActiveSessionInput(unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# GetActiveSessionOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetActiveSessionOutputValidation:
    def test_none_session(self) -> None:
        output = GetActiveSessionOutput(session=None)
        assert output.session is None

    def test_with_session(self) -> None:
        session = _make_session()
        output = GetActiveSessionOutput(session=session)
        assert output.session is session

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetActiveSessionOutput(session=None, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# GetSessionInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSessionInputValidation:
    def test_valid_input(self) -> None:
        inp = GetSessionInput(session_id="S001")
        assert inp.session_id == "S001"

    def test_valid_non_numeric_id(self) -> None:
        """A non-S### printable session ID must not be rejected."""
        inp = GetSessionInput(session_id="Session Alpha")
        assert inp.session_id == "Session Alpha"

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            GetSessionInput(session_id="")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            GetSessionInput(session_id="   ")

    def test_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            GetSessionInput(session_id="  S001")

    def test_trailing_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            GetSessionInput(session_id="S001  ")

    def test_non_printable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-printable"):
            GetSessionInput(session_id="bad\x00id")

    def test_non_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetSessionInput(session_id=123)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetSessionInput(session_id="S001", unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# GetSessionOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSessionOutputValidation:
    def test_valid_output(self) -> None:
        session = _make_session()
        output = GetSessionOutput(session=session)
        assert output.session is session

    def test_extra_fields_rejected(self) -> None:
        session = _make_session()
        with pytest.raises(ValidationError):
            GetSessionOutput(session=session, unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# ListSessionsInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestListSessionsInputValidation:
    def test_empty_input_valid(self) -> None:
        inp = ListSessionsInput()
        assert inp.model_dump() == {}

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListSessionsInput(unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# ListSessionsOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestListSessionsOutputValidation:
    def test_empty_list(self) -> None:
        output = ListSessionsOutput(sessions=[])
        assert output.sessions == []

    def test_multiple_sessions(self) -> None:
        s1 = _make_session("S001")
        s2 = _make_session("S002")
        output = ListSessionsOutput(sessions=[s1, s2])
        assert len(output.sessions) == 2

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListSessionsOutput(sessions=[], unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# ListSessionEventsInput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestListSessionEventsInputValidation:
    def test_valid_input(self) -> None:
        inp = ListSessionEventsInput(session_id="S001")
        assert inp.session_id == "S001"

    def test_valid_non_numeric_id(self) -> None:
        inp = ListSessionEventsInput(session_id="Session Alpha")
        assert inp.session_id == "Session Alpha"

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            ListSessionEventsInput(session_id="")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            ListSessionEventsInput(session_id="   ")

    def test_leading_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            ListSessionEventsInput(session_id="  S001")

    def test_trailing_whitespace_rejected(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            ListSessionEventsInput(session_id="S001  ")

    def test_non_printable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-printable"):
            ListSessionEventsInput(session_id="bad\x00id")

    def test_non_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListSessionEventsInput(session_id=123)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListSessionEventsInput(session_id="S001", unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# SessionEventResult validation
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionEventResultValidation:
    def test_valid_event(self) -> None:
        result = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="note",
            extra_fields={"text": "Hello"},
        )
        assert result.event_id == "evt_001"
        assert result.world_tick == 1000
        assert result.type == "note"
        assert result.extra_fields == {"text": "Hello"}

    def test_empty_extra_fields(self) -> None:
        result = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="note",
            extra_fields={},
        )
        assert result.extra_fields == {}

    def test_nested_json_extra_fields(self) -> None:
        result = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="combat",
            extra_fields={"damage": 15, "targets": ["goblin", "orc"], "critical": True},
        )
        assert result.extra_fields["damage"] == 15
        assert result.extra_fields["targets"] == ["goblin", "orc"]
        assert result.extra_fields["critical"] is True

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionEventResult(  # type: ignore[call-arg]
                event_id="evt_001",
                real_time=_NOW,
                world_tick=WorldTick(1000),
                type="note",
                extra_fields={},
                unknown="x",
            )


# ═══════════════════════════════════════════════════════════════════════════
# ListSessionEventsOutput validation
# ═══════════════════════════════════════════════════════════════════════════


class TestListSessionEventsOutputValidation:
    def test_empty_events(self) -> None:
        output = ListSessionEventsOutput(events=[])
        assert output.events == []

    def test_multiple_events(self) -> None:
        e1 = SessionEventResult(
            event_id="evt_001",
            real_time=_NOW,
            world_tick=WorldTick(1000),
            type="note",
            extra_fields={"text": "A"},
        )
        e2 = SessionEventResult(
            event_id="evt_002",
            real_time=_NOW,
            world_tick=WorldTick(1001),
            type="note",
            extra_fields={"text": "B"},
        )
        output = ListSessionEventsOutput(events=[e1, e2])
        assert len(output.events) == 2

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListSessionEventsOutput(events=[], unknown="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# Registration API
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrationAPI:
    def test_register_with_invalid_registry_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ToolRegistry"):
            register_session_read_tools(
                "not_a_registry",  # type: ignore[arg-type]
                runtime_service=FakeRuntimeService(),
                session_repository=FakeSessionRepository(),
                event_repository=FakeEventRepository(),
            )

    def test_duplicate_registration_rejected(
        self,
        registry: ToolRegistry,
    ) -> None:
        register_session_read_tools(
            registry,
            runtime_service=FakeRuntimeService(),
            session_repository=FakeSessionRepository(),
            event_repository=FakeEventRepository(),
        )
        with pytest.raises(DndAssistantError, match="already registered"):
            register_session_read_tools(
                registry,
                runtime_service=FakeRuntimeService(),
                session_repository=FakeSessionRepository(),
                event_repository=FakeEventRepository(),
            )
