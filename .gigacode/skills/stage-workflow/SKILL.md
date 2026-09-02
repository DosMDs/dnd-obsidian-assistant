---
name: stage-workflow
description: Plan, execute, close, reopen or advance a D&D Session Assistant development stage using DEVELOPMENT_STATUS.md, task IDs, quality gates and ADR discipline. Use when asked to move to the next stage, update project progress, plan the current stage or mark work complete.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "2"
---
# Development stage workflow

## Documentation responsibility split

- `DEVELOPMENT_STATUS.md` = compact canonical **current** roadmap state.
- `docs/stages/NN_*.md` = detailed plan + implementation history + correction
  records + review evidence + completion records.

Do not copy full Final Reports or detailed correction narratives into the
compact status file.

## Start or resume a stage

1. Read `DEVELOPMENT_STATUS.md` for current state.
2. Read the relevant `docs/stages/NN_*.md` for detailed plan/history.
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

**Status update:**
- `DEVELOPMENT_STATUS.md` → task checkbox/current state only.
- Stage document (`docs/stages/NN_*.md`) → detailed completion record/evidence.

## Correction

- Stage document (`docs/stages/NN_*.md`) → detailed correction record.
- `DEVELOPMENT_STATUS.md` → keep current task state only.

## Complete a stage

1. Verify every Definition of Done item.
2. Run:
   - `uv run pytest`
   - `uv run ruff check .`
   - `uv run ruff format --check .`
3. Review architecture boundaries and scope.
4. Update stage status/dates in `DEVELOPMENT_STATUS.md`.
5. Write detailed final review/completion record into the stage document.
6. Do not start the next stage automatically.

## Evidence collection

Before completing any task or stage:

- Changed-file inventory — derive from Git (`git diff --name-status`).
- Commit inventory — derive from Git history (`git log`).
- Test counts — derive from final command output.
- Line counts — derive from final repository state.
- Historical actions — verify from commit/diff, not memory.

Invoke or follow `pre-finalization-audit` before every task commit.

For historical stage review:

- Capture implementation review-head BEFORE documentation/status completion commit.
- Do not include the completion commit in the historical implementation range.

## Git finalization (self-SHA rule)

Before task commit:

- finish all status/stage-doc updates;
- use `(reported in Final Report)` for the current commit SHA.

After task commit:

- no repository mutation for self-reporting;
- report SHA externally in Final Report.

## Advance a stage

Only after explicit user direction or an already-established project policy
authorizing the transition:

1. mark the completed stage `DONE`;
2. mark the next stage `IN PROGRESS`;
3. record start/completion dates;
4. update/create the next `docs/stages/...` plan if needed;
5. keep later stages `NOT STARTED`.

**Status update:**
- `DEVELOPMENT_STATUS.md` → roadmap transition only.
- New stage document → detailed stage plan/tasks.

## Reopen

If a supposedly completed gate fails later, reopen the specific task/stage
rather than hiding the failure with downstream workarounds.