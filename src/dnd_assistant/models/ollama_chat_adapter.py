"""Provider-specific Ollama chat-response adaptation (S8-06).

This module owns provider-specific pure-ish adaptation for ordinary
``/api/chat`` responses *after* HTTP JSON decoding.  It is imported by
``OllamaModelProvider`` and is not part of the public
``dnd_assistant.models`` package API.

Responsibilities
────────────────
* Parse and validate plain chat responses (``parse_plain_chat_response``).
* Parse and validate structured generation responses
  (``parse_structured_chat_response``).
* Enforce presence-based ``tool_calls`` rejection for non-tool operations.

Architectural boundary
──────────────────────
This module depends only on the standard library, Pydantic,
``dnd_assistant.errors``, and ``dnd_assistant.models.types``.
It must not import from storage, retrieval, application, CLI, or tool modules.
It must not import httpx or perform any HTTP operation.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from dnd_assistant.errors import ModelError
from dnd_assistant.models.types import ChatMessage, ChatResponse, MessageRole

# ── Generic type ─────────────────────────────────────────────────────────────

T = TypeVar("T", bound=BaseModel)
"""Type variable bounded to Pydantic BaseModel for structured generation."""


# ── Shared helpers ───────────────────────────────────────────────────────────


def _assert_no_native_tool_calls(
    message_data: dict[str, object],
    *,
    operation: str,
) -> None:
    """Reject native ``tool_calls`` when they are not expected.

    Uses presence-based detection (not truthiness):

    * ``tool_calls`` field missing → allowed (no tool calls).
    * ``tool_calls`` present as ``[]`` → allowed (empty list, no calls).
    * ``tool_calls`` present as a non-empty list → ``ModelError``.
    * ``tool_calls`` present as any non-list value → ``ModelError``.

    Args:
        message_data: The parsed ``message`` dict from an Ollama response.
        operation: Human-readable operation name for error messages.

    Raises:
        ModelError: If ``tool_calls`` is present and is not an empty list.
    """
    if "tool_calls" not in message_data:
        return  # field absent — no tool calls

    raw = message_data["tool_calls"]

    if isinstance(raw, list):
        if len(raw) == 0:
            return  # empty list — no tool calls
        raise ModelError(
            f"Ollama {operation} returned unexpected tool_calls "
            f"({len(raw)} call(s)). "
            "Use chat_with_tools() (S8-04) for tool-calling responses."
        )

    # Present but not a list — always an error
    raise ModelError(
        f"Ollama {operation} returned malformed 'tool_calls' field: "
        f"expected a list, got {type(raw).__name__}"
    )


# ── Plain chat response ──────────────────────────────────────────────────────


def parse_plain_chat_response(data: object) -> ChatResponse:
    """Parse an Ollama ``POST /api/chat`` response into a ``ChatResponse``.

    Validates the outer response structure, enforces presence-based
    ``tool_calls`` rejection, validates the role and content, and
    constructs a validated ``ChatResponse``.

    Args:
        data: The already-decoded JSON response body from Ollama.

    Returns:
        A validated ``ChatResponse``.

    Raises:
        ModelError: For any malformed response, unexpected tool_calls,
            invalid message structure, or content validation failure.
    """
    if not isinstance(data, dict) or "message" not in data:
        raise ModelError("Ollama chat response missing 'message' field")

    msg_data = data["message"]
    if not isinstance(msg_data, dict):
        raise ModelError("Ollama chat response 'message' is not an object")

    role = msg_data.get("role", "")
    content = msg_data.get("content")

    # Presence-based tool_calls rejection (not truthiness)
    _assert_no_native_tool_calls(msg_data, operation="plain chat")

    if role != "assistant":
        raise ModelError(f"Ollama chat returned unexpected role: {role!r}. Expected 'assistant'.")

    # Build a ChatMessage; let Pydantic validation catch remaining issues
    try:
        chat_message = ChatMessage(role=MessageRole.ASSISTANT, content=content)
    except Exception as exc:
        raise ModelError(
            f"Invalid assistant message from Ollama: {exc}",
            cause=exc,
        ) from exc

    try:
        return ChatResponse(message=chat_message)
    except Exception as exc:
        raise ModelError(
            f"Invalid chat response from Ollama: {exc}",
            cause=exc,
        ) from exc


# ── Structured generation response ───────────────────────────────────────────


def parse_structured_chat_response(  # noqa: UP047
    data: object,
    schema: type[T],
) -> T:
    """Parse an Ollama ``POST /api/chat`` response into a validated schema instance.

    Validates the outer response structure (message, role, content),
    enforces presence-based ``tool_calls`` rejection, then validates the
    content against the caller-provided Pydantic schema.

    Args:
        data: The already-decoded JSON response body from Ollama.
        schema: A Pydantic ``BaseModel`` subclass describing the
            expected output shape.

    Returns:
        A validated instance of ``schema``.

    Raises:
        ModelError: For any malformed response, unexpected tool_calls,
            or schema validation failure.
    """
    if not isinstance(data, dict) or "message" not in data:
        raise ModelError("Ollama structured response missing 'message' field")

    msg_data = data["message"]
    if not isinstance(msg_data, dict):
        raise ModelError("Ollama structured response 'message' is not an object")

    role = msg_data.get("role", "")
    content = msg_data.get("content")

    # Presence-based tool_calls rejection (not truthiness)
    _assert_no_native_tool_calls(msg_data, operation="structured generation")

    if role != "assistant":
        raise ModelError(
            f"Ollama structured response returned unexpected role: {role!r}. Expected 'assistant'."
        )

    if not isinstance(content, str):
        raise ModelError(
            f"Ollama structured response 'message.content' is not a string, "
            f"got {type(content).__name__}"
        )

    # Validate content against the caller-provided schema
    try:
        return schema.model_validate_json(content)
    except Exception as exc:
        raise ModelError(
            f"Ollama structured response validation failed: {exc}",
            cause=exc,
        ) from exc
