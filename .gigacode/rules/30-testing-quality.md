---
apply: ALWAYS
mode: ALL
---
# Testing and quality

- Implement tests in the same task as production behavior.
- Prefer unit tests for domain logic, integration tests for real temporary Vault operations, contract tests for schemas/tools, and e2e tests for complete user flows.
- Calendar conversions and arithmetic should receive property-based tests with Hypothesis where useful.
- Ordinary tests must not require a running Ollama instance.
- Ollama network behavior should be mocked with respx; real checks must be isolated as explicit smoke tests.
- File tests must use temporary directories and real filesystem operations where storage semantics matter.
- Every bug fix should add a regression test when practical.
- Select quality gates from the **final actual Git diff**. The canonical classification policy is `.gigacode/rules/31-adaptive-quality-gates.md`.
- For code/test/runtime/config changes, run targeted tests first, then the relevant broader suites; run full `uv run pytest` when required by task scope/risk or an explicit task gate.
- For Python changes, run `uv run ruff check .` and `uv run ruff format --check .` unless the task gives a narrower justified rule.
- For documentation-only Markdown changes, do **not** run pytest or Ruff by default merely for evidence. Use documentation/diff consistency checks plus `git diff --check` and Git scope/finalization checks, unless the Markdown is machine-consumed or another explicit exception applies.
- Re-evaluate the gate class after all edits; an unexpected code/test/runtime/config file in the final diff cancels the documentation-only exemption.
- If the current task/prompt declares a full-suite gate mandatory for a relevant non-documentation reason, completion requires pytest exit code 0 with 0 failed and 0 errors. `"N passed, M skipped, K errors"` is NOT a passing gate for K > 0.
- For changes involving `sys.modules` or process-global test state, run affected suites in relevant execution orders to verify isolation. See `.gigacode/rules/37-test-harness-isolation.md`.
- Organise tests by stable behaviour/capability, not development history. See `.gigacode/rules/35-test-decomposition.md` for the detailed test decomposition policy.
