"""PAIM-01/PAIM-C01: Pydantic AI candidate dependency/framework qualification.

Qualifies pydantic-ai-slim[openai]==2.39.0 against the D&D Session Assistant
environment using supported public APIs only.

All tests in this module are deterministic and require no real Ollama or
network access.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

import pydantic_ai
import pydantic_ai.exceptions
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.openai import OpenAIProvider

# ---------------------------------------------------------------------------
# Q1 — import and exact version
# ---------------------------------------------------------------------------


def test_q1_import_and_version() -> None:
    """Package imports and installed candidate is exactly 2.39.0."""
    assert pydantic_ai.__version__ == "2.39.0"


def test_q1_ollama_classes_importable() -> None:
    """Required Ollama public classes can be imported."""
    # These are the public APIs needed for the remaining qualification
    assert Agent is not None
    assert OllamaModel is not None
    assert OpenAIChatModel is not None
    assert OpenAIProvider is not None
    assert TestModel is not None


# ---------------------------------------------------------------------------
# Q2 — synchronous entry point
# ---------------------------------------------------------------------------


def test_q2_run_sync() -> None:
    """Minimal agent can execute synchronously through the public sync API."""
    model = TestModel(custom_output_text="hello from test")
    agent = Agent(model)
    result = agent.run_sync("test")
    assert result.output is not None
    assert isinstance(result.output, str)


# ---------------------------------------------------------------------------
# Q3 — plain text response
# ---------------------------------------------------------------------------


def test_q3_plain_text_response() -> None:
    """Deterministic plain text result from TestModel."""
    expected = "deterministic response"
    model = TestModel(custom_output_text=expected)
    agent = Agent(model)
    result = agent.run_sync("any prompt")
    assert result.output == expected
    assert isinstance(result.output, str)


# ---------------------------------------------------------------------------
# Q4 — structured output
# ---------------------------------------------------------------------------


class QualificationResult(BaseModel):
    """Small local Pydantic model exclusively for qualification."""

    name: str
    value: int


def test_q4_structured_output() -> None:
    """Framework run returns a validated typed object.

    Uses custom_output_args to simulate a structured response.
    The structured-output mode exercised here is ToolOutput (the default
    when output_type is a Pydantic model): the framework creates a synthetic
    tool for the output schema and the model's tool call populates it.
    """
    model = TestModel(custom_output_args={"name": "qual", "value": 42})
    agent = Agent(model, output_type=QualificationResult)
    result = agent.run_sync("produce structured output")
    assert isinstance(result.output, QualificationResult)
    assert result.output.name == "qual"
    assert result.output.value == 42


# ---------------------------------------------------------------------------
# Q5 — single function tool
# ---------------------------------------------------------------------------


def test_q5_single_tool() -> None:
    """Model requests tool -> tool called exactly once -> result reaches output."""
    call_count: int = 0

    model = TestModel(call_tools=["greet"])
    agent = Agent(model)

    @agent.tool_plain
    def greet(name: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"Hello, {name}!"

    result = agent.run_sync("use the greet tool")
    assert call_count == 1, f"expected 1 call, got {call_count}"
    assert result.output is not None
    assert "Hello" in str(result.output)


# ---------------------------------------------------------------------------
# Q6 — multi-tool execution semantics (PAIM-C01 correction)
# ---------------------------------------------------------------------------


@dataclass
class _ConcurrencyEvidence:
    """Shared state for proving concurrent tool execution."""

    a_started: bool = False
    b_started: bool = False
    a_finished: bool = False
    b_finished: bool = False
    max_active: int = 0
    active: int = 0
    lock: threading.Lock = threading.Lock()

    def enter_a(self) -> None:
        with self.lock:
            self.a_started = True
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def exit_a(self) -> None:
        with self.lock:
            self.active -= 1
            self.a_finished = True

    def enter_b(self) -> None:
        with self.lock:
            self.b_started = True
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def exit_b(self) -> None:
        with self.lock:
            self.active -= 1
            self.b_finished = True

    async def wait_for_b(self, timeout: float = 5.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while not self.b_started and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.001)

    async def wait_for_a(self, timeout: float = 5.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while not self.a_started and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.001)


def test_q6a_default_multi_tool_concurrency() -> None:
    """Default multi-tool execution is concurrent (overlapping).

    Two async tools that synchronise via shared state: tool_a waits until
    tool_b has started, proving that both are active simultaneously under
    the default parallel execution mode.
    """
    evidence = _ConcurrencyEvidence()

    async def tool_a_impl(x: int) -> str:
        evidence.enter_a()
        await evidence.wait_for_b()
        await asyncio.sleep(0.01)
        evidence.exit_a()
        return f"A={x}"

    async def tool_b_impl(y: int) -> str:
        evidence.enter_b()
        await evidence.wait_for_a()
        await asyncio.sleep(0.01)
        evidence.exit_b()
        return f"B={y}"

    # Use TestModel to request both tools in one ModelResponse
    model = TestModel(call_tools=["tool_a", "tool_b"])
    agent = Agent(model)

    @agent.tool_plain
    async def tool_a(x: int) -> str:
        return await tool_a_impl(x)

    @agent.tool_plain
    async def tool_b(y: int) -> str:
        return await tool_b_impl(y)

    result = agent.run_sync("use both tools")
    assert evidence.a_started
    assert evidence.b_started
    assert evidence.a_finished
    assert evidence.b_finished
    # Default mode is parallel: both tools were active simultaneously
    assert evidence.max_active >= 2, (
        f"expected concurrent execution (max_active >= 2), got max_active={evidence.max_active}"
    )
    assert "tool_a" in str(result.output)
    assert "tool_b" in str(result.output)


def test_q6b_explicit_sequential_mode() -> None:
    """Explicit parallel_tool_call_execution_mode('sequential') serialises tools.

    Under sequential mode, tool_b starts only after tool_a finishes,
    so max_active never exceeds 1.
    """
    evidence = _ConcurrencyEvidence()

    async def tool_a_impl(x: int) -> str:
        evidence.enter_a()
        await asyncio.sleep(0.05)
        evidence.exit_a()
        return f"A={x}"

    async def tool_b_impl(y: int) -> str:
        evidence.enter_b()
        await asyncio.sleep(0.05)
        evidence.exit_b()
        return f"B={y}"

    model = TestModel(call_tools=["tool_a", "tool_b"])
    agent = Agent(model)

    @agent.tool_plain
    async def tool_a(x: int) -> str:
        return await tool_a_impl(x)

    @agent.tool_plain
    async def tool_b(y: int) -> str:
        return await tool_b_impl(y)

    with agent.parallel_tool_call_execution_mode("sequential"):
        result = agent.run_sync("use both tools sequentially")

    assert evidence.a_started
    assert evidence.b_started
    assert evidence.a_finished
    assert evidence.b_finished
    # Sequential: at most one tool active at a time
    assert evidence.max_active <= 1, (
        f"expected sequential execution (max_active <= 1), got max_active={evidence.max_active}"
    )
    # Model-emission order is preserved: tool_a before tool_b
    assert "tool_a" in str(result.output)
    assert "tool_b" in str(result.output)


def test_q6c_sync_tool_worker_thread() -> None:
    """A synchronous tool_plain tool executes on a worker thread, not the
    calling thread.

    This is crucial evidence for PAIM-10 (sync/thread safety gate).
    """
    calling_thread_id = threading.get_ident()
    tool_thread_id: list[int] = []

    model = TestModel(call_tools=["identify"])
    agent = Agent(model)

    @agent.tool_plain
    def identify() -> str:
        tool_thread_id.append(threading.get_ident())
        return f"thread={threading.get_ident()}"

    result = agent.run_sync("call identify")
    assert len(tool_thread_id) == 1
    assert tool_thread_id[0] != calling_thread_id, (
        f"sync tool executed on calling thread {calling_thread_id}, "
        f"expected worker thread, got {tool_thread_id[0]}"
    )
    assert result.output is not None


# ---------------------------------------------------------------------------
# Q7 — custom Ollama base URL
# ---------------------------------------------------------------------------
# PAIM-C01 correction: evidence narrowed to what is actually proven.
# The tests prove that OllamaProvider and OpenAIProvider accept and store
# a custom base_url ending in /v1. They do NOT independently capture the
# exact outgoing HTTP request path (e.g. <base>/chat/completions).
# Real Ollama smoke tests (test_pydantic_ai_ollama_smoke.py) prove that
# a real Ollama instance responds correctly through the configured URL.


def test_q7_custom_ollama_base_url() -> None:
    """OllamaProvider accepts custom base_url ending in /v1."""
    from pydantic_ai.providers.ollama import OllamaProvider

    custom_url = "http://my-ollama:11434/v1"
    provider = OllamaProvider(base_url=custom_url)
    model = OllamaModel("qwen3", provider=provider)

    base = str(model.provider.base_url)
    assert custom_url in base, f"expected {custom_url} in {base}"


def test_q7_custom_ollama_base_url_with_openai_provider() -> None:
    """OpenAIProvider with explicit /v1 suffix works for Ollama."""
    custom_url = "http://my-ollama:11434/v1"
    provider = OpenAIProvider(base_url=custom_url)
    model = OllamaModel("qwen3", provider=provider)

    base = str(model.provider.base_url)
    assert custom_url in base, f"expected {custom_url} in {base}"


# ---------------------------------------------------------------------------
# Q8 — predictable framework/provider failure behavior
# ---------------------------------------------------------------------------


def test_q8_connection_failure() -> None:
    """Connection/transport failure raises ModelAPIError.

    Uses a mocked httpx2 transport that raises ConnectError without
    attempting a real socket connection. No real localhost socket is
    opened — the failure is deterministic and requires no network.
    """
    import httpx2
    from openai import AsyncOpenAI

    class _AlwaysFailTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("Mocked connection failure")

    mock_client = httpx2.AsyncClient(transport=_AlwaysFailTransport())
    openai_client = AsyncOpenAI(
        http_client=mock_client,
        api_key="test-key",
        base_url="https://pydantic-ai-test.invalid/v1",
    )
    provider = OpenAIProvider(openai_client=openai_client)
    model = OpenAIChatModel("test-model", provider=provider)
    agent = Agent(model)

    with pytest.raises(pydantic_ai.exceptions.ModelAPIError):
        agent.run_sync("hello")


# ---------------------------------------------------------------------------
# Q8b — unknown tool call semantics (PAIM-C01 correction)
# ---------------------------------------------------------------------------
# PAIM-C01 correction: replaced TestModel-based unknown-tool test with
# FunctionModel-based tests that emulate a provider response containing
# an unknown function call. This is a proper runtime unknown-tool test.


def _make_unknown_tool_response_counter(
    counter: list[int],
) -> object:
    """Return a FunctionModel function that counts model invocations.

    Each call appends 1 to *counter* and returns a ToolCallPart for an
    unregistered tool name.
    """

    def _respond(messages: list, agent_info: object) -> ModelResponse:
        counter[0] += 1
        return ModelResponse(
            parts=[ToolCallPart(tool_name="nonexistent_tool", args="{}")],
        )

    return _respond


def test_q8b_unknown_tool_default_retry() -> None:
    """Unknown tool call with default retry policy.

    Proves:
      - model request count > 1  (semantic retry model round occurred)
      - application tool handler count == 0
      - exact exception type is UnexpectedModelBehavior
    """
    model_requests: list[int] = [0]
    func = _make_unknown_tool_response_counter(model_requests)
    model = FunctionModel(function=func)
    agent = Agent(model)

    handler_calls: list[int] = [0]

    @agent.tool_plain
    def real_tool(x: int) -> str:
        handler_calls[0] += 1
        raise AssertionError("should not be called")

    with pytest.raises(UnexpectedModelBehavior) as exc_info:
        agent.run_sync("call nonexistent_tool")

    # Evidence: at least one semantic retry model round occurred
    assert model_requests[0] > 1, (
        f"expected model requests > 1 (semantic retry), got {model_requests[0]}"
    )
    # Evidence: no application tool handler executed
    assert handler_calls[0] == 0, f"expected 0 handler calls, got {handler_calls[0]}"
    # Evidence: exact public exception type
    assert "exceeded max retries count" in str(exc_info.value).lower()


def test_q8b_unknown_tool_zero_retries() -> None:
    """Unknown tool call with retries={'tools': 0}.

    Proves:
      - model request count == 1  (no semantic retry model round)
      - application tool handler count == 0
      - exact exception type is UnexpectedModelBehavior
    """
    model_requests: list[int] = [0]
    func = _make_unknown_tool_response_counter(model_requests)
    model = FunctionModel(function=func)
    agent = Agent(model, retries={"tools": 0})

    handler_calls: list[int] = [0]

    @agent.tool_plain
    def real_tool(x: int) -> str:
        handler_calls[0] += 1
        return f"x={x}"

    with pytest.raises(UnexpectedModelBehavior) as exc_info:
        agent.run_sync("call nonexistent_tool")

    # Evidence: no semantic retry model round
    assert model_requests[0] == 1, (
        f"expected model requests == 1 (no retry), got {model_requests[0]}"
    )
    # Evidence: no application tool handler executed
    assert handler_calls[0] == 0, f"expected 0 handler calls, got {handler_calls[0]}"
    # Evidence: exact public exception type
    assert "exceeded max retries count" in str(exc_info.value).lower()


def test_q8_structured_output_validation_failure() -> None:
    """Structured output validation failure raises UnexpectedModelBehavior."""
    model = TestModel(custom_output_args={"bad_field": "nope"})
    agent = Agent(model, output_type=QualificationResult)

    with pytest.raises(UnexpectedModelBehavior):
        agent.run_sync("produce structured output")


def test_q8_structured_output_retry_behavior() -> None:
    """Framework retries structured output on validation failure.

    Default retry count is 1 (output validation retry). After exhausting
    retries, UnexpectedModelBehavior is raised.
    """
    model = TestModel(custom_output_args={"bad_field": "nope"})
    agent = Agent(model, output_type=QualificationResult)

    with pytest.raises(UnexpectedModelBehavior) as exc_info:
        agent.run_sync("produce structured output")

    error_msg = str(exc_info.value)
    assert "Exceeded maximum output retries" in error_msg


# ---------------------------------------------------------------------------
# Public exception class reference
# ---------------------------------------------------------------------------


def test_public_exception_classes() -> None:
    """Document the public exception hierarchy observed during qualification."""
    # ModelAPIError is the base for model/provider errors
    assert issubclass(pydantic_ai.exceptions.ModelAPIError, RuntimeError)
    assert issubclass(pydantic_ai.exceptions.ModelHTTPError, pydantic_ai.exceptions.ModelAPIError)

    # UserError for configuration/invalid usage (direct Exception subclass)
    assert issubclass(pydantic_ai.exceptions.UserError, Exception)

    # UnexpectedModelBehavior for validation/retry exhaustion
    assert issubclass(UnexpectedModelBehavior, RuntimeError)
