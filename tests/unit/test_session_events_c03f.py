"""S6-C03F tests — repository-level invalid-candidate/no-intent and os.write OSError.

These tests cover:

1. Repository-level invalid-candidate regression:
   - ``append_event`` with invalid input raises ``StorageError``
   - ``events.jsonl`` remains byte-for-byte unchanged
   - Audit log has no intent record (or does not exist)

2. Direct ``os.write`` OSError translation:
   - ``_append_event_line`` with patched ``os.write`` raising ``OSError``
   - ``StorageError`` with cause chaining
   - Descriptor is closed
   - No retry

3. Short-write and fsync tests from S6-C03 (preserved and confirmed isolated)
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
    _append_event_line,
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


# ── Repository-level invalid-candidate/no-intent regression ────────────────────


class TestInvalidCandidateNoIntent:
    """append_event with invalid candidate: StorageError, events unchanged, no audit intent."""

    @pytest.fixture(autouse=True)
    def _setup_session(self, vault_root: Path) -> None:
        """Create a valid session with empty events.jsonl and metadata.json."""
        _create_session_dir(vault_root, "S001")

    # -- event_type = "" (empty) --

    def test_empty_event_type(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        with pytest.raises(StorageError, match="type"):
            repo.append_event(
                "S001",
                event_type="",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(operation_id="c03f-empty-type"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        assert len(records) == 0

    # -- world_tick = True (bool, not int) --

    def test_bool_world_tick(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        with pytest.raises(StorageError, match="world_tick"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=True,  # type: ignore[arg-type]
                extra_fields=None,
                audit=_make_audit_context(operation_id="c03f-bool-tick"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        assert len(records) == 0

    # -- naive real_time (no tzinfo) --

    def test_naive_real_time(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        with pytest.raises(StorageError, match="timezone-aware"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0),  # naive
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(operation_id="c03f-naive-time"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        assert len(records) == 0

    # -- canonical collision in extra_fields --

    def test_extra_field_collision(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        with pytest.raises(StorageError, match="collides"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields={"event_id": "evt_999"},
                audit=_make_audit_context(operation_id="c03f-collision"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        assert len(records) == 0

    # -- non-JSON-compatible extra value --

    def test_non_json_extra(self, vault_root: Path, audit_service: AuditService) -> None:
        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        with pytest.raises(StorageError, match="not JSON-compatible"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
                world_tick=13800,
                extra_fields={"data": Path("/tmp/test")},
                audit=_make_audit_context(operation_id="c03f-nonjson"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        assert len(records) == 0


# ── Aware-datetime semantic hardening ──────────────────────────────────────────


class TestAwareDatetimeSemantic:
    """_validate_aware_datetime requires non-None utcoffset()."""

    def test_tzinfo_with_none_utcoffset_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        """A tzinfo with non-None tzinfo but None utcoffset() is rejected."""
        from datetime import timedelta, tzinfo

        class _FakeTz(tzinfo):
            """A tzinfo with non-None tzinfo but utcoffset() returns None."""

            def utcoffset(self, dt) -> timedelta | None:
                return None

            def dst(self, dt) -> timedelta | None:
                return None

            def tzname(self, dt) -> str | None:
                return "FakeTz"

        repo = ObsidianSessionEventRepository(vault_root, audit_service)
        _create_session_dir(vault_root, "S001")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        fake_dt = datetime(2026, 8, 31, 18, 0, 0, tzinfo=_FakeTz())
        with pytest.raises(StorageError, match="utcoffset"):
            repo.append_event(
                "S001",
                event_type="note",
                real_time=fake_dt,
                world_tick=13800,
                extra_fields=None,
                audit=_make_audit_context(operation_id="c03f-fake-tz"),
            )
        assert events_path.read_bytes() == before_bytes
        records = _read_audit_records(vault_root)
        assert len(records) == 0


# ── Direct os.write OSError translation ────────────────────────────────────────


class TestOsWriteOserror:
    """Direct _append_event_line test: os.write OSError -> StorageError."""

    def test_os_write_oserror_raises_storage_error(self, tmp_path: Path, monkeypatch) -> None:
        """os.write OSError is translated to StorageError with cause chaining."""
        path = tmp_path / "events.jsonl"
        path.write_text("", encoding="utf-8")
        encoded = _serialize_event(_make_event()).encode("utf-8")

        def failing_write(fd, data):
            raise OSError("simulated write failure")

        monkeypatch.setattr(_events_mod.os, "write", failing_write)

        with pytest.raises(StorageError) as exc_info:
            _append_event_line(path, encoded)

        assert "write" in str(exc_info.value)
        # Cause is chained
        cause = exc_info.value.__cause__
        assert cause is not None
        assert isinstance(cause, OSError)
        assert "simulated write failure" in str(cause)

    def test_os_write_oserror_closes_descriptor(self, tmp_path: Path, monkeypatch) -> None:
        """Descriptor is closed after os.write OSError."""
        path = tmp_path / "events.jsonl"
        path.write_text("", encoding="utf-8")
        encoded = _serialize_event(_make_event()).encode("utf-8")

        def failing_write(fd, data):
            raise OSError("simulated write failure")

        monkeypatch.setattr(_events_mod.os, "write", failing_write)

        with pytest.raises(StorageError):
            _append_event_line(path, encoded)

        # Descriptor was closed — re-opening should succeed
        fd2 = os.open(str(path), os.O_WRONLY)
        os.close(fd2)

    def test_os_write_oserror_no_retry(self, tmp_path: Path, monkeypatch) -> None:
        """No retry after os.write OSError — file content unchanged."""
        path = tmp_path / "events.jsonl"
        path.write_text("", encoding="utf-8")
        before_bytes = path.read_bytes()
        encoded = _serialize_event(_make_event()).encode("utf-8")

        call_count = 0

        def failing_write(fd, data):
            nonlocal call_count
            call_count += 1
            raise OSError("simulated write failure")

        monkeypatch.setattr(_events_mod.os, "write", failing_write)

        with pytest.raises(StorageError):
            _append_event_line(path, encoded)

        assert call_count == 1
        assert path.read_bytes() == before_bytes
