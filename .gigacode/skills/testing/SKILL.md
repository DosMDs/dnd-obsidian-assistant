---
name: testing
description: Add, improve or review tests, fixtures, failure-injection coverage, Hypothesis properties, model adapter mocks or regression tests.
compatibility: Python 3.12+, pytest, Hypothesis, pytest-cov, respx.
metadata:
  version: "2"
---
# Testing workflow

1. Identify the contract/invariant being protected.
2. Choose the lowest useful layer: unit, integration, property, contract or e2e.
3. Include negative/boundary cases; do not optimize only for happy paths.
4. Use temporary real Vault directories for repository integration behavior.
5. Use Hypothesis for calendar algebra and other strong invariants where appropriate.
6. Mock Ollama HTTP for ordinary tests; real Ollama is opt-in.
7. For bug fixes, first reproduce with a regression test when practical.
8. Keep fixtures small, deterministic and platform-neutral.
9. Run the narrow test selection first, then the full suite when feasible.

## Process-global state isolation

- Tests that modify `sys.modules`, `os.environ`, cwd, or other process-global
  state must own restoration via fixture or context-manager cleanup.
- Use `restore_dnd_assistant_modules` (opt-in) for clean-import tests.
- Do not use repository-wide autouse for local test problems.

## Fixture-scope minimization

- Prefer test-local fixtures.
- Module-level autouse only when every test in that module needs it.
- Repository-wide autouse requires demonstrated repository-wide need.

## Order-dependence verification

- For changes involving `sys.modules` or process-global test state, run
  affected suites in multiple execution orders to verify isolation.

## Maintainability ratchets

- Do not cause legacy test ceilings to increase.
- Prefer shared opt-in fixtures over repeated fixture bodies.
- See `.gigacode/rules/36-maintainability-ratchets.md`.

## Mandatory gate semantics

- When a full-suite gate is mandatory: pytest exit code 0, 0 failed, 0 errors.
- `"N passed, M skipped, K errors"` is NOT a passing gate for K > 0.
