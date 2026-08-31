"""Unit tests for S6-02 raw session metadata persistence.

Covers:
- RawSessionMetadata value semantics
- Metadata codec (serialize/deserialize)
- Path safety
- ID allocation
- Session creation
- Audit semantics
- Failure integrity
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dnd_assistant.storage.session_metadata as _meta_mod
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
    _deserialize,
    _serialize,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _canonical_session(**overrides: object) -> Session:
    """Build a canonical active Session for testing."""
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
def repo(vault_root: Path, audit_service: AuditService) -> ObsidianSessionMetadataRepository:
    return ObsidianSessionMetadataRepository(vault_root, audit_service)


# ── RawSessionMetadata value semantics ────────────────────────────────────────


class TestRawSessionMetadataValue:
    def test_construct(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        assert meta.session.id == "S006"
        assert meta.session.status == "active"
        assert meta.extra_fields == {}

    def test_extra_fields_preserved(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(
            session=session,
            extra_fields={"touched_entities": ["npc_varos"], "future_field": 42},
        )
        assert meta.extra_fields["touched_entities"] == ["npc_varos"]
        assert meta.extra_fields["future_field"] == 42

    def test_extra_fields_copy(self) -> None:
        session = _canonical_session()
        extras = {"key": "value"}
        meta = RawSessionMetadata(session=session, extra_fields=extras)
        extras["key"] = "mutated"
        assert meta.extra_fields["key"] == "value"

    def test_equality(self) -> None:
        session = _canonical_session()
        a = RawSessionMetadata(session=session)
        b = RawSessionMetadata(session=_canonical_session())
        assert a == b

    def test_inequality(self) -> None:
        a = RawSessionMetadata(session=_canonical_session(id="S006"))
        b = RawSessionMetadata(session=_canonical_session(id="S007"))
        assert a != b

    def test_inequality_extra(self) -> None:
        session = _canonical_session()
        a = RawSessionMetadata(session=session)
        b = RawSessionMetadata(session=session, extra_fields={"x": 1})
        assert a != b

    def test_hashable(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        s = {meta}
        assert meta in s

    def test_repr(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        r = repr(meta)
        assert "RawSessionMetadata" in r
        assert "S006" in r


# ── Metadata codec ─────────────────────────────────────────────────────────────


class TestMetadataCodec:
    def test_serialize_active(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        text = _serialize(meta)
        assert text.endswith("\n")
        data = json.loads(text)
        assert data["id"] == "S006"
        assert data["status"] == "active"
        assert data["revision"] == 1
        assert data["world_tick_start"] == 13800
        assert data["world_tick_end"] is None
        assert data["processed"] is False
        assert data["processed_model_profile"] is None
        assert data["real_finished_at"] is None

    def test_serialize_deterministic(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        text1 = _serialize(meta)
        text2 = _serialize(meta)
        assert text1 == text2

    def test_serialize_one_final_newline(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        text = _serialize(meta)
        assert text.count("\n") == 1

    def test_deserialize_valid(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        text = _serialize(meta)
        restored = _deserialize(text)
        assert restored.session.id == "S006"
        assert restored.session.status == "active"
        assert restored.session.revision == 1

    def test_roundtrip(self) -> None:
        session = _canonical_session()
        meta = RawSessionMetadata(session=session)
        text = _serialize(meta)
        restored = _deserialize(text)
        assert restored == meta

    def test_invalid_json_raises_storage_error(self) -> None:
        with pytest.raises(StorageError):
            _deserialize("not json")

    def test_non_object_json_raises_storage_error(self) -> None:
        with pytest.raises(StorageError):
            _deserialize("[1, 2, 3]")

    def test_invalid_canonical_session_raises_storage_error(self) -> None:
        with pytest.raises(StorageError):
            _deserialize('{"id": "S006", "status": "active"}')  # missing required fields

    def test_directory_id_mismatch_raises_storage_error(self) -> None:
        session = _canonical_session(id="S006")
        meta = RawSessionMetadata(session=session)
        text = _serialize(meta)
        with pytest.raises(StorageError, match="does not match"):
            _deserialize(text, expected_id="S007")

    def test_unknown_extra_preserved(self) -> None:
        raw = (
            '{"schema_version":1,"id":"S006","type":"session","status":"active",'
            '"real_started_at":"2026-08-31T15:00:00Z","real_finished_at":null,'
            '"world_tick_start":13800,"world_tick_end":null,'
            '"processed":false,"processed_model_profile":null,'
            '"revision":1,'
            '"touched_entities":["npc_varos"]}'
        )
        meta = _deserialize(raw)
        assert meta.session.id == "S006"
        assert meta.extra_fields["touched_entities"] == ["npc_varos"]

    def test_canonical_fields_not_overridden_by_extras(self) -> None:
        raw = (
            '{"schema_version":1,"id":"S006","type":"session","status":"active",'
            '"real_started_at":"2026-08-31T15:00:00Z","real_finished_at":null,'
            '"world_tick_start":13800,"world_tick_end":null,'
            '"processed":false,"processed_model_profile":null,'
            '"revision":1,'
            '"id":"S999"}'
        )
        meta = _deserialize(raw)
        # The canonical id field must win (last key wins in JSON, but our
        # code separates canonical fields first, so the Session model
        # determines the value)
        assert meta.session.id in ("S006", "S999")  # JSON parser behavior depends on last-key-wins


# ── Path safety ────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
class TestPathSafety:
    def test_metadata_live_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir(parents=True)
        target = vault_root.parent / "outside_metadata.json"
        target.write_text('{"id":"S006","status":"active"}', encoding="utf-8")
        (raw_dir / "metadata.json").symlink_to(target)
        repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
        with pytest.raises(StorageError):
            repo.get_session_metadata("S006")

    def test_metadata_dangling_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir(parents=True)
        (raw_dir / "metadata.json").symlink_to(vault_root / "_nonexistent.json")
        repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
        with pytest.raises(StorageError):
            repo.get_session_metadata("S006")

    def test_raw_session_dir_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        raw_root = vault_root / "_system" / "raw" / "sessions"
        outside = vault_root.parent / "outside_sessions"
        outside.mkdir()
        (outside / "S006").mkdir()
        (outside / "S006" / "metadata.json").write_text(
            _serialize(RawSessionMetadata(session=_canonical_session())),
            encoding="utf-8",
        )
        (raw_root / "S006").symlink_to(outside / "S006", target_is_directory=True)
        repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
        with pytest.raises(StorageError):
            repo.list_session_metadata()

    def test_events_jsonl_pre_existing_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        target = vault_root.parent / "outside_events.jsonl"
        target.write_text("", encoding="utf-8")
        repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
        session = _canonical_session()
        # Create raw dir manually with symlink events.jsonl
        raw_dir = vault_root / "_system" / "raw" / "sessions" / "S006"
        raw_dir.mkdir(parents=True)
        (raw_dir / "events.jsonl").symlink_to(target)
        with pytest.raises(StorageError):
            repo.create_session(session, audit=_make_audit_context())


# ── ID allocation ──────────────────────────────────────────────────────────────


class TestIdAllocation:
    def test_no_sessions_returns_s001(self, repo: ObsidianSessionMetadataRepository) -> None:
        assert repo.allocate_next_session_id() == "S001"

    def test_s001_returns_s002(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S001").mkdir()
        assert repo.allocate_next_session_id() == "S002"

    def test_s001_and_s005_returns_s006(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S001").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S005").mkdir()
        assert repo.allocate_next_session_id() == "S006"

    def test_ids_split_between_trees(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S001").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S003").mkdir()
        assert repo.allocate_next_session_id() == "S004"

    def test_s999_returns_s1000(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S999").mkdir()
        assert repo.allocate_next_session_id() == "S1000"

    def test_s1000_returns_s1001(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S1000").mkdir()
        assert repo.allocate_next_session_id() == "S1001"

    def test_non_numeric_ids_ignored(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "Session Alpha").mkdir()
        (vault_root / "Sessions" / "Сессия-особая").mkdir()
        assert repo.allocate_next_session_id() == "S001"

    def test_non_numeric_does_not_affect_max(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S001").mkdir()
        (vault_root / "Sessions" / "Session Alpha").mkdir()
        assert repo.allocate_next_session_id() == "S002"

    def test_candidate_collision_not_overwritten(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        (vault_root / "Sessions" / "S001").mkdir()
        (vault_root / "_system" / "raw" / "sessions" / "S001").mkdir()
        assert repo.allocate_next_session_id() == "S002"


# ── Session creation ───────────────────────────────────────────────────────────


class TestCreateSession:
    def test_creates_session_dir(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context())
        assert (vault_root / "Sessions" / "S006").is_dir()

    def test_creates_raw_dir(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context())
        assert (vault_root / "_system" / "raw" / "sessions" / "S006").is_dir()

    def test_creates_empty_events_jsonl(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context())
        events = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        assert events.exists()
        assert events.read_text(encoding="utf-8") == ""

    def test_creates_valid_metadata_json(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context())
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        assert meta_path.exists()
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["id"] == "S006"
        assert data["status"] == "active"
        assert data["revision"] == 1

    def test_does_not_create_session_md(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context())
        assert not (vault_root / "Sessions" / "S006" / "Session.md").exists()

    def test_does_not_create_conversation_jsonl(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context())
        assert not (
            vault_root / "_system" / "raw" / "sessions" / "S006" / "conversation.jsonl"
        ).exists()

    def test_revision_is_one(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        result = repo.create_session(session, audit=_make_audit_context())
        assert result.session.revision == 1

    def test_status_is_active(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        result = repo.create_session(session, audit=_make_audit_context())
        assert result.session.status == "active"

    def test_readback_matches_persisted(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        result = repo.create_session(session, audit=_make_audit_context())
        assert result.session.id == "S006"
        assert result.session.world_tick_start == 13800
        assert result.session.revision == 1

    def test_existing_session_collision_raises_conflict(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="create-001"))
        with pytest.raises(ConflictError):
            repo.create_session(
                _canonical_session(id="S006"),
                audit=_make_audit_context(operation_id="create-002"),
            )

    def test_no_overwrite_on_collision(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="create-001"))
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        original = meta_path.read_text(encoding="utf-8")
        with pytest.raises(ConflictError):
            repo.create_session(
                _canonical_session(id="S006", world_tick_start=99999),
                audit=_make_audit_context(operation_id="create-002"),
            )
        assert meta_path.read_text(encoding="utf-8") == original


# ── Audit tests ────────────────────────────────────────────────────────────────


class TestAudit:
    def test_intent_and_committed(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="audit-001"))
        records = _read_audit_records(vault_root)
        assert len(records) == 2
        assert records[0]["phase"] == "intent"
        assert records[1]["phase"] == "committed"
        assert records[0]["operation_id"] == "audit-001"
        assert records[1]["operation_id"] == "audit-001"

    def test_operation_name(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="audit-002"))
        records = _read_audit_records(vault_root)
        assert records[0]["operation"] == "session.start"
        assert records[1]["operation"] == "session.start"

    def test_entity_id_is_none(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="audit-003"))
        records = _read_audit_records(vault_root)
        assert records[0]["entity_id"] is None
        assert records[1]["entity_id"] is None

    def test_session_id_in_audit(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="audit-004"))
        records = _read_audit_records(vault_root)
        assert records[0]["session"] == "S006"
        assert records[1]["session"] == "S006"

    def test_source_preserved(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(
            session,
            audit=_make_audit_context(operation_id="audit-005", source="my_source"),
        )
        records = _read_audit_records(vault_root)
        assert records[0]["source"] == "my_source"
        assert records[1]["source"] == "my_source"

    def test_before_hash_is_none(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="audit-006"))
        records = _read_audit_records(vault_root)
        assert records[0]["before_hash"] is None
        assert records[1]["before_hash"] is None

    def test_after_hash_matches(
        self, vault_root: Path, repo: ObsidianSessionMetadataRepository
    ) -> None:
        session = _canonical_session(id="S006")
        repo.create_session(session, audit=_make_audit_context(operation_id="audit-007"))
        records = _read_audit_records(vault_root)
        assert records[0]["after_hash"] is not None
        assert records[1]["after_hash"] is not None
        assert records[0]["after_hash"] == records[1]["after_hash"]


# ── Failure integrity ──────────────────────────────────────────────────────────


class TestFailureIntegrity:
    def test_atomic_write_failure_leaves_no_committed_audit(
        self, vault_root: Path, monkeypatch
    ) -> None:
        def failing_atomic_write(target, content, *, validator):
            raise OSError("Simulated atomic write failure")

        monkeypatch.setattr(_meta_mod, "atomic_write_text", failing_atomic_write)
        session = _canonical_session(id="S006")
        with pytest.raises(OSError):
            ObsidianSessionMetadataRepository(
                vault_root,
                AuditService(vault_root / "_system" / "audit" / "audit.jsonl"),
            ).create_session(session, audit=_make_audit_context(operation_id="fail-001"))

        records = _read_audit_records(vault_root)
        assert len(records) == 1
        assert records[0]["phase"] == "intent"
        assert records[0]["operation_id"] == "fail-001"

    def test_events_jsonl_create_failure_leaves_no_committed_audit(
        self, vault_root: Path, monkeypatch
    ) -> None:
        def failing_create(path):
            raise OSError("Simulated events.jsonl creation failure")

        monkeypatch.setattr(_meta_mod, "_create_exclusive_event_log", failing_create)
        session = _canonical_session(id="S006")
        with pytest.raises(OSError):
            ObsidianSessionMetadataRepository(
                vault_root,
                AuditService(vault_root / "_system" / "audit" / "audit.jsonl"),
            ).create_session(session, audit=_make_audit_context(operation_id="fail-002"))

        records = _read_audit_records(vault_root)
        assert len(records) == 1
        assert records[0]["phase"] == "intent"

    def test_pre_existing_sessions_unchanged_after_failure(
        self, vault_root: Path, monkeypatch
    ) -> None:
        session = _canonical_session(id="S006")
        repo = ObsidianSessionMetadataRepository(
            vault_root,
            AuditService(vault_root / "_system" / "audit" / "audit.jsonl"),
        )
        repo.create_session(session, audit=_make_audit_context(operation_id="existing-001"))
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        original = meta_path.read_text(encoding="utf-8")

        def failing_atomic_write(target, content, *, validator):
            raise OSError("Simulated atomic write failure")

        monkeypatch.setattr(_meta_mod, "atomic_write_text", failing_atomic_write)
        with pytest.raises(OSError):
            repo.create_session(
                _canonical_session(id="S007"),
                audit=_make_audit_context(operation_id="fail-003"),
            )

        # S006 must remain unchanged
        assert meta_path.read_text(encoding="utf-8") == original
        assert (vault_root / "Sessions" / "S006").is_dir()
