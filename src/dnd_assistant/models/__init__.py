"""Model Gateway — provider-neutral contracts and typed DTOs.

This package defines the provider-neutral ``ModelGateway`` protocol and
its associated data-transfer objects.  It depends only on Pydantic and
the standard library.

Importing this package must not trigger imports from:
    storage, retrieval, application, cli, ollama, tools (runtime)
"""

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

__all__: list[str] = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "MessageRole",
    "ModelGateway",
    "ModelHealth",
    "ToolAwareResponse",
    "ToolCall",
]
