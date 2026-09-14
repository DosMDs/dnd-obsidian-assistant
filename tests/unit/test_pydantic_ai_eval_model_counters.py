"""PAIM-C42: Reference ``CountingModelGateway`` literal-counter regressions.

Deterministic offline proof that reference-side model-request counting is
measured at the native ``ModelGateway.chat_with_tools`` semantic boundary
and is not inferred from tool execution or returned DTO contents.

No network, no Ollama, no environment variables.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ModelHealth,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition
from tests.support.paim13_live_harness import CountingModelGateway


class _SentinelError(RuntimeError):
    """Distinct exception used to prove unchanged error propagation."""


def _make_request() -> ChatRequest:
    return ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="hi"),))


def _text_response() -> ToolAwareResponse:
    return ToolAwareResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content="ok", tool_calls=()),
    )


def _tool_call_response() -> ToolAwareResponse:
    return ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(ToolCall(name="read_npc", arguments={"name": "Arlen"}, call_id="c1"),),
        ),
    )


class _SampleSchema(BaseModel):
    """Minimal Pydantic schema for structured-output delegation tests."""

    value: int = 0


class _SpyGateway:
    """Test-local ``ModelGateway`` spy recording every operation.

    Every operation returns a distinct, pre-constructed exact result
    instance so delegation identity can be asserted.  When ``error`` is
    set, every operation raises that exact exception instance.
    """

    def __init__(
        self,
        response: ToolAwareResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.chat_with_tools_calls = 0
        self.chat_calls = 0
        self.generate_structured_calls = 0
        self.embed_calls = 0
        self.health_calls = 0
        self._response = response if response is not None else _text_response()
        self._chat_response = ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content="ok"),
        )
        self._structured_response = _SampleSchema(value=7)
        self._embedding_response: list[list[float]] = [[0.0] * 4]
        self._health_response = ModelHealth(reachable=True, model_available=True)
        self._error = error

    def _raise_if_error(self) -> None:
        if self._error is not None:
            raise self._error

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.chat_with_tools_calls += 1
        self._raise_if_error()
        return self._response

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        self._raise_if_error()
        return self._chat_response

    def generate_structured(self, request: ChatRequest, schema: type) -> Any:
        self.generate_structured_calls += 1
        self._raise_if_error()
        return self._structured_response

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        self._raise_if_error()
        return self._embedding_response

    def health(self) -> ModelHealth:
        self.health_calls += 1
        self._raise_if_error()
        return self._health_response


class TestCountingModelGatewayLiteral:
    """Literal ``chat_with_tools`` counting at the native gateway boundary."""

    def test_one_call_increments_once_and_preserves_response(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)
        response = _text_response()
        delegate._response = response

        returned = gateway.chat_with_tools(_make_request(), [])

        assert gateway.state.chat_with_tools_count == 1
        assert delegate.chat_with_tools_calls == 1
        assert returned is response

    def test_multiple_calls_count_matches_literal_number(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        for _ in range(5):
            gateway.chat_with_tools(_make_request(), [])

        assert gateway.state.chat_with_tools_count == 5
        assert delegate.chat_with_tools_calls == 5

    def test_error_counted_once_and_propagates_unchanged(self) -> None:
        sentinel = _SentinelError("boom")
        delegate = _SpyGateway(error=sentinel)
        gateway = CountingModelGateway(delegate)

        with pytest.raises(_SentinelError) as exc_info:
            gateway.chat_with_tools(_make_request(), [])

        assert exc_info.value is sentinel
        assert gateway.state.chat_with_tools_count == 1
        assert delegate.chat_with_tools_calls == 1

    def test_zero_tool_call_response_still_counts(self) -> None:
        """Counting is at the request boundary, not inferred from tool calls."""
        delegate = _SpyGateway(response=_text_response())
        gateway = CountingModelGateway(delegate)

        returned = gateway.chat_with_tools(_make_request(), [])

        assert returned.message.tool_calls == ()
        assert gateway.state.chat_with_tools_count == 1

    def test_tool_call_response_counts_exactly_once(self) -> None:
        delegate = _SpyGateway(response=_tool_call_response())
        gateway = CountingModelGateway(delegate)

        returned = gateway.chat_with_tools(_make_request(), [])

        assert len(returned.message.tool_calls) == 1
        assert gateway.state.chat_with_tools_count == 1

    def test_other_operations_do_not_increment_chat_with_tools_count(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        gateway.chat(_make_request())
        gateway.generate_structured(_make_request(), _SampleSchema)
        gateway.embed(["a", "b"])
        gateway.health()

        assert gateway.state.chat_with_tools_count == 0
        assert delegate.chat_calls == 1
        assert delegate.generate_structured_calls == 1
        assert delegate.embed_calls == 1
        assert delegate.health_calls == 1


class TestCountingModelGatewayDelegation:
    """Exact delegate result/exception preservation across all operations."""

    def test_chat_preserves_exact_response(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        returned = gateway.chat(_make_request())

        assert returned is delegate._chat_response
        assert delegate.chat_calls == 1

    def test_chat_with_tools_preserves_exact_response(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        returned = gateway.chat_with_tools(_make_request(), [])

        assert returned is delegate._response
        assert delegate.chat_with_tools_calls == 1

    def test_generate_structured_preserves_exact_typed_result(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        returned = gateway.generate_structured(_make_request(), _SampleSchema)

        assert returned is delegate._structured_response
        assert isinstance(returned, _SampleSchema)
        assert delegate.generate_structured_calls == 1

    def test_embed_preserves_exact_result(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        returned = gateway.embed(["a", "b"])

        assert returned is delegate._embedding_response
        assert delegate.embed_calls == 1

    def test_health_preserves_exact_model_health(self) -> None:
        delegate = _SpyGateway()
        gateway = CountingModelGateway(delegate)

        returned = gateway.health()

        assert returned is delegate._health_response
        assert delegate.health_calls == 1

    def test_delegate_exceptions_propagate_unchanged(self) -> None:
        sentinel = _SentinelError("boom")
        delegate = _SpyGateway(error=sentinel)
        gateway = CountingModelGateway(delegate)

        operations = (
            lambda: gateway.chat(_make_request()),
            lambda: gateway.chat_with_tools(_make_request(), []),
            lambda: gateway.generate_structured(_make_request(), _SampleSchema),
            lambda: gateway.embed(["a"]),
            lambda: gateway.health(),
        )

        for operation in operations:
            with pytest.raises(_SentinelError) as exc_info:
                operation()
            assert exc_info.value is sentinel

        assert gateway.state.chat_with_tools_count == 1
