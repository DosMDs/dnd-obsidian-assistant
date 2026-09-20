# ADR-0009: Current-MVP release scope defers accepted live-model qualification

- **Status:** Accepted
- **Date:** 2026-09-20
- **Task:** `S14-10-RELEASE-SCOPE-DECISION`

## Context

Stage 14 (Evals / Hardening) delivered all deterministic/software hardening
requirements and qualified them (`SOFTWARE_HARDENING_PASS`). One accepted
Stage-14 deliverable — `S14-07 — Opt-in Live Ollama Model Baseline + Latency
Metrics + Frozen Report` — required an **accepted canonical live model
baseline** measured through the frozen product-v1 / single-pass-v1 / agent-v3
contract.

That requirement is `BLOCKED` / `UNSATISFIED`. Three **distinct** local Ollama
candidates were each measured exactly once against the unchanged frozen
contract, and none was accepted:

```text
qwen3.5:9b        accepted=false  2 runtime errors (EVAL-P1-007, EVAL-P1-009)
                                  SYSTEM SAFETY PASS; false-write 0/3/0.0 PASS
ministral-3:8b    accepted=false  4 runtime errors (EVAL-P1-002/004/006/010)
                                  SYSTEM SAFETY PASS; false-write 0/3/0.0 PASS
qwen3:14b         accepted=false  0 runtime errors; SYSTEM SAFETY FAIL
                                  (1 unauthorized WRITE handler execution at
                                  EVAL-P1-010); false-write 0/3/0.0 PASS
```

All three measured attempts are consumed and must never be rerun. No accepted
canonical live-model baseline exists. Stage-14 closure and release were
therefore recorded `RELEASE_BLOCKED` by `S14-09`, which was correct at the time.

`S14-07-RES-01` (read-only PLAN) established that the only distinct installed
candidate beyond the consumed set (`huihui_ai/qwen3.5-abliterated:35b`) does not
satisfy the bounded Path-A gating criteria (same model family as a consumed
candidate, abliterated, no profile, ~23.87 GB with unknown practicality, and no
concrete evidence it addresses the three distinct observed failure modes).

The product owner has explicitly authorized a **prospective** change to the
current MVP release scope: the accepted-live-baseline requirement is removed
from the **current MVP release closure criteria** and carried forward as future
work. This is a scope decision, not a measurement result.

## Decision

1. The **accepted canonical live-model baseline is removed from the current MVP
   release closure criteria**. The current MVP release is `RELEASE_READY` under
   the newly authorized prospective release scope.

2. Stage 14 is `DONE` under that prospective release scope. All deterministic
   and software hardening requirements remain closed; the only carve-out is the
   deferred accepted live-model baseline.

3. The historical `S14-07` requirement is recorded as:

   ```text
   status      = BLOCKED / UNSATISFIED
   disposition = DEFERRED_TO_FUTURE_SCOPE
   ```

   `DEFERRED_TO_FUTURE_SCOPE` is **descriptive disposition metadata**, not a
   fifth canonical task status. The canonical status vocabulary remains exactly
   `NOT STARTED` / `IN PROGRESS` / `BLOCKED` / `DONE`.

4. Future accepted-live-model qualification is owned by a **non-stage post-MVP
   milestone concept**:

   ```text
   v0.5.0 — Accepted Live Model Baseline
   ```

   No Stage 15 or other numbered stage is created. No new `NOT STARTED` task is
   created now; the future milestone requirement will be created only when that
   milestone is actually defined.

5. This ADR records a **prospective** release-scope decision. It is not, and must
   never be read as, a retroactive acceptance or reinterpretation of any
   measured candidate.

## Historical qualification result vs prospective release-scope decision

These two facts are independent and both remain true:

```text
HISTORICAL QUALIFICATION RESULT (unchanged, frozen)
  Three distinct live candidates were measured once.
  None met the frozen S14-07 acceptance contract.
  All three remain accepted=false.
  No accepted canonical live-model baseline currently exists.
  S14-07 is BLOCKED / UNSATISFIED.

PROSPECTIVE RELEASE-SCOPE DECISION (this ADR)
  The accepted-live-baseline requirement is removed from the current MVP
  release closure criteria and carried to a post-MVP milestone.
  Stage 14 is DONE under that scope; the current MVP release is RELEASE_READY.
```

The decision does not alter the qualification result. It changes only which
requirements the current MVP release is measured against, going forward.

## Preserved invariants (explicitly unchanged)

This ADR explicitly preserves:

- all three frozen failed-candidate artifacts, byte-for-byte
  (`docs/evidence/evals/s14-07-product-v1-ollama-baseline.json`,
  `…-ministral3-8b-candidate.json`, `…-qwen3-14b-candidate.json`) and their
  bound contract tests;
- the original `S14-07` acceptance criteria;
- no retroactive acceptance of any candidate;
- no threshold relaxation;
- the product-v1 dataset, single-pass-v1 sample plan, agent-v3 prompt and all
  scoring / write-accounting semantics;
- the literal historical `RELEASE_BLOCKED` verdicts in the Stage-14 evidence
  record as correct at the time they were recorded.

## Consequences and limitations

- **`RELEASE_READY` does not mean a canonical local live model has been
  validated.** It means the current MVP release is no longer gated on the
  accepted live-model baseline, which remains deferred and unsatisfied.
- The project still has **no** accepted canonical live-model baseline. Any
  claim that a local live model has been qualified would be false.
- The previously recorded `RELEASE_BLOCKED` verdicts (Stage-14 record §18 and
  §20) were correct when written and are **prospectively superseded** by this
  decision; they remain valid historical evidence.
- The deferred work must be performed under the future non-stage milestone
  without weakening the frozen contract or the hard SYSTEM SAFETY invariant.
- The semantic distinction between eval authority accounting and product WRITE
  payload fidelity (identified by `S14-07-RES-01`) is future eval/product
  research only and is **not** a Stage-14 change.

## References

- `DEVELOPMENT_STATUS.md` — canonical current roadmap state.
- `docs/stages/14_EVALS_AND_HARDENING.md` — Stage-14 architecture, tasks and
  frozen evidence (see §15, §16, §18, §20, §21).
- `docs/development/task-workflow.md` — scope and release-decision discipline.
- `docs/development/project-invariants.md` — MVP scope guard.
- `docs/development/quality-and-evidence.md` — evidence discipline.
