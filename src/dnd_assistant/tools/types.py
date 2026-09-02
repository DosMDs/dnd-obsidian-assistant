"""Provider-neutral typed metadata for the Tool Layer.

Defines the foundational vocabulary for tool definitions, permissions,
side effects, session-mode enforcement, and execution context.

This module belongs to the tools layer and must not import from:
    storage, domain, models, retrieval, application, cli, ollama
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.errors import ValidationError

# ── Permission ───────────────────────────────────────────────────────────────


class Permission(StrEnum):
    """Execution authority level for a tool.

    READ  — may invoke only READ-permission tools.
    WRITE — may invoke both READ and WRITE tools.
    """

    READ = "read"
    WRITE = "write"


# ── Side effect ──────────────────────────────────────────────────────────────


class SideEffect(StrEnum):
    """Machine-readable side-effect category for a tool.

    A read-only tool has an empty side-effect set.
    A write tool must declare at least one supported side effect.
    """

    ENTITY_MUTATION = "entity_mutation"
    SESSION_MUTATION = "session_mutation"
    WORLD_TIME_MUTATION = "world_time_mutation"


# ── Session mode ─────────────────────────────────────────────────────────────


class SessionMode(StrEnum):
    """Execution-state vocabulary for session-mode enforcement.

    A ToolDefinition may allow one or both modes.
    """

    NO_ACTIVE_SESSION = "no_active_session"
    ACTIVE_SESSION = "active_session"


# ── Tool name validation ─────────────────────────────────────────────────────


def _validate_tool_name(value: str) -> str:
    """Validate a tool name.

    Requirements:
    - non-empty string
    - printable
    - no leading/trailing whitespace
    - snake_case: lowercase ASCII letters, digits, underscores only
    """
    if not isinstance(value, str):
        raise ValueError("tool name must be a string")
    if not value:
        raise ValueError("tool name must not be empty")
    if value.strip() != value:
        raise ValueError("tool name must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError("tool name must not contain non-printable characters")
    if not value.replace("_", "").isalnum() or value != value.lower():
        raise ValueError(
            "tool name must be snake_case: lowercase ASCII letters, digits, and underscores only"
        )
    return value


def _validate_non_empty_printable(value: str, field_name: str) -> str:
    """Validate a non-empty printable string without surrounding whitespace."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    if not value.isprintable():
        raise ValueError(f"{field_name} must not contain non-printable characters")
    return value


# ── ToolDefinition ───────────────────────────────────────────────────────────


class ToolDefinition(BaseModel):
    """Provider-neutral typed definition of a callable tool.

    Attributes:
        name: Deterministic snake_case machine name.
        description: Human-readable description.
        input_schema: Pydantic BaseModel subclass for validated input.
        output_schema: Pydantic BaseModel subclass for validated output.
        permission: Execution authority level.
        side_effects: Machine-readable side-effect categories (empty for READ).
        allowed_session_modes: Session modes in which this tool may execute.
    """

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    permission: Permission
    side_effects: frozenset[SideEffect]
    allowed_session_modes: frozenset[SessionMode]

    model_config = {"frozen": True, "extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        """Construct a ToolDefinition, converting Pydantic validation errors.

        This ensures that validation failures at the Tool Layer API boundary
        are surfaced as project ``ValidationError`` rather than leaking
        Pydantic exception types.
        """
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc

    # ── Field validators ──────────────────────────────────────────────────

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_tool_name(value)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _validate_non_empty_printable(value, "description")

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _validate_schema(cls, value: type[BaseModel]) -> type[BaseModel]:
        if not (isinstance(value, type) and issubclass(value, BaseModel)):
            raise ValueError("input_schema and output_schema must be BaseModel subclasses")
        return value

    @field_validator("side_effects")
    @classmethod
    def _validate_side_effects(
        cls, value: frozenset[SideEffect], info: Any
    ) -> frozenset[SideEffect]:
        permission = info.data.get("permission")
        if permission == Permission.READ:
            if value:
                raise ValueError("READ tools must have an empty side_effects set")
        elif permission == Permission.WRITE:
            if not value:
                raise ValueError("WRITE tools must declare at least one side effect")
        return value

    @field_validator("allowed_session_modes")
    @classmethod
    def _validate_allowed_session_modes(
        cls, value: frozenset[SessionMode]
    ) -> frozenset[SessionMode]:
        if not value:
            raise ValueError("allowed_session_modes must not be empty")
        return value


# ── ToolBinding ──────────────────────────────────────────────────────────────

# Handler type: receives validated typed input and returns a BaseModel.
Handler = Callable[..., BaseModel]


class ToolBinding(BaseModel):
    """Internal binding that pairs a ToolDefinition with its callable handler.

    This is an internal type used by ToolRegistry. It is not part of the
    stable public API.
    """

    definition: ToolDefinition
    handler: Handler

    model_config = {"frozen": True, "extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        """Construct a ToolBinding, converting Pydantic validation errors."""
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── ExecutionContext ─────────────────────────────────────────────────────────


class ExecutionContext(BaseModel):
    """Trusted Python execution context for tool invocation.

    This is orchestration input provided by the application layer, not a
    model-output schema.

    Attributes:
        granted_permission: The permission level granted to this execution.
        session_mode: The current session execution mode.
        audit: Audit context for write operations. Must be non-None for
            WRITE invocations. READ invocations must not require it.
    """

    granted_permission: Permission
    session_mode: SessionMode
    audit: Any = None
    """Audit context for write operations.

    At runtime this is expected to be an ``AuditContext`` instance or
    ``None``.  The type is ``Any`` to avoid a runtime dependency on
    ``storage.audit`` at the tools layer.  Static type checkers see the
    ``TYPE_CHECKING`` import above.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    def __init__(self, **data: Any) -> None:
        """Construct an ExecutionContext, converting Pydantic validation errors."""
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc), cause=exc) from exc


# ── Public conversion helpers ────────────────────────────────────────────────


def convert_validation_error(exc: Exception) -> ValidationError:
    """Convert a Pydantic/library validation error to a project ValidationError.

    This is used at the Tool Layer API boundary to ensure that validation
    failures are surfaced as project exceptions rather than leaking
    provider/library exception types.

    Args:
        exc: The caught exception.

    Returns:
        A ``ValidationError`` wrapping the original message.
    """
    msg = str(exc) if str(exc) else "Validation failed"
    if isinstance(exc, ValidationError):
        return exc
    return ValidationError(msg, cause=exc if isinstance(exc, Exception) else None)
