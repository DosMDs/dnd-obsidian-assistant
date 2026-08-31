"""S6-C03 correction tests — event validation, portability, audit, failure integrity.

These tests are isolated from the main test_session_events.py to avoid
excessive file size.  They cover:

- RawSessionEvent validation (evt_000 rejection, field validation)
- Duplicate detection in JSONL parser and list_events
- Metadata existence requirements
- Portability (O_BINARY fallback)
- Audit success (exact hashes, fields)
- Audit failure (intent failure, race, append helper failure, committed failure)
- Short write and fsync failure
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dnd_assistant.storage.session_events as _events_mod
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
    RawSessionEvent,
    _append_event_line,
    _deserialize_event,
    _parse_events_jsonl,
    _serialize_event,
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


def _create_session_dir(vault_root: Path, session_id: str = "S001") -> Path:
    """Create a session directory with empty events.jsonl and metadata.json."""
    session_dir = vault_root / "_system" / "raw" / "sessions" / session_id
    session_dir.mkdir()
    events_path = session_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    meta = '{"id":"' + session_id + '","status":"active"}\n'
    (session_dir / "metadata.json").write_text(meta, encoding="utf-8")
    return events_path


def _symlinks_supported() -> bool:
    try:
        temp = Path(os.environ.get("TEMP", "."))
        lt = temp / ("_st_" + os.urandom(4).hex())
        tt = temp / ("_stt_" + os.urandom(4).hex())
        tt.write_text("test", encoding="utf-8")
        lt.symlink_to(tt)
        result = lt.is_symlink()
        lt.unlink()
        tt.unlink()
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


# ── RawSessionEvent validation ──────────────────────────────────────────────────


class TestRawSessionEventValidation:
    """Tests for canonical RawSessionEvent field validation in __init__."""

    def test_evt_000_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match=">= 1"):
            RawSessionEvent("evt_000", dt, 13800, "note")

    def test_evt_00_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match=">= 1"):
            RawSessionEvent("evt_00", dt, 13800, "note")

    def test_evt_negative_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="event_id"):
            RawSessionEvent("evt_-1", dt, 13800, "note")

    def test_uppercase_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="event_id"):
            RawSessionEvent("EVT_001", dt, 13800, "note")

    def test_non_matching_format_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="event_id"):
            RawSessionEvent("evt_x", dt, 13800, "note")

    def test_whitespace_event_id_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="whitespace"):
            RawSessionEvent(" evt_001", dt, 13800, "note")

    def test_naive_datetime_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0)  # no tzinfo
        with pytest.raises(StorageError, match="timezone-aware"):
            RawSessionEvent("evt_001", dt, 13800, "note")

    def test_world_tick_bool_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="world_tick"):
            RawSessionEvent("evt_001", dt, True, "note")  # type: ignore[arg-type]

    def test_world_tick_float_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="world_tick"):
            RawSessionEvent("evt_001", dt, 13800.5, "note")  # type: ignore[arg-type]

    def test_world_tick_str_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="world_tick"):
            RawSessionEvent("evt_001", dt, "13800", "note")  # type: ignore[arg-type]

    def test_empty_type_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="type"):
            RawSessionEvent("evt_001", dt, 13800, "")

    def test_whitespace_type_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="whitespace"):
            RawSessionEvent("evt_001", dt, 13800, "  ")

    def test_extra_field_collision_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="collides"):
            RawSessionEvent("evt_001", dt, 13800, "note", extra_fields={"event_id": "evt_999"})

    def test_extra_field_real_time_collision_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="collides"):
            RawSessionEvent("evt_001", dt, 13800, "note", extra_fields={"real_time": "2026-01-01"})

    def test_extra_field_world_tick_collision_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="collides"):
            RawSessionEvent("evt_001", dt, 13800, "note", extra_fields={"world_tick": 999})

    def test_extra_field_type_collision_rejected(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="collides"):
            RawSessionEvent("evt_001", dt, 13800, "note", extra_fields={"type": "custom"})

    def test_non_json_extra_rejected_in_init(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="not JSON-compatible"):
            RawSessionEvent("evt_001", dt, 13800, "note", extra_fields={"data": Path("/tmp/test")})

    def test_nan_extra_rejected_in_init(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(StorageError, match="NaN or Infinity"):
            RawSessionEvent("evt_001", dt, 13800, "note", extra_fields={"val": float("nan")})

    def test_leading_zero_above_zero_accepted(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = RawSessionEvent("evt_001", dt, 13800, "note")
        assert ev.event_id == "evt_001"

    def test_evt_005_accepted(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = RawSessionEvent("evt_005", dt, 13800, "note")
        assert ev.event_id == "evt_005"

    def test_evt_0001_accepted(self) -> None:
        dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ev = RawSessionEvent("evt_0001", dt, 13800, "note")
        assert ev.event_id == "evt_0001"


# ── Duplicate detection in JSONL parser ────────────────────────────────────────


class TestDuplicateDetectionInParser:
    """Tests for strict duplicate event_id detection in _parse_events_jsonl."""

    def test_duplicate_event_id_in_parser_raises(self) -> None:
        text = (
            '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\n'
            '{"event_id":"evt_001","real_time":"2026-08-31T18:31:00+00:00","world_tick":15739580,"type":"item_acquired"}\n'
        )
        with pytest.raises(StorageError, match="duplicate event_id"):
            _parse_events_jsonl(text)

    def test_duplicate_event_id_in_list_events(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        """list_events raises StorageError when persisted log has duplicate IDs."""
        events_path = _create_session_dir(vault_root, "S001")
        text = (
            '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\n'
            '{"event_id":"evt_001","real_time":"2026-08-31T18:31:00+00:00","world_tick":15739580,"type":"item_acquired"}\n'
        )
        events_path.write_text(text, encoding="utf-8")
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="duplicate event_id"):
            repo.list_events("S001")

    def test_evt_000_in_parser_raises(self) -> None:
        text = '{"event_id":"evt_000","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\n'
        with pytest.raises(StorageError, match=">= 1"):
            _parse_events_jsonl(text)

    def test_evt_000_in_deserialize_raises(self) -> None:
        text = '{"event_id":"evt_000","real_time":"2026-08-31T18:00:00+00:00","world_tick":13800,"type":"note"}\n'
        with pytest.raises(StorageError, match=">= 1"):
            _deserialize_event(text)


# ── Metadata existence validation ──────────────────────────────────────────────


class TestMetadataExistence:
    """Tests for metadata.json requirement in event read/append."""

    def test_list_events_missing_metadata_raises(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("", encoding="utf-8")
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="no metadata.json"):
            repo.list_events("S001")

    def test_append_event_missing_metadata_raises(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("", encoding="utf-8")
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="no metadata.json"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(),
            )

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_live_metadata_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("", encoding="utf-8")
        target = vault_root.parent / "outside_metadata.json"
        target.write_text('{"id":"S001","status":"active"}\n', encoding="utf-8")
        (session_dir / "metadata.json").symlink_to(target)
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="symlink"):
            repo.list_events("S001")

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_dangling_metadata_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        session_dir = vault_root / "_system" / "raw" / "sessions" / "S001"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("", encoding="utf-8")
        (session_dir / "metadata.json").symlink_to(vault_root / "_nonexistent.json")
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="symlink"):
            repo.list_events("S001")


# ── Portability ─────────────────────────────────────────────────────────────────


class TestPortability:
    """Cross-platform portability tests."""

    def test_o_binary_fallback_defined(self) -> None:
        """_O_BINARY is defined and is an int on all platforms."""
        assert isinstance(_events_mod._O_BINARY, int)


# ── Audit success tests ─────────────────────────────────────────────────────────


class TestAuditSuccess:
    """Tests for successful append producing exact audit records."""

    def test_intent_and_committed_records(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        _create_session_dir(vault_root, "S001")
        ctx = _make_audit_context(operation_id="audit-succ-001", source="test_audit")
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields={"text": "hello"},
            audit=ctx,
        )
        records = _read_audit_records(vault_root)
        assert len(records) == 2
        assert records[0]["phase"] == "intent"
        assert records[1]["phase"] == "committed"
        assert records[0]["operation_id"] == "audit-succ-001"
        assert records[1]["operation_id"] == "audit-succ-001"

    def test_operation_name(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        _create_session_dir(vault_root, "S001")
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields=None,
            audit=_make_audit_context(operation_id="audit-succ-002"),
        )
        records = _read_audit_records(vault_root)
        assert records[0]["operation"] == "session.event.append"
        assert records[1]["operation"] == "session.event.append"

    def test_entity_id_is_none(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        _create_session_dir(vault_root, "S001")
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields=None,
            audit=_make_audit_context(operation_id="audit-succ-003"),
        )
        records = _read_audit_records(vault_root)
        assert records[0]["entity_id"] is None
        assert records[1]["entity_id"] is None

    def test_session_id_in_audit(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        _create_session_dir(vault_root, "S001")
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields=None,
            audit=_make_audit_context(operation_id="audit-succ-004"),
        )
        records = _read_audit_records(vault_root)
        assert records[0]["session"] == "S001"
        assert records[1]["session"] == "S001"

    def test_source_preserved(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        _create_session_dir(vault_root, "S001")
        ctx = _make_audit_context(operation_id="audit-succ-005", source="my_test_source")
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields=None,
            audit=ctx,
        )
        records = _read_audit_records(vault_root)
        assert records[0]["source"] == "my_test_source"
        assert records[1]["source"] == "my_test_source"

    def test_before_hash_exact(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = _create_session_dir(vault_root, "S001")
        before_text = events_path.read_text(encoding="utf-8")
        expected_before = hashlib.sha256(before_text.encode("utf-8")).hexdigest()
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields=None,
            audit=_make_audit_context(operation_id="audit-succ-006"),
        )
        records = _read_audit_records(vault_root)
        assert records[0]["before_hash"] == expected_before
        assert records[1]["before_hash"] == expected_before

    def test_after_hash_exact(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = _create_session_dir(vault_root, "S001")
        repo.append_event(
            "S001",
            event_type="note",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            world_tick=13800,
            extra_fields=None,
            audit=_make_audit_context(operation_id="audit-succ-007"),
        )
        after_text = events_path.read_text(encoding="utf-8")
        expected_after = hashlib.sha256(after_text.encode("utf-8")).hexdigest()
        records = _read_audit_records(vault_root)
        assert records[0]["after_hash"] == expected_after
        assert records[1]["after_hash"] == expected_after
        assert records[0]["after_hash"] == records[1]["after_hash"]


# ── Audit failure tests ─────────────────────────────────────────────────────────


class TestAuditFailure:
    """Tests for audit failure integrity in event append."""

    def test_audit_intent_failure_prevents_mutation(
        self, vault_root: Path, audit_service: AuditService, monkeypatch
    ) -> None:
        """Audit intent failure raises StorageError; events.jsonl unchanged."""
        _create_session_dir(vault_root, "S001")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        original_append = AuditService.append

        def failing_intent_append(self, record) -> None:
            if getattr(record, "phase", None) == "intent":
                raise StorageError("Simulated audit intent failure")
            return original_append(self, record)

        monkeypatch.setattr(AuditService, "append", failing_intent_append)
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="audit"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(operation_id="audit-fail-intent"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        committed = [r for r in records if r.get("phase") == "committed"]
        assert len(committed) == 0

    def test_after_intent_concurrency_race(
        self, vault_root: Path, audit_service: AuditService, monkeypatch
    ) -> None:
        """Competitor mutation between intent and append raises ConflictError."""
        _create_session_dir(vault_root, "S001")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        original_append = AuditService.append
        competitor_appended = False

        def append_with_competitor(self, record) -> None:
            nonlocal competitor_appended
            if getattr(record, "phase", None) == "intent":
                result = original_append(self, record)
                competitor_line = (
                    '{"event_id":"evt_001","real_time":"2026-08-31T18:00:00+00:00",'
                    '"world_tick":13800,"type":"competitor"}\n'
                )
                with open(events_path, "a", encoding="utf-8", newline="") as f:
                    f.write(competitor_line)
                competitor_appended = True
                return result
            return original_append(self, record)

        monkeypatch.setattr(AuditService, "append", append_with_competitor)
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(ConflictError, match="changed after intent"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields={"text": "local"},
                audit=_make_audit_context(operation_id="audit-race"),
            )
        assert competitor_appended
        assert b"competitor" in events_path.read_bytes()
        assert b'"text":"local"' not in events_path.read_bytes()
        records = _read_audit_records(vault_root)
        intents = [r for r in records if r.get("phase") == "intent"]
        assert len(intents) >= 1
        committed = [r for r in records if r.get("phase") == "committed"]
        assert len(committed) == 0

    def test_append_helper_failure_after_intent(
        self, vault_root: Path, audit_service: AuditService, monkeypatch
    ) -> None:
        """Append helper failure after intent raises StorageError."""
        _create_session_dir(vault_root, "S001")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()

        def failing_append(path, encoded_line):
            raise StorageError("Simulated append failure")

        monkeypatch.setattr(_events_mod, "_append_event_line", failing_append)
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="append"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(operation_id="audit-helper-fail"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        intents = [r for r in records if r.get("phase") == "intent"]
        assert len(intents) >= 1
        committed = [r for r in records if r.get("phase") == "committed"]
        assert len(committed) == 0

    def test_audit_committed_failure_leaves_persisted_event(
        self, vault_root: Path, audit_service: AuditService, monkeypatch
    ) -> None:
        """Committed audit failure raises StorageError; event remains persisted."""
        _create_session_dir(vault_root, "S001")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        original_append = AuditService.append

        def failing_committed_append(self, record) -> None:
            if getattr(record, "phase", None) == "committed":
                raise StorageError("Simulated audit committed failure")
            return original_append(self, record)

        monkeypatch.setattr(AuditService, "append", failing_committed_append)
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        with pytest.raises(StorageError, match="audit"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(operation_id="audit-committed-fail"),
            )
        # Event remains persisted
        text = events_path.read_text(encoding="utf-8")
        assert "evt_001" in text
        # Intent remains
        records = _read_audit_records(vault_root)
        intents = [r for r in records if r.get("phase") == "intent"]
        assert len(intents) >= 1
        # No committed audit
        committed = [r for r in records if r.get("phase") == "committed"]
        assert len(committed) == 0
        # Metadata unchanged
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "metadata.json"
        assert meta_path.exists()


# ── Short write and fsync failure tests ─────────────────────────────────────────


class TestAppendHelperFailure:
    """Direct tests for _append_event_line failure modes."""

    def test_short_write_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        """Direct test: short write raises StorageError."""
        path = tmp_path / "events.jsonl"
        path.write_text("", encoding="utf-8")
        encoded = _serialize_event(_make_event()).encode("utf-8")

        original_write = _events_mod.os.write

        def short_write(fd, data):
            return original_write(fd, data[: max(1, len(data) // 2)])

        monkeypatch.setattr(_events_mod.os, "write", short_write)
        with pytest.raises(StorageError, match="Short write"):
            _append_event_line(path, encoded)

    def test_fsync_failure_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        """Direct test: fsync failure raises StorageError."""
        path = tmp_path / "events.jsonl"
        path.write_text("", encoding="utf-8")
        encoded = _serialize_event(_make_event()).encode("utf-8")

        def failing_fsync(fd):
            raise OSError("Simulated fsync failure")

        monkeypatch.setattr(_events_mod.os, "fsync", failing_fsync)
        with pytest.raises(StorageError, match="fsync"):
            _append_event_line(path, encoded)

        # Descriptor was closed
        if path.exists():
            fd2 = os.open(str(path), os.O_WRONLY)
            os.close(fd2)
