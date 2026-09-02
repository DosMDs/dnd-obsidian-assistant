---
name: correction-review
description: Implement or review a correction pass by reproducing the exact defect, protecting already accepted behavior, fixing the owning layer, and preventing scope drift or workaround chains.
compatibility: D&D Session Assistant repository, Git, uv, pytest, Ruff.
metadata:
  version: "1"
---

# Correction review

## Workflow

1. Restate the exact failing invariant.
2. Reproduce or establish it before editing when practical.
3. Identify the architectural layer that owns the defect.
4. Freeze previously accepted behavior outside that defect.
5. Search for the causal mechanism, not only the immediate symptom.
6. Implement the smallest root-cause correction.
7. Add a regression that fails against the defective behavior.
8. Verify the correction does not weaken another contract.
9. Inspect similar occurrences only to assess scope.
10. Do not automatically fix unrelated occurrences.
11. Check maintainability ratchets.
12. Perform pre-finalization-audit.

## Hard rules

- Do not solve a test-harness defect by weakening production behavior.
- Do not solve a local test problem with a repository-wide mechanism unless
  repository-wide scope is demonstrated.
- Do not multiply the same workaround across modules; extract a narrow
  reusable test helper when appropriate.
- A green test obtained by weakening the contract under test is not a valid
  fix.