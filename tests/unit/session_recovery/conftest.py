"""Shared fixtures and helpers for session recovery tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dnd_assistant.domain.session import Session
from dnd_assistant.storage.audit import AuditContext, AuditRecord, AuditService
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)

# ── Audit context factory ─────────────────────────────────────────────────────


def make_audit_context(
    *,
    operation_id: str = "rec-001",
    source: str = "test",
    session: str | None = None,
) -> AuditContext:
    """Build an AuditContext for recovery tests."""
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 31, 15, 0, 0, tzinfo=UTC),
        source=source,
        model_profile=None,
        prompt_version=None,
        session=session,
    )


# ── Session factory ──────────────────────────────────────────────────────────


def make_session(**overrides: object) -> Session:
    """Build a Session with defaults overridable by kwargs."""
    kwargs: dict[str, object] = {
        "id": "S006",
        "type": "session",
        "status": "active",
        "revision": 1,
        "real_started_at": "2026-08-31T14:00:00+00:00",
        "world_tick_start": 100,
    }
    kwargs.update(overrides)
    return Session.model_validate(kwargs)


# ── Vault fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    """Create a temporary Vault with canonical session runtime roots."""
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Sessions").mkdir()
    (root / "_system").mkdir()
    (root / "_system" / "raw").mkdir()
    (root / "_system" / "raw" / "sessions").mkdir()
    (root / "_system" / "audit").mkdir()
    return root


@pytest.fixture
def audit_svc(vault_root: Path) -> AuditService:
    """Create an AuditService backed by the temporary Vault."""
    log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(log_path=log_path)


@pytest.fixture
def recovery_repo(vault_root: Path, audit_svc: AuditService) -> ObsidianSessionRecoveryRepository:
    """Create an ObsidianSessionRecoveryRepository for the temporary Vault."""
    return ObsidianSessionRecoveryRepository(vault_root, audit_svc)


# ── Audit record builder ─────────────────────────────────────────────────────


def make_audit_record(
    ctx: AuditContext,
    *,
    operation: str = "test",
    entity_id: str | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    phase: str = "committed",
) -> AuditRecord:
    """Build an AuditRecord from an AuditContext."""
    return AuditRecord(
        operation_id=ctx.operation_id,
        real_time=ctx.real_time,
        operation=operation,
        entity_id=entity_id,
        before_hash=before_hash,
        after_hash=after_hash,
        source=ctx.source,
        session=ctx.session,
        model_profile=ctx.model_profile,
        prompt_version=ctx.prompt_version,
        phase=phase,
    )


# ── Audit record helpers ─────────────────────────────────────────────────────


def valid_audit_record_str(operation_id: str = "op1") -> str:
    """Return a single valid audit JSONL record WITHOUT trailing newline."""
    record = {
        "schema_version": 1,
        "operation_id": operation_id,
        "real_time": "2026-08-31T15:00:00+00:00",
        "operation": "test",
        "entity_id": None,
        "before_hash": None,
        "after_hash": None,
        "source": "test",
        "session": None,
        "model_profile": None,
        "prompt_version": None,
        "phase": "committed",
    }
    return json.dumps(record, ensure_ascii=False)


def valid_audit_line(operation_id: str = "op1") -> str:
    """Return a single valid audit JSONL record WITH trailing newline."""
    return valid_audit_record_str(operation_id) + "\n"


# ── Session start helper ─────────────────────────────────────────────────────


def start_session(
    vault_root: Path,
    session_id: str = "S006",
    status: str = "active",
    audit_svc: AuditService | None = None,
) -> None:
    """Create a started session with metadata and empty events file."""
    if audit_svc is None:
        log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_svc = AuditService(log_path=log_path)
    meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    session = make_session(id=session_id, status=status)
    meta_repo.create_session(
        session,
        audit=make_audit_context(operation_id="session-start-001"),
    )


# ── Valid event record helpers ───────────────────────────────────────────────


def valid_event_record_str(event_id: str = "evt_001") -> str:
    """Return a single valid event JSONL record WITHOUT trailing newline."""
    record = {
        "event_id": event_id,
        "real_time": "2026-08-31T15:01:00+00:00",
        "world_tick": 13800,
        "type": "note",
        "text": "ok",
    }
    return json.dumps(record, ensure_ascii=False)


def valid_event_line(event_id: str = "evt_001") -> str:
    """Return a single valid event JSONL record WITH trailing newline."""
    return valid_event_record_str(event_id) + "\n"
