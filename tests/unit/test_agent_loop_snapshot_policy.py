"""Exposed-tool snapshot policy tests for the Fast Agent loop (S9-C07).

Tests that the multi-call safety policy fails closed on structurally
inconsistent exposed-tool snapshots:

- Missing exposed definitions
- Duplicate exposed definitions (READ+READ, READ+WRITE, WRITE+READ)
- Malformed Permission values (plain strings, None, foreign StrEnum)
- Defense-in-depth via manually constructed AgentDecision bypassing
  normal FastAgent.decide() validation

Normal valid snapshots (2/4 READ batches, single WRITE, etc.) remain
unchanged and are covered in test_agent_loop_multi_tool.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

import pytest

from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.fast_agent import AgentDecision
from dnd_assistant.errors import ModelError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)

_FAKE_WORLD_TICK = 12345


# ── Foreign StrEnum for malformed-permission tests ────────────────────────


class ForeignPermission(StrEnum):
    READ = "read"
    WRITE = "write"


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_context_with(
    *,
    user_input: str = "test",
) -> object:
    from dnd_assistant.application.agent_context import AgentContext as AC

    return AC(
        user_input=user_input,
        current_world_tick=_FAKE_WORLD_TICK,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
    )


def _make_tool_response(
    *,
    content: str | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> ToolAwareResponse:
    return ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tuple(tool_calls or []),
        ),
    )


def _make_single_message_request() -> ChatRequest:
    """Build a valid ChatRequest with exactly one message."""
    return ChatRequest(
        messages=(ChatMessage(role=MessageRole.USER, content="test"),),
    )


def _make_tool_call(
    name: str,
    arguments: dict[str, object] | None = None,
    call_id: str | None = None,
) -> ToolCall:
    return ToolCall(
        name=name,
        arguments=arguments or {},
        call_id=call_id,
    )


def _make_tool_public(
    name: str,
    *,
    permission: Permission = Permission.READ,
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permission=permission,
        side_effects=[],
        allowed_session_modes=allowed_session_modes
        or [SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION],
    )


def _make_write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


# ── Fake FastAgent returning a manually constructed AgentDecision ─────────


class _FakeFastAgent:
    """Test double that returns a manually constructed AgentDecision.

    This bypasses normal FastAgent.decide() validation so that tests can
    exercise AgentLoop defence in depth against structurally inconsistent
    exposed-tool snapshots.
    """

    def __init__(self, decision: AgentDecision) -> None:
        self._decision = decision

    def decide(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentDecision:
        return self._decision


class _FakeAgentContextBuilder:
    def __init__(self) -> None:
        self.build_call_count: int = 0

    def build(self, user_input: str) -> object:
        self.build_call_count += 1
        return _make_context_with()


class _FakeModelGateway:
    def __init__(self) -> None:
        self.chat_with_tools_call_count: int = 0

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.chat_with_tools_call_count += 1
        return _make_tool_response(content='{"kind":"respond","message":"done"}')

    def chat(self, request: ChatRequest) -> None:
        raise AssertionError("chat() should not be called")

    def generate_structured(self, request: ChatRequest, schema: type) -> None:
        raise AssertionError("generate_structured() should not be called")

    def embed(self, texts: list[str]) -> None:
        raise AssertionError("embed() should not be called")

    def health(self) -> None:
        raise AssertionError("health() should not be called")


class _FakeToolExecutionService:
    """Records calls but does not validate exposed tools."""

    def __init__(self) -> None:
        self.execute_call_count: int = 0

    def execute(
        self,
        decision: AgentDecision,
        tool_call: ToolCall,
        *,
        execution_context: ExecutionContext,
    ) -> object:
        self.execute_call_count += 1
        return None


def _make_agent_loop_with_fake_fast_agent(
    decision: AgentDecision,
    tool_catalog: ToolRegistrySchema | None = None,
) -> AgentLoop:
    """Build an AgentLoop whose _fast_agent is replaced by a _FakeFastAgent.

    This is the same established pattern used for S9-C05 private-coupling
    regression tests.
    """
    builder = _FakeAgentContextBuilder()
    gateway = _FakeModelGateway()
    catalog = tool_catalog or ToolRegistrySchema(tools=[])
    fake_svc = _FakeToolExecutionService()

    loop = AgentLoop(
        context_builder=builder,
        model_gateway=gateway,
        tool_catalog=catalog,
        tool_execution_service=fake_svc,
    )
    # Replace the real FastAgent with our test double
    loop._fast_agent = _FakeFastAgent(decision)
    return loop


# ── Missing exposed definition tests ─────────────────────────────────────


class TestMissingExposedDefinition:
    """Multi-call with a tool call that has no matching exposed definition."""

    def test_missing_exposed_definition_rejected(self) -> None:
        """Tool call name not in exposed_tools -> ModelError, zero execution."""
        calls = (
            _make_tool_call("read_tool", {"value": "x"}),
            _make_tool_call("unknown_tool", {"value": "y"}),
        )
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=list(calls),
        )
        exposed = (_make_tool_public("read_tool"),)
        decision = AgentDecision(
            prompt_version="test",
            request=_make_single_message_request(),
            exposed_tools=exposed,
            response=first_response,
        )
        loop = _make_agent_loop_with_fake_fast_agent(decision)

        fake_svc = loop._tool_execution_service  # type: ignore[attr-defined]
        gateway = loop._model_gateway  # type: ignore[attr-defined]

        with pytest.raises(ModelError, match="no matching exposed"):
            loop.run("test", execution_context=_make_write_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 0


# ── Duplicate exposed definition tests ───────────────────────────────────


class TestDuplicateExposedDefinitions:
    """Duplicate definitions for the same tool name fail closed."""

    def _assert_duplicate_rejected(
        self,
        exposed: tuple[ToolPublicDefinition, ...],
    ) -> None:
        calls = (
            _make_tool_call("read_tool", {"value": "x"}),
            _make_tool_call("read_tool", {"value": "y"}),
        )
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=list(calls),
        )
        decision = AgentDecision(
            prompt_version="test",
            request=_make_single_message_request(),
            exposed_tools=exposed,
            response=first_response,
        )
        loop = _make_agent_loop_with_fake_fast_agent(decision)

        fake_svc = loop._tool_execution_service  # type: ignore[attr-defined]
        gateway = loop._model_gateway  # type: ignore[attr-defined]

        with pytest.raises(ModelError, match="Ambiguous snapshot"):
            loop.run("test", execution_context=_make_write_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 0

    def test_duplicate_read_read_rejected(self) -> None:
        """Duplicate READ+READ definitions -> ModelError."""
        self._assert_duplicate_rejected(
            exposed=(
                _make_tool_public("read_tool", permission=Permission.READ),
                _make_tool_public("read_tool", permission=Permission.READ),
            ),
        )

    def test_duplicate_read_write_rejected(self) -> None:
        """Duplicate READ+WRITE definitions -> ModelError."""
        self._assert_duplicate_rejected(
            exposed=(
                _make_tool_public("read_tool", permission=Permission.READ),
                _make_tool_public("read_tool", permission=Permission.WRITE),
            ),
        )

    def test_duplicate_write_read_rejected(self) -> None:
        """Duplicate WRITE+READ definitions -> ModelError.

        Proves definition order cannot change the safety result.
        """
        self._assert_duplicate_rejected(
            exposed=(
                _make_tool_public("read_tool", permission=Permission.WRITE),
                _make_tool_public("read_tool", permission=Permission.READ),
            ),
        )


# ── Malformed Permission tests ───────────────────────────────────────────


class TestMalformedPermission:
    """Malformed Permission values fail closed with ModelError."""

    def _assert_malformed_permission_rejected(
        self,
        permission: object,
    ) -> None:
        """Helper: construct a ToolPublicDefinition with model_construct to
        bypass Pydantic validation, then verify the multi-call policy
        rejects it with ModelError (not AttributeError/TypeError).
        """
        exposed = (
            ToolPublicDefinition.model_construct(
                name="read_tool",
                description="Tool read_tool",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                permission=permission,
                side_effects=[],
                allowed_session_modes=[
                    SessionMode.NO_ACTIVE_SESSION,
                    SessionMode.ACTIVE_SESSION,
                ],
            ),
        )
        calls = (
            _make_tool_call("read_tool", {"value": "x"}),
            _make_tool_call("read_tool", {"value": "y"}),
        )
        first_response = _make_tool_response(
            content="Calling...",
            tool_calls=list(calls),
        )
        decision = AgentDecision(
            prompt_version="test",
            request=_make_single_message_request(),
            exposed_tools=exposed,
            response=first_response,
        )
        loop = _make_agent_loop_with_fake_fast_agent(decision)

        fake_svc = loop._tool_execution_service  # type: ignore[attr-defined]
        gateway = loop._model_gateway  # type: ignore[attr-defined]

        with pytest.raises(ModelError, match="malformed permission"):
            loop.run("test", execution_context=_make_write_context())

        assert fake_svc.execute_call_count == 0
        assert gateway.chat_with_tools_call_count == 0

    def test_plain_string_read_rejected(self) -> None:
        """permission='read' -> ModelError, not AttributeError."""
        self._assert_malformed_permission_rejected("read")

    def test_plain_string_write_rejected(self) -> None:
        """permission='write' -> ModelError, not AttributeError."""
        self._assert_malformed_permission_rejected("write")

    def test_none_permission_rejected(self) -> None:
        """permission=None -> ModelError, not AttributeError."""
        self._assert_malformed_permission_rejected(None)

    def test_foreign_strenum_read_rejected(self) -> None:
        """Foreign StrEnum with value 'read' -> ModelError."""
        self._assert_malformed_permission_rejected(ForeignPermission.READ)

    def test_foreign_strenum_write_rejected(self) -> None:
        """Foreign StrEnum with value 'write' -> ModelError."""
        self._assert_malformed_permission_rejected(ForeignPermission.WRITE)
