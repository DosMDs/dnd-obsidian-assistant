"""Tests for OllamaModelProvider (S8-02).

Covers:
    * Constructor/profile validation.
    * Endpoint construction (path-prefix preservation).
    * Health — reachability, model availability, failure modes.
    * Plain chat — request mapping, response parsing, error mapping.
    * Tool-history safety (rejection without HTTP call).
    * HTTP failure mapping to ModelError.

All tests use mocked HTTP (respx) — no real Ollama, no network, no Vault.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ModelHealth,
    ToolCall,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_profile(
    *,
    provider: str = "ollama",
    model: str = "qwen-2.5-7b",
    base_url: str = "http://localhost:11434",
    temperature: float | None = None,
    keep_alive: str | None = None,
    role: ModelProfileRole = ModelProfileRole.AGENT,
) -> ModelProfile:
    """Create a ModelProfile with sensible defaults for testing."""
    return ModelProfile(
        provider=provider,
        model=model,
        base_url=base_url,
        temperature=temperature,
        keep_alive=keep_alive,
        role=role,
    )


def _version_response() -> dict[str, Any]:
    return {"version": "0.5.0"}


def _tags_response(*models: str) -> dict[str, Any]:
    """Build a /api/tags response body with the given model names."""
    return {"models": [{"model": name, "name": name, "size": 12345} for name in models]}


def _chat_response_body(content: str = "Hello!") -> dict[str, Any]:
    return {
        "message": {
            "role": "assistant",
            "content": content,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# Constructor / profile validation
# ═══════════════════════════════════════════════════════════════════════════


class TestConstructor:
    """OllamaModelProvider constructor and profile validation."""

    def test_valid_ollama_profile_accepted(self) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)
        assert provider._profile is profile
        provider.close()

    def test_arbitrary_model_name_preserved(self) -> None:
        profile = _make_profile(model="some-custom-model:v2")
        provider = OllamaModelProvider(profile)
        assert provider._profile.model == "some-custom-model:v2"
        provider.close()

    def test_localhost_base_url(self) -> None:
        profile = _make_profile(base_url="http://localhost:11434")
        provider = OllamaModelProvider(profile)
        assert provider._profile.base_url == "http://localhost:11434"
        provider.close()

    def test_lan_base_url(self) -> None:
        profile = _make_profile(base_url="http://192.168.1.50:11434")
        provider = OllamaModelProvider(profile)
        assert provider._profile.base_url == "http://192.168.1.50:11434"
        provider.close()

    def test_path_prefixed_base_url(self) -> None:
        profile = _make_profile(base_url="https://provider.example/ollama")
        provider = OllamaModelProvider(profile)
        assert provider._profile.base_url == "https://provider.example/ollama"
        provider.close()

    def test_non_ollama_provider_rejected(self) -> None:
        profile = _make_profile(provider="some-other-provider")
        with pytest.raises(ValidationError, match="provider='some-other-provider'"):
            OllamaModelProvider(profile)

    def test_no_hardcoded_model(self) -> None:
        """No default model should be hardcoded — the profile is the source."""
        profile = _make_profile(model="custom-model")
        provider = OllamaModelProvider(profile)
        assert provider._profile.model == "custom-model"
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint construction
# ═══════════════════════════════════════════════════════════════════════════


class TestEndpointConstruction:
    """Verify path-preserving URL construction."""

    def test_path_prefix_preserved(self) -> None:
        profile = _make_profile(base_url="https://provider.example/ollama")
        with respx.mock:
            route = respx.get("https://provider.example/ollama/api/version").respond(
                json=_version_response()
            )
            respx.get("https://provider.example/ollama/api/tags").respond(
                json=_tags_response("qwen-2.5-7b")
            )

            provider = OllamaModelProvider(profile)
            provider.health()
            provider.close()

            assert route.called

    def test_simple_base_url(self) -> None:
        profile = _make_profile(base_url="http://localhost:11434")
        with respx.mock:
            route = respx.get("http://localhost:11434/api/version").respond(
                json=_version_response()
            )
            respx.get("http://localhost:11434/api/tags").respond(json=_tags_response("qwen-2.5-7b"))

            provider = OllamaModelProvider(profile)
            provider.health()
            provider.close()

            assert route.called

    def test_chat_endpoint_path_prefix(self) -> None:
        profile = _make_profile(base_url="https://provider.example/ollama")
        with respx.mock:
            respx.get("https://provider.example/ollama/api/version").respond(
                json=_version_response()
            )
            respx.get("https://provider.example/ollama/api/tags").respond(
                json=_tags_response("qwen-2.5-7b")
            )
            chat_route = respx.post("https://provider.example/ollama/api/chat").respond(
                json=_chat_response_body()
            )

            provider = OllamaModelProvider(profile)
            request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
            provider.chat(request)
            provider.close()

            assert chat_route.called


# ═══════════════════════════════════════════════════════════════════════════
# Health tests
# ═══════════════════════════════════════════════════════════════════════════


class TestHealth:
    """OllamaModelProvider.health() behavior."""

    def test_healthy(self) -> None:
        """Both reachable and model available."""
        profile = _make_profile(model="qwen-2.5-7b")
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(json=_tags_response("qwen-2.5-7b"))

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(reachable=True, model_available=True)

    def test_model_missing(self) -> None:
        """Ollama reachable but configured model absent."""
        profile = _make_profile(model="missing-model")
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(
                json=_tags_response("qwen-2.5-7b", "llama3.2")
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="configured model not installed",
        )

    def test_exact_model_field_match(self) -> None:
        """Match against returned ``model`` field."""
        profile = _make_profile(model="llama3.2:3b")
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(
                json={"models": [{"model": "llama3.2:3b", "name": "llama3.2", "size": 12345}]}
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(reachable=True, model_available=True)

    def test_exact_name_field_match(self) -> None:
        """Match against returned ``name`` field."""
        profile = _make_profile(model="llama3.2")
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(
                json={"models": [{"model": "llama3.2:3b", "name": "llama3.2", "size": 12345}]}
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(reachable=True, model_available=True)

    def test_connection_failure_on_version(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result.reachable is False
        assert result.model_available is False

    def test_timeout_on_version(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result.reachable is False
        assert result.model_available is False

    def test_http_failure_from_version(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(500)

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="HTTP 500 from /api/version",
        )

    def test_malformed_version_response(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json={"unexpected": "data"})

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="invalid version response: missing or unusable 'version' field",
        )

    @pytest.mark.parametrize(
        ("version_value", "label"),
        [
            (None, "null"),
            ("", "empty string"),
            ("   ", "whitespace-only"),
            (123, "integer"),
        ],
    )
    def test_unusable_version_rejected(self, version_value: Any, label: str) -> None:
        """version: unusable values must be rejected and /api/tags not called."""
        profile = _make_profile()
        tags_called = False

        def fail_on_tags(request: httpx.Request) -> httpx.Response:
            nonlocal tags_called
            tags_called = True
            return httpx.Response(200, json=_tags_response("qwen-2.5-7b"))

        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json={"version": version_value})
            respx.get("http://localhost:11434/api/tags").mock(side_effect=fail_on_tags)

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="invalid version response: missing or unusable 'version' field",
        )
        assert not tags_called, f"/api/tags must not be called after version={label}"

    def test_non_json_version_response(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(content=b"not json")

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="invalid version response: non-JSON body",
        )

    def test_tags_request_failure_after_version_success(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").mock(
                side_effect=httpx.ConnectError("tags connection failed")
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result.reachable is True
        assert result.model_available is False

    def test_non_success_tags_response(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(500)

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="HTTP 500 from /api/tags",
        )

    def test_malformed_tags_json(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(content=b"not json")

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="invalid /api/tags response: non-JSON body",
        )

    def test_malformed_models_structure(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(json={"models": "not a list"})

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="invalid /api/tags response: 'models' is not a list",
        )

    def test_no_fuzzy_matching(self) -> None:
        """A similar-but-different model name must remain unavailable."""
        profile = _make_profile(model="qwen-2.5-7b")
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(
                json=_tags_response("qwen-2.5-7b-instruct")
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="configured model not installed",
        )

    def test_tags_missing_models_field(self) -> None:
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(json={"not_models": []})

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result == ModelHealth(
            reachable=True,
            model_available=False,
            detail="invalid /api/tags response: missing 'models' field",
        )

    def test_invalid_bytes_version_response(self) -> None:
        """Invalid-byte /api/version body must return ModelHealth, not raise."""
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(
                content=b"\xff\xfe\x00\x01invalid bytes"
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result.reachable is True
        assert result.model_available is False

    def test_invalid_bytes_tags_response(self) -> None:
        """Invalid-byte /api/tags body after valid version must return ModelHealth, not raise."""
        profile = _make_profile()
        with respx.mock:
            respx.get("http://localhost:11434/api/version").respond(json=_version_response())
            respx.get("http://localhost:11434/api/tags").respond(
                content=b"\xff\xfe\x00\x01invalid bytes"
            )

            provider = OllamaModelProvider(profile)
            result = provider.health()
            provider.close()

        assert result.reachable is True
        assert result.model_available is False


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat request tests
# ═══════════════════════════════════════════════════════════════════════════


class TestChatRequest:
    """Verify exact request mapping for plain chat."""

    def _chat_and_get_payload(self, request: ChatRequest) -> dict[str, Any]:
        """Send a chat request and return the captured request payload."""
        profile = _make_profile()
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_response_body())

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.chat(request)
            provider.close()

        return captured["payload"]

    def test_single_user_message(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hello"),))
        )
        assert payload["messages"] == [{"role": "user", "content": "Hello"}]

    def test_system_and_user_history(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.SYSTEM, content="Be helpful"),
                    ChatMessage(role=MessageRole.USER, content="Hi"),
                )
            )
        )
        assert payload["messages"] == [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hi"},
        ]

    def test_prior_assistant_text_history(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="What is 2+2?"),
                    ChatMessage(role=MessageRole.ASSISTANT, content="4"),
                    ChatMessage(role=MessageRole.USER, content="Thanks"),
                )
            )
        )
        assert payload["messages"] == [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "Thanks"},
        ]

    def test_configured_model_used(self) -> None:
        profile = _make_profile(model="custom-model")
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_response_body())

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.chat(ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)))
            provider.close()

        assert captured["payload"]["model"] == "custom-model"

    def test_stream_is_false(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
        )
        assert payload["stream"] is False

    def test_temperature_in_options(self) -> None:
        profile = _make_profile(temperature=0.7)
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_response_body())

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.chat(ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)))
            provider.close()

        assert captured["payload"]["options"]["temperature"] == 0.7

    def test_temperature_omitted_when_none(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
        )
        assert "options" not in payload

    def test_keep_alive_top_level(self) -> None:
        profile = _make_profile(keep_alive="30m")
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_chat_response_body())

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.chat(ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)))
            provider.close()

        assert captured["payload"]["keep_alive"] == "30m"

    def test_keep_alive_omitted_when_none(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
        )
        assert "keep_alive" not in payload

    def test_no_tools_in_payload(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
        )
        assert "tools" not in payload

    def test_no_format_in_payload(self) -> None:
        payload = self._chat_and_get_payload(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))
        )
        assert "format" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat tool-history safety
# ═══════════════════════════════════════════════════════════════════════════


class TestChatToolHistoryRejection:
    """Verify chat() rejects tool-bearing history without making HTTP calls."""

    def test_tool_role_message_rejected(self) -> None:
        profile = _make_profile()
        request = ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.USER, content="Check weather"),
                ChatMessage(
                    role=MessageRole.TOOL,
                    content='{"temp": 22}',
                    tool_name="get_weather",
                ),
            )
        )

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(json=_chat_response_body())

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError, match="TOOL-role"):
                provider.chat(request)
            provider.close()

    def test_assistant_with_tool_calls_rejected(self) -> None:
        profile = _make_profile()
        request = ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.USER, content="Roll a die"),
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content="I'll roll a d20",
                    tool_calls=(
                        ToolCall(
                            name="roll_dice",
                            arguments={"sides": 20},
                            call_id="call_1",
                        ),
                    ),
                ),
            )
        )

        with respx.mock:
            chat_route = respx.post("http://localhost:11434/api/chat").respond(
                json=_chat_response_body()
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError, match="tool_calls"):
                provider.chat(request)
            provider.close()

            # Verify no HTTP call was made
            assert not chat_route.called


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat response tests
# ═══════════════════════════════════════════════════════════════════════════


class TestChatResponse:
    """Verify plain chat response parsing."""

    def _do_chat(self, response_body: Any, status: int = 200) -> Any:
        """Execute a chat and return the result or exception."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=status,
                json=response_body if isinstance(response_body, dict) else None,
                content=json.dumps(response_body).encode()
                if not isinstance(response_body, dict)
                else None,
            )

            provider = OllamaModelProvider(profile)
            try:
                result = provider.chat(request)
                return result
            except Exception as exc:
                return exc
            finally:
                provider.close()

    def test_valid_response(self) -> None:
        result = self._do_chat(_chat_response_body("Hello."))
        assert isinstance(result, ChatResponse)
        assert result.message.content == "Hello."
        assert result.message.role == MessageRole.ASSISTANT

    def test_provider_metadata_ignored(self) -> None:
        """Additional Ollama response metadata must not widen ChatResponse."""
        body = {
            "model": "qwen-2.5-7b",
            "created_at": "2026-09-03T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": "Hello.",
            },
            "total_duration": 123456789,
            "load_duration": 12345,
            "prompt_eval_count": 42,
            "eval_count": 17,
        }
        result = self._do_chat(body)
        assert isinstance(result, ChatResponse)
        assert result.message.content == "Hello."

    def test_thinking_ignored(self) -> None:
        """Provider-specific message.thinking must not be copied into content."""
        body = {
            "message": {
                "role": "assistant",
                "content": "Final answer.",
                "thinking": "I should think step by step...",
            }
        }
        result = self._do_chat(body)
        assert isinstance(result, ChatResponse)
        assert result.message.content == "Final answer."

    def test_unexpected_tool_calls_raises_error(self) -> None:
        body = {
            "message": {
                "role": "assistant",
                "content": "Let me look that up.",
                "tool_calls": [{"function": {"name": "search", "arguments": {}}}],
            }
        }
        result = self._do_chat(body)
        assert isinstance(result, ModelError)
        assert "tool_calls" in str(result)

    def test_wrong_role_raises_error(self) -> None:
        body = {
            "message": {
                "role": "user",
                "content": "Hello",
            }
        }
        result = self._do_chat(body)
        assert isinstance(result, ModelError)
        assert "role" in str(result)

    def test_missing_message_raises_error(self) -> None:
        body = {"not_message": {}}
        result = self._do_chat(body)
        assert isinstance(result, ModelError)
        assert "message" in str(result)

    def test_malformed_message_raises_error(self) -> None:
        body = {"message": "not an object"}
        result = self._do_chat(body)
        assert isinstance(result, ModelError)
        assert "message" in str(result)

    def test_invalid_empty_content_raises_error(self) -> None:
        """Empty content is invalid for ASSISTANT messages."""
        body = {
            "message": {
                "role": "assistant",
                "content": "",
            }
        }
        result = self._do_chat(body)
        assert isinstance(result, ModelError)

    def test_non_json_response_raises_error(self) -> None:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(content=b"not json at all")

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError, match="non-JSON"):
                provider.chat(request)
            provider.close()

    def test_invalid_bytes_chat_response_raises_model_error(self) -> None:
        """Invalid-byte HTTP 200 /api/chat must raise ModelError, not UnicodeDecodeError."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                content=b"\xff\xfe\x00\x01invalid bytes"
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError) as exc_info:
                provider.chat(request)
            provider.close()

        assert not isinstance(exc_info.value, UnicodeDecodeError)
        assert exc_info.value.__cause__ is not None


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat HTTP failure tests
# ═══════════════════════════════════════════════════════════════════════════


class TestChatHttpFailures:
    """Verify HTTP failures surface as ModelError."""

    def _do_failing_chat(self, mock_setup: Any) -> Exception:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            mock_setup()
            provider = OllamaModelProvider(profile)
            try:
                provider.chat(request)
                raise AssertionError("Expected ModelError")
            except Exception as exc:
                return exc
            finally:
                provider.close()

    def test_connection_error(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "connection refused" in str(exc).lower() or "connection refused" in str(exc)

    def test_timeout(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)

    def test_http_400(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(400)

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "400" in str(exc)

    def test_http_404(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(404)

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "404" in str(exc)

    def test_http_500(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(500)

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "500" in str(exc)

    def test_ollama_error_body_extracted(self) -> None:
        """Verify diagnostic from Ollama JSON error body."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=404,
                json={"error": "model not found"},
            )

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "model not found" in str(exc)
        assert "404" in str(exc)

    def test_non_json_error_body(self) -> None:
        """Verify non-JSON/HTML error body does not crash."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=502,
                content=b"<html>Bad Gateway</html>",
            )

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "502" in str(exc)

    def test_invalid_bytes_error_body(self) -> None:
        """Invalid-byte HTTP error body must raise ModelError with HTTP status."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=502,
                content=b"\xff\xfe\x00\x01invalid bytes",
            )

        exc = self._do_failing_chat(setup)
        assert isinstance(exc, ModelError)
        assert "502" in str(exc)
        assert not isinstance(exc, UnicodeDecodeError)


# ═══════════════════════════════════════════════════════════════════════════
# Error cause chain tests
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorCause:
    """Verify representative failures preserve the underlying cause."""

    def test_connect_error_cause(self) -> None:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError) as exc_info:
                provider.chat(request)
            provider.close()

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, httpx.ConnectError)

    def test_timeout_cause(self) -> None:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError) as exc_info:
                provider.chat(request)
            provider.close()

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)
