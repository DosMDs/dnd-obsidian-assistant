"""CLI-level machine-config resolution tests (CFG-00).

These prove that the shared machine-settings boundary supplies the model-config
path across CLI surfaces when ``--config`` is omitted, that the explicit
``--config`` option keeps its precedence, and that a live run without any
resolvable path fails with a deterministic project error rather than a missing
Typer option.

All tests are offline.  Each test points ``DND_ENV_FILE`` at an explicit empty
file so no developer machine dotenv is read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnd_assistant.cli.main import app
from dnd_assistant.config.settings import (
    MACHINE_ENV_FILE_ENV,
    MODEL_CONFIG_PATH_ENV,
)

runner = CliRunner()


@pytest.fixture()
def empty_machine_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from any developer machine dotenv."""
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(empty))
    monkeypatch.delenv(MODEL_CONFIG_PATH_ENV, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def _minimal_vault(tmp_path: Path) -> Path:
    """A structurally initialized Vault sufficient for the recovery preflight."""
    vault = tmp_path / "vault"
    for relative in (
        "Characters/NPCs",
        "Locations",
        "Quests",
        "Items",
        "Sessions",
        "_system/audit",
        "_system/raw/sessions",
        "_system/indexes",
    ):
        (vault / relative).mkdir(parents=True, exist_ok=True)
    return vault


def test_ask_uses_dnd_model_config_path_when_config_omitted(
    tmp_path: Path, empty_machine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-models.toml"
    monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, str(missing))

    result = runner.invoke(
        app,
        ["ask", "hi", "--vault", str(_minimal_vault(tmp_path)), "--profile", "agent"],
    )

    assert result.exit_code == 1
    assert "Machine configuration file not found" in result.output


def test_ask_without_any_config_path_is_deterministic_error(
    tmp_path: Path, empty_machine_env: None
) -> None:
    result = runner.invoke(
        app,
        ["ask", "hi", "--vault", str(_vault(tmp_path)), "--profile", "agent"],
    )

    assert result.exit_code == 1
    assert "not set" in result.output
    assert MODEL_CONFIG_PATH_ENV in result.output


def test_explicit_config_option_keeps_precedence(
    tmp_path: Path, empty_machine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit (invalid) --config is rejected by the option, not the fallback."""
    monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, str(tmp_path / "settings-models.toml"))
    explicit_missing = tmp_path / "explicit-missing.toml"

    result = runner.invoke(
        app,
        [
            "ask",
            "hi",
            "--vault",
            str(_vault(tmp_path)),
            "--config",
            str(explicit_missing),
            "--profile",
            "agent",
        ],
    )

    # Typer validates the explicit option (exit 2); the settings fallback would
    # have produced the deterministic project error above (exit 1).
    assert result.exit_code == 2


def test_eval_ollama_live_uses_dnd_model_config_path(
    tmp_path: Path, empty_machine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-models.toml"
    monkeypatch.setenv(MODEL_CONFIG_PATH_ENV, str(missing))

    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            "--runtime",
            "ollama",
            "--profile",
            "agent",
            "--output",
            str(tmp_path / "report.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Machine configuration file not found" in result.output


def test_eval_deepseek_without_any_config_path_is_deterministic_error(
    tmp_path: Path, empty_machine_env: None
) -> None:
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            "--runtime",
            "deepseek",
            "--profile",
            "agent",
            "--output",
            str(tmp_path / "report.json"),
        ],
    )

    assert result.exit_code == 1
    assert "not set" in result.output
