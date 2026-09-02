"""ModelGateway — provider-neutral typed contract for LLM model inference.

Responsibility
──────────────
Owns: model interaction — prompt completion, structured output, tool calling,
       embeddings, health checks.
Must not own: prompt templates, domain logic, storage, tool execution.
Called by: application layer (FastAgent, PostSessionProcessor, etc.).
Failure boundary: raises ModelError on provider/network failure.

Canonical logical operations
────────────────────────────
chat                — multi-turn conversation (text in, text out).
chat_with_tools     — multi-turn conversation with tool-calling support.
generate_structured — produce structured output matching a Pydantic schema.
embed               — produce vector embeddings for text inputs.
health              — check provider reachability and model availability.

Stage-8 MVP decision: all five operations are synchronous (``def``, not
``async def``).  The current Typer/application/runtime stack is synchronous;
trusted Python services and ToolExecutor are synchronous; httpx supports
synchronous transport.  A future async provider/gateway may be added later
without changing this MVP contract retroactively.

Tool Layer handshake
────────────────────
``chat_with_tools()`` accepts ``ToolPublicDefinition`` from the Tool Layer
via a ``TYPE_CHECKING``-only import.  This keeps the gateway module
lightweight — importing ``dnd_assistant.models.gateway`` must not eagerly
load storage, retrieval, application, CLI, or Ollama.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar

from pydantic import BaseModel

from dnd_assistant.models.types import (
    ChatRequest,
    ChatResponse,
    ModelHealth,
    ToolAwareResponse,
)

if TYPE_CHECKING:
    from dnd_assistant.tools.catalog import ToolPublicDefinition

T = TypeVar("T", bound="BaseModel")

# Re-export the canonical Pydantic base type for the generic bound.
# We use a string forward-ref to avoid importing BaseModel at runtime
# in the Protocol signature — the concrete provider will import it.
# The Protocol itself only needs the TypeVar bound for type-checking.


class ModelGateway(Protocol):
    """Provider-neutral typed contract for LLM model inference.

    Every concrete provider must implement all five operations.
    """

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Plain multi-turn conversation (text in, text out)."""
        ...

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        """Multi-turn conversation with tool-calling support.

        Args:
            request: The conversation history.
            tools: Provider-neutral public tool definitions from the
                Tool Layer catalog.

        Returns:
            A ``ToolAwareResponse`` whose assistant message may contain
            text, tool calls, or both.
        """
        ...

    def generate_structured(
        self,
        request: ChatRequest,
        schema: type[T],
    ) -> T:
        """Produce structured output matching a Pydantic schema.

        Args:
            request: The conversation history.
            schema: A Pydantic ``BaseModel`` subclass describing the
                expected output shape.

        Returns:
            A validated instance of ``schema``.  The provider
            implementation must not return an unvalidated dict or
            string to application code.
        """
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Produce vector embeddings for text inputs.

        Args:
            texts: One or more text strings to embed.

        Returns:
            A list of embedding vectors, one per input text.
        """
        ...

    def health(self) -> ModelHealth:
        """Check provider reachability and model availability.

        Returns:
            A ``ModelHealth`` instance.  Normal unreachable or
            model-unavailable states are represented by the result
            fields — this method does not raise for those conditions.
            Network/transport errors that prevent *any* health
            assessment may raise ``ModelError``.
        """
        ...
