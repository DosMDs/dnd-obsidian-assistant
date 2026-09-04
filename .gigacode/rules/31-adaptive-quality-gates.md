---
apply: ALWAYS
mode: ALL
---

# Adaptive quality gates

Quality gates MUST be selected from the final actual Git diff, not merely
from the task title or intended scope.

## 1. Documentation-only task

A task is documentation-only when every changed file in the final diff is
Markdown documentation or agent/development instruction Markdown and none of
those files are runtime/test fixtures, generated inputs, schemas, or other
machine-consumed application data.

Typical examples:

- `README.md`
- `DEVELOPMENT_STATUS.md`
- `docs/**/*.md`
- `GIGACODE.md`
- `.gigacode/rules/*.md`
- `.gigacode/skills/**/*.md`

For a documentation-only task:

Required:

- inspect the complete final diff;
- validate documentation/status consistency relevant to the task;
- derive and verify the exact changed-file inventory from Git;
- run `git diff --check`;
- run `git status --short` before finalization;
- perform the normal scoped commit/push/upstream verification when the task
  requires Git finalization.

Not required by default:

- `uv run pytest`
- targeted pytest suites
- contract pytest suites
- `uv run ruff check .`
- `uv run ruff format --check .`

Do not run Python test/lint suites merely to manufacture evidence for a
Markdown-only edit.

## 2. Exceptions

Run a targeted validator/test even for a `.md` change when:

- the Markdown file is consumed by runtime code;
- it is a test fixture, golden file, generated input, schema, or executable
  specification;
- a project-specific Markdown/link/schema validator exists and is relevant;
- the task explicitly requires the validation for a concrete technical reason.

The task and Final Report must state the reason.

A `.md` extension alone does not make a file documentation-only when the file
is machine-consumed by the application, tests, build tooling, or release
process.

## 3. Code/config/test task

If the final diff contains Python code, tests, runtime configuration,
dependencies, schemas, executable fixtures, or other machine-consumed files,
use the normal relevant quality gates.

Typical sequence:

```text
targeted tests
→ relevant contract/integration tests
→ full pytest when required by task/risk policy
→ Ruff check/format for Python changes
→ git diff --check
```

Do not automatically require every possible suite. Select gates that are
relevant to the changed surfaces and explicit task requirements.

## 4. Final-diff reclassification

Gate classification must be re-evaluated after all edits.

Example:

```text
documentation-only task
→ accidental Python edit appears
→ task is no longer documentation-only
→ restore the accidental edit OR run the appropriate code quality gates
```

Never claim the documentation-only exemption when the final Git diff contains
non-documentation changes.

If an unexpected machine-consumed file is required for the root cause, treat
that as explicit scope expansion and apply the corresponding gates.

## 5. Final Report

The Final Report must state:

- final changed-file inventory;
- selected quality-gate class;
- commands actually executed;
- commands intentionally skipped under this policy and why.

For ordinary documentation-only work, explicitly report:

```text
Full pytest and Ruff were intentionally not run because the final diff
contains documentation Markdown only.
```

Skipped irrelevant gates are not failures.

## 6. Prompt-generation rule

Task prompts must not mechanically include full pytest/Ruff for a task whose
expected final diff is documentation-only.

Instead, prompts should require:

```text
classify final diff
→ apply the appropriate gate class
→ reclassify after edits
```

If the prompt expected documentation-only scope but the final diff contains a
code/test/runtime file, the documentation-only exemption no longer applies.
