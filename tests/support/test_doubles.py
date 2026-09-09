"""Test-only deterministic model doubles for offline testing.

All offline-safe: no network, no model, no framework imports beyond
``pydantic_ai.models.Model`` and project DTOs.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ToolAwareResponse,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition


class FakeModel(Model):
    """Minimal deterministic Pydantic AI ``Model`` for offline testing.

    Returns a fixed ``ModelResponse`` with text ``"ok"`` on every
    ``request()`` call.  Tracks invocation count for test assertions.
    """

    def __init__(self) -> None:
        super().__init__()
        self._invocation_count = 0

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def system(self) -> str:
        return "test-system"

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self._invocation_count += 1
        return ModelResponse(parts=[TextPart(content="ok")])

    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncGenerator[Any, None]:
        self._invocation_count += 1
        yield ModelResponse(parts=[TextPart(content="ok")])


class RaisingFakeModel(Model):
    """Minimal deterministic Pydantic AI ``Model`` that raises on request.

    Useful for testing error-propagation paths.
    """

    def __init__(self) -> None:
        super().__init__()

    @property
    def model_name(self) -> str:
        return "raising-model"

    @property
    def system(self) -> str:
        return "test-system"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        msg = "Simulated model failure"
        raise RuntimeError(msg)

    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncGenerator[Any, None]:
        msg = "Simulated model failure"
        raise RuntimeError(msg)


class FakeModelGateway:
    """Minimal deterministic ``ModelGateway`` for offline testing.

    Returns a fixed text response on every ``chat_with_tools()`` call.
    Implements the ``ModelGateway`` protocol structurally.
    """

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content="ok"))

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        return ToolAwareResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content="ok", tool_calls=()),
        )

    def generate_structured(self, request: ChatRequest, schema: type) -> Any:
        return schema()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]

    def health(self) -> Any:
        return {"status": "ok"}
