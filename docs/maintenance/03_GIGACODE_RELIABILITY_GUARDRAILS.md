# MNT-03 — GigaCode Reliability Guardrails

**Date:** 2026-09-02

## Objective

Convert lessons from the Stage-7 correction chain into durable GigaCode
rules, skills, and lightweight automated guardrails — without changing
product architecture or starting Stage 8.

## Stage-7 lessons encoded into policy

| Pattern | Encoding |
|---|---|
| A. Task scope drift | `.gigacode/rules/08-task-scope-and-evidence.md` |
| B. Final Report inventory from memory | `.gigacode/rules/08-task-scope-and-evidence.md` |
| C. pytest errors treated as passing | `.gigacode/rules/30-testing-quality.md` (updated) |
| D. Production workaround for sys.modules defect | `.gigacode/rules/37-test-harness-isolation.md` |
| E. Repository-wide fixture for local problem | `.gigacode/rules/37-test-harness-isolation.md` |
| F. Duplicated test-harness fixtures | `.gigacode/rules/37-test-harness-isolation.md` |
| G. Legacy ceiling increased to pass gate | `.gigacode/rules/36-maintainability-ratchets.md` |
| H. Historical docs vs actual Git | `.gigacode/rules/08-task-scope-and-evidence.md` |

## Rules added

| File | Purpose |
|---|---|
| `08-task-scope-and-evidence.md` | Starting-state capture, intended diff, evidence-driven Final Reports |
| `36-maintainability-ratchets.md` | Immutable ratchet invariants, no ceiling self-modification |
| `37-test-harness-isolation.md` | Test-harness isolation principles, fixture scope, duplication threshold |

## Rules updated

| File | Changes |
|---|---|
| `07-git-workflow.md` | Added pre-finalization-audit mandatory step |
| `30-testing-quality.md` | Mandatory gate semantics (0 failed, 0 errors), sys.modules ordering |
| `35-test-decomposition.md` | Cross-reference to ratchet rule, strengthened Exceptions section |

## Skills added

| File | Purpose |
|---|---|
| `pre-finalization-audit/SKILL.md` | Evidence-driven final audit workflow with hard STOP conditions |
| `correction-review/SKILL.md` | Correction workflow: root cause, freeze accepted behavior, regression |

## Skills updated

| Skill | Version | Changes |
|---|---|---|
| `bug-fix/SKILL.md` | v1 → v2 | Protect accepted behavior, test-harness defects stay in infra, no ceiling increase, pre-finalization-audit |
| `implement-feature/SKILL.md` | v1 → v2 | Intended file scope, unrelated defects out of scope, mandatory gates green |
| `testing/SKILL.md` | v1 → v2 | Process-global state isolation, fixture-scope minimization, order-dependence, ratchets, mandatory gates |
| `code-review/SKILL.md` | v1 → v2 | Explicit review checks: scope vs diff, unexpected files, ratchet movement, historical docs vs Git |
| `stage-workflow/SKILL.md` | v2 → v3 | Evidence collection section, pre-finalization-audit invocation, historical review-head capture |

## Automated guardrails added

| File | Purpose |
|---|---|
| `tests/contract/test_test_harness_policy.py` | Restoration fixture non-autouse, uniqueness, opt-in usage sanity |
| `tests/contract/test_maintainability.py` | Retrieval 1477 legacy ceiling regression guard |

### test_test_harness_policy.py guards

1. **Root restoration fixture non-autouse** — verifies
   `restore_dnd_assistant_modules` is a fixture but NOT `autouse=True`.
2. **Uniqueness guard** — verifies no other test module defines
   `restore_dnd_assistant_modules` (only `conftest.py`).
3. **Opt-in usage sanity** — verifies current module-level and class-level
   opt-in usages match the documented accepted set from S7-C12.

### test_maintainability.py guard

1. **Retrieval 1477 ratchet** — verifies
   `TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"] == 1477`.

## What remains intentionally manual

- Pre-finalization audit execution (workflow defined in skill, invoked by agent).
- Code review checklist items (defined in code-review skill).
- Task scope discipline (defined in rule 08, enforced by agent).
- Correction root-cause analysis (defined in correction-review skill).

## Quality gates

- `uv run pytest tests/contract/test_test_harness_policy.py` — PASS
- `uv run pytest tests/contract/test_maintainability.py` — PASS
- `uv run pytest tests/contract/test_boundaries.py` — PASS
- Order-dependence: boundary + catalog in both orders — PASS
- Full `uv run pytest` — 0 failed, 0 errors
- `uv run ruff check .` — PASS
- `uv run ruff format --check .` — PASS
- `git diff --check` — PASS

## Stage status

- Stage 7 — DONE
- MNT-03 — DONE
- Stage 8 — NOT STARTED