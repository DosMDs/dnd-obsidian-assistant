"""S6-05 integration tests — session restart lifecycle with concrete repositories.

Tests cover:
- Restart lifecycle: start -> notes/events -> destroy -> reconstruct -> status works
- Event ID continuity after reconstruction
- World time read from persisted world_time.json after reconstruction
- End session after reconstruction
- Completed session survives reconstruction
- Closed events readable after reconstruction
- Append to completed session rejected after reconstruction
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
)
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.world_time import (
    ObsidianWorldTimeRepository,
)

# ── Helpers ──────────────────────────────────────────────────────────────────────


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


def _create_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Sessions").mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "raw").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


def _create_audit_service(vault_root: Path) -> AuditService:
    return AuditService(vault_root / "_system" / "audit" / "audit.jsonl")


def _init_world_time(vault_root: Path) -> None:
    audit_svc = _create_audit_service(vault_root)
    wt_repo = ObsidianWorldTimeRepository(vault_root, audit_svc)
    wt_repo.initialize_current_world_time(
        13800,
        audit=_make_audit_context(operation_id="wt-init", source="test"),
    )


def _build_runtime(
    vault_root: Path,
) -> tuple[
    SessionRuntimeService,
    AuditService,
    ObsidianSessionMetadataRepository,
    ObsidianSessionEventRepository,
    ObsidianWorldTimeRepository,
]:
    audit_svc = _create_audit_service(vault_root)
    meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)
    wt_repo = ObsidianWorldTimeRepository(vault_root, audit_svc)
    runtime = SessionRuntimeService(meta_repo, wt_repo, event_repo)
    return runtime, audit_svc, meta_repo, event_repo, wt_repo


# ── Fixtures ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    return _create_vault(tmp_path)


# ── TestRestartLifecycle ─────────────────────────────────────────────────────────


class TestRestartLifecycle:
    def test_start_notes_events_destroy_reconstruct_status_works(self, vault_root: Path) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, _, _ = _build_runtime(vault_root)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        assert session1.status == "active"
        runtime1.record_note(
            "first note",
            audit=_make_audit_context(operation_id="note-1", session=session1.id),
        )
        del runtime1, audit1

        runtime2, audit2, _, _, _ = _build_runtime(vault_root)
        active = runtime2.get_active_session()
        assert active is not None
        assert active.id == session1.id
        assert active.status == "active"
        del runtime2, audit2

        runtime3, audit3, _, _, _ = _build_runtime(vault_root)
        active3 = runtime3.get_active_session()
        assert active3 is not None
        assert active3.id == session1.id
        del runtime3, audit3


# ── TestRestartEventIdContinuity ─────────────────────────────────────────────────


class TestRestartEventIdContinuity:
    def test_event_ids_continue_after_reconstruction(self, vault_root: Path) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, _, _ = _build_runtime(vault_root)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        evt1 = runtime1.record_note(
            "first",
            audit=_make_audit_context(operation_id="evt-1", session=session1.id),
        )
        assert evt1.event_id == "evt_001"
        evt2 = runtime1.record_note(
            "second",
            audit=_make_audit_context(operation_id="evt-2", session=session1.id),
        )
        assert evt2.event_id == "evt_002"
        del runtime1, audit1

        runtime2, audit2, _, event_repo2, _ = _build_runtime(vault_root)
        evt3 = runtime2.record_note(
            "third",
            audit=_make_audit_context(operation_id="evt-3", session=session1.id),
        )
        assert evt3.event_id == "evt_003"
        all_events = event_repo2.list_events(session1.id)
        assert len(all_events) == 3
        ids = [e.event_id for e in all_events]
        assert ids == ["evt_001", "evt_002", "evt_003"]
        del runtime2, audit2


# ── TestRestartWorldTime ─────────────────────────────────────────────────────────


class TestRestartWorldTime:
    def test_current_world_time_read_from_persisted_state(self, vault_root: Path) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, _, wt_repo1 = _build_runtime(vault_root)
        _ = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        wt1 = wt_repo1.get_current_world_time()
        assert wt1.current_world_tick == 13800
        del runtime1, audit1, wt_repo1

        _, audit2, _, _, wt_repo2 = _build_runtime(vault_root)
        wt2 = wt_repo2.get_current_world_time()
        assert wt2.current_world_tick == 13800
        assert wt2.revision >= 1
        del audit2, wt_repo2


# ── TestRestartEndSession ────────────────────────────────────────────────────────


class TestRestartEndSession:
    def test_active_session_can_be_ended_after_reconstruction(self, vault_root: Path) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, _, _ = _build_runtime(vault_root)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        del runtime1, audit1

        runtime2, audit2, _, _, _ = _build_runtime(vault_root)
        ended = runtime2.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-1", session=session1.id),
        )
        assert ended.status == "completed"
        assert ended.id == session1.id
        assert ended.real_finished_at is not None
        assert ended.world_tick_end is not None
        del runtime2, audit2


# ── TestRestartCompletedSession ──────────────────────────────────────────────────


class TestRestartCompletedSession:
    def test_completed_session_survives_reconstruction(self, vault_root: Path) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, _, _ = _build_runtime(vault_root)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        runtime1.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-1", session=session1.id),
        )
        del runtime1, audit1

        runtime2, audit2, meta_repo2, _, _ = _build_runtime(vault_root)
        meta = meta_repo2.get_session_metadata(session1.id)
        assert meta.session.status == "completed"
        assert meta.session.real_finished_at is not None
        assert meta.session.revision == 2
        active = runtime2.get_active_session()
        assert active is None
        del runtime2, audit2, meta_repo2

        runtime3, audit3, meta_repo3, _, _ = _build_runtime(vault_root)
        meta3 = meta_repo3.get_session_metadata(session1.id)
        assert meta3.session.status == "completed"
        assert meta3.session.revision == 2
        active3 = runtime3.get_active_session()
        assert active3 is None
        del runtime3, audit3, meta_repo3


# ── TestRestartClosedEventsReadable ──────────────────────────────────────────────


class TestRestartClosedEventsReadable:
    def test_closed_events_readable_after_reconstruction(self, vault_root: Path) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, event_repo1, _ = _build_runtime(vault_root)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        runtime1.record_note(
            "during session",
            audit=_make_audit_context(operation_id="note-1", session=session1.id),
        )
        runtime1.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-1", session=session1.id),
        )
        events1 = event_repo1.list_events(session1.id)
        assert len(events1) == 1
        del runtime1, audit1, event_repo1

        _, audit2, _, event_repo2, _ = _build_runtime(vault_root)
        events2 = event_repo2.list_events(session1.id)
        assert len(events2) == 1
        assert events2[0].event_id == "evt_001"
        assert events2[0].type == "note"
        del audit2, event_repo2


# ── TestRestartClosedAppendRejected ──────────────────────────────────────────────


class TestRestartClosedAppendRejected:
    def test_append_to_completed_session_still_rejected_after_reconstruction(
        self, vault_root: Path
    ) -> None:
        _init_world_time(vault_root)
        runtime1, audit1, _, _, _ = _build_runtime(vault_root)
        session1 = runtime1.start_session(
            audit=_make_audit_context(operation_id="start-1"),
        )
        runtime1.end_session(
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="end-1", session=session1.id),
        )
        del runtime1, audit1

        _, audit2, _, event_repo2, _ = _build_runtime(vault_root)
        with pytest.raises((StorageError, ConflictError)):
            event_repo2.append_event(
                session_id=session1.id,
                event_type="note",
                real_time=datetime(2026, 8, 31, 19, 0, 0, tzinfo=UTC),
                world_tick=15000,
                extra_fields={"text": "after close"},
                audit=_make_audit_context(
                    operation_id="append-after-close",
                    session=session1.id,
                ),
            )
        del audit2, event_repo2
