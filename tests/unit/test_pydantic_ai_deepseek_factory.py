"""RM-02: DeepSeek model factory — deterministic offline unit tests.

These tests are network- and credential-independent.  They prove the narrow
DeepSeek factory's validation, its truthful public profile override, the RM-01
→ public ``ModelSettings`` mapping, and freeze the pinned Pydantic AI 2.39.0
``deepseek-flash`` capability mis-recognition that motivates the override.

No real HTTP request and no DeepSeek credential are used.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.deepseek import deepseek_model_profile
from pydantic_ai.providers.deepseek import DeepSeekProvider

from dnd_assistant.errors import CredentialError, ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, ReasoningEffort
from dnd_assistant.models.pydantic_ai_deepseek import (
    CANONICAL_DEEPSEEK_MODEL,
    DEEPSEEK_FLASH_TRUTHFUL_PROFILE,
    build_pydantic_ai_deepseek_model,
)


def _deepseek_agent(
    *,
    thinking: bool = True,
    reasoning_effort: ReasoningEffort | None = ReasoningEffort.HIGH,
    model: str = CANONICAL_DEEPSEEK_MODEL,
    base_url: str = "https://api.deepseek.com",
    keep_alive: str | None = None,
    temperature: float | None = None,
    role: ModelProfileRole = ModelProfileRole.AGENT,
) -> ModelProfile:
    return ModelProfile(
        provider="deepseek",
        model=model,
        base_url=base_url,
        role=role,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        keep_alive=keep_alive,
        temperature=temperature,
    )


def _stub_provider() -> DeepSeekProvider:
    """Build a public DeepSeekProvider that never performs a real request."""
    return DeepSeekProvider(api_key="offline-dummy-key")


# ── Capability freeze: the pinned profile defect ────────────────────────────


class TestPinnedDeepSeekFlashCapabilityDefect:
    """Freeze the pinned 2.39.0 mis-recognition of canonical deepseek-flash."""

    def test_builtin_profile_reports_thinking_unsupported(self) -> None:
        profile = deepseek_model_profile(CANONICAL_DEEPSEEK_MODEL)
        assert profile is not None
        assert profile.get("supports_thinking") is False

    def test_builtin_provider_permits_forced_tool_choice_with_thinking(self) -> None:
        provider_profile = DeepSeekProvider.model_profile(CANONICAL_DEEPSEEK_MODEL)
        assert provider_profile is not None
        assert provider_profile.get("openai_supports_forced_tool_choice_with_thinking") is True

    def test_builtin_provider_still_sets_reasoning_round_trip_fields(self) -> None:
        provider_profile = DeepSeekProvider.model_profile(CANONICAL_DEEPSEEK_MODEL)
        assert provider_profile is not None
        assert provider_profile.get("openai_chat_thinking_field") == "reasoning_content"
        assert provider_profile.get("openai_chat_send_back_thinking_parts") == "field"


# ── Truthful override ───────────────────────────────────────────────────────


class TestTruthfulProfileOverride:
    def test_override_corrects_thinking_capability(self) -> None:
        assert DEEPSEEK_FLASH_TRUTHFUL_PROFILE.get("supports_thinking") is True
        assert DEEPSEEK_FLASH_TRUTHFUL_PROFILE.get("thinking_always_enabled") is False

    def test_override_corrects_forced_tool_choice_with_thinking(self) -> None:
        assert (
            DEEPSEEK_FLASH_TRUTHFUL_PROFILE.get("openai_supports_forced_tool_choice_with_thinking")
            is False
        )

    def test_model_resolved_profile_is_patched_truthfully(self) -> None:
        model = build_pydantic_ai_deepseek_model(_deepseek_agent(), provider=_stub_provider())
        resolved = model.profile
        assert resolved.get("supports_thinking") is True
        assert resolved.get("thinking_always_enabled") is False
        assert resolved.get("openai_supports_forced_tool_choice_with_thinking") is False
        # The reasoning round-trip fields from the built-in provider profile
        # must survive the merge (the override must not discard them).
        assert resolved.get("openai_chat_thinking_field") == "reasoning_content"
        assert resolved.get("openai_chat_send_back_thinking_parts") == "field"


# ── Settings mapping ────────────────────────────────────────────────────────


class TestSettingsMapping:
    @pytest.mark.parametrize(
        "effort", [ReasoningEffort.LOW, ReasoningEffort.HIGH, ReasoningEffort.MAX]
    )
    def test_thinking_true_maps_toggle_and_effort(self, effort: ReasoningEffort) -> None:
        model = build_pydantic_ai_deepseek_model(
            _deepseek_agent(thinking=True, reasoning_effort=effort),
            provider=_stub_provider(),
        )
        settings = model.settings
        assert settings is not None
        assert settings.get("extra_body") == {"thinking": {"type": "enabled"}}
        assert settings.get("openai_reasoning_effort") == effort.value

    def test_thinking_false_maps_disabled_and_no_effort(self) -> None:
        model = build_pydantic_ai_deepseek_model(
            _deepseek_agent(thinking=False, reasoning_effort=None),
            provider=_stub_provider(),
        )
        settings = model.settings
        assert settings is not None
        assert settings.get("extra_body") == {"thinking": {"type": "disabled"}}
        assert "openai_reasoning_effort" not in settings

    def test_max_effort_is_not_rewritten_through_unified_mapping(self) -> None:
        model = build_pydantic_ai_deepseek_model(
            _deepseek_agent(thinking=True, reasoning_effort=ReasoningEffort.MAX),
            provider=_stub_provider(),
        )
        settings = model.settings
        assert settings is not None
        assert settings.get("openai_reasoning_effort") == "max"
        # The unified `thinking` field is deliberately unused for deepseek-flash.
        assert "thinking" not in settings

    def test_temperature_is_forwarded_unchanged(self) -> None:
        model = build_pydantic_ai_deepseek_model(
            _deepseek_agent(temperature=0.25),
            provider=_stub_provider(),
        )
        settings = model.settings
        assert settings is not None
        assert settings.get("temperature") == 0.25


# ── Construction and validation ─────────────────────────────────────────────


class TestFactoryValidation:
    def test_returns_openai_chat_model_with_canonical_name(self) -> None:
        model = build_pydantic_ai_deepseek_model(_deepseek_agent(), provider=_stub_provider())
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == CANONICAL_DEEPSEEK_MODEL

    def test_rejects_wrong_provider(self) -> None:
        profile = _deepseek_agent().model_copy(update={"provider": "ollama"})
        with pytest.raises(ValidationError, match="requires provider='deepseek'"):
            build_pydantic_ai_deepseek_model(profile, provider=_stub_provider())

    def test_rejects_non_canonical_model(self) -> None:
        with pytest.raises(ValidationError, match="pinned to the canonical model"):
            build_pydantic_ai_deepseek_model(
                _deepseek_agent(model="deepseek-v4-flash"), provider=_stub_provider()
            )

    def test_rejects_non_canonical_base_url(self) -> None:
        with pytest.raises(ValidationError, match="canonical base URL"):
            build_pydantic_ai_deepseek_model(
                _deepseek_agent(base_url="https://example.test"), provider=_stub_provider()
            )

    def test_rejects_keep_alive(self) -> None:
        with pytest.raises(ValidationError, match="keep_alive"):
            build_pydantic_ai_deepseek_model(
                _deepseek_agent(keep_alive="5m"), provider=_stub_provider()
            )

    def test_rejects_non_agent_role(self) -> None:
        profile = ModelProfile(
            provider="deepseek",
            model=CANONICAL_DEEPSEEK_MODEL,
            base_url="https://api.deepseek.com",
            role=ModelProfileRole.POST_SESSION,
        )
        with pytest.raises(ValidationError, match="requires role=AGENT"):
            build_pydantic_ai_deepseek_model(profile, provider=_stub_provider())

    def test_missing_credential_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with pytest.raises(CredentialError, match="DEEPSEEK_API_KEY"):
            build_pydantic_ai_deepseek_model(_deepseek_agent())

    def test_canonical_base_url_trailing_slash_is_accepted(self) -> None:
        model = build_pydantic_ai_deepseek_model(
            _deepseek_agent(base_url="https://api.deepseek.com/"),
            provider=_stub_provider(),
        )
        assert model.model_name == CANONICAL_DEEPSEEK_MODEL
