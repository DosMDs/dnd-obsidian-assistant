---
name: pre-finalization-audit
description: Perform the mandatory evidence-driven final audit before committing or pushing an implementation, correction, maintenance task, or stage completion.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "1"
---

# Pre-finalization audit

## Workflow

1. Recall or capture starting SHA and intended scope.
2. Inspect `git status`.
3. Derive changed files from Git (`git diff --name-status`).
4. Compare changed files with intended task scope.
5. Inspect every unexpected file.
6. Review the complete diff (`git diff`).
7. Check no architecture boundary was weakened.
8. Check no production workaround exists solely for tests.
9. Check hard limits and legacy ratchets did not increase.
10. Run required targeted tests.
11. Run mandatory full gates where the task requires them.
12. Require pytest 0 failed / 0 errors for mandatory full-suite gate.
13. Run Ruff / format / diff-check as required.
14. Re-check status and diff AFTER tests and formatters.
15. Build evidence from actual outputs.
16. Commit only intended files.
17. Push normally.
18. Verify `HEAD == upstream`.
19. Verify clean working tree (`git status --short`).
20. Produce Final Report from committed state.

## Hard STOP conditions

- unexpected file not understood;
- failed mandatory gate;
- nonzero pytest errors;
- legacy ceiling increase without authorization;
- dirty final working tree;
- `HEAD != upstream` after expected push.

## Invariant

Do not commit first and audit afterward.