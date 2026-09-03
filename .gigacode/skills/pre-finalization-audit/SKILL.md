---
name: pre-finalization-audit
description: Perform the mandatory evidence-driven final audit before committing or pushing an implementation, correction, maintenance task, or stage completion.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "2"
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

## Evidence reconciliation

Before committing, perform this mandatory workflow:

1. Run canonical evidence commands.
2. Update docs/status evidence from actual command output.
3. Re-read all newly written evidence blocks.
4. Compare every machine-derived value with the source command output.
5. Search for stale placeholders and contradictory status.
6. Inspect final diff.
7. Only then commit.

### Placeholder/stale-evidence scan

Review newly changed documentation for terms such as:

```text
TBD
TODO
placeholder
N passed
N lines
reported later
NOT STARTED
IN PROGRESS
DONE
ahead_by
behind_by
```

Do not globally forbid all these strings. Instead verify every occurrence is
intentional and contextually correct.

For current self-commit SHA: do not write the current commit's future SHA
into the same commit.

## Invariant

Do not commit first and audit afterward.