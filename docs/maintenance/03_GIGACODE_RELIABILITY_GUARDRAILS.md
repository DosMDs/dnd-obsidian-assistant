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

---

## MNT-C01 — Strengthen test-harness opt-in enforcement

**Date:** 2026-09-02

### Defect

The initial opt-in policy test (`test_test_harness_policy.py`) was
one-directional:

```python
for entry in actual:
    assert entry in expected
```

This `actual ⊆ expected` check caught unexpected **new** usages but did
**not** catch disappearance of a required restoration opt-in.  Removing a
`@pytest.mark.usefixtures("restore_dnd_assistant_modules")` from a
clean-import test class would leave the policy test green.

Additionally, the allowlist contained a stale entry:
`("unit/test_calendar_conversion.py", "TestBoundaries")` — that class is a
pure calendar boundary test with no `sys.modules` mutation and no fixture
usage.

### Correction

1. **Bidirectional exact-set comparison** — Changed both
   `test_known_module_level_optins` and `test_known_class_level_optins` to
   use `actual == expected` with detailed diagnostic messages showing
   missing expected and unexpected entries separately.

2. **Corrected allowlist** — Removed the stale
   `("unit/test_calendar_conversion.py", "TestBoundaries")` entry from
   `CLASS_LEVEL_OPTIIN`.

3. **Semantic clean-import coverage** — Added
   `TestCleanImportCoverage::test_all_clean_import_scopes_covered` which
   structurally detects AST patterns that delete `dnd_assistant` from
   `sys.modules` and verifies the enclosing scope opts into
   `restore_dnd_assistant_modules`.

4. **Negative regression tests** — Added `TestPolicyLogicRegression` with
   11 tests covering:
   - Missing expected opt-in is rejected
   - Unexpected opt-in is rejected
   - Exact match passes
   - Clean-import `del sys.modules[name]` detection (two patterns)
   - No false positive for unrelated code
   - Class-level clean-import detection
   - `_is_usefixtures_restore` detection and non-detection

### Changed files

- `tests/contract/test_test_harness_policy.py`
- `docs/maintenance/03_GIGACODE_RELIABILITY_GUARDRAILS.md`
- `DEVELOPMENT_STATUS.md`

### Zero diff

- `src/` — no changes
- `.gigacode/rules/` — no changes
- `.gigacode/skills/` — no changes

### Maintainability

- `PRODUCTION_HARD_LIMIT` = 700 (unchanged)
- `TEST_HARD_LIMIT` = 1000 (unchanged)
- `TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"]` = 1477 (unchanged)
- `tests/contract/test_test_harness_policy.py` physical lines = 546 (under 1000)

---

## MNT-C02 — Make harness semantic detection precise

**Date:** 2026-09-02

### Defects

**Defect A — Module-level opt-in detection was too weak.**

`_has_module_level_pytestmark` returned True for **any** module-level
`pytestmark = ...` assignment, regardless of whether it actually enabled
the `restore_dnd_assistant_modules` fixture.  This meant a file with::

```python
pytestmark = pytest.mark.slow
```

together with a clean-import that deletes `dnd_assistant.*` from
`sys.modules` would incorrectly pass semantic coverage.

**Defect B — Clean-import detector matched unrelated sys.modules deletion.**

`_has_dnd_assistant_del` and its class/module variants returned True for
**any** `del sys.modules[...]` without verifying that the deletion was
guarded by a condition referencing `dnd_assistant`.  This meant a test
deleting `other_package` from `sys.modules` would be falsely classified
as a D&D Assistant clean-import scope.

### Correction

1. **Replaced `_has_module_level_pytestmark` with
   `_has_module_level_restore_optin`** — returns True only when the
   module-level `pytestmark` assignment actually contains
   `pytest.mark.usefixtures("restore_dnd_assistant_modules")`.  Supports
   direct, list, and tuple forms.

2. **Replaced raw `del sys.modules[...]` detection with guarded
   detection** — `_has_dnd_assistant_del`, `_class_has_dnd_assistant_del`,
   and `_module_has_dnd_assistant_del_outside_class` now walk `If` nodes
   and only return True when the `if` condition references the string
   `"dnd_assistant"`.

3. **Corrected `test_unrelated_del_not_detected`** — changed from
   asserting detection (documenting the false positive) to asserting
   non-detection (the correct semantic behavior).

4. **Added semantic regression tests** (11 new tests):
   - Direct restore fixture mark detected
   - Unrelated pytestmark NOT detected
   - Wrong fixture NOT detected
   - Composite/list pytestmark detected
   - Clean-import + unrelated module mark = uncovered
   - Clean-import + correct module restore = covered
   - Class-level correct restore = covered
   - Bare unrelated `del sys.modules[...]` NOT detected

5. **Updated `test_known_module_level_optins`** to use
   `_has_module_level_restore_optin` instead of raw substring +
   assignment detection.

### Changed files

- `tests/contract/test_test_harness_policy.py`
- `docs/maintenance/03_GIGACODE_RELIABILITY_GUARDRAILS.md`
- `DEVELOPMENT_STATUS.md`

### Zero diff

- `src/` — no changes
- `.gigacode/rules/` — no changes
- `.gigacode/skills/` — no changes

### Maintainability

- `PRODUCTION_HARD_LIMIT` = 700 (unchanged)
- `TEST_HARD_LIMIT` = 1000 (unchanged)
- `TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"]` = 1477 (unchanged)
- `tests/contract/test_test_harness_policy.py` physical lines = (reported in Final Report)