---
name: code-review
description: Review a diff, branch, pull request or implementation for architecture, correctness, data safety, tests and MVP scope.
compatibility: D&D Session Assistant repository.
metadata:
  version: "2"
---
# Code review

Prioritize findings in this order:

1. possible Vault corruption or data loss;
2. unsafe model/filesystem/tool behavior;
3. architecture boundary violations;
4. revision/provenance/visibility mistakes;
5. calendar determinism errors;
6. ambiguous entity writes;
7. cross-platform failures;
8. missing or weak tests;
9. unnecessary dependencies or MVP scope creep;
10. maintainability/style issues.

For each finding provide:
- severity;
- file/location;
- concrete failure scenario;
- smallest recommended correction.

Do not praise routine code. Focus on actionable risks and regressions.

## Explicit review checks

- Requested scope vs actual diff.
- Unexpected files in the diff.
- Production workaround introduced for test infrastructure.
- Global fixture or global-state side effects.
- Duplicated test harnesses across modules.
- Maintainability ratchet movement (ceiling increases).
- Historical documentation claims vs actual Git state.
- Final Report changed-file inventory vs actual commit contents.
- Mandatory gate with failed or error results.
