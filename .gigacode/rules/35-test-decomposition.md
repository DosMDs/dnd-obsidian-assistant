---
apply: ALWAYS
mode: ALL
---

# Test decomposition policy

## Topic-oriented organisation

Tests must be organised by **stable behaviour / capability**, not by
development history or ticket number.

Preferred names:

```text
test_session_recovery_inspection.py
test_session_recovery_audit_tail.py
test_session_recovery_partial_start.py
test_session_recovery_event_tail.py
test_session_recovery_failures.py
```

Avoid names such as:

```text
test_session_recovery_c06.py
test_session_recovery_fix2.py
test_session_recovery_final.py
test_session_recovery_followup.py
```

## Correction-specific test files

Correction IDs belong in:

- commit messages;
- stage history;
- Final Reports.

**Not** in long-lived production module names.
**Not** in new long-lived test module names.

Historical correction-specific files already in the repository are temporary
legacy debt and may remain until explicitly migrated.

Legacy correction exceptions are path-specific: a file with the same basename
at a different path does not inherit the exception.

From MNT-01 onward:

- do **not** create new correction-number test files.

A correction should add its regression to the most specific topical test
module.

If that module is already too large:

- split by behaviour first;
- then add the regression.

Do **not** create another correction-number file.

## Test helpers

Allowed:

- small fixture builders;
- canonical `AuditContext` factories;
- temporary Vault builders;
- assertion helpers with obvious semantics.

Avoid:

- large custom test DSL;
- generic meta-framework;
- helpers that contain the behaviour actually under test;
- deep inheritance between test classes.

Tests should remain readable locally.

Do not DRY tests so aggressively that important scenario differences
disappear.

## Parametrisation

Use `pytest.mark.parametrize` when scenarios share the same:

- setup shape;
- action;
- assertion structure.

Do not combine semantically different failure paths merely to reduce line
count.

A test file should become smaller because responsibilities are clearer, not
because test intent was compressed into unreadable matrices.

## Size thresholds

### Soft review threshold (test)

~700 lines.

When a test module approaches or exceeds this, consider whether it still
represents one coherent behaviour area.

### Hard ratchet limit (test)

1000 physical lines for a **new** non-exempt test module.

Existing test modules that exceed this limit at the time of the MNT-01
baseline are recorded as legacy exceptions in the maintainability contract
test. They may stay at their current size but must not silently grow.

### Exceptions

Any exception above the hard limits must be:

- explicit;
- documented;
- specific to a file;
- reviewed.

Never silently raise the global limit.

### Maintainability ratchet

After baseline capture, the recorded ceiling is a **hard ratchet**.

The value itself must not be increased by an ordinary implementation,
bug-fix, correction, or maintenance task.

See `.gigacode/rules/36-maintainability-ratchets.md` for the full ratchet
invariants.