"""Concrete session mutation tools: start_session, record_event, record_note, end_session.

These tools expose existing deterministic Python session mutation behaviour
through the ToolRegistry/ToolExecutor contracts.  Every mutation performs a
read-only recovery preflight before delegating to SessionRuntimeService.

Dependency direction:
    domain, application.session_runtime, application.session_recovery,
    errors, tools core contracts
    ↓
    this module

Must NOT depend on:
    models, Ollama, Fast Agent, CLI, post-session processor, ChangeSet,
    provider-specific schemas, retrieval, storage repositories directly
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, JsonValue, field_validator
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import ConflictError, ValidationError
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_reads import SessionEventResult
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
)

if TYPE_CHECKING:
    from dnd_assistant.application.session_recovery import SessionRecoveryService
    from dnd_assistant.application.session_runtime import SessionRuntimeService


# ── Shared string validation ────────────────────────────────────────────────


def _validate_strict_string(value: str, field_name: str) -> str:
    """Validate a strict string field.

    Requirements:
    - strict string
    - non-empty
    - no leading/trailing whitespace
    - printable (no control characters)
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError(f"{field_name} must not contain non-printable characters")
    return value


# ── Recovery preflight helper ────────────────────────────────────────────────


def _check_recovery_preflight(
    recovery_service: SessionRecoveryService,
) -> None:
    """Perform a read-only recovery preflight before mutation.

    If recovery issues exist, the mutation is blocked with a generic
    ConflictError.  No recovery issue details are exposed.

    Args:
        recovery_service: The recovery service to inspect.

    Raises:
        ConflictError: Recovery issues exist; mutation is blocked.
        DndAssistantError: Propagated unchanged from inspect_runtime().
    """
    report = recovery_service.inspect_runtime()
    if report.has_issues:
        raise ConflictError("Session runtime requires explicit recovery before mutation")


# ── start_session input/output ───────────────────────────────────────────────


class StartSessionInput(BaseModel):
    """Validated input for the ``start_session`` tool.

    No fields — the runtime owns session ID allocation, world tick,
    and timestamp generation.
    """

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class StartSessionOutput(BaseModel):
    """Output for the ``start_session`` tool.

    Returns the canonical ``Session`` as persisted by the runtime.
    """

    session: Session

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── record_event input/output ────────────────────────────────────────────────


class RecordEventInput(BaseModel):
    """Validated input for the ``record_event`` tool.

    ``event_type`` is a strict string — no closed enum.
    ``extra_fields`` is an optional JSON-compatible payload dict.
    """

    event_type: str
    extra_fields: dict[str, JsonValue] | None = None

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        return _validate_strict_string(value, "event_type")


class RecordEventOutput(BaseModel):
    """Output for the ``record_event`` tool.

    Returns a provider-neutral ``SessionEventResult`` DTO.
    """

    event: SessionEventResult

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── record_note input/output ─────────────────────────────────────────────────


class RecordNoteInput(BaseModel):
    """Validated input for the ``record_note`` tool.

    ``text`` is a strict non-empty printable string.
    """

    text: str

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _validate_strict_string(value, "text")


class RecordNoteOutput(BaseModel):
    """Output for the ``record_note`` tool.

    Returns a provider-neutral ``SessionEventResult`` DTO with
    ``type == "note"`` and ``extra_fields["text"]``.
    """

    event: SessionEventResult

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── end_session input/output ─────────────────────────────────────────────────


class EndSessionInput(BaseModel):
    """Validated input for the ``end_session`` tool.

    ``touched_entity_ids`` is an optional list of stable EntityId values.
    Caller order is preserved; deduplication is owned by the lower layer.
    """

    touched_entity_ids: list[EntityId] = []

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


class EndSessionOutput(BaseModel):
    """Output for the ``end_session`` tool.

    Returns the canonical completed ``Session`` as persisted by the runtime.
    """

    session: Session

    model_config = {"extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Tool definitions ─────────────────────────────────────────────────────────


_START_SESSION_DEFINITION = ToolDefinition(
    name="start_session",
    description="Start a new game session. Requires no active session.",
    input_schema=StartSessionInput,
    output_schema=StartSessionOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.SESSION_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.NO_ACTIVE_SESSION}),
)

_RECORD_EVENT_DEFINITION = ToolDefinition(
    name="record_event",
    description="Record a generic event into the active session",
    input_schema=RecordEventInput,
    output_schema=RecordEventOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.SESSION_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)

_RECORD_NOTE_DEFINITION = ToolDefinition(
    name="record_note",
    description="Record a note into the active session",
    input_schema=RecordNoteInput,
    output_schema=RecordNoteOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.SESSION_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)

_END_SESSION_DEFINITION = ToolDefinition(
    name="end_session",
    description="End the currently active game session",
    input_schema=EndSessionInput,
    output_schema=EndSessionOutput,
    permission=Permission.WRITE,
    side_effects=frozenset({SideEffect.SESSION_MUTATION}),
    allowed_session_modes=frozenset({SessionMode.ACTIVE_SESSION}),
)


# ── Handlers ─────────────────────────────────────────────────────────────────


def _start_session_handler(
    input_model: StartSessionInput,  # noqa: ARG001
    context: ExecutionContext,
    *,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
) -> StartSessionOutput:
    """Start a new session after recovery preflight.

    Flow:
    1. Recovery preflight (read-only).
    2. Delegate to SessionRuntimeService.start_session.
    3. Return the persisted Session.
    """
    _check_recovery_preflight(recovery_service)
    session = runtime_service.start_session(audit=context.audit)
    return StartSessionOutput(session=session)


def _record_event_handler(
    input_model: RecordEventInput,
    context: ExecutionContext,
    *,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
) -> RecordEventOutput:
    """Record a generic event after recovery preflight.

    Flow:
    1. Recovery preflight (read-only).
    2. Delegate to SessionRuntimeService.record_event.
    3. Convert RawSessionEvent to SessionEventResult.
    """
    _check_recovery_preflight(recovery_service)
    raw_event = runtime_service.record_event(
        input_model.event_type,
        extra_fields=input_model.extra_fields,
        audit=context.audit,
    )
    event_result = SessionEventResult(
        event_id=raw_event.event_id,
        real_time=raw_event.real_time,
        world_tick=raw_event.world_tick,
        type=raw_event.type,
        extra_fields=dict(raw_event.extra_fields) if raw_event.extra_fields else {},
    )
    return RecordEventOutput(event=event_result)


def _record_note_handler(
    input_model: RecordNoteInput,
    context: ExecutionContext,
    *,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
) -> RecordNoteOutput:
    """Record a note after recovery preflight.

    Flow:
    1. Recovery preflight (read-only).
    2. Delegate to SessionRuntimeService.record_note.
    3. Convert RawSessionEvent to SessionEventResult.
    """
    _check_recovery_preflight(recovery_service)
    raw_event = runtime_service.record_note(
        input_model.text,
        audit=context.audit,
    )
    event_result = SessionEventResult(
        event_id=raw_event.event_id,
        real_time=raw_event.real_time,
        world_tick=raw_event.world_tick,
        type=raw_event.type,
        extra_fields=dict(raw_event.extra_fields) if raw_event.extra_fields else {},
    )
    return RecordNoteOutput(event=event_result)


def _end_session_handler(
    input_model: EndSessionInput,
    context: ExecutionContext,
    *,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
) -> EndSessionOutput:
    """End the active session after recovery preflight.

    Flow:
    1. Recovery preflight (read-only).
    2. Delegate to SessionRuntimeService.end_session.
    3. Return the completed Session.
    """
    _check_recovery_preflight(recovery_service)
    session = runtime_service.end_session(
        touched_entity_ids=input_model.touched_entity_ids,
        audit=context.audit,
    )
    return EndSessionOutput(session=session)


# ── Registration API ─────────────────────────────────────────────────────────


def register_session_mutation_tools(
    registry: ToolRegistry,
    *,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
) -> None:
    """Register session mutation tools on a ``ToolRegistry``.

    Registers exactly ``start_session``, ``record_event``,
    ``record_note``, and ``end_session`` with their definitions
    and wired handlers.

    Args:
        registry: A ``ToolRegistry`` instance.
        runtime_service: A ``SessionRuntimeService`` implementation.
        recovery_service: A ``SessionRecoveryService`` implementation.

    Raises:
        ValidationError: The registry is not a ToolRegistry.
        ConflictError: A tool with the same name is already registered.
    """
    if not isinstance(registry, ToolRegistry):
        raise ValidationError("registry must be a ToolRegistry instance")

    def _make_start_handler(
        input_model: StartSessionInput,
        context: ExecutionContext,
    ) -> StartSessionOutput:
        return _start_session_handler(
            input_model,
            context,
            runtime_service=runtime_service,
            recovery_service=recovery_service,
        )

    def _make_record_event_handler(
        input_model: RecordEventInput,
        context: ExecutionContext,
    ) -> RecordEventOutput:
        return _record_event_handler(
            input_model,
            context,
            runtime_service=runtime_service,
            recovery_service=recovery_service,
        )

    def _make_record_note_handler(
        input_model: RecordNoteInput,
        context: ExecutionContext,
    ) -> RecordNoteOutput:
        return _record_note_handler(
            input_model,
            context,
            runtime_service=runtime_service,
            recovery_service=recovery_service,
        )

    def _make_end_handler(
        input_model: EndSessionInput,
        context: ExecutionContext,
    ) -> EndSessionOutput:
        return _end_session_handler(
            input_model,
            context,
            runtime_service=runtime_service,
            recovery_service=recovery_service,
        )

    registry.register(_START_SESSION_DEFINITION, _make_start_handler)
    registry.register(_RECORD_EVENT_DEFINITION, _make_record_event_handler)
    registry.register(_RECORD_NOTE_DEFINITION, _make_record_note_handler)
    registry.register(_END_SESSION_DEFINITION, _make_end_handler)
