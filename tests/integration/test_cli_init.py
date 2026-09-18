"""S13-01 CLI tests for ``dnd init``."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.cli.main import app

GOLDEN_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "golden_test_vault"

runner = CliRunner()


def _invoke(*args: str):
    return runner.invoke(app, ["init", *args])


class TestInitCliSuccess:
    def test_fresh_vault_created_russian_output(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        result = _invoke("--vault", str(root))
        assert result.exit_code == 0, result.stderr
        assert "Vault инициализирован." in result.stdout
        assert "Кампания:" in result.stdout
        assert (root / "_system" / "campaign.yaml").is_file()

    def test_second_run_already_initialized(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        _invoke("--vault", str(root))
        result = _invoke("--vault", str(root))
        assert result.exit_code == 0
        assert "Vault уже инициализирован." in result.stdout

    def test_partial_layout_repaired_output(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        _invoke("--vault", str(root))
        shutil.rmtree(root / "Locations")
        result = _invoke("--vault", str(root))
        assert result.exit_code == 0
        assert "Инициализация завершена" in result.stdout

    def test_golden_copy_recognized(self, tmp_path: Path) -> None:
        root = tmp_path / "golden"
        shutil.copytree(GOLDEN_VAULT, root)
        result = _invoke("--vault", str(root))
        assert result.exit_code == 0
        assert "Vault уже инициализирован." in result.stdout
        assert "camp_golden_001" in result.stdout


class TestInitCliErrors:
    def test_missing_vault_root_russian_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        result = _invoke("--vault", str(missing))
        assert result.exit_code == 1
        assert "Ошибка:" in result.stderr
        assert "существующей директорией" in result.stderr
        assert not missing.exists()

    def test_file_vault_root_rejected(self, tmp_path: Path) -> None:
        a_file = tmp_path / "vault.txt"
        a_file.write_text("not a directory", encoding="utf-8")
        result = _invoke("--vault", str(a_file))
        assert result.exit_code == 1
        assert "Ошибка:" in result.stderr

    def test_conflicting_managed_path_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        (root / "Locations").write_text("user file", encoding="utf-8")
        result = _invoke("--vault", str(root))
        assert result.exit_code == 1
        assert "Ошибка:" in result.stderr
        assert not (root / "_system" / "campaign.yaml").exists()
        assert (root / "Locations").read_text(encoding="utf-8") == "user file"

    def test_invalid_existing_config_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        (root / "_system").mkdir(parents=True)
        config = root / "_system" / "campaign.yaml"
        config.write_text("schema_version: 42\ncampaign_id: x\n", encoding="utf-8")
        result = _invoke("--vault", str(root))
        assert result.exit_code == 1
        assert config.read_text(encoding="utf-8") == "schema_version: 42\ncampaign_id: x\n"

    def test_help_is_russian(self) -> None:
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "Инициализировать" in result.stdout
