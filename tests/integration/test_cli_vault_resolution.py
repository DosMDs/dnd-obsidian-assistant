"""CLI-level machine Vault-path resolution tests (CFG-02).

These prove that the shared machine-settings boundary supplies the Vault path
across CLI/TUI surfaces when ``--vault`` is omitted, that the explicit
``--vault`` option keeps highest precedence, that a machine-local path must be
absolute, and that a missing/invalid Vault produces a deterministic project
error rather than a Typer missing-option crash.

All tests are offline.  Each test points ``DND_ENV_FILE`` at an explicit empty
file (or a controlled dotenv) so no developer machine dotenv is read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnd_assistant.cli.main import app
from dnd_assistant.config.settings import (
    MACHINE_ENV_FILE_ENV,
    MODEL_CONFIG_PATH_ENV,
    VAULT_PATH_ENV,
)

runner = CliRunner()


@pytest.fixture()
def isolated_machine_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate tests from any developer machine dotenv and ambient settings."""
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(empty))
    for name in (VAULT_PATH_ENV, MODEL_CONFIG_PATH_ENV, "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return empty


def _minimal_vault(tmp_path: Path) -> Path:
    """A minimal Vault sufficient for ``dnd index rebuild``."""
    vault = tmp_path / "vault"
    audit = vault / "_system" / "audit"
    audit.mkdir(parents=True)
    (audit / "audit.jsonl").write_text("", encoding="utf-8")
    return vault


def _agent_config(tmp_path: Path) -> Path:
    config = tmp_path / "models.toml"
    config.write_text(
        "[profiles.test-agent]\n"
        "provider='ollama'\n"
        "model='test'\n"
        "base_url='http://localhost:11434'\n"
        "role='agent'\n",
        encoding="utf-8",
    )
    return config


# ── Environment / dotenv default ────────────────────────────────────────────


def test_process_env_vault_default_reaches_command(
    tmp_path: Path, isolated_machine_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _minimal_vault(tmp_path)
    monkeypatch.setenv(VAULT_PATH_ENV, str(vault))

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 0, result.output
    assert "успешно" in result.stdout.lower()


def test_dotenv_vault_default_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _minimal_vault(tmp_path)
    env_file = tmp_path / "machine.env"
    env_file.write_text(f"{VAULT_PATH_ENV}={vault}\n", encoding="utf-8")
    monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(env_file))
    monkeypatch.delenv(VAULT_PATH_ENV, raising=False)

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 0, result.output


def test_process_env_overrides_dotenv_for_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_vault = _minimal_vault(tmp_path / "from-dotenv")
    env_file = tmp_path / "machine.env"
    env_file.write_text(f"{VAULT_PATH_ENV}={dotenv_vault}\n", encoding="utf-8")
    monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(env_file))

    process_vault = _minimal_vault(tmp_path / "from-process")
    monkeypatch.setenv(VAULT_PATH_ENV, str(process_vault))

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 0, result.output
    assert (process_vault / "_system" / "indexes").is_dir()
    assert not (dotenv_vault / "_system" / "indexes").exists()


# ── Precedence and compatibility ────────────────────────────────────────────


def test_explicit_vault_overrides_env(
    tmp_path: Path, isolated_machine_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAULT_PATH_ENV, str(tmp_path / "env-missing-vault"))
    explicit = _minimal_vault(tmp_path)

    result = runner.invoke(app, ["index", "rebuild", "--vault", str(explicit)])

    assert result.exit_code == 0, result.output


def test_explicit_nonexistent_vault_keeps_typer_exit_two(
    tmp_path: Path, isolated_machine_env: Path
) -> None:
    result = runner.invoke(app, ["index", "rebuild", "--vault", str(tmp_path / "missing")])

    assert result.exit_code == 2


# ── Missing / invalid machine Vault ─────────────────────────────────────────


def test_missing_vault_is_deterministic_error(tmp_path: Path, isolated_machine_env: Path) -> None:
    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 1
    assert VAULT_PATH_ENV in result.output
    assert "not set" in result.output


def test_invalid_env_vault_follows_project_validation(
    tmp_path: Path, isolated_machine_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAULT_PATH_ENV, str(tmp_path / "does-not-exist"))

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 1
    assert "существующей директорией" in result.output


def test_relative_env_vault_rejected(
    tmp_path: Path, isolated_machine_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAULT_PATH_ENV, "relative/vault")

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 1
    assert "absolute" in result.output


# ── Separation from model configuration ─────────────────────────────────────


def test_env_vault_does_not_satisfy_model_config(
    tmp_path: Path, isolated_machine_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``DND_VAULT_PATH`` is independent from ``DND_MODEL_CONFIG_PATH``."""
    monkeypatch.setenv(VAULT_PATH_ENV, str(_minimal_vault(tmp_path)))

    result = runner.invoke(app, ["ask", "hi", "--profile", "agent"])

    assert result.exit_code == 1
    assert "not set" in result.output
    assert MODEL_CONFIG_PATH_ENV in result.output


# ── TUI uses the same resolution boundary ───────────────────────────────────


def test_tui_uses_env_vault_default(
    tmp_path: Path, isolated_machine_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dnd_assistant.tui import launcher

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv(VAULT_PATH_ENV, str(vault))
    config = _agent_config(tmp_path)
    seen: dict[str, object] = {}

    def fake_run(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(launcher, "run", fake_run)

    result = runner.invoke(app, ["tui", "--config", str(config), "--profile", "test-agent"])

    assert result.exit_code == 0, result.output
    assert seen["vault_root"] == vault
