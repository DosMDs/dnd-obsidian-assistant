"""Provider-neutral model DTOs for the ModelGateway contract.

This module defines the typed data-transfer objects used by the
``ModelGateway`` protocol.  It depends only on Pydantic and the
standard library — no storage, retrieval, application, CLI, Ollama,
or HTTP imports are allowed.

All models use ``extra="forbid"`` and ``frozen=True`` to prevent
silent field injection and accidental mutation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, JsonValue, model_validator


class MessageRole(StrEnum):
    """Role of a message in a multi-turn conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A model-requested tool call.

    ``name`` must be non-empty after validation.
    ``arguments`` is a JSON object.
    ``call_id`` is optional because providers differ in whether they
    emit one.
    """

    name: str
    arguments: dict[str, JsonValue]
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
    """Response from a plain chat (no tool-calling)."""

    message: ChatMessage

    model_config = {"extra": "forbid", "frozen": True}

    @model_validator(mode="after")
    def _role_is_assistant(self) -> ChatResponse:
        if self.message.role != MessageRole.ASSISTANT:
            raise ValueError("ChatResponse.message.role must be ASSISTANT")
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
