"""Tests for the machine-local provider credential boundary (RM-01).

Covers the fixed provider → environment-variable mapping and
``resolve_provider_api_key``.  All tests are deterministic, offline and use
monkeypatched environment state only — no network and no real secrets.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from dnd_assistant.errors import CredentialError
from dnd_assistant.errors import ValidationError as DndValidationError
from dnd_assistant.models import credentials
from dnd_assistant.models import profiles as profiles_module
from dnd_assistant.models.profiles import load_model_profiles

_SECRET = "sk-test-secret-value-1234567890"


class _StrictEnv:
    """Environment proxy that rejects lookups outside the allowed key set."""

    def __init__(self, allowed: set[str]) -> None:
        self._allowed = allowed

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._allowed:
            raise AssertionError(f"unexpected environment lookup for {key!r}")
        return os.environ.get(key, default)


def _patch_credentials_env(
    monkeypatch: pytest.MonkeyPatch, allowed: set[str] | None = None
) -> None:
    """Replace only the ``os`` name bound inside the credentials module.

    The real ``os.environ`` (used by pytest internals) is left untouched.
    """
    shim = SimpleNamespace(environ=_StrictEnv(allowed or set()))
    monkeypatch.setattr(credentials, "os", shim)


# ── Mapping ───────────────────────────────────────────────────────────────


class TestCredentialMapping:
    """Fixed provider → environment-variable mapping."""

    def test_deepseek_env_var_name(self) -> None:
        assert credentials.DEEPSEEK_API_KEY_ENV == "DEEPSEEK_API_KEY"
        assert credentials.PROVIDER_API_KEY_ENV["deepseek"] == "DEEPSEEK_API_KEY"

    def test_env_var_for_deepseek(self) -> None:
        assert credentials.provider_credential_env_var("deepseek") == "DEEPSEEK_API_KEY"

    def test_unknown_provider_raises_validation_error(self) -> None:
        with pytest.raises(DndValidationError, match="No machine-local credential"):
            credentials.provider_credential_env_var("unknown-provider")


# ── Resolution ────────────────────────────────────────────────────────────


class TestResolveProviderApiKey:
    """Credential resolution and fail-closed semantics."""

    def test_present_returns_secretstr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", _SECRET)
        result = credentials.resolve_provider_api_key("deepseek")
        assert isinstance(result, SecretStr)
        assert result.get_secret_value() == _SECRET

    def test_missing_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with pytest.raises(CredentialError, match="DEEPSEEK_API_KEY"):
            credentials.resolve_provider_api_key("deepseek")

    def test_empty_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        with pytest.raises(CredentialError, match="Missing or empty"):
            credentials.resolve_provider_api_key("deepseek")

    def test_whitespace_only_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "   \t  ")
        with pytest.raises(CredentialError, match="Missing or empty"):
            credentials.resolve_provider_api_key("deepseek")

    def test_unknown_provider_performs_no_env_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_credentials_env(monkeypatch)
        with pytest.raises(DndValidationError, match="No machine-local credential"):
            credentials.resolve_provider_api_key("unknown-provider")


# ── Secret non-exposure ───────────────────────────────────────────────────


class TestSecretNonExposure:
    """Credentials never appear in repr, str or error text."""

    def test_repr_does_not_reveal_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", _SECRET)
        result = credentials.resolve_provider_api_key("deepseek")
        assert _SECRET not in repr(result)
        assert _SECRET not in str(result)

    def test_error_text_does_not_reveal_other_env_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("UNRELATED_SECRET", _SECRET)
        with pytest.raises(CredentialError) as excinfo:
            credentials.resolve_provider_api_key("deepseek")
        assert _SECRET not in str(excinfo.value)

    def test_resolved_value_not_part_of_profile_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", _SECRET)
        credentials.resolve_provider_api_key("deepseek")

        toml = """\
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "high"
"""
        path = tmp_path / "ds.toml"
        path.write_text(toml, encoding="utf-8")
        profile = load_model_profiles(path).profiles["agent-deepseek"]
        assert _SECRET not in repr(profile)
        assert not hasattr(profile, "api_key")
        assert not hasattr(profile, "credential")


# ── Profile loading purity ────────────────────────────────────────────────


class TestProfileLoadingEnvironmentIndependence:
    """Profile loading performs no environment access."""

    def test_profiles_module_has_no_environment_access(self) -> None:
        source_path = Path(profiles_module.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "os" and node.attr in {"environ", "getenv", "putenv"}:
                    offenders.append(f"os.{node.attr}")
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "load_dotenv":
                    offenders.append("load_dotenv")
        assert not offenders, f"profiles.py accesses the environment: {offenders}"

    def test_loader_succeeds_without_credential_env(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost:11434"
role = "agent"
"""
        path = tmp_path / "safe.toml"
        path.write_text(toml, encoding="utf-8")
        config = load_model_profiles(path)
        assert config.profiles["fast"].provider == "ollama"
