---
apply: ALWAYS
mode: ALL
---

# Test-harness isolation principles

## 1. Test bugs belong to test infrastructure

Production behavior must not be weakened or broadened merely to survive:

- pytest collection order;
- import reloads;
- monkeypatch leakage;
- `sys.modules` identity churn;
- fixture ordering;
- test-only global state.

If a strict production invariant exposes a test-harness issue:

```
fix the harness
not the production contract
```

## 2. Global-state ownership

Tests that modify process-global state own restoration.

Examples of process-global state:

- `sys.modules`
- `os.environ`
- current working directory
- locale
- module globals
- global registries / singletons
- warnings filters

Use fixture or context-manager cleanup.

## 3. Fixture scope escalation

Preferred fixture scope:

1. test-local fixture / `usefixtures`
2. class-scoped opt-in
3. module-level opt-in or autouse — only when every test in that module
   needs it
4. repository-wide autouse — only with explicit demonstrated
   repository-wide need

Repository-wide autouse is NOT the default.

## 4. Duplication threshold

If substantially identical test-infrastructure cleanup appears in 3 or more
modules, stop copying and create one reusable opt-in helper or fixture.

Do NOT DRY ordinary scenario assertions so aggressively that test meaning
becomes opaque.

## 5. Maintainability interaction

Test-harness helper code must not cause a legacy test ceiling to be increased.

Prefer a shared opt-in fixture or helper over repeated fixture bodies.

## 6. Order-dependence verification

For changes involving `sys.modules` or process-global test state, run
affected suites in relevant execution orders to verify isolation.

## 7. Protected harness infrastructure

Treat as protected scope:

```text
tests/conftest.py
tests/integration/conftest.py
tests/contract/test_test_harness_policy.py
module-restoration allowlists
test-harness allowlists
global autouse fixtures
```

A normal feature/provider/domain task must not change them merely to make
its own tests pass.

## 8. Harness hard-stop rule

If an otherwise local task appears to require modifying protected
test-harness infrastructure and that scope was not explicitly authorized:

```text
STOP
→ report the requirement
→ separate it into a correction/maintenance task
```

Exception: a task explicitly about test-harness behavior may modify it.

Do not forbid legitimate harness maintenance.