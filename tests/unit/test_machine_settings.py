"""Machine-local settings boundary tests (CFG-00).

Covers the single typed machine-settings boundary: dotenv discovery/bootstrap
selector, source precedence, absolute model-config path semantics, credential
mapping/fail-closed resolution and secret redaction.  All tests are
deterministic and offline; no network, no real credentials and no developer
machine dotenv is read (explicit temporary dotenv sources are used).

The credential-boundary family is part of the curated ``provider_upgrade``
selection (it replaced the former ``models.credentials`` module coverage).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from dnd_assistant.config import settings as settings_module
from dnd_assistant.config.settings import (
    DEEPSEEK_API_KEY_ENV,
    MACHINE_ENV_FILE_ENV,
    MODEL_CONFIG_PATH_ENV,
    MachineSettings,
    load_machine_settings,
    load_model_config_path,
    machine_env_file,
    provider_credential_env_var,
    require_provider_api_key,
    resolve_model_config_path,
)
from dnd_assistant.errors import CredentialError
from dnd_assistant.errors import ValidationError as DndValidationError

pytestmark = pytest.mark.provider_upgrade

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "dnd_assistant"
_ALLOWED_ENV_MODULE = _SRC_ROOT / "config" / "settings.py"

_SECRET = "sk-test-secret-value-1234567890"


@pytest.fixture(autouse=True)
def _clean_machine_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with no ambient machine-local env or dotenv selector."""
    for name in (MACHINE_ENV_FILE_ENV, MODEL_CONFIG_PATH_ENV, DEEPSEEK_API_KEY_ENV):
        monkeypatch.delenv(name, raising=False)


def _write_env(tmp_path: Path, body: str, name: str = "machine.env") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ── Dotenv discovery / bootstrap selector ───────────────────────────────────


class TestMachineEnvFileDiscovery:
    def test_default_is_under_user_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings_module, "user_config_dir", lambda _app: str(tmp_path))
        assert machine_env_file() == tmp_path / ".env"

    def test_default_is_independent_of_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr(settings_module, "user_config_dir", lambda _app: str(config_dir))
        before = machine_env_file()
        other = tmp_path / "elsewhere"
        other.mkdir()
        monkeypatch.chdir(other)
        assert machine_env_file() == before

    def test_absolute_selector_is_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        selected = tmp_path / "custom.env"
        monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(selected))
        assert machine_env_file() == selected

    def test_relative_selector_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MACHINE_ENV_FILE_ENV, "relative/.env")
        with pytest.raises(DndValidationError, match=MACHINE_ENV_FILE_ENV):
            machine_env_file()

    def test_selector_cannot_be_redirected_by_dotenv(self, tmp_path: Path) -> None:
        """DND_ENV_FILE is not a settings field and is rejected as an unknown key."""
        redirected = _write_env(tmp_path, f"{MACHINE_ENV_FILE_ENV}={tmp_path / 'evil.env'}\n")
        with pytest.raises(DndValidationError):
            load_machine_settings(env_file=redirected)


# ── Source precedence ───────────────────────────────────────────────────────


class TestSourcePrecedence:
    def test_dotenv_values_are_loaded(self, tmp_path: Path) -> None:
        env_file = _write_env(
            tmp_path,
            f"{MODEL_CONFIG_PATH_ENV}={tmp_path / 'models.toml'}\n"
            f"{DEEPSEEK_API_KEY_ENV}={_SECRET}\n",
        )
        settings = load_machine_settings(env_file=env_file)
        assert settings.model_config_path == tmp_path / "models.toml"
        assert isinstance(settings.deepseek_api_key, SecretStr)

    def test_process_env_overrides_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = _write_env(tmp_path, f"{MODEL_CONFIG_PATH_ENV}={tmp_path / 'from-file.toml'}\n")
        monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, str(tmp_path / "from-env.toml"))
        assert (
            load_machine_settings(env_file=env_file).model_config_path == tmp_path / "from-env.toml"
        )

    def test_explicit_argument_overrides_process_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, str(tmp_path / "from-env.toml"))
        explicit = tmp_path / "explicit.toml"
        assert MachineSettings(model_config_path=explicit).model_config_path == explicit

    def test_missing_env_file_yields_defaults(self, tmp_path: Path) -> None:
        settings = load_machine_settings(env_file=tmp_path / "does-not-exist.env")
        assert settings.model_config_path is None
        assert settings.deepseek_api_key is None

    def test_empty_process_env_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = _write_env(tmp_path, f"{MODEL_CONFIG_PATH_ENV}={tmp_path / 'from-file.toml'}\n")
        monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, "")
        assert (
            load_machine_settings(env_file=env_file).model_config_path
            == tmp_path / "from-file.toml"
        )


# ── Unknown dedicated-dotenv keys ───────────────────────────────────────────


class TestDedicatedDotenvStrictness:
    def test_unknown_key_fails_fast_without_leaking_value(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "SECRETY_VALUE=topsecretleak\n")
        with pytest.raises(DndValidationError) as excinfo:
            load_machine_settings(env_file=env_file)
        assert "topsecretleak" not in str(excinfo.value)

    def test_unrelated_process_env_is_not_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DND_UNRELATED_SETTING", "x")
        monkeypatch.setenv("SOME_RANDOM_PROCESS_VAR", "y")
        env_file = _write_env(tmp_path, f"{MODEL_CONFIG_PATH_ENV}={tmp_path / 'models.toml'}\n")
        settings = load_machine_settings(env_file=env_file)
        assert settings.model_config_path == tmp_path / "models.toml"


# ── Model-config path semantics ─────────────────────────────────────────────


class TestModelConfigPath:
    def test_absolute_path_accepted(self, tmp_path: Path) -> None:
        absolute = tmp_path / "models.toml"
        assert MachineSettings(model_config_path=absolute).model_config_path == absolute

    def test_relative_path_rejected(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, f"{MODEL_CONFIG_PATH_ENV}=relative/models.toml\n")
        with pytest.raises(DndValidationError, match="absolute"):
            load_machine_settings(env_file=env_file)

    def test_resolve_prefers_explicit(self, tmp_path: Path) -> None:
        settings = MachineSettings(model_config_path=tmp_path / "from-settings.toml")
        explicit = tmp_path / "explicit.toml"
        assert resolve_model_config_path(explicit, settings) == explicit

    def test_resolve_uses_settings(self, tmp_path: Path) -> None:
        settings = MachineSettings(model_config_path=tmp_path / "from-settings.toml")
        assert resolve_model_config_path(None, settings) == tmp_path / "from-settings.toml"

    def test_resolve_missing_raises(self) -> None:
        with pytest.raises(DndValidationError, match="not set"):
            resolve_model_config_path(None, MachineSettings())

    def test_load_model_config_path_resolves_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(tmp_path / "absent.env"))
        monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, str(tmp_path / "models.toml"))
        assert load_model_config_path(None) == tmp_path / "models.toml"


# ── Credential mapping / fail-closed / redaction ────────────────────────────


class TestCredentialMapping:
    def test_deepseek_env_var_name(self) -> None:
        assert DEEPSEEK_API_KEY_ENV == "DEEPSEEK_API_KEY"
        assert provider_credential_env_var("deepseek") == "DEEPSEEK_API_KEY"

    def test_unknown_provider_raises_validation_error(self) -> None:
        with pytest.raises(DndValidationError, match="No machine-local credential"):
            provider_credential_env_var("unknown-provider")


class TestProviderApiKey:
    def test_present_returns_secretstr(self) -> None:
        settings = MachineSettings(deepseek_api_key=SecretStr(_SECRET))
        result = settings.provider_api_key("deepseek")
        assert isinstance(result, SecretStr)
        assert result.get_secret_value() == _SECRET

    def test_missing_fails_closed(self) -> None:
        with pytest.raises(CredentialError, match="DEEPSEEK_API_KEY"):
            MachineSettings().provider_api_key("deepseek")

    def test_empty_fails_closed(self) -> None:
        with pytest.raises(CredentialError, match="Missing or empty"):
            MachineSettings(deepseek_api_key=SecretStr("")).provider_api_key("deepseek")

    def test_whitespace_only_fails_closed(self) -> None:
        with pytest.raises(CredentialError, match="Missing or empty"):
            MachineSettings(deepseek_api_key=SecretStr("   \t  ")).provider_api_key("deepseek")

    def test_unknown_provider_performs_no_lookup(self) -> None:
        with pytest.raises(DndValidationError, match="No machine-local credential"):
            MachineSettings().provider_api_key("unknown-provider")

    def test_require_helper_present(self) -> None:
        assert (
            require_provider_api_key("deepseek", SecretStr(_SECRET)).get_secret_value() == _SECRET
        )

    def test_require_helper_none_fails_closed(self) -> None:
        with pytest.raises(CredentialError, match="DEEPSEEK_API_KEY"):
            require_provider_api_key("deepseek", None)


class TestSecretNonExposure:
    def test_repr_and_str_do_not_reveal_secret(self) -> None:
        settings = MachineSettings(deepseek_api_key=SecretStr(_SECRET))
        assert _SECRET not in repr(settings)
        assert _SECRET not in str(settings)

    def test_error_text_does_not_reveal_other_env_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("UNRELATED_SECRET", _SECRET)
        with pytest.raises(CredentialError) as excinfo:
            MachineSettings().provider_api_key("deepseek")
        assert _SECRET not in str(excinfo.value)


# ── No import-time / call-time environment mutation ─────────────────────────


class TestNoEnvironmentMutation:
    def test_load_does_not_mutate_environ(self, tmp_path: Path) -> None:
        env_file = _write_env(
            tmp_path,
            f"{MODEL_CONFIG_PATH_ENV}={tmp_path / 'models.toml'}\n"
            f"{DEEPSEEK_API_KEY_ENV}={_SECRET}\n",
        )
        before = dict(os.environ)
        load_machine_settings(env_file=env_file)
        assert dict(os.environ) == before


# ── Static boundary: one environment reader ─────────────────────────────────


def _env_access_offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in {"environ", "getenv", "putenv"}
        ):
            offenders.append(f"os.{node.attr}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "load_dotenv":
                offenders.append("load_dotenv")
    return offenders


def test_only_config_settings_reads_environment_in_src() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path == _ALLOWED_ENV_MODULE:
            continue
        found = _env_access_offenders(path)
        if found:
            offenders.append(f"{path.relative_to(_SRC_ROOT)}: {sorted(found)}")
    assert not offenders, f"environment access must stay in config/settings.py: {offenders}"


def test_static_boundary_detector_is_not_vacuous(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import os\nx = os.environ.get('A')\n", encoding="utf-8")
    assert _env_access_offenders(sample)
