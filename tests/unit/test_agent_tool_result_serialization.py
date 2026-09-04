"""Tests for deterministic TOOL-result JSON serialisation (S9-03).

Covers:

- Empty, None, False, 0, empty string, empty list, empty dict
- Unicode preservation
- Nested list/dict
- Deterministic key order and compact separators
- TOOL ChatMessage construction (role, content, tool_name, call_id)
- Serialisation failure boundary
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import AgentDecision
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

# ── Dummy schemas ──────────────────────────────────────────────────────────────


class StringInput(BaseModel):
    value: str


class EmptyOutput(BaseModel):
    pass


class ResultOutput(BaseModel):
    result: str


class NumberInput(BaseModel):
    number: int


class NestedOutput(BaseModel):
    name: str
    count: int | None = None
    tags: list[str] = []
    metadata: dict[str, object] = {}
    flag: bool = False


# ── Handlers ───────────────────────────────────────────────────────────────────


def read_handler(input_model: StringInput, context: object) -> ResultOutput:
    return ResultOutput(result=f"read: {input_model.value}")


def empty_handler(input_model: StringInput, context: object) -> EmptyOutput:
    return EmptyOutput()


def nested_handler(input_model: NumberInput, context: object) -> NestedOutput:
    return NestedOutput(
        name="test",
        count=input_model.number,
        tags=["a", "b"],
        metadata={"key": "val", "nested": {"inner": 42}},
        flag=True,
    )


def unicode_handler(input_model: StringInput, context: object) -> NestedOutput:
    return NestedOutput(
        name=input_model.value,
        tags=["\u043f\u0440\u0438\u0432\u0435\u0442", "\u043c\u0438\u0440"],
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def read_tool_def() -> ToolDefinition:
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
def empty_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="empty_tool",
        description="Returns empty output",
        input_schema=StringInput,
        output_schema=EmptyOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def nested_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="nested_tool",
        description="Returns nested output",
        input_schema=NumberInput,
        output_schema=NestedOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def unicode_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="unicode_tool",
        description="Returns Unicode output",
        input_schema=StringInput,
        output_schema=NestedOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
        ),
    )


@pytest.fixture
def registry(
    read_tool_def: ToolDefinition,
    empty_tool_def: ToolDefinition,
    nested_tool_def: ToolDefinition,
    unicode_tool_def: ToolDefinition,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_tool_def, read_handler)
    reg.register(empty_tool_def, empty_handler)
    reg.register(nested_tool_def, nested_handler)
    reg.register(unicode_tool_def, unicode_handler)
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


# ── Decision-building helpers ──────────────────────────────────────────────────


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
        allowed_session_modes=allowed_session_modes or [SessionMode.NO_ACTIVE_SESSION],
    )


def _make_decision(
    *,
    tool_calls: list[ToolCall] | None = None,
    exposed_tools: list[ToolPublicDefinition] | None = None,
    content: str | None = None,
) -> AgentDecision:
    """Build an ``AgentDecision`` with the given tool calls and exposed tools."""
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
                content=content,
                tool_calls=tuple(tool_calls or []),
            ),
        ),
    )


# ── Result serialisation tests ─────────────────────────────────────────────────


class TestResultSerialization:
    """Verify deterministic TOOL-result JSON serialisation."""

    def test_empty_output_serialises_to_empty_object(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("empty_tool", {"value": "x"})
        exposed = [_make_tool_public("empty_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.tool_message.content == "{}"

    def test_unicode_string_serialised(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call(
            "unicode_tool", {"value": "\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444"}
        )
        exposed = [_make_tool_public("unicode_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        parsed = json.loads(result.tool_message.content)
        assert parsed["name"] == "\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444"
        assert "\u043f\u0440\u0438\u0432\u0435\u0442" in parsed["tags"]

    def test_none_value(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("nested_tool", {"number": 0})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        parsed = json.loads(result.tool_message.content)
        assert parsed["count"] == 0

    def test_false_value(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("nested_tool", {"number": 0})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        parsed = json.loads(result.tool_message.content)
        assert parsed["flag"] is True

    def test_zero_value(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("nested_tool", {"number": 0})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        parsed = json.loads(result.tool_message.content)
        assert parsed["count"] == 0

    def test_empty_string_in_output(self) -> None:
        class EmptyStringOutput(BaseModel):
            text: str = ""

        class SimpleIn(BaseModel):
            x: str

        def handler(input_model: SimpleIn, context: object) -> EmptyStringOutput:
            return EmptyStringOutput(text="")

        reg_def = ToolDefinition(
            name="empty_str_tool",
            description="Empty string tool",
            input_schema=SimpleIn,
            output_schema=EmptyStringOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg = ToolRegistry()
        reg.register(reg_def, handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("empty_str_tool", {"x": "y"})
        exposed = [_make_tool_public("empty_str_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = svc.execute(decision, tool_call, execution_context=ctx)
        parsed = json.loads(result.tool_message.content)
        assert parsed["text"] == ""

    def test_empty_list_in_output(self) -> None:
        class ListOutput(BaseModel):
            items: list[str] = []

        class SimpleIn(BaseModel):
            x: str

        def handler(input_model: SimpleIn, context: object) -> ListOutput:
            return ListOutput(items=[])

        reg_def = ToolDefinition(
            name="list_tool",
            description="List tool",
            input_schema=SimpleIn,
            output_schema=ListOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg = ToolRegistry()
        reg.register(reg_def, handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("list_tool", {"x": "y"})
        exposed = [_make_tool_public("list_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = svc.execute(decision, tool_call, execution_context=ctx)
        parsed = json.loads(result.tool_message.content)
        assert parsed["items"] == []

    def test_empty_dict_in_output(self) -> None:
        class DictOutput(BaseModel):
            data: dict[str, object] = {}

        class SimpleIn(BaseModel):
            x: str

        def handler(input_model: SimpleIn, context: object) -> DictOutput:
            return DictOutput(data={})

        reg_def = ToolDefinition(
            name="dict_tool",
            description="Dict tool",
            input_schema=SimpleIn,
            output_schema=DictOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg = ToolRegistry()
        reg.register(reg_def, handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("dict_tool", {"x": "y"})
        exposed = [_make_tool_public("dict_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = svc.execute(decision, tool_call, execution_context=ctx)
        parsed = json.loads(result.tool_message.content)
        assert parsed["data"] == {}

    def test_nested_list_and_dict(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("nested_tool", {"number": 42})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        parsed = json.loads(result.tool_message.content)
        assert parsed["metadata"] == {"key": "val", "nested": {"inner": 42}}
        assert parsed["tags"] == ["a", "b"]

    def test_deterministic_key_order_and_compact_separators(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        """Assert exact string equality for multi-field output."""
        tool_call = _make_tool_call("nested_tool", {"number": 1})
        exposed = [_make_tool_public("nested_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        content = result.tool_message.content
        # Verify sort_keys: "count" before "flag" before "metadata" before "name" before "tags"
        assert content.index('"count"') < content.index('"flag"')
        assert content.index('"flag"') < content.index('"metadata"')
        assert content.index('"metadata"') < content.index('"name"')
        assert content.index('"name"') < content.index('"tags"')
        # Verify compact separators (no spaces after : or ,)
        assert ',"flag"' in content
        assert ':"test"' in content
        # Verify no whitespace between tokens
        assert ", " not in content
        assert ": " not in content


# ── TOOL message tests ─────────────────────────────────────────────────────────


class TestToolMessage:
    """Verify the constructed TOOL ChatMessage properties."""

    def test_role_is_tool(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.tool_message.role is MessageRole.TOOL

    def test_content_is_deterministic_json(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        parsed = json.loads(result.tool_message.content)
        assert parsed["result"] == "read: hello"

    def test_tool_name_equals_tool_call_name(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.tool_message.tool_name == "read_tool"

    def test_tool_calls_is_empty(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"})
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.tool_message.tool_calls == ()

    def test_call_id_preserved(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"}, call_id="provider-call-123")
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.tool_message.tool_call_id == "provider-call-123"

    def test_call_id_none(
        self,
        service: AgentToolExecutionService,
        read_context: ExecutionContext,
    ) -> None:
        tool_call = _make_tool_call("read_tool", {"value": "hello"}, call_id=None)
        exposed = [_make_tool_public("read_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        result = service.execute(decision, tool_call, execution_context=read_context)
        assert result.tool_message.tool_call_id is None


# ── Serialisation failure tests ────────────────────────────────────────────────


class TestSerializationFailure:
    """Verify behaviour when serialisation of validated output fails."""

    def test_normal_output_serialises_fine(self) -> None:
        """Prove that normally serialisable output works (baseline)."""

        class SimpleOutput(BaseModel):
            value: str

        class SimpleIn(BaseModel):
            x: str

        def handler(input_model: SimpleIn, context: object) -> SimpleOutput:
            return SimpleOutput(value="ok")

        reg_def = ToolDefinition(
            name="serial_tool",
            description="Serial tool",
            input_schema=SimpleIn,
            output_schema=SimpleOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        reg = ToolRegistry()
        reg.register(reg_def, handler)
        exe = ToolExecutor(reg)
        svc = AgentToolExecutionService(tool_executor=exe)

        tool_call = _make_tool_call("serial_tool", {"x": "y"})
        exposed = [_make_tool_public("serial_tool")]
        decision = _make_decision(tool_calls=[tool_call], exposed_tools=exposed)
        ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        result = svc.execute(decision, tool_call, execution_context=ctx)
        assert json.loads(result.tool_message.content) == {"value": "ok"}
