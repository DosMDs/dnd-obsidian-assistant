"""Tests for OllamaModelProvider.chat_with_tools() (S8-04).

All tests use mocked HTTP (respx) — no real Ollama, no network, no Vault.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from dnd_assistant.errors import ModelError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.types import Permission, SessionMode

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_tool(
    name: str = "get_entity",
    description: str = "Get an entity by ID",
    input_schema: dict[str, Any] | None = None,
) -> ToolPublicDefinition:
    return ToolPublicDefinition(
        name=name,
        description=description,
        input_schema=input_schema
        or {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        permission=Permission.READ,
        side_effects=[],
        allowed_session_modes=[SessionMode.ACTIVE_SESSION, SessionMode.NO_ACTIVE_SESSION],
    )


def _make_profile(**kw: Any) -> ModelProfile:
    return ModelProfile(
        provider=kw.get("provider", "ollama"),
        model=kw.get("model", "qwen-2.5-7b"),
        base_url=kw.get("base_url", "http://localhost:11434"),
        temperature=kw.get("temperature"),
        keep_alive=kw.get("keep_alive"),
        role=kw.get("role", ModelProfileRole.AGENT),
    )


def _tool_resp(
    content: str | None = None, tool_calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"message": msg}


def _fcall(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": arguments}}


def _simple_req() -> ChatRequest:
    return ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))


def _capture_payload(request: ChatRequest, tools: list[ToolPublicDefinition]) -> dict[str, Any]:
    profile = _make_profile()
    captured: dict[str, Any] = {}

    def capture(req: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(req.content)
        return httpx.Response(200, json=_tool_resp(content="Hello."))

    with respx.mock:
        respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)
        p = OllamaModelProvider(profile)
        p.chat_with_tools(request, tools)
        p.close()
    return captured["payload"]


def _capture_msgs(
    request: ChatRequest, tools: list[ToolPublicDefinition] | None = None
) -> list[dict[str, Any]]:
    return _capture_payload(request, tools or [_make_tool()])["messages"]


def _do_chat(
    body: dict[str, Any], tools: list[ToolPublicDefinition] | None = None
) -> ToolAwareResponse | Exception:
    profile = _make_profile()
    effective_tools: list[ToolPublicDefinition]
    if tools is None:
        effective_tools = [_make_tool()]
    else:
        effective_tools = tools
    with respx.mock:
        respx.post("http://localhost:11434/api/chat").respond(json=body)
        p = OllamaModelProvider(profile)
        try:
            return p.chat_with_tools(_simple_req(), effective_tools)
        except Exception as exc:
            return exc
        finally:
            p.close()


def _http_fail(setup: Any) -> Exception:
    profile = _make_profile()
    with respx.mock:
        setup()
        p = OllamaModelProvider(profile)
        try:
            p.chat_with_tools(_simple_req(), [_make_tool()])
            raise AssertionError("Expected ModelError")
        except Exception as exc:
            return exc
        finally:
            p.close()


# ═══════════════════════════════════════════════════════════════════════════
# Tool schema mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestToolSchemaMapping:
    def test_exact_shape(self) -> None:
        tool = _make_tool()
        p = _capture_payload(_simple_req(), [tool])
        assert p["tools"][0] == {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @pytest.mark.parametrize(
        "field", ["output_schema", "permission", "side_effects", "allowed_session_modes"]
    )
    def test_metadata_not_sent(self, field: str) -> None:
        assert field not in _capture_payload(_simple_req(), [_make_tool()])["tools"][0]["function"]

    def test_input_schema_not_mutated(self) -> None:
        tool = _make_tool()
        orig = dict(tool.input_schema)
        _capture_payload(_simple_req(), [tool])
        assert tool.input_schema == orig

    def test_order_preserved(self) -> None:
        p = _capture_payload(_simple_req(), [_make_tool(name="a"), _make_tool(name="b")])
        assert [t["function"]["name"] for t in p["tools"]] == ["a", "b"]

    def test_multiple_tools(self) -> None:
        tools = [_make_tool(name=f"t{i}") for i in range(3)]
        p = _capture_payload(_simple_req(), tools)
        assert len(p["tools"]) == 3
        for i, t in enumerate(tools):
            assert p["tools"][i]["function"]["name"] == t.name

    def test_empty_tool_list(self) -> None:
        assert _capture_payload(_simple_req(), [])["tools"] == []


# ═══════════════════════════════════════════════════════════════════════════
# Request profile mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestRequestProfileMapping:
    def test_model(self) -> None:
        assert _capture_payload(_simple_req(), [_make_tool()])["model"] == "qwen-2.5-7b"

    def test_stream_false(self) -> None:
        assert _capture_payload(_simple_req(), [_make_tool()])["stream"] is False

    def test_temperature_in_options(self) -> None:
        profile = _make_profile(temperature=0.7)
        captured: dict[str, Any] = {}

        def capture(req: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(req.content)
            return httpx.Response(200, json=_tool_resp(content="Hello."))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)
            p = OllamaModelProvider(profile)
            p.chat_with_tools(_simple_req(), [_make_tool()])
            p.close()
        assert captured["payload"]["options"]["temperature"] == 0.7

    def test_temperature_omitted(self) -> None:
        assert "options" not in _capture_payload(_simple_req(), [_make_tool()])

    def test_keep_alive(self) -> None:
        profile = _make_profile(keep_alive="30m")
        captured: dict[str, Any] = {}

        def capture(req: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(req.content)
            return httpx.Response(200, json=_tool_resp(content="Hello."))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)
            p = OllamaModelProvider(profile)
            p.chat_with_tools(_simple_req(), [_make_tool()])
            p.close()
        assert captured["payload"]["keep_alive"] == "30m"

    def test_keep_alive_omitted(self) -> None:
        assert "keep_alive" not in _capture_payload(_simple_req(), [_make_tool()])

    def test_no_format_or_think(self) -> None:
        p = _capture_payload(_simple_req(), [_make_tool()])
        assert "format" not in p
        assert "think" not in p


# ═══════════════════════════════════════════════════════════════════════════
# Plain history mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestPlainHistoryMapping:
    def test_single_user(self) -> None:
        assert _capture_msgs(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
        ) == [{"role": "user", "content": "Hi"}]

    def test_system_and_user(self) -> None:
        assert _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.SYSTEM, content="Be helpful"),
                    ChatMessage(role=MessageRole.USER, content="Hello"),
                )
            )
        ) == [{"role": "system", "content": "Be helpful"}, {"role": "user", "content": "Hello"}]

    def test_prior_assistant(self) -> None:
        assert _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Q?"),
                    ChatMessage(role=MessageRole.ASSISTANT, content="A."),
                    ChatMessage(role=MessageRole.USER, content="Thanks"),
                )
            )
        ) == [
            {"role": "user", "content": "Q?"},
            {"role": "assistant", "content": "A."},
            {"role": "user", "content": "Thanks"},
        ]

    def test_no_prompt_mutation(self) -> None:
        msgs = _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.SYSTEM, content="You are helpful."),
                    ChatMessage(role=MessageRole.USER, content="Hi"),
                )
            )
        )
        assert msgs == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]


# ═══════════════════════════════════════════════════════════════════════════
# Tool-history mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestToolHistoryMapping:
    def test_assistant_tool_call_only(self) -> None:
        msgs = _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Get npc_1"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="get_entity", arguments={"entity_id": "npc_1"}, call_id=None
                            ),
                        ),
                    ),
                )
            )
        )
        assert msgs[1]["role"] == "assistant"
        assert "content" not in msgs[1] or msgs[1].get("content") is None
        tc = msgs[1]["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["index"] == 0
        assert tc["function"]["name"] == "get_entity"
        assert tc["function"]["arguments"] == {"entity_id": "npc_1"}

    def test_text_and_tool_calls(self) -> None:
        msgs = _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Check"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content="I'll check.",
                        tool_calls=(
                            ToolCall(
                                name="get_entity", arguments={"entity_id": "npc_1"}, call_id=None
                            ),
                        ),
                    ),
                )
            )
        )
        assert msgs[1]["content"] == "I'll check."
        assert len(msgs[1]["tool_calls"]) == 1

    def test_multiple_tool_calls(self) -> None:
        msgs = _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Get both"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="get_entity", arguments={"entity_id": "npc_1"}, call_id=None
                            ),
                            ToolCall(name="search", arguments={"query": "lich"}, call_id=None),
                        ),
                    ),
                )
            )
        )
        calls = msgs[1]["tool_calls"]
        assert len(calls) == 2
        assert [c["function"]["index"] for c in calls] == [0, 1]
        assert [c["function"]["name"] for c in calls] == ["get_entity", "search"]

    def test_tool_result(self) -> None:
        msgs = _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Get weather"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="get_entity", arguments={"entity_id": "npc_1"}, call_id=None
                            ),
                        ),
                    ),
                    ChatMessage(
                        role=MessageRole.TOOL, content='{"temp": 22}', tool_name="get_entity"
                    ),
                )
            )
        )
        assert msgs[2] == {"role": "tool", "tool_name": "get_entity", "content": '{"temp": 22}'}

    def test_multi_turn(self) -> None:
        msgs = _capture_msgs(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Get npc_1"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="get_entity", arguments={"entity_id": "npc_1"}, call_id=None
                            ),
                        ),
                    ),
                    ChatMessage(
                        role=MessageRole.TOOL, content='{"name": "Aria"}', tool_name="get_entity"
                    ),
                    ChatMessage(role=MessageRole.USER, content="Level?"),
                )
            )
        )
        assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "user"]
        assert msgs[3]["content"] == "Level?"


# ═══════════════════════════════════════════════════════════════════════════
# Call-ID incompatibility
# ═══════════════════════════════════════════════════════════════════════════


class TestCallIdIncompatibility:
    def _assert_rejected(self, request: ChatRequest) -> None:
        profile = _make_profile()
        with respx.mock:
            route = respx.post("http://localhost:11434/api/chat").respond(
                json=_tool_resp(content="Hello.")
            )
            p = OllamaModelProvider(profile)
            with pytest.raises(ModelError, match="call_id"):
                p.chat_with_tools(request, [_make_tool()])
            p.close()
            assert not route.called

    def test_assistant_call_id_rejected(self) -> None:
        self._assert_rejected(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Hi"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="get_entity",
                                arguments={"entity_id": "npc_1"},
                                call_id="call_123",
                            ),
                        ),
                    ),
                )
            )
        )

    def test_tool_call_id_rejected(self) -> None:
        self._assert_rejected(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Hi"),
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=None,
                        tool_calls=(
                            ToolCall(
                                name="get_entity", arguments={"entity_id": "npc_1"}, call_id=None
                            ),
                        ),
                    ),
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content="result",
                        tool_name="get_entity",
                        tool_call_id="call_123",
                    ),
                )
            )
        )


# ═══════════════════════════════════════════════════════════════════════════
# Response tests
# ═══════════════════════════════════════════════════════════════════════════


class TestResponses:
    def test_text_only(self) -> None:
        r = _do_chat(_tool_resp(content="No tool needed."))
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content == "No tool needed."
        assert r.message.tool_calls == ()

    def test_tool_call_only(self) -> None:
        r = _do_chat(
            _tool_resp(content="", tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})])
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content is None
        assert len(r.message.tool_calls) == 1
        tc = r.message.tool_calls[0]
        assert tc.name == "get_entity"
        assert tc.arguments == {"entity_id": "npc_1"}
        assert tc.call_id is None

    def test_text_and_tool_call(self) -> None:
        r = _do_chat(
            _tool_resp(
                content="I'll check.", tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})]
            )
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content == "I'll check."
        assert len(r.message.tool_calls) == 1
        assert r.message.tool_calls[0].name == "get_entity"

    def test_parallel_calls(self) -> None:
        tools = [_make_tool(name="get_entity"), _make_tool(name="search")]
        r = _do_chat(
            _tool_resp(
                content=None,
                tool_calls=[
                    _fcall("get_entity", {"entity_id": "npc_1"}),
                    _fcall("search", {"query": "lich"}),
                ],
            ),
            tools=tools,
        )
        assert isinstance(r, ToolAwareResponse)
        assert len(r.message.tool_calls) == 2
        assert r.message.tool_calls[0].name == "get_entity"
        assert r.message.tool_calls[1].name == "search"
        assert r.message.tool_calls[0].call_id is None
        assert r.message.tool_calls[1].call_id is None

    def test_duplicate_same_name(self) -> None:
        r = _do_chat(
            _tool_resp(
                content=None,
                tool_calls=[
                    _fcall("get_entity", {"entity_id": "npc_1"}),
                    _fcall("get_entity", {"entity_id": "npc_2"}),
                ],
            )
        )
        assert isinstance(r, ToolAwareResponse)
        assert len(r.message.tool_calls) == 2
        assert r.message.tool_calls[0].arguments == {"entity_id": "npc_1"}
        assert r.message.tool_calls[1].arguments == {"entity_id": "npc_2"}


# ═══════════════════════════════════════════════════════════════════════════
# Allowlist tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAllowlist:
    def test_allowed_tool_accepted(self) -> None:
        r = _do_chat(
            _tool_resp(content="", tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})]),
            tools=[_make_tool(name="get_entity")],
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.tool_calls[0].name == "get_entity"

    def test_unknown_tool_rejected(self) -> None:
        r = _do_chat(_tool_resp(content="", tool_calls=[_fcall("unknown_tool", {})]))
        assert isinstance(r, ModelError)

    def test_empty_allowlist_with_returned_tool_rejected(self) -> None:
        r = _do_chat(
            _tool_resp(content="", tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})]),
            tools=[],
        )
        assert isinstance(r, ModelError)

    def test_empty_allowlist_text_only_accepted(self) -> None:
        r = _do_chat(_tool_resp(content="Hello."), tools=[])
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content == "Hello."


# ═══════════════════════════════════════════════════════════════════════════
# Malformed tool-call tests (parametrized)
# ═══════════════════════════════════════════════════════════════════════════


_MALFORMED_CASES = [
    ("tool_calls_not_a_list", _tool_resp(content="", tool_calls="not a list")),  # type: ignore[arg-type]
    ("entry_not_an_object", _tool_resp(content="", tool_calls=["not an object"])),
    ("missing_function", _tool_resp(content="", tool_calls=[{"no_function": True}])),
    ("function_not_object", _tool_resp(content="", tool_calls=[{"function": "not an object"}])),
    ("missing_name", _tool_resp(content="", tool_calls=[{"function": {"no_name": True}}])),
    ("empty_name", _tool_resp(content="", tool_calls=[{"function": {"name": ""}}])),
    ("non_string_name", _tool_resp(content="", tool_calls=[{"function": {"name": 123}}])),
    (
        "missing_arguments",
        _tool_resp(content="", tool_calls=[{"function": {"name": "get_entity"}}]),
    ),
    (
        "arguments_not_object",
        _tool_resp(
            content="", tool_calls=[{"function": {"name": "get_entity", "arguments": "string"}}]
        ),
    ),
    (
        "arguments_is_json_string",
        _tool_resp(
            content="",
            tool_calls=[{"function": {"name": "get_entity", "arguments": '{"id":"npc_1"}'}}],
        ),
    ),
    (
        "type_not_function",
        _tool_resp(
            content="",
            tool_calls=[
                {"type": "not_function", "function": {"name": "get_entity", "arguments": {}}}
            ],
        ),
    ),
]


class TestMalformedToolCalls:
    @pytest.mark.parametrize("label,body", _MALFORMED_CASES)
    def test_malformed_rejected(self, label: str, body: dict[str, Any]) -> None:
        r = _do_chat(body)
        assert isinstance(r, ModelError), f"Expected ModelError for {label}"

    def test_validation_cause_preserved(self) -> None:
        """NaN in arguments via raw bytes: ToolCall validation preserves cause."""
        profile = _make_profile()
        raw = b'{"message":{"role":"assistant","content":"","tool_calls":[{"function":{"name":"get_entity","arguments":{"val":NaN}}}]}}'
        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(content=raw)
            p = OllamaModelProvider(profile)
            with pytest.raises(ModelError) as exc:
                p.chat_with_tools(_simple_req(), [_make_tool()])
            p.close()
            assert exc.value.__cause__ is not None


# ═══════════════════════════════════════════════════════════════════════════
# Falsy malformed tool_calls regression (S8-C05)
# ═══════════════════════════════════════════════════════════════════════════


class TestFalsyMalformedToolCalls:
    """Present-but-invalid falsy tool_calls values must raise ModelError.

    The S8-C04 implementation conflated ``tool_calls`` field absence with
    truthiness, allowing falsy malformed values to bypass ``_parse_tool_calls``
    and be accepted as text-only responses when usable text was present.
    """

    @pytest.mark.parametrize(
        "label,malformed",
        [
            ("null", None),
            ("empty_string", ""),
            ("empty_object", {}),
            ("zero", 0),
            ("false", False),
        ],
    )
    def test_falsy_malformed_rejected(self, label: str, malformed: object) -> None:
        body: dict[str, object] = {
            "message": {
                "role": "assistant",
                "content": "Usable text",
                "tool_calls": malformed,
            }
        }
        r = _do_chat(body)
        assert isinstance(r, ModelError), (
            f"Expected ModelError for tool_calls={label!r} with usable text, got {type(r).__name__}"
        )
        assert "tool_calls" in str(r).lower()

    def test_empty_list_with_text_is_valid(self) -> None:
        """tool_calls=[] with usable text must remain a valid text-only response."""
        body: dict[str, object] = {
            "message": {
                "role": "assistant",
                "content": "Usable text",
                "tool_calls": [],
            }
        }
        r = _do_chat(body)
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content == "Usable text"
        assert r.message.tool_calls == ()


# ═══════════════════════════════════════════════════════════════════════════
# Non-finite argument regression
# ═══════════════════════════════════════════════════════════════════════════


class TestNonFiniteArguments:
    def test_nan_rejected(self) -> None:
        profile = _make_profile()
        raw = b'{"message":{"role":"assistant","content":"","tool_calls":[{"function":{"name":"get_entity","arguments":{"val":NaN}}}]}}'
        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(content=raw)
            p = OllamaModelProvider(profile)
            with pytest.raises(ModelError) as exc:
                p.chat_with_tools(_simple_req(), [_make_tool()])
            p.close()
            assert exc.value.__cause__ is not None


# ═══════════════════════════════════════════════════════════════════════════
# Response content edge tests (parametrized)
# ═══════════════════════════════════════════════════════════════════════════


class TestResponseContentEdges:
    def test_empty_content_with_tool_calls(self) -> None:
        r = _do_chat(
            _tool_resp(content="", tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})])
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content is None

    def test_missing_content_with_tool_calls(self) -> None:
        r = _do_chat(
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [_fcall("get_entity", {"entity_id": "npc_1"})],
                }
            }
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content is None

    def test_none_content_with_tool_calls(self) -> None:
        r = _do_chat(
            _tool_resp(content=None, tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})])
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content is None

    def test_non_string_content_rejected(self) -> None:
        r = _do_chat(
            {
                "message": {
                    "role": "assistant",
                    "content": 123,
                    "tool_calls": [_fcall("get_entity", {"entity_id": "npc_1"})],
                }
            }
        )
        assert isinstance(r, ModelError)

    def test_empty_no_tool_calls_rejected(self) -> None:
        r = _do_chat(_tool_resp(content=""))
        assert isinstance(r, ModelError)

    def test_missing_no_tool_calls_rejected(self) -> None:
        r = _do_chat({"message": {"role": "assistant"}})
        assert isinstance(r, ModelError)

    def test_none_no_tool_calls_rejected(self) -> None:
        r = _do_chat(_tool_resp(content=None))
        assert isinstance(r, ModelError)


# ═══════════════════════════════════════════════════════════════════════════
# Provider metadata tests
# ═══════════════════════════════════════════════════════════════════════════


class TestProviderMetadata:
    def test_extra_metadata_ignored(self) -> None:
        r = _do_chat(
            {
                "model": "qwen-2.5-7b",
                "created_at": "2026-09-03T00:00:00Z",
                "message": {"role": "assistant", "content": "Hello."},
                "total_duration": 123456789,
                "done": True,
            }
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content == "Hello."

    def test_thinking_ignored(self) -> None:
        r = _do_chat(
            {
                "message": {
                    "role": "assistant",
                    "content": "Final answer.",
                    "thinking": "I should think...",
                }
            }
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.content == "Final answer."

    def test_function_index_not_exposed(self) -> None:
        r = _do_chat(
            _tool_resp(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "index": 0,
                            "name": "get_entity",
                            "arguments": {"entity_id": "npc_1"},
                        }
                    }
                ],
            )
        )
        assert isinstance(r, ToolAwareResponse)
        assert r.message.tool_calls[0].call_id is None
        assert r.message.tool_calls[0].name == "get_entity"


# ═══════════════════════════════════════════════════════════════════════════
# HTTP failure tests (parametrized)
# ═══════════════════════════════════════════════════════════════════════════


class TestHttpFailures:
    def test_connection_error(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert "connection refused" in str(exc).lower()

    def test_timeout(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)

    @pytest.mark.parametrize("status", [400, 404, 500])
    def test_http_error(self, status: int) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(status)

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert str(status) in str(exc)

    def test_ollama_error_body(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=404, json={"error": "model not found"}
            )

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert "model not found" in str(exc)
        assert "404" in str(exc)

    def test_non_json_error_body(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=502, content=b"<html>Bad Gateway</html>"
            )

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert "502" in str(exc)

    def test_invalid_bytes_error_body(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=502, content=b"\xff\xfe\x00\x01invalid bytes"
            )

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert "502" in str(exc)
        assert not isinstance(exc, UnicodeDecodeError)

    def test_non_json_successful_response(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(content=b"not json at all")

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert "non-JSON" in str(exc)

    def test_invalid_bytes_successful_response(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                content=b"\xff\xfe\x00\x01invalid bytes"
            )

        exc = _http_fail(setup)
        assert isinstance(exc, ModelError)
        assert exc.__cause__ is not None
        assert not isinstance(exc, UnicodeDecodeError)


# ═══════════════════════════════════════════════════════════════════════════
# No execution proof
# ═══════════════════════════════════════════════════════════════════════════


class TestNoExecution:
    def test_exactly_one_http_request(self) -> None:
        profile = _make_profile()
        with respx.mock:
            route = respx.post("http://localhost:11434/api/chat").respond(
                json=_tool_resp(
                    content="", tool_calls=[_fcall("get_entity", {"entity_id": "npc_1"})]
                )
            )
            p = OllamaModelProvider(profile)
            r = p.chat_with_tools(_simple_req(), [_make_tool()])
            p.close()
        assert isinstance(r, ToolAwareResponse)
        assert route.called
        assert route.call_count == 1
