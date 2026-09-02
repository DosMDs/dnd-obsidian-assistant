"""Tests for tool type definitions: Permission, SideEffect, SessionMode,
ToolDefinition validation, immutability, and cross-field constraints.

These tests use only local dummy schemas and handlers — no real campaign
Vault, no concrete tools, no model providers.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.errors import ValidationError
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
    convert_validation_error,
)

# ── Dummy schemas for testing ────────────────────────────────────────────────


class DummyInput(BaseModel):
    value: str


class DummyOutput(BaseModel):
    result: str


# ── Permission ───────────────────────────────────────────────────────────────


class TestPermission:
    def test_read_value(self) -> None:
        assert Permission.READ.value == "read"

    def test_write_value(self) -> None:
        assert Permission.WRITE.value == "write"

    def test_str_enum_membership(self) -> None:
        assert "read" in set(m.value for m in Permission)
        assert "write" in set(m.value for m in Permission)


# ── SideEffect ───────────────────────────────────────────────────────────────


class TestSideEffect:
    def test_entity_mutation(self) -> None:
        assert SideEffect.ENTITY_MUTATION.value == "entity_mutation"

    def test_session_mutation(self) -> None:
        assert SideEffect.SESSION_MUTATION.value == "session_mutation"

    def test_world_time_mutation(self) -> None:
        assert SideEffect.WORLD_TIME_MUTATION.value == "world_time_mutation"


# ── SessionMode ──────────────────────────────────────────────────────────────


class TestSessionMode:
    def test_no_active_session(self) -> None:
        assert SessionMode.NO_ACTIVE_SESSION.value == "no_active_session"

    def test_active_session(self) -> None:
        assert SessionMode.ACTIVE_SESSION.value == "active_session"


# ── ToolDefinition — valid ───────────────────────────────────────────────────


class TestToolDefinitionValid:
    def test_valid_read_definition(self) -> None:
        """A READ tool with no side effects and both session modes."""
        definition = ToolDefinition(
            name="get_example",
            description="Get an example value",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        assert definition.name == "get_example"
        assert definition.permission == Permission.READ
        assert definition.side_effects == frozenset()
        assert len(definition.allowed_session_modes) == 2

    def test_valid_write_definition(self) -> None:
        """A WRITE tool with one side effect and one session mode."""
        definition = ToolDefinition(
            name="create_example",
            description="Create an example resource",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            permission=Permission.WRITE,
            side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
            allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
        )
        assert definition.name == "create_example"
        assert definition.permission == Permission.WRITE
        assert SideEffect.ENTITY_MUTATION in definition.side_effects

    def test_write_multiple_side_effects(self) -> None:
        definition = ToolDefinition(
            name="complex_write",
            description="A write tool with multiple side effects",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            permission=Permission.WRITE,
            side_effects=frozenset({SideEffect.ENTITY_MUTATION, SideEffect.SESSION_MUTATION}),
            allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
        )
        assert len(definition.side_effects) == 2

    def test_snake_case_name(self) -> None:
        definition = ToolDefinition(
            name="my_valid_tool_name_42",
            description="A snake_case tool name",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
        )
        assert definition.name == "my_valid_tool_name_42"


# ── ToolDefinition — invalid ─────────────────────────────────────────────────


class TestToolDefinitionInvalidName:
    def test_empty_name(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            ToolDefinition(
                name="",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_whitespace_name(self) -> None:
        with pytest.raises(ValidationError, match="leading or trailing whitespace"):
            ToolDefinition(
                name=" bad-name",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_uppercase_name(self) -> None:
        with pytest.raises(ValidationError, match="snake_case"):
            ToolDefinition(
                name="UPPERCASE",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_name_with_special_chars(self) -> None:
        with pytest.raises(ValidationError, match="snake_case"):
            ToolDefinition(
                name="tool-name!",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_name_with_spaces(self) -> None:
        with pytest.raises(ValidationError, match="snake_case"):
            ToolDefinition(
                name="my tool",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )


class TestToolDefinitionInvalidDescription:
    def test_empty_description(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            ToolDefinition(
                name="get_x",
                description="",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_whitespace_description(self) -> None:
        with pytest.raises(ValidationError, match="leading or trailing whitespace"):
            ToolDefinition(
                name="get_x",
                description=" leading space",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )


class TestToolDefinitionInvalidSchema:
    def test_input_schema_not_basemodel(self) -> None:
        with pytest.raises(ValidationError, match="BaseModel"):
            ToolDefinition(
                name="get_x",
                description="desc",
                input_schema=dict,  # type: ignore[arg-type]
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_output_schema_not_basemodel(self) -> None:
        with pytest.raises(ValidationError, match="BaseModel"):
            ToolDefinition(
                name="get_x",
                description="desc",
                input_schema=DummyInput,
                output_schema=str,  # type: ignore[arg-type]
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )


class TestToolDefinitionSideEffectConstraints:
    def test_read_with_side_effects_rejected(self) -> None:
        with pytest.raises(ValidationError, match="READ tools must have an empty"):
            ToolDefinition(
                name="get_x",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
                allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
            )

    def test_write_without_side_effects_rejected(self) -> None:
        with pytest.raises(ValidationError, match="WRITE tools must declare"):
            ToolDefinition(
                name="create_x",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.WRITE,
                side_effects=frozenset(),
                allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
            )


class TestToolDefinitionSessionModeConstraints:
    def test_empty_allowed_session_modes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="allowed_session_modes must not be empty"):
            ToolDefinition(
                name="get_x",
                description="desc",
                input_schema=DummyInput,
                output_schema=DummyOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset(),
            )


# ── ToolDefinition — immutability ────────────────────────────────────────────


class TestToolDefinitionImmutability:
    def test_definition_is_frozen(self) -> None:
        definition = ToolDefinition(
            name="get_x",
            description="desc",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
        )
        with pytest.raises(PydanticValidationError):
            definition.name = "new_name"  # type: ignore[misc]


# ── ExecutionContext ─────────────────────────────────────────────────────────


class TestExecutionContext:
    def test_read_context_without_audit(self) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        assert ctx.granted_permission == Permission.READ
        assert ctx.session_mode == SessionMode.NO_ACTIVE_SESSION
        assert ctx.audit is None

    def test_write_context_with_audit(self) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=None,
        )
        assert ctx.granted_permission == Permission.WRITE

    def test_context_is_frozen(self) -> None:
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        with pytest.raises(PydanticValidationError):
            ctx.granted_permission = Permission.WRITE  # type: ignore[misc]


# ── convert_validation_error ─────────────────────────────────────────────────


class TestConvertValidationError:
    def test_preserves_validation_error(self) -> None:
        original = ValidationError("already valid")
        result = convert_validation_error(original)
        assert result is original

    def test_wraps_value_error(self) -> None:
        result = convert_validation_error(ValueError("bad value"))
        assert isinstance(result, ValidationError)
        assert "bad value" in str(result)

    def test_wraps_type_error(self) -> None:
        result = convert_validation_error(TypeError("wrong type"))
        assert isinstance(result, ValidationError)
        assert "wrong type" in str(result)

    def test_empty_message_fallback(self) -> None:
        result = convert_validation_error(Exception())
        assert isinstance(result, ValidationError)
        assert "Validation failed" in str(result)
