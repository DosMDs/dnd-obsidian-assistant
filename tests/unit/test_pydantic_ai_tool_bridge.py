"""Tests for PydanticAIToolBridge — snapshot freeze, framework translation,
execution adapter, and ToolExecutor authority.

All tests use real project ToolRegistry, ToolExecutor, ExecutionContext, and
harmless in-memory test handlers.  No Vault/filesystem writes.

Organisation
────────────

- TestPydanticAIToolSnapshot: BR-01 through BR-06 (snapshot behaviour)
- TestPydanticAIToolFreeze: BR-07 through BR-09 (malformed-snapshot rejection)
- TestPydanticAIToolExecute: BR-10 through BR-16 (execution adapter)
- TestPydanticAIToolAuthority: BR-17 through BR-20 (ToolExecutor final authority)
- TestPydanticAIToolErrors: handler failure / output validation
- TestPydanticAIToolArchitecture: no-direct-framework-execution assertion
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ToolCallPart

from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
from dnd_assistant.errors import ConflictError, ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

# ==============================================================================
# Shared test schemas and handlers
# ==============================================================================


class AlphaInput(BaseModel):
    value: str


class BetaInput(BaseModel):
    number: int


class ToolOutput(BaseModel):
    result: str


def _alpha_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
    return ToolOutput(result=f"alpha:{inp.value}")


def _beta_handler(inp: BetaInput, ctx: object) -> ToolOutput:
    return ToolOutput(result=f"beta:{inp.number}")


def _write_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
    return ToolOutput(result=f"write:{inp.value}")


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def read_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="read_alpha",
        description="A read-only test tool",
        input_schema=AlphaInput,
        output_schema=ToolOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def read_beta_def() -> ToolDefinition:
    return ToolDefinition(
        name="read_beta",
        description="Another read-only test tool",
        input_schema=BetaInput,
        output_schema=ToolOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def write_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="write_alpha",
        description="A write test tool",
        input_schema=AlphaInput,
        output_schema=ToolOutput,
        permission=Permission.WRITE,
        side_effects=frozenset({SideEffect.ENTITY_MUTATION}),
        allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
    )


@pytest.fixture
def registry(
    read_tool_def: ToolDefinition,
    read_beta_def: ToolDefinition,
    write_tool_def: ToolDefinition,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_tool_def, _alpha_handler)
    reg.register(read_beta_def, _beta_handler)
    reg.register(write_tool_def, _write_handler)
    return reg


@pytest.fixture
def bridge(registry: ToolRegistry) -> PydanticAIToolBridge:
    return PydanticAIToolBridge(registry=registry)


@pytest.fixture
def read_public(read_tool_def: ToolDefinition) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=read_tool_def.name,
        description=read_tool_def.description,
        input_schema=read_tool_def.input_schema.model_json_schema(),
        output_schema=read_tool_def.output_schema.model_json_schema(),
        permission=read_tool_def.permission,
        side_effects=sorted(read_tool_def.side_effects, key=lambda e: e.value),
        allowed_session_modes=sorted(read_tool_def.allowed_session_modes, key=lambda m: m.value),
    )


@pytest.fixture
def read_beta_public(read_beta_def: ToolDefinition) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=read_beta_def.name,
        description=read_beta_def.description,
        input_schema=read_beta_def.input_schema.model_json_schema(),
        output_schema=read_beta_def.output_schema.model_json_schema(),
        permission=read_beta_def.permission,
        side_effects=sorted(read_beta_def.side_effects, key=lambda e: e.value),
        allowed_session_modes=sorted(read_beta_def.allowed_session_modes, key=lambda m: m.value),
    )


@pytest.fixture
def write_public(write_tool_def: ToolDefinition) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=write_tool_def.name,
        description=write_tool_def.description,
        input_schema=write_tool_def.input_schema.model_json_schema(),
        output_schema=write_tool_def.output_schema.model_json_schema(),
        permission=write_tool_def.permission,
        side_effects=sorted(write_tool_def.side_effects, key=lambda e: e.value),
        allowed_session_modes=sorted(write_tool_def.allowed_session_modes, key=lambda m: m.value),
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


@pytest.fixture
def write_context_no_audit() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


# ==============================================================================
# BR-01 through BR-06 — Snapshot tests
# ==============================================================================


class TestPydanticAIToolSnapshot:
    """Snapshot behaviour: empty, deterministic mapping, order preservation,
    live-registry isolation, caller-list isolation, framework-toolset isolation.
    """

    # BR-01 — empty snapshot
    def test_br01_empty_snapshot(self, bridge: PydanticAIToolBridge) -> None:
        snapshot = bridge.freeze([])
        assert snapshot.names == ()
        assert len(snapshot.definitions) == 0

        toolset = snapshot.to_external_toolset()
        assert len(toolset.tool_defs) == 0

    # BR-02 — deterministic mapping
    def test_br02_deterministic_mapping(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_beta_public: ToolPublicDefinition,
    ) -> None:
        snapshot = bridge.freeze([read_public, read_beta_public])
        assert snapshot.names == ("read_alpha", "read_beta")

        toolset = snapshot.to_external_toolset()
        assert len(toolset.tool_defs) == 2

        names = [d.name for d in toolset.tool_defs]
        assert "read_alpha" in names
        assert "read_beta" in names

        alpha_def = next(d for d in toolset.tool_defs if d.name == "read_alpha")
        assert alpha_def.description == "A read-only test tool"
        assert alpha_def.parameters_json_schema is not None
        assert "properties" in alpha_def.parameters_json_schema
        assert "value" in alpha_def.parameters_json_schema["properties"]

        beta_def = next(d for d in toolset.tool_defs if d.name == "read_beta")
        assert beta_def.description == "Another read-only test tool"
        assert "number" in beta_def.parameters_json_schema["properties"]

    # BR-03 — order preservation
    def test_br03_order_preservation(
        self,
        bridge: PydanticAIToolBridge,
        read_beta_public: ToolPublicDefinition,
        read_public: ToolPublicDefinition,
    ) -> None:
        """Input exposure order is retained in the project snapshot."""
        snapshot = bridge.freeze([read_beta_public, read_public])
        assert snapshot.definitions[0].name == "read_beta"
        assert snapshot.definitions[1].name == "read_alpha"

    # BR-04 — live registry mutation does not expand snapshot
    def test_br04_live_registry_mutation(
        self,
        bridge: PydanticAIToolBridge,
        registry: ToolRegistry,
        read_public: ToolPublicDefinition,
    ) -> None:
        snapshot = bridge.freeze([read_public])

        new_def = ToolDefinition(
            name="new_tool",
            description="New tool",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        def _new_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
            return ToolOutput(result="new")

        registry.register(new_def, _new_handler)

        assert snapshot.names == ("read_alpha",)
        toolset = snapshot.to_external_toolset()
        assert len(toolset.tool_defs) == 1
        assert toolset.tool_defs[0].name == "read_alpha"

    # BR-05 — caller-list mutation does not expand snapshot
    def test_br05_caller_list_mutation(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_beta_public: ToolPublicDefinition,
    ) -> None:
        exposed = [read_public, read_beta_public]
        snapshot = bridge.freeze(exposed)

        exposed.clear()

        assert snapshot.names == ("read_alpha", "read_beta")
        assert len(snapshot.definitions) == 2

    # BR-06 — mutable framework toolset cannot mutate authority
    def test_br06_mutable_framework_toolset(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        snapshot = bridge.freeze([read_public])

        toolset_a = snapshot.to_external_toolset()
        assert len(toolset_a.tool_defs) == 1

        toolset_a.tool_defs.clear()

        toolset_b = snapshot.to_external_toolset()
        assert len(toolset_b.tool_defs) == 1
        assert toolset_b.tool_defs[0].name == "read_alpha"

        toolset_c = snapshot.to_external_toolset()
        if toolset_c.tool_defs[0].parameters_json_schema is not None:
            toolset_c.tool_defs[0].parameters_json_schema.clear()

        toolset_d = snapshot.to_external_toolset()
        assert toolset_d.tool_defs[0].parameters_json_schema is not None
        assert "properties" in toolset_d.tool_defs[0].parameters_json_schema


# ==============================================================================
# BR-07 through BR-09 — Malformed-snapshot tests
# ==============================================================================


class TestPydanticAIToolFreeze:
    """Malformed-snapshot rejection: duplicate, unknown, metadata drift."""

    # BR-07 — duplicate exposed name
    def test_br07_duplicate_exposed_name(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        with pytest.raises(ValidationError, match="Duplicate tool name"):
            bridge.freeze([read_public, read_public])

    # BR-08 — unknown public tool
    def test_br08_unknown_public_tool(
        self,
        bridge: PydanticAIToolBridge,
    ) -> None:
        unknown = ToolPublicDefinition(
            name="unknown_tool",
            description="Not in registry",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
        )
        with pytest.raises(ValidationError, match="not registered"):
            bridge.freeze([unknown])

    # BR-09 — permission mismatch
    def test_br09_permission_mismatch(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        mismatched = ToolPublicDefinition(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission=Permission.WRITE,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(read_public.allowed_session_modes, key=lambda m: m.value),
        )
        with pytest.raises(ValidationError, match="permission mismatch"):
            bridge.freeze([mismatched])

    # BR-09 — session-mode mismatch
    def test_br09_session_mode_mismatch(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        mismatched = ToolPublicDefinition(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission=read_public.permission,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=[SessionMode.ACTIVE_SESSION],
        )
        with pytest.raises(ValidationError, match="allowed_session_modes mismatch"):
            bridge.freeze([mismatched])

    # BR-09 — description mismatch
    def test_br09_description_mismatch(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        mismatched = ToolPublicDefinition(
            name=read_public.name,
            description="Wrong description",
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission=read_public.permission,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(read_public.allowed_session_modes, key=lambda m: m.value),
        )
        with pytest.raises(ValidationError, match="description mismatch"):
            bridge.freeze([mismatched])

    # BR-09 — input schema mismatch
    def test_br09_input_schema_mismatch(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        mismatched = ToolPublicDefinition(
            name=read_public.name,
            description=read_public.description,
            input_schema={"type": "object", "properties": {"wrong": {"type": "string"}}},
            output_schema=read_public.output_schema,
            permission=read_public.permission,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(read_public.allowed_session_modes, key=lambda m: m.value),
        )
        with pytest.raises(ValidationError, match="input_schema mismatch"):
            bridge.freeze([mismatched])


# ==============================================================================
# BR-10 through BR-16 — Execution tests
# ==============================================================================


class TestPydanticAIToolExecute:
    """Execution adapter: valid calls, argument parsing, rejection."""

    # BR-10 — READ execution
    def test_br10_read_execution(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="read_alpha", args='{"value": "hello"}')

        output = bridge.execute(snapshot, tool_call, execution_context=read_context)
        assert isinstance(output, ToolOutput)
        assert output.result == "alpha:hello"

    # BR-11 — JSON-string object arguments
    def test_br11_json_string_object_args(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="read_alpha", args='{"value": "x"}')

        output = bridge.execute(snapshot, tool_call, execution_context=read_context)
        assert isinstance(output, ToolOutput)
        assert output.result == "alpha:x"

    # BR-12 — malformed JSON
    def test_br12_malformed_json(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="read_alpha", args="{broken")

        with pytest.raises(ValidationError, match="Failed to parse arguments"):
            bridge.execute(snapshot, tool_call, execution_context=read_context)

    # BR-13 — non-object JSON
    def test_br13_non_object_json(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="read_alpha", args="[]")

        with pytest.raises(ValidationError, match="Failed to parse arguments"):
            bridge.execute(snapshot, tool_call, execution_context=read_context)

    # BR-14 — schema-invalid dict
    def test_br14_schema_invalid_dict(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="read_alpha", args='{"wrong_field": "x"}')

        with pytest.raises(ValidationError):
            bridge.execute(snapshot, tool_call, execution_context=read_context)

    # BR-15 — hidden live tool
    def test_br15_hidden_live_tool(
        self,
        bridge: PydanticAIToolBridge,
        registry: ToolRegistry,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])

        hidden_def = ToolDefinition(
            name="hidden_tool",
            description="Hidden from snapshot",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        def _hidden_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
            return ToolOutput(result="hidden")

        registry.register(hidden_def, _hidden_handler)

        tool_call = ToolCallPart(tool_name="hidden_tool", args='{"value": "x"}')
        with pytest.raises(ValidationError, match="not in the frozen exposure"):
            bridge.execute(snapshot, tool_call, execution_context=read_context)

    # BR-16 — completely unknown tool
    def test_br16_completely_unknown_tool(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="nonexistent_tool", args='{"value": "x"}')

        with pytest.raises(ValidationError, match="not in the frozen exposure"):
            bridge.execute(snapshot, tool_call, execution_context=read_context)


# ==============================================================================
# BR-17 through BR-20 — ToolExecutor final-authority tests
# ==============================================================================


class TestPydanticAIToolAuthority:
    """ToolExecutor final-authority: WRITE success, permission denial,
    missing audit, session-mode denial."""

    # BR-17 — WRITE success
    def test_br17_write_success(
        self,
        bridge: PydanticAIToolBridge,
        write_public: ToolPublicDefinition,
        write_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([write_public])
        tool_call = ToolCallPart(tool_name="write_alpha", args='{"value": "test"}')

        output = bridge.execute(snapshot, tool_call, execution_context=write_context)
        assert isinstance(output, ToolOutput)
        assert output.result == "write:test"

    # BR-18 — permission denial (READ authority cannot execute WRITE tool)
    def test_br18_permission_denial(
        self,
        bridge: PydanticAIToolBridge,
        write_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([write_public])
        tool_call = ToolCallPart(tool_name="write_alpha", args='{"value": "x"}')

        with pytest.raises(ConflictError, match="Permission denied"):
            bridge.execute(snapshot, tool_call, execution_context=read_context)

    # BR-19 — missing audit for WRITE tool
    def test_br19_missing_audit(
        self,
        bridge: PydanticAIToolBridge,
        write_public: ToolPublicDefinition,
        write_context_no_audit: ExecutionContext,
    ) -> None:
        snapshot = bridge.freeze([write_public])
        tool_call = ToolCallPart(tool_name="write_alpha", args='{"value": "x"}')

        with pytest.raises(ValidationError, match="requires a non-None AuditContext"):
            bridge.execute(snapshot, tool_call, execution_context=write_context_no_audit)

    # BR-20 — session-mode denial
    def test_br20_session_mode_denial(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """read_alpha allows all modes, so we need a session-only READ tool."""
        session_only_def = ToolDefinition(
            name="session_only_tool",
            description="Only allowed during active session",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
        )

        def _session_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
            return ToolOutput(result="ok")

        reg = ToolRegistry()
        reg.register(session_only_def, _session_handler)
        local_bridge = PydanticAIToolBridge(registry=reg)

        public = ToolPublicDefinition(
            name=session_only_def.name,
            description=session_only_def.description,
            input_schema=session_only_def.input_schema.model_json_schema(),
            output_schema=session_only_def.output_schema.model_json_schema(),
            permission=session_only_def.permission,
            side_effects=sorted(session_only_def.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(
                session_only_def.allowed_session_modes, key=lambda m: m.value
            ),
        )

        snapshot = local_bridge.freeze([public])

        no_session_ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        tool_call = ToolCallPart(tool_name="session_only_tool", args='{"value": "x"}')

        with pytest.raises(ConflictError, match="Session mode"):
            local_bridge.execute(snapshot, tool_call, execution_context=no_session_ctx)


# ==============================================================================
# Handler failure / output validation
# ==============================================================================


class TestPydanticAIToolErrors:
    """Handler exception propagation and output validation failure."""

    def test_handler_runtime_error_propagates(
        self,
        bridge: PydanticAIToolBridge,
        read_context: ExecutionContext,
    ) -> None:
        """A RuntimeError from the handler propagates unchanged."""
        error_def = ToolDefinition(
            name="error_tool",
            description="Tool that raises",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        def _error_handler(inp: AlphaInput, ctx: object) -> ToolOutput:
            raise RuntimeError("handler boom")

        reg = ToolRegistry()
        reg.register(error_def, _error_handler)
        local_bridge = PydanticAIToolBridge(registry=reg)

        public = ToolPublicDefinition(
            name=error_def.name,
            description=error_def.description,
            input_schema=error_def.input_schema.model_json_schema(),
            output_schema=error_def.output_schema.model_json_schema(),
            permission=error_def.permission,
            side_effects=sorted(error_def.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(error_def.allowed_session_modes, key=lambda m: m.value),
        )

        snapshot = local_bridge.freeze([public])
        tool_call = ToolCallPart(tool_name="error_tool", args='{"value": "x"}')

        with pytest.raises(RuntimeError, match="handler boom"):
            local_bridge.execute(snapshot, tool_call, execution_context=read_context)

    def test_output_validation_failure_propagates(
        self,
        bridge: PydanticAIToolBridge,
        read_context: ExecutionContext,
    ) -> None:
        """Handler returning incompatible output triggers ToolExecutor ValidationError."""
        bad_output_def = ToolDefinition(
            name="bad_output_tool",
            description="Returns wrong type",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        def _bad_handler(inp: AlphaInput, ctx: object) -> str:
            return "not_a_pydantic_model"

        reg = ToolRegistry()
        reg.register(bad_output_def, _bad_handler)
        local_bridge = PydanticAIToolBridge(registry=reg)

        public = ToolPublicDefinition(
            name=bad_output_def.name,
            description=bad_output_def.description,
            input_schema=bad_output_def.input_schema.model_json_schema(),
            output_schema=bad_output_def.output_schema.model_json_schema(),
            permission=bad_output_def.permission,
            side_effects=sorted(bad_output_def.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(
                bad_output_def.allowed_session_modes, key=lambda m: m.value
            ),
        )

        snapshot = local_bridge.freeze([public])
        tool_call = ToolCallPart(tool_name="bad_output_tool", args='{"value": "x"}')

        with pytest.raises(ValidationError):
            local_bridge.execute(snapshot, tool_call, execution_context=read_context)


# ==============================================================================
# Architecture assertion — no direct framework execution
# ==============================================================================


class TestPydanticAIToolArchitecture:
    """Verify the bridge does not use prohibited framework patterns."""

    def test_no_framework_handler_in_bridge_source(self) -> None:
        """The bridge source must not contain @agent.tool or ToolBinding.handler."""
        import pathlib

        source = (
            pathlib.Path(__file__).parent.parent.parent
            / "src"
            / "dnd_assistant"
            / "application"
            / "pydantic_ai_tool_bridge.py"
        )
        text = source.read_text(encoding="utf-8")

        assert "@agent.tool" not in text, "Bridge must not use @agent.tool decorator"
        assert "@agent.tool_plain" not in text, "Bridge must not use @agent.tool_plain decorator"
        assert "ToolBinding.handler" not in text and "binding.handler" not in text, (
            "Bridge must not access ToolBinding.handler directly"
        )

    def test_executor_is_tool_executor(self) -> None:
        """Verify the bridge's internal executor is a ToolExecutor instance."""
        reg = ToolRegistry()
        bridge = PydanticAIToolBridge(registry=reg)
        executor = bridge._get_executor()
        assert isinstance(executor, ToolExecutor)
