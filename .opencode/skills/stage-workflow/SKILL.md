---
name: stage-workflow
description: Plan, resume, review, close or reopen a D&D Assistant stage or migration task using current status, scoped acceptance criteria and evidence-driven finalization.
---
# Stage workflow

Read [DEVELOPMENT_STATUS.md](../../../DEVELOPMENT_STATUS.md) for current stage/task state and the relevant `docs/stages/*` or `docs/migrations/*` record. Generic PLAN/BUILD, session and Git-finalization procedure is canonical in [task-workflow](../../../docs/development/task-workflow.md); this skill covers stage-specific boundaries only.

- Documentation split: `DEVELOPMENT_STATUS.md` is compact **current** state; `docs/stages/NN_*.md` and `docs/migrations/*.md` hold detailed plan/history/evidence. Do not copy full Final Reports into the status file, and never treat a historical snapshot as current status.
- Start/resume: confirm current stage boundaries and out-of-scope work; inspect current code/tests before assuming task state; create/update task IDs only when necessary.
- Complete a task only when required behavior/tests exist, every hard criterion maps to concrete evidence, gates pass and the diff was reviewed.
- Complete a stage only when every Definition of Done item is verified, final gates pass, architecture boundaries/scope were reviewed, and status/stage docs are updated. Record the implementation review-head BEFORE the docs/status completion commit.
- Git direction evidence: `base_only = git rev-list --count head..base`, `head_only = git rev-list --count base..head`; prefer base-only/head-only terms over ahead_by/behind_by.
- Advancing: mark the current stage DONE and the next IN PROGRESS only after explicit user direction or established policy; keep later stages NOT STARTED; never begin the next roadmap task automatically.
- Reopen the specific task/stage if a completed gate later fails instead of hiding it with downstream workarounds.

Quality gates/evidence and Git finalization live in [quality-and-evidence](../../../docs/development/quality-and-evidence.md) and [task-workflow](../../../docs/development/task-workflow.md).
