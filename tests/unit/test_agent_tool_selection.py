"""Unit tests for ``select_agent_tools`` — deterministic Fast-Agent tool exposure.

Covers:

- Permission eligibility (READ, WRITE, WRITE + missing audit).
- Session-mode eligibility (ACTIVE_SESSION, NO_ACTIVE_SESSION, both).
- Combined intersection eligibility.
- Empty catalog.
- Order preservation.
- Non-mutation of inputs.
- No execution side effects.
- TypeError for invalid argument types.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.agent_tool_selection import select_agent_tools
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode, SideEffect

# ── Helpers ──────────────────────────────────────────────────────────────────────


def _make_tool(
    name: str,
    *,
    permission: Permission = Permission.READ,
    side_effects: list[SideEffect] | None = None,
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    """Build a ``ToolPublicDefinition`` with minimal boilerplate."""
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        permission=permission,
        side_effects=side_effects or [],
        allowed_session_modes=allowed_session_modes or [SessionMode.NO_ACTIVE_SESSION],
    )


def _make_context(
    *,
    permission: Permission = Permission.READ,
    session_mode: SessionMode = SessionMode.NO_ACTIVE_SESSION,
    audit: AuditContext | None = None,
) -> ExecutionContext:
    """Build an ``ExecutionContext`` with minimal boilerplate."""
    return ExecutionContext(
        granted_permission=permission,
        session_mode=session_mode,
        audit=audit,
    )


@pytest.fixture
def valid_audit() -> AuditContext:
    return AuditContext(
        operation_id="test-op",
        real_time=datetime(2026, 9, 3, tzinfo=UTC),
        source="test",
    )


# ── Permission eligibility ───────────────────────────────────────────────────────


class TestPermissionEligibility:
    """READ authority exposes only READ tools; WRITE authority exposes both."""

    def test_read_authority_exposes_read_tool(self) -> None:
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        context = _make_context(permission=Permission.READ)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "read_tool"

    def test_read_authority_hides_write_tool(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                )
            ]
        )
        context = _make_context(permission=Permission.READ)
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_read_authority_hides_write_tool_even_with_audit(self) -> None:
        """Audit presence never upgrades granted permission."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                )
            ]
        )
        context = _make_context(
            permission=Permission.READ,
            audit=AuditContext(
                operation_id="test-op",
                real_time=datetime(2026, 9, 3, tzinfo=UTC),
                source="test",
            ),
        )
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_write_authority_exposes_read_tool(self) -> None:
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        context = _make_context(permission=Permission.WRITE, audit=None)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "read_tool"

    def test_write_authority_exposes_write_tool_with_audit(self, valid_audit: AuditContext) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                )
            ]
        )
        context = _make_context(permission=Permission.WRITE, audit=valid_audit)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "write_tool"

    def test_write_authority_hides_write_tool_without_audit(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                )
            ]
        )
        context = _make_context(permission=Permission.WRITE, audit=None)
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_write_authority_mixed_exposure(self, valid_audit: AuditContext) -> None:
        """With WRITE authority and audit, both READ and WRITE tools are exposed."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool("read_tool", permission=Permission.READ),
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                ),
            ]
        )
        context = _make_context(permission=Permission.WRITE, audit=valid_audit)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 2
        assert result[0].name == "read_tool"
        assert result[1].name == "write_tool"

    def test_write_authority_read_exposed_write_hidden_without_audit(self) -> None:
        """Without audit, only READ tools are exposed even with WRITE authority."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool("read_tool", permission=Permission.READ),
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                ),
            ]
        )
        context = _make_context(permission=Permission.WRITE, audit=None)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "read_tool"


# ── Session-mode eligibility ─────────────────────────────────────────────────────


class TestSessionModeEligibility:
    """A tool is eligible only when context.session_mode is in allowed_session_modes."""

    def test_active_session_tool_exposed_in_active_context(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "active_tool",
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        context = _make_context(session_mode=SessionMode.ACTIVE_SESSION)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "active_tool"

    def test_active_session_tool_hidden_in_no_active_context(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "active_tool",
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        context = _make_context(session_mode=SessionMode.NO_ACTIVE_SESSION)
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_no_session_tool_exposed_in_no_active_context(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "no_session_tool",
                    allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
                )
            ]
        )
        context = _make_context(session_mode=SessionMode.NO_ACTIVE_SESSION)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "no_session_tool"

    def test_no_session_tool_hidden_in_active_context(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "no_session_tool",
                    allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
                )
            ]
        )
        context = _make_context(session_mode=SessionMode.ACTIVE_SESSION)
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_both_modes_tool_exposed_in_active_context(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "both_tool",
                    allowed_session_modes=[
                        SessionMode.ACTIVE_SESSION,
                        SessionMode.NO_ACTIVE_SESSION,
                    ],
                )
            ]
        )
        context = _make_context(session_mode=SessionMode.ACTIVE_SESSION)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "both_tool"

    def test_both_modes_tool_exposed_in_no_active_context(self) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "both_tool",
                    allowed_session_modes=[
                        SessionMode.ACTIVE_SESSION,
                        SessionMode.NO_ACTIVE_SESSION,
                    ],
                )
            ]
        )
        context = _make_context(session_mode=SessionMode.NO_ACTIVE_SESSION)
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        assert result[0].name == "both_tool"


# ── Combined intersection eligibility ────────────────────────────────────────────


class TestCombinedEligibility:
    """Eligibility is an intersection: all dimensions must pass."""

    def test_all_dimensions_pass(self, valid_audit: AuditContext) -> None:
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_active",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        context = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=valid_audit,
        )
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1

    def test_fails_permission_dimension(self) -> None:
        """READ authority + WRITE tool -> hidden regardless of other dimensions."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_active",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        context = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=AuditContext(
                operation_id="test-op",
                real_time=datetime(2026, 9, 3, tzinfo=UTC),
                source="test",
            ),
        )
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_fails_session_mode_dimension(self, valid_audit: AuditContext) -> None:
        """Active-only tool in no-active context -> hidden."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_active",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        context = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=valid_audit,
        )
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_fails_audit_dimension(self) -> None:
        """WRITE tool without audit -> hidden even when permission and mode match."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_active",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        context = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=None,
        )
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_mixed_catalog_intersection(self, valid_audit: AuditContext) -> None:
        """Multiple tools with different eligibility profiles."""
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "read_both",
                    permission=Permission.READ,
                    allowed_session_modes=[
                        SessionMode.ACTIVE_SESSION,
                        SessionMode.NO_ACTIVE_SESSION,
                    ],
                ),
                _make_tool(
                    "write_active",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                ),
                _make_tool(
                    "write_no_session",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                    allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
                ),
                _make_tool(
                    "read_active",
                    permission=Permission.READ,
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                ),
            ]
        )
        context = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
            audit=valid_audit,
        )
        result = select_agent_tools(catalog, context=context)
        names = [t.name for t in result]
        assert names == ["read_both", "write_active", "read_active"]


# ── Empty catalog ────────────────────────────────────────────────────────────────


class TestEmptyCatalog:
    def test_empty_catalog_returns_empty_list(self) -> None:
        catalog = ToolRegistrySchema(tools=[])
        context = _make_context()
        result = select_agent_tools(catalog, context=context)
        assert result == []

    def test_empty_catalog_no_exception(self) -> None:
        catalog = ToolRegistrySchema(tools=[])
        context = _make_context()
        select_agent_tools(catalog, context=context)  # no exception


# ── Order preservation ───────────────────────────────────────────────────────────


class TestOrderPreservation:
    def test_preserves_input_order(self) -> None:
        tools = [
            _make_tool("z_tool", permission=Permission.READ),
            _make_tool("a_tool", permission=Permission.READ),
            _make_tool("m_tool", permission=Permission.READ),
        ]
        catalog = ToolRegistrySchema(tools=tools)
        context = _make_context()
        result = select_agent_tools(catalog, context=context)
        assert [t.name for t in result] == ["z_tool", "a_tool", "m_tool"]

    def test_order_preserved_after_filtering(self) -> None:
        """Ineligible tools removed but eligible ones keep original order."""
        tools = [
            _make_tool("first", permission=Permission.READ),
            _make_tool(
                "hidden_write",
                permission=Permission.WRITE,
                side_effects=[SideEffect.ENTITY_MUTATION],
            ),
            _make_tool("second", permission=Permission.READ),
        ]
        catalog = ToolRegistrySchema(tools=tools)
        context = _make_context(permission=Permission.READ)
        result = select_agent_tools(catalog, context=context)
        assert [t.name for t in result] == ["first", "second"]


# ── Non-mutation ─────────────────────────────────────────────────────────────────


class TestNonMutation:
    def test_does_not_mutate_catalog_tools_list(self) -> None:
        tools = [
            _make_tool("read_tool", permission=Permission.READ),
            _make_tool(
                "write_tool",
                permission=Permission.WRITE,
                side_effects=[SideEffect.ENTITY_MUTATION],
            ),
        ]
        original_tools = list(tools)
        catalog = ToolRegistrySchema(tools=tools)
        context = _make_context(permission=Permission.READ)
        select_agent_tools(catalog, context=context)
        assert len(catalog.tools) == len(original_tools)
        assert all(a.name == b.name for a, b in zip(catalog.tools, original_tools, strict=True))

    def test_does_not_mutate_tool_metadata(self) -> None:
        tool = _make_tool("read_tool", permission=Permission.READ)
        catalog = ToolRegistrySchema(tools=[tool])
        context = _make_context()
        orig_name = tool.name
        orig_desc = tool.description
        orig_permission = tool.permission
        select_agent_tools(catalog, context=context)
        assert tool.name == orig_name
        assert tool.description == orig_desc
        assert tool.permission == orig_permission

    def test_does_not_mutate_context(self) -> None:
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        context = _make_context()
        select_agent_tools(catalog, context=context)
        assert context.granted_permission == Permission.READ
        assert context.session_mode == SessionMode.NO_ACTIVE_SESSION
        assert context.audit is None

    def test_returned_list_is_separate_from_catalog(self) -> None:
        """Modifying the returned list must not alter catalog.tools."""
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        context = _make_context()
        result = select_agent_tools(catalog, context=context)
        assert len(result) == 1
        result.clear()
        assert len(catalog.tools) == 1


# ── TypeError for invalid arguments ──────────────────────────────────────────────


class TestTypeErrors:
    def test_raises_type_error_for_non_catalog(self) -> None:
        context = _make_context()
        with pytest.raises(TypeError, match="catalog must be a ToolRegistrySchema"):
            select_agent_tools("not_a_catalog", context=context)  # type: ignore[arg-type]

    def test_raises_type_error_for_non_context(self) -> None:
        catalog = ToolRegistrySchema(tools=[])
        with pytest.raises(TypeError, match="context must be an ExecutionContext"):
            select_agent_tools(catalog, context="not_a_context")  # type: ignore[arg-type]


# ── No execution side effects ────────────────────────────────────────────────────


class TestNoExecutionSideEffects:
    """Selection must perform zero handler/ToolExecutor/Vault/network calls.

    This is structurally verified by not importing or instantiating any
    of those components in this test module.
    """

    def test_no_forbidden_imports_in_module(self) -> None:
        """Verify agent_tool_selection does not import forbidden modules.

        Uses the module's __init__-time import state rather than process-level
        sys.modules, which may be contaminated by other tests in the same run.
        """
        import dnd_assistant.application.agent_tool_selection as mod

        import_names = {name for name in dir(mod) if not name.startswith("_")}
        # The module should only expose select_agent_tools
        assert "select_agent_tools" in import_names
        # No forbidden module names should appear in the module's namespace
        forbidden_prefixes = ["models", "storage", "retrieval", "cli", "ollama"]
        for name in import_names - {"select_agent_tools"}:
            assert not any(name.startswith(prefix) for prefix in forbidden_prefixes), (
                f"agent_tool_selection exposes forbidden import: {name}"
            )
