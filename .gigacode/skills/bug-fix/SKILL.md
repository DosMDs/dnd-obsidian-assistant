---
name: bug-fix
description: Diagnose and fix a defect, failing test, traceback, data-integrity issue or platform-specific problem in D&D Session Assistant.
compatibility: Python 3.12+, uv, pytest, Ruff.
metadata:
  version: "2"
---
# Bug fixing

1. Reproduce or establish the failing invariant before editing.
2. Trace the failure to the correct architectural layer instead of patching symptoms in CLI/model code.
3. Protect accepted behavior outside the defect — do not broaden production contracts for test-runner artifacts.
4. Test-harness defects remain in test infrastructure; do not weaken production behavior to fix them.
5. Add or update a regression test.
6. Make the smallest fix that restores the intended contract.
7. For storage bugs, verify failure behavior cannot corrupt the Vault.
8. For Windows/macOS bugs, avoid platform-specific workaround code when a portable Python solution exists.
9. Do not increase maintainability ceilings.
10. Run the regression test, relevant suite and Ruff checks.
11. Finish with pre-finalization-audit.
12. Report root cause, changed behavior and any residual risk.

See `.gigacode/skills/correction-review/SKILL.md` for the full correction workflow.
