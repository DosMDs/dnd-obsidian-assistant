"""Smoke tests for the CLI entrypoint.

These tests ensure the console script entrypoint is correctly wired
and that the Typer application can be imported and invoked.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer
from typer.testing import CliRunner

from dnd_assistant.cli.main import app

runner = CliRunner()


def test_app_is_typer_instance() -> None:
    """The app object should be a Typer instance."""
    assert isinstance(app, typer.Typer)


def test_app_name_is_dnd() -> None:
    """The canonical CLI name should be 'dnd'."""
    assert app.info.name == "dnd"


def test_cli_help_via_runner() -> None:
    """``--help`` via CliRunner should exit with code 0 and show Russian UI."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "локальный помощник" in result.stdout


def test_cli_entrypoint_help_exits_ok() -> None:
    """``uv run dnd --help`` should exit with code 0 and show Russian UI.

    Uses ``PYTHONIOENCODING=utf-8`` to ensure Russian text is correctly
    captured on Windows regardless of the active console code page.
    """
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        ["uv", "run", "dnd", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(project_root),
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "локальный помощник" in result.stdout
