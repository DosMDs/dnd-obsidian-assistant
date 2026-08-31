"""Unit tests for S6-04 session close lifecycle.

Covers:
- Normal close of active session
- Close state verification (status, timestamps, revision, processing)
- touched_entities merge semantics
- processing_status pending
- Unknown extras preservation
- Lifecycle precondition failures
- Path safety / symlink rejection
- Audit intent/committed semantics
- Race/failure semantics
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
    _serialize,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _active_session(**overrides: object) -> Session:
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
    operation_id: str = "test-close-001",
    source: str = "test",
    session: str | None = "S006",
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
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


def _create_active_session(
    vault_root: Path,
    session_id: str = "S006",
    extras: dict | None = None,
) -> None:
    """Create an active session with metadata.json and empty events.jsonl."""
    session_dir = vault_root / "_system" / "raw" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    events_path = session_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    session = _active_session(id=session_id)
    meta = RawSessionMetadata(session=session, extra_fields=extras or {})
    text = _serialize(meta)
    metadata_path = session_dir / "metadata.json"
    # Use open with newline="" to avoid \n -> \r\n translation on Windows
    with open(metadata_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ── Normal close ────────────────────────────────────────────────────────────────


class TestNormalClose:
    def test_close_active_session_succeeds(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.session.status == "completed"
        assert result.session.revision == 2

    def test_status_is_completed(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.session.status == "completed"

    def test_real_finished_at_matches_audit_time(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        audit_time = datetime(2026, 8, 31, 19, 30, 0, tzinfo=UTC)
        ctx = AuditContext(
            operation_id="close-002",
            real_time=audit_time,
            source="test",
            session="S006",
        )
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=ctx,
        )
        assert result.session.real_finished_at == audit_time

    def test_world_tick_end_captured(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=99999,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.session.world_tick_end == 99999

    def test_revision_increments_exactly_one(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.session.revision == 2

    def test_processed_remains_false(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.session.processed is False

    def test_processed_model_profile_remains_none(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.session.processed_model_profile is None

    def test_processing_status_pending(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("processing_status") == "pending"

    def test_empty_touched_list_persisted(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("touched_entities") == []

    def test_touched_entities_persisted(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=["npc_varos", "loc_sunken_crypt"],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("touched_entities") == [
            "npc_varos",
            "loc_sunken_crypt",
        ]

    def test_unknown_extras_preserved(self, vault_root: Path, repo) -> None:
        _create_active_session(
            vault_root,
            "S006",
            extras={"legacy_field": "keep me", "custom_data": {"a": 1}},
        )
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("legacy_field") == "keep me"
        assert result.extra_fields.get("custom_data") == {"a": 1}

    def test_events_jsonl_unchanged_bytes(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        before_bytes = events_path.read_bytes()
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        after_bytes = events_path.read_bytes()
        assert before_bytes == after_bytes


# ── Touched-entity merge semantics ──────────────────────────────────────────────


class TestTouchedEntityMerge:
    def test_existing_touched_preserved(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006", extras={"touched_entities": ["npc_a"]})
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("touched_entities") == ["npc_a"]

    def test_existing_and_supplied_merged(self, vault_root: Path, repo) -> None:
        _create_active_session(
            vault_root,
            "S006",
            extras={"touched_entities": ["npc_a", "npc_b"]},
        )
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=["npc_b", "loc_c"],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("touched_entities") == ["npc_a", "npc_b", "loc_c"]

    def test_duplicate_supplied_deduplicated(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=["npc_a", "npc_a", "npc_b"],
            audit=_make_audit_context(),
        )
        assert result.extra_fields.get("touched_entities") == ["npc_a", "npc_b"]

    def test_invalid_supplied_id_raises_validation_error(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        with pytest.raises(ValidationError, match="entity ID"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[""],
                audit=_make_audit_context(),
            )

    def test_invalid_persisted_touched_shape_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006", extras={"touched_entities": "not_a_list"})
        with pytest.raises(StorageError, match="not a list"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_invalid_persisted_touched_value_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006", extras={"touched_entities": [123]})
        with pytest.raises(StorageError, match="non-string"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_no_mutation_on_invalid_input(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        metadata_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = metadata_path.read_bytes()
        events_before = events_path.read_bytes()
        with pytest.raises(ValidationError):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[""],
                audit=_make_audit_context(),
            )
        assert metadata_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before


# ── Lifecycle precondition failures ─────────────────────────────────────────────


class TestLifecyclePreconditions:
    def test_stale_expected_revision_raises_conflict(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        with pytest.raises(ConflictError, match="revision mismatch"):
            repo.close_session(
                "S006",
                expected_revision=99,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_completed_session_raises_conflict(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="close-1"),
        )
        with pytest.raises(ConflictError, match="not active"):
            repo.close_session(
                "S006",
                expected_revision=2,
                world_tick_end=16000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="close-2"),
            )

    def test_active_with_real_finished_at_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        text = meta_path.read_text(encoding="utf-8")
        text = text.replace(
            '"real_finished_at":null',
            '"real_finished_at":"2026-08-31T17:00:00+00:00"',
        )
        meta_path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError, match="real_finished_at"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_active_with_world_tick_end_set_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        text = meta_path.read_text(encoding="utf-8")
        text = text.replace('"world_tick_end":null', '"world_tick_end":14000')
        meta_path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError, match="world_tick_end"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_active_with_processed_true_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        text = meta_path.read_text(encoding="utf-8")
        text = text.replace('"processed":false', '"processed":true')
        meta_path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError, match="processed"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_active_with_processed_model_profile_set_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        text = meta_path.read_text(encoding="utf-8")
        text = text.replace(
            '"processed_model_profile":null',
            '"processed_model_profile":"post_session"',
        )
        meta_path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError, match="processed_model_profile"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_finish_time_before_start_raises_validation_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        audit_time = datetime(2026, 8, 31, 14, 0, 0, tzinfo=UTC)
        ctx = AuditContext(
            operation_id="close-bad-time",
            real_time=audit_time,
            source="test",
            session="S006",
        )
        with pytest.raises(ValidationError, match="predates"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=ctx,
            )

    def test_no_mutation_on_precondition_failure(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        metadata_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = metadata_path.read_bytes()
        events_before = events_path.read_bytes()
        with pytest.raises(ConflictError):
            repo.close_session(
                "S006",
                expected_revision=99,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )
        assert metadata_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before


# ── Path safety / symlink rejection ─────────────────────────────────────────────


class TestPathSafety:
    def test_missing_metadata_raises_not_found(self, vault_root: Path, repo) -> None:
        with pytest.raises(NotFoundError, match="not found"):
            repo.close_session(
                "S999",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    def test_missing_events_jsonl_raises_storage_error(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.unlink()
        with pytest.raises(StorageError, match="not found"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_metadata_live_symlink_rejected(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        target = vault_root / "external_target.json"
        target.write_text('{"id":"S006","status":"active"}\n', encoding="utf-8")
        meta_path.unlink()
        meta_path.symlink_to(target)
        with pytest.raises(StorageError, match="symlink"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_events_live_symlink_rejected(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        target = vault_root / "external_events.jsonl"
        target.write_text("", encoding="utf-8")
        events_path.unlink()
        events_path.symlink_to(target)
        with pytest.raises(StorageError, match="symlink"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_events_dangling_symlink_rejected(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_path.unlink()
        events_path.symlink_to(vault_root / "nonexistent.jsonl")
        with pytest.raises(StorageError, match="symlink"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(),
            )


# ── Close audit semantics ───────────────────────────────────────────────────────


class TestCloseAudit:
    def test_intent_and_committed_phases(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        audit_ctx = _make_audit_context(operation_id="audit-close-001")
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=audit_ctx,
        )
        records = _read_audit_records(vault_root)
        intent = [r for r in records if r.get("phase") == "intent"]
        committed = [r for r in records if r.get("phase") == "committed"]
        assert len(intent) == 1
        assert len(committed) == 1
        assert intent[0]["operation_id"] == "audit-close-001"
        assert committed[0]["operation_id"] == "audit-close-001"

    def test_operation_is_session_end(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-op"),
        )
        records = _read_audit_records(vault_root)
        for r in records:
            if r.get("operation_id") == "audit-op":
                assert r["operation"] == "session.end"

    def test_session_field_preserved(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-sess"),
        )
        records = _read_audit_records(vault_root)
        for r in records:
            if r.get("operation_id") == "audit-sess":
                assert r["session"] == "S006"

    def test_entity_id_is_none(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-eid"),
        )
        records = _read_audit_records(vault_root)
        for r in records:
            if r.get("operation_id") == "audit-eid":
                assert r.get("entity_id") is None

    def test_source_preserved(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        ctx = AuditContext(
            operation_id="audit-src",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            source="my_source",
            session="S006",
        )
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=ctx,
        )
        records = _read_audit_records(vault_root)
        for r in records:
            if r.get("operation_id") == "audit-src":
                assert r["source"] == "my_source"

    def test_real_time_preserved(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        audit_time = datetime(2026, 8, 31, 20, 15, 0, tzinfo=UTC)
        ctx = AuditContext(
            operation_id="audit-time",
            real_time=audit_time,
            source="test",
            session="S006",
        )
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=ctx,
        )
        records = _read_audit_records(vault_root)
        for r in records:
            if r.get("operation_id") == "audit-time":
                assert r["real_time"] == "2026-08-31T20:15:00Z"

    def test_before_hash_matches_original_metadata(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        # Use _read_exact_text to match how close_session reads
        from dnd_assistant.storage.session_metadata import _read_exact_text

        before_text = _read_exact_text(meta_path)
        expected_hash = hashlib.sha256(before_text.encode("utf-8")).hexdigest()
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-hash"),
        )
        records = _read_audit_records(vault_root)
        audit_records = [r for r in records if r.get("operation_id") == "audit-hash"]
        assert len(audit_records) >= 1
        # All records for this operation_id should have the same before_hash
        for r in audit_records:
            assert r["before_hash"] == expected_hash, (
                f"Record phase={r.get('phase')}: expected {expected_hash}, got {r['before_hash']}"
            )

    def test_model_profile_and_prompt_version_preserved(
        self,
        vault_root: Path,
        repo,
    ) -> None:
        _create_active_session(vault_root, "S006")
        ctx = AuditContext(
            operation_id="audit-model",
            real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
            source="test",
            session="S006",
            model_profile="test_model",
            prompt_version="v1",
        )
        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=ctx,
        )
        records = _read_audit_records(vault_root)
        for r in records:
            if r.get("operation_id") == "audit-model":
                assert r["model_profile"] == "test_model"
                assert r["prompt_version"] == "v1"
