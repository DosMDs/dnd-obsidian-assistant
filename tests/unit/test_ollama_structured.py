"""Tests for OllamaModelProvider.generate_structured() (S8-03).

Covers:
    * Schema-input validation (reject non-Pydantic types before HTTP).
    * Exact JSON Schema transmission (format == schema.model_json_schema()).
    * Request mapping (model, stream, temperature, keep_alive, no tools, no think).
    * No prompt mutation (messages unchanged semantically).
    * Tool-history rejection (no HTTP call).
    * Successful structured output (simple, nested, caller validators, thinking ignored).
    * Invalid structured content (JSON, missing fields, wrong types, extra fields).
    * Malformed provider responses (missing message, wrong role, tool_calls).
    * HTTP failure mapping (connection, timeout, 4xx, 5xx, non-JSON, invalid bytes).

All tests use mocked HTTP (respx) — no real Ollama, no network, no Vault.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, field_validator

from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolCall,
)

# ── Test schemas ─────────────────────────────────────────────────────────────


class SimpleSchema(BaseModel):
    """Simple Pydantic schema for structured output tests."""

    name: str
    level: int


class NestedInner(BaseModel):
    x: int
    y: int


class NestedSchema(BaseModel):
    label: str
    inner: NestedInner


class StrictSchema(BaseModel):
    """Schema with extra=forbid and a caller-defined validator."""

    name: str
    value: int

    model_config = {"extra": "forbid"}

    @field_validator("value")
    @classmethod
    def _value_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("value must be positive")
        return v


class StrictNestedSchema(BaseModel):
    """Nested schema with strict mode for wrong-type testing."""

    name: str
    count: int

    model_config = {"strict": True}


# ── Helpers ──────────────────────────────────────────────────────────────────


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


def _structured_response_body(content: str) -> dict[str, Any]:
    """Build a successful Ollama /api/chat response with structured content."""
    return {
        "message": {
            "role": "assistant",
            "content": content,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# Schema-input validation
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemaInputValidation:
    """Verify generate_structured() rejects invalid schema arguments before HTTP."""

    def _assert_rejected_before_http(self, schema: Any) -> None:
        """Assert that the schema is rejected and /api/chat is not called."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            chat_route = respx.post("http://localhost:11434/api/chat").respond(
                json=_structured_response_body('{"name":"Aria","level":5}')
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ValidationError):
                provider.generate_structured(request, schema)
            provider.close()

            assert not chat_route.called, "/api/chat must not be called for invalid schema"

    def test_pydantic_model_class_accepted(self) -> None:
        """A valid Pydantic BaseModel subclass is accepted."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                json=_structured_response_body('{"name":"Aria","level":5}')
            )

            provider = OllamaModelProvider(profile)
            result = provider.generate_structured(request, SimpleSchema)
            provider.close()

        assert isinstance(result, SimpleSchema)

    def test_int_rejected(self) -> None:
        self._assert_rejected_before_http(int)

    def test_dict_rejected(self) -> None:
        self._assert_rejected_before_http(dict)

    def test_ordinary_class_rejected(self) -> None:
        class NotPydantic:
            pass

        self._assert_rejected_before_http(NotPydantic)

    def test_pydantic_instance_rejected(self) -> None:
        instance = SimpleSchema(name="Aria", level=5)
        self._assert_rejected_before_http(instance)


# ═══════════════════════════════════════════════════════════════════════════
# Structured request mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredRequestMapping:
    """Verify exact request payload mapping for structured generation."""

    def _generate_and_capture(
        self, request: ChatRequest, schema: type[BaseModel]
    ) -> dict[str, Any]:
        """Send a structured request and return the captured payload."""
        profile = _make_profile()
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_structured_response_body('{"name":"Aria","level":5}'))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.generate_structured(request, schema)
            provider.close()

        return captured["payload"]

    def test_format_equals_schema_json_schema(self) -> None:
        payload = self._generate_and_capture(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Extract"),)),
            SimpleSchema,
        )
        assert payload["format"] == SimpleSchema.model_json_schema()

    def test_configured_model_used(self) -> None:
        profile = _make_profile(model="custom-model")
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_structured_response_body('{"name":"Aria","level":5}'))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.generate_structured(
                ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
                SimpleSchema,
            )
            provider.close()

        assert captured["payload"]["model"] == "custom-model"

    def test_stream_is_false(self) -> None:
        payload = self._generate_and_capture(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
            SimpleSchema,
        )
        assert payload["stream"] is False

    def test_temperature_in_options(self) -> None:
        profile = _make_profile(temperature=0.7)
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_structured_response_body('{"name":"Aria","level":5}'))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.generate_structured(
                ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
                SimpleSchema,
            )
            provider.close()

        assert captured["payload"]["options"]["temperature"] == 0.7

    def test_temperature_omitted_when_none(self) -> None:
        payload = self._generate_and_capture(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
            SimpleSchema,
        )
        assert "options" not in payload

    def test_keep_alive_top_level(self) -> None:
        profile = _make_profile(keep_alive="30m")
        captured: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_structured_response_body('{"name":"Aria","level":5}'))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").mock(side_effect=capture)

            provider = OllamaModelProvider(profile)
            provider.generate_structured(
                ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
                SimpleSchema,
            )
            provider.close()

        assert captured["payload"]["keep_alive"] == "30m"

    def test_keep_alive_omitted_when_none(self) -> None:
        payload = self._generate_and_capture(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
            SimpleSchema,
        )
        assert "keep_alive" not in payload

    def test_no_tools_in_payload(self) -> None:
        payload = self._generate_and_capture(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
            SimpleSchema,
        )
        assert "tools" not in payload

    def test_no_think_in_payload(self) -> None:
        payload = self._generate_and_capture(
            ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),)),
            SimpleSchema,
        )
        assert "think" not in payload

    def test_messages_unchanged_no_prompt_mutation(self) -> None:
        """No hidden schema/system/user message is injected into messages."""
        payload = self._generate_and_capture(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.SYSTEM, content="Extract data"),
                    ChatMessage(role=MessageRole.USER, content="Aria is level 5"),
                )
            ),
            SimpleSchema,
        )
        assert payload["messages"] == [
            {"role": "system", "content": "Extract data"},
            {"role": "user", "content": "Aria is level 5"},
        ]


# ═══════════════════════════════════════════════════════════════════════════
# Tool-history rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredToolHistoryRejection:
    """Verify generate_structured() rejects tool-bearing history without HTTP."""

    def _assert_rejected_before_http(self, request: ChatRequest) -> None:
        profile = _make_profile()

        with respx.mock:
            chat_route = respx.post("http://localhost:11434/api/chat").respond(
                json=_structured_response_body('{"name":"Aria","level":5}')
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError):
                provider.generate_structured(request, SimpleSchema)
            provider.close()

            assert not chat_route.called, "/api/chat must not be called"

    def test_tool_role_message_rejected(self) -> None:
        self._assert_rejected_before_http(
            ChatRequest(
                messages=(
                    ChatMessage(role=MessageRole.USER, content="Check weather"),
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content='{"temp": 22}',
                        tool_name="get_weather",
                    ),
                )
            )
        )

    def test_assistant_with_tool_calls_rejected(self) -> None:
        self._assert_rejected_before_http(
            ChatRequest(
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
        )


# ═══════════════════════════════════════════════════════════════════════════
# Successful structured output
# ═══════════════════════════════════════════════════════════════════════════


class TestSuccessfulStructuredOutput:
    """Verify successful structured output returns the exact requested type."""

    def _do_structured(
        self,
        schema: type[BaseModel],
        content: str,
        extra_fields: dict[str, Any] | None = None,
    ) -> BaseModel:
        """Execute a structured generation and return the result."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Extract"),))

        body: dict[str, Any] = {
            "message": {
                "role": "assistant",
                "content": content,
            }
        }
        if extra_fields:
            body.update(extra_fields)

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(json=body)

            provider = OllamaModelProvider(profile)
            result = provider.generate_structured(request, schema)
            provider.close()

        return result

    def test_simple_object(self) -> None:
        result = self._do_structured(SimpleSchema, '{"name":"Aria","level":5}')
        assert isinstance(result, SimpleSchema)
        assert result.name == "Aria"
        assert result.level == 5

    def test_nested_object(self) -> None:
        result = self._do_structured(
            NestedSchema,
            '{"label":"point","inner":{"x":10,"y":20}}',
        )
        assert isinstance(result, NestedSchema)
        assert result.label == "point"
        assert result.inner.x == 10
        assert result.inner.y == 20

    def test_caller_validator_enforced(self) -> None:
        """Caller-defined Pydantic validators are actually enforced."""
        result = self._do_structured(StrictSchema, '{"name":"test","value":42}')
        assert isinstance(result, StrictSchema)
        assert result.value == 42

    def test_provider_metadata_ignored(self) -> None:
        """Additional Ollama response metadata does not affect the result."""
        result = self._do_structured(
            SimpleSchema,
            '{"name":"Aria","level":5}',
            extra_fields={
                "model": "qwen-2.5-7b",
                "created_at": "2026-09-03T00:00:00Z",
                "total_duration": 123456789,
            },
        )
        assert isinstance(result, SimpleSchema)
        assert result.name == "Aria"

    def test_thinking_ignored(self) -> None:
        """Provider-specific message.thinking does not affect structured validation."""
        result = self._do_structured(
            SimpleSchema,
            '{"name":"Aria","level":5}',
            extra_fields={
                "message": {
                    "role": "assistant",
                    "content": '{"name":"Aria","level":5}',
                    "thinking": "I should extract the fields...",
                }
            },
        )
        assert isinstance(result, SimpleSchema)
        assert result.name == "Aria"
        assert result.level == 5


# ═══════════════════════════════════════════════════════════════════════════
# Invalid structured content
# ═══════════════════════════════════════════════════════════════════════════


class TestInvalidStructuredContent:
    """Verify invalid structured content raises ModelError."""

    def _do_failing_structured(
        self,
        content: str,
        schema: type[BaseModel] | None = None,
    ) -> Exception:
        """Execute a structured generation that should fail."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Extract"),))
        use_schema = schema or SimpleSchema

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                json=_structured_response_body(content)
            )

            provider = OllamaModelProvider(profile)
            try:
                provider.generate_structured(request, use_schema)
                raise AssertionError("Expected ModelError")
            except Exception as exc:
                return exc
            finally:
                provider.close()

    def test_invalid_json_content(self) -> None:
        exc = self._do_failing_structured("not valid json at all")
        assert isinstance(exc, ModelError)

    def test_missing_required_field(self) -> None:
        exc = self._do_failing_structured(
            '{"name":"Aria"}',  # missing 'level'
        )
        assert isinstance(exc, ModelError)

    def test_wrong_field_type(self) -> None:
        exc = self._do_failing_structured(
            '{"name":"Aria","level":"five"}',
            StrictNestedSchema,
        )
        assert isinstance(exc, ModelError)

    def test_nested_schema_failure(self) -> None:
        exc = self._do_failing_structured(
            '{"label":"point","inner":{"x":"ten","y":20}}',
            NestedSchema,
        )
        assert isinstance(exc, ModelError)

    def test_caller_validator_failure(self) -> None:
        exc = self._do_failing_structured(
            '{"name":"test","value":-1}',
            StrictSchema,
        )
        assert isinstance(exc, ModelError)

    def test_extra_field_forbidden(self) -> None:
        """Schema with extra='forbid' rejects extra fields."""
        exc = self._do_failing_structured(
            '{"name":"test","value":42,"extra":"forbidden"}',
            StrictSchema,
        )
        assert isinstance(exc, ModelError)

    def test_validation_error_preserves_cause(self) -> None:
        """Representative validation failures preserve Pydantic exception as __cause__."""
        exc = self._do_failing_structured(
            '{"name":"Aria"}',  # missing 'level'
        )
        assert isinstance(exc, ModelError)
        assert exc.__cause__ is not None


# ═══════════════════════════════════════════════════════════════════════════
# Malformed provider responses
# ═══════════════════════════════════════════════════════════════════════════


class TestMalformedProviderResponse:
    """Verify malformed provider responses raise ModelError."""

    def _do_failing_structured(self, response_body: Any, status: int = 200) -> Exception:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            if isinstance(response_body, dict):
                respx.post("http://localhost:11434/api/chat").respond(
                    status_code=status, json=response_body
                )
            else:
                respx.post("http://localhost:11434/api/chat").respond(
                    status_code=status,
                    content=json.dumps(response_body).encode(),
                )

            provider = OllamaModelProvider(profile)
            try:
                provider.generate_structured(request, SimpleSchema)
                raise AssertionError("Expected ModelError")
            except Exception as exc:
                return exc
            finally:
                provider.close()

    def test_missing_message(self) -> None:
        exc = self._do_failing_structured({"not_message": {}})
        assert isinstance(exc, ModelError)

    def test_message_not_an_object(self) -> None:
        exc = self._do_failing_structured({"message": "not an object"})
        assert isinstance(exc, ModelError)

    def test_wrong_role(self) -> None:
        exc = self._do_failing_structured({"message": {"role": "user", "content": "hello"}})
        assert isinstance(exc, ModelError)

    def test_missing_content(self) -> None:
        exc = self._do_failing_structured({"message": {"role": "assistant"}})
        assert isinstance(exc, ModelError)

    def test_non_string_content(self) -> None:
        exc = self._do_failing_structured({"message": {"role": "assistant", "content": 123}})
        assert isinstance(exc, ModelError)

    def test_unexpected_tool_calls(self) -> None:
        exc = self._do_failing_structured(
            {
                "message": {
                    "role": "assistant",
                    "content": "Let me look that up.",
                    "tool_calls": [{"function": {"name": "search", "arguments": {}}}],
                }
            }
        )
        assert isinstance(exc, ModelError)
        assert "tool_calls" in str(exc)

    def test_non_json_outer_response(self) -> None:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(content=b"not json at all")

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError, match="non-JSON"):
                provider.generate_structured(request, SimpleSchema)
            provider.close()

    def test_invalid_bytes_outer_response(self) -> None:
        """Invalid-byte HTTP 200 must raise ModelError, not UnicodeDecodeError."""
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(
                content=b"\xff\xfe\x00\x01invalid bytes"
            )

            provider = OllamaModelProvider(profile)
            with pytest.raises(ModelError) as exc_info:
                provider.generate_structured(request, SimpleSchema)
            provider.close()

        assert not isinstance(exc_info.value, UnicodeDecodeError)
        assert exc_info.value.__cause__ is not None


# ═══════════════════════════════════════════════════════════════════════════
# HTTP failure tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredHttpFailures:
    """Verify HTTP failures surface as ModelError."""

    def _do_failing_structured(self, mock_setup: Any) -> Exception:
        profile = _make_profile()
        request = ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))

        with respx.mock:
            mock_setup()
            provider = OllamaModelProvider(profile)
            try:
                provider.generate_structured(request, SimpleSchema)
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

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "connection refused" in str(exc).lower()

    def test_timeout(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)

    def test_http_400(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(400)

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "400" in str(exc)

    def test_http_404(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(404)

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "404" in str(exc)

    def test_http_500(self) -> None:
        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(500)

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "500" in str(exc)

    def test_ollama_error_body_extracted(self) -> None:
        """Verify diagnostic from Ollama JSON error body."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=404,
                json={"error": "model not found"},
            )

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "model not found" in str(exc)
        assert "404" in str(exc)

    def test_non_json_error_body(self) -> None:
        """Verify non-JSON error body does not crash."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=502,
                content=b"<html>Bad Gateway</html>",
            )

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "502" in str(exc)

    def test_invalid_bytes_error_body(self) -> None:
        """Invalid-byte HTTP error body must raise ModelError with HTTP status."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").respond(
                status_code=502,
                content=b"\xff\xfe\x00\x01invalid bytes",
            )

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert "502" in str(exc)
        assert not isinstance(exc, UnicodeDecodeError)

    def test_connect_error_cause(self) -> None:
        """Connection failure preserves underlying httpx exception."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert exc.__cause__ is not None
        assert isinstance(exc.__cause__, httpx.ConnectError)

    def test_timeout_cause(self) -> None:
        """Timeout preserves underlying httpx exception."""

        def setup() -> None:
            respx.post("http://localhost:11434/api/chat").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

        exc = self._do_failing_structured(setup)
        assert isinstance(exc, ModelError)
        assert exc.__cause__ is not None
        assert isinstance(exc.__cause__, httpx.TimeoutException)
