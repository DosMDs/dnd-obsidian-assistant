"""Golden Vault integration tests for the Stage-6 session runtime stack.

Tests the real concrete stack against a temporary copy of the Golden Vault
fixture:

    Golden Vault copy (tmp_path)
        -> AuditService
        -> ObsidianSessionMetadataRepository
        -> ObsidianSessionEventRepository
        -> ObsidianWorldTimeRepository
        -> SessionRuntimeService
        -> SessionRecoveryService
        -> Typer CLI (CliRunner)

Every mutation test operates on a ``tmp_path`` copy of the committed
fixture at ``tests/fixtures/golden_test_vault/``.  The committed fixture
is never used as a writable target.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.cli.main import app
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
)
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)
from dnd_assistant.storage.world_time import (
    ObsidianWorldTimeRepository,
)

# -- Fixture source path ----------------------------------------------------------

_GOLDEN_SOURCE = Path(__file__).resolve().parent.parent / "fixtures" / "golden_test_vault"

# -- CLI runner -------------------------------------------------------------------

runner = CliRunner()

# -- Audit helper -----------------------------------------------------------------


def _make_audit_context(
    operation_id: str = "test-001",
    source: str = "test",
    session: str | None = None,
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
        source=source,
        session=session,
    )


# -- Temp-copy strategy -----------------------------------------------------------


def _copy_golden(tmp_path: Path) -> Path:
    """Create a writable temporary copy of the Golden Vault fixture.

    The destination path contains spaces and Unicode to exercise portable
    ``Path`` handling.
    """
    dest = tmp_path / "Golden Vault Kopiya"
    shutil.copytree(_GOLDEN_SOURCE, dest)
    return dest


def _golden_source_snapshot() -> dict[str, str]:
    """Return {relative_path: sha256} for every file under the Golden source.

    Used to prove the committed fixture is not mutated by tests.
    """
    snapshot: dict[str, str] = {}
    for path in sorted(_GOLDEN_SOURCE.rglob("*")):
        if path.is_file():
            rel = path.relative_to(_GOLDEN_SOURCE).as_posix()
            data = path.read_bytes()
            snapshot[rel] = hashlib.sha256(data).hexdigest()
    return snapshot


# -- Repository/service builders --------------------------------------------------


def _build_runtime(
    vault_root: Path,
) -> tuple[
    SessionRuntimeService,
    AuditService,
    ObsidianSessionMetadataRepository,
    ObsidianSessionEventRepository,
    ObsidianWorldTimeRepository,
]:
    audit_svc = AuditService(str(vault_root / "_system" / "audit" / "audit.jsonl"))
    meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)
    wt_repo = ObsidianWorldTimeRepository(vault_root, audit_svc)
    runtime = SessionRuntimeService(meta_repo, wt_repo, event_repo)
    return runtime, audit_svc, meta_repo, event_repo, wt_repo


def _build_recovery(vault_root: Path) -> SessionRecoveryService:
    audit_svc = AuditService(str(vault_root / "_system" / "audit" / "audit.jsonl"))
    recovery_repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
    return SessionRecoveryService(recovery_repo)


# -- Fixtures ---------------------------------------------------------------------


@pytest.fixture
def golden_copy(tmp_path: Path) -> Path:
    """Provide a writable temporary copy of the Golden Vault."""
    return _copy_golden(tmp_path)


@pytest.fixture
def source_snapshot() -> dict[str, str]:
    """Provide a byte-level snapshot of the committed Golden source."""
    return _golden_source_snapshot()


# ===== Source immutability proof ================================================


class TestGoldenSourceImmutability:
    """Prove the committed Golden fixture is never mutated by tests."""

    def test_source_unchanged_after_lifecycle(
        self, golden_copy: Path, source_snapshot: dict[str, str]
    ) -> None:
        """Run a full lifecycle on the copy, then verify source bytes unchanged."""
        runtime, audit_svc, _, _, wt_repo = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-lifecycle"),
        )
        runtime.record_note(
            "lifecycle note",
            audit=_make_audit_context(operation_id="note-lifecycle", session=session.id),
        )
        runtime.end_session(
            touched_entity_ids=["npc_varos"],
            audit=_make_audit_context(operation_id="end-lifecycle", session=session.id),
        )
        del runtime, audit_svc, wt_repo

        after = _golden_source_snapshot()
        assert after == source_snapshot, "Golden source fixture was modified by test lifecycle"

    def test_no_generated_artifacts_in_source(self, source_snapshot: dict[str, str]) -> None:
        """Verify no derived/generated artifacts exist in the committed source."""
        assert "_system/world_time.json" in source_snapshot
        assert "_system/audit/audit.jsonl" in source_snapshot
        assert "_system/fixture-manifest.json" in source_snapshot
        for sid in ("S001", "S002", "S003", "S004", "S005"):
            assert f"_system/raw/sessions/{sid}/events.jsonl" in source_snapshot
            assert f"_system/raw/sessions/{sid}/metadata.json" in source_snapshot
            assert f"_system/raw/sessions/{sid}/conversation.jsonl" in source_snapshot
            assert f"Sessions/{sid}/Session.md" in source_snapshot
            assert f"Sessions/{sid}/Notes.md" in source_snapshot
            assert f"Sessions/{sid}/Summary.md" in source_snapshot
            assert f"Sessions/{sid}/Recap.md" in source_snapshot
        sqlite_files = [k for k in source_snapshot if ".sqlite" in k or ".db" in k]
        temp_files = [k for k in source_snapshot if ".tmp" in k or "~" in k]
        assert not sqlite_files, f"Unexpected SQLite files in source: {sqlite_files}"
        assert not temp_files, f"Unexpected temp files in source: {temp_files}"


# ===== Baseline Stage-6 compatibility ===========================================


class TestGoldenBaselineCompatibility:
    """Prove the Golden Vault is a valid Stage-6 fixture."""

    def test_world_time_reads_canonical(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        wt_repo = ObsidianWorldTimeRepository(golden_copy, audit_svc)
        wt = wt_repo.get_current_world_time()
        assert wt.current_world_tick == 13800
        assert wt.revision == 1

    def test_five_completed_sessions(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        meta_repo = ObsidianSessionMetadataRepository(golden_copy, audit_svc)
        all_meta = meta_repo.list_session_metadata()
        assert len(all_meta) == 5
        for meta in all_meta:
            assert meta.session.status == "completed"

    def test_no_active_session(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        meta_repo = ObsidianSessionMetadataRepository(golden_copy, audit_svc)
        active = meta_repo.get_active_session()
        assert active is None

    def test_all_twenty_historical_events_load(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        event_repo = ObsidianSessionEventRepository(golden_copy, audit_svc)
        total = 0
        for sid in ("S001", "S002", "S003", "S004", "S005"):
            events = event_repo.list_events(sid)
            assert len(events) == 4, f"Expected 4 events for {sid}, got {len(events)}"
            for i, evt in enumerate(events, start=1):
                assert evt.event_id == f"evt_{i:03d}", (
                    f"Expected evt_{i:03d} for {sid}, got {evt.event_id}"
                )
            total += len(events)
        assert total == 20

    def test_clean_recovery_inspection(self, golden_copy: Path) -> None:
        recovery = _build_recovery(golden_copy)
        report = recovery.inspect_runtime()
        assert not report.has_issues, f"Expected clean recovery, got: {report.issues}"

    def test_next_session_id_is_s006(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        meta_repo = ObsidianSessionMetadataRepository(golden_copy, audit_svc)
        next_id = meta_repo.allocate_next_session_id()
        assert next_id == "S006"


# ===== S006 lifecycle ===========================================================


class TestGoldenS006Lifecycle:
    """Full S006 lifecycle against a Golden Vault copy."""

    def test_start_s006(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-s006"),
        )
        assert session.id == "S006"
        assert session.status == "active"
        assert session.world_tick_start == 13800
        assert session.revision == 1
        del runtime, audit_svc

    def test_note_persisted(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, event_repo, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-note"),
        )
        evt = runtime.record_note(
            "Testovaya zametka v Golden Vault",
            audit=_make_audit_context(operation_id="note-1", session=session.id),
        )
        assert evt.event_id == "evt_001"
        assert evt.world_tick == 13800
        assert evt.type == "note"

        events = event_repo.list_events(session.id)
        assert len(events) == 1
        assert events[0].event_id == "evt_001"
        del runtime, audit_svc, event_repo

    def test_status_after_start(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        runtime.start_session(
            audit=_make_audit_context(operation_id="start-status"),
        )
        active = runtime.get_active_session()
        assert active is not None
        assert active.id == "S006"
        assert active.status == "active"
        del runtime, audit_svc

    def test_end_s006_with_touched(self, golden_copy: Path) -> None:
        runtime, audit_svc, meta_repo, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-end"),
        )
        ended = runtime.end_session(
            touched_entity_ids=["npc_varos", "item_silver_key"],
            audit=_make_audit_context(operation_id="end-s006", session=session.id),
        )
        assert ended.status == "completed"
        assert ended.world_tick_end == 13800
        assert ended.revision == 2

        meta = meta_repo.get_session_metadata("S006")
        assert meta.session.status == "completed"
        assert meta.extra_fields.get("processing_status") == "pending"
        assert meta.session.real_finished_at is not None
        del runtime, audit_svc, meta_repo

    def test_no_active_after_end(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-noactive"),
        )
        runtime.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-noactive", session=session.id),
        )
        active = runtime.get_active_session()
        assert active is None
        del runtime, audit_svc


# ===== World time update during lifecycle =======================================


class TestGoldenWorldTimeUpdate:
    """Persisted world time is updated during the lifecycle."""

    def test_world_tick_advances(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        wt_repo = ObsidianWorldTimeRepository(golden_copy, audit_svc)
        wt_repo.set_current_world_time(
            13920,
            expected_revision=1,
            audit=_make_audit_context(operation_id="wt-advance", source="test"),
        )
        wt = wt_repo.get_current_world_time()
        assert wt.current_world_tick == 13920
        assert wt.revision == 2

    def test_note_uses_updated_tick(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        wt_repo = ObsidianWorldTimeRepository(golden_copy, audit_svc)
        wt_repo.set_current_world_time(
            13920,
            expected_revision=1,
            audit=_make_audit_context(operation_id="wt-pre-note", source="test"),
        )
        runtime = SessionRuntimeService(
            ObsidianSessionMetadataRepository(golden_copy, audit_svc),
            wt_repo,
            ObsidianSessionEventRepository(golden_copy, audit_svc),
        )
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-wt-note"),
        )
        evt = runtime.record_note(
            "after world time update",
            audit=_make_audit_context(operation_id="note-wt", session=session.id),
        )
        assert evt.world_tick == 13920
        del runtime, audit_svc, wt_repo

    def test_end_uses_updated_tick(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        wt_repo = ObsidianWorldTimeRepository(golden_copy, audit_svc)
        wt_repo.set_current_world_time(
            13920,
            expected_revision=1,
            audit=_make_audit_context(operation_id="wt-pre-end", source="test"),
        )
        runtime = SessionRuntimeService(
            ObsidianSessionMetadataRepository(golden_copy, audit_svc),
            wt_repo,
            ObsidianSessionEventRepository(golden_copy, audit_svc),
        )
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-wt-end"),
        )
        ended = runtime.end_session(
            touched_entity_ids=["npc_varos"],
            audit=_make_audit_context(operation_id="end-wt", session=session.id),
        )
        assert ended.world_tick_end == 13920
        del runtime, audit_svc, wt_repo


# ===== Audit correctness ========================================================


class TestGoldenAuditCorrectness:
    """All new mutations on the copy are audited."""

    def test_cli_source_in_audit(self, golden_copy: Path) -> None:
        result = runner.invoke(
            app,
            [
                "session",
                "start",
                "--vault",
                str(golden_copy),
            ],
        )
        assert result.exit_code == 0

        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        records = audit_svc.read_all()
        cli_records = [r for r in records if r.source == "cli"]
        assert len(cli_records) >= 1

    def test_test_source_world_time_audit(self, golden_copy: Path) -> None:
        audit_svc = AuditService(str(golden_copy / "_system" / "audit" / "audit.jsonl"))
        wt_repo = ObsidianWorldTimeRepository(golden_copy, audit_svc)
        wt_repo.set_current_world_time(
            13920,
            expected_revision=1,
            audit=_make_audit_context(operation_id="wt-audit-test", source="test"),
        )
        records = audit_svc.read_all()
        wt_records = [
            r for r in records if r.operation in ("world_time.initialize", "world_time.update")
        ]
        assert len(wt_records) >= 1
        assert wt_records[-1].source == "test"


# ===== Historical session immutability ==========================================


class TestGoldenHistoricalImmutability:
    """S001-S005 must remain byte-for-byte unchanged after S006 lifecycle."""

    def _snapshot_historical(self, vault_root: Path) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for sid in ("S001", "S002", "S003", "S004", "S005"):
            for subdir in ("Sessions", "_system/raw/sessions"):
                base = vault_root / subdir / sid
                if base.exists():
                    for p in base.rglob("*"):
                        if p.is_file():
                            rel = p.relative_to(vault_root).as_posix()
                            snapshot[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return snapshot

    def test_historical_sessions_unchanged_after_lifecycle(self, golden_copy: Path) -> None:
        before = self._snapshot_historical(golden_copy)

        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-hist"),
        )
        runtime.record_note(
            "note during S006",
            audit=_make_audit_context(operation_id="note-hist", session=session.id),
        )
        runtime.end_session(
            touched_entity_ids=["npc_varos"],
            audit=_make_audit_context(operation_id="end-hist", session=session.id),
        )
        del runtime, audit_svc

        after = self._snapshot_historical(golden_copy)
        assert after == before, "Historical S001-S005 files were modified"


# ===== Restart on Golden copy ===================================================


class TestGoldenRestart:
    """Restart lifecycle on a Golden Vault copy."""

    def test_restart_rediscovers_active_session(self, golden_copy: Path) -> None:
        runtime1, audit_svc1, _, _, _ = _build_runtime(golden_copy)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-restart"),
        )
        runtime1.record_note(
            "note before restart",
            audit=_make_audit_context(operation_id="note-restart", session=session1.id),
        )
        del runtime1, audit_svc1

        runtime2, audit_svc2, _, event_repo2, _ = _build_runtime(golden_copy)
        active = runtime2.get_active_session()
        assert active is not None
        assert active.id == session1.id
        assert active.status == "active"

        events = event_repo2.list_events(session1.id)
        assert len(events) == 1
        assert events[0].event_id == "evt_001"

        runtime2.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-restart", session=session1.id),
        )
        del runtime2, audit_svc2, event_repo2

    def test_historical_still_readable_after_restart(self, golden_copy: Path) -> None:
        runtime1, audit_svc1, _, _, _ = _build_runtime(golden_copy)
        session = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-hist-read"),
        )
        runtime1.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-hist-read", session=session.id),
        )
        del runtime1, audit_svc1

        _, audit_svc2, meta_repo2, _, _ = _build_runtime(golden_copy)
        for sid in ("S001", "S002", "S003", "S004", "S005"):
            meta = meta_repo2.get_session_metadata(sid)
            assert meta.session.status == "completed"
        del audit_svc2, meta_repo2


# ===== S006 raw artifact verification ===========================================


class TestGoldenS006Artifacts:
    """New S006 raw artifacts must follow Stage-6 contracts."""

    def test_s006_directories_exist(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        runtime.start_session(
            audit=_make_audit_context(operation_id="start-artifacts"),
        )
        del runtime, audit_svc

        assert (golden_copy / "Sessions" / "S006").is_dir()
        assert (golden_copy / "_system" / "raw" / "sessions" / "S006").is_dir()

    def test_s006_has_metadata_and_events_only(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        runtime.start_session(
            audit=_make_audit_context(operation_id="start-artifacts2"),
        )
        del runtime, audit_svc

        raw_dir = golden_copy / "_system" / "raw" / "sessions" / "S006"
        raw_files = {p.name for p in raw_dir.iterdir() if p.is_file()}
        assert "metadata.json" in raw_files
        assert "events.jsonl" in raw_files
        assert "conversation.jsonl" not in raw_files

        session_dir = golden_copy / "Sessions" / "S006"
        session_files = {p.name for p in session_dir.iterdir() if p.is_file()}
        assert "Session.md" not in session_files
        assert "Notes.md" not in session_files
        assert "Summary.md" not in session_files
        assert "Recap.md" not in session_files


# ===== Duplicate-start failure hardening ========================================


class TestGoldenDuplicateStart:
    """Starting while active must fail without side effects."""

    def test_duplicate_start_fails(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        runtime.start_session(
            audit=_make_audit_context(operation_id="start-first"),
        )
        with pytest.raises(ConflictError):
            runtime.start_session(
                audit=_make_audit_context(operation_id="start-second"),
            )
        del runtime, audit_svc

    def test_no_s007_created_on_duplicate_start(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        runtime.start_session(
            audit=_make_audit_context(operation_id="start-first2"),
        )
        try:
            runtime.start_session(
                audit=_make_audit_context(operation_id="start-second2"),
            )
        except ConflictError:
            pass
        del runtime, audit_svc

        assert not (golden_copy / "Sessions" / "S007").exists()
        assert not (golden_copy / "_system" / "raw" / "sessions" / "S007").exists()


# ===== Invalid-note failure hardening ===========================================


class TestGoldenInvalidNote:
    """Invalid note must fail without persisting."""

    def test_leading_whitespace_note_rejected(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, event_repo, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-inv-note"),
        )
        with pytest.raises((ValidationError, ConflictError, StorageError)):
            runtime.record_note(
                " leading whitespace",
                audit=_make_audit_context(operation_id="inv-note", session=session.id),
            )
        events = event_repo.list_events(session.id)
        assert len(events) == 0
        del runtime, audit_svc, event_repo

    def test_cli_invalid_note_exits_nonzero(self, golden_copy: Path) -> None:
        runner.invoke(
            app,
            [
                "session",
                "start",
                "--vault",
                str(golden_copy),
            ],
        )
        result = runner.invoke(
            app,
            [
                "note",
                " leading whitespace",
                "--vault",
                str(golden_copy),
            ],
        )
        assert result.exit_code != 0


# ===== Closed append immutability ===============================================


class TestGoldenClosedAppend:
    """Appending to a closed session must fail."""

    def test_append_after_close_raises(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, event_repo, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-close-append"),
        )
        runtime.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-close-append", session=session.id),
        )
        with pytest.raises((NotFoundError, ConflictError, StorageError)):
            runtime.record_note(
                "after close",
                audit=_make_audit_context(
                    operation_id="note-after-close",
                    session=session.id,
                ),
            )
        del runtime, audit_svc, event_repo

    def test_cli_note_after_close_exits_nonzero(self, golden_copy: Path) -> None:
        runner.invoke(
            app,
            [
                "session",
                "start",
                "--vault",
                str(golden_copy),
            ],
        )
        runner.invoke(
            app,
            [
                "session",
                "end",
                "--vault",
                str(golden_copy),
            ],
        )
        result = runner.invoke(
            app,
            [
                "note",
                "after close",
                "--vault",
                str(golden_copy),
            ],
        )
        assert result.exit_code != 0


# ===== Golden recovery integration ==============================================


class TestGoldenRecoveryIntegration:
    """Event-tail corruption and explicit repair on a Golden copy."""

    def test_event_tail_corruption_detected(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-recovery"),
        )
        runtime.record_note(
            "valid note before corruption",
            audit=_make_audit_context(operation_id="note-recovery", session=session.id),
        )
        del runtime, audit_svc

        # Remove trailing LF from events.jsonl
        events_path = golden_copy / "_system" / "raw" / "sessions" / session.id / "events.jsonl"
        data = events_path.read_bytes()
        assert data.endswith(b"\n")
        events_path.write_bytes(data.rstrip(b"\n"))

        recovery = _build_recovery(golden_copy)
        report = recovery.inspect_runtime()
        assert report.has_issues
        codes = {i.code for i in report.issues}
        assert "event_partial_tail" in codes
        assert any(i.recoverable for i in report.issues if i.code == "event_partial_tail")

    def test_cli_blocked_by_corrupt_event_tail(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-cli-block"),
        )
        runtime.record_note(
            "note before corruption",
            audit=_make_audit_context(operation_id="note-cli-block", session=session.id),
        )
        del runtime, audit_svc

        events_path = golden_copy / "_system" / "raw" / "sessions" / session.id / "events.jsonl"
        data = events_path.read_bytes()
        events_path.write_bytes(data.rstrip(b"\n"))

        result = runner.invoke(
            app,
            [
                "session",
                "status",
                "--vault",
                str(golden_copy),
            ],
        )
        assert result.exit_code != 0

    def test_explicit_event_tail_repair(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-repair"),
        )
        evt = runtime.record_note(
            "note to repair",
            audit=_make_audit_context(operation_id="note-repair", session=session.id),
        )
        del runtime, audit_svc

        events_path = golden_copy / "_system" / "raw" / "sessions" / session.id / "events.jsonl"
        data = events_path.read_bytes()
        events_path.write_bytes(data.rstrip(b"\n"))

        recovery = _build_recovery(golden_copy)
        result = recovery.repair_event_tail(
            session_id=session.id,
            audit=_make_audit_context(
                operation_id="repair-event",
                source="test",
                session=session.id,
            ),
        )
        assert result.after_hash is not None

        repaired = events_path.read_bytes()
        assert repaired.endswith(b"\n")

        _, audit_svc2, _, event_repo2, _ = _build_runtime(golden_copy)
        events = event_repo2.list_events(session.id)
        assert len(events) == 1
        assert events[0].event_id == evt.event_id
        del audit_svc2, event_repo2

    def test_post_repair_cli_works(self, golden_copy: Path) -> None:
        runtime, audit_svc, _, _, _ = _build_runtime(golden_copy)
        session = runtime.start_session(
            audit=_make_audit_context(operation_id="start-post-repair"),
        )
        runtime.record_note(
            "pre corruption",
            audit=_make_audit_context(operation_id="note-pre", session=session.id),
        )
        del runtime, audit_svc

        events_path = golden_copy / "_system" / "raw" / "sessions" / session.id / "events.jsonl"
        data = events_path.read_bytes()
        events_path.write_bytes(data.rstrip(b"\n"))

        recovery = _build_recovery(golden_copy)
        recovery.repair_event_tail(
            session_id=session.id,
            audit=_make_audit_context(
                operation_id="repair-post",
                source="test",
                session=session.id,
            ),
        )

        result = runner.invoke(
            app,
            [
                "note",
                "after repair",
                "--vault",
                str(golden_copy),
            ],
        )
        assert result.exit_code == 0, f"CLI failed after repair: {result.stderr}"


# ===== Symlink hardening ========================================================


class TestGoldenSymlinkHardening:
    """Unsafe session topology must be rejected."""

    def test_raw_session_symlink_rejected(self, golden_copy: Path, tmp_path: Path) -> None:
        target = tmp_path / "outside_target"
        target.mkdir()
        symlink_path = golden_copy / "_system" / "raw" / "sessions" / "S006"
        try:
            symlink_path.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("OS does not support symlink creation")

        recovery = _build_recovery(golden_copy)
        report = recovery.inspect_runtime()
        assert report.has_issues
        codes = {i.code for i in report.issues}
        assert "unsafe_session_path" in codes


# ===== CLI Golden lifecycle =====================================================


class TestGoldenCliLifecycle:
    """Real CLI sequence against a Golden Vault copy."""

    def test_full_cli_lifecycle(self, golden_copy: Path) -> None:
        result = runner.invoke(app, ["session", "status", "--vault", str(golden_copy)])
        assert result.exit_code == 0
        assert "Ak" in result.stdout or "нет" in result.stdout

        result = runner.invoke(app, ["session", "start", "--vault", str(golden_copy)])
        assert result.exit_code == 0, f"Start failed: {result.stderr}"
        assert "S006" in result.stdout

        result = runner.invoke(app, ["session", "status", "--vault", str(golden_copy)])
        assert result.exit_code == 0
        assert "S006" in result.stdout
        assert "active" in result.stdout

        result = runner.invoke(
            app,
            [
                "note",
                "Test note from CLI",
                "--vault",
                str(golden_copy),
            ],
        )
        assert result.exit_code == 0, f"Note failed: {result.stderr}"
        assert "evt_001" in result.stdout

        result = runner.invoke(
            app,
            [
                "session",
                "end",
                "--vault",
                str(golden_copy),
                "--touched-id",
                "npc_varos",
                "--touched-id",
                "item_silver_key",
            ],
        )
        assert result.exit_code == 0, f"End failed: {result.stderr}"
        assert "completed" in result.stdout

        result = runner.invoke(app, ["session", "status", "--vault", str(golden_copy)])
        assert result.exit_code == 0
        assert "Ak" in result.stdout or "нет" in result.stdout
