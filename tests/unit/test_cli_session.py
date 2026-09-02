"""Tests for CLI session commands and note command.

This module tests the session Typer subgroup (start/status/end) and the
note root command.  All tests use synthetic ``tmp_path`` Vaults and the
Typer ``CliRunner`` for invocation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dnd_assistant.cli.main import app
from dnd_assistant.cli.session import _new_operation_id, _now_utc
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

runner = CliRunner()


# ── Test Vault helpers ─────────────────────────────────────────────────────


def _create_vault(tmp_path: Path) -> Path:
    """Create a temporary Vault with canonical session runtime roots."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Sessions").mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "raw").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


def _init_world_time(vault_root: Path, tick: int = 13800) -> None:
    """Initialize world_time.json via the production repository."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_svc = AuditService(str(audit_log_path))
    wt_repo = ObsidianWorldTimeRepository(vault_root, audit_svc)
    ctx = AuditContext(
        operation_id="test-wt-init",
        real_time=datetime.now(UTC),
        source="test",
    )
    wt_repo.initialize_current_world_time(tick, audit=ctx)


def _make_audit_ctx(**overrides: Any) -> AuditContext:
    """Create a minimal AuditContext for test setup."""
    kwargs: dict[str, Any] = {
        "operation_id": "test-setup",
        "real_time": datetime.now(UTC),
        "source": "test",
    }
    kwargs.update(overrides)
    return AuditContext(**kwargs)


def _start_session_via_repo(vault_root: Path, tick: int = 13800) -> str:
    """Start a session through the production repository (not CLI)."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_svc = AuditService(str(audit_log_path))
    session_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)
    wt_repo = ObsidianWorldTimeRepository(vault_root, audit_svc)

    from dnd_assistant.application.session_runtime import SessionRuntimeService

    runtime = SessionRuntimeService(session_repo, wt_repo, event_repo)
    ctx = _make_audit_ctx(operation_id="test-start-session", source="test")
    session = runtime.start_session(audit=ctx)
    return session.id


# ── Help text tests ────────────────────────────────────────────────────────


class TestHelpText:
    """Verify help text for session subgroup and note command."""

    def test_session_help_exposes_start_status_end(self) -> None:
        result = runner.invoke(app, ["session", "--help"])
        assert result.exit_code == 0
        assert "start" in result.stdout
        assert "status" in result.stdout
        assert "end" in result.stdout

    def test_root_help_exposes_note(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "note" in result.stdout
        assert "session" in result.stdout

    def test_session_start_help(self) -> None:
        result = runner.invoke(app, ["session", "start", "--help"])
        assert result.exit_code == 0
        assert "--vault" in result.stdout

    def test_session_status_help(self) -> None:
        result = runner.invoke(app, ["session", "status", "--help"])
        assert result.exit_code == 0
        assert "--vault" in result.stdout

    def test_session_end_help(self) -> None:
        result = runner.invoke(app, ["session", "end", "--help"])
        assert result.exit_code == 0
        assert "--vault" in result.stdout
        assert "--touched-id" in result.stdout

    def test_note_help(self) -> None:
        result = runner.invoke(app, ["note", "--help"])
        assert result.exit_code == 0
        assert "--vault" in result.stdout


# ── Start command tests ────────────────────────────────────────────────────


class TestSessionStart:
    """Tests for ``dnd session start --vault PATH``."""

    def test_start_success(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        result = runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "S001" in result.stdout
        assert "active" in result.stdout
        assert "13800" in result.stdout

    def test_start_persists_s001(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        session_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta = session_repo.get_session_metadata("S001")
        assert meta.session.id == "S001"
        assert meta.session.status == "active"

    def test_start_output_contains_session_id(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        result = runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "S001" in result.stdout

    def test_start_uses_canonical_world_tick(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root, tick=999)

        result = runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "999" in result.stdout

    def test_start_uses_source_cli_audit(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        records = audit_svc.read_all()
        cli_records = [r for r in records if r.source == "cli"]
        assert len(cli_records) >= 2
        assert all(r.source == "cli" for r in cli_records)

    def test_start_with_existing_active_exits_1(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_start_with_missing_world_time_exits_1(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)

        result = runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_start_does_not_create_second_session_on_failure(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)

        runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        session_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        all_meta = session_repo.list_session_metadata()
        assert len(all_meta) == 0


# ── Status command tests ───────────────────────────────────────────────────


class TestSessionStatus:
    """Tests for ``dnd session status --vault PATH``."""

    def test_no_active_session_exits_0(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)

        result = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "Активной сессии нет" in result.stdout

    def test_active_session_shows_correct_id(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "S001" in result.stdout
        assert "active" in result.stdout

    def test_active_session_shows_start_tick(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root, tick=42)
        _start_session_via_repo(vault_root, tick=42)

        result = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "42" in result.stdout

    def test_status_reconstructs_from_vault(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result1 = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])
        assert result1.exit_code == 0

        result2 = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])
        assert result2.exit_code == 0
        assert "S001" in result2.stdout


# ── Note command tests ─────────────────────────────────────────────────────


class TestNoteCommand:
    """Tests for ``dnd note TEXT --vault PATH``."""

    def test_note_with_active_session_succeeds(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["note", "Hello, world!", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "evt_001" in result.stdout
        assert "note" in result.stdout

    def test_note_event_type_is_note(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        runner.invoke(app, ["note", "Test note", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)
        events = event_repo.list_events("S001")
        assert len(events) == 1
        assert events[0].type == "note"

    def test_note_text_preserved_exactly(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)
        text = "В комнате пахнет сыростью и старой бумагой."

        runner.invoke(app, ["note", text, "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)
        events = event_repo.list_events("S001")
        assert events[0].extra_fields.get("text") == text

    def test_note_event_id_persisted(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["note", "Test", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "evt_001" in result.stdout

    def test_note_world_tick_from_canonical(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root, tick=777)
        _start_session_via_repo(vault_root, tick=777)

        result = runner.invoke(app, ["note", "Test", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "777" in result.stdout

    def test_note_without_active_session_exits_1(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        result = runner.invoke(app, ["note", "Test", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    @pytest.mark.parametrize(
        ("invalid_text",),
        [
            pytest.param(" leading whitespace", id="leading-whitespace"),
            pytest.param("trailing whitespace ", id="trailing-whitespace"),
        ],
    )
    def test_note_invalid_text_exits_1(self, tmp_path: Path, invalid_text: str) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["note", invalid_text, "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    @pytest.mark.parametrize(
        ("invalid_text",),
        [
            pytest.param(" leading whitespace", id="leading-whitespace"),
            pytest.param("trailing whitespace ", id="trailing-whitespace"),
        ],
    )
    def test_note_invalid_text_does_not_persist(self, tmp_path: Path, invalid_text: str) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        runner.invoke(app, ["note", invalid_text, "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)
        events = event_repo.list_events("S001")
        assert len(events) == 0


# ── End command tests ──────────────────────────────────────────────────────


class TestSessionEnd:
    """Tests for ``dnd session end --vault PATH``."""

    def test_end_active_session_succeeds(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["session", "end", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "S001" in result.stdout
        assert "completed" in result.stdout

    def test_end_session_shows_world_tick_end(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root, tick=13800)
        _start_session_via_repo(vault_root, tick=13800)

        result = runner.invoke(app, ["session", "end", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "13800" in result.stdout

    def test_end_session_shows_revision(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(app, ["session", "end", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "2" in result.stdout

    def test_end_session_no_active_exits_1(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        result = runner.invoke(app, ["session", "end", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_note_after_end_exits_1(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        runner.invoke(app, ["session", "end", "--vault", str(vault_root)])
        result = runner.invoke(app, ["note", "Test after end", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_status_after_end_reports_no_active(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        runner.invoke(app, ["session", "end", "--vault", str(vault_root)])
        result = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])

        assert result.exit_code == 0
        assert "Активной сессии нет" in result.stdout

    def test_end_with_touched_ids(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        result = runner.invoke(
            app,
            [
                "session",
                "end",
                "--vault",
                str(vault_root),
                "--touched-id",
                "npc_varos",
                "--touched-id",
                "loc_blackwood",
            ],
        )

        assert result.exit_code == 0
        assert "2" in result.stdout

    def test_end_touched_ids_persisted(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        runner.invoke(
            app,
            [
                "session",
                "end",
                "--vault",
                str(vault_root),
                "--touched-id",
                "npc_varos",
            ],
        )

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        session_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
        meta = session_repo.get_session_metadata("S001")
        extras = meta.extra_fields
        assert extras.get("touched_entities") == ["npc_varos"]
        assert extras.get("processing_status") == "pending"


# ── Audit tests ────────────────────────────────────────────────────────────


class TestCliAudit:
    """Verify CLI mutations produce correct audit records."""

    def test_start_audit_source_is_cli(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        records = audit_svc.read_all()
        cli_records = [r for r in records if r.source == "cli"]
        assert len(cli_records) >= 2
        assert all(r.source == "cli" for r in cli_records)

    def test_start_audit_operation_id_non_empty(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        records = audit_svc.read_all()
        cli_records = [r for r in records if r.source == "cli"]
        for rec in cli_records:
            assert rec.operation_id
            assert rec.operation_id.startswith("cli-")

    def test_start_audit_real_time_aware(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        records = audit_svc.read_all()
        cli_records = [r for r in records if r.source == "cli"]
        for rec in cli_records:
            assert rec.real_time.tzinfo is not None

    def test_multiple_invocations_different_operation_ids(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root, tick=100)
        _start_session_via_repo(vault_root, tick=100)

        runner.invoke(app, ["note", "First", "--vault", str(vault_root)])
        runner.invoke(app, ["note", "Second", "--vault", str(vault_root)])

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(str(audit_log_path))
        records = audit_svc.read_all()
        note_records = [r for r in records if r.operation == "session.event.append"]
        note_op_ids = {r.operation_id for r in note_records}
        assert len(note_op_ids) >= 2


# ── Recovery preflight tests ───────────────────────────────────────────────


class TestRecoveryPreflight:
    """Verify recovery preflight blocks mutations on damaged state."""

    def test_corrupt_audit_blocks_start(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)

        audit_path = vault_root / "_system" / "audit" / "audit.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.rstrip("\n"), encoding="utf-8")

        result = runner.invoke(app, ["session", "start", "--vault", str(vault_root)])

        assert result.exit_code != 0
        assert "Обнаружено" in result.stderr

    def test_corrupt_audit_blocks_note(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        audit_path = vault_root / "_system" / "audit" / "audit.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.rstrip("\n"), encoding="utf-8")

        result = runner.invoke(app, ["note", "Test", "--vault", str(vault_root)])

        assert result.exit_code != 0
        assert "Обнаружено" in result.stderr

    def test_corrupt_audit_blocks_end(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        audit_path = vault_root / "_system" / "audit" / "audit.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.rstrip("\n"), encoding="utf-8")

        result = runner.invoke(app, ["session", "end", "--vault", str(vault_root)])

        assert result.exit_code != 0
        assert "Обнаружено" in result.stderr

    def test_corrupt_audit_does_not_mutate(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        audit_path = vault_root / "_system" / "audit" / "audit.jsonl"
        before_bytes = audit_path.read_bytes()
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.rstrip("\n"), encoding="utf-8")
        corrupt_bytes = audit_path.read_bytes()

        runner.invoke(app, ["note", "Test", "--vault", str(vault_root)])

        after_bytes = audit_path.read_bytes()
        assert after_bytes == corrupt_bytes
        assert after_bytes != before_bytes

    def test_status_blocks_on_partial_audit_tail(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        audit_path = vault_root / "_system" / "audit" / "audit.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.rstrip("\n"), encoding="utf-8")

        result = runner.invoke(app, ["session", "status", "--vault", str(vault_root)])

        assert result.exit_code != 0
        assert "Обнаружено" in result.stderr
        assert "audit_partial_tail" in result.stderr

    def test_status_read_only_on_partial_audit_tail(self, tmp_path: Path) -> None:
        vault_root = _create_vault(tmp_path)
        _init_world_time(vault_root)
        _start_session_via_repo(vault_root)

        audit_path = vault_root / "_system" / "audit" / "audit.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.rstrip("\n"), encoding="utf-8")
        corrupt_bytes = audit_path.read_bytes()

        runner.invoke(app, ["session", "status", "--vault", str(vault_root)])

        audit_after = audit_path.read_bytes()
        assert audit_after == corrupt_bytes


# ── Helper function unit tests ─────────────────────────────────────────────


class TestCliHelpers:
    """Direct tests for CLI helper functions."""

    def test_now_utc_returns_aware_datetime(self) -> None:
        dt = _now_utc()
        assert dt.tzinfo is not None

    def test_new_operation_id_has_prefix(self) -> None:
        oid = _new_operation_id("cli-test")
        assert oid.startswith("cli-test-")
        assert len(oid) > len("cli-test-")

    def test_new_operation_id_unique(self) -> None:
        ids = {_new_operation_id("cli-test") for _ in range(100)}
        assert len(ids) == 100


# ── Import / boundary tests ────────────────────────────────────────────────


@pytest.mark.usefixtures("restore_dnd_assistant_modules")
class TestCliSessionBoundaries:
    """Ensure CLI session module does not import restricted packages."""

    def test_cli_session_does_not_import_models(self) -> None:
        import importlib
        import sys

        for mod in list(sys.modules):
            if mod.startswith("dnd_assistant"):
                del sys.modules[mod]
        importlib.import_module("dnd_assistant.cli.session")
        loaded = {m for m in sys.modules if m.startswith("dnd_assistant.models")}
        assert not loaded, f"cli.session imported model modules: {loaded}"

    def test_cli_session_does_not_import_ollama(self) -> None:
        import importlib
        import sys

        for mod in list(sys.modules):
            if mod.startswith("dnd_assistant"):
                del sys.modules[mod]
        importlib.import_module("dnd_assistant.cli.session")
        loaded = {m for m in sys.modules if m.startswith("ollama")}
        assert not loaded, f"cli.session triggered ollama import: {loaded}"

    def test_cli_session_does_not_import_tools(self) -> None:
        import importlib
        import sys

        for mod in list(sys.modules):
            if mod.startswith("dnd_assistant"):
                del sys.modules[mod]
        importlib.import_module("dnd_assistant.cli.session")
        loaded = {m for m in sys.modules if m.startswith("dnd_assistant.tools")}
        assert not loaded, f"cli.session imported tool modules: {loaded}"
