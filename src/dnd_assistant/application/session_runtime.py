"""Session runtime service — start, status, and event recording lifecycle.

This module composes ``SessionMetadataRepository``,
``WorldTimeRepository``, and ``SessionEventRepository`` to provide the
deterministic session lifecycle.

This module belongs to the application layer and must not import from:
    models, tools, ollama
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditContext
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
        WorldTimeRepository,
    )


class SessionRuntimeService:
    """Application service for session lifecycle operations.

    Composes ``SessionMetadataRepository``, ``WorldTimeRepository``, and
    ``SessionEventRepository`` to provide deterministic start, status, and
    event recording operations.

    Args:
        session_repo: The session metadata repository.
        world_time_repo: The world time repository.
        event_repo: The session event repository.
    """

    def __init__(
        self,
        session_repo: SessionMetadataRepository,
        world_time_repo: WorldTimeRepository,
        event_repo: SessionEventRepository,
    ) -> None:
        self._session_repo = session_repo
        self._world_time_repo = world_time_repo
        self._event_repo = event_repo

    def start_session(
        self,
        *,
        audit: AuditContext,
    ) -> Session:
        """Start a new session.

        Lifecycle:
        1. Check no active session exists.
        2. Read canonical current world time.
        3. Allocate next session ID.
        4. Construct canonical Session with status="active".
        5. Persist through SessionMetadataRepository.
        6. Return the persisted Session.

        Args:
            audit: Audit context for this operation.
                ``audit.real_time`` is the session start timestamp.

        Returns:
            The persisted ``Session``.

        Raises:
            ConflictError: An active session already exists.
            NotFoundError: World time has not been initialized.
            StorageError: A storage operation failed.
        """
        # 1. Check for existing active session
        existing_active = self._session_repo.get_active_session()
        if existing_active is not None:
            raise ConflictError(
                f"Cannot start a new session while session "
                f"{existing_active.session.id} is still active"
            )

        # 2. Read canonical current world time
        try:
            world_time = self._world_time_repo.get_current_world_time()
        except NotFoundError:
            raise NotFoundError(
                "Cannot start a session: current world time has not been initialized. "
                "Use the world-time initialization command first."
            ) from None

        # 3. Allocate next session ID
        session_id = self._session_repo.allocate_next_session_id()

        # 4. Construct canonical Session
        session = Session(
            id=session_id,
            type="session",
            status="active",
            real_started_at=audit.real_time,
            real_finished_at=None,
            world_tick_start=world_time.current_world_tick,
            world_tick_end=None,
            processed=False,
            processed_model_profile=None,
            revision=1,
        )

        # 5. Persist through repository
        persisted = self._session_repo.create_session(session, audit=audit)

        # 6. Return the persisted Session
        return persisted.session

    def get_active_session(self) -> Session | None:
        """Return the active session, if exactly one exists.

        Returns:
            The active ``Session``, or ``None`` if no active session exists.

        Raises:
            ConflictError: More than one active session exists.
            StorageError: A storage operation failed.
        """
        active = self._session_repo.get_active_session()
        if active is None:
            return None
        return active.session

    # ── Event recording ───────────────────────────────────────────────────

    def record_event(
        self,
        event_type: str,
        *,
        extra_fields: Mapping[str, object] | None = None,
        audit: AuditContext,
    ) -> RawSessionEvent:
        """Record a generic raw event into the active session.

        Lifecycle:
        1. Read active session (exactly one required).
        2. Read canonical current world time.
        3. Delegate append to ``SessionEventRepository``.

        Args:
            event_type: The event type string (e.g. ``"item_acquired"``).
            extra_fields: Event-specific top-level fields.
            audit: Audit context for this operation.

        Returns:
            The persisted ``RawSessionEvent``.

        Raises:
            NotFoundError: No active session exists, or world time has
                not been initialized.
            ConflictError: More than one active session exists.
            StorageError: A storage operation failed.
        """
        # 1. Read active session (exactly one required)
        active = self._session_repo.get_active_session()
        if active is None:
            raise NotFoundError("Cannot record event: no active session. Start a session first.")

        # 2. Read canonical current world time
        try:
            world_time = self._world_time_repo.get_current_world_time()
        except NotFoundError:
            raise NotFoundError(
                "Cannot record event: current world time has not been "
                "initialized. Use the world-time initialization command first."
            ) from None

        # 3. Delegate append to repository
        return self._event_repo.append_event(
            session_id=active.session.id,
            event_type=event_type,
            real_time=audit.real_time,
            world_tick=world_time.current_world_tick,
            extra_fields=dict(extra_fields) if extra_fields else None,
            audit=audit,
        )

    def record_note(
        self,
        text: str,
        *,
        audit: AuditContext,
    ) -> RawSessionEvent:
        """Record a note into the active session.

        This is deterministic sugar for ``record_event("note", ...)``
        with ``extra_fields={"text": text}``.

        Args:
            text: The note text.  Must be non-empty, printable, with no
                leading/trailing whitespace or control characters.
            audit: Audit context for this operation.

        Returns:
            The persisted ``RawSessionEvent``.

        Raises:
            ValidationError: The note text is invalid.
            NotFoundError: No active session exists, or world time has
                not been initialized.
            ConflictError: More than one active session exists.
            StorageError: A storage operation failed.
        """
        # Validate note text
        if not isinstance(text, str):
            raise ValidationError("Note text must be a string")
        if not text:
            raise ValidationError("Note text must not be empty")
        if text.strip() != text:
            raise ValidationError("Note text must not have leading or trailing whitespace")
        if not text.isprintable():
            raise ValidationError("Note text must not contain non-printable characters")

        return self.record_event(
            "note",
            extra_fields={"text": text},
            audit=audit,
        )
