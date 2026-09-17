"""TUI-03 lazy ``dnd tui`` launch surface.

Proves the launcher is invoked exactly once and that a normal CLI import does
not eagerly load the TUI package or Textual.
"""

from __future__ import annotations

import subprocess
import sys

from typer.testing import CliRunner

from dnd_assistant.cli.main import app as dnd_app
from dnd_assistant.tui import launcher


def test_dnd_tui_invokes_launcher_once(monkeypatch) -> None:
    calls: list[str] = []

    def fake_run() -> None:
        calls.append("run")

    monkeypatch.setattr(launcher, "run", fake_run)

    result = CliRunner().invoke(dnd_app, ["tui"])

    assert result.exit_code == 0
    assert calls == ["run"]


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
