---
name: tool-layer
description: Implement or review ToolRegistry, ToolExecutor, public tool schemas and safe model-callable read/write/calendar operations.
---
# Tool layer

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 7](../../../docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md), actual registry/executor/handler contracts and relevant tool-family tests.

Expose a small set of well-differentiated tools. Define typed input/output schemas and explicit permission, side-effect and session metadata. Preserve the executor's validation pipeline and exactly-once accepted handler invocation; domain validation, filesystem/audit effects, calendar arithmetic and entity resolution remain in their established service owners.

Handlers call trusted services/repositories. Never expose arbitrary shell/file writes, recursive delete or generic rename. Resolve entity ambiguity before mutation through the accepted resolution path; do not move resolver policy into the executor. Framework tool visibility is not authorization.

Add contracts linking published schemas to runtime validation/Python implementation, and negative tests for permissions, session/audit prerequisites, malformed input/output and side effects. Common failures include schema/executor drift, speculative write target selection and bypassing repository safety. Stop on new authority, broad generic tools or framework coupling outside scope. Framework bridges additionally require [PAIM guidance](../pydantic-ai-migration/SKILL.md); use [quality policy](../../../docs/development/quality-and-evidence.md).
