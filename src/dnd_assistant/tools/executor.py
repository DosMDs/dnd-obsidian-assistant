"""ToolExecutor — deterministic execution pipeline for registered tools.

Responsibility
──────────────
Orchestrates the canonical execution order: registry lookup, input
validation, permission check, session-mode check, audit prerequisite,
handler invocation, output validation, typed result.

The executor must not:
    open Vault files, read/write Markdown/YAML/JSONL directly,
    execute shell commands, generate IDs, calculate revisions,
    calculate world_tick, perform entity resolution,
    repair session corruption, write audit.jsonl,
    catch and reinterpret domain/storage state.

This module belongs to the tools layer and must not import from:
    storage (runtime), domain, models, retrieval, application, cli, ollama
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.errors import ConflictError, NotFoundError, ValidationError
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    convert_pydantic_validation_error,
)

if TYPE_CHECKING:
    from dnd_assistant.tools.registry import ToolRegistry
    from dnd_assistant.tools.types import BaseModel, Handler


class ToolExecutor:
    """Executor that invokes registered tools through a validated pipeline.

    Args:
        registry: The ``ToolRegistry`` to look up tools from.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    # ── Public API ───────────────────────────────────────────────────────

    def execute(
        self,
        tool_name: str,
        *,
        input_data: dict[str, Any],
        context: ExecutionContext,
    ) -> BaseModel:
        """Execute a tool by name through the validated pipeline.

        Canonical execution order:

        1. Registry lookup.
        2. Raw input validation against ToolDefinition.input_schema.
        3. Permission validation.
        4. Allowed-session-mode validation.
        5. WRITE AuditContext prerequisite.
        6. Handler invocation exactly once.
        7. Output validation against ToolDefinition.output_schema.
        8. Return typed output.

        Args:
            tool_name: The registered tool name.
            input_data: Raw input data as a Python mapping.
            context: The execution context (permission, session mode, audit).

        Returns:
            The validated typed output.

        Raises:
            NotFoundError: Unknown tool name.
            ValidationError: Invalid input, output, or execution context
                prerequisites.
            ConflictError: Permission or session-mode policy denial.
            DndAssistantError: Propagated unchanged from the handler.
            Exception: Any non-DndAssistantError exception raised by the
                handler propagates unchanged (programming bugs, runtime
                failures, etc.).
        """
        # 1. Registry lookup
        try:
            binding = self._registry.get(tool_name)
        except NotFoundError:
            raise

        definition = binding.definition
        handler: Handler = binding.handler

        # 2. Raw input validation
        try:
            validated_input = definition.input_schema.model_validate(input_data)
        except PydanticValidationError as exc:
            raise convert_pydantic_validation_error(exc) from exc

        # 3. Permission validation
        if (
            context.granted_permission == Permission.READ
            and definition.permission == Permission.WRITE
        ):
            raise ConflictError(
                f"Permission denied: READ authority cannot execute WRITE tool '{tool_name}'"
            )

        # 4. Allowed-session-mode validation
        if context.session_mode not in definition.allowed_session_modes:
            raise ConflictError(
                f"Session mode '{context.session_mode.value}' is not allowed for tool '{tool_name}'"
            )

        # 5. WRITE AuditContext prerequisite
        if definition.permission == Permission.WRITE and context.audit is None:
            raise ValidationError(f"WRITE tool '{tool_name}' requires a non-None AuditContext")

        # 6. Handler invocation exactly once.
        # Non-DndAssistantError exceptions propagate unchanged so that
        # programming bugs and runtime failures remain visible.
        raw_output = handler(validated_input, context)

        # 7. Output validation
        try:
            validated_output = definition.output_schema.model_validate(raw_output)
        except PydanticValidationError as exc:
            raise convert_pydantic_validation_error(exc) from exc

        # 8. Return typed output
        return validated_output
