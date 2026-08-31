"""S6-C04 event lifecycle tests — closed append and close/event races.

Covers:
- Closed-session event append raises ConflictError
- Closed-session list_events still succeeds
- Close wins after event intent, before event append
- Close wins after physical event append
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dnd_assistant.storage.session_events as _events_mod
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
)
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
    _serialize,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _active_session(**overrides: object) -> Session:
    kwargs = {
        "id": "S006",
        "type": "session",
        "status": "active",
        "real_started_at": datetime(2026, 8, 31, 15, 0, 0, tzinfo=UTC),
        "real_finished_at": None,
        "world_tick_start": 13800,
        "world_tick_end": None,
        "processed": False,
        "processed_model_profile": None,
        "revision": 1,
    }
    kwargs.update(overrides)
    return Session(**kwargs)  # type: ignore[arg-type]


def _make_audit_context(
    operation_id: str = "test-op-001",
    source: str = "test",
    session: str | None = None,
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime.now(UTC),
        source=source,
        session=session,
    )


def _read_audit_records(vault_root: Path) -> list[dict]:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    if not log_path.exists():
        return []
    records: list[dict] = []
    text = log_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Sessions").mkdir(parents=True, exist_ok=True)
    (root / "_system" / "raw" / "sessions").mkdir(parents=True, exist_ok=True)
    audit_dir = root / "_system" / "audit"
    audit_dir.mkdir(parents=True)
    return root


@pytest.fixture
def audit_service(vault_root: Path) -> AuditService:
    audit_log = vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(audit_log)


@pytest.fixture
def meta_repo(vault_root: Path, audit_service: AuditService) -> ObsidianSessionMetadataRepository:
    return ObsidianSessionMetadataRepository(vault_root, audit_service)


@pytest.fixture
def event_repo(vault_root: Path, audit_service: AuditService) -> ObsidianSessionEventRepository:
    return ObsidianSessionEventRepository(vault_root, audit_service)


def _create_active_session(
    vault_root: Path,
    session_id: str = "S006",
) -> None:
    session_dir = vault_root / "_system" / "raw" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    events_path = session_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    session = _active_session(id=session_id)
    meta = RawSessionMetadata(session=session)
    text = _serialize(meta)
    metadata_path = session_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _make_event_line(event_id: str = "evt_001") -> str:
    return (
        '{"event_id":"' + event_id + '","real_time":"2026-08-31T18:30:00+00:00",'
        '"type":"note","world_tick":14500}\n'
    )


# ── Closed-session event append ────────────────────────────────────────────────


class TestClosedSessionEventAppend:
    def test_list_events_succeeds_on_closed_session(
        self, vault_root: Path, meta_repo, event_repo
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="close-list"),
        )
        events = event_repo.list_events("S006")
        assert events == []

    def test_append_event_on_closed_session_raises_conflict(
        self, vault_root: Path, meta_repo, event_repo
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_before = events_path.read_bytes()

        meta_repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="close-append"),
        )

        with pytest.raises(ConflictError, match="not active"):
            event_repo.append_event(
                "S006",
                event_type="note",
                real_time=datetime(2026, 8, 31, 19, 0, 0, tzinfo=UTC),
                world_tick=16000,
                extra_fields={"text": "should fail"},
                audit=_make_audit_context(operation_id="post-close"),
            )

        assert events_path.read_bytes() == events_before

        records = _read_audit_records(vault_root)
        post_recs = [r for r in records if r.get("operation_id") == "post-close"]
        assert len(post_recs) == 0


# ── Close wins after event intent, before event append ─────────────────────────


class TestCloseWinsAfterEventIntent:
    def test_close_wins_after_event_intent_before_append(
        self, vault_root: Path, meta_repo, event_repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_before = events_path.read_bytes()

        original_append = event_repo._audit_service.append
        call_count = 0

        def close_after_event_intent(record):
            nonlocal call_count
            call_count += 1
            original_append(record)
            if call_count == 1:
                # After event intent, close the session
                meta_repo.close_session(
                    "S006",
                    expected_revision=1,
                    world_tick_end=15000,
                    touched_entity_ids=[],
                    audit=_make_audit_context(
                        operation_id="race-close-after-event-intent",
                        session="S006",
                    ),
                )

        monkeypatch.setattr(event_repo._audit_service, "append", close_after_event_intent)

        with pytest.raises(ConflictError, match="changed after intent"):
            event_repo.append_event(
                "S006",
                event_type="note",
                real_time=datetime(2026, 8, 31, 19, 0, 0, tzinfo=UTC),
                world_tick=16000,
                extra_fields={"text": "race"},
                audit=_make_audit_context(operation_id="race-event-intent"),
            )

        assert events_path.read_bytes() == events_before
        assert meta_path.exists()
        meta_text = meta_path.read_text(encoding="utf-8")
        assert '"status":"completed"' in meta_text

        records = _read_audit_records(vault_root)
        event_recs = [r for r in records if r.get("operation_id") == "race-event-intent"]
        intent_recs = [r for r in event_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in event_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Close wins after physical event append ─────────────────────────────────────


class TestCloseWinsAfterEventAppend:
    def test_close_wins_after_event_physical_append(
        self, vault_root: Path, meta_repo, event_repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"

        # Patch _append_event_line to close after physical append succeeds
        original_append_line = _events_mod._append_event_line

        def close_after_physical_append(path, encoded_line):
            original_append_line(path, encoded_line)
            meta_repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(
                    operation_id="race-close-after-event-append",
                    session="S006",
                ),
            )

        monkeypatch.setattr(_events_mod, "_append_event_line", close_after_physical_append)

        with pytest.raises(StorageError, match="metadata changed after event append"):
            event_repo.append_event(
                "S006",
                event_type="note",
                real_time=datetime(2026, 8, 31, 19, 0, 0, tzinfo=UTC),
                world_tick=16000,
                extra_fields={"text": "race"},
                audit=_make_audit_context(operation_id="race-event-append"),
            )

        # Event bytes may be persisted
        assert events_path.exists()

        # Metadata is completed
        assert meta_path.exists()
        meta_text = meta_path.read_text(encoding="utf-8")
        assert '"status":"completed"' in meta_text

        records = _read_audit_records(vault_root)
        event_recs = [r for r in records if r.get("operation_id") == "race-event-append"]
        intent_recs = [r for r in event_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in event_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0
