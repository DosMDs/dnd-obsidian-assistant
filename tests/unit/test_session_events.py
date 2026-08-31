"""Unit tests for S6-03 raw session event persistence.

Covers:
- RawSessionEvent value semantics
- Event codec (serialize/deserialize)
- Strict JSONL parser
- Event ID allocation
- Append-only persistence
- Path safety
- Audit semantics
- Failure/race integrity
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dnd_assistant.storage.session_events as _events_mod
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
    RawSessionEvent,
    _allocate_event_id,
    _append_event_line,
    _deserialize_event,
    _parse_events_jsonl,
    _serialize_event,
    _validate_json_value,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_event(
    event_id: str = "evt_001",
    real_time: datetime | None = None,
    world_tick: int = 13800,
    type: str = "note",
    **extra: object,
) -> RawSessionEvent:
    if real_time is None:
        real_time = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
    return RawSessionEvent(
        event_id=event_id,
        real_time=real_time,
        world_tick=world_tick,
        type=type,
        extra_fields=extra if extra else None,
    )


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


def _symlinks_supported() -> bool:
    try:
        temp = Path(os.environ.get("TEMP", "."))
        link_test = temp / f"_symlink_test_{os.urandom(4).hex()}"
        target_test = temp / f"_symlink_target_{os.urandom(4).hex()}"
        target_test.write_text("test", encoding="utf-8")
        link_test.symlink_to(target_test)
        result = link_test.is_symlink()
        link_test.unlink()
        target_test.unlink()
        return result
    except OSError:
        return False


_SYMLINKS_SUPPORTED = _symlinks_supported()


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    """Create a minimal Vault structure with session runtime roots."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Sessions").mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "raw").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


@pytest.fixture
def audit_service(vault_root: Path) -> AuditService:
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(log_path)


@pytest.fixture
def event_repo(vault_root: Path, audit_service: AuditService) -> ObsidianSessionEventRepository:
    return ObsidianSessionEventRepository(vault_root, audit_service)


@pytest.fixture
def session_with_events(vault_root: Path) -> Path:
    """Create a session directory with an empty events.jsonl."""
    session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
    session_dir.mkdir()
    events_path = session_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    return events_path


# ── RawSessionEvent value semantics ────────────────────────────────────────────


class TestRawSessionEventValue:
    def test_construct_note_event(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = RawSessionEvent(
            event_id="evt_001",
            real_time=dt,
            world_tick=13800,
            type="note",
            extra_fields={"text": "Test note"},
        )
        assert ev.event_id == "evt_001"
        assert ev.real_time == dt
        assert ev.world_tick == 13800
        assert ev.type == "note"
        assert ev.extra_fields == {"text": "Test note"}

    def test_construct_generic_event(self) -> None:
        dt = datetime(2026, 8, 31, 18, 31, 0, tzinfo=UTC)
        ev = RawSessionEvent(
            event_id="evt_002",
            real_time=dt,
            world_tick=15739580,
            type="item_acquired",
            extra_fields={"entity": "Silver Key"},
        )
        assert ev.type == "item_acquired"
        assert ev.extra_fields == {"entity": "Silver Key"}

    def test_equality(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        a = RawSessionEvent("evt_001", dt, 13800, "note", {"text": "hello"})
        b = RawSessionEvent("evt_001", dt, 13800, "note", {"text": "hello"})
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        a = RawSessionEvent("evt_001", dt, 13800, "note")
        b = RawSessionEvent("evt_002", dt, 13800, "note")
        assert a != b

    def test_repr(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = RawSessionEvent("evt_001", dt, 13800, "note")
        assert "RawSessionEvent" in repr(ev)
        assert "evt_001" in repr(ev)

    def test_extra_fields_copy(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        extras = {"text": "hello"}
        ev = RawSessionEvent("evt_001", dt, 13800, "note", extra_fields=extras)
        extras["text"] = "modified"
        assert ev.extra_fields == {"text": "hello"}


# ── Event codec ────────────────────────────────────────────────────────────────


class TestEventCodec:
    def test_serialize_note(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = _make_event(event_id="evt_001", real_time=dt, world_tick=13800, text="Бармен сказал")
        line = _serialize_event(ev)
        assert line.endswith("\n")
        assert line.count("\n") == 1
        data = json.loads(line)
        assert data["event_id"] == "evt_001"
        assert data["real_time"] == "2026-08-31T18:00:00+00:00"
        assert data["world_tick"] == 13800
        assert data["type"] == "note"
        assert data["text"] == "Бармен сказал"

    def test_serialize_generic_event(self) -> None:
        dt = datetime(2026, 8, 31, 18, 31, 0, tzinfo=UTC)
        ev = _make_event("evt_002", dt, 15739580, "item_acquired", entity="Silver Key")
        line = _serialize_event(ev)
        data = json.loads(line)
        assert data["event_id"] == "evt_002"
        assert data["type"] == "item_acquired"
        assert data["entity"] == "Silver Key"

    def test_deserialize_note(self) -> None:
        line = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note","text":"Бармен сказал"}\n'
        ev = _deserialize_event(line)
        assert ev.event_id == "evt_001"
        assert ev.world_tick == 13800
        assert ev.type == "note"
        assert ev.extra_fields["text"] == "Бармен сказал"

    def test_deserialize_generic_event(self) -> None:
        line = '{"entity":"Silver Key","event_id":"evt_002","real_time":"2026-08-31T18:31:00+00:00","type":"item_acquired","world_tick":15739580}\n'
        ev = _deserialize_event(line)
        assert ev.event_id == "evt_002"
        assert ev.type == "item_acquired"
        assert ev.extra_fields["entity"] == "Silver Key"

    def test_roundtrip(self) -> None:
        dt = datetime(2026, 8, 31, 19, 2, 0, tzinfo=UTC)
        original = _make_event("evt_003", dt, 15739810, "party_decision", text="Не отдавать амулет")
        line = _serialize_event(original)
        restored = _deserialize_event(line)
        assert original == restored

    def test_deterministic_json(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = _make_event("evt_001", dt, 13800, "note", text="hello")
        line1 = _serialize_event(ev)
        line2 = _serialize_event(ev)
        assert line1 == line2

    def test_one_physical_line(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = _make_event("evt_001", dt, 13800, "note", text="line1\nline2")
        line = _serialize_event(ev)
        assert line.count("\n") == 1
        data = json.loads(line)
        assert data["text"] == "line1\nline2"

    def test_aware_real_time_required(self) -> None:
        line = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00","world_tick":13800,"type":"note"}'
        with pytest.raises(StorageError, match="timezone-aware"):
            _deserialize_event(line)

    def test_invalid_event_type_rejected(self) -> None:
        for bad_type in ("", "  ", "\t", "\n"):
            line = json.dumps(
                {
                    "event_id": "evt_001",
                    "real_time": "2026-08-31T18:00:00+00:00",
                    "world_tick": 13800,
                    "type": bad_type,
                }
            )
            with pytest.raises(StorageError):
                _deserialize_event(line)

    def test_event_specific_fields_preserved(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = _make_event("evt_001", dt, 13800, "note", text="hello", entity="world")
        assert ev.extra_fields["text"] == "hello"
        assert ev.extra_fields["entity"] == "world"

    def test_non_json_extra_rejected(self) -> None:
        with pytest.raises(StorageError, match="not JSON-compatible"):
            _validate_json_value({"data": Path("/tmp/test")})

    def test_nan_infinity_rejected(self) -> None:
        with pytest.raises(StorageError, match="NaN or Infinity"):
            _validate_json_value(float("nan"))
        with pytest.raises(StorageError, match="NaN or Infinity"):
            _validate_json_value(float("inf"))
        with pytest.raises(StorageError, match="NaN or Infinity"):
            _validate_json_value(float("-inf"))


# ── Strict JSONL parser ────────────────────────────────────────────────────────


class TestStrictJsonlParser:
    def test_empty_events_file(self) -> None:
        assert _parse_events_jsonl("") == []

    def test_one_event(self) -> None:
        line = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note","text":"hello"}\n'
        events = _parse_events_jsonl(line)
        assert len(events) == 1
        assert events[0].event_id == "evt_001"

    def test_multiple_events_preserve_order(self) -> None:
        text = (
            '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note","text":"first"}\n'
            '{"event_id":"evt_002","real_time":"2026-08-31T18:31:00+00:00","world_tick":15739580,"type":"item_acquired","entity":"Silver Key"}\n'
        )
        events = _parse_events_jsonl(text)
        assert len(events) == 2
        assert events[0].event_id == "evt_001"
        assert events[1].event_id == "evt_002"

    def test_blank_line_raises(self) -> None:
        text = (
            '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\n'
            "\n"
            '{"event_id":"evt_002","real_time":"2026-08-31T18:31:00+00:00","world_tick":15739580,"type":"item_acquired"}\n'
        )
        with pytest.raises(StorageError, match="blank line"):
            _parse_events_jsonl(text)

    def test_malformed_json_raises(self) -> None:
        text = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\nbroken\n'
        with pytest.raises(StorageError, match="malformed JSON"):
            _parse_events_jsonl(text)

    def test_non_object_raises(self) -> None:
        text = '["not_an_object"]\n'
        with pytest.raises(StorageError, match="expected JSON object"):
            _parse_events_jsonl(text)

    def test_missing_field_raises(self) -> None:
        text = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800}\n'
        with pytest.raises(StorageError, match="invalid type"):
            _parse_events_jsonl(text)

    def test_invalid_event_id_raises(self) -> None:
        text = '{"event_id":"bad_id","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\n'
        with pytest.raises(StorageError, match="event_id"):
            _parse_events_jsonl(text)

    def test_duplicate_event_id_raises(self) -> None:
        ev1 = _make_event("evt_001")
        ev2 = _make_event("evt_001")
        with pytest.raises(StorageError, match="Duplicate event ID"):
            _allocate_event_id([ev1, ev2])

    def test_non_newline_terminated_final_record_raises(self) -> None:
        text = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}'
        with pytest.raises(StorageError, match="newline-terminated"):
            _parse_events_jsonl(text)

    def test_unknown_event_specific_fields_preserved(self) -> None:
        text = '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note","custom_field":"custom_value"}\n'
        events = _parse_events_jsonl(text)
        assert len(events) == 1
        assert events[0].extra_fields["custom_field"] == "custom_value"


# ── Event ID allocation ────────────────────────────────────────────────────────


class TestEventIdAllocation:
    def test_empty_returns_evt_001(self) -> None:
        assert _allocate_event_id([]) == "evt_001"

    def test_evt_001_returns_evt_002(self) -> None:
        ev = _make_event("evt_001")
        assert _allocate_event_id([ev]) == "evt_002"

    def test_evt_005_returns_evt_006(self) -> None:
        ev = _make_event("evt_005")
        assert _allocate_event_id([ev]) == "evt_006"

    def test_evt_999_returns_evt_1000(self) -> None:
        ev = _make_event("evt_999")
        assert _allocate_event_id([ev]) == "evt_1000"

    def test_evt_1000_returns_evt_1001(self) -> None:
        ev = _make_event("evt_1000")
        assert _allocate_event_id([ev]) == "evt_1001"


# ── Append-only persistence ─────────────────────────────────────────────────────


class TestAppendOnlyPersistence:
    def test_append_first_event(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        ev = repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "First note"},
            audit=_make_audit_context(),
        )
        assert ev.event_id == "evt_001"
        assert ev.type == "note"
        assert ev.extra_fields["text"] == "First note"

    def test_append_second_event(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "First"},
            audit=_make_audit_context(operation_id="op-001"),
        )
        ev2 = repo.append_event(
            "S001",
            event_type="item_acquired",
            real_time=datetime(2026, 8, 31, 18, 31, 0, tzinfo=UTC),
            world_tick=15739580,
            extra_fields={"entity": "Silver Key"},
            audit=_make_audit_context(operation_id="op-002"),
        )
        assert ev2.event_id == "evt_002"
        assert ev2.type == "item_acquired"
        assert ev2.extra_fields["entity"] == "Silver Key"

    def test_existing_bytes_remain_exact_prefix(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        before_bytes = events_path.read_bytes()
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "hello"},
            audit=_make_audit_context(),
        )
        after_bytes = events_path.read_bytes()
        assert after_bytes.startswith(before_bytes)
        assert len(after_bytes) > len(before_bytes)

    def test_only_one_new_line_added(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "hello"},
            audit=_make_audit_context(),
        )
        lines = events_path.read_text(encoding="utf-8").split("\n")
        non_empty = [ln for ln in lines if ln]
        assert len(non_empty) == 1

    def test_events_file_not_rewritten(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        inode_before = events_path.stat().st_ino if hasattr(events_path.stat(), "st_ino") else None
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "hello"},
            audit=_make_audit_context(),
        )
        if inode_before is not None:
            assert events_path.stat().st_ino == inode_before

    def test_metadata_json_unchanged(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")
        metadata_path = session_dir / "metadata.json"
        metadata_path.write_text('{"test":"data"}\n', encoding="utf-8")

        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "hello"},
            audit=_make_audit_context(),
        )
        assert metadata_path.read_text(encoding="utf-8") == '{"test":"data"}\n'

    def test_fsync_called(self, vault_root: Path, monkeypatch) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        fsync_called = False
        original_fsync = _events_mod.os.fsync

        def tracking_fsync(fd):
            nonlocal fsync_called
            fsync_called = True
            return original_fsync(fd)

        monkeypatch.setattr(_events_mod.os, "fsync", tracking_fsync)

        encoded = _serialize_event(_make_event()).encode("utf-8")
        _append_event_line(events_path, encoded)

        assert fsync_called

    def test_returned_event_equals_persisted_final_event(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.write_text("", encoding="utf-8")

        result = repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "hello"},
            audit=_make_audit_context(),
        )
        persisted = repo.list_events("S001")
        assert len(persisted) == 1
        assert result == persisted[0]


# ── Path safety ─────────────────────────────────────────────────────────────────


class TestPathSafety:
    def test_missing_events_file_raises(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="events.jsonl not found"):
            repo.list_events("S001")

    def test_missing_events_file_append_raises(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="events.jsonl not found"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(),
            )

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_live_events_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        target = vault_root / "external_target.jsonl"
        target.write_text("", encoding="utf-8")
        events_path = session_dir / "events.jsonl"
        events_path.symlink_to(target)

        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="symlink"):
            repo.list_events("S001")

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_dangling_events_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        events_path = session_dir / "events.jsonl"
        events_path.symlink_to(vault_root / "nonexistent.jsonl")

        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="symlink"):
            repo.list_events("S001")
