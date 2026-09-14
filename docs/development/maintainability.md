# Maintainability

Read this when a task touches a large module or test file, adds substantial new
behavior, refactors, or changes maintainability values. Evidence/gate discipline
lives in [quality-and-evidence.md](quality-and-evidence.md).

## 1. Cohesion first

A module should represent one coherent responsibility describable without
joining unrelated concerns with "and". Signals a module may need splitting:

```text
several unrelated groups of private helpers
several independent persistence protocols
multiple independent lifecycle workflows
multiple distinct mutation algorithms
many unrelated validation families
large sections testable independently
```

Place new functionality in the narrowest existing cohesive module. Do not add
new behavior to a large file merely because it already contains nearby imports
or helpers; if the correct responsibility does not exist, create a focused
module.

For an already-oversized module: a small surgical fix is allowed when extraction
would materially increase risk, but a new substantial responsibility must not be
added directly — create or extract a cohesive module first or in the same task.

## 2. Facade compatibility and dependency direction

Refactoring a large module into a package must preserve public contracts where
practical: `package/__init__.py` as a stable facade, explicit re-exports of the
original public API surface, internal modules for decomposed implementation. Do
not preserve private imports merely because tests incorrectly depended on
internals; migrate tests to the correct internal module.

Splitting must never introduce circular dependencies or violate layering:

```text
domain
↑
storage / retrieval
↑
application
↑
cli / tools / models
```

## 3. Avoid micro-file architecture

Decomposition follows meaningful responsibility boundaries. Do not create
one-function-per-file structure merely to satisfy line-count thresholds; closely
coupled helpers implementing one cohesive algorithm may stay together. A new
module should represent a meaningful responsibility worth naming. Reducing line
count alone is not a valid extraction rationale. **Cohesion is primary; line
count is only a diagnostic signal.**

## 4. Size thresholds (unchanged)

These are diagnostic signals, not architectural targets. A cohesive 520-line
parser may remain intact; a 300-line module with unrelated responsibilities may
still need splitting.

Production:

```text
soft review threshold   ~500 logical / source lines
hard ratchet limit      700 physical lines for a NEW non-exempt production module
```

Test:

```text
soft review threshold   ~700 lines
hard ratchet limit      1000 physical lines for a NEW non-exempt test module
```

Existing modules above a hard limit at the MNT-01 baseline are legacy exceptions
recorded in the maintainability contract test. They may stay at their current
size but must not silently grow. Any exception above the hard limits must be
explicit, documented, specific to a file and reviewed. Never silently raise the
global limit.

## 5. Ratchet invariants

The following are ratchets and may not be increased merely because a change no
longer fits:

```text
PRODUCTION_HARD_LIMIT (700)
TEST_HARD_LIMIT (1000)
PRODUCTION_LEGACY_EXCEPTIONS values
TEST_LEGACY_EXCEPTIONS values
```

- Do not increase an existing legacy exception value unless the current user
  task explicitly authorizes changing that exact file's ceiling — even when no
  new key is added (e.g. changing `1477` to `1495` for an existing key is a
  ratchet regression).
- A maintainability gate does not pass if the task modified its own threshold or
  exception value solely to make itself pass. If code/tests exceed an accepted
  ceiling: split, refactor, deduplicate, or report a blocker. Do not move the
  ceiling.
- Do not increase `PRODUCTION_HARD_LIMIT` or `TEST_HARD_LIMIT` without explicit
  architectural or user authorization.
- Every task touching maintainability values must verify: no new legacy
  exception was added without justification; no existing ceiling was increased;
  global hard limits are unchanged. Otherwise the task is not complete.
- No hard-limit gaming: finishing at 699/700 is within the limit but is not
  automatically good decomposition. Do not split tiny cohesive modules solely to
  satisfy a soft threshold.

## 6. Proactive headroom

- If a production file starts above ~600 lines and a task adds substantial
  behavior, consider decomposition before adding logic.
- If a test file starts above ~850 lines and substantial new coverage is needed,
  prefer a new topic-oriented test module where coherent.

These are review thresholds, not new hard limits, and are not encoded in
maintainability contract tests.

## 7. Test decomposition

Tests must be organised by stable behaviour/capability, not development history
or ticket number. Prefer names like `test_session_recovery_partial_start.py`,
`test_session_recovery_event_tail.py`, `test_session_recovery_failures.py`.
Avoid `..._c06.py`, `..._fix2.py`, `..._final.py`, `..._followup.py`.

- Correction IDs belong in commit messages, stage history and Final Reports —
  not in long-lived production or new test module names. Historical
  correction-specific files are temporary legacy debt and may remain until
  explicitly migrated; legacy exceptions are path-specific.
- From MNT-01 onward, do not create new correction-number test files. A
  correction adds its regression to the most specific topical test module; if
  that module is too large, split by behaviour first, then add the regression.
- Test helpers allowed: small fixture builders, canonical context factories,
  temporary Vault builders, assertion helpers with obvious semantics. Avoid
  large custom test DSLs, generic meta-frameworks, helpers that contain the
  behaviour under test, and deep inheritance between test classes. Tests should
  remain readable locally; do not DRY so aggressively that important scenario
  differences disappear.
- Use `pytest.mark.parametrize` when scenarios share setup shape, action and
  assertion structure. Do not combine semantically different failure paths
  merely to reduce line count. A test file should become smaller because
  responsibilities are clearer, not because intent was compressed into
  unreadable matrices.
