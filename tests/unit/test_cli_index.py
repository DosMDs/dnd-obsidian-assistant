"""Tests for CLI index rebuild command (S5-03).

Covers:
- dnd --help still works
- dnd index --help works
- dnd index rebuild --help works
- Rebuild against a temporary valid Vault succeeds
- Invalid Vault path fails cleanly
- After rebuild, the SQLite file exists at the canonical path
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.cli.main import app
from dnd_assistant.retrieval.index import FTS_INDEX_FILENAME

runner = CliRunner()


def _create_minimal_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    audit_dir = vault / "_system" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit.jsonl").write_text("", encoding="utf-8")
    return vault


class TestHelp:
    def test_dnd_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_index_help(self) -> None:
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0

    def test_index_rebuild_help(self) -> None:
        result = runner.invoke(app, ["index", "rebuild", "--help"])
        assert result.exit_code == 0


class TestRebuild:
    def test_rebuild_succeeds(self, tmp_path: Path) -> None:
        vault = _create_minimal_vault(tmp_path)
        result = runner.invoke(app, ["index", "rebuild", str(vault)])
        assert result.exit_code == 0
        assert "успешно" in result.stdout.lower()

        index_path = vault / "_system" / "indexes" / FTS_INDEX_FILENAME
        assert index_path.exists()

    def test_invalid_vault_fails(self, tmp_path: Path) -> None:
        invalid = tmp_path / "nonexistent"
        result = runner.invoke(app, ["index", "rebuild", str(invalid)])
        assert result.exit_code != 0
