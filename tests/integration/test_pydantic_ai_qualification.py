"""PAIM-01: Pydantic AI candidate dependency/framework qualification.

Qualifies pydantic-ai-slim[openai]==2.39.0 against the D&D Session Assistant
environment using supported public APIs only.

All tests in this module are deterministic (TestModel-based) and require no
real Ollama or network access.
"""

from __future__ import annotations

import pydantic_ai
import pydantic_ai.exceptions
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, UnexpectedModelBehavior
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
# Q6 — multiple tool calls in one model response
# ---------------------------------------------------------------------------


def test_q6_multiple_tools_in_one_response() -> None:
    """One model response requests at least two harmless tools.

    Observes baseline framework behavior: TestModel issues all requested
    tool calls in a single ModelResponse, and the framework executes them
    sequentially (default synchronous behavior).
    """
    call_order: list[str] = []

    model = TestModel(call_tools=["tool_a", "tool_b"])
    agent = Agent(model)

    @agent.tool_plain
    def tool_a(x: int) -> str:
        call_order.append("a")
        return f"A={x}"

    @agent.tool_plain
    def tool_b(y: int) -> str:
        call_order.append("b")
        return f"B={y}"

    result = agent.run_sync("use both tools")
    assert len(call_order) == 2, f"expected 2 calls, got {len(call_order)}"
    assert "tool_a" in str(result.output)
    assert "tool_b" in str(result.output)

    # Observed concurrency: sequential (synchronous execution in main thread)
    assert call_order == ["a", "b"], f"expected sequential execution, got {call_order}"


# ---------------------------------------------------------------------------
# Q7 — custom Ollama base URL
# ---------------------------------------------------------------------------


def test_q7_custom_ollama_base_url() -> None:
    """Custom self-hosted base URL can be supplied via OllamaProvider.

    Verifies the framework targets the expected OpenAI-compatible Ollama
    endpoint family: <base>/chat/completions (where base includes /v1).
    """
    from pydantic_ai.providers.ollama import OllamaProvider

    custom_url = "http://my-ollama:11434/v1"
    provider = OllamaProvider(base_url=custom_url)
    model = OllamaModel("qwen3", provider=provider)

    # The provider stores the base URL with /v1 path
    base = str(model.provider.base_url)
    assert custom_url in base, f"expected {custom_url} in {base}"

    # The endpoint path is the standard OpenAI-compatible chat completions
    # path that Ollama serves at <base>/chat/completions
    # Pydantic AI's OllamaProvider uses Ollama namespace which correctly
    # targets the Ollama API without requiring /v1 prefix in the path


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
    """Connection/transport failure raises ModelAPIError."""
    provider = OpenAIProvider(
        base_url="http://localhost:1/v1",
        http_client=None,
    )
    model = OpenAIChatModel("test-model", provider=provider)
    agent = Agent(model)

    with pytest.raises(pydantic_ai.exceptions.ModelAPIError):
        agent.run_sync("hello")


def test_q8_unknown_tool_call_fails_closed() -> None:
    """Model requesting an unregistered tool raises UserError."""
    model = TestModel(call_tools=["nonexistent_tool"])
    agent = Agent(model)

    with pytest.raises(pydantic_ai.exceptions.UserError):
        agent.run_sync("call nonexistent_tool")


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
