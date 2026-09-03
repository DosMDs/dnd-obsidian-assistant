"""Provider-specific Ollama tool-calling adaptation (S8-04).

This module owns pure-ish adaptation between:

    provider-neutral ToolPublicDefinition / ChatMessage / ToolCall
                        ↕
                 native Ollama JSON shapes

It must not own:
    HTTP client lifecycle
    tool execution / handler lookup
    ToolRegistry access
    Vault access
    agent loops
    permission enforcement
    session-mode enforcement
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dnd_assistant.errors import ModelError
from dnd_assistant.models.types import (
    ChatMessage,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)

if TYPE_CHECKING:
    from dnd_assistant.tools.catalog import ToolPublicDefinition


# ── Tool schema mapping ─────────────────────────────────────────────────────


def map_tools_to_ollama(tools: list[ToolPublicDefinition]) -> list[dict[str, Any]]:
    """Map provider-neutral ``ToolPublicDefinition`` list to Ollama tool JSON.

    Only ``name``, ``description``, and ``input_schema`` are sent.
    ``output_schema``, ``permission``, ``side_effects``, and
    ``allowed_session_modes`` are intentionally excluded.

    The input ``tools`` list order is preserved in the output.
    The original ``input_schema`` dict is not mutated.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


# ── Tool-aware message mapping ──────────────────────────────────────────────


def map_tool_aware_message(msg: ChatMessage) -> dict[str, Any]:
    """Map a provider-neutral ``ChatMessage`` to an Ollama message dict.

    Supports SYSTEM, USER, plain ASSISTANT, ASSISTANT with tool_calls,
    and TOOL result messages.

    Raises ``ModelError`` if the message contains a ``call_id`` or
    ``tool_call_id`` that cannot be represented losslessly in Ollama's
    native format.
    """
    role = msg.role

    if role in (MessageRole.SYSTEM, MessageRole.USER):
        return {
            "role": role.value,
            "content": msg.content or "",
        }

    if role == MessageRole.ASSISTANT:
        return _map_assistant_message(msg)

    if role == MessageRole.TOOL:
        return _map_tool_result_message(msg)

    raise ModelError(f"Unknown message role: {role!r}")


def _map_assistant_message(msg: ChatMessage) -> dict[str, Any]:
    """Map an ASSISTANT message to Ollama JSON.

    Supports plain text, tool-calls-only, and text + tool calls.

    Raises ``ModelError`` if any ``ToolCall`` has a non-None ``call_id``
    because native Ollama cannot represent that metadata losslessly.
    """
    result: dict[str, Any] = {
        "role": MessageRole.ASSISTANT.value,
    }

    if msg.content is not None:
        result["content"] = msg.content

    if msg.tool_calls:
        for tc in msg.tool_calls:
            if tc.call_id is not None:
                raise ModelError(
                    "Ollama adapter cannot represent ToolCall.call_id losslessly. "
                    "Use call_id=None for Ollama tool calls."
                )

        result["tool_calls"] = [
            {
                "type": "function",
                "function": {
                    "index": idx,
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for idx, tc in enumerate(msg.tool_calls)
        ]

    return result


def _map_tool_result_message(msg: ChatMessage) -> dict[str, Any]:
    """Map a TOOL result message to Ollama JSON.

    Raises ``ModelError`` if ``tool_call_id`` is non-None because
    native Ollama cannot represent that metadata losslessly.
    """
    if msg.tool_call_id is not None:
        raise ModelError(
            "Ollama adapter cannot represent ChatMessage.tool_call_id losslessly. "
            "Use tool_call_id=None for Ollama tool results."
        )

    return {
        "role": MessageRole.TOOL.value,
        "tool_name": msg.tool_name or "",
        "content": msg.content or "",
    }


# ── Tool-aware history mapping ──────────────────────────────────────────────


def map_tool_aware_history(messages: tuple[ChatMessage, ...]) -> list[dict[str, Any]]:
    """Map a full provider-neutral message history to Ollama message list.

    Each message is mapped individually.  The history order is preserved.
    """
    return [map_tool_aware_message(m) for m in messages]


# ── Response parsing ────────────────────────────────────────────────────────


def parse_tool_aware_response(
    data: dict[str, Any],
    allowed_tool_names: set[str],
) -> ToolAwareResponse:
    """Parse an Ollama ``POST /api/chat`` response into ``ToolAwareResponse``.

    Validates the outer response structure, extracts tool calls, normalises
    content, and maps each valid native tool call into a provider-neutral
    ``ToolCall`` with ``call_id=None``.

    Args:
        data: The parsed JSON response from Ollama.
        allowed_tool_names: The set of tool names from the current
            ``chat_with_tools()`` ``tools`` argument.

    Returns:
        A validated ``ToolAwareResponse``.

    Raises:
        ModelError: For any malformed response, unknown tool type,
            out-of-allowlist tool name, invalid ``ToolCall``, or
            content normalisation failure.
    """
    if not isinstance(data, dict) or "message" not in data:
        raise ModelError("Ollama tool response missing 'message' field")

    msg_data = data["message"]
    if not isinstance(msg_data, dict):
        raise ModelError("Ollama tool response 'message' is not an object")

    role = msg_data.get("role", "")
    if role != "assistant":
        raise ModelError(
            f"Ollama tool response returned unexpected role: {role!r}. Expected 'assistant'."
        )

    content = msg_data.get("content")
    raw_tool_calls = msg_data.get("tool_calls")

    # Parse tool calls first
    tool_calls: tuple[ToolCall, ...] = ()
    if raw_tool_calls:
        tool_calls = _parse_tool_calls(raw_tool_calls, allowed_tool_names)

    # Normalise content
    if tool_calls:
        if content is None:
            pass  # content=None is acceptable with tool calls
        elif isinstance(content, str):
            if content == "":
                content = None  # Normalise empty string to None when tool calls exist
        else:
            raise ModelError(
                f"Ollama tool response 'message.content' is not a string or None, "
                f"got {type(content).__name__}"
            )
    else:
        # No tool calls — content must produce a valid text-only assistant message
        if content is None or (isinstance(content, str) and content == ""):
            raise ModelError("Ollama tool response has no tool calls and no usable content")
        if not isinstance(content, str):
            raise ModelError(
                f"Ollama tool response 'message.content' is not a string, "
                f"got {type(content).__name__}"
            )

    # Build the assistant ChatMessage
    try:
        chat_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        )
    except Exception as exc:
        raise ModelError(
            f"Invalid assistant message from Ollama tool response: {exc}",
            cause=exc,
        ) from exc

    try:
        return ToolAwareResponse(message=chat_message)
    except Exception as exc:
        raise ModelError(
            f"Invalid tool-aware response from Ollama: {exc}",
            cause=exc,
        ) from exc


def _parse_tool_calls(
    raw_tool_calls: object,
    allowed_tool_names: set[str],
) -> tuple[ToolCall, ...]:
    """Parse native Ollama tool calls into provider-neutral ``ToolCall`` tuples.

    Validates the native structure, maps each valid call, and rejects
    out-of-allowlist names.
    """
    if not isinstance(raw_tool_calls, list):
        raise ModelError(
            f"Ollama tool response 'tool_calls' is not a list, got {type(raw_tool_calls).__name__}"
        )

    result: list[ToolCall] = []
    for entry in raw_tool_calls:
        if not isinstance(entry, dict):
            raise ModelError(
                f"Ollama tool_calls entry is not an object, got {type(entry).__name__}"
            )

        # Validate type field if present
        entry_type = entry.get("type")
        if entry_type is not None and entry_type != "function":
            raise ModelError(
                f"Ollama tool_calls entry has unknown type: {entry_type!r}. Expected 'function'."
            )

        func = entry.get("function")
        if not isinstance(func, dict):
            raise ModelError("Ollama tool_calls entry 'function' is missing or not an object")

        name = func.get("name")
        if not isinstance(name, str) or not name:
            raise ModelError(
                "Ollama tool_calls entry 'function.name' is missing, empty, or not a string"
            )

        arguments = func.get("arguments")
        if not isinstance(arguments, dict):
            raise ModelError(
                "Ollama tool_calls entry 'function.arguments' is missing or not an object"
            )

        # Reject stringified arguments
        if isinstance(arguments, str):
            raise ModelError(
                "Ollama tool_calls entry 'function.arguments' is a JSON string, "
                "expected a JSON object"
            )

        # Allowlist check
        if name not in allowed_tool_names:
            raise ModelError(
                f"Ollama returned tool call '{name}' which is not in the "
                f"supplied allowlist. Allowed: {sorted(allowed_tool_names)}"
            )

        # Build provider-neutral ToolCall
        try:
            tc = ToolCall(name=name, arguments=arguments, call_id=None)
        except Exception as exc:
            raise ModelError(
                f"Invalid ToolCall from Ollama: {exc}",
                cause=exc,
            ) from exc

        result.append(tc)

    return tuple(result)
