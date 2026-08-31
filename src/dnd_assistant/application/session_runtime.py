"""Session runtime service — start and status lifecycle.

This module composes ``SessionMetadataRepository`` and
``WorldTimeRepository`` to provide the deterministic session lifecycle.

This module belongs to the application layer and must not import from:
    models, tools, ollama
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd_assistant.domain.session import Session
from dnd_assistant.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    from dnd_assistant.storage.audit import AuditContext
    from dnd_assistant.storage.types import (
        SessionMetadataRepository,
        WorldTimeRepository,
    )


class SessionRuntimeService:
    """Application service for session lifecycle operations.

    Composes ``SessionMetadataRepository`` and ``WorldTimeRepository``
    to provide deterministic start and status operations.

    Args:
        session_repo: The session metadata repository.
        world_time_repo: The world time repository.
    """

    def __init__(
        self,
        session_repo: SessionMetadataRepository,
        world_time_repo: WorldTimeRepository,
    ) -> None:
        self._session_repo = session_repo
        self._world_time_repo = world_time_repo

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
