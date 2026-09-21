"""Sanitized DeepSeek request-capture helpers for the RM-02 compatibility spike.

This module provides an ``httpx2`` mock transport that records only an
allowlisted *projection* of each outbound Chat Completions request.  It never
persists, stores or exposes:

- provider reasoning (chain-of-thought) text;
- prompt / conversation text;
- raw request or response bodies;
- HTTP headers (notably ``Authorization``);
- API keys or other credentials.

The projection carries only booleans, field names, enum categories and counts,
which is sufficient to prove the wire shape of the DeepSeek thinking /
reasoning-effort / tool-continuation protocol without leaking hidden reasoning.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2

__all__ = [
    "DeepSeekTransportCapture",
    "SanitizedRequest",
    "deepseek_chat_completion",
    "project_request",
]

# Safe, allowlisted category values for the outbound `tool_choice` field.
_TOOL_CHOICE_SCALARS = frozenset({"auto", "required", "none"})

# Message roles considered when checking for replayed reasoning content.
_ASSISTANT_ROLE = "assistant"
_TOOL_ROLE = "tool"


@dataclass(frozen=True)
class SanitizedRequest:
    """Allowlisted projection of one outbound Chat Completions request."""

    index: int
    model: str | None
    tools_present: bool
    tools_count: int
    tool_choice_present: bool
    tool_choice_category: str
    thinking_present: bool
    thinking_type: str | None
    reasoning_effort: str | None
    assistant_reasoning_content_present: bool
    tool_result_ids: tuple[str, ...]
    message_roles: tuple[str, ...]

    def safe_repr(self) -> str:
        """Return a string containing only allowlisted, non-sensitive fields."""
        return (
            "SanitizedRequest("
            f"index={self.index}, "
            f"model={self.model!r}, "
            f"tools_present={self.tools_present}, "
            f"tools_count={self.tools_count}, "
            f"tool_choice_present={self.tool_choice_present}, "
            f"tool_choice_category={self.tool_choice_category!r}, "
            f"thinking_present={self.thinking_present}, "
            f"thinking_type={self.thinking_type!r}, "
            f"reasoning_effort={self.reasoning_effort!r}, "
            f"assistant_reasoning_content_present="
            f"{self.assistant_reasoning_content_present}, "
            f"tool_result_ids={self.tool_result_ids!r}, "
            f"message_roles={self.message_roles!r}"
            ")"
        )


def _as_messages(body: Mapping[str, Any]) -> Sequence[Any]:
    messages = body.get("messages")
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        return messages
    return ()


def _project_tool_choice(body: Mapping[str, Any]) -> tuple[bool, str]:
    if "tool_choice" not in body or body.get("tool_choice") is None:
        return False, "absent"
    choice = body.get("tool_choice")
    if isinstance(choice, str):
        return True, choice if choice in _TOOL_CHOICE_SCALARS else "other"
    if isinstance(choice, Mapping):
        return True, "named"
    return True, "other"


def project_request(index: int, raw_body: bytes) -> SanitizedRequest:
    """Build a :class:`SanitizedRequest` from a raw JSON request body.

    Any parse failure yields an empty projection rather than raising, so the
    transport stays available while never exposing the raw bytes.
    """
    try:
        decoded = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        decoded = None
    body: Mapping[str, Any] = decoded if isinstance(decoded, Mapping) else {}

    model = body.get("model")
    tools_raw = body.get("tools")
    tools: list[Any] = (
        list(tools_raw)
        if isinstance(tools_raw, Sequence) and not isinstance(tools_raw, (str, bytes))
        else []
    )
    tools_present = bool(tools)
    tools_count = len(tools)

    tool_choice_present, tool_choice_category = _project_tool_choice(body)

    # `ModelSettings.extra_body` is merged into the request body at top level by
    # the OpenAI SDK, so the DeepSeek `thinking` toggle appears as a top-level key.
    thinking = body.get("thinking")
    thinking_present = False
    thinking_type: str | None = None
    if isinstance(thinking, Mapping):
        thinking_present = True
        raw_type = thinking.get("type")
        thinking_type = raw_type if isinstance(raw_type, str) else None

    raw_effort = body.get("reasoning_effort")
    reasoning_effort = raw_effort if isinstance(raw_effort, str) else None

    roles: list[str] = []
    tool_result_ids: list[str] = []
    assistant_reasoning_content_present = False
    for message in _as_messages(body):
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        role_str = role if isinstance(role, str) else ""
        roles.append(role_str)
        if role_str == _ASSISTANT_ROLE and message.get("reasoning_content"):
            assistant_reasoning_content_present = True
        if role_str == _TOOL_ROLE:
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str):
                tool_result_ids.append(call_id)

    return SanitizedRequest(
        index=index,
        model=model if isinstance(model, str) else None,
        tools_present=tools_present,
        tools_count=tools_count,
        tool_choice_present=tool_choice_present,
        tool_choice_category=tool_choice_category,
        thinking_present=thinking_present,
        thinking_type=thinking_type,
        reasoning_effort=reasoning_effort,
        assistant_reasoning_content_present=assistant_reasoning_content_present,
        tool_result_ids=tuple(tool_result_ids),
        message_roles=tuple(roles),
    )


class DeepSeekTransportCapture:
    """A recording ``httpx2`` mock transport for offline DeepSeek tests.

    Each request is projected through :func:`project_request`; the raw request
    body is discarded immediately after projection.  Responses are supplied in
    order and returned as JSON Chat Completions bodies.
    """

    def __init__(self, responses: Sequence[Mapping[str, Any]]) -> None:
        self._responses = list(responses)
        self._cursor = 0
        self.requests: list[SanitizedRequest] = []

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def client(self) -> httpx2.AsyncClient:
        capture = self

        class _RecordingTransport(httpx2.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
                capture.requests.append(project_request(len(capture.requests), request.content))
                if capture._cursor >= len(capture._responses):
                    raise httpx2.ConnectError("No more mock DeepSeek responses") from None
                body = capture._responses[capture._cursor]
                capture._cursor += 1
                return httpx2.Response(
                    200,
                    json=dict(body),
                    headers={"content-type": "application/json"},
                )

        return httpx2.AsyncClient(transport=_RecordingTransport())


def deepseek_chat_completion(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: Sequence[Mapping[str, Any]] | None = None,
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """Build a synthetic DeepSeek/OpenAI-shaped Chat Completions body."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    if tool_calls:
        message["tool_calls"] = [dict(call) for call in tool_calls]

    if finish_reason is None:
        finish_reason = "tool_calls" if tool_calls else "stop"

    return {
        "id": "chatcmpl-deepseek-synthetic",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
