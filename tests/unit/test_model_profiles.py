"""Tests for machine-local model profile configuration (S8-01).

Covers ModelProfileRole, ModelProfile validation, ModelProfilesConfig,
and the TOML-based load_model_profiles loader.

All tests are deterministic, require no Ollama, no network, and no Vault.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.errors import NotFoundError, StorageError
from dnd_assistant.errors import ValidationError as DndValidationError
from dnd_assistant.models.profiles import (
    ModelProfile,
    ModelProfileRole,
    ModelProfilesConfig,
    load_model_profiles,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _write_toml(path: Path, content: str) -> Path:
    """Write a TOML string to a temporary file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


_VALID_AGENT_TOML = """\
[profiles.fast]
provider = "ollama"
model = "qwen-2.5-7b"
base_url = "http://localhost:11434"
temperature = 0.0
keep_alive = "30m"
role = "agent"
"""


# ═══════════════════════════════════════════════════════════════════════════
# ModelProfileRole
# ═══════════════════════════════════════════════════════════════════════════


class TestModelProfileRole:
    """ModelProfileRole enum values and semantics."""

    def test_agent_value(self) -> None:
        assert ModelProfileRole.AGENT.value == "agent"

    def test_summarizer_value(self) -> None:
        assert ModelProfileRole.SUMMARIZER.value == "summarizer"

    def test_embedding_value(self) -> None:
        assert ModelProfileRole.EMBEDDING.value == "embedding"

    def test_all_roles_defined(self) -> None:
        assert set(ModelProfileRole) == {
            ModelProfileRole.AGENT,
            ModelProfileRole.SUMMARIZER,
            ModelProfileRole.EMBEDDING,
        }

    def test_role_from_string(self) -> None:
        assert ModelProfileRole("agent") is ModelProfileRole.AGENT
        assert ModelProfileRole("summarizer") is ModelProfileRole.SUMMARIZER
        assert ModelProfileRole("embedding") is ModelProfileRole.EMBEDDING

    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(ValueError, match="'invalid'"):
            ModelProfileRole("invalid")


# ═══════════════════════════════════════════════════════════════════════════
# ModelProfile — valid construction
# ═══════════════════════════════════════════════════════════════════════════


class TestModelProfileValid:
    """Valid ModelProfile construction."""

    def test_minimal_agent(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
        )
        assert p.provider == "ollama"
        assert p.model == "qwen-2.5-7b"
        assert p.base_url == "http://localhost:11434"
        assert p.role is ModelProfileRole.AGENT
        assert p.temperature is None
        assert p.keep_alive is None

    def test_full_agent(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            temperature=0.0,
            keep_alive="30m",
            role=ModelProfileRole.AGENT,
        )
        assert p.temperature == 0.0
        assert p.keep_alive == "30m"

    def test_summarizer_role(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="llama-3.1-8b",
            base_url="http://192.168.1.50:11434",
            temperature=0.2,
            role=ModelProfileRole.SUMMARIZER,
        )
        assert p.role is ModelProfileRole.SUMMARIZER
        assert p.temperature == 0.2

    def test_embedding_role(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="nomic-embed-text",
            base_url="http://localhost:11434",
            role=ModelProfileRole.EMBEDDING,
        )
        assert p.role is ModelProfileRole.EMBEDDING

    def test_localhost_endpoint(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
        )
        assert p.base_url == "http://localhost:11434"

    def test_lan_endpoint(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://192.168.1.50:11434",
            role=ModelProfileRole.AGENT,
        )
        assert p.base_url == "http://192.168.1.50:11434"

    def test_https_endpoint(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="https://some-provider.example",
            role=ModelProfileRole.AGENT,
        )
        assert p.base_url == "https://some-provider.example"

    def test_non_ollama_provider(self) -> None:
        p = ModelProfile(
            provider="test-provider",
            model="test-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
        )
        assert p.provider == "test-provider"


# ═══════════════════════════════════════════════════════════════════════════
# ModelProfile — field validation
# ═══════════════════════════════════════════════════════════════════════════


class TestModelProfileProvider:
    """provider field validation."""

    def test_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="provider must be non-empty"):
            ModelProfile(
                provider="",
                model="m",
                base_url="http://localhost",
                role=ModelProfileRole.AGENT,
            )

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="provider must be non-empty"):
            ModelProfile(
                provider="   ",
                model="m",
                base_url="http://localhost",
                role=ModelProfileRole.AGENT,
            )


class TestModelProfileModel:
    """model field validation."""

    def test_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="model must be non-empty"):
            ModelProfile(
                provider="ollama",
                model="",
                base_url="http://localhost",
                role=ModelProfileRole.AGENT,
            )

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="model must be non-empty"):
            ModelProfile(
                provider="ollama",
                model="   ",
                base_url="http://localhost",
                role=ModelProfileRole.AGENT,
            )


class TestModelProfileBaseUrl:
    """base_url field validation."""

    def test_non_url_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="base_url must start with"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="not-a-url",
                role=ModelProfileRole.AGENT,
            )

    def test_ftp_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="base_url must start with"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="ftp://localhost",
                role=ModelProfileRole.AGENT,
            )

    def test_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="base_url must start with"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="",
                role=ModelProfileRole.AGENT,
            )

    def test_scheme_only_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="no host after scheme"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://",
                role=ModelProfileRole.AGENT,
            )


class TestModelProfileTemperature:
    """temperature field validation."""

    def test_omitted_is_none(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        assert p.temperature is None

    def test_zero_accepted(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            temperature=0.0,
            role=ModelProfileRole.AGENT,
        )
        assert p.temperature == 0.0

    def test_positive_accepted(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            temperature=0.5,
            role=ModelProfileRole.AGENT,
        )
        assert p.temperature == 0.5

    def test_large_positive_accepted(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            temperature=100.0,
            role=ModelProfileRole.AGENT,
        )
        assert p.temperature == 100.0

    def test_negative_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="temperature must not be negative"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                temperature=-0.1,
                role=ModelProfileRole.AGENT,
            )

    def test_nan_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="temperature must not be NaN"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                temperature=math.nan,
                role=ModelProfileRole.AGENT,
            )

    def test_infinity_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="temperature must not be Infinity"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                temperature=math.inf,
                role=ModelProfileRole.AGENT,
            )

    def test_neg_infinity_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="temperature must not be Infinity"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                temperature=-math.inf,
                role=ModelProfileRole.AGENT,
            )


class TestModelProfileKeepAlive:
    """keep_alive field validation."""

    def test_omitted_is_none(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        assert p.keep_alive is None

    def test_valid_value_accepted(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            keep_alive="30m",
            role=ModelProfileRole.AGENT,
        )
        assert p.keep_alive == "30m"

    def test_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="keep_alive must not be empty"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                keep_alive="",
                role=ModelProfileRole.AGENT,
            )

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="keep_alive must not be empty"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                keep_alive="   ",
                role=ModelProfileRole.AGENT,
            )


class TestModelProfileStrictSchema:
    """Unknown fields inside a profile must be rejected."""

    def test_typo_in_field_name_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                role=ModelProfileRole.AGENT,
                temperatur=0.2,
            )

    def test_completely_unknown_field_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
            ModelProfile(
                provider="ollama",
                model="m",
                base_url="http://localhost",
                role=ModelProfileRole.AGENT,
                unknown_field="value",
            )


# ═══════════════════════════════════════════════════════════════════════════
# ModelProfilesConfig
# ═══════════════════════════════════════════════════════════════════════════


class TestModelProfilesConfig:
    """ModelProfilesConfig collection validation."""

    def test_single_profile(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        config = ModelProfilesConfig(profiles={"fast": p})
        assert len(config.profiles) == 1
        assert config.profiles["fast"] is p

    def test_multiple_profiles(self) -> None:
        p1 = ModelProfile(
            provider="ollama",
            model="m1",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        p2 = ModelProfile(
            provider="ollama",
            model="m2",
            base_url="http://localhost",
            temperature=0.2,
            role=ModelProfileRole.SUMMARIZER,
        )
        config = ModelProfilesConfig(profiles={"fast": p1, "post": p2})
        assert len(config.profiles) == 2

    def test_empty_profiles_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="at least one profile is required"):
            ModelProfilesConfig(profiles={})

    def test_empty_name_rejected(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        with pytest.raises(PydanticValidationError, match="profile name must not be empty"):
            ModelProfilesConfig(profiles={"": p})

    def test_whitespace_name_rejected(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        with pytest.raises(PydanticValidationError, match="profile name must not be empty"):
            ModelProfilesConfig(profiles={"   ": p})

    def test_unknown_field_rejected(self) -> None:
        p = ModelProfile(
            provider="ollama",
            model="m",
            base_url="http://localhost",
            role=ModelProfileRole.AGENT,
        )
        with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
            ModelProfilesConfig(profiles={"fast": p}, extra_field="x")  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# load_model_profiles — valid TOML parsing
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadModelProfilesValid:
    """Valid TOML files produce correct ModelProfilesConfig."""

    def test_single_agent_profile(self, tmp_path: Path) -> None:
        path = _write_toml(tmp_path / "config.toml", _VALID_AGENT_TOML)
        config = load_model_profiles(path)
        assert len(config.profiles) == 1
        p = config.profiles["fast"]
        assert p.provider == "ollama"
        assert p.model == "qwen-2.5-7b"
        assert p.base_url == "http://localhost:11434"
        assert p.temperature == 0.0
        assert p.keep_alive == "30m"
        assert p.role is ModelProfileRole.AGENT

    def test_multiple_profiles(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "fast-model"
base_url = "http://localhost:11434"
role = "agent"

[profiles.post]
provider = "ollama"
model = "heavy-model"
base_url = "http://192.168.1.50:11434"
temperature = 0.2
role = "summarizer"
"""
        path = _write_toml(tmp_path / "multi.toml", toml)
        config = load_model_profiles(path)
        assert len(config.profiles) == 2
        assert config.profiles["fast"].model == "fast-model"
        assert config.profiles["post"].model == "heavy-model"
        assert config.profiles["post"].temperature == 0.2

    def test_summarizer_role_from_toml(self, tmp_path: Path) -> None:
        toml = """\
[profiles.s]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "summarizer"
"""
        path = _write_toml(tmp_path / "s.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["s"].role is ModelProfileRole.SUMMARIZER

    def test_embedding_role_from_toml(self, tmp_path: Path) -> None:
        toml = """\
[profiles.e]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "embedding"
"""
        path = _write_toml(tmp_path / "e.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["e"].role is ModelProfileRole.EMBEDDING

    def test_optional_temperature_omitted(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "agent"
"""
        path = _write_toml(tmp_path / "no-temp.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["fast"].temperature is None

    def test_optional_keep_alive_omitted(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "agent"
"""
        path = _write_toml(tmp_path / "no-keep.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["fast"].keep_alive is None

    def test_localhost_endpoint(self, tmp_path: Path) -> None:
        toml = """\
[profiles.x]
provider = "ollama"
model = "m"
base_url = "http://localhost:11434"
role = "agent"
"""
        path = _write_toml(tmp_path / "local.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["x"].base_url == "http://localhost:11434"

    def test_lan_endpoint(self, tmp_path: Path) -> None:
        toml = """\
[profiles.x]
provider = "ollama"
model = "m"
base_url = "http://192.168.1.50:11434"
role = "agent"
"""
        path = _write_toml(tmp_path / "lan.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["x"].base_url == "http://192.168.1.50:11434"

    def test_https_endpoint(self, tmp_path: Path) -> None:
        toml = """\
[profiles.x]
provider = "ollama"
model = "m"
base_url = "https://some-provider.example"
role = "agent"
"""
        path = _write_toml(tmp_path / "https.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["x"].base_url == "https://some-provider.example"

    def test_unrelated_top_level_section_tolerated(self, tmp_path: Path) -> None:
        toml = """\
[timeouts]
request_seconds = 30

[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "agent"
"""
        path = _write_toml(tmp_path / "with-timeouts.toml", toml)
        config = load_model_profiles(path)
        assert len(config.profiles) == 1
        assert config.profiles["fast"].model == "m"

    def test_non_ollama_provider_from_toml(self, tmp_path: Path) -> None:
        toml = """\
[profiles.custom]
provider = "test-provider"
model = "test-model"
base_url = "http://localhost"
role = "agent"
"""
        path = _write_toml(tmp_path / "custom.toml", toml)
        config = load_model_profiles(path)
        assert config.profiles["custom"].provider == "test-provider"


# ═══════════════════════════════════════════════════════════════════════════
# load_model_profiles — TOML non-finite temperature
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadModelProfilesNonFiniteTemperature:
    """Non-finite temperature values rejected via TOML."""

    def test_nan_temperature_rejected(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
temperature = nan
role = "agent"
"""
        path = _write_toml(tmp_path / "nan.toml", toml)
        with pytest.raises(DndValidationError, match="temperature must not be NaN"):
            load_model_profiles(path)

    def test_inf_temperature_rejected(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
temperature = inf
role = "agent"
"""
        path = _write_toml(tmp_path / "inf.toml", toml)
        with pytest.raises(DndValidationError, match="temperature must not be Infinity"):
            load_model_profiles(path)

    def test_neg_inf_temperature_rejected(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
temperature = -inf
role = "agent"
"""
        path = _write_toml(tmp_path / "neg-inf.toml", toml)
        with pytest.raises(DndValidationError, match="temperature must not be Infinity"):
            load_model_profiles(path)


# ═══════════════════════════════════════════════════════════════════════════
# load_model_profiles — loader failures
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadModelProfilesFailures:
    """Loader error mapping."""

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "does-not-exist.toml"
        with pytest.raises(NotFoundError, match="Machine configuration file not found"):
            load_model_profiles(path)

    def test_malformed_toml(self, tmp_path: Path) -> None:
        path = _write_toml(tmp_path / "bad.toml", "this is not toml [[")
        with pytest.raises(DndValidationError, match="Failed to parse machine configuration TOML"):
            load_model_profiles(path)

    def test_missing_profiles_section(self, tmp_path: Path) -> None:
        path = _write_toml(tmp_path / "no-profiles.toml", "[timeouts]\nrequest_seconds = 30\n")
        with pytest.raises(DndValidationError, match="missing the required 'profiles' section"):
            load_model_profiles(path)

    def test_profiles_not_a_table(self, tmp_path: Path) -> None:
        path = _write_toml(tmp_path / "bad-profiles.toml", 'profiles = "not-a-table"\n')
        with pytest.raises(DndValidationError, match="Expected 'profiles' to be a table"):
            load_model_profiles(path)

    def test_empty_profiles_section(self, tmp_path: Path) -> None:
        path = _write_toml(tmp_path / "empty.toml", "[profiles]\n")
        with pytest.raises(DndValidationError, match="at least one profile is required"):
            load_model_profiles(path)

    def test_profile_missing_required_field(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
base_url = "http://localhost"
role = "agent"
"""
        path = _write_toml(tmp_path / "missing-model.toml", toml)
        with pytest.raises(DndValidationError, match="Invalid model profile configuration"):
            load_model_profiles(path)

    def test_profile_invalid_role(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "invalid-role"
"""
        path = _write_toml(tmp_path / "bad-role.toml", toml)
        with pytest.raises(DndValidationError, match="Invalid model profile configuration"):
            load_model_profiles(path)

    def test_profile_unknown_field_rejected(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "agent"
temperatur = 0.2
"""
        path = _write_toml(tmp_path / "typo.toml", toml)
        with pytest.raises(DndValidationError, match="Invalid model profile configuration"):
            load_model_profiles(path)

    def test_directory_instead_of_file(self, tmp_path: Path) -> None:
        path = tmp_path / "subdir"
        path.mkdir()
        # On Windows, path.exists() is True for a directory, but read_text
        # raises PermissionError (OSError) -> StorageError.
        with pytest.raises((NotFoundError, StorageError)):
            load_model_profiles(path)


# ═══════════════════════════════════════════════════════════════════════════
# Determinism / side-effect safety
# ═══════════════════════════════════════════════════════════════════════════


class TestNoSideEffects:
    """Tests require no Ollama, no network, no Vault, no home directory."""

    def test_uses_tmp_path_not_home(self, tmp_path: Path) -> None:
        toml = """\
[profiles.fast]
provider = "ollama"
model = "m"
base_url = "http://localhost"
role = "agent"
"""
        path = _write_toml(tmp_path / "safe.toml", toml)
        config = load_model_profiles(path)
        assert len(config.profiles) == 1
