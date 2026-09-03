---
apply: ALWAYS
mode: ALL
---

# Maintainability ratchet invariants

## 1. Limits are not convenience knobs

The following values are maintainability ratchets:

- `PRODUCTION_HARD_LIMIT`
- `TEST_HARD_LIMIT`
- `PRODUCTION_LEGACY_EXCEPTIONS` values
- `TEST_LEGACY_EXCEPTIONS` values

They may NOT be increased merely because a current change no longer fits.

## 2. Existing legacy ceilings

Do not increase an existing legacy exception value unless the current user
task explicitly authorizes changing that exact file's ceiling.

This applies even when no new dictionary key is added.

**Example:** changing `1477` to `1495` for an existing key is a ratchet
regression, even though the key already existed.

## 3. Gate self-modification

A maintainability gate does not pass if the task modified its own threshold
or exception value solely to make itself pass.

If code or tests exceed their accepted ceiling:

- split the module;
- refactor;
- deduplicate;
- or report a blocker.

Do not move the ceiling.

## 4. Global hard limits

Do not increase `PRODUCTION_HARD_LIMIT` (700) or `TEST_HARD_LIMIT` (1000)
without explicit architectural or user authorization.

## 5. Ratchet review

Every task that touches maintainability values must verify:

- no new legacy exception was added without justification;
- no existing ceiling was increased;
- global hard limits are unchanged.

If any of these is violated, the task is not complete.

## 6. Proactive headroom guidance

If a production file starts above ~600 lines and a task adds substantial
behavior, consider decomposition before adding logic.

If a test file starts above ~850 lines and substantial new coverage is
needed, prefer a new topic-oriented test module where coherent.

These are review thresholds, not new hard limits. They are not encoded in
maintainability contract tests.

## 7. No hard-limit gaming

Finishing at 699/700 is technically within the hard limit but is not
automatically good decomposition.

File cohesion remains primary. Do not split tiny cohesive modules solely to
satisfy a soft threshold.