"""Repository tests for ObsidianWorldTimeRepository.

Tests cover:
- path/layout: exact location, containment, symlink safety
- read: valid, missing, corrupt, invalid schema
- initialize: missing, existing, invalid tick
- update: success, revision increment, stale revision, backward tick
- audit: intent/committed records, correct hashes, entity_id is None
- failure integrity: atomic write failure, race detection
"""

from __future__ import annotations

import json
import os
from datetime import UTC
from pathlib import Path

import pytest

from dnd_assistant.errors import ConflictError, NotFoundError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_audit_context(
    operation_id: str = "test-op-001",
    source: str = "test",
) -> AuditContext:
    from datetime import datetime

    return AuditContext(
        operation_id=operation_id,
        real_time=datetime.now(UTC),
        source=source,
    )


def _write_world_time(vault_root: Path, tick: int = 13800, revision: int = 1) -> Path:
    """Write a valid world_time.json to the Vault."""
    path = vault_root / "_system" / "world_time.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "type": "world_time",
        "current_world_tick": tick,
        "revision": revision,
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _read_audit_records(vault_root: Path) -> list[dict]:
    """Read and parse all audit records from the audit log."""
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
    audit_dir = root / "_system" / "audit"
    audit_dir.mkdir(parents=True)
    return root


@pytest.fixture
def audit_service(vault_root: Path) -> AuditService:
    audit_log = vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(audit_log)


@pytest.fixture
def repo(vault_root: Path, audit_service: AuditService) -> ObsidianWorldTimeRepository:
    return ObsidianWorldTimeRepository(vault_root, audit_service)


def _symlinks_supported() -> bool:
    """Check whether the OS supports creating symlinks in a temp directory."""
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


# ── Path/layout tests ─────────────────────────────────────────────────────────


class TestPathLayout:
    """Canonical path resolution and containment."""

    def test_exact_location(self, repo: ObsidianWorldTimeRepository) -> None:
        assert repo.world_time_path.name == "world_time.json"
        assert repo.world_time_path.parent.name == "_system"

    def test_absolute_path(self, repo: ObsidianWorldTimeRepository) -> None:
        assert repo.world_time_path.is_absolute()

    def test_contained_under_vault(self, repo: ObsidianWorldTimeRepository) -> None:
        repo.world_time_path.relative_to(repo.vault_root)

    def test_missing_file_not_created_on_read(self, repo: ObsidianWorldTimeRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.get_current_world_time()
        assert not repo.world_time_path.exists()

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_system_live_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        system_dir = vault_root / "_system"
        real_system = vault_root / "_real_system"
        real_system.mkdir()
        (real_system / "audit").mkdir()
        import shutil

        for item in list(system_dir.iterdir()):
            shutil.move(str(item), str(real_system / item.name))
        system_dir.rmdir()
        system_dir.symlink_to(real_system, target_is_directory=True)
        with pytest.raises(StorageError):
            ObsidianWorldTimeRepository(vault_root, audit_service)

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_system_dangling_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        system_dir = vault_root / "_system"
        import shutil

        shutil.rmtree(str(system_dir))
        system_dir.symlink_to(vault_root / "_nonexistent", target_is_directory=True)
        with pytest.raises(StorageError):
            ObsidianWorldTimeRepository(vault_root, audit_service)

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_world_time_live_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        _write_world_time(vault_root)
        real_path = vault_root / "_system" / "world_time.json"
        symlink_path = vault_root / "_system" / "world_time_link.json"
        symlink_path.symlink_to(real_path)
        real_path.unlink()
        symlink_path.rename(real_path)
        repo = ObsidianWorldTimeRepository(vault_root, audit_service)
        with pytest.raises(NotFoundError):
            repo.get_current_world_time()

    @pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
    def test_world_time_dangling_symlink_rejected(
        self, vault_root: Path, audit_service: AuditService
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(vault_root / "_nonexistent.json")
        repo = ObsidianWorldTimeRepository(vault_root, audit_service)
        with pytest.raises(NotFoundError):
            repo.get_current_world_time()


# ── Read tests ────────────────────────────────────────────────────────────────


class TestRead:
    """Reading current world time."""

    def test_valid_read(self, vault_root: Path, repo: ObsidianWorldTimeRepository) -> None:
        _write_world_time(vault_root, tick=13800, revision=1)
        state = repo.get_current_world_time()
        assert state.current_world_tick == 13800
        assert state.revision == 1

    def test_missing_raises_not_found(self, repo: ObsidianWorldTimeRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.get_current_world_time()

    def test_malformed_json_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_json_array_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_json_string_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('"hello"', encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_wrong_schema_version_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 99,
            "type": "world_time",
            "current_world_tick": 0,
            "revision": 1,
        }
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_wrong_type_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "type": "campaign_state",
            "current_world_tick": 0,
            "revision": 1,
        }
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_invalid_tick_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "type": "world_time",
            "current_world_tick": "not_a_tick",
            "revision": 1,
        }
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_invalid_revision_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "type": "world_time",
            "current_world_tick": 0,
            "revision": 0,
        }
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()

    def test_unknown_field_raises_storage_error(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        path = vault_root / "_system" / "world_time.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "type": "world_time",
            "current_world_tick": 0,
            "revision": 1,
            "unknown_field": "unexpected",
        }
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StorageError):
            repo.get_current_world_time()


# ── Initialize tests ──────────────────────────────────────────────────────────


class TestInitialize:
    """Initializing world time state."""

    def test_initialize_missing(self, repo: ObsidianWorldTimeRepository) -> None:
        state = repo.initialize_current_world_time(13800, audit=_make_audit_context())
        assert state.current_world_tick == 13800
        assert state.revision == 1

    def test_initialize_negative_tick(self, repo: ObsidianWorldTimeRepository) -> None:
        state = repo.initialize_current_world_time(-500, audit=_make_audit_context())
        assert state.current_world_tick == -500
        assert state.revision == 1

    def test_initialize_zero_tick(self, repo: ObsidianWorldTimeRepository) -> None:
        state = repo.initialize_current_world_time(0, audit=_make_audit_context())
        assert state.current_world_tick == 0
        assert state.revision == 1

    def test_initialize_existing_raises_conflict(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root)
        with pytest.raises(ConflictError):
            repo.initialize_current_world_time(200, audit=_make_audit_context())

    def test_initialize_invalid_tick_raises_validation_error(
        self, repo: ObsidianWorldTimeRepository
    ) -> None:
        with pytest.raises(ValidationError):
            repo.initialize_current_world_time("bad", audit=_make_audit_context())

    def test_initialize_bool_tick_raises_validation_error(
        self, repo: ObsidianWorldTimeRepository
    ) -> None:
        with pytest.raises(ValidationError):
            repo.initialize_current_world_time(True, audit=_make_audit_context())

    def test_initialize_float_tick_raises_validation_error(
        self, repo: ObsidianWorldTimeRepository
    ) -> None:
        with pytest.raises(ValidationError):
            repo.initialize_current_world_time(100.0, audit=_make_audit_context())

    def test_initialize_verified_readback(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        repo.initialize_current_world_time(500, audit=_make_audit_context(operation_id="init-001"))
        state = repo.get_current_world_time()
        assert state.current_world_tick == 500
        assert state.revision == 1


# ── Update tests ──────────────────────────────────────────────────────────────


class TestUpdate:
    """Updating world time state."""

    def test_successful_update(self, vault_root: Path, repo: ObsidianWorldTimeRepository) -> None:
        _write_world_time(vault_root, tick=100, revision=1)
        state = repo.set_current_world_time(
            200,
            expected_revision=1,
            audit=_make_audit_context(),
        )
        assert state.current_world_tick == 200
        assert state.revision == 2

    def test_revision_increments_exactly_one(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=0, revision=5)
        state = repo.set_current_world_time(
            10,
            expected_revision=5,
            audit=_make_audit_context(),
        )
        assert state.revision == 6

    def test_stale_revision_raises_conflict(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=100, revision=3)
        with pytest.raises(ConflictError):
            repo.set_current_world_time(
                200,
                expected_revision=2,
                audit=_make_audit_context(),
            )

    def test_missing_raises_not_found(self, repo: ObsidianWorldTimeRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.set_current_world_time(
                100,
                expected_revision=1,
                audit=_make_audit_context(),
            )

    def test_backward_update_accepted(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=1000, revision=1)
        state = repo.set_current_world_time(
            -500,
            expected_revision=1,
            audit=_make_audit_context(),
        )
        assert state.current_world_tick == -500
        assert state.revision == 2

    def test_invalid_tick_rejected(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=100, revision=1)
        with pytest.raises(ValidationError):
            repo.set_current_world_time(
                "bad",
                expected_revision=1,
                audit=_make_audit_context(),
            )

    def test_invalid_expected_revision_rejected(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=100, revision=1)
        with pytest.raises(ValidationError):
            repo.set_current_world_time(
                200,
                expected_revision="bad",
                audit=_make_audit_context(),
            )


# ── Audit tests ───────────────────────────────────────────────────────────────


class TestAudit:
    """Audit record verification for world-time mutations."""

    def test_initialize_has_intent_and_committed(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        repo.initialize_current_world_time(
            100, audit=_make_audit_context(operation_id="audit-init-001")
        )
        records = _read_audit_records(vault_root)
        assert len(records) == 2
        assert records[0]["phase"] == "intent"
        assert records[1]["phase"] == "committed"
        assert records[0]["operation_id"] == "audit-init-001"
        assert records[1]["operation_id"] == "audit-init-001"

    def test_initialize_operation_name(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        repo.initialize_current_world_time(
            100, audit=_make_audit_context(operation_id="audit-init-002")
        )
        records = _read_audit_records(vault_root)
        assert records[0]["operation"] == "world_time.initialize"
        assert records[1]["operation"] == "world_time.initialize"

    def test_update_has_intent_and_committed(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=0, revision=1)
        repo.set_current_world_time(
            200,
            expected_revision=1,
            audit=_make_audit_context(operation_id="audit-upd-001"),
        )
        records = _read_audit_records(vault_root)
        assert len(records) == 2
        intent = records[0]
        committed = records[1]
        assert intent["phase"] == "intent"
        assert committed["phase"] == "committed"
        assert intent["operation_id"] == "audit-upd-001"
        assert committed["operation_id"] == "audit-upd-001"

    def test_update_operation_name(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=0, revision=1)
        repo.set_current_world_time(
            200,
            expected_revision=1,
            audit=_make_audit_context(operation_id="audit-upd-002"),
        )
        records = _read_audit_records(vault_root)
        intent = records[0]
        committed = records[1]
        assert intent["operation"] == "world_time.update"
        assert committed["operation"] == "world_time.update"

    def test_entity_id_is_none(self, vault_root: Path, repo: ObsidianWorldTimeRepository) -> None:
        repo.initialize_current_world_time(
            100, audit=_make_audit_context(operation_id="audit-eid-001")
        )
        records = _read_audit_records(vault_root)
        assert records[0]["entity_id"] is None
        assert records[1]["entity_id"] is None

    def test_source_preserved(self, vault_root: Path, repo: ObsidianWorldTimeRepository) -> None:
        ctx = _make_audit_context(operation_id="audit-src-001", source="my_source")
        repo.initialize_current_world_time(100, audit=ctx)
        records = _read_audit_records(vault_root)
        assert records[0]["source"] == "my_source"
        assert records[1]["source"] == "my_source"

    def test_session_preserved(self, vault_root: Path, repo: ObsidianWorldTimeRepository) -> None:
        from datetime import datetime

        ctx = AuditContext(
            operation_id="audit-ses-001",
            real_time=datetime.now(UTC),
            source="test",
            session="S001",
        )
        repo.initialize_current_world_time(100, audit=ctx)
        records = _read_audit_records(vault_root)
        assert records[0]["session"] == "S001"
        assert records[1]["session"] == "S001"

    def test_initialize_before_hash_none(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        repo.initialize_current_world_time(
            100, audit=_make_audit_context(operation_id="audit-bh-001")
        )
        records = _read_audit_records(vault_root)
        assert records[0]["before_hash"] is None
        assert records[1]["before_hash"] is None

    def test_initialize_after_hash_not_none(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        repo.initialize_current_world_time(
            100, audit=_make_audit_context(operation_id="audit-ah-001")
        )
        records = _read_audit_records(vault_root)
        assert records[0]["after_hash"] is not None
        assert records[1]["after_hash"] is not None
        assert records[0]["after_hash"] == records[1]["after_hash"]

    def test_update_before_and_after_hashes(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=0, revision=1)
        repo.set_current_world_time(
            200,
            expected_revision=1,
            audit=_make_audit_context(operation_id="audit-hash-001"),
        )
        records = _read_audit_records(vault_root)
        intent = records[0]
        committed = records[1]
        assert intent["before_hash"] is not None
        assert intent["after_hash"] is not None
        assert committed["before_hash"] is not None
        assert committed["after_hash"] is not None
        assert intent["before_hash"] == committed["before_hash"]
        assert intent["after_hash"] == committed["after_hash"]
        assert intent["before_hash"] != intent["after_hash"]


# ── Failure integrity tests ───────────────────────────────────────────────────


class TestFailureIntegrity:
    """Failure integrity for world-time mutations."""

    def test_atomic_write_failure_leaves_existing_unchanged(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository, monkeypatch
    ) -> None:
        _write_world_time(vault_root, tick=100, revision=1)
        original_text = (vault_root / "_system" / "world_time.json").read_text(encoding="utf-8")

        import dnd_assistant.storage.atomic as atomic_mod

        def failing_replace(src, dst):
            raise OSError("Simulated atomic write failure")

        monkeypatch.setattr(atomic_mod, "_os_replace", failing_replace)

        with pytest.raises(OSError):
            repo.set_current_world_time(
                200,
                expected_revision=1,
                audit=_make_audit_context(operation_id="fail-001"),
            )

        # Original file unchanged
        assert (vault_root / "_system" / "world_time.json").read_text(
            encoding="utf-8"
        ) == original_text

    def test_initialize_write_failure_leaves_file_missing(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository, monkeypatch
    ) -> None:
        import dnd_assistant.storage.atomic as atomic_mod

        def failing_replace(src, dst):
            raise OSError("Simulated atomic write failure")

        monkeypatch.setattr(atomic_mod, "_os_replace", failing_replace)

        with pytest.raises(OSError):
            repo.initialize_current_world_time(
                100, audit=_make_audit_context(operation_id="fail-init-001")
            )

        # File should still be missing
        assert not (vault_root / "_system" / "world_time.json").exists()

    def test_failed_mutation_has_no_committed_audit(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository, monkeypatch
    ) -> None:
        _write_world_time(vault_root, tick=100, revision=1)

        import dnd_assistant.storage.atomic as atomic_mod

        def failing_replace(src, dst):
            raise OSError("Simulated atomic write failure")

        monkeypatch.setattr(atomic_mod, "_os_replace", failing_replace)

        with pytest.raises(OSError):
            repo.set_current_world_time(
                200,
                expected_revision=1,
                audit=_make_audit_context(operation_id="fail-audit-001"),
            )

        records = _read_audit_records(vault_root)
        # Should have intent but no committed
        assert len(records) == 1
        assert records[0]["phase"] == "intent"
        assert records[0]["operation_id"] == "fail-audit-001"

    def test_content_change_race_detected(
        self, vault_root: Path, repo: ObsidianWorldTimeRepository
    ) -> None:
        _write_world_time(vault_root, tick=100, revision=1)
        path = vault_root / "_system" / "world_time.json"

        # Modify the file directly (simulating a concurrent write)
        data = {
            "schema_version": 1,
            "type": "world_time",
            "current_world_tick": 999,
            "revision": 2,
        }
        modified = (
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        )
        path.write_text(modified, encoding="utf-8")

        # Now try to update with stale expected_revision
        with pytest.raises(ConflictError):
            repo.set_current_world_time(
                200,
                expected_revision=1,  # Stale — file now has revision 2
                audit=_make_audit_context(operation_id="race-001"),
            )
