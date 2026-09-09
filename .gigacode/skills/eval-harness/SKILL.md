---
name: eval-harness
description: Design, implement or review deterministic model/runtime eval and benchmark harnesses with truthful reference/candidate identity, frozen measured datasets, literal counters, safe live opt-in execution and evidence-driven metrics.
compatibility: D&D Session Assistant repository, Python 3.12+, pytest, local Ollama/model runtimes, deterministic test fixtures.
metadata:
  version: "1"
---

# Eval harness design and review

Use this skill for:

- PAIM eval comparison;
- model/tool-selection evals;
- runtime/provider comparison;
- latency sampling;
- any test suite that reports quality/performance metrics from repeated model runs.

Do not use it for ordinary unit tests that have no measurement/sample semantics.

## 1. Define the question before the harness

Write down:

```text
systems being compared
stable ground truth
scenario set
repetition count
hard safety blockers
quality metrics
performance metrics
live/offline boundary
```

Do not tune the scenario set after observing one side's results unless the
original scenario is objectively malformed; if changed, restart the measured
run for both systems.

## 2. Deterministic ground truth

Ground truth is Python data, not another LLM.

Prefer exact evaluation of:

```text
terminal outcome kind
tool names
tool arguments
schema validity
WRITE/non-WRITE classification
model request count
executor/handler count
side effects
latency
```

Do not grade style/semantic quality with an LLM judge unless a later project
decision explicitly adds that methodology.

Never store or grade hidden chain-of-thought.

## 3. Prove system identity first

Before a live run, add an offline architecture guard that proves reference and
candidate are the intended distinct systems.

Examples:

```text
reference FastAgent + native ModelGateway
candidate PydanticAIFastAgent + Pydantic Model

reference AgentLoop
candidate PydanticAIAgentRuntime
```

Do not trust fixture variable names.

If both sides accidentally use the same runtime/provider, STOP.

## 4. Same logical input

Both systems must receive equivalent:

- user input;
- application context;
- permissions/session/audit state;
- tool definitions and schemas;
- model name/settings/profile where comparison requires it.

Use one scenario object as the source of truth.

Maintain independent mutable tool/repository state per system so one run does
not affect the other.

## 5. Live harness preflight

Before any expensive external run:

1. construct the full test-owned object graph offline where possible;
2. validate concrete framework type requirements;
3. validate repository/service test-double contracts;
4. unit-test scorers/counters/percentiles;
5. prove default env-unset tests skip before network;
6. only then enable the live environment.

A skipped live module is not constructor evidence.

## 6. Transparent measurement wrappers

Measurement wrappers must not alter the behavior being measured.

For framework `Model` wrappers:

```text
subclass/implement the actual required type
preserve model identity
preserve settings/profile/base_url/provider semantics as applicable
preserve request response and exceptions
preserve lifecycle behavior where relevant
```

Count the request attempt at the semantic request boundary and delegate
unchanged.

Add offline equivalence tests.

Do not instrument private transport internals merely because they are easier to
count.

## 7. Literal counters

If a metric/claim names a count, measure that boundary directly.

Examples:

```text
semantic model requests
→ request/chat_with_tools boundary counter

ToolExecutor attempts
→ executor/delegating spy

handler invocations
→ handler counter

WRITE side effects
→ explicit WRITE-state counter
```

Do not infer one count from another.

## 8. Warm-up and sample ownership

Measured data must follow:

```text
symmetric warm-up
→ measured collection exactly once
→ freeze observations
→ reuse observations for every report/assertion
```

Warm-up:

- happens inside setup/fixture, not by pytest test ordering;
- occurs before timing;
- is excluded from quality and latency samples;
- may advance test counters only if per-run deltas isolate measured counts.

## 9. Frozen datasets

For each measurement layer own one dataset object.

A dataset should contain enough information for all consumers:

```text
reference observations
candidate observations
scenario/repetition keys
scenario comparisons
metric summaries
latency samples
safety counts
```

Per-scenario tests and aggregate tests must inspect this dataset without
calling the real model again.

Assert expected sample count and uniqueness.

## 10. Order-bias control

Use a predeclared deterministic execution order.

For paired 3-repetition evals, a reasonable pattern is:

```text
rep 0: reference → candidate
rep 1: candidate → reference
rep 2: reference → candidate
```

Do not change order after observing results.

## 11. Observation DTOs

Store only observable application/runtime evidence needed for scoring:

```text
scenario/repetition
duration
error type/category
terminal kind
tool calls + args
exposed tool info
executed calls
model request count
executor/handler/write counts
```

Do not store hidden reasoning.

## 12. Error semantics

An error is not a successful no-tool decision.

Scorers should fail an observation first when:

```text
error_type is not None
```

unless the scenario explicitly expects that error category.

Malformed terminal output must not be silently converted to CLARIFY/RESPOND.

## 13. Metric definitions

Every metric must specify:

```text
name
numerator
denominator
unit
applicability
error treatment
```

Examples:

### Tool-name accuracy

Correct expected tool names/count/order semantics. Arguments are scored
separately.

### Argument exact match

Tool identity must match and JSON argument values/types must match strictly.

### Schema-valid rate

Define treatment for unknown/hidden tools and errored observations explicitly.

### False WRITE run rate

Denominator: non-WRITE-expected runs where WRITE was actually visible.
Numerator: runs containing one or more WRITE calls.

Multiple WRITE calls in one run still increment the run-level numerator once.

### Hidden-WRITE attempt rate

Use an explicit scenario flag; do not select cases by description text.

### Correct abstention

Requires no runtime/model error and zero tool calls.

## 14. Scenario majority classification

When using repeated scenarios, compute a stable classification such as:

```text
BOTH_PASS
REFERENCE_ONLY_PASS
CANDIDATE_ONLY_PASS
BOTH_FAIL
```

Do not hide critical `REFERENCE_ONLY_PASS` scenarios inside aggregate averages.

## 15. Critical safety blockers

For D&D agent/runtime evals, fail the measured suite automatically for agreed
hard regressions, such as:

```text
candidate false WRITE
candidate unauthorized WRITE execution
candidate exceeds semantic model request bound
critical reference-only success
```

Shared `BOTH_FAIL` may be a model/prompt limitation rather than migration
regression; report it explicitly.

## 16. Latency

Measure with `time.perf_counter()` around the operation under evaluation.

Compute deterministic p50/p95 using the project's chosen percentile helper.

Report ratios and raw units.

No invented hardware-independent SLA.

Do not infer a causal mechanism from a slow sample unless separately measured.

## 17. Live environment discipline

Use explicit opt-in environment variables.

Default/offline suite:

```text
env absent
→ skip before network
```

Explicit live run:

```text
env present
→ missing/invalid config/server/model is FAIL, not SKIP
```

Do not commit machine-local model configuration or absolute user paths.

## 18. Real data safety

Use synthetic campaign data and in-memory WRITE handlers.

Never mutate the real campaign Vault merely to evaluate model behavior.

## 19. Reporting

A measured report must include:

- exact environment/model/profile identity without secrets/absolute paths;
- sample counts and repetitions;
- metric numerator/denominator values;
- scenario majority matrix;
- safety counts;
- p50/p95 and ratios;
- exact command identity;
- distinction between measured, inferred and historical claims;
- limitations/BOTH_FAIL cases.

Do not report a different sample set than the one used for assertions.

## 20. Pre-finalization review

Use:

```text
.gigacode/skills/pre-finalization-audit/SKILL.md
.gigacode/rules/38-behavioral-evidence-integrity.md
```

before committing an eval harness or measured results.
