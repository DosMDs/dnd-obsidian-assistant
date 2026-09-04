---
apply: ALWAYS
mode: AGENT
---

# Task scope and evidence invariants

## 1. Starting-state capture

Before modifying a task:

- capture starting HEAD (commit SHA);
- capture branch name;
- capture `git status --short`;
- identify expected/allowed file scope from the task description.

A dirty working tree must not be silently absorbed into the task.

Pre-existing changes must be:

- identified;
- classified;
- preserved;

unless the task explicitly authorizes restoration or removal.

Never silently discard pre-existing changes.

## 2. Intended diff

Every task has an **intended diff** — the set of files the task is expected
to create or modify.

Before commit:

```text
actual changed-file list MUST be derived from Git
and compared against the intended task scope.
```

Use equivalent commands such as:

- `git status --short`
- `git diff --name-status`
- `git diff --stat`
- `git diff`

Every unexpected changed file must be inspected.

Required decision for each unexpected file:

```text
unexpected file
    -> required for root cause?
        yes -> explicitly classify/document scope expansion
        no  -> remove unintended edit
```

Do NOT silently widen scope.

If scope expansion represents another independent defect or task:

```text
STOP and report it instead of absorbing it.
```

## 2.1. Final-diff quality-gate classification

Quality-gate class is determined from the **actual final Git diff**, not only
from the task title or originally intended scope.

Canonical rule:

```text
.gigacode/rules/31-adaptive-quality-gates.md
```

Required flow before finalization:

```text
derive final changed-file inventory from Git
→ classify documentation-only vs machine-consumed/code/test/runtime changes
→ select relevant gates
→ run gates
→ re-read final diff
→ confirm classification still applies
```

For ordinary documentation-only Markdown changes, full pytest and Ruff are
not required by default. Their intentional omission must be reported as a
policy-based skip, not as missing evidence.

If a non-documentation or machine-consumed file appears in the final diff,
reclassify the task and either restore the unintended edit or run the
corresponding code/test quality gates.

## 3. Final Report evidence

Final Reports must be evidence-driven.

The following MUST be obtained from final repository/command state, never
reconstructed from memory:

- changed files
- commit SHA
- parent/starting SHA
- test counts when tests were required/executed
- failed/error counts when tests were required/executed
- Ruff result when Ruff was required/executed
- line counts when relevant
- maintainability values when relevant
- selected quality-gate class
- intentionally skipped gates and policy reason
- HEAD/upstream equality
- working-tree cleanliness

Explicit invariant:

```text
A file present in the commit but absent from the Final Report changed-file
inventory is a finalization failure.
```

Historical claims must be checked against actual historical Git state.

Do not write that a restore, edit, test, or quality gate occurred if it did
not occur.

For documentation-only tasks it is valid and preferred to state explicitly:

```text
Full pytest and Ruff were intentionally not run because the final diff
contains documentation Markdown only.
```

Do not fabricate zero-failure counts for commands that were intentionally
not run.

## 4. Scope expansion rule

If during implementation a task discovers an unrelated defect or missing
feature:

- document the discovery;
- do NOT automatically fix it;
- report it to the user for prioritization.

Do not absorb unrelated work into the current task scope.

## 5. Evidence transcription invariant

Machine-derived evidence must not be recomputed mentally when the canonical
command can produce it.

This applies to at least:

```text
changed-file inventories
commit inventories
commit counts
parent/base/head SHAs
merge base
ahead/behind
test counts
failed/error/skipped counts
physical line counts
maintainability values
HEAD/upstream equality
```

### Canonical-command requirement

Run the canonical command against the final state and copy its value
directly into documentation/evidence.

Explicitly prohibited: using arithmetic reconstruction for current line
counts:

```text
previous_count + additions - deletions
```

when:

```python
len(path.read_bytes().splitlines())
```

can be run against the current file.

Historical calculations may use Git if the historical file itself cannot
otherwise be directly inspected, but the methodology must be explicit.

### Evidence reconciliation after writing

Correct command output followed by incorrect Markdown transcription is
still a task failure.

Required workflow:

```text
run canonical evidence commands
→ write docs/status evidence
→ re-read newly written evidence
→ compare each machine-derived value against command output
→ only then commit
```

This applies to implementation tasks, corrections, maintenance tasks and
stage completion reviews.

For documentation-only tasks, "canonical evidence commands" means the
commands relevant to that gate class. Do not add irrelevant pytest/Ruff runs
solely because this reconciliation rule exists.

## 6. Git direction semantics

For `base..head`:

```text
base_only = git rev-list --count head..base
head_only = git rev-list --count base..head
```

For `git rev-list --left-right --count base...head`:

```text
left  = base-only
right = head-only
```

For GitHub-style `compare(base, head)`:

```text
ahead_by  = head-only
behind_by = base-only
```

Never infer these labels from visual position alone.

Prefer `base-only` and `head-only` as primary evidence terms because they
are directionally self-explanatory.
