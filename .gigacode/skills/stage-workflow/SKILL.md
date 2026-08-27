---
name: stage-workflow
description: Plan, execute, close, reopen or advance a D&D Session Assistant development stage using DEVELOPMENT_STATUS.md, task IDs, quality gates and ADR discipline. Use when asked to move to the next stage, update project progress, plan the current stage or mark work complete.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "1"
---
# Development stage workflow

## Start or resume a stage

1. Read `DEVELOPMENT_STATUS.md`.
2. Read the relevant stage document under `docs/stages/` if present.
3. Inspect current code/tests before assuming task state.
4. Confirm the current stage boundaries and out-of-scope work.
5. Create/update task IDs in `DEVELOPMENT_STATUS.md` only when necessary.

## Execute a task

1. Pick one coherent current-stage task.
2. Inspect affected code/tests.
3. Use Plan Mode for multi-file, architectural or risky work.
4. Implement the smallest valid slice.
5. Add/update tests in the same task.
6. Run targeted checks.
7. Run broader pytest/Ruff gates when feasible.
8. Review the diff.

## Mark a task complete

A task can be checked off only when:
- required behavior exists;
- required tests exist;
- relevant tests pass;
- relevant lint/format checks pass;
- diff was reviewed.

Record unresolved risk/blockers explicitly.

## Complete a stage

1. Verify every Definition of Done item.
2. Run:
   - `uv run pytest`
   - `uv run ruff check .`
   - `uv run ruff format --check .`
3. Review architecture boundaries and scope.
4. Update stage status/dates in `DEVELOPMENT_STATUS.md`.
5. Do not start the next stage automatically.

## Advance a stage

Only after explicit user direction or an already-established project policy authorizing the transition:

1. mark the completed stage `DONE`;
2. mark the next stage `IN PROGRESS`;
3. record start/completion dates;
4. update/create the next `docs/stages/...` plan if needed;
5. keep later stages `NOT STARTED`.

## Reopen

If a supposedly completed gate fails later, reopen the specific task/stage rather than hiding the failure with downstream workarounds.
