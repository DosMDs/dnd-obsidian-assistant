---
name: stage-workflow
description: Plan, execute, close, reopen or advance a D&D Session Assistant development stage using DEVELOPMENT_STATUS.md, task IDs, quality gates, correction escalation and ADR discipline. Use when asked to move to the next stage, update project progress, plan the current stage or mark work complete.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "4"
---
# Development stage workflow

## Documentation responsibility split

- `DEVELOPMENT_STATUS.md` = compact canonical **current** roadmap state.
- `docs/stages/NN_*.md` = detailed plan + implementation history + correction
  records + review evidence + completion records.
- `docs/migrations/*.md` = migration-specific detailed history/evidence.

Do not copy full Final Reports or detailed correction narratives into the
compact status file.

Durable project-context documents must not become a competing current-status
source. Historical snapshots in context/docs remain historical; current state
is always read from `DEVELOPMENT_STATUS.md`.

## Start or resume a stage

1. Read `DEVELOPMENT_STATUS.md` for current state.
2. Read the relevant stage/migration detailed document.
3. Inspect current code/tests before assuming task state.
4. Confirm the current stage boundaries and out-of-scope work.
5. Create/update task IDs in `DEVELOPMENT_STATUS.md` only when necessary.

## Execute a task

1. Pick one coherent current-stage task.
2. Inspect affected code/tests.
3. Use Plan Mode for multi-file, architectural, migration, eval or risky work.
4. Define hard acceptance criteria and their planned evidence sources.
5. Implement the smallest valid slice.
6. Add/update tests in the same task.
7. Run targeted checks.
8. Run broader pytest/Ruff gates according to actual final diff/risk.
9. Review the diff.
10. Perform pre-finalization audit.

For behavioral parity/live/eval tasks, also apply:

```text
.gigacode/rules/38-behavioral-evidence-integrity.md
```

For eval/benchmark work use:

```text
.gigacode/skills/eval-harness/SKILL.md
```

## Mark a task complete

A task can be checked off only when:

- required behavior exists;
- required tests/evidence exist;
- every hard acceptance criterion maps to concrete evidence;
- relevant tests pass;
- relevant lint/format checks pass;
- diff was reviewed;
- Final Report claims do not exceed the evidence.

Record unresolved risk/blockers explicitly.

**Status update:**
- `DEVELOPMENT_STATUS.md` → task checkbox/current state only.
- Stage/migration document → detailed completion record/evidence.

## Correction

- Stage/migration document → detailed correction record.
- `DEVELOPMENT_STATUS.md` → keep current task state only.
- Use `correction-review` to classify the owning defect layer.

### Correction-chain escalation

If the same task reaches two or more corrections for the same problem class
(evidence, harness, documentation transcription, gate provenance,
maintainability workaround):

```text
STOP before another local patch
→ analyze repeated pattern
→ check whether an always-on rule/skill is missing the invariant
→ update shared guidance/helper when appropriate
→ then continue the correction
```

Do not allow a long correction chain to become the de facto specification.

## Complete a stage

1. Verify every Definition of Done item.
2. Run required final stage gates, normally including:
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
- Behavioral claims — map to exact assertions/counters/commands.

Invoke or follow `pre-finalization-audit` before every task commit.

For historical stage review:

- Capture implementation review-head BEFORE documentation/status completion commit.
- Do not include the completion commit in the historical implementation range.

### Historical Git comparison procedure

For stage completion review, record in this order:

```text
base SHA
captured implementation head SHA
merge-base
base-only count
head-only count
then optional ahead_by / behind_by labels
```

Definitions:

```text
base..head:
    base_only = git rev-list --count head..base
    head_only = git rev-list --count base..head

git rev-list --left-right --count base...head:
    left  = base-only
    right = head-only

GitHub compare(base, head):
    ahead_by  = head-only
    behind_by = base-only
```

Prefer `base-only` and `head-only` as primary evidence terms because they
are directionally self-explanatory.

## Stage-completion evidence reconciliation

Require stage reviews to re-open/re-read the newly written completion record
**before the completion commit** and reconcile:

```text
SHAs
commit inventory
commit count
changed-file inventory
line counts
test counts
stage statuses
Git direction semantics
behavioral acceptance claims
```

Do not consider the review complete merely because the commands themselves
were correct.

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
4. update/create the next stage plan if needed;
5. keep later stages `NOT STARTED`.

**Status update:**
- `DEVELOPMENT_STATUS.md` → roadmap transition only.
- New stage document → detailed stage plan/tasks.

Do not automatically begin the next roadmap task merely because a Final Report
was produced. A correction/review cycle is complete only after acceptance.

## Reopen

If a supposedly completed gate fails later, reopen the specific task/stage
rather than hiding the failure with downstream workarounds.
