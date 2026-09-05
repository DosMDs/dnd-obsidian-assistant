"""PAIM-01: Real local Ollama smoke test for Pydantic AI qualification.

Opt-in test requiring a running local Ollama instance.
Skipped by default unless DND_ASSISTANT_OLLAMA_SMOKE_CONFIG is set.

This is NOT part of the normal test suite.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.ollama

# ---------------------------------------------------------------------------
# Smoke configuration
# ---------------------------------------------------------------------------

SMOKE_CONFIG_ENV = "DND_ASSISTANT_OLLAMA_SMOKE_CONFIG"

# Default values if env var is absent
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_MODEL = "huihui_ai/qwen3.5-abliterated:35b"


def _smoke_skip_condition() -> bool:
    """Return True if smoke tests should be skipped."""
    return os.environ.get(SMOKE_CONFIG_ENV) is None


_SMOKE_SKIP_REASON = (
    f"Set {SMOKE_CONFIG_ENV}=1 or {SMOKE_CONFIG_ENV}=base_url,model"
    " to enable real Ollama smoke tests"
)


def _parse_smoke_config() -> tuple[str, str]:
    """Parse smoke config into (base_url, model_name)."""
    config = os.environ.get(SMOKE_CONFIG_ENV, "1")
    parts = config.split(",", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return _DEFAULT_OLLAMA_BASE_URL, _DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Smoke: plain text response
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_smoke_skip_condition(), reason=_SMOKE_SKIP_REASON)
def test_ollama_plain_text() -> None:
    """Pydantic AI OllamaModel -> local Ollama -> plain text response."""
    from pydantic_ai import Agent
    from pydantic_ai.models.ollama import OllamaModel
    from pydantic_ai.providers.ollama import OllamaProvider

    base_url, model_name = _parse_smoke_config()
    provider = OllamaProvider(base_url=base_url)
    model = OllamaModel(model_name, provider=provider)
    agent = Agent(model)

    result = agent.run_sync("Say exactly: smoke test ok")
    output = result.output.strip().lower()
    assert isinstance(output, str)
    assert len(output) > 0, "empty response from Ollama"


# ---------------------------------------------------------------------------
# Smoke: structured output
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_smoke_skip_condition(), reason=_SMOKE_SKIP_REASON)
def test_ollama_structured_output() -> None:
    """Pydantic AI OllamaModel -> local Ollama -> structured output."""
    from pydantic import BaseModel
    from pydantic_ai import Agent
    from pydantic_ai.models.ollama import OllamaModel
    from pydantic_ai.providers.ollama import OllamaProvider

    base_url, model_name = _parse_smoke_config()

    class SmokeResult(BaseModel):
        answer: str
        score: int

    provider = OllamaProvider(base_url=base_url)
    model = OllamaModel(model_name, provider=provider)
    agent = Agent(model, output_type=SmokeResult)

    result = agent.run_sync("Return answer='hello' and score=42 as structured output.")
    assert isinstance(result.output, SmokeResult)
    assert result.output.answer
    assert result.output.score > 0
