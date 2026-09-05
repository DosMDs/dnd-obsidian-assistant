# Migration 001 — Pydantic AI Runtime Migration

## 1. Decision

Project will evaluate and, if gates pass, migrate generic agent/model runtime mechanics to Pydantic AI in a dedicated branch.

This is not a commitment to force full framework adoption. The migration is intentionally reversible and evidence-driven.

Reference custom runtime remains available in `main` and Git history.

## 2. Reference baseline

```text
Repository: DosMDs/dnd-obsidian-assistant
Reference branch: main
Reference SHA: f424a0f659afd5f8bcbce55c4d280cc8e621133f
Date: 2026-09-04
State: S9-06 accepted, S9-07 not started
```

Active migration branch:

```text
feat/pydantic-ai-runtime
```

PAIM-00 kickoff commit:

```text
ac9fd4c7e19475adb2331eb010ce8c78af98b309
```

Optional human-friendly reference tag may be created separately, but branch base SHA is sufficient for rollback/review.

## 3. Why migrate now

The project already has a reliable custom implementation of:

- provider-neutral model protocol;
- native Ollama integration;
- tool-call DTO/validation plumbing;
- one-step FastAgent;
- bounded AgentLoop;
- CLI composition;
- extensive safety tests.

That work provides an unusually strong reference specification. Stage 10+ has not started, so migration can happen before later features depend on the custom runtime shape.

## 4. Target value

Pydantic AI should reduce maintenance of generic infrastructure:

- provider/message protocol details;
- tool-call/tool-result mechanics;
- structured output plumbing;
- generic model→tool→model loop;
- request/tool usage accounting;
- standard tracing/instrumentation.

It must not replace trusted application policy.

## 5. Non-negotiable boundaries

### Must remain custom/project-owned

```text
Domain schemas
VaultRepository
CalendarService
Retrieval/EntityResolver
Session runtime/raw JSONL
ToolRegistry application metadata
ToolExecutor
Permission/session/audit policy
DndAgentPolicy
ChangeSet
Post-session policy
Campaign State policy
Deterministic eval acceptance rules
```

### May move to framework

```text
Agent model protocol
Message/tool-call plumbing
Structured output mechanics
Generic run loop
Tool-result replay
Usage/tracing support
```

## 6. Authorization rule

No framework facility is trusted as the final authorization boundary.

```text
framework-visible tool
→ application adapter
→ ToolExecutor
→ trusted side effect
```

This rule remains even if framework filtering/approval appears sufficient in normal cases.

## 7. PAIM task map

### PAIM-00 — Documentation/branch kickoff — DONE

No runtime changes.

Deliverables:

- migration branch;
- ADR;
- migration plan;
- status/roadmap update;
- GigaCode rule/skill;
- exact base SHA;
- outcome/rollback policy.

### PAIM-01 — Candidate dependency qualification

Build minimal isolated tests/spike using chosen Pydantic AI candidate.

Prove:

- import/runtime compatibility;
- sync entrypoint behavior;
- local Ollama connection;
- structured result;
- single tool;
- multi-tool response;
- custom base URL;
- predictable failure mapping.

No FastAgent replacement yet.

### PAIM-02 — Blocker gate

Prove the exact architecture-critical capabilities:

- complete batch admission before side effects;
- sequential tool execution;
- explicit retry control;
- bounded requests/tool calls;
- immutable/frozen per-turn exposed set at application level;
- all calls route via `ToolExecutor`;
- hidden/unknown/malformed call fails closed.

If not achievable using stable public extension points, stop and classify issue before continuing.

### PAIM-03 — Test harness improvements directly needed by migration

Only if necessary:

- standardize HTTPX mocking with `respx`;
- evaluate `pytest-randomly` for hidden state.

Do not bundle unrelated infrastructure libraries.

### PAIM-04 — Toolset bridge

Translate `ToolRegistry` public definitions into Pydantic AI tool definitions/toolset without moving handler logic.

Invocation goes to `ToolExecutor`.

### PAIM-05 — DndAgentPolicy

Create explicit application policy component or equivalent cohesive layer covering all Stage-9 agent safety semantics.

### PAIM-06 — Context/deps integration

Reuse accepted Context Builder/retrieval path. Context remains application-prepared data.

### PAIM-07 — Replace one-step FastAgent mechanics

Use framework for first model decision while preserving observable app contract/safety behavior.

### PAIM-08 — Replace bounded AgentLoop mechanics

Use framework generic orchestration. Preserve D&D-specific limits/admission/terminal rules.

### PAIM-09 — Ollama gate

Compare framework integration to native reference. Select:

```text
framework Ollama
custom/native Ollama component
migration reconsideration
```

### PAIM-10 — Sync/thread gate

Prove worker-thread/tool-callback behavior does not violate storage/audit/session assumptions.

### PAIM-11 — Full behavioral parity

Run Stage-9 negative/boundary suite against final migration runtime.

### PAIM-12 — Real Ollama smoke/performance

Use actual accepted local model/profile for operational evidence.

### PAIM-13 — Eval comparison

Measure safety/correctness/latency vs reference.

### PAIM-14 — Cleanup

Delete superseded generic custom infrastructure and obsolete implementation-specific tests. Avoid permanent dual runtime.

### PAIM-15 — Final review

Decide `ACCEPTED`, `PARTIAL`, or `REJECTED`.


## 8. PAIM-00 completion record

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Reference/base SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`
**PAIM-00 commit:** `ac9fd4c7e19475adb2331eb010ce8c78af98b309`

Git verification confirms the PAIM-00 commit is a direct child of the accepted reference SHA and that the migration branch is exactly one commit ahead of the reference at this checkpoint. `main` remains at `f424a0f659afd5f8bcbce55c4d280cc8e621133f`.

### Exact PAIM-00 changed-file inventory

```text
.gigacode/rules/40-pydantic-ai-migration.md
.gigacode/skills/pydantic-ai-migration/SKILL.md
DEVELOPMENT_STATUS.md
GIGACODE.md
docs/adr/0003-pydantic-ai-runtime-migration.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
docs/migrations/README.md
docs/stages/09_FAST_AGENT.md
```

All eight changed files are Markdown documentation/agent-instruction files. No Python source, tests, `pyproject.toml`, `uv.lock`, runtime configuration, provider code, tool code or Vault/storage code changed in PAIM-00.

### Evidence note

The repository facts above were independently reconciled from Git after the PAIM-00 commit. This record intentionally does **not** invent command-level test/Ruff results that are not present in the retained repository evidence. PAIM-00 is accepted as the documentation/architecture kickoff; PAIM-C00 reconciles the documentation gaps before PAIM-01.

### Next task

```text
PAIM-01 — Candidate dependency/framework qualification
```

## 9. Blocker criteria

A framework behavior is a potential blocker when project invariants cannot be implemented through public/supported APIs without large fragile workaround.

Examples:

- cannot preflight complete mixed tool batch before any execution;
- cannot guarantee ToolExecutor-only side effects;
- framework forces retries that can repeat writes;
- sync/thread behavior breaks trusted storage assumptions and requires domain redesign;
- Ollama integration loses critical tool/structured-output correctness;
- maintaining project semantics requires effectively rewriting the framework run loop internally.

## 10. Escape hatch levels

### Level 1 — supported extension

Use hooks/toolsets/custom model/provider/output validator/public graph API.

### Level 2 — selective custom component

Keep/implement only the problematic component, e.g. native Ollama adapter.

### Level 3 — reject migration

Do not merge runtime branch. Preserve findings and continue custom implementation from `main`.

## 11. Rollback/rejection documentation

If `REJECTED`, record:

- exact Pydantic AI version;
- Ollama version/model where relevant;
- failing invariant;
- minimal reproduction/test;
- framework issue/limitation reference;
- attempted public extension points;
- why custom workaround was rejected;
- implications for future custom runtime design.

Port this conclusion back to `main` as documentation even though runtime changes are not merged.

## 12. No-double-runtime rule

Reference comparison may temporarily instantiate old/new mechanics in tests or spike modules.

Final migration branch before merge must not expose two equal-status production agent runtimes selected by config merely to avoid deleting old code.

The fallback is Git/main, not a permanent feature flag.

## 13. Dependency/upgrade policy

- exact framework candidate chosen by PAIM-01;
- lock exact transitive resolution via `uv.lock`;
- no unrelated dependency upgrades;
- later Pydantic AI upgrade = standalone maintenance task;
- provider/framework release notes and regression tests required.

## 14. Completion order

```text
S9-06 accepted baseline
→ PAIM-00..15
→ outcome
→ S9-07 Stage-9 final historical review
→ Stage 9 DONE
→ Stage 10
```
