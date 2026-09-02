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

```
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

```
unexpected file
    -> required for root cause?
        yes -> explicitly classify/document scope expansion
        no  -> remove unintended edit
```

Do NOT silently widen scope.

If scope expansion represents another independent defect or task:

```
STOP and report it instead of absorbing it.
```

## 3. Final Report evidence

Final Reports must be evidence-driven.

The following MUST be obtained from final repository/command state, never
reconstructed from memory:

- changed files
- commit SHA
- parent/starting SHA
- test counts
- failed/error counts
- Ruff result
- line counts
- maintainability values
- HEAD/upstream equality
- working-tree cleanliness

Explicit invariant:

```
A file present in the commit but absent from the Final Report changed-file
inventory is a finalization failure.
```

Historical claims must be checked against actual historical Git state.

Do not write that a restore, edit, or test occurred if it did not occur.

## 4. Scope expansion rule

If during implementation a task discovers an unrelated defect or missing
feature:

- document the discovery;
- do NOT automatically fix it;
- report it to the user for prioritization.

Do not absorb unrelated work into the current task scope.