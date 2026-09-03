"""Provider-neutral model DTOs for the ModelGateway contract.

This module defines the typed data-transfer objects used by the
``ModelGateway`` protocol.  It depends only on Pydantic and the
standard library — no storage, retrieval, application, CLI, Ollama,
or HTTP imports are allowed.

All models use ``extra="forbid"`` and ``frozen=True`` to prevent
silent field injection and accidental mutation.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, JsonValue, model_validator
from pydantic.functional_validators import AfterValidator


class MessageRole(StrEnum):
    """Role of a message in a multi-turn conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


def _reject_non_finite(v: object) -> object:
    """Reject non-finite float values recursively in JSON-compatible data.

    Pydantic's ``JsonValue`` accepts ``float("nan")``, ``float("inf")``,
    and ``float("-inf")`` by default, but these are not valid JSON values.
    This validator ensures strict JSON compatibility at any nesting depth.
    """
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise ValueError(
            "Non-finite float values (NaN, Infinity, -Infinity) are not "
            "valid JSON values and are not permitted in ToolCall.arguments"
        )
    if isinstance(v, dict):
        for val in v.values():
            _reject_non_finite(val)
    elif isinstance(v, list):
        for item in v:
            _reject_non_finite(item)
    return v


FiniteJsonValue = Annotated[JsonValue, AfterValidator(_reject_non_finite)]
"""``JsonValue`` that rejects non-finite floats (NaN, ±Infinity) recursively."""


class ToolCall(BaseModel):
    """A model-requested tool call.

    ``name`` must be non-empty after validation.
    ``arguments`` is a JSON object with strict JSON-compatible values
    (non-finite floats such as NaN and ±Infinity are rejected).
    ``call_id`` is optional because providers differ in whether they
    emit one.
    """

    name: str
    arguments: dict[str, FiniteJsonValue]
    call_id: str | None = None

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _name_non_empty(self) -> ToolCall:
        if not self.name:
            raise ValueError("ToolCall.name must be non-empty")
        return self


class ChatMessage(BaseModel):
    """A single message in a multi-turn conversation.

    Validation invariants:

    * SYSTEM / USER — non-empty ``content`` required, no tool metadata.
    * ASSISTANT — at least one of ``content`` or ``tool_calls`` must
      be non-empty; ``tool_name`` and ``tool_call_id`` forbidden.
    * TOOL — non-empty ``content`` and ``tool_name`` required; no
      nested ``tool_calls``.
    """

    role: MessageRole
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str | None = None
    tool_call_id: str | None = None

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _validate_role_invariants(self) -> ChatMessage:
        role = self.role

        if role in (MessageRole.SYSTEM, MessageRole.USER):
            if not self.content:
                raise ValueError(f"{role.value} message must have non-empty content")
            if self.tool_calls:
                raise ValueError(f"{role.value} message must not have tool_calls")
            if self.tool_name is not None:
                raise ValueError(f"{role.value} message must not have tool_name")
            if self.tool_call_id is not None:
                raise ValueError(f"{role.value} message must not have tool_call_id")

        elif role == MessageRole.ASSISTANT:
            if not self.content and not self.tool_calls:
                raise ValueError(
                    "ASSISTANT message must have at least one of content or tool_calls"
                )
            if self.tool_name is not None:
                raise ValueError("ASSISTANT message must not have tool_name")
            if self.tool_call_id is not None:
                raise ValueError("ASSISTANT message must not have tool_call_id")

        elif role == MessageRole.TOOL:
            if not self.content:
                raise ValueError("TOOL message must have non-empty content")
            if not self.tool_name:
                raise ValueError("TOOL message must have non-empty tool_name")
            if self.tool_calls:
                raise ValueError("TOOL message must not have tool_calls")

        return self


class ChatRequest(BaseModel):
    """A request to send a conversation to a model.

    Must contain at least one message.
    """

    messages: tuple[ChatMessage, ...]

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _at_least_one_message(self) -> ChatRequest:
        if not self.messages:
            raise ValueError("ChatRequest must have at least one message")
        return self


class ChatResponse(BaseModel):
    """Response from a plain chat (no tool-calling).

    The assistant message must have no tool calls — tool-calling
    responses belong in ``ToolAwareResponse``.
    """

    message: ChatMessage

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _role_is_assistant(self) -> ChatResponse:
        if self.message.role != MessageRole.ASSISTANT:
            raise ValueError("ChatResponse.message.role must be ASSISTANT")
        return self

    @model_validator(mode="after")
    def _no_tool_calls(self) -> ChatResponse:
        if self.message.tool_calls:
            raise ValueError(
                "ChatResponse must not contain tool calls — "
                "use ToolAwareResponse for tool-calling responses"
            )
        return self


class ToolAwareResponse(BaseModel):
    """Response from a chat-with-tools invocation.

    The assistant message may contain text only, tool calls only, or
    both — the model is allowed to answer without calling a tool.
    """

    message: ChatMessage

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _role_is_assistant(self) -> ToolAwareResponse:
        if self.message.role != MessageRole.ASSISTANT:
            raise ValueError("ToolAwareResponse.message.role must be ASSISTANT")
        return self


class ModelHealth(BaseModel):
    """Provider-neutral health-check result."""

    reachable: bool
    model_available: bool
    detail: str | None = None

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _model_available_requires_reachable(self) -> ModelHealth:
        if self.model_available and not self.reachable:
            raise ValueError("model_available=True requires reachable=True")
        return self

    @property
    def healthy(self) -> bool:
        """Convenience: ``True`` when both reachable and model_available."""
        return self.reachable and self.model_available
