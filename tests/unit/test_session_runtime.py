"""Unit tests for S6-02 SessionRuntimeService.

Tests cover:
- start_session lifecycle
- get_active_session lifecycle
- ConflictError when already active
- NotFoundError when world time missing
- World time not mutated during start
- No in-memory authoritative active session
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import ConflictError, NotFoundError
from dnd_assistant.storage.audit import AuditContext

# ── Fakes / stubs ──────────────────────────────────────────────────────────────


class FakeSessionMetadataRepo:
    """Fake implementation of SessionMetadataRepository for testing.

    Stores RawSessionMetadata-like objects in memory.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _FakeMetadata] = {}
        self._next_id: str | None = None

    def set_next_id(self, session_id: str) -> None:
        self._next_id = session_id

    def allocate_next_session_id(self) -> str:
        if self._next_id is not None:
            return self._next_id
        # Simple auto-allocator for tests
        n = len(self._sessions) + 1
        return f"S{n:03d}"

    def create_session(
        self,
        session: Session,
        *,
        audit: AuditContext,
    ) -> _FakeMetadata:
        if session.id in self._sessions:
            raise ConflictError(f"Session {session.id} already exists")
        meta = _FakeMetadata(session=session)
        self._sessions[session.id] = meta
        return meta

    def get_active_session(self) -> _FakeMetadata | None:
        active = [m for m in self._sessions.values() if m.session.status == "active"]
        if len(active) == 0:
            return None
        if len(active) == 1:
            return active[0]
        raise ConflictError(f"Multiple active sessions: {[m.session.id for m in active]}")

    def get_session_metadata(self, session_id: str) -> _FakeMetadata:
        if session_id not in self._sessions:
            raise NotFoundError(f"Session {session_id} not found")
        return self._sessions[session_id]


class _FakeMetadata:
    """Minimal stand-in for RawSessionMetadata."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session


class FakeWorldTimeRepo:
    """Fake implementation of WorldTimeRepository for testing."""

    def __init__(self, tick: int | None = 13800) -> None:
        self._tick = tick

    def get_current_world_time(self) -> CurrentWorldTime:
        if self._tick is None:
            raise NotFoundError("World time not initialized")
        return CurrentWorldTime(current_world_tick=self._tick, revision=1)


def _make_audit_context(
    operation_id: str = "test-op-001",
    source: str = "test",
) -> AuditContext:
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 31, 15, 0, 0, tzinfo=UTC),
        source=source,
    )


# ── Start session ──────────────────────────────────────────────────────────────


class TestStartSession:
    def test_start_with_no_sessions_returns_first_id(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.id == "S001"
        assert session.status == "active"

    def test_start_after_s005_returns_s006(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        session_repo.set_next_id("S006")
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.id == "S006"

    def test_real_started_at_matches_audit_time(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        audit_time = datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC)
        ctx = AuditContext(
            operation_id="test-001",
            real_time=audit_time,
            source="test",
        )
        session = service.start_session(audit=ctx)
        assert session.real_started_at == audit_time

    def test_world_tick_start_comes_from_world_time_repo(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=99999)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.world_tick_start == 99999

    def test_status_is_active(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.status == "active"

    def test_real_finished_at_is_none(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.real_finished_at is None

    def test_world_tick_end_is_none(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.world_tick_end is None

    def test_processed_is_false(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.processed is False

    def test_processed_model_profile_is_none(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.processed_model_profile is None

    def test_revision_is_one(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        session = service.start_session(audit=_make_audit_context())
        assert session.revision == 1


# ── Get active session ─────────────────────────────────────────────────────────


class TestGetActiveSession:
    def test_none_when_no_session(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        assert service.get_active_session() is None

    def test_returns_same_session_after_start(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        started = service.start_session(audit=_make_audit_context())
        active = service.get_active_session()
        assert active is not None
        assert active.id == started.id
        assert active.status == "active"

    def test_multiple_active_raises_conflict(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        service.start_session(audit=_make_audit_context(operation_id="first"))
        # Manually inject a second active session into the fake repo
        session_repo._sessions["S002"] = _FakeMetadata(
            Session(
                id="S002",
                type="session",
                status="active",
                real_started_at=datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC),
                world_tick_start=14000,
                revision=1,
            )
        )
        with pytest.raises(ConflictError):
            service.get_active_session()


# ── Second start while active ──────────────────────────────────────────────────


class TestSecondStartWhileActive:
    def test_raises_conflict(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        service.start_session(audit=_make_audit_context(operation_id="first"))
        with pytest.raises(ConflictError, match="active"):
            service.start_session(audit=_make_audit_context(operation_id="second"))


# ── World time missing ─────────────────────────────────────────────────────────


class TestWorldTimeMissing:
    def test_raises_not_found(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=None)  # not initialized
        service = SessionRuntimeService(session_repo, world_repo)
        with pytest.raises(NotFoundError, match="world time"):
            service.start_session(audit=_make_audit_context())


# ── World time not mutated by start ────────────────────────────────────────────


class TestWorldTimeNotMutated:
    def test_start_does_not_change_world_time(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        before = world_repo.get_current_world_time()
        service.start_session(audit=_make_audit_context())
        after = world_repo.get_current_world_time()
        assert before.current_world_tick == after.current_world_tick
        assert before.revision == after.revision


# ── No in-memory authoritative active session ─────────────────────────────────


class TestNoInMemoryActiveSession:
    def test_get_active_session_reads_from_repo(self) -> None:
        session_repo = FakeSessionMetadataRepo()
        world_repo = FakeWorldTimeRepo(tick=13800)
        service = SessionRuntimeService(session_repo, world_repo)
        # Start a session
        service.start_session(audit=_make_audit_context(operation_id="first"))
        # Manually change the repo state (simulating external mutation)
        session_repo._sessions["S001"] = _FakeMetadata(
            Session(
                id="S001",
                type="session",
                status="completed",  # changed externally
                real_started_at=datetime(2026, 8, 31, 15, 0, 0, tzinfo=UTC),
                world_tick_start=13800,
                revision=1,
            )
        )
        # Service must reflect the repo state, not an in-memory cache
        assert service.get_active_session() is None
