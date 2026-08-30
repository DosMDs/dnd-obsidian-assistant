"""ToolRegistry — deferred contract for the registry of callable tools.

Responsibility
──────────────
Owns: tool definitions, tool metadata, tool lookup.
Must not own: tool execution logic, tool result handling.
Called by: application layer, ToolExecutor.
Failure boundary: raises NotFoundError for unknown tools,
                  ValidationError for invalid schemas.

Deferred to Stage 7
────────────────────
The typed ToolRegistry API and ToolDefinition schema belong to Stage 7
(Tool layer). Stage 1 inventories the responsibility boundary only — no
executable signatures are defined here.
"""
