"""S13-05 ``dnd time init`` deterministic admin surface tests.

The positive fixture is produced through the accepted S13-01 initializer, not a
hand-built pseudo-Vault, so the S13-01 initialization precondition is exercised
against a real initialized layout.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.application.vault_initialization import VaultInitializationStatus
from dnd_assistant.cli.main import app
from dnd_assistant.composition.audit_context import build_audit_context
from dnd_assistant.composition.vault_initialization import (
    compose_vault_initialization_service,
)
from dnd_assistant.storage.audit import AuditService

runner = CliRunner()


def _audit_path(root: Path) -> Path:
    return root / "_system" / "audit" / "audit.jsonl"


def _audit_count(root: Path) -> int:
    return len(AuditService(str(_audit_path(root))).read_all())


def _initialize(root: Path) -> None:
    root.mkdir(exist_ok=True)
    service = compose_vault_initialization_service(root)
    result = service.initialize(audit=build_audit_context(source="test", prefix="test-init"))
    assert result.status is VaultInitializationStatus.CREATED


def _minimal_layout_without_marker(root: Path) -> None:
    (root / "_system" / "audit").mkdir(parents=True)
    _audit_path(root).write_text("", encoding="utf-8")
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "Sessions").mkdir()


def _world_time(root: Path) -> dict:
    return json.loads((root / "_system" / "world_time.json").read_text(encoding="utf-8"))


def _invoke(root: Path, tick: int):
    return runner.invoke(app, ["time", "init", "--vault", str(root), f"--world-tick={tick}"])


def test_time_init_help_is_model_free() -> None:
    result = runner.invoke(app, ["time", "init", "--help"])
    assert result.exit_code == 0
    assert "--world-tick" in result.stdout
    assert "--config" not in result.stdout
    assert "--profile" not in result.stdout


def test_time_init_accepts_negative_tick_and_audits(tmp_path: Path) -> None:
    _initialize(tmp_path)
    before = _audit_count(tmp_path)

    result = _invoke(tmp_path, -5)

    assert result.exit_code == 0
    state = _world_time(tmp_path)
    assert state["current_world_tick"] == -5
    assert state["revision"] == 1

    records = AuditService(str(_audit_path(tmp_path))).read_all()
    added = records[before:]
    assert [record.operation for record in added] == [
        "world_time.initialize",
        "world_time.initialize",
    ]
    assert [record.phase for record in added] == ["intent", "committed"]


def test_time_init_refuses_existing_world_time(tmp_path: Path) -> None:
    _initialize(tmp_path)
    assert _invoke(tmp_path, 3).exit_code == 0

    second = _invoke(tmp_path, 99)

    assert second.exit_code != 0
    assert _world_time(tmp_path)["current_world_tick"] == 3


def test_time_init_absent_campaign_marker_is_refused(tmp_path: Path) -> None:
    _minimal_layout_without_marker(tmp_path)
    before = _audit_count(tmp_path)

    result = _invoke(tmp_path, 0)

    assert result.exit_code != 0
    assert "dnd init" in result.output
    assert not (tmp_path / "_system" / "world_time.json").exists()
    assert _audit_count(tmp_path) == before


def test_time_init_invalid_campaign_marker_fails_closed(tmp_path: Path) -> None:
    _minimal_layout_without_marker(tmp_path)
    (tmp_path / "_system" / "campaign.yaml").write_text(
        "schema_version: 2\ncampaign_id: camp_x\n", encoding="utf-8"
    )
    before = _audit_count(tmp_path)

    result = _invoke(tmp_path, 0)

    assert result.exit_code != 0
    assert not (tmp_path / "_system" / "world_time.json").exists()
    assert _audit_count(tmp_path) == before


def test_time_init_incomplete_layout_is_refused_without_repair(tmp_path: Path) -> None:
    _initialize(tmp_path)
    shutil.rmtree(tmp_path / "Items")
    before = _audit_count(tmp_path)

    result = _invoke(tmp_path, 0)

    assert result.exit_code != 0
    assert "dnd init" in result.output
    assert not (tmp_path / "Items").exists()
    assert not (tmp_path / "_system" / "world_time.json").exists()
    assert _audit_count(tmp_path) == before


def test_time_init_uninitialized_audit_topology_fails(tmp_path: Path) -> None:
    result = _invoke(tmp_path, 0)
    assert result.exit_code != 0
    assert not (tmp_path / "_system" / "world_time.json").exists()
