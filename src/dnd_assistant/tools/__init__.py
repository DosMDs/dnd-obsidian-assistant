"""Tool Layer — provider-neutral tool registry, executor, and typed metadata.

This package provides the foundational Tool Layer contracts:

- ``ToolRegistry`` — register, lookup, and list tool definitions.
- ``ToolExecutor`` — validated execution pipeline for registered tools.
- ``Permission``, ``SideEffect``, ``SessionMode`` — typed metadata vocabulary.
- ``ToolDefinition`` — provider-neutral tool metadata.
- ``ExecutionContext`` — trusted Python execution context.
- ``ToolPublicDefinition``, ``ToolRegistrySchema`` — provider-neutral
  public catalog DTOs.
- ``build_tool_registry_schema`` — generic catalog builder.

No concrete campaign tools are imported at package root.  Concrete tool
implementations (e.g. ``entity_reads``) must be imported explicitly by
composition code and registered through ``ToolRegistry.register()``.

This package must not import Ollama, ModelGateway, or any provider package.
"""

from dnd_assistant.tools.catalog import (
    ToolPublicDefinition,
    ToolRegistrySchema,
    build_tool_registry_schema,
)
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
    ToolDefinition,
    convert_pydantic_validation_error,
)

__all__: list[str] = [
    "ExecutionContext",
    "Permission",
    "SessionMode",
    "SideEffect",
    "ToolDefinition",
    "ToolExecutor",
    "ToolPublicDefinition",
    "ToolRegistry",
    "ToolRegistrySchema",
    "build_tool_registry_schema",
    "convert_pydantic_validation_error",
]
