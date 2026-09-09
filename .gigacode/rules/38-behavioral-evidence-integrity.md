---
apply: ALWAYS
mode: ALL
---

# Behavioral evidence and measurement integrity

This rule applies whenever a task claims behavioral parity, safety evidence,
provider/framework qualification, live smoke results, eval metrics, performance
measurements, or a Final Report derived from tests/commands.

## 1. Claim-to-evidence invariant

A completion claim must not be stronger than the executable or machine-derived
evidence that supports it.

Examples:

```text
"handler called exactly once"
→ requires a literal handler counter/spy that delegates to the real handler path

"ToolExecutor was never reached"
→ requires a ToolExecutor/bridge attempt counter, not only handler_count == 0

"tool was hidden"
→ requires assertion against the actual model-visible exposure snapshot/list

"two model requests"
→ requires counting at the semantic model request boundary

"same scenario"
→ both systems must be driven by one shared logical scenario specification

"canonical/full suite"
→ requires the canonical command defined by repository policy
```

A green test is not evidence for a claim that the test never asserts.

## 2. Literal evidence over correlated inference

When a boundary can be measured directly, do not infer it from a correlated
signal.

Prohibited examples:

```text
model_requests = 2 if tools_executed else 1
handler_called = len(tool_execution_results)
ToolExecutor_not_called = handler_count == 0
model_loading_caused_latency = first_sample_was_slow
```

Use a direct counter/spy/observation instead.

If literal observation is impossible at a stable public boundary, label the
result explicitly as `inferred` and explain why. Inferred evidence must not be
used to satisfy a hard acceptance criterion that requires literal proof.

## 3. Same-logical-scenario parity

Reference/candidate parity must compare equivalent logical inputs.

Required:

- one shared scenario definition/ground truth;
- equivalent application context;
- equivalent exposed tool definitions;
- equivalent model/profile settings where required;
- equivalent expected failure mechanism when error parity is claimed.

Do not call these parity:

```text
reference malformed JSON vs candidate transport exception
reference assistant text+tool vs candidate tool-only
reference hidden tool vs candidate visible tool
reference ModelError vs candidate arbitrary ValueError
```

unless the difference itself is the explicitly documented subject of the test.

## 4. Failure-helper fail-closed rule

Shared test helpers for negative scenarios must verify the complete safety
contract, not merely that "an exception happened".

Required where applicable:

- expected project exception type/category;
- semantic model request count;
- executor/bridge attempts;
- handler effects;
- forbidden WRITE effects;
- no forbidden next model round.

Do not:

- catch `BaseException` for ordinary application failures;
- accept arbitrary exceptions as parity;
- return early after observing two failures before checking side effects;
- allow an errored no-tool observation to count as successful abstention.

## 5. Reference/candidate identity

Before an expensive parity/eval run, prove that the two compared paths are
actually distinct and are the intended systems.

Examples:

```text
reference FastAgent / AgentLoop / native ModelGateway
candidate PydanticAIFastAgent / PydanticAIAgentRuntime / Pydantic Model
```

Add an offline architecture guard when accidental self-comparison is possible.

Do not infer identity from fixture names such as `reference_runtime`.

## 6. Live-gate preflight

A live test that is skipped because an environment variable is absent does not
validate:

- fixture construction;
- constructor signatures;
- concrete framework type requirements;
- repository/service test-double contracts;
- wrapper transparency;
- metric/scoring behavior.

Before the first expensive live run, provide offline tests that exercise the
object graph and measurement harness far enough to catch those failures.

Explicit opt-in live runs may then validate network/provider behavior.

## 7. Wrapper/decorator transparency

A test wrapper around a framework/runtime object must preserve every public
property that can influence behavior.

For model wrappers, inspect the pinned framework version and preserve/delegate
as applicable:

```text
concrete/base type contract
model_name
system/provider identity
base_url
settings
profile
request semantics
exception semantics
resource lifecycle
```

Do not modify production type checks merely to accommodate a test wrapper.

Add offline wrapper-equivalence tests before live use.

## 8. Measured dataset ownership

An eval/benchmark must have one clearly owned measured sample set per layer.

Required:

```text
warm-up first
→ measured sample collection exactly once
→ freeze observations in memory
→ all scenario classifications/metrics/latency reports reuse those observations
```

Do not rerun the real model to compute aggregate metrics after per-scenario
measurement.

Warm-up must not rely on pytest test ordering and must not enter measured
samples.

## 9. Metric-contract discipline

Every metric must define:

- numerator;
- denominator;
- unit (run/call/turn/sample);
- error treatment;
- applicability conditions.

Examples:

```text
false WRITE rate
→ run-level numerator over non-WRITE-expected runs where WRITE was visible

schema-valid rate
→ explicit policy for errored runs and hidden/unknown tools

correct abstention
→ runtime/model error is never a successful abstention
```

Metric labels must be tied to metric identity/position, never to observed
numerator values.

## 10. Performance evidence

Measure performance with direct timers around the intended operation.

Do not infer causality from timing alone. For example, a slow first request may
be consistent with cold/warm-up effects but does not prove model loading unless
that mechanism is separately instrumented.

Do not invent a hardware-independent SLA unless the project already defines
one.

## 11. Hard-limit integrity

A task is not complete if it makes itself pass by weakening a maintainability
ratchet or adding a convenience exception without explicit authorization.

If a new/changed module exceeds its hard limit:

```text
split / deduplicate / refactor / report blocker
```

not:

```text
raise/add allowlist ceiling
```

## 12. Completion traceability

For tasks with explicit hard acceptance criteria, maintain an acceptance map:

```text
criterion
→ exact test/assertion/command
→ final result
```

Before marking `DONE`, every hard criterion must have a concrete evidence
source. Missing evidence means `IN PROGRESS` or `BLOCKED`, not `DONE`.

## 13. Correction-chain escalation

If the same task requires two or more correction passes for the same class of
problem (evidence weakness, harness identity, measurement, final-report
transcription, maintainability workaround), stop before adding another local
workaround.

Perform a meta-review:

```text
repeated defect pattern
→ missing reusable invariant?
→ update rule/skill/test helper if appropriate
→ then continue correction
```

The purpose is to prevent long correction chains caused by the same missing
workflow constraint.
