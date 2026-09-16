"""Direct contract coverage for neutral shared agent contracts (PAIM-15/PAIM-RETIRE-01).

These tests target ``dnd_assistant.application.agent_contracts`` directly and
carry forward the provider-neutral, framework-independent behaviour that was
previously exercised only through the retired reference runtime:

- deterministic TOOL-result adaptation and JSON serialisation
- provider-neutral TOOL ``ChatMessage`` construction
- deterministic agent request projection from ``AgentContext``
- terminal ``AgentTextOutcome`` validation and parsing

No reference runtime, no provider, and no ``ToolExecutor`` are required.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import PydanticSerializationError

from dnd_assistant.application.agent_context import AgentContext
from dnd_assistant.application.agent_contracts import (
    AgentDecision,
    AgentOutcomeKind,
    AgentTextOutcome,
    build_agent_request,
    build_agent_tool_execution_result,
    parse_agent_outcome,
)
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    FiniteJsonValue,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.prompts.agent_v3 import PROMPT_VERSION, SYSTEM_PROMPT

# ── Output schemas ─────────────────────────────────────────────────────────────


class EmptyOutput(BaseModel):
    pass


class ResultOutput(BaseModel):
    result: str


class NestedOutput(BaseModel):
    name: str
    count: int | None = None
    tags: list[str] = []
    metadata: dict[str, object] = {}
    flag: bool = False


class NoneOutput(BaseModel):
    value: object | None = None


class BoolOutput(BaseModel):
    flag: bool = False


class IntOutput(BaseModel):
    count: int = 0


class EmptyStringOutput(BaseModel):
    text: str = ""


class ListOutput(BaseModel):
    items: list[str] = []


class DictOutput(BaseModel):
    data: dict[str, object] = {}


class UnserializableOutput(BaseModel):
    value: object


def _tool_call(
    name: str = "read_tool",
    arguments: dict[str, FiniteJsonValue] | None = None,
    call_id: str | None = None,
) -> ToolCall:
    resolved: dict[str, FiniteJsonValue] = arguments if arguments is not None else {}
    return ToolCall(name=name, arguments=resolved, call_id=call_id)


# ── Deterministic tool-result serialisation ────────────────────────────────────


class TestResultSerialization:
    """Verify deterministic TOOL-result JSON serialisation via the shared factory."""

    def test_empty_output_serialises_to_empty_object(self) -> None:
        result = build_agent_tool_execution_result(_tool_call("empty_tool"), EmptyOutput())
        assert result.tool_message.content == "{}"

    def test_unicode_string_serialised(self) -> None:
        output = NestedOutput(
            name="\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444",
            tags=["\u043f\u0440\u0438\u0432\u0435\u0442", "\u043c\u0438\u0440"],
        )
        result = build_agent_tool_execution_result(_tool_call("unicode_tool"), output)
        assert result.tool_message.content is not None
        parsed = json.loads(result.tool_message.content)
        assert parsed["name"] == "\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444"
        assert "\u043f\u0440\u0438\u0432\u0435\u0442" in parsed["tags"]

    def test_none_value_serialises_to_json_null(self) -> None:
        result = build_agent_tool_execution_result(_tool_call("none_tool"), NoneOutput())
        assert result.tool_message.content is not None
        assert json.loads(result.tool_message.content)["value"] is None
        assert "null" in result.tool_message.content

    def test_false_value_serialises_to_json_false(self) -> None:
        result = build_agent_tool_execution_result(_tool_call("false_tool"), BoolOutput())
        assert result.tool_message.content is not None
        assert json.loads(result.tool_message.content)["flag"] is False
        assert '"flag":false' in result.tool_message.content

    def test_zero_value_serialises_to_json_0(self) -> None:
        result = build_agent_tool_execution_result(_tool_call("zero_tool"), IntOutput())
        assert result.tool_message.content is not None
        parsed = json.loads(result.tool_message.content)
        assert parsed["count"] == 0
        assert parsed["count"] is not False
        assert '"count":0' in result.tool_message.content

    def test_empty_string_in_output(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("empty_str_tool"), EmptyStringOutput()
        )
        assert result.tool_message.content is not None
        assert json.loads(result.tool_message.content)["text"] == ""

    def test_empty_list_in_output(self) -> None:
        result = build_agent_tool_execution_result(_tool_call("list_tool"), ListOutput())
        assert result.tool_message.content is not None
        assert json.loads(result.tool_message.content)["items"] == []

    def test_empty_dict_in_output(self) -> None:
        result = build_agent_tool_execution_result(_tool_call("dict_tool"), DictOutput())
        assert result.tool_message.content is not None
        assert json.loads(result.tool_message.content)["data"] == {}

    def test_nested_list_and_dict(self) -> None:
        output = NestedOutput(
            name="test",
            count=42,
            tags=["a", "b"],
            metadata={"key": "val", "nested": {"inner": 42}},
            flag=True,
        )
        result = build_agent_tool_execution_result(_tool_call("nested_tool"), output)
        assert result.tool_message.content is not None
        parsed = json.loads(result.tool_message.content)
        assert parsed["metadata"] == {"key": "val", "nested": {"inner": 42}}
        assert parsed["tags"] == ["a", "b"]

    def test_deterministic_full_string_equality(self) -> None:
        output = NestedOutput(
            name="test",
            count=1,
            tags=["a", "b"],
            metadata={"key": "val", "nested": {"inner": 42}},
            flag=True,
        )
        result = build_agent_tool_execution_result(_tool_call("nested_tool"), output)
        expected = (
            '{"count":1,"flag":true,"metadata":{"key":"val","nested":{"inner":42}},'
            '"name":"test","tags":["a","b"]}'
        )
        assert result.tool_message.content == expected

    def test_deterministic_key_order_and_compact_separators(self) -> None:
        output = NestedOutput(
            name="test",
            count=1,
            tags=["a", "b"],
            metadata={"key": "val", "nested": {"inner": 42}},
            flag=True,
        )
        result = build_agent_tool_execution_result(_tool_call("nested_tool"), output)
        content = result.tool_message.content
        assert content is not None
        assert content.index('"count"') < content.index('"flag"')
        assert content.index('"flag"') < content.index('"metadata"')
        assert content.index('"metadata"') < content.index('"name"')
        assert content.index('"name"') < content.index('"tags"')
        assert ',"flag"' in content
        assert ':"test"' in content
        assert ", " not in content
        assert ": " not in content


# ── TOOL ChatMessage construction ──────────────────────────────────────────────


class TestToolMessage:
    """Verify the constructed TOOL ``ChatMessage`` properties."""

    def test_role_is_tool(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("read_tool"), ResultOutput(result="read: hello")
        )
        assert result.tool_message.role is MessageRole.TOOL

    def test_content_is_deterministic_json(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("read_tool"), ResultOutput(result="read: hello")
        )
        assert result.tool_message.content is not None
        assert json.loads(result.tool_message.content)["result"] == "read: hello"

    def test_tool_name_equals_tool_call_name(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("read_tool"), ResultOutput(result="x")
        )
        assert result.tool_message.tool_name == "read_tool"

    def test_tool_calls_is_empty(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("read_tool"), ResultOutput(result="x")
        )
        assert result.tool_message.tool_calls == ()

    def test_call_id_preserved(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("read_tool", call_id="provider-call-123"),
            ResultOutput(result="x"),
        )
        assert result.tool_message.tool_call_id == "provider-call-123"

    def test_call_id_none(self) -> None:
        result = build_agent_tool_execution_result(
            _tool_call("read_tool", call_id=None), ResultOutput(result="x")
        )
        assert result.tool_message.tool_call_id is None

    def test_exact_tool_call_is_preserved(self) -> None:
        call = _tool_call("read_tool", {"value": "x"}, call_id="c1")
        result = build_agent_tool_execution_result(call, ResultOutput(result="x"))
        assert result.tool_call is call


# ── Serialisation failure boundary ─────────────────────────────────────────────


class TestSerializationFailure:
    """Verify behaviour when serialisation of validated output fails."""

    def test_real_serialization_failure_raises_validation_error(self) -> None:
        output = UnserializableOutput(value=object())
        with pytest.raises(ValidationError) as exc_info:
            build_agent_tool_execution_result(_tool_call("unserializable_tool"), output)
        cause = exc_info.value.__cause__
        assert cause is not None
        assert isinstance(cause, PydanticSerializationError)


# ── Deterministic request projection ───────────────────────────────────────────


def _empty_context(user_input: str = "hello") -> AgentContext:
    return AgentContext(
        user_input=user_input,
        current_world_tick=None,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
    )


class TestBuildAgentRequest:
    """Verify the deterministic provider-neutral request projection."""

    def test_uses_system_and_user_messages(self) -> None:
        request = build_agent_request(_empty_context())
        assert isinstance(request, ChatRequest)
        assert len(request.messages) == 2
        assert request.messages[0].role is MessageRole.SYSTEM
        assert request.messages[0].content == SYSTEM_PROMPT
        assert request.messages[1].role is MessageRole.USER

    def test_user_payload_is_deterministic_compact_json(self) -> None:
        request = build_agent_request(_empty_context("find the silver key"))
        payload = request.messages[1].content
        assert payload is not None
        parsed = json.loads(payload)
        assert parsed["user_input"] == "find the silver key"
        assert parsed["active_session"] is None
        assert parsed["relevant_entities"] == []
        assert parsed["recent_events"] == []
        # Compact separators: no ", " or ": " token spacing.
        assert ", " not in payload
        assert ": " not in payload

    def test_unicode_is_preserved(self) -> None:
        request = build_agent_request(
            _empty_context("\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444")
        )
        payload = request.messages[1].content
        assert payload is not None
        assert "\u0413\u044d\u043d\u0434\u0430\u043b\u044c\u0444" in payload


# ── Terminal outcome contract ──────────────────────────────────────────────────


class TestParseAgentOutcome:
    """Verify terminal ``AgentTextOutcome`` validation and parsing."""

    def test_parses_respond(self) -> None:
        response = _text_response('{"kind": "respond", "message": "done"}')
        outcome = parse_agent_outcome(response)
        assert outcome.kind is AgentOutcomeKind.RESPOND
        assert outcome.message == "done"

    def test_parses_clarify(self) -> None:
        response = _text_response('{"kind": "clarify", "message": "which one?"}')
        outcome = parse_agent_outcome(response)
        assert outcome.kind is AgentOutcomeKind.CLARIFY

    def test_rejects_response_with_tool_calls(self) -> None:
        response = ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content='{"kind": "respond", "message": "x"}',
                tool_calls=(_tool_call("read_tool"),),
            )
        )
        with pytest.raises(ModelError):
            parse_agent_outcome(response)

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(ModelError):
            parse_agent_outcome(_text_response("not json"))

    def test_rejects_empty_message(self) -> None:
        with pytest.raises(ModelError):
            parse_agent_outcome(_text_response('{"kind": "respond", "message": ""}'))

    def test_rejects_whitespace_only_message(self) -> None:
        with pytest.raises(ModelError):
            parse_agent_outcome(_text_response('{"kind": "respond", "message": "   "}'))


class TestAgentTextOutcome:
    """Verify the validated terminal outcome model invariants."""

    def test_rejects_empty_message(self) -> None:
        with pytest.raises(PydanticValidationError, match="empty"):
            AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="")

    def test_rejects_whitespace_only_message(self) -> None:
        with pytest.raises(PydanticValidationError, match="whitespace"):
            AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="   ")

    def test_forbids_extra_fields(self) -> None:
        with pytest.raises(PydanticValidationError):
            AgentTextOutcome.model_validate({"kind": "respond", "message": "x", "extra": 1})

    def test_is_frozen(self) -> None:
        outcome = AgentTextOutcome(kind=AgentOutcomeKind.RESPOND, message="x")
        with pytest.raises(PydanticValidationError):
            outcome.message = "y"  # type: ignore[misc]


class TestAgentDecisionFrozen:
    """Verify the decision snapshot DTO is immutable."""

    def test_decision_carries_prompt_version(self) -> None:
        decision = AgentDecision(
            prompt_version=PROMPT_VERSION,
            request=build_agent_request(_empty_context()),
            exposed_tools=(),
            response=_text_response('{"kind": "respond", "message": "x"}'),
        )
        assert decision.prompt_version == PROMPT_VERSION
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.prompt_version = "other"  # type: ignore[misc]


def _text_response(content: str | None) -> ToolAwareResponse:
    return ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=(),
        )
    )


# ── Prompt/request version transition (S12-04) ─────────────────────────────────


class TestPromptVersionTransition:
    """The current Fast-Agent request identity is agent-v3; v1/v2 preserved."""

    def test_current_prompt_version_is_agent_v3(self) -> None:
        assert PROMPT_VERSION == "agent-v3"

    def test_v3_system_prompt_is_text_identical_to_v2(self) -> None:
        from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION as v2_version
        from dnd_assistant.prompts.agent_v2 import SYSTEM_PROMPT as v2_prompt

        assert v2_version == "agent-v2"
        assert SYSTEM_PROMPT == v2_prompt

    def test_historical_agent_v1_resource_preserved(self) -> None:
        from dnd_assistant.prompts.agent_v1 import PROMPT_VERSION as v1_version
        from dnd_assistant.prompts.agent_v1 import SYSTEM_PROMPT as v1_prompt

        assert v1_version == "agent-v1"
        assert v1_prompt
