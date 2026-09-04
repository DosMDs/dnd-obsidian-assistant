"""Strict ToolCall membership boundary tests (S9-C04).

Verifies that the recursive strict JSON value comparator in
``_tool_call_in`` rejects type-substituted arguments that Python
``==`` would accept, while accepting structurally identical values
including dicts with different key insertion order.

Every rejection proves:
- ``ValidationError`` is raised
- ToolExecutor is NOT called
- handler is NOT called
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionResult,
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import AgentDecision
from dnd_assistant.errors import ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)

if TYPE_CHECKING:
    pass


# ── Dummy schemas ───────────────────────────────────────────────────────────────


class StringInput(BaseModel):
    value: str


class ResultOutput(BaseModel):
    result: str


# ── Handlers ────────────────────────────────────────────────────────────────────


def read_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"read: {input_model.value}")


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="read_tool",
        description="A read-only test tool",
        input_schema=StringInput,
        output_schema=ResultOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def registry(tool_def: ToolDefinition) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(tool_def, read_handler)
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


@pytest.fixture
def service(executor: ToolExecutor) -> AgentToolExecutionService:
    return AgentToolExecutionService(tool_executor=executor)


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────────


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
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permission=permission,
        side_effects=[],
        allowed_session_modes=[SessionMode.NO_ACTIVE_SESSION],
    )


def _make_decision(
    *,
    tool_calls: list[ToolCall] | None = None,
    exposed_tools: list[ToolPublicDefinition] | None = None,
) -> AgentDecision:
    return AgentDecision(
        prompt_version="test-v1",
        request=ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.SYSTEM, content="System prompt"),
                ChatMessage(role=MessageRole.USER, content='{"user_input": "test"}'),
            ),
        ),
        exposed_tools=tuple(exposed_tools or []),
        response=ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=tuple(tool_calls or []),
            ),
        ),
    )


class _CountingExecutor:
    """ToolExecutor stand-in that counts calls and never succeeds on its own."""

    def __init__(self) -> None:
        self.call_count = 0

    def execute(  # type: ignore[override]
        self,
        tool_name: str,
        *,
        input_data: dict[str, Any],
        context: ExecutionContext,
    ) -> BaseModel:
        self.call_count += 1
        return ResultOutput(result="ok")


# ── Strict type-substitution rejection tests ────────────────────────────────────


class TestStrictTypeSubstitutionRejection:
    """Prove type-substituted arguments are rejected before ToolExecutor."""

    @pytest.fixture
    def counting_service(self) -> AgentToolExecutionService:
        return AgentToolExecutionService(tool_executor=_CountingExecutor())

    def _assert_rejected(
        self,
        service: AgentToolExecutionService,
        decision: AgentDecision,
        supplied_call: ToolCall,
        context: ExecutionContext,
    ) -> None:
        with pytest.raises(ValidationError, match="not a member"):
            service.execute(decision, supplied_call, execution_context=context)

    # ── 0 vs False ──────────────────────────────────────────────────────────

    def test_decision_arg_0_rejects_supplied_false(self, read_context: ExecutionContext) -> None:
        """decision arguments={'x': 0}, supplied arguments={'x': False}."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"x": 0})
        supplied_call = _make_tool_call("read_tool", {"x": False})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0

    def test_decision_arg_false_rejects_supplied_0(self, read_context: ExecutionContext) -> None:
        """decision arguments={'x': False}, supplied arguments={'x': 0}."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"x": False})
        supplied_call = _make_tool_call("read_tool", {"x": 0})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0

    # ── 1 vs True ───────────────────────────────────────────────────────────

    def test_decision_arg_1_rejects_supplied_true(self, read_context: ExecutionContext) -> None:
        """decision arguments={'x': 1}, supplied arguments={'x': True}."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"x": 1})
        supplied_call = _make_tool_call("read_tool", {"x": True})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0

    def test_decision_arg_true_rejects_supplied_1(self, read_context: ExecutionContext) -> None:
        """decision arguments={'x': True}, supplied arguments={'x': 1}."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"x": True})
        supplied_call = _make_tool_call("read_tool", {"x": 1})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0

    # ── int vs float ────────────────────────────────────────────────────────

    def test_decision_arg_1_rejects_supplied_1_dot_0(self, read_context: ExecutionContext) -> None:
        """decision arguments={'x': 1}, supplied arguments={'x': 1.0}."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"x": 1})
        supplied_call = _make_tool_call("read_tool", {"x": 1.0})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0

    # ── Nested type substitution ────────────────────────────────────────────

    def test_nested_dict_0_vs_false_rejected(self, read_context: ExecutionContext) -> None:
        """nested {'x': {'y': 0}} vs {'x': {'y': False}}."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"x": {"y": 0}})
        supplied_call = _make_tool_call("read_tool", {"x": {"y": False}})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0

    def test_nested_list_type_substitution_rejected(self, read_context: ExecutionContext) -> None:
        """nested [1, False] vs [True, 0] — different types and values."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"items": [1, False]})
        supplied_call = _make_tool_call("read_tool", {"items": [True, 0]})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        self._assert_rejected(svc, decision, supplied_call, read_context)
        assert counting.call_count == 0


# ── Dict order equivalence tests ────────────────────────────────────────────────


class TestDictOrderEquivalence:
    """Prove dicts with different key insertion order are treated as equal."""

    def test_different_key_order_accepted(self) -> None:
        """{'a': 1, 'b': 2} and {'b': 2, 'a': 1} are the same."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"a": 1, "b": 2})
        supplied_call = _make_tool_call("read_tool", {"b": 2, "a": 1})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        # Membership passes; execution reaches CountingExecutor
        result = svc.execute(decision, supplied_call, execution_context=ctx)
        assert isinstance(result, AgentToolExecutionResult)
        assert counting.call_count == 1

    def test_different_key_order_with_nested_dicts_accepted(self) -> None:
        """Nested dicts with different key order are the same."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call("read_tool", {"outer": {"a": 1, "b": 2}})
        supplied_call = _make_tool_call("read_tool", {"outer": {"b": 2, "a": 1}})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = svc.execute(decision, supplied_call, execution_context=ctx)
        assert isinstance(result, AgentToolExecutionResult)
        assert counting.call_count == 1

    def test_different_key_order_with_mixed_types_accepted(self) -> None:
        """Dict with mixed types and different key order is the same."""
        counting = _CountingExecutor()
        svc = AgentToolExecutionService(tool_executor=counting)
        decision_call = _make_tool_call(
            "read_tool",
            {"name": "test", "count": 42, "flag": True},
        )
        supplied_call = _make_tool_call(
            "read_tool",
            {"flag": True, "name": "test", "count": 42},
        )
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = svc.execute(decision, supplied_call, execution_context=ctx)
        assert isinstance(result, AgentToolExecutionResult)
        assert counting.call_count == 1


# ── Exact valid call still executes exactly once ────────────────────────────────


class TestExactValidCallExecutes:
    """Prove that a structurally identical call still executes exactly once."""

    def test_exact_call_executes_once(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert isinstance(result, AgentToolExecutionResult)
        assert result.tool_call is tool_call
        assert result.output.result == "read: hello"

    def test_equivalent_call_executes_once(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        """Different object with same field values is accepted."""
        original = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        same_value = _make_tool_call("read_tool", {"value": "hello"}, call_id="c1")
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[original], exposed_tools=exposed)
        result = service.execute(decision, same_value, execution_context=read_context)
        assert isinstance(result, AgentToolExecutionResult)
        assert result.output.result == "read: hello"

    def test_dict_order_different_still_executes(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        """Same keys in different order still passes membership."""
        decision_call = _make_tool_call("read_tool", {"value": "hello", "extra": "world"})
        supplied_call = _make_tool_call("read_tool", {"extra": "world", "value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[decision_call], exposed_tools=exposed)
        result = service.execute(decision, supplied_call, execution_context=read_context)
        assert isinstance(result, AgentToolExecutionResult)
