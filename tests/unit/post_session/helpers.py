"""S11-01 post-session processing test helpers.

These are test-only helpers, not production code.  They intentionally avoid
pytest so they can be imported by both unit and integration test modules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dnd_assistant.domain.session import Session
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository

BASE_START = datetime(2026, 8, 31, 14, 0, 0, tzinfo=UTC)
BASE_END = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)


def make_session(session_id: str = "S001", status: str = "completed", **overrides: object):
    """Build a Session with deterministic defaults."""
    kwargs: dict[str, object] = {
        "id": session_id,
        "type": "session",
        "status": status,
        "revision": 1,
        "real_started_at": BASE_START,
        "world_tick_start": 100,
    }
    if status == "completed":
        kwargs["real_finished_at"] = BASE_END
        kwargs["world_tick_end"] = 200
    kwargs.update(overrides)
    return Session.model_validate(kwargs)


def make_audit_context(
    operation_id: str = "op-1",
    real_time: datetime = BASE_END,
    session: str | None = None,
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=real_time,
        source="test",
        session=session,
    )


def make_vault(tmp_path: Path) -> Path:
    """Create a temporary Vault with canonical session runtime roots."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Sessions").mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "raw").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


def make_audit_service(root: Path) -> AuditService:
    return AuditService(root / "_system" / "audit" / "audit.jsonl")


def create_completed_session(
    root: Path,
    audit_service: AuditService,
    session_id: str = "S001",
    touched: tuple[str, ...] = ("npc-a",),
) -> ObsidianSessionMetadataRepository:
    """Create an active session, then close it with the given touched entities."""
    repo = ObsidianSessionMetadataRepository(root, audit_service)
    repo.create_session(
        make_session(session_id=session_id, status="active"),
        audit=make_audit_context(operation_id=f"{session_id}-start", real_time=BASE_START),
    )
    repo.close_session(
        session_id,
        expected_revision=1,
        world_tick_end=200,
        touched_entity_ids=list(touched),
        audit=make_audit_context(operation_id=f"{session_id}-end", real_time=BASE_END),
    )
    return repo
