"""Project-owned Ollama HTTP transport policy.

This module defines the single authoritative timeout configuration for all
Ollama HTTP transports in the application.  Both the native
``OllamaModelProvider`` and the Pydantic AI ``OllamaModel`` builder consume
these constants and the factory function, ensuring symmetric timeout behavior
across both runtime paths.

Usage::

    from dnd_assistant.models.transport import build_ollama_http_timeout

    client = httpx.Client(timeout=build_ollama_http_timeout())

    settings = ModelSettings(timeout=build_ollama_http_timeout())

Architectural boundary
──────────────────────
This module imports only ``httpx``.  It must not import from
``dnd_assistant.models``, ``dnd_assistant.domain``, ``dnd_assistant.storage``,
or any other application module.
"""

from __future__ import annotations

import httpx

# ── Constants ──────────────────────────────────────────────────────────────

OLLAMA_CONNECT_TIMEOUT_SECONDS: float = 5.0
"""Maximum time (seconds) to establish a TCP connection to Ollama."""

OLLAMA_REQUEST_TIMEOUT_SECONDS: float = 120.0
"""Maximum time (seconds) for the complete Ollama HTTP request (read phase).

This is a **maximum transport ceiling**, not a latency target or SLA.
Normal turns are expected to complete well within this window.
"""


# ── Factory ────────────────────────────────────────────────────────────────


def build_ollama_http_timeout() -> httpx.Timeout:
    """Return a fresh ``httpx.Timeout`` with the project's Ollama policy.

    Semantics:

    * ``connect`` — 5 seconds to establish a TCP connection.
    * ``read`` / ``request`` — 120 seconds for the full request/response.
    * ``write`` and ``pool`` — bounded by the same ``httpx.Timeout`` object
      (HTTPX uses the general timeout value for write/pool when they are not
      explicitly set).

    Returns:
        A new ``httpx.Timeout`` instance.  Each call returns an independent
        object so that mutable timeout state is never shared.
    """
    return httpx.Timeout(
        OLLAMA_REQUEST_TIMEOUT_SECONDS,
        connect=OLLAMA_CONNECT_TIMEOUT_SECONDS,
    )
