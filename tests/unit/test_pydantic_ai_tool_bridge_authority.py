"""Authority, provenance, and structural-validation tests for Pydantic AI
tool bridge (PAIM-C07).

These tests verify:

- Cross-bridge snapshot rejection (Bridge A snapshot cannot execute in Bridge B)
- Forged/manual snapshot rejection
- Tampered-copy (dataclasses.replace) rejection
- Foreign-StrEnum impostor rejection (C07-E1 through C07-E4)
- Structural ToolCallPart, snapshot, and ExecutionContext validation
- Side-effect and output-schema drift rejection
- Same-name cross-bridge handler isolation
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ToolCallPart

from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
    PydanticAIToolSnapshot,
)
from dnd_assistant.errors import ValidationError
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

# ── Foreign StrEnum impostors ────────────────────────────────────────────────


class ForeignPermission(StrEnum):
    READ = "read"
    WRITE = "write"


class ForeignSessionMode(StrEnum):
    ACTIVE_SESSION = "active_session"
    NO_ACTIVE_SESSION = "no_active_session"


class ForeignSideEffect(StrEnum):
    ENTITY_MUTATION = "entity_mutation"


# ── Shared test schemas ──────────────────────────────────────────────────────


class AlphaInput(BaseModel):
    value: str


class ToolOutput(BaseModel):
    result: str


# ── Handler counters ─────────────────────────────────────────────────────────


@dataclass
class HandlerCounters:
    alpha_a: int = 0
    alpha_b: int = 0


# ── Fixtures ─────────────────────────────────────────────────────────────────


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
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def registry(read_tool_def: ToolDefinition, write_tool_def: ToolDefinition) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_tool_def, lambda inp, ctx: ToolOutput(result="ok"))
    reg.register(write_tool_def, lambda inp, ctx: ToolOutput(result="ok"))
    return reg


@pytest.fixture
def bridge(registry: ToolRegistry) -> PydanticAIToolBridge:
    return PydanticAIToolBridge(registry=registry)


# ==============================================================================
# Forged/manual snapshot authority
# ==============================================================================


class TestForgedSnapshotAuthority:
    """A manually constructed snapshot must not become execution authority."""

    def test_forged_snapshot_execution_rejected(
        self,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        """A manually constructed PydanticAIToolSnapshot must be rejected."""
        reg = ToolRegistry()
        bridge = PydanticAIToolBridge(registry=reg)

        forged_def = ToolDefinition(
            name="forged_tool",
            description="Forged definition",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        forged_snapshot = PydanticAIToolSnapshot._create(
            definitions=(forged_def,),
            owner_token=object(),
        )

        tool_call = ToolCallPart(tool_name="forged_tool", args='{"value": "x"}')

        with pytest.raises(ValidationError, match="different bridge"):
            bridge.execute(forged_snapshot, tool_call, execution_context=read_context)

    def test_forged_snapshot_toolset_rejected(self) -> None:
        """A manually constructed snapshot must not generate framework exposure."""
        reg = ToolRegistry()
        bridge = PydanticAIToolBridge(registry=reg)

        forged_def = ToolDefinition(
            name="forged_tool",
            description="Forged",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        forged_snapshot = PydanticAIToolSnapshot._create(
            definitions=(forged_def,),
            owner_token=object(),
        )

        with pytest.raises(ValidationError, match="different bridge"):
            bridge.to_external_toolset(forged_snapshot)


# ==============================================================================
# Tampered-copy defense
# ==============================================================================


class TestTamperedCopyDefense:
    """A frozen snapshot must resist dataclasses.replace expansion."""

    def test_tampered_copy_rejected(
        self,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        """dataclasses.replace on a valid snapshot must produce a rejected copy."""
        reg = ToolRegistry()
        reg.register(
            ToolDefinition(
                name="read_alpha",
                description="A read-only test tool",
                input_schema=AlphaInput,
                output_schema=ToolOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset(
                    {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
                ),
            ),
            lambda inp, ctx: ToolOutput(result="ok"),
        )
        bridge = PydanticAIToolBridge(registry=reg)

        snapshot = bridge.freeze([read_public])

        extra_def = ToolDefinition(
            name="extra_tool",
            description="Extra tool not in original freeze",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        tampered = dataclasses.replace(
            snapshot,
            definitions=snapshot.definitions + (extra_def,),
        )

        tool_call = ToolCallPart(tool_name="extra_tool", args='{"value": "x"}')

        with pytest.raises(ValidationError, match="no longer registered"):
            bridge.execute(tampered, tool_call, execution_context=read_context)


# ==============================================================================
# Cross-bridge authority
# ==============================================================================


class TestCrossBridgeAuthority:
    """A snapshot from Bridge A cannot execute or generate exposure in Bridge B."""

    def test_cross_bridge_execution_rejected(self) -> None:
        """Bridge B must reject execution of a snapshot created by Bridge A."""
        counters = HandlerCounters()

        def handler_a(inp: AlphaInput, ctx: object) -> ToolOutput:
            counters.alpha_a += 1
            return ToolOutput(result="a")

        def handler_b(inp: AlphaInput, ctx: object) -> ToolOutput:
            counters.alpha_b += 1
            return ToolOutput(result="b")

        common_def = ToolDefinition(
            name="same_tool",
            description="Same name, different handler",
            input_schema=AlphaInput,
            output_schema=ToolOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )

        reg_a = ToolRegistry()
        reg_a.register(common_def, handler_a)

        reg_b = ToolRegistry()
        reg_b.register(common_def, handler_b)

        bridge_a = PydanticAIToolBridge(registry=reg_a)
        bridge_b = PydanticAIToolBridge(registry=reg_b)

        public = ToolPublicDefinition(
            name="same_tool",
            description="Same name, different handler",
            input_schema=AlphaInput.model_json_schema(),
            output_schema=ToolOutput.model_json_schema(),
            permission=Permission.READ,
            side_effects=[],
            allowed_session_modes=[
                SessionMode.NO_ACTIVE_SESSION,
                SessionMode.ACTIVE_SESSION,
            ],
        )

        snapshot_a = bridge_a.freeze([public])
        tool_call = ToolCallPart(tool_name="same_tool", args='{"value": "x"}')
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )

        with pytest.raises(ValidationError, match="different bridge"):
            bridge_b.execute(snapshot_a, tool_call, execution_context=ctx)

        assert counters.alpha_a == 0
        assert counters.alpha_b == 0

    def test_cross_bridge_toolset_rejected(self) -> None:
        """Bridge B must reject framework exposure from Bridge A's snapshot."""
        reg = ToolRegistry()
        bridge_a = PydanticAIToolBridge(registry=reg)
        bridge_b = PydanticAIToolBridge(registry=reg)

        snapshot = bridge_a.freeze([])

        with pytest.raises(ValidationError, match="different bridge"):
            bridge_b.to_external_toolset(snapshot)


# ==============================================================================
# Foreign-StrEnum impostor rejection (C07-E1 through C07-E4)
# ==============================================================================


class TestForeignStrEnumImpostors:
    """Foreign same-value StrEnum values must be rejected during freeze()."""

    # C07-E1 — foreign permission
    def test_c07e1_foreign_permission_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """A ForeignPermission with the same textual value must be rejected."""
        impostor = ToolPublicDefinition.model_construct(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission=ForeignPermission.READ,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(read_public.allowed_session_modes, key=lambda m: m.value),
        )
        with pytest.raises(ValidationError, match="not a valid Permission"):
            bridge.freeze([impostor])

    # C07-E2 — foreign session mode
    def test_c07e2_foreign_session_mode_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """A ForeignSessionMode with the same textual value must be rejected."""
        impostor = ToolPublicDefinition.model_construct(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission=read_public.permission,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=[ForeignSessionMode.ACTIVE_SESSION],
        )
        with pytest.raises(ValidationError, match="not the expected enum type"):
            bridge.freeze([impostor])

    # C07-E3 — foreign side effect
    def test_c07e3_foreign_side_effect_rejected(
        self,
        bridge: PydanticAIToolBridge,
        write_tool_def: ToolDefinition,
    ) -> None:
        """A ForeignSideEffect with the same textual value must be rejected."""
        public = ToolPublicDefinition(
            name=write_tool_def.name,
            description=write_tool_def.description,
            input_schema=write_tool_def.input_schema.model_json_schema(),
            output_schema=write_tool_def.output_schema.model_json_schema(),
            permission=write_tool_def.permission,
            side_effects=[SideEffect.ENTITY_MUTATION],
            allowed_session_modes=sorted(
                write_tool_def.allowed_session_modes, key=lambda m: m.value
            ),
        )
        impostor = ToolPublicDefinition.model_construct(
            name=public.name,
            description=public.description,
            input_schema=public.input_schema,
            output_schema=public.output_schema,
            permission=public.permission,
            side_effects=[ForeignSideEffect.ENTITY_MUTATION],
            allowed_session_modes=public.allowed_session_modes,
        )
        with pytest.raises(ValidationError, match="not the expected enum type"):
            bridge.freeze([impostor])

    # C07-E4 — plain-string impostor
    def test_c07e4_plain_string_impostor_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """A plain string value in an enum field must be rejected."""
        impostor = ToolPublicDefinition.model_construct(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission="read",
            side_effects=[],
            allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
        )
        with pytest.raises(ValidationError, match="not a valid Permission"):
            bridge.freeze([impostor])


# ==============================================================================
# Structural-input validation
# ==============================================================================


class TestStructuralInputValidation:
    """Structural validation of ToolCallPart, snapshot, and ExecutionContext."""

    # C07-T1 — malformed tool_call
    def test_c07t1_malformed_tool_call_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
        read_context: ExecutionContext,
    ) -> None:
        """A non-ToolCallPart must be rejected as ValidationError."""
        snapshot = bridge.freeze([read_public])

        with pytest.raises(ValidationError, match="must be a ToolCallPart"):
            bridge.execute(
                snapshot,
                tool_call=object(),  # type: ignore[arg-type]
                execution_context=read_context,
            )

    # C07-T2 — malformed snapshot
    def test_c07t2_malformed_snapshot_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_context: ExecutionContext,
    ) -> None:
        """A non-PydanticAIToolSnapshot must be rejected as ValidationError."""
        tool_call = ToolCallPart(tool_name="read_alpha", args='{"value": "x"}')

        with pytest.raises(ValidationError, match="must be a PydanticAIToolSnapshot"):
            bridge.execute(
                snapshot=object(),  # type: ignore[arg-type]
                tool_call=tool_call,
                execution_context=read_context,
            )

    # C07-T3 — malformed ExecutionContext
    def test_c07t3_malformed_context_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """A non-ExecutionContext must be rejected as ValidationError."""
        snapshot = bridge.freeze([read_public])
        tool_call = ToolCallPart(tool_name="read_alpha", args='{"value": "x"}')

        with pytest.raises(ValidationError, match="must be an ExecutionContext"):
            bridge.execute(
                snapshot,
                tool_call=tool_call,
                execution_context=object(),  # type: ignore[arg-type]
            )


# ==============================================================================
# Metadata drift rejection
# ==============================================================================


class TestMetadataDrift:
    """Side-effect and output-schema drift must be rejected during freeze()."""

    def test_side_effect_drift_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """A public definition with mismatched side effects must be rejected."""
        drifted = ToolPublicDefinition(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema=read_public.output_schema,
            permission=read_public.permission,
            side_effects=[SideEffect.ENTITY_MUTATION],
            allowed_session_modes=sorted(read_public.allowed_session_modes, key=lambda m: m.value),
        )
        with pytest.raises(ValidationError, match="cardinality mismatch"):
            bridge.freeze([drifted])

    def test_output_schema_drift_rejected(
        self,
        bridge: PydanticAIToolBridge,
        read_public: ToolPublicDefinition,
    ) -> None:
        """A public definition with mismatched output schema must be rejected."""
        drifted = ToolPublicDefinition(
            name=read_public.name,
            description=read_public.description,
            input_schema=read_public.input_schema,
            output_schema={"type": "object", "properties": {"wrong": {"type": "string"}}},
            permission=read_public.permission,
            side_effects=sorted(read_public.side_effects, key=lambda e: e.value),
            allowed_session_modes=sorted(read_public.allowed_session_modes, key=lambda m: m.value),
        )
        with pytest.raises(ValidationError, match="output_schema mismatch"):
            bridge.freeze([drifted])
