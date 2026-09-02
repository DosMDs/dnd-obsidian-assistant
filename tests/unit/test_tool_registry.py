"""Tests for ToolRegistry: register, lookup, list, and error semantics.

These tests use only local dummy schemas and handlers — no real campaign
Vault, no concrete tools, no model providers.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    Permission,
    SessionMode,
    SideEffect,
    ToolBinding,
    ToolDefinition,
)

# ── Dummy schemas and handlers ───────────────────────────────────────────────


class DummyInput(BaseModel):
    value: str


class DummyOutput(BaseModel):
    result: str


def dummy_handler(input_model: DummyInput, context: object) -> DummyOutput:
    return DummyOutput(result=f"handled: {input_model.value}")


def another_handler(input_model: DummyInput, context: object) -> DummyOutput:
    return DummyOutput(result="another")


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def read_definition() -> ToolDefinition:
    return ToolDefinition(
        name="get_example",
        description="Get an example",
        input_schema=DummyInput,
        output_schema=DummyOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def write_definition() -> ToolDefinition:
    return ToolDefinition(
        name="create_example",
        description="Create an example",
        input_schema=DummyInput,
        output_schema=DummyOutput,
        permission=Permission.WRITE,
        side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
        allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
    )


# ── Register ─────────────────────────────────────────────────────────────────


class TestToolRegistryRegister:
    def test_register_read_tool(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        assert len(empty_registry) == 1

    def test_register_write_tool(
        self, empty_registry: ToolRegistry, write_definition: ToolDefinition
    ) -> None:
        empty_registry.register(write_definition, dummy_handler)
        assert len(empty_registry) == 1

    def test_register_multiple_tools(
        self,
        empty_registry: ToolRegistry,
        read_definition: ToolDefinition,
        write_definition: ToolDefinition,
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        empty_registry.register(write_definition, dummy_handler)
        assert len(empty_registry) == 2

    def test_duplicate_name_raises_conflict(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        with pytest.raises(ConflictError, match="already registered"):
            empty_registry.register(read_definition, dummy_handler)

    def test_register_non_definition_raises_validation_error(
        self, empty_registry: ToolRegistry
    ) -> None:
        with pytest.raises(ValidationError, match="ToolDefinition"):
            empty_registry.register("not_a_definition", dummy_handler)  # type: ignore[arg-type]

    def test_register_non_callable_handler_raises_validation_error(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        with pytest.raises(ValidationError, match="callable"):
            empty_registry.register(read_definition, "not_callable")  # type: ignore[arg-type]


# ── Lookup ───────────────────────────────────────────────────────────────────


class TestToolRegistryLookup:
    def test_get_returns_binding(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        binding = empty_registry.get("get_example")
        assert isinstance(binding, ToolBinding)
        assert binding.definition.name == "get_example"

    def test_get_unknown_raises_not_found(self, empty_registry: ToolRegistry) -> None:
        with pytest.raises(NotFoundError, match="Unknown tool"):
            empty_registry.get("nonexistent")

    def test_get_definition_returns_definition(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        definition = empty_registry.get_definition("get_example")
        assert isinstance(definition, ToolDefinition)
        assert definition.name == "get_example"

    def test_get_definition_unknown_raises_not_found(self, empty_registry: ToolRegistry) -> None:
        with pytest.raises(NotFoundError, match="Unknown tool"):
            empty_registry.get_definition("nonexistent")

    def test_registry_lookup_does_not_invoke_handler(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        call_count = 0

        def counting_handler(input_model: DummyInput, context: object) -> DummyOutput:
            nonlocal call_count
            call_count += 1
            return DummyOutput(result="x")

        empty_registry.register(read_definition, counting_handler)
        empty_registry.get("get_example")
        assert call_count == 0


# ── Listing ──────────────────────────────────────────────────────────────────


class TestToolRegistryListing:
    def test_empty_registry_returns_empty_list(self, empty_registry: ToolRegistry) -> None:
        assert empty_registry.list_definitions() == ()

    def test_list_definitions_deterministic_order(
        self,
        empty_registry: ToolRegistry,
        read_definition: ToolDefinition,
        write_definition: ToolDefinition,
    ) -> None:
        # Register in reverse alphabetical order
        empty_registry.register(write_definition, dummy_handler)
        empty_registry.register(read_definition, dummy_handler)

        definitions = empty_registry.list_definitions()
        assert isinstance(definitions, Sequence)
        names = [d.name for d in definitions]
        assert names == sorted(names)  # deterministic = alphabetical

    def test_list_definitions_returns_all(
        self,
        empty_registry: ToolRegistry,
        read_definition: ToolDefinition,
        write_definition: ToolDefinition,
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        empty_registry.register(write_definition, dummy_handler)
        assert len(empty_registry.list_definitions()) == 2


# ── Length ───────────────────────────────────────────────────────────────────


class TestToolRegistryLength:
    def test_len_empty(self, empty_registry: ToolRegistry) -> None:
        assert len(empty_registry) == 0

    def test_len_after_registration(
        self, empty_registry: ToolRegistry, read_definition: ToolDefinition
    ) -> None:
        empty_registry.register(read_definition, dummy_handler)
        assert len(empty_registry) == 1
