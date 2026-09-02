"""Concrete session read tools: get_active_session, get_session, list_sessions, list_session_events.

These tools expose existing deterministic Python session read behaviour
through the ToolRegistry/ToolExecutor contracts.  They are strictly read-only.

Dependency direction:
    domain, application.session_runtime, storage read protocols, errors,
    tools core contracts
    ↓
    this module

Must NOT depend on:
    models, Ollama, Fast Agent, CLI, post-session processor, ChangeSet,
    provider-specific schemas
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, JsonValue, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic.types import AwareDatetime

from dnd_assistant.domain.calendar import WorldTick
from dnd_assistant.domain.session import Session
from dnd_assistant.errors import StorageError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    ToolDefinition,
)

if TYPE_CHECKING:
    from dnd_assistant.application.session_runtime import SessionRuntimeService
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
    )


# ── Shared session-ID validation ─────────────────────────────────────────────


def _validate_session_id(value: str) -> str:
    """Validate a session identifier string.

    Requirements:
    - strict string
    - non-empty
    - no surrounding whitespace
    - printable Unicode allowed
    - control/non-printable characters rejected
    """
    if not isinstance(value, str):
        raise ValueError("session_id must be a string")
    if not value:
        raise ValueError("session_id must not be empty")
    if value.strip() != value:
        raise ValueError("session_id must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("session_id must not contain non-printable characters")
    return value


# ── get_active_session input/output ──────────────────────────────────────────


class GetActiveSessionInput(BaseModel):
    """Validated input for the ``get_active_session`` tool.

    No fields — empty input only.
    """

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class GetActiveSessionOutput(BaseModel):
    """Output for the ``get_active_session`` tool.

    ``session`` is ``None`` when no active session exists.
    """

    session: Session | None = None

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── get_session input/output ─────────────────────────────────────────────────


class GetSessionInput(BaseModel):
    """Validated input for the ``get_session`` tool.

    Accepts a stable session identifier string.
    """

    session_id: str

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    @field_validator("session_id")
    @classmethod
    def _validate_session_id_field(cls, value: str) -> str:
        return _validate_session_id(value)


class GetSessionOutput(BaseModel):
    """Output for the ``get_session`` tool.

    Exposes only the canonical ``Session`` fields.
    ``RawSessionMetadata.extra_fields`` is intentionally excluded.
    """

    session: Session

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── list_sessions input/output ───────────────────────────────────────────────


class ListSessionsInput(BaseModel):
    """Validated input for the ``list_sessions`` tool.

    No fields — empty input only.  No filters in S7-02.
    """

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class ListSessionsOutput(BaseModel):
    """Ordered list of canonical ``Session`` values.

    Preserves the repository's session-ID sorted order.
    ``RawSessionMetadata.extra_fields`` is intentionally excluded.
    """

    sessions: list[Session]

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── list_session_events input/output ─────────────────────────────────────────


class ListSessionEventsInput(BaseModel):
    """Validated input for the ``list_session_events`` tool.

    Accepts a stable session identifier string.
    """

    session_id: str

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    @field_validator("session_id")
    @classmethod
    def _validate_session_id_field(cls, value: str) -> str:
        return _validate_session_id(value)


class SessionEventResult(BaseModel):
    """Provider-neutral event DTO for the ``list_session_events`` tool.

    Preserves all canonical event fields plus event-specific extra_fields
    by value.  Unlike ``RawSessionMetadata.extra_fields``, event extras
    are actual event payload content and are necessary to preserve notes
    and event-specific data.
    """

    event_id: str
    real_time: AwareDatetime
    world_tick: WorldTick
    type: str
    extra_fields: dict[str, JsonValue]

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class ListSessionEventsOutput(BaseModel):
    """Ordered list of ``SessionEventResult`` values.

    Preserves the exact physical append order from the repository.
    """

    events: list[SessionEventResult]

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Tool definitions ─────────────────────────────────────────────────────────


_GET_ACTIVE_SESSION_DEFINITION = ToolDefinition(
    name="get_active_session",
    description="Return the currently active session, or None if no session is active",
    input_schema=GetActiveSessionInput,
    output_schema=GetActiveSessionOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_GET_SESSION_DEFINITION = ToolDefinition(
    name="get_session",
    description="Retrieve a single session's canonical metadata by its session ID",
    input_schema=GetSessionInput,
    output_schema=GetSessionOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_LIST_SESSIONS_DEFINITION = ToolDefinition(
    name="list_sessions",
    description="List all sessions in session-ID order",
    input_schema=ListSessionsInput,
    output_schema=ListSessionsOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)

_LIST_SESSION_EVENTS_DEFINITION = ToolDefinition(
    name="list_session_events",
    description="List all raw events for a session in physical append order",
    input_schema=ListSessionEventsInput,
    output_schema=ListSessionEventsOutput,
    permission=Permission.READ,
    side_effects=frozenset(),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}),
)


# ── Handlers ─────────────────────────────────────────────────────────────────


def _get_active_session_handler(
    input_model: GetActiveSessionInput,  # noqa: ARG001
    context: ExecutionContext,  # noqa: ARG001
    *,
    runtime_service: SessionRuntimeService,
) -> GetActiveSessionOutput:
    """Return the active session, or None if no session is active.

    ``ConflictError`` from multiple active sessions propagates unchanged.
    ``StorageError`` from storage corruption propagates unchanged.
    """
    session = runtime_service.get_active_session()
    return GetActiveSessionOutput(session=session)


def _get_session_handler(
    input_model: GetSessionInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    session_repository: SessionMetadataRepository,
) -> GetSessionOutput:
    """Retrieve a single session by its stable ID.

    Flow:
    1. Delegate to ``SessionMetadataRepository.get_session_metadata``.
    2. Fail-closed consistency check: metadata.session.id == requested_id.
    3. Return canonical ``Session`` (extra_fields intentionally excluded).
    """
    requested_id = input_model.session_id
    metadata = session_repository.get_session_metadata(requested_id)

    # Fail-closed consistency check
    if metadata.session.id != requested_id:
        raise StorageError("Session read consistency check failed")

    return GetSessionOutput(session=metadata.session)


def _list_sessions_handler(
    input_model: ListSessionsInput,  # noqa: ARG001
    context: ExecutionContext,  # noqa: ARG001
    *,
    session_repository: SessionMetadataRepository,
) -> ListSessionsOutput:
    """List all sessions in repository order.

    Preserves the repository's session-ID sorted order.
    ``RawSessionMetadata.extra_fields`` is intentionally excluded.
    """
    all_metadata = session_repository.list_session_metadata()
    sessions = [meta.session for meta in all_metadata]
    return ListSessionsOutput(sessions=sessions)


def _list_session_events_handler(
    input_model: ListSessionEventsInput,
    context: ExecutionContext,  # noqa: ARG001
    *,
    event_repository: SessionEventRepository,
) -> ListSessionEventsOutput:
    """List all raw events for a session in physical append order.

    Converts each ``RawSessionEvent`` to a provider-neutral
    ``SessionEventResult`` DTO, preserving event extra_fields by value.
    """
    requested_id = input_model.session_id
    raw_events = event_repository.list_events(requested_id)

    results: list[SessionEventResult] = []
    for ev in raw_events:
        # Convert extra_fields to JsonValue-compatible dict
        extra: dict[str, JsonValue] = {}
        for k, v in ev.extra_fields.items():
            extra[k] = v  # type: ignore[assignment]

        results.append(
            SessionEventResult(
                event_id=ev.event_id,
                real_time=ev.real_time,
                world_tick=ev.world_tick,
                type=ev.type,
                extra_fields=extra,
            )
        )

    return ListSessionEventsOutput(events=results)


# ── Registration API ─────────────────────────────────────────────────────────


def register_session_read_tools(
    registry: ToolRegistry,
    *,
    runtime_service: SessionRuntimeService,
    session_repository: SessionMetadataRepository,
    event_repository: SessionEventRepository,
) -> None:
    """Register session read tools on a ``ToolRegistry``.

    Registers exactly ``get_active_session``, ``get_session``,
    ``list_sessions``, and ``list_session_events`` with their
    definitions and wired handlers.

    Args:
        registry: A ``ToolRegistry`` instance.
        runtime_service: A ``SessionRuntimeService`` implementation.
        session_repository: A ``SessionMetadataRepository`` implementation.
        event_repository: A ``SessionEventRepository`` implementation.

    Raises:
        ValidationError: The registry is not a ToolRegistry.
        ConflictError: A tool with the same name is already registered.
    """
    if not isinstance(registry, ToolRegistry):
        raise ValidationError("registry must be a ToolRegistry instance")

    def _make_get_active_handler(
        input_model: GetActiveSessionInput,
        context: ExecutionContext,
    ) -> GetActiveSessionOutput:
        return _get_active_session_handler(input_model, context, runtime_service=runtime_service)

    def _make_get_handler(
        input_model: GetSessionInput,
        context: ExecutionContext,
    ) -> GetSessionOutput:
        return _get_session_handler(input_model, context, session_repository=session_repository)

    def _make_list_handler(
        input_model: ListSessionsInput,
        context: ExecutionContext,
    ) -> ListSessionsOutput:
        return _list_sessions_handler(input_model, context, session_repository=session_repository)

    def _make_list_events_handler(
        input_model: ListSessionEventsInput,
        context: ExecutionContext,
    ) -> ListSessionEventsOutput:
        return _list_session_events_handler(input_model, context, event_repository=event_repository)

    registry.register(_GET_ACTIVE_SESSION_DEFINITION, _make_get_active_handler)
    registry.register(_GET_SESSION_DEFINITION, _make_get_handler)
    registry.register(_LIST_SESSIONS_DEFINITION, _make_list_handler)
    registry.register(_LIST_SESSION_EVENTS_DEFINITION, _make_list_events_handler)
