---
name: code-review
description: Review a diff, branch, pull request or implementation for architecture, correctness, data safety, tests and MVP scope.
compatibility: D&D Session Assistant repository.
metadata:
  version: "4"
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

## Boundary validation review checks

For any code handling external/model/config/serialized data, review:

```text
truthiness used as structural validation
    e.g. if value: when missing/null/empty/falsy have distinct meanings

missing/null/empty/falsy equivalence errors
    are None, [], {}, "", 0, False treated as the same case?

bool-as-int bugs
    isinstance(True, int) is True
    is bool rejected before int is accepted?

numeric conversion overflow
    oversized Python int -> float may raise OverflowError

non-finite numeric values
    NaN, +Infinity, -Infinity explicitly handled or rejected?

incidental exception leakage across public boundaries
    parsing, decoding, coercion, indexing, third-party exceptions

evidence transcription mismatch
    does documentation match actual command output?

Git direction-label mistakes
    ahead_by = head-only, behind_by = base-only
    base-only and head-only as primary evidence terms
```