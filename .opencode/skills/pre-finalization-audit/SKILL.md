---
name: pre-finalization-audit
description: Perform the mandatory evidence-driven final audit before committing or pushing an implementation, correction, documentation, maintenance or eval task.
---
# Pre-finalization audit

Mandatory audit before commit/push, run from the actual final Git state; never commit first and audit afterward. Workflow/Git rules are in [task-workflow](../../../docs/development/task-workflow.md); gate selection and evidence rules in [quality-and-evidence](../../../docs/development/quality-and-evidence.md); ratchets in [maintainability](../../../docs/development/maintainability.md).

1. Recall starting SHA and intended scope.
2. `git status`; derive changed files from Git (`git diff --name-status`) and compare with intended scope; inspect every unexpected file.
3. Review the complete diff; confirm no architecture boundary was weakened and no production workaround exists solely for tests.
4. Confirm hard limits and legacy ratchets did not increase and no new exception was added to make the task pass.
5. Build an acceptance→evidence map (`criterion → literal test/assertion/command → result`); label inferred evidence and never use it to close a hard criterion.
6. Run the gates selected from the final diff; a mandatory full-suite gate requires pytest exit 0 with 0 failed / 0 errors.
7. Re-check status and diff AFTER tests/formatters.
8. Adversarial evidence audit: could the tests/report still pass if the claimed behavior were false? Check arbitrary-exception acceptance, executor-vs-handler boundary, actual model-visible exposure, distinct reference/candidate paths, literal vs inferred counts, env-gated skips hiding broken fixtures, wrapper type/settings preservation, warm-up before measurement, frozen samples reused, an errored run counted as abstention, timing-only causation, and canonical-command identity.
9. Reconcile newly written evidence against command output; scan for stale placeholders; then commit only intended files, push normally, verify `HEAD == upstream` and a clean tree, and produce the Final Report from committed state.

Hard STOP: unexplained unexpected file, failed mandatory gate, nonzero pytest errors, unauthorized ratchet change, hard criterion with no literal evidence, claims stronger than evidence, dirty final tree, or `HEAD != upstream` after the expected push.
