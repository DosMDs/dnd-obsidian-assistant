---
name: correction-review
description: Implement or review a correction pass by reproducing the exact defect, classifying its owning layer, protecting already accepted behavior, fixing the causal mechanism, and preventing repeated evidence/workaround chains.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "2"
---

# Correction review

## Workflow

1. Restate the exact failing invariant.
2. Classify the defect before editing.
3. Reproduce or establish it before editing when practical.
4. Identify the architectural/test/evidence layer that owns the defect.
5. Freeze previously accepted behavior outside that defect.
6. Search for the causal mechanism, not only the immediate symptom.
7. Implement the smallest root-cause correction.
8. Add a regression/evidence check that would fail against the defective behavior.
9. Verify the correction does not weaken another contract.
10. Inspect similar occurrences only to assess scope.
11. Do not automatically fix unrelated occurrences.
12. Check maintainability ratchets.
13. Reconcile all original hard acceptance criteria still affected by the correction.
14. Perform `pre-finalization-audit`.

## Defect classification

Choose the primary owner explicitly:

```text
PRODUCTION
  runtime/domain/application behavior is wrong

TEST_HARNESS
  fixtures/wrappers/counters/test doubles/ordering are wrong

EVIDENCE
  tests do not literally prove the claimed invariant

DOCUMENTATION
  code/tests are correct but recorded metadata/claims are wrong

GATE_PROVENANCE
  the wrong command/suite/environment was reported as the required gate
```

Do not modify production for a TEST_HARNESS/EVIDENCE/DOCUMENTATION defect.

If classification is uncertain, investigate before editing rather than
spreading fixes across layers.

## Hard rules

- Do not solve a test-harness defect by weakening production behavior.
- Do not solve a local test problem with a repository-wide mechanism unless
  repository-wide scope is demonstrated.
- Do not multiply the same workaround across modules; extract a narrow
  reusable test helper when appropriate.
- A green test obtained by weakening the contract under test is not a valid
  fix.
- A correction is not complete merely because the new test passes; it must
  close the exact original claim/evidence gap.
- Do not add/increase maintainability exceptions just to fit correction code.

## Regression validity

A correction regression should answer:

```text
Would this test/assertion have failed against the exact defective state?
```

If not, it is not sufficient evidence for the correction.

For evidence defects, this may mean strengthening a helper or adding literal
counters rather than adding another scenario.

## Correction-chain escalation

If the same task accumulates **two or more correction passes** for the same
class of defect (especially TEST_HARNESS, EVIDENCE, DOCUMENTATION or
GATE_PROVENANCE), stop before beginning another local correction.

Perform a meta-review:

1. list the repeated defect pattern;
2. identify which always-on rule or reusable skill failed to encode it;
3. decide whether a reusable rule/skill/helper update is warranted;
4. update that shared guidance in a dedicated/coherent scope when appropriate;
5. only then continue the feature/migration correction.

Example repeated patterns that trigger this review:

```text
claims stronger than assertions
inferred counts reported as measured
reference and candidate accidentally using the same runtime
live fixtures never constructed because offline tests skipped
warm-up after measurement
aggregate metrics rerunning a different sample set
line-count/changed-file/status transcription drift
```

The objective is to stop correction chains from becoming prompt-specific
workaround chains.

## Correction final report

Report:

- original defect classification;
- exact reproducer/evidence gap;
- owning layer;
- changed scope;
- regression that would fail before the correction;
- accepted behavior preserved;
- exact gates/results;
- whether this correction exposed a reusable rule/skill gap;
- final Git evidence.
