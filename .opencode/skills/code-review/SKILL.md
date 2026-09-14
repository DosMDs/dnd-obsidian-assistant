---
name: code-review
description: Review a diff, branch, pull request or implementation for architecture, correctness, Vault safety, tests and MVP scope.
---
# Code review

Read-only review of a diff, branch, PR or implementation; it grants no mutation, commit, push or live-eval authority. Apply [project-invariants](../../../docs/development/project-invariants.md), [untrusted-boundaries](../../../docs/development/untrusted-boundaries.md) and [quality-and-evidence](../../../docs/development/quality-and-evidence.md); use the `.opencode/agents/` reviewer subagents for independent passes.

Prioritize findings in this order: possible Vault corruption/data loss; unsafe model/filesystem/tool behavior; architecture boundary violations; revision/provenance/visibility mistakes; calendar determinism errors; ambiguous entity writes; cross-platform failures; missing or weak tests; unnecessary dependencies or MVP scope creep; maintainability/style.

For each finding give severity, file/location, a concrete failure scenario and the smallest recommended correction. Do not praise routine code; focus on actionable risks and regressions.

Explicit checks: requested scope vs actual diff; unexpected files; production workaround introduced for test infrastructure; global fixture/global-state side effects; duplicated test harnesses; maintainability ratchet/ceiling movement; historical documentation claims vs actual Git state; Final Report changed-file inventory vs commit contents; a mandatory gate with failed/error results. Boundary checks: truthiness used as structural validation; missing/null/empty/falsy conflation; bool-as-int; integer-to-float overflow; non-finite float handling; incidental exception leakage across public boundaries; evidence transcription mismatch; Git direction-label mistakes.
