# Maintainability Baseline — MNT-01

**Date:** 2026-09-01
**Starting HEAD:** `c1c7855ca82d346a8f7683e2e2086419886f3f73`

This document records the repository's module-size and test-organisation
baseline at the time of MNT-01. It serves as the authoritative source for
legacy exceptions enforced by `tests/contract/test_maintainability.py`.

---

## MNT-02 — Behavior-preserving decomposition of session_recovery

**Date:** 2026-09-01
**Commit:** `599fbcdcb09084b1420d3f37fe5b47fb30c7a400`

### Production decomposition

`src/dnd_assistant/storage/session_recovery.py` (1947 lines) was decomposed
into a package with the following modules:

| Module | Lines (MNT-02) | Lines (MNT-C02) | Responsibility |
|---|---|---|---|
| `session_recovery/types.py` | 218 | 218 | Recovery DTOs (RecoveryIssue, SessionRecoveryReport, RecoveryActionResult) |
| `session_recovery/support.py` | 216 | 216 | Shared recovery primitives (hash, audit, snapshot) |
| `session_recovery/audit_tail.py` | 378 | 378 | Audit inspection and self-targeting repair |
| `session_recovery/partial_start.py` | 374 | 374 | Partial-start ownership verification and cleanup |
| `session_recovery/event_tail.py` | 500 | 501 | Event-tail validation and repair |
| `session_recovery/inspection.py` | 322 | 322 | Read-only session runtime inspection |
| `session_recovery/repository.py` | 177 | 177 | ObsidianSessionRecoveryRepository orchestration facade |
| `session_recovery/__init__.py` | 39 | 46 | Public package facade |

All new production modules satisfy the <= 700 line hard limit.
No new production legacy exceptions were added.

### Test migration

Old files removed:

- `tests/unit/test_session_recovery.py` — 585 lines (21 tests)
- `tests/unit/test_session_recovery_failures.py` — 633 lines (17 tests)
- `tests/unit/test_session_recovery_c05.py` — 915 lines (26 tests)
- `tests/unit/test_session_recovery_c05f.py` — 740 lines (26 tests)

New topical test files (MNT-C02F final):

| Module | Lines | Responsibility |
|---|---|---|
| `session_recovery/conftest.py` | 179 | Shared fixtures and helpers |
| `session_recovery/test_types.py` | 125 | Recovery DTO value/equality/hash |
| `session_recovery/test_audit_tail.py` | 352 | Audit inspection, repair, UTF-8, CRLF, I/O errors |
| `session_recovery/test_inspection.py` | 367 | Read-only inspection, partial start, events, metadata |
| `session_recovery/test_partial_start.py` | 527 | Partial cleanup, ownership, races, blocked-by-LF, repair-audit-first, exact-byte invariants |
| `session_recovery/test_event_tail.py` | 863 | Event repair, metadata prereq, audit prereq, I/O errors, missing-LF refusal, invalid UTF-8 metadata, phase-specific races |
| `contract/test_session_recovery_facade.py` | 117 | Facade import and signature contract tests |

All new test modules satisfy the <= 1000 line hard limit.
No new test legacy exceptions were added.

### Legacy exceptions removed

- Production: `storage/session_recovery.py` — 1947 (removed)
- Correction paths: `unit/test_session_recovery_c05.py`, `unit/test_session_recovery_c05f.py` (removed)

### Behavioral gates

- Pre-refactor recovery test baseline: 117 passed, 1 skipped (historical at `fd91034`)
- Post-refactor recovery test suite (MNT-C02F/MNT-C02FF final): 125 passed, 1 skipped
- Facade contract test: 11 passed
- Full pytest: (reported in Final Report)
- ruff check: (reported in Final Report)
- ruff format --check: (reported in Final Report)
- All public imports preserved
- SessionRecoveryRepository protocol resolution preserved
- Application-layer compatibility preserved
- No circular imports

---

## Production modules

### Files exceeding hard limit (700 lines) — legacy exceptions

| # | Path | Lines | Responsibility | Classification | Priority |
|---|---|---|---|---|---|---|
| 1 | `src/dnd_assistant/storage/vault_repository.py` | 1379 | General Vault CRUD, entity operations | DECOMPOSE | P1 |
| 2 | `src/dnd_assistant/domain/calendar.py` | 1295 | Calendar parsing, arithmetic, event queries, intercalary rules | DECOMPOSE | P1 |
| 3 | `src/dnd_assistant/storage/session_metadata.py` | 1138 | Session metadata persistence, status lifecycle | DECOMPOSE | P0 |
| 4 | `src/dnd_assistant/storage/session_events.py` | 1096 | Session event logging, event tail repair | DECOMPOSE | P0 |
| 5 | `src/dnd_assistant/storage/world_time.py` | 834 | World-time persistence and serialization | DECOMPOSE | P1 |
| 6 | `src/dnd_assistant/storage/types.py` | 741 | Storage DTOs, path types, revision types | DECOMPOSE | P2 |

### Files near soft threshold (400–700 lines) — watch

| Path | Lines | Notes |
|---|---|---|
| `src/dnd_assistant/storage/session_recovery/event_tail.py` | 501 | Cohesive event-tail recovery |
| `src/dnd_assistant/retrieval/index.py` | 632 | FTS index logic |
| `src/dnd_assistant/storage/audit.py` | 337 | OK |
| `src/dnd_assistant/storage/paths.py` | 287 | OK |
| `src/dnd_assistant/retrieval/search.py` | 279 | OK |

### All other production files

All remaining production modules are below the listed soft-review range.

---

## Test modules

### Files exceeding hard limit (1000 lines) — legacy exceptions

| # | Path | Lines | Responsibility | Classification | Priority |
|---|---|---|---|---|---|
| 1 | `tests/unit/test_retrieval_contracts.py` | 1477 | Retrieval contract tests | DECOMPOSE | P2 |
| 2 | `tests/unit/test_storage_append_fact.py` | 1229 | Storage append fact tests | DECOMPOSE | P2 |
| 3 | `tests/unit/test_fts_index.py` | 1171 | FTS index tests | DECOMPOSE | P2 |
| 4 | `tests/unit/test_session_metadata.py` | 1112 | Session metadata tests | DECOMPOSE | P1 |
| 5 | `tests/unit/test_storage_patch_repository.py` | 1103 | Storage patch repository tests | DECOMPOSE | P2 |
| 6 | `tests/unit/test_storage_vault_repository.py` | 1102 | Vault repository tests | DECOMPOSE | P2 |

### Files near or above soft threshold (700–1000 lines) — watch

| Path | Lines | Notes |
|---|---|---|
| `tests/unit/session_recovery/test_event_tail.py` | 863 | Event-tail recovery tests |
| `tests/unit/test_world_time_repository.py` | 722 | Watch |
| `tests/integration/test_vault_repository_path_races.py` | 722 | Watch |
| `tests/unit/test_calendar_event_queries.py` | 715 | Watch |
| `tests/unit/test_session_close_failures.py` | 707 | Watch |
| `tests/unit/test_session_close.py` | 706 | Watch |

### All other test files

All remaining test modules are below the test soft-review threshold.

---

## Correction-specific test file inventory

These files use correction-history naming and are recorded as legacy.
They may remain until explicitly migrated in MNT-02+.

| Path | Lines | Legacy name |
|---|---|---|
| `tests/unit/test_session_events_c03.py` | 569 | Correction C03 |
| `tests/unit/test_session_events_c03f.py` | 279 | Correction C03 follow-up |

---

## Classification summary

### Production modules

| Classification | Count | Paths |
|---|---|---|
| DECOMPOSE (P0) | 2 | `session_metadata.py`, `session_events.py` |
| DECOMPOSE (P1) | 3 | `vault_repository.py`, `calendar.py`, `world_time.py` |
| DECOMPOSE (P2) | 1 | `types.py` |
| OK | 42 | All remaining production modules |

### Test modules

| Classification | Count | Paths |
|---|---|---|
| DECOMPOSE (P1) | 1 | `test_session_metadata.py` |
| DECOMPOSE (P2) | 5 | `test_retrieval_contracts.py`, `test_storage_append_fact.py`, `test_fts_index.py`, `test_storage_patch_repository.py`, `test_storage_vault_repository.py` |
| WATCH | 6 | Various (700–1000 lines) |
| OK | 55 | All remaining test modules |

---

## Legacy exceptions for ratchet

### Production legacy exceptions (baseline = current line count)

1. `src/dnd_assistant/storage/vault_repository.py` — 1379 lines
2. `src/dnd_assistant/domain/calendar.py` — 1295 lines
3. `src/dnd_assistant/storage/session_metadata.py` — 1138 lines
4. `src/dnd_assistant/storage/session_events.py` — 1096 lines
5. `src/dnd_assistant/storage/world_time.py` — 834 lines
6. `src/dnd_assistant/storage/types.py` — 741 lines

> **MNT-02 removed:** `storage/session_recovery.py` — 1947 lines (decomposed into 8 modules, all under 700 lines)

### Test legacy exceptions (baseline = current line count)

1. `tests/unit/test_retrieval_contracts.py` — 1477 lines
2. `tests/unit/test_storage_append_fact.py` — 1229 lines
3. `tests/unit/test_fts_index.py` — 1171 lines
4. `tests/unit/test_session_metadata.py` — 1112 lines
5. `tests/unit/test_storage_patch_repository.py` — 1103 lines
6. `tests/unit/test_storage_vault_repository.py` — 1102 lines

### Legacy correction-test path allowlist

These exact paths (relative to `tests/`) are grandfathered. A file with the
same basename at a different path does NOT inherit the exception.

1. `unit/test_session_events_c03.py`
2. `unit/test_session_events_c03f.py`

> **MNT-C02 removed:** `unit/test_session_recovery_c05.py`, `unit/test_session_recovery_c05f.py` (migrated to topical test modules)

---

## MNT-02 completed

**Behavior-preserving decomposition of `session_recovery` production + tests.**

See MNT-02 section above for final structure and line counts.

---

## Notes

- No production source files were modified during MNT-01.
- No existing test files were renamed or moved during MNT-01.
- The ratchet contract test (`tests/contract/test_maintainability.py`)
  enforces the legacy exceptions recorded above.