"""S13-05 ``dnd time init`` deterministic admin surface tests."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.cli.main import app
from dnd_assistant.storage.audit import AuditService

runner = CliRunner()


def _write_vault(root: Path) -> None:
    (root / "_system" / "audit").mkdir(parents=True)
    (root / "_system" / "audit" / "audit.jsonl").write_text("", encoding="utf-8")
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "Sessions").mkdir()


def _world_time(root: Path) -> dict:
    return json.loads((root / "_system" / "world_time.json").read_text(encoding="utf-8"))


def test_time_init_help_is_model_free() -> None:
    result = runner.invoke(app, ["time", "init", "--help"])
    assert result.exit_code == 0
    assert "--world-tick" in result.stdout
    assert "--config" not in result.stdout
    assert "--profile" not in result.stdout


def test_time_init_accepts_negative_tick_and_audits(tmp_path: Path) -> None:
    _write_vault(tmp_path)

    result = runner.invoke(app, ["time", "init", "--vault", str(tmp_path), "--world-tick=-5"])

    assert result.exit_code == 0
    state = _world_time(tmp_path)
    assert state["current_world_tick"] == -5
    assert state["revision"] == 1

    records = AuditService(str(tmp_path / "_system" / "audit" / "audit.jsonl")).read_all()
    operations = [record.operation for record in records]
    phases = [record.phase for record in records]
    assert operations == ["world_time.initialize", "world_time.initialize"]
    assert phases == ["intent", "committed"]


def test_time_init_refuses_existing_world_time(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    first = runner.invoke(app, ["time", "init", "--vault", str(tmp_path), "--world-tick=3"])
    assert first.exit_code == 0

    second = runner.invoke(app, ["time", "init", "--vault", str(tmp_path), "--world-tick=99"])

    assert second.exit_code != 0
    assert _world_time(tmp_path)["current_world_tick"] == 3


def test_time_init_uninitialized_audit_topology_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["time", "init", "--vault", str(tmp_path), "--world-tick=0"])
    assert result.exit_code != 0
    assert not (tmp_path / "_system" / "world_time.json").exists()
