"""Opt-in real Ollama smoke tests (S8-06).

These tests require explicit environment configuration to run:

* ``DND_ASSISTANT_OLLAMA_SMOKE_CONFIG`` — path to the normal machine TOML.
* ``DND_ASSISTANT_OLLAMA_SMOKE_AGENT_PROFILE`` — profile name for
  chat/structured/tool smoke.
* ``DND_ASSISTANT_OLLAMA_SMOKE_EMBEDDING_PROFILE`` — profile name for
  embedding smoke.

When ``DND_ASSISTANT_OLLAMA_SMOKE_CONFIG`` is absent, all tests skip
before any network request.

When present, a missing profile variable, invalid config, unreachable
endpoint, or unavailable model causes the opted-in run to fail.

No hardcoded endpoint or model defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import load_model_profiles
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ToolAwareResponse,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.types import Permission, SessionMode

pytestmark = pytest.mark.ollama

# ── Environment variable names ───────────────────────────────────────────────

ENV_CONFIG = "DND_ASSISTANT_OLLAMA_SMOKE_CONFIG"
ENV_AGENT_PROFILE = "DND_ASSISTANT_OLLAMA_SMOKE_AGENT_PROFILE"
ENV_EMBEDDING_PROFILE = "DND_ASSISTANT_OLLAMA_SMOKE_EMBEDDING_PROFILE"


# ── Test schema for structured generation ─────────────────────────────────────


class SmokeStructuredResult(BaseModel):
    """Minimal schema for structured-generation smoke tests."""

    ok: bool


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _require_env(name: str) -> str:
    """Get a required environment variable or raise a clear error."""
    value = os.environ.get(name)
    if not value:
        pytest.fail(
            f"Explicit smoke opt-in detected ({ENV_CONFIG} is set), "
            f"but required variable {name} is missing or empty."
        )
    return value


@pytest.fixture(scope="module")
def smoke_config_path() -> Path:
    """Load and validate the smoke config path from environment.

    When ``DND_ASSISTANT_OLLAMA_SMOKE_CONFIG`` is absent, skip all
    tests before any network request.
    """
    raw = os.environ.get(ENV_CONFIG)
    if not raw:
        pytest.skip(f"{ENV_CONFIG} is not set — skipping real Ollama smoke tests")
    path = Path(raw)
    if not path.exists():
        pytest.fail(
            f"Explicit smoke opt-in detected ({ENV_CONFIG}={raw}), "
            f"but config file not found: {path}"
        )
    return path


@pytest.fixture(scope="module")
def smoke_agent_profile_name() -> str:
    return _require_env(ENV_AGENT_PROFILE)


@pytest.fixture(scope="module")
def smoke_embedding_profile_name() -> str:
    return _require_env(ENV_EMBEDDING_PROFILE)


@pytest.fixture(scope="module")
def smoke_config(smoke_config_path: Path) -> Any:
    """Load the full model profiles config from the smoke config path."""
    try:
        return load_model_profiles(smoke_config_path)
    except Exception as exc:
        pytest.fail(f"Failed to load smoke config from {smoke_config_path}: {exc}")


@pytest.fixture(scope="module")
def agent_provider(smoke_config: Any, smoke_agent_profile_name: str) -> Any:
    """Create an OllamaModelProvider from the agent profile.

    The provider is closed in the module-scoped finalizer.
    """
    if smoke_agent_profile_name not in smoke_config.profiles:
        pytest.fail(
            f"Agent profile {smoke_agent_profile_name!r} not found in config. "
            f"Available: {list(smoke_config.profiles)}"
        )

    profile = smoke_config.profiles[smoke_agent_profile_name]
    if profile.provider != "ollama":
        pytest.fail(
            f"Agent profile {smoke_agent_profile_name!r} has "
            f"provider={profile.provider!r}, expected 'ollama'"
        )

    provider = OllamaModelProvider(profile)
    yield provider
    provider.close()


@pytest.fixture(scope="module")
def embedding_provider(smoke_config: Any, smoke_embedding_profile_name: str) -> Any:
    """Create an OllamaModelProvider from the embedding profile.

    The provider is closed in the module-scoped finalizer.
    """
    if smoke_embedding_profile_name not in smoke_config.profiles:
        pytest.fail(
            f"Embedding profile {smoke_embedding_profile_name!r} not found in config. "
            f"Available: {list(smoke_config.profiles)}"
        )

    profile = smoke_config.profiles[smoke_embedding_profile_name]
    if profile.provider != "ollama":
        pytest.fail(
            f"Embedding profile {smoke_embedding_profile_name!r} has "
            f"provider={profile.provider!r}, expected 'ollama'"
        )

    provider = OllamaModelProvider(profile)
    yield provider
    provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Health smoke
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthSmoke:
    """Real Ollama health check."""

    def test_agent_health(self, agent_provider: OllamaModelProvider) -> None:
        result = agent_provider.health()
        assert result.reachable is True, f"Ollama endpoint is not reachable: {result.detail}"
        assert result.model_available is True, f"Configured model is not available: {result.detail}"


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat smoke
# ═══════════════════════════════════════════════════════════════════════════


class TestChatSmoke:
    """Real Ollama plain chat."""

    def test_simple_chat(self, agent_provider: OllamaModelProvider) -> None:
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Say hello"),))
        result = agent_provider.chat(request)
        assert isinstance(result, ChatResponse)
        assert result.message.content is not None
        assert len(result.message.content) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Structured generation smoke
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredSmoke:
    """Real Ollama structured generation."""

    def test_simple_structured(self, agent_provider: OllamaModelProvider) -> None:
        request = ChatRequest(
            messages=(
                ChatMessage(
                    role=MessageRole.USER,
                    content='Return JSON: {"ok": true}',
                ),
            )
        )
        result = agent_provider.generate_structured(request, SmokeStructuredResult)
        assert isinstance(result, SmokeStructuredResult)
        assert result.ok is True


# ═══════════════════════════════════════════════════════════════════════════
# Tool transport smoke
# ═══════════════════════════════════════════════════════════════════════════


class TestToolTransportSmoke:
    """Real Ollama tool-calling transport (no tool execution)."""

    def test_tool_transport(self, agent_provider: OllamaModelProvider) -> None:
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Say hello"),))
        tools = [
            ToolPublicDefinition(
                name="smoke_echo",
                description="Echo back the input text",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
                permission=Permission.READ,
                side_effects=[],
                allowed_session_modes=[
                    SessionMode.ACTIVE_SESSION,
                    SessionMode.NO_ACTIVE_SESSION,
                ],
            )
        ]

        result = agent_provider.chat_with_tools(request, tools)
        assert isinstance(result, ToolAwareResponse)
        assert result.message.role == MessageRole.ASSISTANT

        # Model may return text, tool calls, or both — all are valid
        if result.message.tool_calls:
            for tc in result.message.tool_calls:
                assert tc.name == "smoke_echo", f"Unexpected tool call name: {tc.name!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Embedding smoke
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingSmoke:
    """Real Ollama embeddings."""

    def test_simple_embedding(self, embedding_provider: OllamaModelProvider) -> None:
        result = embedding_provider.embed(["smoke"])
        assert isinstance(result, list)
        assert len(result) == 1
        vector = result[0]
        assert isinstance(vector, list)
        assert len(vector) > 0
        for val in vector:
            assert isinstance(val, float)
            from math import isfinite

            assert isfinite(val), f"Non-finite embedding value: {val}"
