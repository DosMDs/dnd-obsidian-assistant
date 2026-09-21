"""Tests for provider-gated reasoning settings on machine-local profiles (RM-01).

Covers the canonical ``ReasoningEffort`` vocabulary, the DeepSeek AGENT
thinking/reasoning contract, provider/role gating and TOML round-trip.

All tests are deterministic, require no Ollama, no network, no Vault and no
environment access.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.errors import ValidationError as DndValidationError
from dnd_assistant.models.profiles import (
    ModelProfile,
    ModelProfileRole,
    ReasoningEffort,
    load_model_profiles,
)


def _write_toml(path: Path, content: str) -> Path:
    """Write a TOML string to a temporary file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _deepseek_agent(**overrides: object) -> ModelProfile:
    base: dict[str, object] = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "role": ModelProfileRole.AGENT,
        "thinking": True,
        "reasoning_effort": ReasoningEffort.HIGH,
    }
    base.update(overrides)
    return ModelProfile(**base)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# ReasoningEffort
# ═══════════════════════════════════════════════════════════════════════════


class TestReasoningEffort:
    """Canonical reasoning-effort vocabulary."""

    def test_canonical_values(self) -> None:
        assert {effort.value for effort in ReasoningEffort} == {"low", "high", "max"}

    def test_from_string(self) -> None:
        assert ReasoningEffort("low") is ReasoningEffort.LOW
        assert ReasoningEffort("high") is ReasoningEffort.HIGH
        assert ReasoningEffort("max") is ReasoningEffort.MAX

    def test_medium_rejected(self) -> None:
        with pytest.raises(ValueError, match="'medium'"):
            ReasoningEffort("medium")

    def test_unknown_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReasoningEffort("extreme")


# ═══════════════════════════════════════════════════════════════════════════
# DeepSeek AGENT reasoning contract
# ═══════════════════════════════════════════════════════════════════════════


class TestDeepSeekAgentReasoning:
    """Accepted DeepSeek AGENT thinking/reasoning_effort semantics."""

    @pytest.mark.parametrize(
        "effort",
        [ReasoningEffort.LOW, ReasoningEffort.HIGH, ReasoningEffort.MAX],
    )
    def test_thinking_true_with_each_effort(self, effort: ReasoningEffort) -> None:
        p = _deepseek_agent(reasoning_effort=effort)
        assert p.thinking is True
        assert p.reasoning_effort is effort

    def test_thinking_false_without_effort(self) -> None:
        p = _deepseek_agent(thinking=False, reasoning_effort=None)
        assert p.thinking is False
        assert p.reasoning_effort is None

    def test_thinking_omitted_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="must set thinking explicitly"):
            _deepseek_agent(thinking=None)

    def test_thinking_true_without_effort_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="requires an explicit reasoning_effort"):
            _deepseek_agent(thinking=True, reasoning_effort=None)

    def test_thinking_false_with_effort_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="thinking=false must not set"):
            _deepseek_agent(thinking=False, reasoning_effort=ReasoningEffort.HIGH)

    def test_effort_without_thinking_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="must set thinking explicitly"):
            _deepseek_agent(thinking=None, reasoning_effort=ReasoningEffort.HIGH)

    def test_medium_effort_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            _deepseek_agent(reasoning_effort="medium")


# ═══════════════════════════════════════════════════════════════════════════
# Provider / role gating of reasoning settings
# ═══════════════════════════════════════════════════════════════════════════


class TestReasoningProviderRoleGating:
    """Reasoning settings are DeepSeek-AGENT-only in this release."""

    def test_ollama_thinking_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="only supported for provider 'deepseek'"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost:11434",
                role=ModelProfileRole.AGENT,
                thinking=True,
                reasoning_effort=ReasoningEffort.HIGH,
            )

    def test_ollama_effort_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="only supported for provider 'deepseek'"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost:11434",
                role=ModelProfileRole.AGENT,
                reasoning_effort=ReasoningEffort.HIGH,
            )

    def test_arbitrary_provider_without_reasoning_still_valid(self) -> None:
        p = ModelProfile(
            provider="test-provider",
            model="test-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
        )
        assert p.provider == "test-provider"
        assert p.thinking is None
        assert p.reasoning_effort is None

    def test_deepseek_non_agent_reasoning_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="only supported for role 'agent'"):
            ModelProfile(
                provider="deepseek",
                model="deepseek-flash",
                base_url="https://api.deepseek.com",
                role=ModelProfileRole.POST_SESSION,
                thinking=True,
                reasoning_effort=ReasoningEffort.HIGH,
            )

    def test_deepseek_non_agent_without_reasoning_valid(self) -> None:
        p = ModelProfile(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            role=ModelProfileRole.POST_SESSION,
        )
        assert p.thinking is None
        assert p.reasoning_effort is None


# ═══════════════════════════════════════════════════════════════════════════
# DeepSeek reasoning via TOML loader
# ═══════════════════════════════════════════════════════════════════════════


class TestDeepSeekReasoningToml:
    """TOML round-trip for the DeepSeek reasoning contract."""

    def test_valid_candidate_profile(self, tmp_path: Path) -> None:
        toml = """\
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "high"
"""
        path = _write_toml(tmp_path / "ds.toml", toml)
        config = load_model_profiles(path)
        p = config.profiles["agent-deepseek"]
        assert p.provider == "deepseek"
        assert p.thinking is True
        assert p.reasoning_effort is ReasoningEffort.HIGH

    def test_medium_effort_rejected_via_loader(self, tmp_path: Path) -> None:
        toml = """\
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "medium"
"""
        path = _write_toml(tmp_path / "ds-medium.toml", toml)
        with pytest.raises(DndValidationError, match="Invalid model profile configuration"):
            load_model_profiles(path)

    def test_missing_thinking_rejected_via_loader(self, tmp_path: Path) -> None:
        toml = """\
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
reasoning_effort = "high"
"""
        path = _write_toml(tmp_path / "ds-nothink.toml", toml)
        with pytest.raises(DndValidationError, match="Invalid model profile configuration"):
            load_model_profiles(path)


# ═══════════════════════════════════════════════════════════════════════════
# Reasoning fields — immutability / extra-field rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestReasoningImmutability:
    """New reasoning fields preserve frozen/extra=forbid behavior."""

    def test_frozen_assignment_rejected(self) -> None:
        p = _deepseek_agent()
        with pytest.raises(PydanticValidationError):
            p.thinking = False  # type: ignore[misc]

    def test_unknown_reasoning_like_field_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
            ModelProfile(
                provider="deepseek",
                model="deepseek-flash",
                base_url="https://api.deepseek.com",
                role=ModelProfileRole.AGENT,
                thinking=True,
                reasoning_effort=ReasoningEffort.HIGH,
                reason_effort="high",  # type: ignore[call-arg]
            )
