# ADR-0005: Module and test decomposition policy

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

The repository is functionally healthy, but several modules and test suites
have grown large during correctness-hardening stages (Stage 5 — Retrieval,
Stage 6 — Session Runtime).

Large cohesive code is not automatically bad, but very large files increase:

- review cost;
- agent context cost;
- merge/edit risk;
- accidental coupling;
- difficulty identifying the correct change surface.

Specific hotspots include:

- `storage/session_recovery.py` — 1947 lines, multiple distinct workflows;
- `storage/session_metadata.py` — 1138 lines, mixed responsibilities;
- `storage/session_events.py` — 1096 lines, event logging + repair;
- `storage/vault_repository.py` — 1379 lines, general Vault operations;
- `domain/calendar.py` — 1295 lines, parsing + arithmetic + queries;
- `storage/world_time.py` — 834 lines, persistence + serialization;
- `storage/types.py` — 741 lines, multiple DTO families.

Test files have similar growth patterns, with several exceeding 1000 lines
and correction-specific test files accumulating over time.

Without a written policy, future development may continue to enlarge
existing modules rather than decomposing by responsibility.

## Decision

Adopt the following policies, codified as always-on rules:

### Cohesion-driven decomposition

A module should represent one coherent responsibility. Extraction is
preferred when a module owns multiple independently changing concerns.

### Stable public facades

When a large module is refactored into a package, public contracts should be
preserved through `__init__.py` re-exports where practical.

### Topic-oriented tests

Tests are organised by stable behaviour / capability, not by ticket number
or correction history.

### Size ratchet for new growth

New production modules: max 700 physical lines.
New test modules: max 1000 physical lines.

Existing oversized files are recorded as legacy exceptions with a pinned
baseline. They may stay at their current size but must not silently grow.

### Correction-specific test filenames

New correction-number test filenames (e.g. `_c06`, `_fix2`) are prohibited.
Regressions must be added to the most specific topical test module.

### Incremental migration

Existing oversized modules and correction-specific test files are migrated
incrementally through dedicated maintenance tasks (MNT-02+), not through a
big-bang rewrite.

## Consequences

### Positive

- Future diffs are smaller and more focused.
- New contributors and agents can identify the correct change surface more
  easily.
- Technical debt is monotonic: oversized files may shrink but must not
  silently grow.
- The automated ratchet provides objective enforcement without requiring
  human reviewers to manually check file sizes.

### Negative

- Some decomposition effort is required before adding substantial new
  behaviour to oversized modules.
- The line-count ratchet is a coarse proxy for cohesion; it may need
  adjustment as the codebase evolves.

### Risks

- Over-decomposition into micro-files would harm readability. The policy
  explicitly warns against one-function-per-file architecture.
- The ratchet may need occasional exception review for generated code or
  unusually dense lookup tables. The policy requires explicit documented
  exceptions.

## Rejected alternatives

### One-function-per-file architecture

Rejected: would increase navigation cost and import complexity without
proportional benefit.

### Repository-wide big-bang refactor

Rejected: too risky for an active development codebase. Incremental
migration preserves stability.

### Blind LOC optimisation

Rejected: line count is a diagnostic signal, not a quality target. A
300-line module with mixed responsibilities may still need splitting.

### Rewriting completed stable stages without reason

Rejected: stable Stage 1-5 code is not refactored unless a concrete
architectural problem is identified.

## Implementation

Implementation commit: (reported in Final Report)

The policy is enforced through:

- `.gigacode/rules/15-module-decomposition.md` — production module policy;
- `.gigacode/rules/35-test-decomposition.md` — test decomposition policy;
- `tests/contract/test_maintainability.py` — automated line-count ratchet
  and correction-filename guard;
- `docs/engineering/MAINTAINABILITY_BASELINE.md` — current-state inventory
  and legacy exceptions.