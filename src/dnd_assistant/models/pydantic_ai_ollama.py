"""Pydantic AI Ollama model builder — PAIM-09 Ollama integration decision gate.

This module provides the narrow production factory that constructs a Pydantic
AI ``OllamaModel`` from a project ``ModelProfile`` for use with the
``PydanticAIAgentRuntime``.

Ownership
─────────

Owned here:
    ``build_pydantic_ai_ollama_model()`` — factory function.
    ``_normalize_openai_compatible_base_url()`` — private URL helper.

Owned elsewhere (unchanged):
    ``ModelProfile`` — project model profile schema.
    ``ModelProfileRole`` — role enum (AGENT, SUMMARIZER, EMBEDDING).
    ``PydanticAIAgentRuntime`` — bounded agent runtime.
    ``OllamaModelProvider`` — native ModelGateway implementation.

Import boundary
───────────────

This module may import:
    ``pydantic_ai``
    ``pydantic_ai.models.ollama.OllamaModel``
    ``pydantic_ai.providers.ollama.OllamaProvider``
    ``dnd_assistant.models.profiles``

This module must NOT eagerly import:
    ``dnd_assistant.application.pydantic_ai_agent_runtime``
    ``dnd_assistant.storage``
    ``dnd_assistant.retrieval``
    ``dnd_assistant.cli``
    ``dnd_assistant.tools.executor``
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings

from dnd_assistant.errors import ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole


def build_pydantic_ai_ollama_model(
    profile: ModelProfile,
) -> OllamaModel:
    """Construct a Pydantic AI ``OllamaModel`` from a project ``ModelProfile``.

    The builder is intended exclusively for the ``PydanticAIAgentRuntime``
    agent model transport.  It validates the profile's provider, role, and
    ``keep_alive`` semantics before constructing framework objects.

    Args:
        profile: A project ``ModelProfile`` whose ``provider`` must be
            ``"ollama"`` and ``role`` must be ``AGENT``.

    Returns:
        A configured ``OllamaModel`` instance with the framework
        ``OllamaProvider``.

    Raises:
        ValidationError: If ``profile`` is not a ``ModelProfile`` instance,
            or has a non-ollama provider, a non-AGENT role, or a non-None
            ``keep_alive`` value.
    """
    # ── Runtime type check ──────────────────────────────────────────────
    if not isinstance(profile, ModelProfile):
        raise ValidationError(
            f"profile must be a ModelProfile instance, got {type(profile).__name__}"
        )

    # ── Provider validation ─────────────────────────────────────────────
    if profile.provider != "ollama":
        raise ValidationError(
            f"Pydantic AI Ollama model requires provider='ollama', "
            f"got provider={profile.provider!r}"
        )

    # ── Role validation ─────────────────────────────────────────────────
    if profile.role is not ModelProfileRole.AGENT:
        raise ValidationError(
            f"Pydantic AI Ollama model requires role=AGENT, got role={profile.role!r}"
        )

    # ── keep_alive fail-closed ──────────────────────────────────────────
    if profile.keep_alive is not None:
        raise ValidationError(
            "Pydantic AI 2.39 Ollama OpenAI-compatible agent transport "
            "cannot currently guarantee preservation of "
            "ModelProfile.keep_alive. "
            "Set keep_alive=None for the agent profile, or use the "
            "native OllamaModelProvider for non-agent keep_alive semantics."
        )

    # ── Base URL normalisation ──────────────────────────────────────────
    normalized_base_url = _normalize_openai_compatible_base_url(profile.base_url)

    # ── Framework construction ──────────────────────────────────────────
    provider = OllamaProvider(base_url=normalized_base_url)

    settings: ModelSettings | None = None
    if profile.temperature is not None:
        settings = ModelSettings(temperature=profile.temperature)

    return OllamaModel(
        profile.model,
        provider=provider,
        settings=settings,
    )


def _normalize_openai_compatible_base_url(base_url: str) -> str:
    """Normalise a native Ollama root URL to an OpenAI-compatible /v1 URL.

    Required transformations::

        http://localhost:11434          -> http://localhost:11434/v1
        http://localhost:11434/         -> http://localhost:11434/v1
        http://localhost:11434/v1       -> http://localhost:11434/v1
        http://localhost:11434/v1/      -> http://localhost:11434/v1
        https://example.test/ollama     -> https://example.test/ollama/v1
        https://example.test/ollama/    -> https://example.test/ollama/v1
        https://example.test/ollama/v1  -> https://example.test/ollama/v1

    Uses the standard-library URL parser to correctly handle path prefixes
    and avoid ``/v1/v1`` duplication.

    Args:
        base_url: The project profile's ``base_url`` (already validated as
            a syntactically valid HTTP/HTTPS URL by ``ModelProfile``).

    Returns:
        A URL string ending in ``/v1`` suitable for ``OllamaProvider``.

    Raises:
        ValidationError: If the URL cannot be parsed.
    """
    try:
        parsed = urlparse(base_url)
    except ValueError as exc:
        raise ValidationError(
            f"Failed to parse base_url: {base_url!r}",
            cause=exc,
        ) from exc

    path = parsed.path.rstrip("/")

    # Already has /v1 suffix — preserve as-is
    if path.endswith("/v1"):
        normalized_path = path
    else:
        normalized_path = f"{path}/v1" if path else "/v1"

    # Reconstruct without trailing slash
    normalized = f"{parsed.scheme}://{parsed.netloc}{normalized_path}"

    return normalized
