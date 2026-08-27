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
- Before completion run targeted tests, then `uv run pytest`, `uv run ruff check .`, and `uv run ruff format --check .` when feasible.
