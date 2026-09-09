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

```text
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

## 9. Live-test skip is not constructor evidence

A live/integration test skipped because an environment variable or external
service is unavailable does **not** prove that its fixtures/object graph can be
constructed.

For opt-in live suites, provide offline preflight tests for the test-owned
infrastructure when constructor/type/fixture failures are plausible.

At minimum validate as applicable:

```text
fixture constructors
dependency/test-double contracts
concrete runtime type requirements
wrapper/decorator type compatibility
scenario/scoring helpers
```

A default offline suite that only skips the live module must not be cited as
proof that the live harness is ready.

## 10. Framework-wrapper transparency

A test wrapper/decorator around a concrete framework object must preserve the
public behavior/configuration that can affect execution.

Before using such a wrapper in live or parity evidence:

- confirm it satisfies required concrete/base type checks;
- inspect the pinned framework version's public contract;
- preserve/delegate settings/profile/provider/model identity where relevant;
- preserve exception semantics;
- preserve lifecycle semantics where the wrapped object owns resources;
- add offline equivalence tests.

Do not loosen production `isinstance` or validation checks merely to admit a
weak test double.

## 11. Measurement fixture ownership

Measured eval/benchmark state must not depend on pytest test ordering.

Required pattern:

```text
fixture/setup owns warm-up
→ fixture/setup collects measured observations
→ observations are frozen/reused
→ reporting/assertion tests consume them without repeating the measured action
```

Standalone `test_warmup_*` methods that happen to sort before/after measured
tests are not a reliable warm-up mechanism.

If a module-scoped measured dataset is intended to execute exactly once,
assert sample counts and uniqueness of scenario/repetition keys.

## 12. Test-double truthfulness

A test double must model the contract required by the test and fail loudly on
unexpected use.

Examples:

- scripted model gateways should fail on an unexpected extra request;
- "hidden tool" fixtures must prove the tool is actually absent from exposure;
- fake repositories must satisfy the real return/error contract used by the
  production consumer;
- a null object must not return `None` where the real interface signals absence
  with a typed exception or state object.
