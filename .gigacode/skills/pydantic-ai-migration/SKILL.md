---
name: pydantic-ai-migration
description: Implement, review or qualify PAIM tasks that migrate D&D Session Assistant generic agent/model runtime mechanics to Pydantic AI while preserving ToolExecutor, domain/storage and Stage-9 safety boundaries.
compatibility: Python 3.12+, Pydantic, httpx, pytest, current project ToolExecutor/ModelGateway/Fast Agent reference; Pydantic AI candidate version is task-specific until accepted.
metadata:
  version: "1"
---
# Pydantic AI runtime migration

## Before editing

Read in this order:

```text
DEVELOPMENT_STATUS.md
docs/adr/0003-pydantic-ai-runtime-migration.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
.gigacode/rules/40-pydantic-ai-migration.md
relevant current implementation/tests
```

Capture:

- starting branch and SHA;
- PAIM task ID;
- exact responsibility being qualified/replaced;
- existing Stage-9 behavior tests that define the reference;
- framework version if dependency already exists.

## Task design checklist

For each change answer explicitly:

1. What custom responsibility is being replaced or qualified?
2. Which Pydantic AI public API/extension point supplies generic mechanism?
3. Which D&D-specific invariants must remain outside framework?
4. Can all side effects still route through `ToolExecutor`?
5. Can forbidden tool batches be rejected before first side effect?
6. What retry/concurrency/thread behavior changes?
7. What Ollama/provider behavior changes?
8. Which old code becomes superseded, and when will it be removed?
9. What test proves parity rather than framework internals?

## Tool bridge rule

Preferred shape:

```text
ToolRegistrySchema
→ framework tool definitions/toolset
→ thin invocation adapter
→ ToolExecutor.execute(...)
```

Do not move repository/domain writes into direct framework tool functions.

## Policy rule

Keep or introduce one cohesive application policy layer (`DndAgentPolicy` or equivalent) for Stage-9 safety semantics.

Do not scatter policy across unrelated hooks without a clear owner.

## Qualification first

Before large refactor, prove critical framework behavior with focused tests/spikes. If a blocker appears, stop expanding migration scope and document it.

A PAIM task may legitimately end with:

```text
qualified
selective-custom required
blocked pending architecture decision
migration rejection recommended
```

Do not hide a failed gate with a large workaround.

## Ollama comparison

When working on PAIM-09 or provider integration, compare against current native behavior using equivalent requests/model configuration.

Include both mocked contracts and explicit opt-in real Ollama smoke where the task requires it.

## Test strategy

Prefer stable project behavior assertions over Pydantic AI internal graph/message snapshots.

Critical negative tests include:

- hidden/unknown tool;
- mixed READ/WRITE batch;
- multiple WRITE;
- duplicate call ID;
- invalid args/output;
- retry-sensitive failure;
- second tool round;
- missing permission/session/audit prerequisite;
- zero side effects on rejected batch.

## Cleanup rule

Do not keep old production runtime merely as a runtime fallback. Once a replacement is accepted and parity evidence is green, remove superseded generic code in the planned cleanup task.

Reference remains in Git/main.

## Final report

Include:

- starting SHA/branch;
- final changed-file inventory;
- framework version/API used;
- reference behavior/invariants tested;
- tests/gates with exact results;
- any framework limitation found;
- classification: acceptable / selective-custom / blocker;
- removed/deferred old code;
- commit SHA/message/push result;
- upstream equality verification.

Use the repository's adaptive quality-gate and mandatory Git finalization rules.
