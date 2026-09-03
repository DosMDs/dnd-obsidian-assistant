"""Mocked integration tests for OllamaModelProvider with real profile loading.

Proves that the accepted machine profile loader and concrete
``OllamaModelProvider`` compose correctly across all five ModelGateway
operations without introducing a Stage-9 application composition layer.

All tests use mocked HTTP (respx) — no real Ollama, no network, no Vault.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import load_model_profiles
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ModelHealth,
    ToolAwareResponse,
)
from dnd_assistant.tools.catalog import ToolPublicDefinition
from dnd_assistant.tools.types import Permission, SessionMode

# ── Test schema for structured generation ─────────────────────────────────────


class IntegrationSchema(BaseModel):
    """Minimal schema for structured-generation integration tests."""

    ok: bool


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def machine_toml(tmp_path: Path) -> Path:
    """Create a temporary machine TOML config with agent and embedding profiles."""
    config = tmp_path / "machine.toml"
    config.write_text(
        "[profiles.agent_test]\n"
        'provider = "ollama"\n'
        'model = "agent-test-model"\n'
        'base_url = "http://localhost:11434"\n'
        "temperature = 0\n"
        'keep_alive = "5m"\n'
        'role = "agent"\n'
        "\n"
        "[profiles.embedding_test]\n"
        'provider = "ollama"\n'
        'model = "embedding-test-model"\n'
        'base_url = "http://localhost:11434"\n'
        'role = "embedding"\n',
        encoding="utf-8",
    )
    return config


@pytest.fixture
def agent_profile(machine_toml: Path) -> Any:
    """Load the agent_test profile from the temporary machine config."""
    config = load_model_profiles(machine_toml)
    return config.profiles["agent_test"]


@pytest.fixture
def embedding_profile(machine_toml: Path) -> Any:
    """Load the embedding_test profile from the temporary machine config."""
    config = load_model_profiles(machine_toml)
    return config.profiles["embedding_test"]


# ═══════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthIntegration:
    """Mocked health integration through real profile loader."""

    def test_healthy(self, agent_profile: Any) -> None:
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json={"version": "0.5.0"})
            respx.get("http://localhost:11434/api/tags").respond(
                json={
                    "models": [
                        {"model": "agent-test-model", "name": "agent-test-model", "size": 12345}
                    ]
                }
            )

            provider = OllamaModelProvider(agent_profile)
            try:
                result = provider.health()
            finally:
                provider.close()

        assert result == ModelHealth(reachable=True, model_available=True)

    def test_unreachable(self, agent_profile: Any) -> None:
        with respx.mock:
            respx.get("http://localhost:11434/api/version").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

            provider = OllamaModelProvider(agent_profile)
            try:
                result = provider.health()
            finally:
                provider.close()

        assert result.reachable is False
        assert result.model_available is False


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat
# ═══════════════════════════════════════════════════════════════════════════


class TestChatIntegration:
    """Mocked plain chat integration through real profile loader."""

    def test_simple_chat(self, agent_profile: Any) -> None:
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                json={"message": {"role": "assistant", "content": "Hello!"}}
            )

            provider = OllamaModelProvider(agent_profile)
            try:
                result = provider.chat(request)
            finally:
                provider.close()

        assert isinstance(result, ChatResponse)
        assert result.message.content == "Hello!"
        assert result.message.role == MessageRole.ASSISTANT


# ═══════════════════════════════════════════════════════════════════════════
# Structured generation
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredIntegration:
    """Mocked structured generation integration through real profile loader."""

    def test_simple_structured(self, agent_profile: Any) -> None:
        request = ChatRequest(
            messages=(ChatMessage(role=MessageRole.USER, content="Return ok=true"),)
        )

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                json={"message": {"role": "assistant", "content": '{"ok": true}'}}
            )

            provider = OllamaModelProvider(agent_profile)
            try:
                result = provider.generate_structured(request, IntegrationSchema)
            finally:
                provider.close()

        assert isinstance(result, IntegrationSchema)
        assert result.ok is True


# ═══════════════════════════════════════════════════════════════════════════
# Tool-aware chat
# ═══════════════════════════════════════════════════════════════════════════


class TestToolAwareIntegration:
    """Mocked tool-aware chat integration through real profile loader."""

    def test_text_only_response(self, agent_profile: Any) -> None:
        """Model may respond with text only — no tool call required."""
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hello"),))
        tools = [
            ToolPublicDefinition(
                name="smoke_echo",
                description="Echo back the input",
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

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                json={"message": {"role": "assistant", "content": "Hi there!"}}
            )

            provider = OllamaModelProvider(agent_profile)
            try:
                result = provider.chat_with_tools(request, tools)
            finally:
                provider.close()

        assert isinstance(result, ToolAwareResponse)
        assert result.message.content == "Hi there!"
        assert result.message.role == MessageRole.ASSISTANT

    def test_tool_call_response(self, agent_profile: Any) -> None:
        """Model may respond with a tool call."""
        request = ChatRequest(
            messages=(ChatMessage(role=MessageRole.USER, content="Echo 'hello'"),)
        )
        tools = [
            ToolPublicDefinition(
                name="smoke_echo",
                description="Echo back the input",
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

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                json={
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "index": 0,
                                    "name": "smoke_echo",
                                    "arguments": {"text": "hello"},
                                },
                            }
                        ],
                    }
                }
            )

            provider = OllamaModelProvider(agent_profile)
            try:
                result = provider.chat_with_tools(request, tools)
            finally:
                provider.close()

        assert isinstance(result, ToolAwareResponse)
        assert len(result.message.tool_calls) == 1
        assert result.message.tool_calls[0].name == "smoke_echo"
        assert result.message.tool_calls[0].arguments == {"text": "hello"}


# ═══════════════════════════════════════════════════════════════════════════
# Embeddings
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingIntegration:
    """Mocked embedding integration through real profile loader."""

    def test_single_embedding(self, embedding_profile: Any) -> None:
        with respx.mock:
            respx.post("http://localhost:11434/api/embed").respond(
                json={"embeddings": [[0.1, 0.2, 0.3]]}
            )

            provider = OllamaModelProvider(embedding_profile)
            try:
                result = provider.embed(["test"])
            finally:
                provider.close()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == [0.1, 0.2, 0.3]

    def test_health_before_embed(self, embedding_profile: Any) -> None:
        """Embedding profile also supports health()."""
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json={"version": "0.5.0"})
            respx.get("http://localhost:11434/api/tags").respond(
                json={
                    "models": [
                        {
                            "model": "embedding-test-model",
                            "name": "embedding-test-model",
                            "size": 12345,
                        }
                    ]
                }
            )

            provider = OllamaModelProvider(embedding_profile)
            try:
                result = provider.health()
            finally:
                provider.close()

        assert result == ModelHealth(reachable=True, model_available=True)
