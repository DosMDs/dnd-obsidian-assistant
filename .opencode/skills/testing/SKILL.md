---
name: testing
description: Add or review meaningful D&D Assistant unit, integration, contract, property and end-to-end tests, fixtures and regression evidence.
---
# Testing

Read the owning contract/implementation, [current status](../../../DEVELOPMENT_STATUS.md) and [quality-and-evidence](../../../docs/development/quality-and-evidence.md). Identify the literal invariant before choosing the lowest useful testing layer.

Use temporary real Vaults for filesystem semantics, deterministic platform-neutral fixtures, Hypothesis for strong calendar algebra, and mocked HTTP (respx) for ordinary provider tests. For bug fixes establish the regression before fixing where practical. Derive structural classes before writing coverage: missing/null/expected empty/wrong empty/falsy/valid/malformed. Where numeric semantics apply consider 0, 1, -1, ordinary positive/negative ints and floats, True/False, NaN, both infinities, very large positive/negative integers and wrong scalar types. This is contract-driven review, not a demand for every value everywhere; one malformed truthy case does not prove falsy rejection, and NaN rejection does not prove overflow containment.

Tests that change process-global state (`sys.modules`, `os.environ`, cwd, registries/singletons) own restoration via fixture or context-manager cleanup. Prefer test-local fixtures; module autouse only when every test needs it; repository-wide autouse requires demonstrated repository-wide need. Verify relevant execution orders after `sys.modules`/global changes. Preserve maintainability ratchets and avoid new correction-number test modules and opaque test DSLs.

Do not use skip/xfail to hide a required acceptance failure; explain expected skips/xfails and unexpected passes, and keep mandatory criteria backed by passing literal checks. Run focused checks then the broader gates warranted by the final diff/risk; root `uv run pytest` alone is canonical full-suite evidence, and a mandatory full-suite gate requires exit 0 with 0 failed / 0 errors. Skipped live tests prove neither construction nor network behavior. Measurement work requires [eval-harness](../eval-harness/SKILL.md). Stop/report unauthorized protected harness scope, weakened production for a double, missing literal evidence or a mandatory failed/error gate. Finish with [pre-finalization-audit](../pre-finalization-audit/SKILL.md).
