"""Tests for cross-operation tool_calls field-presence hardening (S8-06).

Covers presence-based (not truthiness-based) ``tool_calls`` rejection for
both ``chat()`` and ``generate_structured()``.

All tests use mocked HTTP (respx) — no real Ollama, no network, no Vault.
"""

from __future__ import annotations

from typing import Any

import respx
from pydantic import BaseModel

from dnd_assistant.errors import ModelError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.types import ChatMessage, ChatRequest, ChatResponse, MessageRole

# ── Test schema for structured generation ─────────────────────────────────────


class HardeningSchema(BaseModel):
    """Minimal schema for structured-generation hardening tests."""

    ok: bool


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_profile(**kw: Any) -> ModelProfile:
    return ModelProfile(
        provider=kw.get("provider", "ollama"),
        model=kw.get("model", "qwen-2.5-7b"),
        base_url=kw.get("base_url", "http://localhost:11434"),
        temperature=kw.get("temperature"),
        keep_alive=kw.get("keep_alive"),
        role=kw.get("role", ModelProfileRole.AGENT),
    )


def _simple_request() -> ChatRequest:
    return ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="Hi"),))


_MISSING = object()
"""Sentinel to distinguish \"not provided\" from explicit None."""


def _chat_body(content: str = "Hello!", tool_calls: Any = _MISSING) -> dict[str, Any]:
    """Build a plain chat response body with optional tool_calls field.

    When ``tool_calls`` is the ``_MISSING`` sentinel, the field is
    omitted entirely from the response.  When it is any other value
    (including ``None``), the field is included with that value.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not _MISSING:
        msg["tool_calls"] = tool_calls
    return {"message": msg}


def _structured_body(
    content: str = '{"ok": true}',
    tool_calls: Any = _MISSING,
) -> dict[str, Any]:
    """Build a structured response body with optional tool_calls field.

    When ``tool_calls`` is the ``_MISSING`` sentinel, the field is
    omitted entirely from the response.  When it is any other value
    (including ``None``), the field is included with that value.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not _MISSING:
        msg["tool_calls"] = tool_calls
    return {"message": msg}


# ═══════════════════════════════════════════════════════════════════════════
# Plain chat — field-presence tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPlainChatFieldPresence:
    """Verify presence-based tool_calls semantics for chat()."""

    def _do_chat(self, body: dict[str, Any]) -> ChatResponse | Exception:
        profile = _make_profile()
        request = _simple_request()

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(json=body)

            provider = OllamaModelProvider(profile)
            try:
                result = provider.chat(request)
                return result
            except Exception as exc:
                return exc
            finally:
                provider.close()

    def test_missing_tool_calls_accepted(self) -> None:
        """tool_calls field missing → valid ChatResponse."""
        result = self._do_chat(_chat_body("Hello."))
        assert isinstance(result, ChatResponse)
        assert result.message.content == "Hello."

    def test_empty_list_tool_calls_accepted(self) -> None:
        """tool_calls=[] → valid ChatResponse."""
        result = self._do_chat(_chat_body("Hello.", tool_calls=[]))
        assert isinstance(result, ChatResponse)
        assert result.message.content == "Hello."

    def test_none_tool_calls_rejected(self) -> None:
        """tool_calls=None → ModelError."""
        result = self._do_chat(_chat_body("Hello.", tool_calls=None))
        assert isinstance(result, ModelError)

    def test_empty_string_tool_calls_rejected(self) -> None:
        """tool_calls='' → ModelError."""
        result = self._do_chat(_chat_body("Hello.", tool_calls=""))
        assert isinstance(result, ModelError)

    def test_empty_object_tool_calls_rejected(self) -> None:
        """tool_calls={} → ModelError."""
        result = self._do_chat(_chat_body("Hello.", tool_calls={}))
        assert isinstance(result, ModelError)

    def test_zero_tool_calls_rejected(self) -> None:
        """tool_calls=0 → ModelError."""
        result = self._do_chat(_chat_body("Hello.", tool_calls=0))
        assert isinstance(result, ModelError)

    def test_false_tool_calls_rejected(self) -> None:
        """tool_calls=False → ModelError."""
        result = self._do_chat(_chat_body("Hello.", tool_calls=False))
        assert isinstance(result, ModelError)

    def test_true_tool_calls_rejected(self) -> None:
        """tool_calls=True → ModelError."""
        result = self._do_chat(_chat_body("Hello.", tool_calls=True))
        assert isinstance(result, ModelError)

    def test_non_empty_list_tool_calls_rejected(self) -> None:
        """tool_calls=[valid-looking call] → ModelError."""
        result = self._do_chat(
            _chat_body(
                "Let me look that up.",
                tool_calls=[{"function": {"name": "search", "arguments": {}}}],
            )
        )
        assert isinstance(result, ModelError)
        assert "tool_calls" in str(result)


# ═══════════════════════════════════════════════════════════════════════════
# Structured generation — field-presence tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuredFieldPresence:
    """Verify presence-based tool_calls semantics for generate_structured()."""

    def _do_structured(self, body: dict[str, Any]) -> HardeningSchema | Exception:
        profile = _make_profile()
        request = _simple_request()

        with respx.mock:
            respx.post("http://localhost:11434/api/chat").respond(json=body)

            provider = OllamaModelProvider(profile)
            try:
                result = provider.generate_structured(request, HardeningSchema)
                return result
            except Exception as exc:
                return exc
            finally:
                provider.close()

    def test_missing_tool_calls_accepted(self) -> None:
        """tool_calls field missing → validated schema."""
        result = self._do_structured(_structured_body())
        assert isinstance(result, HardeningSchema)
        assert result.ok is True

    def test_empty_list_tool_calls_accepted(self) -> None:
        """tool_calls=[] → validated schema."""
        result = self._do_structured(_structured_body(tool_calls=[]))
        assert isinstance(result, HardeningSchema)
        assert result.ok is True

    def test_none_tool_calls_rejected(self) -> None:
        """tool_calls=None → ModelError."""
        result = self._do_structured(_structured_body(tool_calls=None))
        assert isinstance(result, ModelError)

    def test_empty_string_tool_calls_rejected(self) -> None:
        """tool_calls='' → ModelError."""
        result = self._do_structured(_structured_body(tool_calls=""))
        assert isinstance(result, ModelError)

    def test_empty_object_tool_calls_rejected(self) -> None:
        """tool_calls={} → ModelError."""
        result = self._do_structured(_structured_body(tool_calls={}))
        assert isinstance(result, ModelError)

    def test_zero_tool_calls_rejected(self) -> None:
        """tool_calls=0 → ModelError."""
        result = self._do_structured(_structured_body(tool_calls=0))
        assert isinstance(result, ModelError)

    def test_false_tool_calls_rejected(self) -> None:
        """tool_calls=False → ModelError."""
        result = self._do_structured(_structured_body(tool_calls=False))
        assert isinstance(result, ModelError)

    def test_true_tool_calls_rejected(self) -> None:
        """tool_calls=True → ModelError."""
        result = self._do_structured(_structured_body(tool_calls=True))
        assert isinstance(result, ModelError)

    def test_non_empty_list_tool_calls_rejected(self) -> None:
        """tool_calls=[valid-looking call] → ModelError."""
        result = self._do_structured(
            _structured_body(
                content='{"ok": true}',
                tool_calls=[{"function": {"name": "search", "arguments": {}}}],
            )
        )
        assert isinstance(result, ModelError)
        assert "tool_calls" in str(result)
