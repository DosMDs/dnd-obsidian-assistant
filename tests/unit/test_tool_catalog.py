"""Unit tests for the provider-neutral public registry schema (catalog).

Covers:

- ``ToolPublicDefinition`` DTO validation and immutability.
- ``ToolRegistrySchema`` DTO validation and immutability.
- ``build_tool_registry_schema`` generic behavior.
- MVP registry catalog integration.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.tools.catalog import (
    ToolPublicDefinition,
    ToolRegistrySchema,
    build_tool_registry_schema,
)
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

# ── Helpers ──────────────────────────────────────────────────────────────────────


class _SimpleInput(BaseModel):
    x: int
    model_config = {"extra": "forbid"}


class _SimpleOutput(BaseModel):
    result: str
    model_config = {"extra": "forbid"}


class _OtherInput(BaseModel):
    name: str
    model_config = {"extra": "forbid"}


class _OtherOutput(BaseModel):
    ok: bool
    model_config = {"extra": "forbid"}


def _make_registry(
    definitions: list[tuple[str, Permission, frozenset[SideEffect], frozenset[SessionMode]]],
) -> ToolRegistry:
    """Build a ToolRegistry with simple handlers for testing."""
    registry = ToolRegistry()
    for i, (name, perm, effects, modes) in enumerate(definitions):
        input_cls = _SimpleInput if i % 2 == 0 else _OtherInput
        output_cls = _SimpleOutput if i % 2 == 0 else _OtherOutput

        defn = ToolDefinition(
            name=name,
            description=f"Tool {name}",
            input_schema=input_cls,
            output_schema=output_cls,
            permission=perm,
            side_effects=effects,
            allowed_session_modes=modes,
        )

        def _handler(
            input_model: BaseModel,
            context: Any,  # noqa: ARG001
            _out_cls: type[BaseModel] = output_cls,
        ) -> BaseModel:
            return _out_cls.model_validate({})

        registry.register(defn, _handler)
    return registry


# ── ToolPublicDefinition DTO tests ────────────────────────────────────────────────


class TestToolPublicDefinition:
    """ToolPublicDefinition DTO validation and immutability."""

    def test_valid_dto(self) -> None:
        dto = ToolPublicDefinition(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
        )
        assert dto.name == "test_tool"
        assert dto.description == "A test tool"
        assert dto.permission == Permission.READ
        assert dto.side_effects == []
        assert dto.allowed_session_modes == [SessionMode.NO_ACTIVE_SESSION]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            ToolPublicDefinition(
                name="test",
                description="desc",
                input_schema={},
                output_schema={},
                permission=Permission.READ,
                side_effects=[],
                allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
                handler=lambda: None,  # type: ignore[call-arg]
            )

    def test_frozen_immutable(self) -> None:
        dto = ToolPublicDefinition(
            name="test",
            description="desc",
            input_schema={},
            output_schema={},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
        )
        with pytest.raises(PydanticValidationError):
            dto.name = "changed"  # type: ignore[misc]

    def test_side_effects_preserves_input_order(self) -> None:
        """The DTO preserves the list as provided; sorting is the catalog builder's job."""
        dto = ToolPublicDefinition(
            name="test",
            description="desc",
            input_schema={},
            output_schema={},
            permission=Permission.WRITE,
            side_effects=[SideEffect.SESSION_MUTATION, SideEffect.ENTITY_MUTATION],
            allowed_session_modes=[SessionMode.ACTIVE_SESSION],
        )
        assert dto.side_effects == [SideEffect.SESSION_MUTATION, SideEffect.ENTITY_MUTATION]

    def test_session_modes_sorted(self) -> None:
        dto = ToolPublicDefinition(
            name="test",
            description="desc",
            input_schema={},
            output_schema={},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.ACTIVE_SESSION, SessionMode.NO_ACTIVE_SESSION],
        )
        assert dto.allowed_session_modes == [
            SessionMode.ACTIVE_SESSION,
            SessionMode.NO_ACTIVE_SESSION,
        ]


# ── ToolRegistrySchema DTO tests ──────────────────────────────────────────────────


class TestToolRegistrySchema:
    """ToolRegistrySchema DTO validation and immutability."""

    def test_empty_tools_list(self) -> None:
        schema = ToolRegistrySchema(tools=[])
        assert schema.tools == []

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            ToolRegistrySchema(tools=[], version="1.0")  # type: ignore[call-arg]

    def test_frozen_immutable(self) -> None:
        schema = ToolRegistrySchema(tools=[])
        with pytest.raises(PydanticValidationError):
            schema.tools = []  # type: ignore[misc]


# ── build_tool_registry_schema generic tests ──────────────────────────────────────


class TestBuildToolRegistrySchema:
    """Generic catalog builder behavior."""

    def test_non_registry_rejected(self) -> None:
        with pytest.raises(TypeError, match="ToolRegistry"):
            build_tool_registry_schema("not a registry")  # type: ignore[arg-type]

    def test_registry_like_impostor_rejected(self) -> None:
        """A duck-typed object with list_definitions must not be accepted."""

        class _FakeRegistryLike:
            def list_definitions(self) -> tuple[object, ...]:
                return ()

        with pytest.raises(TypeError, match="ToolRegistry"):
            build_tool_registry_schema(_FakeRegistryLike())  # type: ignore[arg-type]

    def test_tool_registry_subclass_accepted(self) -> None:
        """A ToolRegistry subclass must be accepted by isinstance."""

        class _SubRegistry(ToolRegistry):
            pass

        schema = build_tool_registry_schema(_SubRegistry())
        assert isinstance(schema, ToolRegistrySchema)
        assert schema.tools == []

    def test_spoofed_class_name_module_impostor_rejected(self) -> None:
        """A class named ToolRegistry with matching __module__ must be rejected.

        The S7-C09 MRO fallback checked class name and module string,
        which are metadata attributes that can be fabricated.  This
        regression proves no such escape hatch exists.
        """
        FakeToolRegistry = type(
            "ToolRegistry",
            (),
            {
                "__module__": "dnd_assistant.tools.registry",
                "list_definitions": lambda self: (),
            },
        )

        fake = FakeToolRegistry()
        assert not isinstance(fake, ToolRegistry)
        with pytest.raises(TypeError, match="ToolRegistry"):
            build_tool_registry_schema(fake)  # type: ignore[arg-type]

    def test_empty_registry(self) -> None:
        registry = ToolRegistry()
        schema = build_tool_registry_schema(registry)
        assert isinstance(schema, ToolRegistrySchema)
        assert schema.tools == []

    def test_ordering_independent_of_registration_order(self) -> None:
        """Catalog ordering must be sorted by name, not registration order."""
        registry = _make_registry(
            [
                (
                    "z_tool",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
                (
                    "a_tool",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
                (
                    "m_tool",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
            ]
        )
        schema = build_tool_registry_schema(registry)
        names = [t.name for t in schema.tools]
        assert names == ["a_tool", "m_tool", "z_tool"]

    def test_description_preserved(self) -> None:
        registry = _make_registry(
            [
                (
                    "my_tool",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
            ]
        )
        schema = build_tool_registry_schema(registry)
        assert schema.tools[0].description == "Tool my_tool"

    def test_permission_preserved(self) -> None:
        registry = _make_registry(
            [
                (
                    "read_tool",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
                (
                    "write_tool",
                    Permission.WRITE,
                    frozenset({SideEffect.ENTITY_MUTATION}),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
            ]
        )
        schema = build_tool_registry_schema(registry)
        perm_map = {t.name: t.permission for t in schema.tools}
        assert perm_map["read_tool"] == Permission.READ
        assert perm_map["write_tool"] == Permission.WRITE

    def test_side_effects_deterministically_sorted(self) -> None:
        registry = _make_registry(
            [
                (
                    "multi_effect",
                    Permission.WRITE,
                    frozenset({SideEffect.WORLD_TIME_MUTATION, SideEffect.ENTITY_MUTATION}),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
            ]
        )
        schema = build_tool_registry_schema(registry)
        assert schema.tools[0].side_effects == [
            SideEffect.ENTITY_MUTATION,
            SideEffect.WORLD_TIME_MUTATION,
        ]

    def test_session_modes_deterministically_sorted(self) -> None:
        registry = _make_registry(
            [
                (
                    "multi_mode",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.ACTIVE_SESSION, SessionMode.NO_ACTIVE_SESSION}),
                ),
            ]
        )
        schema = build_tool_registry_schema(registry)
        assert schema.tools[0].allowed_session_modes == [
            SessionMode.ACTIVE_SESSION,
            SessionMode.NO_ACTIVE_SESSION,
        ]

    def test_input_json_schema_from_model_json_schema(self) -> None:
        registry = _make_registry(
            [
                ("test", Permission.READ, frozenset(), frozenset({SessionMode.NO_ACTIVE_SESSION})),
            ]
        )
        schema = build_tool_registry_schema(registry)
        input_schema = schema.tools[0].input_schema
        assert isinstance(input_schema, dict)
        assert "properties" in input_schema
        assert "x" in input_schema["properties"]

    def test_output_json_schema_from_model_json_schema(self) -> None:
        registry = _make_registry(
            [
                ("test", Permission.READ, frozenset(), frozenset({SessionMode.NO_ACTIVE_SESSION})),
            ]
        )
        schema = build_tool_registry_schema(registry)
        output_schema = schema.tools[0].output_schema
        assert isinstance(output_schema, dict)
        assert "properties" in output_schema
        assert "result" in output_schema["properties"]

    def test_serialized_model_dump_is_json_serializable(self) -> None:
        registry = _make_registry(
            [
                (
                    "tool_a",
                    Permission.READ,
                    frozenset(),
                    frozenset({SessionMode.NO_ACTIVE_SESSION}),
                ),
                (
                    "tool_b",
                    Permission.WRITE,
                    frozenset({SideEffect.ENTITY_MUTATION}),
                    frozenset({SessionMode.ACTIVE_SESSION}),
                ),
            ]
        )
        schema = build_tool_registry_schema(registry)
        payload = schema.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert len(parsed["tools"]) == 2

    def test_no_handler_exposed(self) -> None:
        registry = _make_registry(
            [
                ("test", Permission.READ, frozenset(), frozenset({SessionMode.NO_ACTIVE_SESSION})),
            ]
        )
        schema = build_tool_registry_schema(registry)
        payload = schema.model_dump(mode="json")
        for tool in payload["tools"]:
            assert "handler" not in tool
            assert "callable" not in tool

    def test_no_python_class_objects_in_serialized(self) -> None:
        registry = _make_registry(
            [
                ("test", Permission.READ, frozenset(), frozenset({SessionMode.NO_ACTIVE_SESSION})),
            ]
        )
        schema = build_tool_registry_schema(registry)
        payload = schema.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True)
        assert "<class " not in serialized
        assert "object at" not in serialized

    def test_catalog_is_snapshot_no_mutation(self) -> None:
        """Building the catalog must not mutate the registry."""
        registry = _make_registry(
            [
                ("test", Permission.READ, frozenset(), frozenset({SessionMode.NO_ACTIVE_SESSION})),
            ]
        )
        before_count = len(registry)
        _ = build_tool_registry_schema(registry)
        assert len(registry) == before_count

    def test_changing_returned_dict_does_not_mutate_registry(self) -> None:
        registry = _make_registry(
            [
                ("test", Permission.READ, frozenset(), frozenset({SessionMode.NO_ACTIVE_SESSION})),
            ]
        )
        schema = build_tool_registry_schema(registry)
        payload = schema.model_dump(mode="json")
        payload["tools"] = []
        assert len(registry) == 1


# ── MVP registry catalog integration ──────────────────────────────────────────────


class TestMvpRegistryCatalog:
    """Catalog built from the composed MVP registry."""

    def test_18_entries(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        assert len(schema.tools) == 18

    def test_exact_sorted_names(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        names = [t.name for t in schema.tools]
        expected = [
            "advance_world_time",
            "append_entity_fact",
            "end_session",
            "game_date_to_world_tick",
            "get_active_session",
            "get_entity",
            "get_session",
            "get_world_time",
            "list_session_events",
            "list_sessions",
            "patch_entity",
            "record_event",
            "record_note",
            "search_entities",
            "set_world_time",
            "start_session",
            "time_between_world_ticks",
            "world_tick_to_date",
        ]
        assert names == expected

    def test_read_write_metadata(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        read_count = sum(1 for t in schema.tools if t.permission == Permission.READ)
        write_count = sum(1 for t in schema.tools if t.permission == Permission.WRITE)
        assert read_count == 10
        assert write_count == 8

    def test_all_input_schemas_non_empty(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        for tool in schema.tools:
            assert isinstance(tool.input_schema, dict)
            assert len(tool.input_schema) > 0, f"Empty input schema for {tool.name}"

    def test_all_output_schemas_non_empty(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        for tool in schema.tools:
            assert isinstance(tool.output_schema, dict)
            assert len(tool.output_schema) > 0, f"Empty output schema for {tool.name}"

    def test_schemas_equal_registered_pydantic_source(self, mvp_registry: ToolRegistry) -> None:
        """Each catalog schema must match its registered Pydantic source schema."""
        schema = build_tool_registry_schema(mvp_registry)
        definitions = {d.name: d for d in mvp_registry.list_definitions()}
        for tool in schema.tools:
            defn = definitions[tool.name]
            assert tool.input_schema == defn.input_schema.model_json_schema()
            assert tool.output_schema == defn.output_schema.model_json_schema()

    def test_json_serializable(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        payload = schema.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True)
        parsed = json.loads(serialized)
        assert len(parsed["tools"]) == 18

    def test_no_handler_in_serialized(self, mvp_registry: ToolRegistry) -> None:
        schema = build_tool_registry_schema(mvp_registry)
        payload = schema.model_dump(mode="json")
        for tool in payload["tools"]:
            assert "handler" not in tool


# ── Fixture ────────────────────────────────────────────────────────────────────────


@pytest.fixture(name="mvp_registry")
def _mvp_registry_fixture() -> ToolRegistry:
    """Build the MVP registry with minimal fakes for catalog testing.

    Uses sentinel fakes because ``build_mvp_tool_registry`` must not
    execute handlers.
    """
    from dnd_assistant.tools.mvp_registry import build_mvp_tool_registry

    class _FakeSearchService:
        def search(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

        def get_by_id(self, *args: Any, **kwargs: Any) -> None:
            return None

    class _FakeRepository:
        def get_entity(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def patch_entity(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def append_entity_fact(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

    class _FakeRuntimeService:
        def get_active_session(self, *args: Any, **kwargs: Any) -> None:
            return None

        def start_session(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def record_event(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def record_note(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def end_session(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

    class _FakeRecoveryService:
        def inspect_runtime(self, *args: Any, **kwargs: Any) -> Any:
            return type("Report", (), {"has_issues": False})()

    class _FakeSessionRepo:
        def get_session_metadata(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def list_session_metadata(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

    class _FakeEventRepo:
        def list_events(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

    class _FakeWorldTimeRepo:
        def get_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def initialize_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def set_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

    class _FakeCalendarService:
        @property
        def definition(self) -> Any:
            return type("Def", (), {"calendar_id": "test_calendar"})()

        def tick_to_date(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def date_to_tick(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def advance_world_time(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

        def time_until(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError("Catalog test must not execute handlers")

    return build_mvp_tool_registry(
        search_service=_FakeSearchService(),
        repository=_FakeRepository(),
        runtime_service=_FakeRuntimeService(),
        recovery_service=_FakeRecoveryService(),
        session_repository=_FakeSessionRepo(),
        event_repository=_FakeEventRepo(),
        world_time_repository=_FakeWorldTimeRepo(),
        calendar_service=_FakeCalendarService(),
    )
