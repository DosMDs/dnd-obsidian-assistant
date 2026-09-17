"""TUI-03 lazy ``dnd tui`` launch surface.

Proves the launcher is invoked exactly once and that a normal CLI import does
not eagerly load the TUI package or Textual.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.cli.main import app as dnd_app
from dnd_assistant.tui import launcher


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def _make_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        "[profiles.test-agent]\n"
        "provider='ollama'\n"
        "model='test'\n"
        "base_url='http://localhost:11434'\n"
        "role='agent'\n",
        encoding="utf-8",
    )
    return config


def test_dnd_tui_invokes_launcher_once(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, str, bool]] = []

    def fake_run(
        *,
        vault_root: Path,
        config_path: Path,
        profile_name: str,
        allow_agent_write: bool = False,
    ) -> None:
        calls.append((vault_root, profile_name, allow_agent_write))

    monkeypatch.setattr(launcher, "run", fake_run)

    vault = _make_vault(tmp_path)
    config = _make_config(tmp_path)
    result = CliRunner().invoke(
        dnd_app,
        [
            "tui",
            "--vault",
            str(vault),
            "--config",
            str(config),
            "--profile",
            "test-agent",
        ],
    )

    assert result.exit_code == 0
    assert calls == [(vault, "test-agent", False)]


def test_dnd_tui_allow_write_is_agent_ceiling(monkeypatch, tmp_path: Path) -> None:
    calls: list[bool] = []

    def fake_run(
        *,
        vault_root: Path,
        config_path: Path,
        profile_name: str,
        allow_agent_write: bool = False,
    ) -> None:
        assert profile_name == "test-agent"
        calls.append(allow_agent_write)

    monkeypatch.setattr(launcher, "run", fake_run)

    result = CliRunner().invoke(
        dnd_app,
        [
            "tui",
            "--vault",
            str(_make_vault(tmp_path)),
            "--config",
            str(_make_config(tmp_path)),
            "--profile",
            "test-agent",
            "--allow-write",
        ],
    )

    assert result.exit_code == 0
    assert calls == [True]


def test_dnd_tui_missing_vault_directory_exits_nonzero(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    missing = tmp_path / "does-not-exist"
    result = CliRunner().invoke(
        dnd_app,
        [
            "tui",
            "--vault",
            str(missing),
            "--config",
            str(config),
            "--profile",
            "test-agent",
        ],
    )
    # Typer rejects the nonexistent --vault path at parse time.
    assert result.exit_code == 2


def test_cli_import_does_not_eagerly_import_tui_or_textual() -> None:
    code = (
        "import sys\n"
        "import dnd_assistant.cli.main\n"
        "assert 'textual' not in sys.modules, 'textual imported eagerly'\n"
        "assert 'dnd_assistant.tui' not in sys.modules, 'tui imported eagerly'\n"
        "assert 'dnd_assistant.tui.launcher' not in sys.modules, 'launcher imported eagerly'\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
