"""Ollama-specific ModelGateway provider implementation.

This module implements the ``ModelGateway`` protocol for Ollama's native
HTTP API.  It is intentionally a partial implementation — S8-02 owns only:

    * ``chat()`` — plain (non-tool) multi-turn conversation.
    * ``health()`` — Ollama reachability and configured-model availability.

Later tasks (S8-03, S8-04, S8-05) will add ``generate_structured()``,
``chat_with_tools()``, and ``embed()`` respectively.

Architectural boundary
─────────────────────
This module imports httpx, the provider-neutral DTOs and the ModelProfile
schema.  It must not import from storage, retrieval, application, CLI,
domain, or tools.

Provider-specific DTOs and Ollama JSON shapes live here — not in
``models/types.py`` or ``models/gateway.py``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.profiles import ModelProfile
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageRole,
    ModelHealth,
)

# ── Constants ──────────────────────────────────────────────────────────────

_OLLAMA_PROVIDER = "ollama"
"""The only ``provider`` value accepted by ``OllamaModelProvider``."""

# ── Provider implementation ───────────────────────────────────────────────


class OllamaModelProvider:
    """Ollama-specific ModelGateway provider.

    Configured from a ``ModelProfile`` whose ``provider`` must be
    ``"ollama"``.

    This is intentionally a partial implementation — only ``chat()``
    and ``health()`` are implemented in S8-02.

    HTTP client ownership
    ─────────────────────
    Each ``OllamaModelProvider`` owns a synchronous ``httpx.Client``
    with an explicit ``close()`` method.  The client is created on
    construction and must be closed when the provider is no longer
    needed via an explicit ``.close()`` call.
    """

    def __init__(self, profile: ModelProfile) -> None:
        if profile.provider != _OLLAMA_PROVIDER:
            raise ValidationError(
                f"OllamaModelProvider requires provider='{_OLLAMA_PROVIDER}', "
                f"got provider={profile.provider!r}"
            )

        self._profile = profile
        self._client = httpx.Client()

    def close(self) -> None:
        """Close the underlying HTTP client, releasing any resources."""
        self._client.close()

    # ── Health ─────────────────────────────────────────────────────────

    def health(self) -> ModelHealth:
        """Check Ollama reachability and configured-model availability.

        Returns:
            A ``ModelHealth`` instance.  Normal unreachable or
            model-unavailable states are represented by the result
            fields — this method does not raise for those conditions.
        """
        # Step 1 — Ollama reachability via /api/version
        try:
            version_resp = self._client.get(self._url("/api/version"))
        except httpx.RequestError as exc:
            return ModelHealth(
                reachable=False,
                model_available=False,
                detail=_bounded_detail(str(exc)),
            )

        if not version_resp.is_success:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail=f"HTTP {version_resp.status_code} from /api/version",
            )

        try:
            version_data = version_resp.json()
        except ValueError:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail="invalid version response: non-JSON body",
            )

        version_value = _extract_version(version_data)
        if version_value is None:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail="invalid version response: missing or unusable 'version' field",
            )

        # Step 2 — configured model availability via /api/tags
        try:
            tags_resp = self._client.get(self._url("/api/tags"))
        except httpx.RequestError as exc:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail=_bounded_detail(str(exc)),
            )

        if not tags_resp.is_success:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail=f"HTTP {tags_resp.status_code} from /api/tags",
            )

        try:
            tags_data = tags_resp.json()
        except ValueError:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail="invalid /api/tags response: non-JSON body",
            )

        if not isinstance(tags_data, dict) or "models" not in tags_data:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail="invalid /api/tags response: missing 'models' field",
            )

        models_list = tags_data["models"]
        if not isinstance(models_list, list):
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail="invalid /api/tags response: 'models' is not a list",
            )

        configured_model = self._profile.model
        model_found = _model_in_tags(configured_model, models_list)

        if model_found:
            return ModelHealth(
                reachable=True,
                model_available=True,
            )
        else:
            return ModelHealth(
                reachable=True,
                model_available=False,
                detail="configured model not installed",
            )

    # ── Plain chat ─────────────────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Plain multi-turn conversation (text in, text out).

        Args:
            request: The conversation history.

        Returns:
            A ``ChatResponse`` with the assistant's reply.

        Raises:
            ModelError: If the request contains tool-specific history
                that cannot be represented in plain Ollama chat, or if
                the provider/network/response fails.
            ValidationError: If the provider is not ``"ollama"``
                (raised in ``__init__``).
        """
        # Reject tool-bearing history before making any HTTP call
        self._assert_no_tool_history(request)

        payload = self._build_chat_payload(request)

        try:
            response = self._client.post(self._url("/api/chat"), json=payload)
        except httpx.RequestError as exc:
            raise ModelError(
                f"Ollama chat request failed: {exc}",
                cause=exc,
            ) from exc

        if not response.is_success:
            detail = _extract_ollama_error(response)
            raise ModelError(
                f"Ollama chat returned HTTP {response.status_code}: {detail}",
            )

        return self._parse_chat_response(response)

    # ── Internal helpers ───────────────────────────────────────────────

    def _url(self, path: str) -> str:
        """Build an absolute URL from the profile's base URL and a path.

        Uses ``urllib.parse.urljoin`` which preserves any existing path
        prefix in the base URL.

        Example::

            base_url = "https://provider.example/ollama"
            _url("/api/chat")  -> "https://provider.example/ollama/api/chat"
        """
        # urljoin with a leading-slash path replaces the base path,
        # so we strip the leading slash for path-prefix preservation.
        return urljoin(self._profile.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _build_chat_payload(self, request: ChatRequest) -> dict[str, Any]:
        """Build the Ollama ``POST /api/chat`` JSON payload."""
        payload: dict[str, Any] = {
            "model": self._profile.model,
            "messages": [_map_message(m) for m in request.messages],
            "stream": False,
        }

        if self._profile.temperature is not None:
            payload.setdefault("options", {})["temperature"] = self._profile.temperature

        if self._profile.keep_alive is not None:
            payload["keep_alive"] = self._profile.keep_alive

        return payload

    def _assert_no_tool_history(self, request: ChatRequest) -> None:
        """Raise ``ModelError`` if the request contains tool-specific messages.

        This is called *before* any HTTP request to avoid sending
        semantically invalid payloads to Ollama.
        """
        for msg in request.messages:
            if msg.role == MessageRole.TOOL:
                raise ModelError(
                    "Plain chat does not support TOOL-role messages. "
                    "Use chat_with_tools() (S8-04) for tool-bearing history."
                )
            if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                raise ModelError(
                    "Plain chat does not support assistant messages with tool_calls. "
                    "Use chat_with_tools() (S8-04) for tool-bearing history."
                )

    def _parse_chat_response(self, response: httpx.Response) -> ChatResponse:
        """Parse an Ollama ``POST /api/chat`` response into a ``ChatResponse``.

        Raises ``ModelError`` for malformed responses, unexpected
        tool_calls, or invalid message structure.
        """
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelError(
                "Ollama chat returned non-JSON response",
                cause=exc,
            ) from exc

        if not isinstance(data, dict) or "message" not in data:
            raise ModelError("Ollama chat response missing 'message' field")

        msg_data = data["message"]
        if not isinstance(msg_data, dict):
            raise ModelError("Ollama chat response 'message' is not an object")

        role = msg_data.get("role", "")
        content = msg_data.get("content")

        # Check for unexpected tool_calls
        tool_calls = msg_data.get("tool_calls")
        if tool_calls:
            raise ModelError(
                "Ollama plain chat returned unexpected tool_calls. "
                "Use chat_with_tools() (S8-04) for tool-calling responses."
            )

        if role != "assistant":
            raise ModelError(
                f"Ollama chat returned unexpected role: {role!r}. Expected 'assistant'."
            )

        # Build a ChatMessage; let Pydantic validation catch remaining issues
        try:
            chat_message = ChatMessage(role=MessageRole.ASSISTANT, content=content)
        except Exception as exc:
            raise ModelError(
                f"Invalid assistant message from Ollama: {exc}",
                cause=exc,
            ) from exc

        try:
            return ChatResponse(message=chat_message)
        except Exception as exc:
            raise ModelError(
                f"Invalid chat response from Ollama: {exc}",
                cause=exc,
            ) from exc


# ── Module-level helpers ───────────────────────────────────────────────────


def _extract_version(version_data: Any) -> str | None:
    """Extract a usable version string from a /api/version response.

    Returns the stripped version string if the value is a non-empty string,
    or ``None`` for any unusable value (missing, null, empty, whitespace-only,
    non-string).
    """
    if not isinstance(version_data, dict):
        return None
    raw = version_data.get("version")
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped if stripped else None


def _map_message(msg: ChatMessage) -> dict[str, Any]:
    """Map a provider-neutral ``ChatMessage`` to an Ollama message dict.

    Only SYSTEM, USER, and ASSISTANT roles are mapped.  TOOL and
    tool-bearing assistant messages are rejected before this point
    (in ``_assert_no_tool_history``).
    """
    return {
        "role": msg.role.value,
        "content": msg.content or "",
    }


def _model_in_tags(configured_model: str, models_list: list[Any]) -> bool:
    """Check if the configured model is present in the /api/tags model list.

    Uses exact string matching against the ``model`` and ``name`` fields
    of each entry in the models list.
    """
    for entry in models_list:
        if not isinstance(entry, dict):
            continue
        entry_model = entry.get("model")
        entry_name = entry.get("name")
        if entry_model == configured_model or entry_name == configured_model:
            return True
    return False


def _extract_ollama_error(response: httpx.Response) -> str:
    """Extract a short diagnostic from an Ollama error response.

    If the response is JSON and contains an ``error`` field, returns
    a bounded string.  Otherwise returns the HTTP status line.
    """
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"

    if isinstance(data, dict) and isinstance(data.get("error"), str):
        error_text = data["error"]
        # Keep it safely bounded
        return error_text[:200]

    return f"HTTP {response.status_code}"


def _bounded_detail(text: str, max_len: int = 200) -> str:
    """Truncate a detail string to a safe maximum length."""
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
