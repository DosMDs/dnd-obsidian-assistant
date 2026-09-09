---
name: pre-finalization-audit
description: Perform the mandatory evidence-driven final audit before committing or pushing an implementation, correction, maintenance task, stage completion, live qualification or eval result.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "3"
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
10. Build an acceptance-to-evidence map for every hard criterion.
11. Run required targeted tests.
12. Run mandatory full gates where the task requires them.
13. Require pytest 0 failed / 0 errors for mandatory full-suite gate.
14. Run Ruff / format / diff-check as required.
15. Re-check status and diff AFTER tests and formatters.
16. Run the adversarial evidence audit below.
17. Build evidence from actual outputs.
18. Update docs/status from that evidence.
19. Re-read and reconcile the newly written evidence.
20. Commit only intended files.
21. Push normally.
22. Verify `HEAD == upstream`.
23. Verify clean working tree (`git status --short`).
24. Produce Final Report from committed state.

## Hard STOP conditions

- unexpected file not understood;
- failed mandatory gate;
- nonzero pytest errors;
- legacy ceiling increase without authorization;
- new maintainability exception added merely to make the task pass;
- hard acceptance criterion with no concrete evidence source;
- Final Report/docs claim stronger behavior than executable evidence;
- dirty final working tree;
- `HEAD != upstream` after expected push.

## Acceptance-to-evidence closure

For each explicit acceptance requirement write/review a compact map:

```text
criterion
→ literal test/assertion/command
→ result
```

Examples:

```text
handler exactly once
→ handler invocation counter around real path

zero ToolExecutor attempts
→ executor/bridge attempt counter

model request count == 2
→ semantic request-boundary counter

tool hidden
→ actual model-visible exposure assertion

full canonical suite green
→ exact root `uv run pytest` output
```

If the evidence is only inferred, label it `inferred` and do not use it to
close a hard criterion requiring literal proof.

Canonical rule:

```text
.gigacode/rules/38-behavioral-evidence-integrity.md
```

## Adversarial evidence audit

Before finalization, ask whether the new tests/report could still pass/be
written if the claimed behavior were false.

Required checks when relevant:

```text
1. Could a negative test pass because it accepts any exception?
2. Could it pass after executor invocation but before the handler?
3. Is a "hidden" tool actually absent from the model-visible exposure?
4. Are reference and candidate really different runtime/provider paths?
5. Are both sides driven by the same logical scenario/failure mechanism?
6. Is a reported count measured literally or inferred from another effect?
7. Did an env-gated skip hide a broken live fixture/constructor?
8. Does a framework wrapper preserve concrete type + settings/profile semantics?
9. Are warm-up calls actually before measurement?
10. Are aggregate metrics computed from the exact same frozen samples?
11. Is an errored no-tool run accidentally counted as abstention/success?
12. Does the report claim a causal explanation that timing alone cannot prove?
13. Did a test/production file cross its hard line limit?
14. Was an allowlist/ratchet edited to accommodate the current task?
15. Does the named "canonical/full suite" correspond to the actual canonical command?
```

A yes/unknown answer that affects a hard criterion blocks finalization.

## Evidence reconciliation

Before committing, perform this mandatory workflow:

1. Run canonical evidence commands.
2. Update docs/status evidence from actual command output.
3. Re-read all newly written evidence blocks.
4. Compare every machine-derived value with the source command output.
5. Compare every behavioral claim with the test/assertion that proves it.
6. Search for stale placeholders and contradictory status.
7. Inspect final diff.
8. Only then commit.

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

## Canonical command provenance

When reporting a suite/gate, preserve the identity of the command that
produced it.

Reserved wording:

```text
canonical pytest / full pytest / full suite
```

should normally mean:

```text
repository root
live-only env variables unset as required
uv run pytest
```

Focused/unit/contract subsets must be named as subsets.

For live gates report the explicit opt-in command/environment separately from
the offline canonical suite.

## Invariant

Do not commit first and audit afterward.
