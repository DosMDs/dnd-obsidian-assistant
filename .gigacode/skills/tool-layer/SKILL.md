---
name: tool-layer
description: Implement or review ToolRegistry, ToolExecutor, tool schemas, safe read/write/calendar tools or model-callable operations.
compatibility: Python 3.12+, Pydantic, pytest.
metadata:
  version: "1"
---
# Tool layer

1. Expose a small set of well-differentiated tools; do not create dozens preemptively.
2. Define typed input/output schemas and side-effect/permission metadata.
3. Validate tool name, arguments, permission and domain invariants before execution.
4. ToolExecutor calls trusted application/domain/storage services; tools do not bypass repositories.
5. Never expose arbitrary shell, arbitrary file writes, recursive delete or generic rename to an LLM.
6. Keep calendar operations deterministic through CalendarService.
7. For writes involving entity references, resolve ambiguity before mutation.
8. Add contract tests ensuring published schema, runtime validation and Python implementation stay synchronized.
