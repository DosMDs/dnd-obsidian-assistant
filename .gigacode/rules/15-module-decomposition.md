---
apply: ALWAYS
mode: ALL
---

# Module decomposition policy

## Cohesion first

A module should represent one coherent responsibility that can be described
without using "and" to join unrelated concerns.

Signals that a module may need splitting:

- several unrelated groups of private helpers;
- several independent persistence protocols;
- multiple independent lifecycle workflows;
- multiple distinct mutation algorithms;
- many unrelated validation families;
- large sections that could be tested independently.

## New code

Place new functionality in the narrowest existing cohesive module.

Do not add new behavior to a large file merely because that file already
contains nearby imports or helpers.

If the correct responsibility does not exist:

- create a focused module

rather than enlarging an unrelated one.

## Existing oversized modules

If a task touches an already oversized module:

- a small surgical fix is allowed when extraction would materially increase
  risk;

but:

- a new substantial responsibility must not be added directly;
- create or extract a cohesive module first or in the same task.

## Facade compatibility

Refactoring a large module into a package must preserve public contracts
where practical.

Preferred approach:

- `package/__init__.py` as a stable facade;
- explicit re-exports from the original public API surface;
- internal modules for decomposed implementation.

Do not preserve private imports merely because tests incorrectly depended on
internals; migrate tests toward the correct internal module when appropriate.

## Dependency direction

Splitting modules must never introduce circular dependencies or violate the
project's architectural layering:

```
domain
↑
storage / retrieval
↑
application
↑
cli / tools / models  (as appropriate)
```

Follow existing architectural boundaries defined in `GIGACODE.md`.

## Size thresholds

These are **diagnostic signals**, not architectural targets.

A cohesive 520-line parser may reasonably remain intact. A 300-line module
with unrelated responsibilities may still need splitting.

### Soft review threshold (production)

~500 logical / source lines.

When a production module approaches or exceeds this, consider whether it
still represents one coherent responsibility.

### Hard ratchet limit (production)

700 physical lines for a **new** non-exempt production module.

Existing modules that exceed this limit at the time of the MNT-01 baseline
are recorded as legacy exceptions in the maintainability contract test.
They may stay at their current size but must not silently grow.

### Soft review threshold (test)

~700 lines.

### Hard ratchet limit (test)

1000 physical lines for a **new** non-exempt test module.

Existing test modules above this limit are recorded as legacy exceptions.

### Exceptions

Any exception above the hard limits must be:

- explicit;
- documented;
- specific to a file;
- reviewed.

Never silently raise the global limit.