---
name: implement-feature
description: Implement a new D&D Session Assistant feature or roadmap task. Use when asked to add, build, implement, create, extend or complete application behavior across one or more Python modules.
compatibility: Python 3.12+, uv, pytest, Ruff.
metadata:
  version: "1"
---
# Implement feature

## Workflow

1. Locate the roadmap stage and affected architectural layers.
2. Inspect existing contracts, production code and nearby tests before designing changes.
3. For multi-file or boundary-affecting work, produce a short plan with files, contracts, tests and risks.
4. Implement the smallest vertical slice that satisfies the request without violating dependency direction.
5. Add tests in the same change.
6. Run targeted tests, then broader pytest/Ruff checks when feasible.
7. Review the final diff for unrelated edits and architecture violations.

## Guardrails

- Never bypass ToolExecutor/VaultRepository for campaign writes.
- Never move deterministic logic into an LLM.
- Never couple domain/storage to Ollama.
- Do not introduce postponed MVP technologies without explicit user approval.
