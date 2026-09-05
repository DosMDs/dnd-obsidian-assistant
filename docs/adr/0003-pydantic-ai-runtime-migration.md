# ADR-0003 — Controlled Pydantic AI Runtime Migration

- **Status:** Accepted for controlled migration; final runtime adoption pending
- **Date:** 2026-09-04
- **Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`
- **Migration branch:** `feat/pydantic-ai-runtime`
- **PAIM-00 kickoff commit:** `ac9fd4c7e19475adb2331eb010ce8c78af98b309`
- **Decision owner:** project architecture

## Context

Stage 8 and Stage 9 produced a substantial custom LLM/agent infrastructure:

- synchronous provider-neutral `ModelGateway`;
- native Ollama provider/adapters;
- structured response/tool-call DTO validation;
- deterministic tool exposure;
- compact Context Builder;
- one-step `FastAgent`;
- bounded model→tool→model `AgentLoop`;
- application-level allowlist and multi-tool safety semantics;
- `dnd ask` CLI with mocked/parser-backed E2E evidence.

This custom implementation is reliable enough to act as a behavioral reference, but continuing to maintain generic provider/tool/agent-loop mechanics may create unnecessary infrastructure cost.

Pydantic AI provides typed agent/model/tool/structured-output abstractions and official Ollama support. It may replace a meaningful portion of generic runtime code, but its framework defaults do not automatically encode D&D Session Assistant trust/safety semantics.

## Decision

Evaluate and implement a **controlled migration** to Pydantic AI in a dedicated branch from the accepted S9-06 reference baseline.

Migration branch (created from the reference SHA):

```text
feat/pydantic-ai-runtime
```

The migration is not a commitment to full framework takeover. It is an evidence-driven architecture program with three valid outcomes: `ACCEPTED`, `PARTIAL`, `REJECTED`.

## Reference and rollback strategy

`main` remains the fully working custom reference implementation until a migration result is accepted.

The project does **not** keep two equal-status production runtimes indefinitely for rollback. Git history/main is the rollback mechanism.

Optional short-lived comparison/spike code is allowed only where needed to prove parity/blockers and must be removed or integrated before final review.

## Ownership boundary

### Pydantic AI may own generic mechanism

- provider/model message protocol;
- model invocation;
- structured-output mechanism;
- tool-call protocol;
- tool-result replay;
- generic model→tool→model orchestration;
- request/tool usage accounting;
- framework tracing/instrumentation;
- retry mechanics only under explicit project policy.

### D&D Session Assistant continues to own policy/consequences

- domain schemas;
- `VaultRepository`;
- path/revision/atomic-write rules;
- `CalendarService`;
- retrieval/visibility/entity resolution;
- raw session runtime;
- `ToolRegistry` application metadata;
- `ToolExecutor`;
- permissions/session-mode/audit policy;
- `DndAgentPolicy`;
- ambiguity/clarification policy;
- `ChangeSet`;
- post-session write policy;
- deterministic eval acceptance rules.

## Authorization decision

Framework tool exposure/filtering/approval is **not** an authorization boundary.

Every accepted side-effecting invocation must flow through:

```text
Pydantic AI / model
→ framework-visible tool adapter
→ DndAgentPolicy admission
→ ToolExecutor
→ application/domain service
→ VaultRepository
```

No PAIM task may rewrite write handlers as direct framework tools that bypass `ToolExecutor`.

## Stage-9 semantics to preserve

Migration must preserve equivalent externally observable behavior for:

- frozen turn-local exposed-tool set;
- fail-closed hidden/unknown tool calls;
- bounded model requests;
- bounded tool calls;
- READ-only accepted multi-call batch policy;
- mixed/forbidden WRITE batch rejection before any execution;
- duplicate non-null call ID rejection;
- WRITE audit prerequisite;
- sequential execution where a batch is accepted;
- explicit retry policy;
- terminal second-response restrictions;
- clarification over speculative write.

Framework default behavior is subordinate to these semantics.

## Ollama decision

Pydantic AI's Ollama path must be qualified against the current native provider.

A final architecture such as:

```text
Pydantic AI Agent
+
custom/native Ollama model/provider helper
+
DndAgentPolicy
+
ToolExecutor
```

is explicitly allowed and is classified as `PARTIAL`, not failure.

## Framework escape hatch

When a framework limitation is found:

1. Prefer documented public extension points.
2. If necessary, keep/implement a small selective custom component.
3. If preserving project invariants requires large private-internal patching or effectively rewriting framework orchestration, classify migration as `REJECTED`.

The architecture must not be weakened solely to fit framework defaults.

## Dependency policy

- choose a concrete Pydantic AI version through PAIM qualification;
- pin accepted version/resolution with project dependency metadata and `uv.lock`;
- avoid unrelated dependency upgrades;
- framework upgrades are standalone maintenance tasks;
- upgrades require release-note review and regression gates.

## Known risk themes at decision time

Qualification must cover at least:

- framework tool filtering/authorization separation;
- Ollama compatibility vs native API behavior;
- multi-tool concurrency/batching;
- automatic retries;
- sync tool execution/thread offload;
- structured output + tool calling interactions;
- framework approval not being trusted authorization;
- framework history not replacing raw session history.

See project migration risk register/context for current issue references.

## Outcome definitions

### ACCEPTED

Framework becomes primary generic agent runtime. Superseded custom generic code is removed.

### PARTIAL

Framework becomes primary for compatible generic mechanics while documented custom component(s) remain because they better satisfy project invariants.

### REJECTED

Runtime migration changes are not merged. `main` custom runtime remains canonical. The final ADR/findings are ported to `main` so the failed approach and evidence remain documented.

## Consequences

Positive:

- potential reduction in custom generic runtime code;
- standard typed agent/tool/output abstractions;
- easier provider/runtime evolution;
- ability to use framework tracing/eval ecosystem selectively.

Costs/risks:

- new framework dependency and upgrade cadence;
- potential semantic mismatch with strict Stage-9 safety behavior;
- possible native Ollama feature regression through compatibility APIs;
- thread/retry/concurrency defaults requiring explicit control.

## Migration kickoff status

PAIM-00 was completed on 2026-09-05 in `feat/pydantic-ai-runtime`. Git verification shows the PAIM-00 commit `ac9fd4c7e19475adb2331eb010ce8c78af98b309` is a direct child of the reference main SHA `f424a0f659afd5f8bcbce55c4d280cc8e621133f`. `main` remains unchanged at the reference SHA.

The next qualification task is `PAIM-01`.

## Follow-up

Canonical task plan:

```text
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

`S9-07` and Stage 10 are deferred until PAIM final architecture review.
