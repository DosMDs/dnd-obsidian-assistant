"""Contract tests: provider-neutral ModelGateway DTOs and Protocol.

This module verifies:
1. DTO validation invariants (MessageRole, ToolCall, ChatMessage,
   ChatRequest, ChatResponse, ToolAwareResponse, ModelHealth).
2. Response invariants (role == ASSISTANT).
3. ModelHealth invariants and convenience property.
4. ModelGateway protocol shape (exactly 5 sync operations).
5. Lightweight import behaviour.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.models.gateway import ModelGateway
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ModelHealth,
    ToolAwareResponse,
    ToolCall,
)

# ── MessageRole ────────────────────────────────────────────────────────────


class TestMessageRole:
    def test_system_value(self) -> None:
        assert MessageRole.SYSTEM.value == "system"

    def test_user_value(self) -> None:
        assert MessageRole.USER.value == "user"

    def test_assistant_value(self) -> None:
        assert MessageRole.ASSISTANT.value == "assistant"

    def test_tool_value(self) -> None:
        assert MessageRole.TOOL.value == "tool"

    def test_str_enum_comparison(self) -> None:
        assert str(MessageRole.SYSTEM) == "system"

    def test_from_string(self) -> None:
        assert MessageRole("system") is MessageRole.SYSTEM
        assert MessageRole("user") is MessageRole.USER
        assert MessageRole("assistant") is MessageRole.ASSISTANT
        assert MessageRole("tool") is MessageRole.TOOL


# ── ToolCall ───────────────────────────────────────────────────────────────


class TestToolCall:
    def test_valid_minimal(self) -> None:
        tc = ToolCall(name="get_weather", arguments={"city": "Waterdeep"})
        assert tc.name == "get_weather"
        assert tc.arguments == {"city": "Waterdeep"}
        assert tc.call_id is None

    def test_valid_with_call_id(self) -> None:
        tc = ToolCall(
            name="roll_dice",
            arguments={"count": 1, "sides": 20},
            call_id="call_abc123",
        )
        assert tc.call_id == "call_abc123"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            ToolCall(name="", arguments={})

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ToolCall(name="foo", arguments={}, extra_field="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        tc = ToolCall(name="foo", arguments={})
        with pytest.raises(ValidationError):
            tc.name = "bar"  # type: ignore[misc]

    def test_json_arguments_accepted(self) -> None:
        tc = ToolCall(
            name="search",
            arguments={"query": "lich", "limit": 5, "tags": ["undead"]},
        )
        assert tc.arguments["query"] == "lich"
        assert tc.arguments["limit"] == 5
        assert tc.arguments["tags"] == ["undead"]

    # ── S8-C00 regression: strict JSON (no NaN / ±Infinity) ───────────────

    def test_nan_at_top_level_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Non-finite"):
            ToolCall(name="x", arguments={"val": float("nan")})

    def test_infinity_at_top_level_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Non-finite"):
            ToolCall(name="x", arguments={"val": float("inf")})

    def test_neg_infinity_at_top_level_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Non-finite"):
            ToolCall(name="x", arguments={"val": float("-inf")})

    def test_non_finite_nested_in_dict_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Non-finite"):
            ToolCall(name="x", arguments={"outer": {"inner": float("nan")}})

    def test_non_finite_nested_in_list_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Non-finite"):
            ToolCall(name="x", arguments={"items": [1, 2, float("inf")]})

    def test_deeply_nested_non_finite_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Non-finite"):
            ToolCall(name="x", arguments={"a": {"b": [{"c": float("-inf")}]}})

    def test_valid_nested_json_accepted(self) -> None:
        tc = ToolCall(
            name="x",
            arguments={
                "null_val": None,
                "bool_val": True,
                "int_val": 42,
                "float_val": 3.14,
                "str_val": "hello",
                "list_val": [1, 2, 3],
                "dict_val": {"a": 1},
            },
        )
        assert tc.arguments["null_val"] is None
        assert tc.arguments["bool_val"] is True
        assert tc.arguments["int_val"] == 42
        assert tc.arguments["float_val"] == 3.14
        assert tc.arguments["str_val"] == "hello"
        assert tc.arguments["list_val"] == [1, 2, 3]
        assert tc.arguments["dict_val"] == {"a": 1}


# ── ChatMessage ────────────────────────────────────────────────────────────


class TestChatMessageSystem:
    def test_valid_system(self) -> None:
        msg = ChatMessage(role=MessageRole.SYSTEM, content="You are a helpful assistant.")
        assert msg.content == "You are a helpful assistant."
        assert msg.tool_calls == ()
        assert msg.tool_name is None
        assert msg.tool_call_id is None

    def test_system_empty_content_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty content"):
            ChatMessage(role=MessageRole.SYSTEM, content="")

    def test_system_none_content_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty content"):
            ChatMessage(role=MessageRole.SYSTEM, content=None)

    def test_system_tool_calls_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_calls"):
            ChatMessage(
                role=MessageRole.SYSTEM,
                content="Hello",
                tool_calls=(ToolCall(name="x", arguments={}),),
            )

    def test_system_tool_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_name"):
            ChatMessage(role=MessageRole.SYSTEM, content="Hello", tool_name="x")

    def test_system_tool_call_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_call_id"):
            ChatMessage(role=MessageRole.SYSTEM, content="Hello", tool_call_id="x")


class TestChatMessageUser:
    def test_valid_user(self) -> None:
        msg = ChatMessage(role=MessageRole.USER, content="What is the weather?")
        assert msg.content == "What is the weather?"

    def test_user_empty_content_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty content"):
            ChatMessage(role=MessageRole.USER, content="")

    def test_user_none_content_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty content"):
            ChatMessage(role=MessageRole.USER, content=None)

    def test_user_tool_calls_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_calls"):
            ChatMessage(
                role=MessageRole.USER,
                content="Hi",
                tool_calls=(ToolCall(name="x", arguments={}),),
            )

    def test_user_tool_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_name"):
            ChatMessage(role=MessageRole.USER, content="Hi", tool_name="x")


class TestChatMessageAssistant:
    def test_valid_text_only(self) -> None:
        msg = ChatMessage(role=MessageRole.ASSISTANT, content="The weather is sunny.")
        assert msg.content == "The weather is sunny."
        assert msg.tool_calls == ()

    def test_valid_tool_calls_only(self) -> None:
        msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(ToolCall(name="get_weather", arguments={"city": "Waterdeep"}),),
        )
        assert msg.content is None
        assert len(msg.tool_calls) == 1

    def test_valid_text_and_tool_calls(self) -> None:
        msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content="Let me check.",
            tool_calls=(ToolCall(name="search", arguments={"q": "lich"}),),
        )
        assert msg.content == "Let me check."
        assert len(msg.tool_calls) == 1

    def test_neither_content_nor_tool_calls_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one of content or tool_calls"):
            ChatMessage(role=MessageRole.ASSISTANT, content=None)

    def test_empty_content_no_tool_calls_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one of content or tool_calls"):
            ChatMessage(role=MessageRole.ASSISTANT, content="")

    def test_tool_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_name"):
            ChatMessage(role=MessageRole.ASSISTANT, content="Hi", tool_name="x")

    def test_tool_call_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_call_id"):
            ChatMessage(role=MessageRole.ASSISTANT, content="Hi", tool_call_id="x")


class TestChatMessageTool:
    def test_valid_tool(self) -> None:
        msg = ChatMessage(
            role=MessageRole.TOOL,
            content='{"temperature": 22}',
            tool_name="get_weather",
        )
        assert msg.content == '{"temperature": 22}'
        assert msg.tool_name == "get_weather"
        assert msg.tool_call_id is None

    def test_valid_tool_with_call_id(self) -> None:
        msg = ChatMessage(
            role=MessageRole.TOOL,
            content="Result",
            tool_name="roll_dice",
            tool_call_id="call_abc",
        )
        assert msg.tool_call_id == "call_abc"

    def test_empty_content_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty content"):
            ChatMessage(role=MessageRole.TOOL, content="", tool_name="x")

    def test_none_content_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty content"):
            ChatMessage(role=MessageRole.TOOL, content=None, tool_name="x")

    def test_empty_tool_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty tool_name"):
            ChatMessage(role=MessageRole.TOOL, content="ok", tool_name="")

    def test_none_tool_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty tool_name"):
            ChatMessage(role=MessageRole.TOOL, content="ok", tool_name=None)

    def test_tool_calls_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not have tool_calls"):
            ChatMessage(
                role=MessageRole.TOOL,
                content="ok",
                tool_name="x",
                tool_calls=(ToolCall(name="y", arguments={}),),
            )


class TestChatMessageGeneral:
    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ChatMessage(role=MessageRole.USER, content="Hi", unknown="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        msg = ChatMessage(role=MessageRole.USER, content="Hi")
        with pytest.raises(ValidationError):
            msg.content = "Changed"  # type: ignore[misc]


# ── ChatRequest ────────────────────────────────────────────────────────────


class TestChatRequest:
    def test_valid_single_message(self) -> None:
        req = ChatRequest(
            messages=(ChatMessage(role=MessageRole.USER, content="Hi"),),
        )
        assert len(req.messages) == 1

    def test_valid_multiple_messages(self) -> None:
        req = ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.SYSTEM, content="You are helpful."),
                ChatMessage(role=MessageRole.USER, content="What is the weather?"),
            ),
        )
        assert len(req.messages) == 2

    def test_empty_messages_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one message"):
            ChatRequest(messages=())

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ChatRequest(  # type: ignore[call-arg]
                messages=(ChatMessage(role=MessageRole.USER, content="Hi"),),
                extra="x",
            )

    def test_frozen(self) -> None:
        req = ChatRequest(
            messages=(ChatMessage(role=MessageRole.USER, content="Hi"),),
        )
        with pytest.raises(ValidationError):
            req.messages = ()  # type: ignore[misc]


# ── ChatResponse ───────────────────────────────────────────────────────────


class TestChatResponse:
    def test_valid_assistant_response(self) -> None:
        resp = ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content="Hello!"),
        )
        assert resp.message.content == "Hello!"

    def test_non_assistant_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be ASSISTANT"):
            ChatResponse(
                message=ChatMessage(role=MessageRole.USER, content="Hi"),
            )

    def test_tool_role_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be ASSISTANT"):
            ChatResponse(
                message=ChatMessage(
                    role=MessageRole.TOOL,
                    content="result",
                    tool_name="x",
                ),
            )

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ChatResponse(  # type: ignore[call-arg]
                message=ChatMessage(role=MessageRole.ASSISTANT, content="Hi"),
                unknown="x",
            )

    # ── S8-C00 regression: plain chat must not contain tool calls ──────────

    def test_tool_calls_only_rejected(self) -> None:
        """ASSISTANT + tool_calls only must be rejected by ChatResponse."""
        with pytest.raises(ValidationError, match="must not contain tool calls"):
            ChatResponse(
                message=ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=None,
                    tool_calls=(ToolCall(name="x", arguments={}),),
                ),
            )

    def test_text_and_tool_calls_rejected(self) -> None:
        """ASSISTANT + content + tool_calls must be rejected by ChatResponse."""
        with pytest.raises(ValidationError, match="must not contain tool calls"):
            ChatResponse(
                message=ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content="Let me check.",
                    tool_calls=(ToolCall(name="x", arguments={}),),
                ),
            )


# ── ToolAwareResponse ──────────────────────────────────────────────────────


class TestToolAwareResponse:
    def test_valid_text_only(self) -> None:
        resp = ToolAwareResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content="Sure."),
        )
        assert resp.message.content == "Sure."

    def test_valid_tool_calls(self) -> None:
        resp = ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=(ToolCall(name="search", arguments={"q": "lich"}),),
            ),
        )
        assert len(resp.message.tool_calls) == 1

    def test_valid_text_and_tool_calls(self) -> None:
        resp = ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content="Let me search.",
                tool_calls=(ToolCall(name="search", arguments={"q": "lich"}),),
            ),
        )
        assert resp.message.content == "Let me search."

    def test_non_assistant_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be ASSISTANT"):
            ToolAwareResponse(
                message=ChatMessage(role=MessageRole.USER, content="Hi"),
            )

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ToolAwareResponse(  # type: ignore[call-arg]
                message=ChatMessage(role=MessageRole.ASSISTANT, content="Hi"),
                unknown="x",
            )


# ── S8-C00: multi-tool turn representation (Stage-9-capable) ────────────


class TestMultiToolTurnRepresentation:
    """Verify the DTO layer can represent a future tool-calling trajectory.

    This does NOT execute anything — it only validates that the message
    DTOs can model assistant tool-calling turns and corresponding TOOL
    result messages, which is required for Stage-9 conversation history.
    """

    def test_multi_tool_assistant_turn(self) -> None:
        assistant_msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(
                ToolCall(name="get_weather", arguments={"city": "Waterdeep"}, call_id="call_01"),
                ToolCall(name="search", arguments={"q": "lich"}, call_id="call_02"),
            ),
        )
        assert assistant_msg.role is MessageRole.ASSISTANT
        assert assistant_msg.content is None
        assert len(assistant_msg.tool_calls) == 2
        assert assistant_msg.tool_calls[0].call_id == "call_01"
        assert assistant_msg.tool_calls[1].call_id == "call_02"

    def test_corresponding_tool_messages(self) -> None:
        tool_1 = ChatMessage(
            role=MessageRole.TOOL,
            content='{"temperature": 22}',
            tool_name="get_weather",
            tool_call_id="call_01",
        )
        tool_2 = ChatMessage(
            role=MessageRole.TOOL,
            content="No results found.",
            tool_name="search",
            tool_call_id="call_02",
        )
        assert tool_1.tool_call_id == "call_01"
        assert tool_2.tool_call_id == "call_02"
        assert tool_1.tool_name == "get_weather"
        assert tool_2.tool_name == "search"

    def test_assistant_with_text_and_multiple_tool_calls(self) -> None:
        assistant_msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content="Let me check both sources.",
            tool_calls=(
                ToolCall(name="get_weather", arguments={"city": "Neverwinter"}, call_id="c1"),
                ToolCall(name="search", arguments={"q": "artifact"}, call_id="c2"),
            ),
        )
        assert assistant_msg.content == "Let me check both sources."
        assert len(assistant_msg.tool_calls) == 2


# ── ModelHealth ────────────────────────────────────────────────────────────


class TestModelHealth:
    def test_reachable_and_available(self) -> None:
        h = ModelHealth(reachable=True, model_available=True)
        assert h.reachable is True
        assert h.model_available is True
        assert h.healthy is True

    def test_reachable_not_available(self) -> None:
        h = ModelHealth(reachable=True, model_available=False)
        assert h.healthy is False

    def test_not_reachable_not_available(self) -> None:
        h = ModelHealth(reachable=False, model_available=False)
        assert h.healthy is False

    def test_model_available_without_reachable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="model_available=True requires reachable=True"):
            ModelHealth(reachable=False, model_available=True)

    def test_detail_accepted(self) -> None:
        h = ModelHealth(
            reachable=True,
            model_available=True,
            detail="Ollama running, model loaded",
        )
        assert h.detail == "Ollama running, model loaded"

    def test_detail_none(self) -> None:
        h = ModelHealth(reachable=True, model_available=True)
        assert h.detail is None

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ModelHealth(reachable=True, model_available=True, unknown="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        h = ModelHealth(reachable=True, model_available=True)
        with pytest.raises(ValidationError):
            h.reachable = False  # type: ignore[misc]


# ── Gateway protocol shape ─────────────────────────────────────────────────


class TestModelGatewayProtocol:
    """Verify the ModelGateway protocol has exactly 5 sync operations."""

    CANONICAL_OPERATIONS = frozenset(
        {
            "chat",
            "chat_with_tools",
            "generate_structured",
            "embed",
            "health",
        }
    )

    PROTOCOL_INTERNALS = frozenset(
        {
            "__init__",
            "__subclasshook__",
            "__init_subclass__",
            "__new__",
            "__class_getitem__",
            "__instancecheck__",
            "__subclasscheck__",
            "__abstractmethods__",
            "__call__",
            "__delattr__",
            "__dir__",
            "__format__",
            "__getattribute__",
            "__hash__",
            "__reduce__",
            "__reduce_ex__",
            "__repr__",
            "__setattr__",
            "__sizeof__",
            "__str__",
        }
    )

    def test_exactly_five_operations(self) -> None:
        own: set[str] = set()
        for name in dir(ModelGateway):
            if name.startswith("_") and name not in self.PROTOCOL_INTERNALS:
                continue
            if name in self.PROTOCOL_INTERNALS:
                continue
            own.add(name)
        assert own == set(self.CANONICAL_OPERATIONS), (
            f"Expected exactly {sorted(self.CANONICAL_OPERATIONS)}, got {sorted(own)}"
        )

    def test_no_replacement_api(self) -> None:
        """No generate/complete/invoke replacement API exists."""
        for bad_name in ("generate", "complete", "invoke"):
            assert not hasattr(ModelGateway, bad_name), f"ModelGateway must not have {bad_name}()"

    def test_all_operations_are_sync(self) -> None:
        """None of the five operations are async def."""
        import inspect

        for name in self.CANONICAL_OPERATIONS:
            member = getattr(ModelGateway, name, None)
            assert member is not None, f"{name} not found on ModelGateway"
            assert not inspect.iscoroutinefunction(member), (
                f"{name} must not be async (Stage-8 MVP decision: sync)"
            )
