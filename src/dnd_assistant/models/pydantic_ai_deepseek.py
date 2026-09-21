"""Pydantic AI DeepSeek model builder — RM-02 compatibility factory.

This module provides the narrow project-owned factory that constructs a
Pydantic AI ``OpenAIChatModel`` backed by ``DeepSeekProvider`` for the
canonical DeepSeek agent model.

Ownership
─────────

Owned here:
    ``build_pydantic_ai_deepseek_model()`` — AGENT-role factory.
    ``DEEPSEEK_FLASH_TRUTHFUL_PROFILE`` — public capability correction.
    ``_build_deepseek_settings()`` — RM-01 → public ModelSettings mapping.

Owned elsewhere (unchanged):
    ``ModelProfile`` — project model profile schema.
    ``DeepSeekProvider`` / ``OpenAIChatModel`` — Pydantic AI public classes.
    ``resolve_provider_api_key()`` — machine-local credential boundary.

Why the profile correction exists (RM-02 evidence)
──────────────────────────────────────────────────

Pinned ``pydantic-ai-slim[openai]==2.39.0`` recognizes DeepSeek thinking
capability only for ``deepseek-reasoner`` / ``deepseek-r1*`` / ``deepseek-v4-*``
names (``pydantic_ai.profiles.deepseek``).  The current official identifier
``deepseek-flash`` does not match, so the built-in profile reports:

- ``supports_thinking = False`` (the unified ``thinking`` setting is then
  silently stripped in ``Model.prepare_request``); and
- ``openai_supports_forced_tool_choice_with_thinking = True`` (incorrect for a
  V4-family model, whose thinking mode rejects forced ``tool_choice``).

The RM-02 factory therefore applies a **minimal, truthful public profile
override** for ``deepseek-flash``.  It does not copy the built-in DeepSeek
provider profile, duplicate OpenAI transport/message mapping, subclass the
provider, or patch framework-private state.

Settings mapping
────────────────

The unified ``thinking`` setting is deliberately **not** used for
``deepseek-flash`` (it is stripped by the incorrect capability recognition).
Instead the RM-01 contract maps through public provider-specific settings:

    thinking=true  + effort low|high|max
        → extra_body={"thinking": {"type": "enabled"}}
          openai_reasoning_effort=<effort>

    thinking=false
        → extra_body={"thinking": {"type": "disabled"}}
          (no reasoning_effort)

Temperature note: DeepSeek's documented thinking-mode contract ignores
``temperature`` without raising.  This factory forwards a configured
``temperature`` unchanged (the narrowest behavior: no invented migration) and
relies on the provider contract for thinking-mode semantics.

RM-02 boundary: this module is **not** wired into ``composition/agent_model.py``
or any production agent dispatch.  RM-03 owns production integration.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.settings import ModelSettings

from dnd_assistant.errors import ValidationError
from dnd_assistant.models.credentials import resolve_provider_api_key
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole

__all__ = [
    "DEEPSEEK_FLASH_TRUTHFUL_PROFILE",
    "build_pydantic_ai_deepseek_model",
]

_DEEPSEEK_PROVIDER = "deepseek"
CANONICAL_DEEPSEEK_MODEL = "deepseek-flash"
_CANONICAL_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Minimal public capability override for the canonical ``deepseek-flash``.
# Only fields shown incorrect by RM-02 source/offline evidence are set.
DEEPSEEK_FLASH_TRUTHFUL_PROFILE = OpenAIModelProfile(
    supports_thinking=True,
    thinking_always_enabled=False,
    openai_supports_forced_tool_choice_with_thinking=False,
)


def build_pydantic_ai_deepseek_model(
    profile: ModelProfile,
    *,
    provider: DeepSeekProvider | None = None,
) -> OpenAIChatModel:
    """Construct a Pydantic AI ``OpenAIChatModel`` for the DeepSeek AGENT role.

    Args:
        profile: A project ``ModelProfile`` with ``provider="deepseek"``,
            ``role`` AGENT and model ``deepseek-flash``.
        provider: Optional pre-constructed public ``DeepSeekProvider``.  This is
            a transport-injection seam used by tests and does not change the
            production credential path; when omitted the factory resolves the
            machine-local ``DEEPSEEK_API_KEY`` at construction time.

    Returns:
        A configured ``OpenAIChatModel`` with the truthful DeepSeek profile
        override and RM-01-mapped thinking/reasoning settings.

    Raises:
        ValidationError: If ``profile`` is not a valid canonical DeepSeek AGENT
            profile, or if it carries settings the DeepSeek transport cannot
            honor.
    """
    _validate_profile(profile)

    if provider is None:
        secret = resolve_provider_api_key(_DEEPSEEK_PROVIDER)
        provider = DeepSeekProvider(api_key=secret.get_secret_value())

    return OpenAIChatModel(
        profile.model,
        provider=provider,
        profile=DEEPSEEK_FLASH_TRUTHFUL_PROFILE,
        settings=_build_deepseek_settings(profile),
    )


def _validate_profile(profile: ModelProfile) -> None:
    """Fail closed on any profile the canonical DeepSeek factory cannot honor."""
    if not isinstance(profile, ModelProfile):
        raise ValidationError(
            f"profile must be a ModelProfile instance, got {type(profile).__name__}"
        )

    if profile.provider != _DEEPSEEK_PROVIDER:
        raise ValidationError(
            f"Pydantic AI DeepSeek model requires provider={_DEEPSEEK_PROVIDER!r}, "
            f"got provider={profile.provider!r}"
        )

    if profile.role is not ModelProfileRole.AGENT:
        raise ValidationError(
            f"Pydantic AI DeepSeek model requires role="
            f"{ModelProfileRole.AGENT.value.upper()}, got role={profile.role!r}"
        )

    if profile.model != CANONICAL_DEEPSEEK_MODEL:
        raise ValidationError(
            "Pydantic AI DeepSeek factory is pinned to the canonical model "
            f"{CANONICAL_DEEPSEEK_MODEL!r}; got model={profile.model!r}. A different "
            "identifier requires its own capability review before use."
        )

    if profile.thinking is None:
        raise ValidationError(
            "DeepSeek agent profile must set thinking explicitly (RM-01 contract)"
        )

    if profile.thinking and profile.reasoning_effort is None:
        raise ValidationError(
            "DeepSeek thinking=true requires an explicit reasoning_effort (RM-01 contract)"
        )

    if not profile.thinking and profile.reasoning_effort is not None:
        raise ValidationError(
            "DeepSeek thinking=false must not set reasoning_effort (RM-01 contract)"
        )

    if profile.keep_alive is not None:
        raise ValidationError(
            "DeepSeek agent transport does not support ModelProfile.keep_alive; "
            "set keep_alive=None for a DeepSeek agent profile."
        )

    if _normalize_base_url(profile.base_url) != _CANONICAL_DEEPSEEK_BASE_URL:
        raise ValidationError(
            "Pydantic AI DeepSeek factory uses the provider's canonical base URL "
            f"{_CANONICAL_DEEPSEEK_BASE_URL!r}; got base_url={profile.base_url!r}. "
            "A non-canonical endpoint requires a separate review."
        )


def _build_deepseek_settings(profile: ModelProfile) -> ModelSettings:
    """Map the RM-01 contract onto public Pydantic AI ``ModelSettings``.

    Uses the public provider-specific path only.  The unified ``thinking``
    setting is not used because the pinned framework strips it for the
    canonical ``deepseek-flash`` identifier.
    """
    settings: dict[str, Any] = {
        "extra_body": {"thinking": {"type": "enabled" if profile.thinking else "disabled"}},
    }
    if profile.thinking and profile.reasoning_effort is not None:
        settings["openai_reasoning_effort"] = profile.reasoning_effort.value
    if profile.temperature is not None:
        settings["temperature"] = profile.temperature
    return ModelSettings(**settings)


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")
