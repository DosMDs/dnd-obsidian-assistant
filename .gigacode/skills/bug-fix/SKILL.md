---
name: bug-fix
description: Diagnose and fix a defect, failing test, traceback, data-integrity issue or platform-specific problem in D&D Session Assistant.
compatibility: Python 3.12+, uv, pytest, Ruff.
metadata:
  version: "1"
---
# Bug fixing

1. Reproduce or establish the failing invariant before editing.
2. Trace the failure to the correct architectural layer instead of patching symptoms in CLI/model code.
3. Add or update a regression test.
4. Make the smallest fix that restores the intended contract.
5. For storage bugs, verify failure behavior cannot corrupt the Vault.
6. For Windows/macOS bugs, avoid platform-specific workaround code when a portable Python solution exists.
7. Run the regression test, relevant suite and Ruff checks.
8. Report root cause, changed behavior and any residual risk.
