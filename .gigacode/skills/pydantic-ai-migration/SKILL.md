---
name: pydantic-ai-migration
description: Implement, review or qualify PAIM tasks that migrate D&D Session Assistant generic agent/model runtime mechanics to Pydantic AI while preserving ToolExecutor, domain/storage and Stage-9 safety boundaries. Includes parity, real-Ollama and eval-harness evidence requirements.
compatibility: Python 3.12+, Pydantic, httpx, pytest, current project ToolExecutor/ModelGateway/Fast Agent reference; Pydantic AI candidate version is task-specific until accepted.
metadata:
  version: "2"
---
# Pydantic AI runtime migration

## Before editing

Read in this order:

```text
DEVELOPMENT_STATUS.md
docs/adr/0003-pydantic-ai-runtime-migration.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
.gigacode/rules/40-pydantic-ai-migration.md
.gigacode/rules/38-behavioral-evidence-integrity.md
relevant current implementation/tests
```

For eval/benchmark work also read/use:

```text
.gigacode/skills/eval-harness/SKILL.md
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
10. What literal evidence proves every hard acceptance criterion?

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

## Pinned-framework source verification

When implementing a framework wrapper/decorator/capability or relying on exact
request/retry/deferred behavior:

1. identify the exact pinned Pydantic AI version/tag;
2. inspect the relevant public source/API contract for that version;
3. use public extension points;
4. add an offline construction/contract test before any expensive live run.

Do not assume a duck-typed wrapper is accepted when production performs
concrete `isinstance` checks.

For model wrappers, preserve/delegate relevant public semantics such as:

```text
Model base type
model_name
system/provider identity
base_url
settings
profile
request/exception behavior
resource lifecycle where applicable
```

Do not weaken production validation to accommodate test instrumentation.

## Ollama comparison

When working on PAIM-09 or provider integration, compare against current native behavior using equivalent requests/model configuration.

Include both mocked contracts and explicit opt-in real Ollama smoke where the task requires it.

Real smoke evidence must prove the actual project path, not only a bare Pydantic `Agent`:

```text
machine-local profile
→ production Pydantic model factory
→ production runtime
→ real Ollama
→ project policy/ToolExecutor path
```

When claiming direct/no-tool behavior, assert the actual exposure snapshot is empty. When claiming handler/result replay, measure handler calls and project TOOL message content literally.

## Parity-gate strategy

For old/new runtime parity:

- drive both sides from one shared logical scenario specification;
- use independent but equivalent mutable state;
- prove reference and candidate runtime identity before the matrix;
- compare application/provider-neutral DTOs, not private framework internals;
- assert exact error categories where they are project contracts;
- assert semantic model request count, executor attempts and handler effects for negative paths;
- do not infer zero executor attempts from zero handler calls;
- do not compare different failure mechanisms and call it parity.

A shared negative helper must fail closed and must not accept arbitrary exceptions.

## Real-live gate preflight

Before an opt-in real Ollama gate:

```text
offline fixture/constructor preflight
→ wrapper/type contract tests
→ scoring/helper tests
→ default env-unset skip behavior
→ explicit real live run
```

A skipped live test is not proof that its fixture graph can be constructed.

Do not mark a live gate ready solely because offline pytest skipped it cleanly.

## Eval/measurement gate strategy

For PAIM eval comparison:

### Ground truth

- deterministic Python expectations;
- no LLM-as-judge;
- no chain-of-thought grading/storage;
- synthetic campaign data, never real Vault mutation.

### Reference/candidate identity

Prove the two compared systems are actually distinct, e.g.:

```text
reference:
FastAgent / AgentLoop + native OllamaModelProvider

candidate:
PydanticAIFastAgent / PydanticAIAgentRuntime + official Pydantic OllamaModel
```

Do not trust fixture names; assert object/path identity offline.

### Same configuration

Use the same:

```text
ModelProfile
model name
temperature
application context
tool definitions
scenario wording
```

unless a transport difference is explicitly the subject of the eval.

### Literal counters

Measure semantic model requests at the real semantic boundary on both sides.
Do not derive request count from tool execution count.

Measure handler/executor effects directly when they are reported.

### Frozen measured datasets

For each measured layer:

```text
symmetric warm-up before timing
→ collect scenario × repetition × runtime samples exactly once
→ freeze observations in memory
→ reuse the same observations for scenario classification, metrics and latency
```

Never rerun the real model merely to compute aggregate metrics.

Warm-up must not depend on pytest test ordering.

### Metric contracts

Define numerator/denominator/unit/error treatment for every metric.

Errors are not successful abstention.

False-WRITE metrics must distinguish:

```text
WRITE visible but not expected
vs
WRITE hidden by application policy
```

### Critical blockers

The measured suite should fail automatically for agreed critical regressions,
including where applicable:

```text
candidate false WRITE
candidate unauthorized WRITE handler execution
candidate > allowed semantic model requests
critical REFERENCE_ONLY_PASS scenario
```

Do not hide critical regressions inside aggregate averages.

### Performance

Report measured p50/p95 and ratios without inventing a portability SLA.
Do not infer causal explanations (for example model loading) from a slow sample
unless separately instrumented.

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

## Correction escalation

If a PAIM task reaches two or more correction passes for the same evidence or
harness defect class, stop before another prompt-specific patch.

Use `correction-review` to identify the repeated pattern and update a reusable
rule/skill/helper when appropriate.

Common escalation patterns:

```text
claims stronger than assertions
inferred metrics reported as measured
reference/candidate self-comparison
live fixture only tested through skip
maintainability allowlist used as a convenience
warm-up/sample ownership errors
migration record transcription drift
```

## Cleanup rule

Do not keep old production runtime merely as a runtime fallback. Once a replacement is accepted and parity evidence is green, remove superseded generic code in the planned cleanup task.

Reference remains in Git/main.

## Final report

Include:

- starting SHA/branch;
- final changed-file inventory;
- framework version/API used;
- reference behavior/invariants tested;
- acceptance-to-evidence mapping for hard criteria;
- tests/gates with exact results;
- exact command identity for canonical vs focused vs live suites;
- any framework limitation found;
- classification: acceptable / selective-custom / blocker;
- removed/deferred old code;
- commit SHA/message/push result;
- upstream equality verification.

Use the repository's adaptive quality-gate, behavioral-evidence and mandatory Git finalization rules.
