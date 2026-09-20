"""S13-03 bootstrap composition and BOOTSTRAP-role enforcement tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dnd_assistant.composition.bootstrap import compose_bootstrap_runtime
from dnd_assistant.errors import ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.pydantic_ai_ollama import build_pydantic_ai_bootstrap_model

pytestmark = pytest.mark.provider_upgrade


def _config(tmp_path: Path, role: str) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        "[profiles]\n"
        "[profiles.heavy]\n"
        'provider = "ollama"\n'
        'model = "m"\n'
        'base_url = "http://localhost:11434"\n'
        f'role = "{role}"\n',
        encoding="utf-8",
    )
    return config


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "_system").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _dummy_factory(profile: ModelProfile) -> Any:
    return object()


def test_bootstrap_model_builder_rejects_non_bootstrap_role() -> None:
    profile = ModelProfile(
        provider="ollama",
        model="m",
        base_url="http://localhost:11434",
        role=ModelProfileRole.AGENT,
    )
    with pytest.raises(ValidationError):
        build_pydantic_ai_bootstrap_model(profile)


def test_compose_bootstrap_runtime_rejects_non_bootstrap_role(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        compose_bootstrap_runtime(
            vault_root=_vault(tmp_path),
            config_path=_config(tmp_path, "agent"),
            profile_name="heavy",
            model_factory=_dummy_factory,
        )


def test_compose_bootstrap_runtime_rejects_missing_profile(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        compose_bootstrap_runtime(
            vault_root=_vault(tmp_path),
            config_path=_config(tmp_path, "bootstrap"),
            profile_name="missing",
            model_factory=_dummy_factory,
        )
