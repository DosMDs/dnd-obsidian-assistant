---
name: correction-review
description: Diagnose or review correction passes by classifying the owning defect, proving the original evidence gap and escalating repeated failures into durable guidance review.
---
# Correction review

A correction is a new Task ID → new session → PLAN again ([task-workflow](../../../docs/development/task-workflow.md) §9). Preserve accepted behavior outside the defect and fix the causal mechanism, not the symptom.

Classify the primary owner explicitly before editing: `PRODUCTION` (runtime/domain/application behavior wrong), `TEST_HARNESS` (fixtures/wrappers/counters/doubles/ordering wrong), `EVIDENCE` (tests do not literally prove the claim), `DOCUMENTATION` (code/tests correct but recorded claims wrong), `GATE_PROVENANCE` (wrong command/suite/environment reported as the required gate). Do not modify production for a non-production defect; investigate uncertain classification before editing rather than spreading fixes across layers.

Workflow: restate the exact failing invariant → classify → reproduce/establish before editing when practical → freeze accepted behavior → search the causal mechanism, not only the symptom → smallest root-cause fix → add a regression that would fail against the defective state → verify no other contract weakened → check ratchets → reconcile all original hard acceptance criteria still affected → [pre-finalization-audit](../pre-finalization-audit/SKILL.md). Inspect similar occurrences only to assess scope; do not auto-fix unrelated ones.

Regression validity: a correction test must answer "would this have failed against the exact defective state?"; if not, it is not sufficient evidence. For evidence defects this may mean strengthening a helper or adding literal counters rather than another scenario.

Correction-chain escalation: if the same task accumulates two or more correction passes for the same defect class (especially TEST_HARNESS/EVIDENCE/DOCUMENTATION/GATE_PROVENANCE), STOP before another local patch, identify the repeated pattern, decide whether an always-on rule/skill/helper failed to encode it, update that shared guidance in a coherent scope, then continue. Do not let a correction chain become the de facto specification.

Report: defect classification, exact reproducer/evidence gap, owning layer, changed scope, the regression that fails before the fix, preserved accepted behavior, exact gates/results, any reusable guidance gap, and final Git evidence.
