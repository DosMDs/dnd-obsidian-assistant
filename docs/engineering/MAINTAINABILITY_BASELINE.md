# Maintainability Baseline — MNT-01

**Date:** 2026-09-01
**Starting HEAD:** `c1c7855ca82d346a8f7683e2e2086419886f3f73`

This document records the repository's module-size and test-organisation
baseline at the time of MNT-01. It serves as the authoritative source for
legacy exceptions enforced by `tests/contract/test_maintainability.py`.

---

## Production modules

### Files exceeding hard limit (700 lines) — legacy exceptions

| # | Path | Lines | Responsibility | Classification | Priority |
|---|---|---|---|---|---|
| 1 | `src/dnd_assistant/storage/session_recovery.py` | 1947 | Session recovery: inspection, audit tail, event tail, partial start, repair | DECOMPOSE | P0 |
| 2 | `src/dnd_assistant/storage/vault_repository.py` | 1379 | General Vault CRUD, entity operations | DECOMPOSE | P1 |
| 3 | `src/dnd_assistant/domain/calendar.py` | 1295 | Calendar parsing, arithmetic, event queries, intercalary rules | DECOMPOSE | P1 |
| 4 | `src/dnd_assistant/storage/session_metadata.py` | 1138 | Session metadata persistence, status lifecycle | DECOMPOSE | P0 |
| 5 | `src/dnd_assistant/storage/session_events.py` | 1096 | Session event logging, event tail repair | DECOMPOSE | P0 |
| 6 | `src/dnd_assistant/storage/world_time.py` | 834 | World-time persistence and serialization | DECOMPOSE | P1 |
| 7 | `src/dnd_assistant/storage/types.py` | 741 | Storage DTOs, path types, revision types | DECOMPOSE | P2 |

### Files near soft threshold (400–700 lines) — watch

| Path | Lines | Notes |
|---|---|---|
| `src/dnd_assistant/retrieval/index.py` | 632 | FTS index logic |
| `src/dnd_assistant/storage/audit.py` | 337 | OK |
| `src/dnd_assistant/storage/paths.py` | 287 | OK |
| `src/dnd_assistant/retrieval/search.py` | 279 | OK |

### All other production files

Under 250 lines — OK.

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
| `tests/unit/test_session_recovery_c05.py` | 729 | Correction-specific; legacy |
| `tests/unit/test_world_time_repository.py` | 722 | Watch |
| `tests/integration/test_vault_repository_path_races.py` | 722 | Watch |
| `tests/unit/test_calendar_event_queries.py` | 715 | Watch |
| `tests/unit/test_session_close_failures.py` | 707 | Watch |
| `tests/unit/test_session_close.py` | 706 | Watch |

### All other test files

Under 700 lines — OK.

---

## Correction-specific test file inventory

These files use correction-history naming and are recorded as legacy.
They may remain until explicitly migrated in MNT-02+.

| Path | Lines | Legacy name |
|---|---|---|
| `tests/unit/test_session_events_c03.py` | 569 | Correction C03 |
| `tests/unit/test_session_events_c03f.py` | 279 | Correction C03 follow-up |
| `tests/unit/test_session_recovery_c05.py` | 729 | Correction C05 |
| `tests/unit/test_session_recovery_c05f.py` | 616 | Correction C05 follow-up |

---

## Classification summary

### Production modules

| Classification | Count | Paths |
|---|---|---|
| DECOMPOSE (P0) | 3 | `session_recovery.py`, `session_metadata.py`, `session_events.py` |
| DECOMPOSE (P1) | 3 | `vault_repository.py`, `calendar.py`, `world_time.py` |
| DECOMPOSE (P2) | 1 | `types.py` |
| OK | 33 | All others |

### Test modules

| Classification | Count | Paths |
|---|---|---|
| DECOMPOSE (P1) | 1 | `test_session_metadata.py` |
| DECOMPOSE (P2) | 5 | `test_retrieval_contracts.py`, `test_storage_append_fact.py`, `test_fts_index.py`, `test_storage_patch_repository.py`, `test_storage_vault_repository.py` |
| WATCH | 6 | Various (700–1000 lines) |
| OK | 48 | All others |

---

## Legacy exceptions for ratchet

### Production legacy exceptions (baseline = current line count)

1. `src/dnd_assistant/storage/session_recovery.py` — 1947 lines
2. `src/dnd_assistant/storage/vault_repository.py` — 1379 lines
3. `src/dnd_assistant/domain/calendar.py` — 1295 lines
4. `src/dnd_assistant/storage/session_metadata.py` — 1138 lines
5. `src/dnd_assistant/storage/session_events.py` — 1096 lines
6. `src/dnd_assistant/storage/world_time.py` — 834 lines
7. `src/dnd_assistant/storage/types.py` — 741 lines

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
3. `unit/test_session_recovery_c05.py`
4. `unit/test_session_recovery_c05f.py`

---

## Recommended MNT-02 target

**Behavior-preserving decomposition of `session_recovery` production + tests.**

### Proposed production structure

```
src/dnd_assistant/storage/session_recovery/
    __init__.py          — stable facade re-exporting public API
    types.py             — recovery-specific types/DTOs
    audit_tail.py        — audit-trail recovery logic
    inspection.py        — session inspection and validation
    partial_start.py     — partial-start cleanup
    event_tail.py        — event-tail repair
    repository.py        — recovery repository orchestration
```

### Proposed test structure

```
tests/unit/session_recovery/
    test_inspection.py
    test_audit_tail.py
    test_partial_start.py
    test_event_tail.py
    test_failures.py
```

Exact split to be determined by cohesion analysis during MNT-02.

---

## Notes

- No production source files were modified during MNT-01.
- No existing test files were renamed or moved during MNT-01.
- The ratchet contract test (`tests/contract/test_maintainability.py`)
  enforces the legacy exceptions recorded above.