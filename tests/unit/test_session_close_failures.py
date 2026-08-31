"""S6-C04/S6-C04F correction tests — session close failure/race/integrity coverage.

Covers:
- Exact before_hash and after_hash audit regression
- Atomic metadata-write failure after durable intent
- Genuine audit-intent failure (audit append raises before mutation)
- Metadata changed after intent race
- Events changed after intent before metadata close race
- Events changed after metadata close race
- Committed close audit failure
- Canonical runtime root race
- Post-write symlink-race
- Strict Revision/WorldTick/scalar touched-ID/processing_status validation
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import dnd_assistant.storage.session_metadata as _meta_mod
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, StorageError, ValidationError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
    _read_exact_text,
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
    session_dir = vault_root / "_system" / "raw" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    events_path = session_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    session = _active_session(id=session_id)
    meta = RawSessionMetadata(session=session, extra_fields=extras or {})
    text = _serialize(meta)
    metadata_path = session_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Exact after_hash audit regression ──────────────────────────────────────────


class TestExactCloseAuditHash:
    def test_before_hash_exact(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        before_text = meta_path.read_text(encoding="utf-8")
        expected_before = _content_hash(before_text)

        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-before"),
        )
        records = _read_audit_records(vault_root)
        audit_recs = [r for r in records if r.get("operation_id") == "audit-before"]
        for r in audit_recs:
            assert r["before_hash"] == expected_before, (
                f"phase={r.get('phase')}: expected {expected_before}, got {r['before_hash']}"
            )

    def test_after_hash_exact(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-after"),
        )
        persisted_text = _serialize(result)
        expected_after = _content_hash(persisted_text)

        records = _read_audit_records(vault_root)
        audit_recs = [r for r in records if r.get("operation_id") == "audit-after"]
        for r in audit_recs:
            assert r["after_hash"] == expected_after, (
                f"phase={r.get('phase')}: expected {expected_after}, got {r['after_hash']}"
            )


# ── Atomic write failure ────────────────────────────────────────────────────────


class TestAtomicWriteFailure:
    def test_atomic_write_failure_after_intent(self, vault_root: Path, repo, monkeypatch) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = meta_path.read_bytes()
        events_before = events_path.read_bytes()

        original_append = repo._audit_service.append
        call_count = 0

        def tracking_append(record):
            nonlocal call_count
            call_count += 1
            original_append(record)
            if call_count == 1:
                monkeypatch.setattr(
                    _meta_mod,
                    "atomic_write_text",
                    lambda **kw: (_ for _ in ()).throw(
                        StorageError("simulated atomic write failure")
                    ),
                )

        monkeypatch.setattr(repo._audit_service, "append", tracking_append)

        with pytest.raises(StorageError, match="simulated atomic write failure"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="fail-write"),
            )

        assert meta_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before

        active = repo.get_active_session()
        assert active is not None
        assert active.session.status == "active"

        records = _read_audit_records(vault_root)
        fail_recs = [r for r in records if r.get("operation_id") == "fail-write"]
        intent_recs = [r for r in fail_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in fail_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Genuine audit-intent failure ────────────────────────────────────────────────


class TestGenuineAuditIntentFailure:
    """AuditService.append itself raises before writing the intent record.

    Expected:
        - close_session raises StorageError
        - metadata bytes unchanged
        - events bytes unchanged
        - session remains active
        - NO audit records for this operation_id
        - atomic_write_text was NEVER called
    """

    def test_audit_intent_failure_prevents_mutation(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = meta_path.read_bytes()
        events_before = events_path.read_bytes()

        atomic_write_call_count = 0
        original_atomic = _meta_mod.atomic_write_text

        def tracking_atomic(target, content, *, validator):
            nonlocal atomic_write_call_count
            atomic_write_call_count += 1
            return original_atomic(target=target, content=content, validator=validator)

        monkeypatch.setattr(_meta_mod, "atomic_write_text", tracking_atomic)

        original_append = repo._audit_service.append
        call_count = 0

        def failing_audit_intent(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise StorageError("simulated close audit intent failure")
            original_append(record)

        monkeypatch.setattr(repo._audit_service, "append", failing_audit_intent)

        with pytest.raises(StorageError, match="simulated close audit intent failure"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="fail-intent"),
            )

        assert meta_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before

        active = repo.get_active_session()
        assert active is not None
        assert active.session.status == "active"

        records = _read_audit_records(vault_root)
        fail_recs = [r for r in records if r.get("operation_id") == "fail-intent"]
        assert len(fail_recs) == 0, (
            f"Expected zero audit records for failed intent, got {len(fail_recs)}"
        )

        assert atomic_write_call_count == 0, (
            f"atomic_write_text was called {atomic_write_call_count} times, expected 0"
        )


# ── Metadata changed after intent race ─────────────────────────────────────────


class TestMetadataChangedAfterIntent:
    def test_metadata_changed_after_intent_raises_conflict(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        events_before = events_path.read_bytes()

        original_append = repo._audit_service.append
        call_count = 0

        def mutate_after_intent(record):
            nonlocal call_count
            call_count += 1
            original_append(record)
            if call_count == 1:
                competitor = _active_session(id="S006", revision=2, status="active")
                comp_meta = RawSessionMetadata(session=competitor)
                comp_text = _serialize(comp_meta)
                meta_path.write_text(comp_text, encoding="utf-8")

        monkeypatch.setattr(repo._audit_service, "append", mutate_after_intent)

        with pytest.raises(ConflictError, match="changed after intent"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="race-meta"),
            )

        assert meta_path.exists()
        assert events_path.read_bytes() == events_before

        records = _read_audit_records(vault_root)
        race_recs = [r for r in records if r.get("operation_id") == "race-meta"]
        intent_recs = [r for r in race_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in race_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Events changed after intent before metadata close race ─────────────────────


class TestEventsChangedAfterIntent:
    def test_events_changed_after_intent_raises_conflict(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        meta_before = meta_path.read_bytes()

        original_append = repo._audit_service.append
        call_count = 0

        def mutate_events_after_intent(record):
            nonlocal call_count
            call_count += 1
            original_append(record)
            if call_count == 1:
                competitor_line = (
                    '{"event_id":"evt_001","real_time":"2026-08-31T18:30:00+00:00",'
                    '"type":"note","world_tick":14500}\n'
                )
                with open(events_path, "a", encoding="utf-8", newline="") as f:
                    f.write(competitor_line)

        monkeypatch.setattr(repo._audit_service, "append", mutate_events_after_intent)

        with pytest.raises(ConflictError, match="changed after intent"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="race-events"),
            )

        assert events_path.exists()
        assert meta_path.read_bytes() == meta_before

        records = _read_audit_records(vault_root)
        race_recs = [r for r in records if r.get("operation_id") == "race-events"]
        intent_recs = [r for r in race_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in race_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Events changed after metadata close ────────────────────────────────────────


class TestEventsChangedAfterMetadataClose:
    def test_events_changed_after_metadata_close_raises_storage_error(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"

        original_atomic = _meta_mod.atomic_write_text

        def mutating_atomic(target, content, *, validator):
            original_atomic(target=target, content=content, validator=validator)
            competitor_line = (
                '{"event_id":"evt_001","real_time":"2026-08-31T18:30:00+00:00",'
                '"type":"note","world_tick":14500}\n'
            )
            with open(events_path, "a", encoding="utf-8", newline="") as f:
                f.write(competitor_line)

        monkeypatch.setattr(_meta_mod, "atomic_write_text", mutating_atomic)

        with pytest.raises(StorageError, match="changed after metadata close"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="race-post-close"),
            )

        assert meta_path.exists()
        meta_text = meta_path.read_text(encoding="utf-8")
        assert '"status":"completed"' in meta_text

        assert events_path.exists()

        records = _read_audit_records(vault_root)
        race_recs = [r for r in records if r.get("operation_id") == "race-post-close"]
        intent_recs = [r for r in race_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in race_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Committed close audit failure ──────────────────────────────────────────────


class TestCommittedAuditFailure:
    def test_committed_audit_failure_leaves_completed_metadata(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_before = events_path.read_bytes()

        original_append = repo._audit_service.append
        call_count = 0

        def failing_committed(record):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise StorageError("simulated committed audit failure")
            original_append(record)

        monkeypatch.setattr(repo._audit_service, "append", failing_committed)

        with pytest.raises(StorageError, match="audit finalization failed"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="fail-committed"),
            )

        assert meta_path.exists()
        meta_text = meta_path.read_text(encoding="utf-8")
        assert '"status":"completed"' in meta_text
        assert '"processing_status":"pending"' in meta_text

        assert events_path.read_bytes() == events_before

        records = _read_audit_records(vault_root)
        fail_recs = [r for r in records if r.get("operation_id") == "fail-committed"]
        intent_recs = [r for r in fail_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in fail_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Canonical runtime root race ────────────────────────────────────────────────


class TestRuntimeRootRace:
    def test_missing_runtime_root_after_intent_raises_storage_error(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"

        original_append = repo._audit_service.append
        call_count = 0

        def remove_root_after_intent(record):
            nonlocal call_count
            call_count += 1
            original_append(record)
            if call_count == 1:
                import shutil

                shutil.rmtree(vault_root / "_system" / "raw")

        monkeypatch.setattr(repo._audit_service, "append", remove_root_after_intent)

        with pytest.raises(StorageError, match="does not exist"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="race-root"),
            )

        assert not meta_path.exists()
        assert not events_path.exists()

        records = _read_audit_records(vault_root)
        race_recs = [r for r in records if r.get("operation_id") == "race-root"]
        intent_recs = [r for r in race_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in race_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Post-write symlink-race ─────────────────────────────────────────────────────


@pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="OS does not support symlinks")
class TestPostWriteSymlinkRace:
    def test_events_replaced_with_symlink_after_metadata_write_raises_storage_error(
        self, vault_root: Path, repo, monkeypatch
    ) -> None:
        _create_active_session(vault_root, "S006")
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"

        original_atomic = _meta_mod.atomic_write_text

        def symlink_after_atomic(target, content, *, validator):
            original_atomic(target=target, content=content, validator=validator)
            external_target = vault_root / "external_events.jsonl"
            external_target.write_text("", encoding="utf-8")
            events_path.unlink()
            events_path.symlink_to(external_target)

        monkeypatch.setattr(_meta_mod, "atomic_write_text", symlink_after_atomic)

        with pytest.raises(StorageError, match="symlink"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="symlink-race"),
            )

        assert meta_path.exists()
        meta_text = meta_path.read_text(encoding="utf-8")
        assert '"status":"completed"' in meta_text

        records = _read_audit_records(vault_root)
        race_recs = [r for r in records if r.get("operation_id") == "symlink-race"]
        intent_recs = [r for r in race_recs if r.get("phase") == "intent"]
        assert len(intent_recs) == 1

        committed_recs = [r for r in race_recs if r.get("phase") == "committed"]
        assert len(committed_recs) == 0


# ── Strict expected_revision validation ────────────────────────────────────────


class TestStrictRevisionValidation:
    """Repository-level invalid expected_revision regressions.

    Every invalid value must:
    - raise ValidationError
    - leave metadata bytes unchanged
    - leave events bytes unchanged
    - produce zero audit records for the operation
    """

    @pytest.mark.parametrize(
        "bad_revision",
        [
            True,
            False,
            1.0,
            "1",
            0,
            -1,
        ],
    )
    def test_invalid_expected_revision_raises_validation_error(
        self, vault_root: Path, repo, bad_revision
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = meta_path.read_bytes()
        events_before = events_path.read_bytes()

        with pytest.raises(ValidationError):
            repo.close_session(
                "S006",
                expected_revision=bad_revision,  # type: ignore[arg-type]
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="bad-revision"),
            )

        assert meta_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before

        records = _read_audit_records(vault_root)
        bad_recs = [r for r in records if r.get("operation_id") == "bad-revision"]
        assert len(bad_recs) == 0


# ── Strict world_tick_end validation ───────────────────────────────────────────


class TestStrictWorldTickValidation:
    """Repository-level invalid world_tick_end regressions.

    Every invalid value must:
    - raise ValidationError
    - leave metadata bytes unchanged
    - leave events bytes unchanged
    - produce zero audit records for the operation

    Valid signed integer WorldTick values must still be accepted.
    """

    @pytest.mark.parametrize(
        "bad_tick",
        [
            True,
            False,
            1.0,
            "15000",
        ],
    )
    def test_invalid_world_tick_end_raises_validation_error(
        self, vault_root: Path, repo, bad_tick
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = meta_path.read_bytes()
        events_before = events_path.read_bytes()

        with pytest.raises(ValidationError):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=bad_tick,  # type: ignore[arg-type]
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="bad-tick"),
            )

        assert meta_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before

        records = _read_audit_records(vault_root)
        bad_recs = [r for r in records if r.get("operation_id") == "bad-tick"]
        assert len(bad_recs) == 0

    def test_negative_world_tick_end_allowed(self, vault_root: Path, repo) -> None:
        """Valid signed integer WorldTick values must be accepted."""
        _create_active_session(vault_root, "S006")
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=-500,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="neg-tick"),
        )
        assert result.session.world_tick_end == -500


# ── Scalar touched_entity_ids ──────────────────────────────────────────────────


class TestScalarTouchedEntityIds:
    """Repository-level scalar touched_entity_ids regressions.

    Scalar str/bytes/bytearray must never be iterated as IDs.
    Every case must:
    - raise ValidationError
    - leave metadata bytes unchanged
    - leave events bytes unchanged
    - produce zero audit records for the operation
    """

    @pytest.mark.parametrize(
        "scalar",
        [
            "npc_varos",
            b"npc_varos",
            bytearray(b"npc_varos"),
        ],
    )
    def test_scalar_touched_entity_ids_raises_validation_error(
        self, vault_root: Path, repo, scalar
    ) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = meta_path.read_bytes()
        events_before = events_path.read_bytes()

        with pytest.raises(ValidationError, match="scalar"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=scalar,  # type: ignore[arg-type]
                audit=_make_audit_context(operation_id="scalar-touch"),
            )

        assert meta_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before

        records = _read_audit_records(vault_root)
        bad_recs = [r for r in records if r.get("operation_id") == "scalar-touch"]
        assert len(bad_recs) == 0


# ── Persisted processing_status corruption ─────────────────────────────────────


class TestProcessingStatusCorruption:
    """Repository-level persisted processing_status corruption regressions.

    Invalid persisted processing_status values must:
    - raise StorageError
    - leave metadata bytes unchanged
    - leave events bytes unchanged
    - produce zero close audit records
    - session remains active

    A pre-existing string processing_status must be accepted and replaced
    with "pending".
    """

    @pytest.mark.parametrize(
        "bad_extras",
        [
            {"processing_status": 123},
            {"processing_status": None},
            {"processing_status": ["pending"]},
            {"processing_status": {"state": "pending"}},
        ],
    )
    def test_corrupt_processing_status_raises_storage_error(
        self, vault_root: Path, repo, bad_extras
    ) -> None:
        _create_active_session(vault_root, "S006", extras=bad_extras)
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"
        events_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "events.jsonl"
        meta_before = meta_path.read_bytes()
        events_before = events_path.read_bytes()

        with pytest.raises(StorageError, match="processing_status"):
            repo.close_session(
                "S006",
                expected_revision=1,
                world_tick_end=15000,
                touched_entity_ids=[],
                audit=_make_audit_context(operation_id="bad-ps"),
            )

        assert meta_path.read_bytes() == meta_before
        assert events_path.read_bytes() == events_before

        active = repo.get_active_session()
        assert active is not None
        assert active.session.status == "active"

        records = _read_audit_records(vault_root)
        bad_recs = [r for r in records if r.get("operation_id") == "bad-ps"]
        assert len(bad_recs) == 0

    def test_existing_string_processing_status_replaced_with_pending(
        self, vault_root: Path, repo
    ) -> None:
        """Pre-existing string processing_status is accepted and replaced."""
        _create_active_session(vault_root, "S006", extras={"processing_status": "old_value"})
        result = repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="ps-replace"),
        )
        assert result.extra_fields.get("processing_status") == "pending"


# ── Strengthened after_hash audit regression ────────────────────────────────────


class TestExactCloseAuditHashStrengthened:
    """after_hash must be computed from the actual persisted metadata file."""

    def test_after_hash_from_exact_persisted_file(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"

        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-after-exact"),
        )

        # Compute expected hash from the actual persisted metadata file
        persisted_text = _read_exact_text(meta_path)
        expected_after = _content_hash(persisted_text)

        records = _read_audit_records(vault_root)
        audit_recs = [r for r in records if r.get("operation_id") == "audit-after-exact"]

        # Exactly two records: intent and committed
        intent_recs = [r for r in audit_recs if r.get("phase") == "intent"]
        committed_recs = [r for r in audit_recs if r.get("phase") == "committed"]
        assert len(intent_recs) == 1, f"Expected 1 intent, got {len(intent_recs)}"
        assert len(committed_recs) == 1, f"Expected 1 committed, got {len(committed_recs)}"

        for r in audit_recs:
            assert r["after_hash"] == expected_after, (
                f"phase={r.get('phase')}: expected {expected_after}, got {r['after_hash']}"
            )

    def test_before_hash_with_exact_phase_counts(self, vault_root: Path, repo) -> None:
        _create_active_session(vault_root, "S006")
        meta_path = vault_root / "_system" / "raw" / "sessions" / "S006" / "metadata.json"

        # Compute expected before_hash from the actual persisted metadata file
        before_text = _read_exact_text(meta_path)
        expected_before = _content_hash(before_text)

        repo.close_session(
            "S006",
            expected_revision=1,
            world_tick_end=15000,
            touched_entity_ids=[],
            audit=_make_audit_context(operation_id="audit-before-exact"),
        )

        records = _read_audit_records(vault_root)
        audit_recs = [r for r in records if r.get("operation_id") == "audit-before-exact"]

        # Exactly two records: intent and committed
        intent_recs = [r for r in audit_recs if r.get("phase") == "intent"]
        committed_recs = [r for r in audit_recs if r.get("phase") == "committed"]
        assert len(intent_recs) == 1, f"Expected 1 intent, got {len(intent_recs)}"
        assert len(committed_recs) == 1, f"Expected 1 committed, got {len(committed_recs)}"

        for r in audit_recs:
            assert r["before_hash"] == expected_before, (
                f"phase={r.get('phase')}: expected {expected_before}, got {r['before_hash']}"
            )
