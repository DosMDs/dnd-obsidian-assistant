"""Unit tests for ``select_agent_tools`` — deterministic Fast-Agent tool exposure.

Covers:

- Permission eligibility (READ, WRITE, WRITE + missing audit, malformed permission).
- Session-mode eligibility (ACTIVE_SESSION, NO_ACTIVE_SESSION, both).
- Combined intersection eligibility.
- Empty catalog.
- Order preservation.
- Non-mutation of inputs.
- No execution side effects (module-import and fresh-process levels).
- TypeError for invalid argument types.
- Malformed ``granted_permission`` fails closed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

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


# ── Malformed permission fails closed ────────────────────────────────────────────


class TestMalformedPermission:
    """Regression: unexpected ``granted_permission`` values must fail closed.

    ``ExecutionContext`` is a frozen dataclass and does not runtime-validate
    its annotations.  A malformed value (e.g. a plain string, wrong enum,
    or object) must never accidentally acquire WRITE-equivalent exposure.
    """

    def test_malformed_string_does_not_expose_read_tool(self) -> None:
        """A plain string ``granted_permission`` must not expose any tool."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "bogus_value"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        result = select_agent_tools(catalog, context=context)
        assert result == [], "malformed permission must not expose READ tools"

    def test_malformed_string_does_not_expose_write_tool(self) -> None:
        """A plain string ``granted_permission`` must not expose WRITE tools."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "bogus_value"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                ),
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], "malformed permission must not expose WRITE tools"

    def test_malformed_string_with_audit_does_not_expose_write_tool(self) -> None:
        """Even with audit present, malformed permission must not expose WRITE tools."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "bogus_value"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=AuditContext(
                    operation_id="test-op",
                    real_time=datetime(2026, 9, 3, tzinfo=UTC),
                    source="test",
                ),
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                ),
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], "malformed permission with audit must not expose WRITE tools"

    def test_wrong_permission_enum_value_does_not_expose_tools(self) -> None:
        """A valid Permission enum value that is neither READ nor WRITE must fail closed."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "nonexistent"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        result = select_agent_tools(catalog, context=context)
        assert result == [], "unexpected Permission value must not expose tools"


# ── StrEnum boundary: Permission same-value strings ──────────────────────────────


class TestStrEnumPermissionBoundary:
    """Regression: plain strings matching StrEnum values must NOT acquire authority.

    ``Permission`` is a ``StrEnum``, so ``"read" == Permission.READ`` is
    ``True`` in Python.  The selector must use ``isinstance`` + ``is``
    (identity) to reject structurally malformed values.
    """

    def test_plain_string_read_does_not_expose_read_tool(self) -> None:
        """Plain string ``"read"`` must not expose READ tools."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "read"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        result = select_agent_tools(catalog, context=context)
        assert result == [], 'plain string "read" must not expose READ tools'

    def test_plain_string_write_does_not_expose_read_tool(self) -> None:
        """Plain string ``"write"`` must not expose READ tools."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "write"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        result = select_agent_tools(catalog, context=context)
        assert result == [], 'plain string "write" must not expose READ tools'

    def test_plain_string_write_does_not_expose_write_tool_with_audit(self) -> None:
        """Plain string ``"write"`` must not expose WRITE tools even with audit."""
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, "write"),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=AuditContext(
                    operation_id="test-op",
                    real_time=datetime(2026, 9, 3, tzinfo=UTC),
                    source="test",
                ),
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                ),
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], 'plain string "write" with audit must not expose WRITE tools'


# ── Foreign StrEnum permission ───────────────────────────────────────────────────


class _ForeignPermission(StrEnum):
    """Test-only foreign StrEnum whose values match Permission members."""

    READ = "read"
    WRITE = "write"


class TestForeignStrEnumPermission:
    """Regression: a foreign StrEnum with matching values must not acquire authority."""

    def test_foreign_read_does_not_expose_read_tool(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, _ForeignPermission.READ),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        result = select_agent_tools(catalog, context=context)
        assert result == [], "foreign StrEnum READ must not expose READ tools"

    def test_foreign_write_does_not_expose_read_tool(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, _ForeignPermission.WRITE),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(tools=[_make_tool("read_tool", permission=Permission.READ)])
        result = select_agent_tools(catalog, context=context)
        assert result == [], "foreign StrEnum WRITE must not expose READ tools"

    def test_foreign_write_does_not_expose_write_tool_with_audit(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=cast(Permission, _ForeignPermission.WRITE),  # type: ignore[unused-ignore]
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=AuditContext(
                    operation_id="test-op",
                    real_time=datetime(2026, 9, 3, tzinfo=UTC),
                    source="test",
                ),
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "write_tool",
                    permission=Permission.WRITE,
                    side_effects=[SideEffect.ENTITY_MUTATION],
                ),
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], "foreign StrEnum WRITE with audit must not expose WRITE tools"


# ── StrEnum boundary: SessionMode same-value strings ─────────────────────────────


class TestStrEnumSessionModeBoundary:
    """Regression: plain strings matching SessionMode StrEnum values must be rejected."""

    def test_plain_string_active_session_does_not_expose_active_tool(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=cast(SessionMode, "active_session"),  # type: ignore[unused-ignore]
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "active_tool",
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], 'plain string "active_session" must not expose tools'

    def test_plain_string_no_active_session_does_not_expose_no_session_tool(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=cast(SessionMode, "no_active_session"),  # type: ignore[unused-ignore]
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "no_session_tool",
                    allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
                )
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], 'plain string "no_active_session" must not expose tools'


# ── Foreign StrEnum session mode ─────────────────────────────────────────────────


class _ForeignSessionMode(StrEnum):
    """Test-only foreign StrEnum whose values match SessionMode members."""

    ACTIVE_SESSION = "active_session"
    NO_ACTIVE_SESSION = "no_active_session"


class TestForeignStrEnumSessionMode:
    """Regression: a foreign StrEnum with matching session-mode values must be rejected."""

    def test_foreign_active_session_does_not_expose_active_tool(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=cast(SessionMode, _ForeignSessionMode.ACTIVE_SESSION),  # type: ignore[unused-ignore]
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "active_tool",
                    allowed_session_modes=[SessionMode.ACTIVE_SESSION],
                )
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], "foreign StrEnum ACTIVE_SESSION must not expose tools"

    def test_foreign_no_active_session_does_not_expose_no_session_tool(self) -> None:
        context = cast(
            ExecutionContext,
            ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=cast(SessionMode, _ForeignSessionMode.NO_ACTIVE_SESSION),  # type: ignore[unused-ignore]
                audit=None,
            ),
        )
        catalog = ToolRegistrySchema(
            tools=[
                _make_tool(
                    "no_session_tool",
                    allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
                )
            ]
        )
        result = select_agent_tools(catalog, context=context)
        assert result == [], "foreign StrEnum NO_ACTIVE_SESSION must not expose tools"


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

    Verified at two levels:
    1. Fresh-process import: a subprocess that imports only
       ``agent_tool_selection`` must NOT eagerly load forbidden modules.
    2. Structural: this test module does not import or instantiate any
       executor/handler/Vault/network components.
    """

    def test_fresh_process_does_not_eagerly_load_forbidden_modules(self) -> None:
        """Fresh-process import must not load models, executor, storage, etc.

        This is a subprocess-based regression test for the S9-C00 import-boundary
        fix.  A child process imports only ``agent_tool_selection`` and inspects
        ``sys.modules`` for forbidden ``dnd_assistant.*`` subpackages.

        Must pass on Windows and macOS without Bash/shell-specific commands.
        """
        code = textwrap.dedent("""\
            import sys

            # Import only the module under test.
            import dnd_assistant.application.agent_tool_selection

            # Collect all loaded dnd_assistant.* module prefixes.
            loaded = {
                name
                for name in sys.modules
                if name.startswith("dnd_assistant.")
            }

            # Forbidden subpackages that must NOT be eagerly loaded.
            forbidden = {
                "dnd_assistant.models",
                "dnd_assistant.models.ollama",
                "dnd_assistant.tools.executor",
                "dnd_assistant.storage",
                "dnd_assistant.retrieval",
                "dnd_assistant.cli",
            }

            # Report for diagnostics.
            print("Loaded dnd_assistant.* modules:", sorted(loaded))
            print("Forbidden intersection:", sorted(loaded & forbidden))

            # Assert no forbidden module is loaded.
            assert not (loaded & forbidden), (
                f"Fresh import loads forbidden modules: {loaded & forbidden}"
            )
        """)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        assert result.returncode == 0, (
            f"Fresh-process import test failed (exit {result.returncode}): {result.stderr}"
        )
