---
name: testing
description: Add, improve or review tests, fixtures, failure-injection coverage, Hypothesis properties, model adapter mocks or regression tests.
compatibility: Python 3.12+, pytest, Hypothesis, pytest-cov, respx.
metadata:
  version: "1"
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
