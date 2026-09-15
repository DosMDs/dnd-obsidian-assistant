"""S11-01 deterministic, model-free eligibility tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dnd_assistant.application.post_session_eligibility import (
    EligibilityReason,
    evaluate_processing_eligibility,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
)
from dnd_assistant.storage.session_paths import resolve_session_storage_paths
from tests.unit.post_session.helpers import (
    BASE_START,
    create_completed_session,
    make_audit_context,
    make_session,
)


def _event_repo(vault_root: Path, audit_service: AuditService) -> ObsidianSessionEventRepository:
    return ObsidianSessionEventRepository(vault_root, audit_service)


def _evaluate(
    vault_root: Path,
    audit_service: AuditService,
    session_id: str = "S001",
    *,
    metadata_repo: Any | None = None,
    attempt_id: str | None = None,
):
    store = ObsidianPostSessionProcessingStore(vault_root)
    repo = (
        metadata_repo
        if metadata_repo is not None
        else ObsidianSessionMetadataRepository(vault_root, audit_service)
    )
    return evaluate_processing_eligibility(
        repo,
        _event_repo(vault_root, audit_service),
        store,
        session_id,
        attempt_id=attempt_id,
    )


def _write_raw_session(vault_root: Path, session: Session, extras: dict[str, Any]) -> None:
    paths = resolve_session_storage_paths(vault_root, session.id)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    data = session.model_dump(mode="json")
    data.update(extras)
    (paths.raw_dir / "metadata.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (paths.raw_dir / "events.jsonl").write_text("", encoding="utf-8")


# ── Happy path ────────────────────────────────────────────────────────────


def test_completed_valid_session_accepted(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service, touched=("npc-a", "loc-b"))
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is True
    assert result.reason is EligibilityReason.ELIGIBLE
    assert result.touched_entity_ids == ("npc-a", "loc-b")


def test_eligible_result_binds_observed_session_revision(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is True
    # close_session increments the active-session revision 1 -> 2.
    assert result.session_revision == 2


def test_ineligible_result_has_no_session_revision(vault_root, audit_service) -> None:
    result = _evaluate(vault_root, audit_service, "S999")
    assert result.eligible is False
    assert result.session_revision is None


def test_active_session_rejected(vault_root, audit_service) -> None:
    repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
    repo.create_session(
        make_session(status="active"),
        audit=make_audit_context(operation_id="start"),
    )
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.SESSION_NOT_COMPLETED


# ── Metadata failures ─────────────────────────────────────────────────────


def test_missing_session_rejected(vault_root, audit_service) -> None:
    result = _evaluate(vault_root, audit_service, "S999")
    assert result.eligible is False
    assert result.reason is EligibilityReason.SESSION_NOT_FOUND


def test_corrupt_metadata_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    paths = resolve_session_storage_paths(vault_root, "S001")
    paths.raw_metadata.write_text("{not json}\n", encoding="utf-8")
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.SESSION_MALFORMED


def test_missing_finish_time_rejected(vault_root, audit_service) -> None:
    session = make_session(
        status="completed",
        real_finished_at=None,
    )
    # Session schema permits None; ordering checks must not run before presence.
    _write_raw_session(vault_root, session, {})
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.MISSING_FINISH_TIME


def test_missing_end_tick_rejected(vault_root, audit_service) -> None:
    session = make_session(status="completed", world_tick_end=None)
    _write_raw_session(vault_root, session, {})
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.MISSING_END_TICK


def test_invalid_tick_order_rejected(vault_root, audit_service) -> None:
    session = make_session(status="completed", world_tick_end=50, world_tick_start=100)
    _write_raw_session(vault_root, session, {})
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.INVALID_TICK_ORDER


def test_invalid_real_time_order_rejected(vault_root, audit_service) -> None:
    session = make_session(
        status="completed",
        real_finished_at=datetime(2026, 8, 31, 13, 0, 0, tzinfo=UTC),
    )
    _write_raw_session(vault_root, session, {})
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.INVALID_REAL_TIME_ORDER


# ── Events failures ───────────────────────────────────────────────────────


def test_missing_events_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    paths = resolve_session_storage_paths(vault_root, "S001")
    paths.raw_events.unlink()
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.EVENTS_MALFORMED


def test_corrupt_events_rejected(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service)
    paths = resolve_session_storage_paths(vault_root, "S001")
    paths.raw_events.write_text("{not json}\n", encoding="utf-8")
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.EVENTS_MALFORMED


# ── Active-session contradictions ─────────────────────────────────────────


def test_multiple_active_sessions_contradiction(vault_root, audit_service) -> None:
    repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
    create_completed_session(vault_root, audit_service, session_id="S001")
    repo.create_session(
        make_session(session_id="S002", status="active"),
        audit=make_audit_context(operation_id="start-2"),
    )
    repo.create_session(
        make_session(session_id="S003", status="active"),
        audit=make_audit_context(operation_id="start-3"),
    )
    result = _evaluate(vault_root, audit_service, "S001")
    assert result.eligible is False
    assert result.reason is EligibilityReason.ACTIVE_SESSION_CONTRADICTION


def test_self_reported_active_contradiction(vault_root, audit_service) -> None:
    create_completed_session(vault_root, audit_service, session_id="S001")

    class SelfActiveRepo:
        def __init__(self, inner: ObsidianSessionMetadataRepository) -> None:
            self._inner = inner

        def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
            return self._inner.get_session_metadata(session_id)

        def get_active_session(self) -> RawSessionMetadata:
            return self._inner.get_session_metadata("S001")

    result = _evaluate(
        vault_root,
        audit_service,
        "S001",
        metadata_repo=SelfActiveRepo(ObsidianSessionMetadataRepository(vault_root, audit_service)),
    )
    assert result.eligible is False
    assert result.reason is EligibilityReason.ACTIVE_SESSION_CONTRADICTION


# ── Touched entities / legacy fields ──────────────────────────────────────


def test_malformed_touched_entities_rejected(vault_root, audit_service) -> None:
    session = make_session(status="completed")
    _write_raw_session(vault_root, session, {"touched_entities": "npc-a"})
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.INVALID_TOUCHED_ENTITIES


def test_touched_entities_non_string_item_rejected(vault_root, audit_service) -> None:
    session = make_session(status="completed")
    _write_raw_session(vault_root, session, {"touched_entities": ["npc-a", 5]})
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is False
    assert result.reason is EligibilityReason.INVALID_TOUCHED_ENTITIES


def test_legacy_processed_fields_do_not_affect_eligibility(vault_root, audit_service) -> None:
    session = make_session(
        status="completed",
        processed=True,
        processed_model_profile="post_session",
    )
    _write_raw_session(
        vault_root,
        session,
        {"touched_entities": ["npc-a"], "processing_status": "whatever"},
    )
    result = _evaluate(vault_root, audit_service)
    assert result.eligible is True
    assert result.reason is EligibilityReason.ELIGIBLE


# ── Zero-write on failure ─────────────────────────────────────────────────


def test_failure_performs_zero_ledger_or_model_writes(vault_root, audit_service) -> None:
    repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
    repo.create_session(
        make_session(status="active"),
        audit=make_audit_context(operation_id="start"),
    )
    audit_log = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_before = AuditService(audit_log).read_all()

    store = ObsidianPostSessionProcessingStore(vault_root)
    result = evaluate_processing_eligibility(
        repo, _event_repo(vault_root, audit_service), store, "S001"
    )
    assert result.eligible is False

    assert store.read_ledger_if_present("S001") is None
    processing = vault_root / "_system" / "raw" / "sessions" / "S001" / "processing"
    assert not processing.exists()
    assert AuditService(audit_log).read_all() == audit_before


# ── Attempt-terminal rule ─────────────────────────────────────────────────


def test_terminal_attempt_is_ineligible(vault_root, audit_service) -> None:
    from dnd_assistant.application.post_session_ledger import record_ledger_event
    from dnd_assistant.domain.post_session import AttemptFailed, FailureCategory, ProcessingPhase

    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    attempt_id = "att_" + "a" * 32
    record_ledger_event(
        store,
        "S001",
        AttemptFailed(
            event_id="le_" + "a" * 32,
            attempt_id=attempt_id,
            session_ref="S001",
            real_time=BASE_START,
            phase=ProcessingPhase.EXTRACTION,
            failure_category=FailureCategory.MODEL_TIMEOUT,
            message="timeout",
        ),
    )
    result = _evaluate(vault_root, audit_service, "S001", attempt_id=attempt_id)
    assert result.eligible is False
    assert result.reason is EligibilityReason.ATTEMPT_ALREADY_TERMINAL


def test_non_terminal_attempt_is_eligible(vault_root, audit_service) -> None:
    from dnd_assistant.application.post_session_ledger import record_ledger_event
    from dnd_assistant.domain.post_session import AttemptStarted, Sha256Fingerprint

    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    attempt_id = "att_" + "b" * 32
    record_ledger_event(
        store,
        "S001",
        AttemptStarted(
            event_id="le_" + "b" * 32,
            attempt_id=attempt_id,
            session_ref="S001",
            real_time=BASE_START,
            input_fingerprint=Sha256Fingerprint(digest="c" * 64),
            processor_version="1",
            prompt_version="1",
        ),
    )
    result = _evaluate(vault_root, audit_service, "S001", attempt_id=attempt_id)
    assert result.eligible is True


def test_corrupt_ledger_raises_storage_error(vault_root, audit_service) -> None:
    import pytest

    from dnd_assistant.errors import StorageError

    create_completed_session(vault_root, audit_service)
    store = ObsidianPostSessionProcessingStore(vault_root)
    store.append_ledger_line("S001", "{not json}\n")
    with pytest.raises(StorageError):
        evaluate_processing_eligibility(
            ObsidianSessionMetadataRepository(vault_root, audit_service),
            _event_repo(vault_root, audit_service),
            store,
            "S001",
            attempt_id="att_" + "a" * 32,
        )
