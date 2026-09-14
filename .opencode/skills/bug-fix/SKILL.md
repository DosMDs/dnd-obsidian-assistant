---
name: bug-fix
description: Diagnose and fix a D&D Assistant defect, failing invariant, traceback, data-integrity issue or platform regression in its owning layer.
---
# Bug fix

Read [current status](../../../DEVELOPMENT_STATUS.md), the affected contract/code/tests and original failure evidence. Use [correction-review](../correction-review/SKILL.md) to distinguish production, harness, evidence, documentation and gate-provenance defects before editing.

Reproduce or establish the exact failing invariant. Trace the causal mechanism to its owner, preserve accepted behavior outside it, and implement the smallest authorized fix. Add a regression that would fail against the defective state. Do not patch CLI/model symptoms for a storage/domain defect or broaden production contracts for collection-order artifacts.

For storage failures prove previous canonical data stays valid; for platform failures prefer portable Python and exercise the relevant Windows/macOS semantics. Run the regression and appropriate broader gates under [quality policy](../../../docs/development/quality-and-evidence.md), including Ruff for Python changes. No ratchet increases to fit the fix.

Stop and report if the fix requires unrelated scope, unauthorized protected harness changes, real Vault mutation or weakening an accepted contract. Escalate repeated correction classes through correction-review. Finish with [pre-finalization-audit](../pre-finalization-audit/SKILL.md); report root cause, changed behavior, literal regression evidence and residual risks. This skill grants no commit/push authorization.
