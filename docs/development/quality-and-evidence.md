# Quality and evidence

Read this when a task involves tests, evals, parity, acceptance evidence or
quality-gate selection. Workflow/status rules live in
[task-workflow.md](task-workflow.md); decomposition/ratchets in
[maintainability.md](maintainability.md).

## 1. Core invariant

```text
claim strength <= evidence strength
```

- A green test does not prove an unasserted behavior.
- A passing test is not evidence for a claim the test never asserts.
- Select quality gates from the **actual final Git diff**, not the task title.

## 2. Adaptive quality-gate selection

Quality-gate class is determined from the final Git diff and re-evaluated after
all edits.

### Documentation-only task

A task is documentation-only when every final-diff file is Markdown
documentation or agent/development instruction Markdown and none is a
runtime/test fixture, golden/generated input, schema or other machine-consumed
application data.

Typical documentation-only files: `README.md`, `DEVELOPMENT_STATUS.md`,
`docs/**/*.md`, `AGENTS.md`, `.opencode/agents/*.md`,
`.opencode/skills/**/*.md`.

Required by default: inspect the complete final diff; validate
documentation/status consistency; derive and verify the exact changed-file
inventory from Git; `git diff --check`; `git status --short`; normal scoped
commit/push/upstream verification when the task requires Git finalization.

Not required by default: `uv run pytest`, targeted/contract pytest suites,
`uv run ruff check .`, `uv run ruff format --check .`. Do not run Python
test/lint suites merely to manufacture evidence for a Markdown-only edit.

### Exceptions

Run a targeted validator/test even for a `.md` change when the file is consumed
by runtime code, is a test fixture/golden/generated input/schema/executable
specification, a relevant project Markdown/link/schema validator exists, or the
task explicitly requires it. A `.md` extension alone does not grant the
exemption when the file is machine-consumed.

### Code/config/test task

If the final diff contains Python, tests, runtime config, dependencies, schemas
or executable fixtures, use the normal relevant gates, typically:

```text
targeted tests
→ relevant contract/integration tests
→ full pytest when required by task/risk policy
→ Ruff check/format for Python changes
→ git diff --check
```

Do not automatically require every possible suite; select gates relevant to the
changed surfaces and explicit task requirements.

When a task or prompt declares a full-suite gate mandatory for a relevant
non-documentation reason, completion requires pytest exit code 0 with 0 failed
and 0 errors. `"N passed, M skipped, K errors"` is not a passing gate for
`K > 0`.

### Protected append-only migration history

Append-only records under `docs/migrations/*.md` are excluded from Ruff
formatting by repository configuration (`extend-exclude` in `pyproject.toml`).
Do not reformat historical migration sections to satisfy Ruff, and do not
substitute ad-hoc `--exclude` arguments for the canonical formatting gate
(`uv run ruff format --check .`).

### Final-diff reclassification

```text
documentation-only task
→ accidental Python edit appears
→ task is no longer documentation-only
→ restore the accidental edit OR run the appropriate code gates
```

Never claim the documentation-only exemption when the final diff contains
non-documentation changes. If an unexpected machine-consumed file is required
for root cause, treat it as explicit scope expansion and apply the
corresponding gates.

### Final Report gate statement

State the final changed-file inventory, the selected gate class, commands
actually executed, and commands intentionally skipped with the policy reason.
For ordinary documentation-only work, state explicitly:

```text
Full pytest and Ruff were intentionally not run because the final diff
contains documentation Markdown only.
```

Skipped irrelevant gates are not failures. Do not fabricate zero-failure counts
for commands intentionally not run.

## 3. Testing strategy

- Implement tests in the same task as production behavior.
- Prefer unit tests for domain logic, integration tests for real temporary
  Vault operations, contract tests for schemas/tools, and e2e tests for complete
  user flows.
- Calendar conversions and arithmetic should receive property-based tests with
  Hypothesis where useful.
- Ordinary tests must not require a running Ollama instance. Mock Ollama
  network behavior with respx; isolate real checks as explicit smoke tests.
- File tests must use temporary directories and real filesystem operations
  where storage semantics matter.
- Every bug fix should add a regression test when practical.
- For changes involving `sys.modules` or process-global test state, run affected
  suites in relevant execution orders to verify isolation.

## 4. Canonical command identity

Reserved names such as `canonical pytest`, `full pytest`, `full suite` must
refer to the repository-defined canonical command, normally from the repository
root:

```text
uv run pytest
```

A focused subset, unit suite, contract suite, or a command run from a
subdirectory must be named precisely and must not be reported as the canonical
full suite. When environment state affects collection/network behavior, record
the relevant state (e.g. PAIM live env set = explicit live gate; unset =
canonical offline pytest).

## 5. Evidence integrity

### Literal evidence over correlated inference

When a boundary can be measured directly, do not infer it from a correlated
signal. Prohibited examples:

```text
model_requests = 2 if tools_executed else 1
handler_called = len(tool_execution_results)
ToolExecutor_not_called = handler_count == 0
model_loading_caused_latency = first_sample_was_slow
```

Use a direct counter/spy/observation. If literal observation is impossible at a
stable public boundary, label the result explicitly `inferred` and explain why;
inferred evidence must not satisfy a hard criterion that requires literal proof.

Distinguish `literal/measured`, `inferred`, and `documented/historical`. Do not
promote inferred evidence to literal in a Final Report.

### Acceptance → evidence traceability

For tasks with explicit hard acceptance criteria, maintain a map:

```text
acceptance criterion
→ exact code/test/assertion/command that proves it
→ final result
```

Examples: "handler exactly once" needs a literal handler counter around the
real path; "zero ToolExecutor execution" needs an executor/bridge attempt
counter, not only `handler_count == 0`; "tool hidden" needs an assertion against
actual model-visible exposure; "two model requests" needs a counter at the
semantic request boundary. A hard criterion without a concrete evidence source
means the task is `IN PROGRESS`/`BLOCKED`, not `DONE`.

### Evidence transcription

Machine-derived evidence must be obtained from the canonical command against the
final state, never reconstructed mentally. This applies to changed-file
inventories, commit inventories/counts, parent/base/head SHAs, merge base,
ahead/behind, test counts, failed/error/skipped counts, physical line counts,
maintainability values and HEAD/upstream equality. Do not use arithmetic
reconstruction for current line counts when the file can be measured directly.

### Git direction semantics

For `base..head`: `base_only = git rev-list --count head..base`,
`head_only = git rev-list --count base..head`. For
`git rev-list --left-right --count base...head`, left = base-only and right =
head-only. For GitHub-style `compare(base, head)`, `ahead_by` = head-only and
`behind_by` = base-only. Prefer `base-only`/`head-only` as the primary,
self-explanatory terms; never infer these labels from visual position.

Correct command output followed by incorrect Markdown transcription is still a
task failure: run canonical commands → write evidence → re-read it → compare
each value → commit. A file present in the commit but absent from the Final
Report changed-file inventory is a finalization failure.

## 6. Parity, live and measurement discipline

- **Same logical scenario:** parity comparisons require one shared scenario
  definition, equivalent context, equivalent exposed tool definitions and
  equivalent model/profile settings. Do not call mismatched inputs (e.g.
  malformed JSON vs transport exception, hidden vs visible tool, project error
  vs arbitrary `ValueError`) parity unless that difference is the documented
  subject.
- **Reference/candidate identity:** before an expensive parity/eval run, prove
  the compared paths are distinct and intended (e.g. reference FastAgent vs
  candidate PydanticAIFastAgent). Do not infer identity from fixture names; add
  an offline architecture guard when accidental self-comparison is possible.
- **Failure helpers fail closed:** negative-scenario helpers must verify the
  complete safety contract (expected project exception type, model request
  count, executor/bridge attempts, handler effects, no forbidden WRITE, no
  forbidden next round), not merely that "an exception happened". Do not catch
  `BaseException` for ordinary failures or accept arbitrary exceptions as
  parity.
- **Live-gate preflight:** a live test skipped because an env var/service is
  absent proves nothing about fixture construction, constructor signatures,
  concrete framework type requirements, test-double contracts, wrapper
  transparency or scoring. Provide offline preflight tests before the first
  expensive live run; opt-in live runs then validate network/provider behavior.
- **Wrapper transparency:** a test wrapper/decorator around a framework object
  must preserve public behavior that affects execution (concrete/base type
  contract, model/provider identity, settings/profile, request/exception
  semantics, resource lifecycle where relevant). Do not loosen production
  `isinstance`/validation checks to admit a weak test double; add offline
  equivalence tests.
- **Measured dataset ownership:** one clearly owned measured sample set per
  layer: warm up first, collect measured samples exactly once, freeze the
  observations, and let all classifications/metrics/latency reports reuse them.
  Do not rerun the model to compute aggregates, and do not rely on pytest test
  ordering for warm-up. Assert sample counts and key uniqueness when a measured
  dataset is intended to execute once.
- **Metric contract:** every metric defines numerator, denominator, unit
  (run/call/turn/sample), error treatment and applicability conditions. Metric
  labels must be tied to identity/position, never to observed numerator values.
  A runtime/model error is never a successful abstention.
- **Performance evidence:** measure with direct timers around the intended
  operation. Do not infer causality from timing alone, and do not invent a
  hardware-independent SLA the project has not defined.
- **Test doubles:** a double must model the contract the test requires and fail
  loudly on unexpected use (scripted gateways fail on an unexpected extra
  request; hidden-tool fixtures prove absence; fake repositories satisfy the
  real return/error contract).

PAIM-specific runtime/parity procedure is defined by its migration record and
the future OC-03 skill; do not weaken this evidence discipline for it.

## 7. Test-harness isolation

- Test bugs belong to test infrastructure. Do not weaken or broaden production
  behavior merely to survive collection order, import reloads, monkeypatch
  leakage, `sys.modules` churn, fixture ordering or test-only global state. Fix
  the harness, not the production contract.
- Tests that modify process-global state (`sys.modules`, `os.environ`, cwd,
  locale, module globals, registries/singletons, warnings filters) own its
  restoration via fixture or context-manager cleanup.
- Preferred fixture scope: test-local/`usefixtures` → class-scoped opt-in →
  module-level opt-in/autouse (only when every test in the module needs it) →
  repository-wide autouse (only with explicit demonstrated repository-wide
  need). Repository-wide autouse is not the default.
- If substantially identical cleanup appears in 3+ modules, create one reusable
  opt-in helper/fixture. Do not DRY ordinary scenario assertions until meaning
  becomes opaque.
- Treat as protected scope: `tests/conftest.py`, `tests/integration/conftest.py`,
  `tests/contract/test_test_harness_policy.py`, module-restoration allowlists,
  test-harness allowlists and global autouse fixtures. A normal
  feature/provider/domain task must not change them merely to make its own tests
  pass. If a local task appears to require changing protected harness
  infrastructure without authorization, **STOP**, report the requirement, and
  separate it into a correction/maintenance task (a task explicitly about
  harness behavior may modify it).

## 8. Hard-limit integrity

A task is not complete if it makes itself pass by weakening a maintainability
ratchet or adding a convenience exception without explicit authorization. If a
new/changed module exceeds its hard limit: split/deduplicate/refactor or report
a blocker — never raise/add an allowlist ceiling. See
[maintainability.md](maintainability.md).
