"""S11-01 end-to-end/restart integration tests for the processing ledger.

These tests exercise a real temporary Vault, real repositories and a real
append-only ledger on disk.  They prove that the durable foundational evidence
survives a fresh repository instance and that no Summary/Recap/ChangeSet/entity
mutation is introduced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dnd_assistant.application.post_session_eligibility import (
    EligibilityReason,
    evaluate_processing_eligibility,
)
from dnd_assistant.application.post_session_identity import (
    compute_input_fingerprint,
    new_attempt_id,
)
from dnd_assistant.application.post_session_ledger import (
    LedgerAppendOutcome,
    attempt_has_terminal_event,
    load_ledger_events,
    new_ledger_event_id,
    record_ledger_event,
)
from dnd_assistant.domain.post_session import (
    AttemptStarted,
    PreparedCalendarProjection,
    PreparedEntityProjection,
    PreparedInputIdentity,
    PreparedSessionProjection,
)
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from tests.unit.post_session.helpers import (
    BASE_START,
    create_completed_session,
    make_vault,
)

_START = datetime(2026, 8, 31, 14, 0, 0, tzinfo=UTC)
_END = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)


def _identity() -> PreparedInputIdentity:
    return PreparedInputIdentity(
        processor_version="1",
        prompt_version="1",
        session=PreparedSessionProjection(
            id="S001",
            status="completed",
            real_started_at=_START,
            real_finished_at=_END,
            world_tick_start=100,
            world_tick_end=200,
            revision=2,
            touched_entities=("npc-a",),
        ),
        entities=(
            PreparedEntityProjection(
                id="npc-a",
                type=EntityType.NPC,
                revision=3,
                name="Aria",
                status="alive",
                visibility=Visibility.PLAYER,
                knowledge_status=KnowledgeStatus.CONFIRMED,
            ),
        ),
        calendar=PreparedCalendarProjection(world_tick_start=100, world_tick_end=200),
    )


def _snapshot(root: Path) -> set[str]:
    return {str(p.relative_to(root).as_posix()) for p in root.rglob("*") if p.is_file()}


def test_completed_session_ledger_restart_and_no_canonical_mutation(tmp_path: Path) -> None:
    root = make_vault(tmp_path)
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    create_completed_session(root, audit)

    metadata_repo = ObsidianSessionMetadataRepository(root, audit)
    event_repo = ObsidianSessionEventRepository(root, audit)
    store = ObsidianPostSessionProcessingStore(root)

    fingerprint = compute_input_fingerprint(_identity())
    attempt_id = new_attempt_id()

    before_files = _snapshot(root)

    # 39. Completed valid session passes eligibility.
    result = evaluate_processing_eligibility(
        metadata_repo, event_repo, store, "S001", attempt_id=attempt_id
    )
    assert result.eligible is True
    assert result.reason is EligibilityReason.ELIGIBLE

    # 40. Trusted attempt-start event persists.
    event = AttemptStarted(
        event_id=new_ledger_event_id(),
        attempt_id=attempt_id,
        session_ref="S001",
        real_time=BASE_START,
        input_fingerprint=fingerprint,
        processor_version="1",
        prompt_version="1",
        model_profile="post_session",
    )
    append = record_ledger_event(store, "S001", event)
    assert append.outcome is LedgerAppendOutcome.CREATED

    # 41. A fresh repository/store instance reconstructs exact evidence.
    fresh_store = ObsidianPostSessionProcessingStore(root)
    fresh_events = load_ledger_events(fresh_store, "S001")
    assert fresh_events == (event,)
    (loaded,) = fresh_events
    assert isinstance(loaded, AttemptStarted)
    assert loaded.attempt_id == attempt_id
    assert loaded.input_fingerprint == fingerprint
    assert attempt_has_terminal_event(fresh_events, attempt_id) is False

    # Idempotent retry after restart is a no-op.
    retry = record_ledger_event(fresh_store, "S001", event)
    assert retry.outcome is LedgerAppendOutcome.ALREADY_PRESENT

    # 42. No Summary/Recap/ChangeSet/entity canonical mutation occurred.
    after_files = _snapshot(root)
    new_files = after_files - before_files
    assert new_files == {"_system/raw/sessions/S001/processing/ledger.jsonl"}
    assert not (root / "Sessions" / "S001" / "Summary.md").exists()
    assert not (root / "Sessions" / "S001" / "Recap.md").exists()
    assert not (root / "_system" / "changesets").exists()

    # Ledger writes add no audit records beyond the session start/end records.
    assert all(record.session == "S001" for record in audit.read_all())
    assert {record.operation for record in audit.read_all()} == {"session.start", "session.end"}
