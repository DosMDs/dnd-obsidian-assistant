# Stage 6 — Session Runtime without LLM

## Objective

Establish the session runtime foundation: safe session-storage path/layout
contracts, canonical current-world-time persistence, raw session metadata
persistence, append-only event logging, session lifecycle (start/status/end),
restart/recovery integrity, thin CLI orchestration, and Golden-Vault
integration hardening.

Stage 6 is strictly LLM-free.  No Ollama, ModelGateway, Fast Agent, Tool
Registry, ChangeSet, or post-session processing.

## Discovered baseline contracts

Before Stage 6 implementation, the following facts were established from
existing code and ADRs:

1. **Session domain model** (`domain/session.py`) — canonical strict
   `Session` with `extra="forbid"`.  No `touched_entities` or
   `processing_status` fields.  Raw sidecar metadata may contain fields
   beyond canonical `Session`; the typed metadata contract will be
   defined in a later Stage-6 task.

2. **CalendarService** (ADR-0003) — deterministic and stateless.
   It owns `world_tick <-> GameDate`, `advance_world_time`, and calendar
   event queries.  It does NOT own persisted current world time.

3. **Current-world-tick persistence** — the persisted current world tick
   facility is not yet implemented.  This is an acknowledged dependency
   gap that must be resolved before full `session start` (S6-01).

4. **VaultRepository** (`storage/vault_repository.py`) — entity-only
   repository for NPC/Location/Quest/Item.  It is NOT a raw-session
   repository.  Session/raw methods must not be added to it.

5. **atomic_write_text** (`storage/atomic.py`) — whole-file atomic
   replacement primitive.  It does NOT define append-only JSONL semantics.

6. **Golden `conversation.jsonl`** — intentionally empty in the Golden
   Vault fixture because its schema is not yet defined.

7. **Golden writable tests** — must operate on `tmp_path` copies only.

## Tasks

- [x] `S6-00` Session runtime kickoff + safe session-storage path contracts
- [x] `S6-01` Canonical current-world-time persistence boundary
- [x] `S6-02` Raw session metadata persistence + ID allocation + start/status lifecycle
- [x] `S6-03` Append-only raw note/event JSONL logging
- [x] `S6-04` Session end/close immutability + touched IDs + processing pending
- [ ] `S6-05` Restart/recovery + corrupt-state/failure-path integrity
- [ ] `S6-06` Thin CLI orchestration: session start/status/end + note
- [ ] `S6-07` Golden-Vault temp-copy integration + cross-platform/failure hardening
- [ ] `S6-08` Full Stage-6 historical review / verification / status completion

## Definition of Done

- session storage path/layout contracts are typed, tested, and read-only (S6-00)
- canonical current-world-time persistence boundary is defined and tested (S6-01)
- raw session metadata persistence + ID allocation + start/status lifecycle work (S6-02)
- append-only raw note/event JSONL logging works (S6-03)
- session end/close immutability + touched IDs + processing pending work (S6-04)
- restart/recovery + corrupt-state/failure-path integrity works (S6-05)
- thin CLI orchestration: session start/status/end + note (S6-06)
- Golden-Vault temp-copy integration + cross-platform/failure hardening (S6-07)
- full Stage-6 historical review / verification / status completion (S6-08)
- no Stage-7+ work pulled forward

## Implementation history

### S6-00 — Session runtime kickoff + safe session-storage path contracts

**Scope implemented:**

1. `src/dnd_assistant/storage/session_paths.py` — new module defining:
   - `SessionStoragePaths` — immutable value object with safe absolute
     paths for one session's storage locations.
   - `resolve_session_storage_paths(vault_root, session_id)` — typed
     resolver that validates Vault root and session ID, checks symlink
     containment, and returns `SessionStoragePaths` without creating any
     directories or files.

2. `src/dnd_assistant/storage/__init__.py` — added `SessionStoragePaths`
   and `resolve_session_storage_paths` to the curated public export surface.

3. `tests/unit/test_session_storage_paths.py` — 85 tests covering:
   - `SessionStoragePaths` value semantics (construction, equality,
     inequality, hashability, repr)
   - Valid layout for canonical session IDs (S006, S014)
   - Missing session directories (resolver is tolerant)
   - Unicode/Cyrillic session IDs
   - Invalid session ID rejection (empty, whitespace, traversal,
     path separators, Windows-invalid characters, trailing dot/space)
   - Windows reserved device names (22 names + 10 case variants +
     4 extension variants) — all rejected even on non-Windows
   - Non-reserved IDs containing reserved-name substrings (accepted)
   - Vault root failures (missing, file, invalid type)
   - Symlink safety (3 tests, skipped when OS doesn't support symlinks)
   - No-mutation invariant (resolver does not create files/directories)
   - Import/boundary checks (no models, retrieval, tools, application,
     or CLI imports)

4. `DEVELOPMENT_STATUS.md` — updated to Stage 6 IN PROGRESS with
   S6-00 task table.

5. `docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md` — created with
   objective, discovered baseline contracts, task plan, and this
   completion record.

6. `docs/stages/README.md` — added Stage 6 index entry.

**Contract decisions:**

- `SessionStoragePaths` uses `__slots__` and is immutable by convention
  (matching `DiscoveredEntityFile` style).
- Session ID validation is stricter than domain `Session.id` — it rejects
  path-unsafe characters, traversal, Windows reserved names, trailing
  dot/space, and path separators regardless of host OS.
- Vault root validation reuses `_resolve_vault_root` from `paths.py`
  (no code duplication).
- Symlink containment checks follow the same component-by-component
  pattern as `_resolve_entity_directory` in `paths.py`.
- The resolver is pure read-only — no directories or files are created.
- `_resolve_vault_root` is imported at module level (not lazy) to avoid
  test-isolation issues when boundary tests manipulate `sys.modules`.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_storage_paths.py` — 82 passed, 3 skipped
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/contract/test_boundaries.py tests/unit/test_storage_paths.py` — 267 passed, 13 skipped
- `uv run pytest` (full suite) — 2022 passed, 59 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 191 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Starting SHA:** `79d2c1d153e02a578a81fade9e0fa3098f0c2b59`
**Implementation commit:** `d68c5dd51c377b98d7d03d475630469ceb5f4758`
**Follow-up documentation commit:** `3bab266c105df46c07cb1fb3bf9951b16cd1c3e9`
**Commit message:** `feat: define session storage path contracts (S6-00)`

**Historical note:** Original S6-00 was published as two commits although
the task requested one logical commit. Published history was preserved;
no rewrite was used.

**Known deferred items:**

- `S6-01` and subsequent Stage-6 tasks are NOT started.
- Stage 7 remains NOT STARTED.
- No ADR was created — the path layout follows the existing Golden Vault
  convention and does not introduce a new architectural decision.

### S6-C00 — Session-path immutability and symlink hardening

**Review base:** `3bab266c105df46c07cb1fb3bf9951b16cd1c3e9`

**Defects found:**

1. **C00-1 — SessionStoragePaths is not actually immutable.** The class
   used `__slots__` and private attributes with property accessors, but
   assignment like `paths._session_dir = other` was still possible. The
   docstring and stage documentation claimed immutability but the
   implementation did not enforce it.

2. **C00-2 — Dangling symlink components are not reliably rejected.** The
   `_check_component_symlinks` helper used `path.exists() and
   path.is_symlink()`. For a dangling/broken symlink, `exists()` returns
   `False` while `is_symlink()` returns `True`, so the symlink was not
   detected.

3. **C00-3 — Leaf session storage locations are not symlink-checked.**
   Component checking stopped at the directory level
   (`Sessions/<id>/`, `_system/raw/sessions/<id>/`). Leaf paths
   (`Session.md`, `metadata.json`, `events.jsonl`) were appended without
   checking whether they were existing symlinks.

4. **C00-4 — Completion evidence / SHA labeling is inaccurate.** The
   stage document listed `Final SHA: d68c5dd...` but the actual repository
   head after S6-00 was `3bab266c...` (the follow-up documentation commit).

**Root causes:**

- `SessionStoragePaths` was hand-rolled with `__slots__` + properties
  instead of a `@dataclass(frozen=True)` or equivalent enforcement.
- The symlink check used `exists()` before `is_symlink()`, following the
  same pattern as the earlier `_resolve_entity_directory` in `paths.py`.
- Leaf paths were not considered as potential symlink vectors.
- The SHA label was not updated after the documentation commit was created.

**Production fixes:**

1. **`src/dnd_assistant/storage/session_paths.py`:**
   - `SessionStoragePaths` converted to `@dataclass(frozen=True, slots=True)`
     with direct public fields. The frozen dataclass raises
     `FrozenInstanceError` on any field assignment, guaranteeing true
     immutability. Equality, hashability and repr are provided by the
     dataclass generator.
   - `_check_component_symlinks` changed from `accumulated.exists() and
     accumulated.is_symlink()` to `accumulated.is_symlink()` — checked
     first, independently of `exists()`. This catches dangling symlinks.
   - New `_check_leaf_symlinks(*paths)` function checks that no leaf path
     is an existing symlink (dangling or live).
   - `resolve_session_storage_paths` now calls `_check_leaf_symlinks` on
     all five returned locations (`session_md`, `raw_metadata`,
     `raw_events`) after constructing leaf paths.

2. **`docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md`:**
   - `Final SHA` relabeled to `Implementation commit` / `Follow-up
     documentation commit` for historical accuracy.
   - Historical note added explaining the two-commit publication.
   - This S6-C00 correction record appended.

**Regression tests added (7 new tests, 92 total in file):**

- `TestSessionStoragePathsValue::test_frozen_immutable` — verifies that
  `FrozenInstanceError` is raised on assignment to any of the 5 fields.
- `TestSymlinkSafety::test_dangling_sessions_symlink_rejected` — dangling
  symlink at `Sessions/` directory component.
- `TestSymlinkSafety::test_dangling_raw_symlink_rejected` — dangling
  symlink at `_system/raw/` directory component.
- `TestSymlinkSafety::test_session_md_leaf_symlink_rejected` — existing
  live `Session.md` leaf symlink.
- `TestSymlinkSafety::test_dangling_session_md_leaf_symlink_rejected` —
  dangling `Session.md` leaf symlink.
- `TestSymlinkSafety::test_raw_metadata_leaf_symlink_rejected` — existing
  live `metadata.json` leaf symlink.
- `TestSymlinkSafety::test_dangling_raw_metadata_leaf_symlink_rejected` —
  dangling `metadata.json` leaf symlink.

All symlink tests are conditionally skipped when the OS does not support
symlink creation (Windows without developer mode).

**Causal relation — pre-correction failures:**

- `test_frozen_immutable` would have failed on `d68c5dd` because the old
  `SessionStoragePaths` allowed field assignment.
- `test_dangling_sessions_symlink_rejected` and
  `test_dangling_raw_symlink_rejected` would have failed because
  `_check_component_symlinks` used `exists() and is_symlink()`, and
  dangling symlinks have `exists() == False`.
- All four leaf-symlink tests would have failed because no leaf-path
  symlink checking existed.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_storage_paths.py` — 83 passed, 9 skipped
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/contract/test_boundaries.py tests/unit/test_storage_paths.py` — 268 passed, 19 skipped
- `uv run pytest` (full suite) — 2023 passed, 65 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 191 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Correction commit SHA:** (set after commit)
**Commit message:** `fix: harden session storage path contracts (S6-C00)`

**Historical Git note:**

```
S6-00 implementation commit:
d68c5dd51c377b98d7d03d475630469ceb5f4758

S6-00 follow-up documentation commit:
3bab266c105df46c07cb1fb3bf9951b16cd1c3e9
```

Original S6-00 was published as two commits although the task requested
one logical commit. Published history was preserved; no rewrite was used.

### S6-01 — Canonical current-world-time persistence boundary

**Scope implemented:**

1. `docs/adr/0004-current-world-time-persistence.md` — ADR-0004 documenting
   the decision to use `_system/world_time.json` as the canonical persisted
   representation, with typed schema, atomic writes, audit, and optimistic
   revision concurrency.

2. `src/dnd_assistant/domain/world_time.py` — `CurrentWorldTime` domain
   schema: strict immutable Pydantic model with `schema_version`, `type`,
   `current_world_tick` (WorldTick), and `revision` (Revision).  Rejects
   extra fields, wrong type, invalid schema version.

3. `src/dnd_assistant/storage/types.py` — `WorldTimeRepository` protocol
   with `get_current_world_time()`, `initialize_current_world_time(...)`,
   and `set_current_world_time(...)`.

4. `src/dnd_assistant/storage/world_time.py` — `ObsidianWorldTimeRepository`
   concrete implementation backed by `_system/world_time.json`:
   - Path safety: symlink checking for all components and leaf.
   - Audit path validation matching `VaultRepository` patterns.
   - Mutation environment revalidation before each write.
   - Atomic write via `atomic_write_text` with parse validator.
   - Read-back verification (hash, schema, tick, revision).
   - Audit intent/committed records with `entity_id=None`.
   - Optimistic concurrency via revision checking.
   - No monotonicity enforcement (backward tick updates accepted).

5. `src/dnd_assistant/domain/__init__.py` — added `CurrentWorldTime` export.

6. `src/dnd_assistant/storage/__init__.py` — added `ObsidianWorldTimeRepository`
   and `WorldTimeRepository` exports.

7. `tests/unit/test_world_time.py` — 17 domain tests covering:
   - Valid construction (negative, zero, positive ticks).
   - Strict type rejection (bool, str, float).
   - Revision validation (zero, bool rejected).
   - Extra fields, wrong type, wrong schema version rejected.
   - Immutability.
   - JSON roundtrip.

8. `tests/unit/test_world_time_repository.py` — 47 tests covering:
   - Path/layout (exact location, containment, no-creation on read).
   - Symlink safety (4 tests, skipped when OS doesn't support symlinks).
   - Read (valid, missing, malformed JSON, array, string, wrong schema
     version, wrong type, invalid tick, invalid revision, unknown field).
   - Initialize (missing, negative/zero/positive tick, existing, invalid
     tick types, verified readback).
   - Update (success, revision +1, stale revision, missing, backward
     update accepted, invalid tick/revision rejected).
   - Audit (intent/committed phases, operation names, entity_id=None,
     source/session preserved, before/after hashes).
   - Failure integrity (atomic write failure leaves existing unchanged,
     initialize failure leaves file missing, no committed audit on
     failure, content change race detected).

9. `tests/contract/test_boundaries.py` — 10 new boundary tests verifying:
   - `domain.world_time` does not import storage/models/retrieval/tools.
   - `storage.world_time` does not import models/retrieval/tools.

**Contract decisions:**

- `_system/world_time.json` is the canonical Vault location (ADR-0004).
- `CurrentWorldTime` is a strict `frozen=True`, `extra="forbid"` model.
- `WorldTick` and `Revision` are reused from existing canonical types.
- `GameDate` is never stored — always derived through `CalendarService`.
- `WorldTimeRepository` is a separate protocol from `VaultRepository`.
- Path safety follows the same component-by-component symlink checking
  pattern as `session_paths.py`.
- Audit path validation follows the same pattern as `vault_repository.py`.
- Revision semantics: initialize → revision 1, successful set → +1.
- No monotonicity enforcement (backward tick updates are valid).
- Missing file on read → `NotFoundError` (no silent default).
- Existing file on initialize → `ConflictError` (no silent overwrite).

**Quality-gate results:**

- `uv run pytest tests/unit/test_world_time.py` — 17 passed
- `uv run pytest tests/unit/test_world_time_repository.py` — 43 passed, 4 skipped
- `uv run pytest` (full suite) — 2160 passed, 69 skipped (3 transient failures
  in monkeypatch-based failure-integrity tests when run in full suite; all pass
  in isolation and targeted runs)
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — All files formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Starting SHA:** `fcb6492953e1c1daaf254f3ac8e6e20215b1047c`
**Implementation commit:** `92131b71637c492b7b4cc42fa2a11f5b2afab5e6`
**Commit message:** `feat: add canonical world time persistence (S6-01)`

**Explicit deferrals:**

- S6-02 and subsequent Stage-6 tasks are NOT started.
- Stage 7 remains NOT STARTED.
- No Golden Vault fixture was modified.
- `CalendarService` remains stateless (no mutable clock added).
- `CampaignState` and `campaign.yaml` were not extended with world tick.
- No Session lifecycle, Tool Layer, ModelGateway, or LLM code.

### S6-C01 — World-time path/race/test-isolation hardening

**Review base:** `7bd23d5591499e8611bd19d82aaee6fa8731276d`

**Defects confirmed:**

1. **C01-1 — Read path follows / misclassifies world-time symlinks.** The
   `get_current_world_time()` method used `path.exists()` without first
   reauthorizing canonical world-time topology.  A dangling leaf symlink
   produced `NotFoundError` instead of `StorageError`.  A live leaf symlink
   was followed without detection.

2. **C01-2 — Initialize-once second-check semantics missing.** The
   `_commit_mutation` helper used `before_hash is None` as an implicit
   mode flag for initialize, skipping the second content check entirely.
   An intervening creation between intent and write would be silently
   replaced.

3. **C01-3 — No real between-read-and-commit race test.** The existing
   `test_content_change_race_detected` changed the file before calling
   `set_current_world_time()`, testing only stale `expected_revision`
   detection — not the second check inside `_commit_mutation()`.

4. **C01-4 — No initialize race regression test.** No test verified that
   a competing file appearing between initialize intent and atomic write
   is rejected with `ConflictError`.

5. **C01-5 — Symlink tests expected wrong exception.** The live and
   dangling leaf symlink tests expected `NotFoundError` instead of
   `StorageError`.

6. **C01-6 — Test isolation failure in monkeypatch-based tests.** The
   failure-integrity tests patched `atomic_write_text` on a re-imported
   module object.  When `test_boundaries.py`'s `_clean_import` created a
   new module object, the monkeypatch targeted the wrong namespace,
   causing 5 transient failures in the full suite.

**Root causes:**

- `get_current_world_time()` had no path reauthorization before the
  `exists()` check.
- `_commit_mutation` used `before_hash is None` as an implicit mode flag
  instead of an explicit typed mode.
- The original race test only tested stale-revision detection, not the
  commit-time second check.
- The symlink tests were written with the wrong expected exception type.
- The test monkeypatch imported a fresh module object instead of using
  the module object that `ObsidianWorldTimeRepository`'s methods reference.

**Production fixes:**

1. **`src/dnd_assistant/storage/world_time.py`:**
   - Added `_MutationMode` enum (`INITIALIZE`, `UPDATE`) for explicit
     typed mutation semantics.
   - Added `_reauthorize_world_time_path(vault_root, world_time_path)`
     — a centralized helper that verifies:
     - Vault root is still a directory;
     - lexical relative path is exactly `_system/world_time.json`;
     - `_system` is not a live or dangling symlink;
     - `world_time.json` is not a live or dangling symlink;
     - resolved path remains under Vault root;
     - resolved path matches the canonical location.
   - `get_current_world_time()` now calls `_reauthorize_world_time_path`
     before the `exists()` check.  A dangling/live symlink raises
     `StorageError` before any file content is read.
   - `initialize_current_world_time()` now calls `_reauthorize_world_time_path`
     before the existence decision, distinguishing safe missing from unsafe
     symlink conditions.
   - `set_current_world_time()` now calls `_reauthorize_world_time_path`
     before the initial read.
   - `_commit_mutation` accepts an explicit `mode: _MutationMode` parameter.
     For `INITIALIZE`, the second check verifies the file is still absent
     (not a symlink, not a regular file).  For `UPDATE`, the existing
     hash-based second check is preserved.
   - Removed the now-unused `_check_component_symlinks` and
     `_check_leaf_symlink` helpers (replaced by `_reauthorize_world_time_path`).

2. **`tests/unit/test_world_time_repository.py`:**
   - `test_world_time_live_symlink_rejected` — now creates an external
     target (outside the Vault), verifies `StorageError` on read, and
     asserts the external target was not modified.
   - `test_world_time_dangling_symlink_rejected` — now expects
     `StorageError` instead of `NotFoundError`.
   - Added `test_initialize_with_dangling_symlink_rejected` — module-level
     test verifying `StorageError` on initialize with a dangling leaf symlink.
   - Added `test_update_with_live_symlink_rejected` — module-level test
     verifying `StorageError` on update with a live leaf symlink pointing
     outside the Vault, and that the external target is not modified.
   - Added `test_between_read_and_commit_race_detected` — deterministic
     test that monkeypatches `AuditService.append` to mutate
     `world_time.json` after intent is durable but before atomic write.
     Asserts `ConflictError` and no committed audit record.
   - Added `test_initialize_race_detected` — deterministic test that
     monkeypatches `AuditService.append` to create a competing
     `world_time.json` after initialize intent but before atomic write.
     Asserts `ConflictError` and no committed audit record.
   - Fixed test isolation: the module-level `import dnd_assistant.storage.world_time as _world_time_mod` captures the module object at collection time.  All monkeypatch tests use `_world_time_mod` (not a re-imported module) so the patch targets the same namespace that `ObsidianWorldTimeRepository`'s methods reference, regardless of `test_boundaries.py`'s `_clean_import` ordering.
   - Failure-integrity tests create `ObsidianWorldTimeRepository` instances
     inline (not via the `repo` fixture) to avoid stale module references.

**Quality-gate results:**

- `uv run pytest tests/unit/test_world_time.py` — 17 passed
- `uv run pytest tests/unit/test_world_time_repository.py` — 45 passed, 6 skipped
- `uv run pytest tests/contract/test_boundaries.py tests/unit/test_world_time_repository.py` — 82 passed, 6 skipped
- `uv run pytest tests/unit/test_world_time_repository.py tests/contract/test_boundaries.py` — 82 passed, 6 skipped (reverse order)
- `uv run pytest tests/unit/test_world_time.py tests/unit/test_world_time_repository.py tests/unit/test_audit_protocol.py tests/unit/test_session_storage_paths.py tests/contract/test_boundaries.py` — 182 passed, 15 skipped
- `uv run pytest` (full suite) — **2096 passed, 71 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 196 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Historical Git note:**

S6-01 was published as two commits:

```
S6-01 implementation commit:
92131b71637c492b7b4cc42fa2a11f5b2afab5e6

S6-01 follow-up documentation commit:
7bd23d5591499e8611bd19d82aaee6fa8731276d
```

The S6-01 quality-gate record in the stage document previously described
"2160 passed, 69 skipped (3 transient failures)" as a successful full-suite
gate.  This was inaccurate — 3 failures in a full suite is a failed gate.
S6-C01 corrects this: the initial S6-01 full suite had 3 transient
monkeypatch-ordering failures, and S6-C01 fixes the root cause so the
full suite now reports 0 failures.

Published S6-01 history was preserved; no rewrite was used.

**Correction commit SHA:** (set after commit)
**Commit message:** `fix: harden world time persistence integrity (S6-C01)`

### S6-02 — Raw session metadata persistence + ID allocation + start/status lifecycle

**Scope implemented:**

1. `src/dnd_assistant/storage/types.py` — `SessionMetadataRepository` protocol
   with `allocate_next_session_id()`, `create_session()`, `get_session_metadata()`,
   `list_session_metadata()`, and `get_active_session()`.

2. `src/dnd_assistant/storage/session_metadata.py` — new module defining:
   - `RawSessionMetadata` — storage-level representation wrapping a validated
     canonical `Session` plus preserved unknown extra fields.
   - `_serialize` / `_deserialize` — deterministic JSON codec with one final
     newline, compact separators, and sorted keys.
   - `_CANONICAL_SESSION_FIELDS` — frozenset ensuring extra fields never
     override canonical Session fields.
   - `ObsidianSessionMetadataRepository` — concrete filesystem-backed
     implementation with:
     - ID allocation scanning both `Sessions/` and `_system/raw/sessions/`.
     - Session creation: creates both directories, empty `events.jsonl`,
       atomically writes `metadata.json`, verified read-back.
     - Path reauthorization and mutation environment validation before writes.
     - Audit intent/committed records with `operation="session.start"`.
     - Exclusive-create semantics for `events.jsonl` via `os.open(O_CREAT|O_EXCL)`.
     - Symlink rejection at all leaf and directory levels.
     - Active-session discovery with `ConflictError` for 2+ active sessions.

3. `src/dnd_assistant/application/session_runtime.py` — `SessionRuntimeService`
   composing `SessionMetadataRepository` + `WorldTimeRepository`:
   - `start_session()`: checks no active session, reads current world tick,
     allocates ID, constructs `Session(status="active", revision=1)`, persists.
   - `get_active_session()`: delegates to repository (no in-memory cache).

4. `src/dnd_assistant/storage/__init__.py` — added `RawSessionMetadata`,
   `ObsidianSessionMetadataRepository`, `SessionMetadataRepository` exports.

5. `tests/unit/test_session_metadata.py` — 53 tests covering:
   - `RawSessionMetadata` value semantics (construct, equality, hash, repr).
   - Metadata codec: serialize, deserialize, roundtrip, invalid JSON, non-object,
     invalid Session fields, directory/ID mismatch, unknown extras preserved,
     canonical fields not overridden.
   - Path safety: 4 symlink tests (skipped when OS doesn't support symlinks).
   - ID allocation: no sessions, S001→S002, S001+S005→S006, split trees,
     S999→S1000, S1000→S1001, non-numeric ignored, collision detection.
   - Session creation: directories, events.jsonl, metadata.json, no Session.md,
     no conversation.jsonl, revision=1, status=active, readback, collision,
     no overwrite.
   - Audit: intent+committed, operation name, entity_id=None, session ID,
     source, before_hash=None, after_hash matches.
   - Failure integrity: atomic write failure, events.jsonl creation failure,
     pre-existing sessions unchanged.

6. `tests/unit/test_session_runtime.py` — 17 tests covering:
   - Start session: first ID, S005→S006, real_started_at, world_tick_start,
     status=active, real_finished_at=None, world_tick_end=None, processed=False,
     processed_model_profile=None, revision=1.
   - Get active session: none, same session after start, multiple active→Conflict.
   - Second start while active→ConflictError.
   - World time missing→NotFoundError.
   - World time not mutated by start.
   - No in-memory authoritative active session.

7. `tests/contract/test_boundaries.py` — 8 new boundary tests verifying:
   - `storage.session_metadata` does not import models/retrieval/tools/application/cli.
   - `application.session_runtime` does not import models/tools/ollama.

**Contract decisions:**

- `RawSessionMetadata` wraps `Session` + `extra_fields` dict, analogous to
  `VaultDocument` for entities.
- Canonical Session fields (`_CANONICAL_SESSION_FIELDS`) are never overridden
  by extra fields during serialization.
- ID allocation scans both `Sessions/` and `_system/raw/sessions/` for
  `^S[0-9]+$` patterns; non-numeric IDs are preserved.
- `events.jsonl` is created empty via exclusive-create (`os.open(O_CREAT|O_EXCL)`)
  — not through `atomic_write_text`.
- `Session.md` is explicitly NOT written in S6-02.
- `get_active_session()` reads Vault state each time (no in-memory cache).
- `ConflictError` for 2+ active sessions; no arbitrary selection.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_metadata.py` — 49 passed, 4 skipped
- `uv run pytest tests/unit/test_session_runtime.py` — 17 passed
- `uv run pytest tests/contract/test_boundaries.py tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py` — 111 passed, 4 skipped
- `uv run pytest tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py tests/contract/test_boundaries.py` — 111 passed, 4 skipped
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py tests/unit/test_world_time.py tests/unit/test_world_time_repository.py tests/contract/test_boundaries.py` — 359 passed, 19 skipped
- `uv run pytest` (full suite) — **2170 passed, 75 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 200 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Starting SHA:** `7a3091cc96bc1c91a21d6d96131a5d5eefccbd0e`
**Implementation commit:** (set after commit)
**Commit message:** `feat: add session start and metadata runtime (S6-02)`

**Explicit deferrals:**

- S6-03 (append-only event JSONL logging) is NOT started.
- S6-04 (session end, touched IDs, processing pending) is NOT started.
- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or event schema implemented.

### S6-03 — Append-only raw note/event JSONL logging

**Scope implemented:**

1. `src/dnd_assistant/storage/session_events.py` — new module defining:
   - `RawSessionEvent` — storage-level representation of a raw session event
     with canonical core fields (`event_id`, `real_time`, `world_tick`, `type`)
     and event-specific extra top-level fields preserved without interpretation.
   - `_serialize_event` / `_deserialize_event` — deterministic JSON codec.
   - `_validate_json_value` — recursive JSON-compatible value validation.
   - `_parse_events_jsonl` — strict JSONL parser.
   - `_allocate_event_id` — per-session event ID allocation.
   - `_append_event_line` — append-only primitive with `os.open(O_APPEND | O_BINARY)`.
   - `ObsidianSessionEventRepository` — concrete implementation.

2. `src/dnd_assistant/storage/types.py` — `SessionEventRepository` protocol.

3. `src/dnd_assistant/application/session_runtime.py` — extended with
   `record_event()` and `record_note()`.

4. `tests/unit/test_session_events.py` — 44 tests (2 symlink skipped).

5. `tests/unit/test_session_runtime.py` — 12 new tests (29 total).

6. `tests/contract/test_boundaries.py` — 5 new boundary tests.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_events.py` — 44 passed, 2 skipped
- `uv run pytest tests/unit/test_session_runtime.py` — 29 passed
- `uv run pytest` (full suite) — **2246 passed, 87 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 202 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Starting SHA:** `88c60ea758f2bfa2d2e85d779e980412bcf0922a`
**Implementation commit:** `3145165e7e18a6a3e66999658371c8960d1a2ca1`
**Commit message:** `feat: add append-only session event logging (S6-03)`

**Explicit deferrals:**

- S6-04 (session end, touched IDs, processing pending) is NOT started.
- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or `touched_entities` semantics.
- No session end, processing_status, corrupt-tail repair, or CLI commands.

### S6-C02 — Session metadata root/discovery/durability hardening

**Review base:** `e96e49be8fa2f0c2765853cbe327d5c80bf3461f`

**Defects confirmed:**

1. **C02-1 — events.jsonl creation is not durably fsynced.** The
   `_create_exclusive_event_log` helper opened the file descriptor with
   `os.open(O_CREAT | O_EXCL | O_WRONLY)` but closed it without calling
   `os.fsync()`.

2. **C02-2 — Missing canonical roots incorrectly treated as empty.** The
   `allocate_next_session_id` method silently skipped missing `Sessions/`
   or `_system/raw/sessions/` roots and returned `S001`. The
   `list_session_metadata` method returned an empty list for a missing
   `_system/raw/sessions/`.

3. **C02-3 — `parents=True` bootstrap risk in `create_session`.** Both
   `session_dir.mkdir(parents=True, exist_ok=False)` and
   `raw_dir.mkdir(parents=True, exist_ok=False)` could recreate missing
   canonical parent directories.

4. **C02-4 — Dangling discovery entry silently skipped.** In
   `list_session_metadata`, the `is_dir()` check came before
   `is_symlink()`, so a dangling symlink entry (`is_symlink() == True`,
   `is_dir() == False`) was silently ignored.

5. **C02-5 — Metadata discovery could follow live symlink.** The
   `metadata_path.exists()` check followed symlinks without first
   verifying the leaf was not a symlink.

6. **C02-6 — Missing audit intent failure regression.** No test verified
   that an audit intent append failure prevents all filesystem mutation.

7. **C02-7 — Missing audit committed failure regression.** No test verified
   that an audit committed append failure leaves persisted session data
   intact without destructive rollback.

**Production fixes:**

1. **`src/dnd_assistant/storage/session_metadata.py`:**
   - `_create_exclusive_event_log`: added `os.fsync(fd)` before
     `os.close(fd)`. If fsync fails, raises `StorageError`.
   - Added `_validate_session_runtime_roots(vault_root)` — validates
     `Sessions`, `_system`, `_system/raw`, `_system/raw/sessions`,
     `_system/audit` are not symlinks (live or dangling), exist, are
     directories, and resolve beneath the Vault root.
   - `allocate_next_session_id()`: calls `_validate_session_runtime_roots`
     before scanning IDs.
   - `create_session()`: calls `_validate_session_runtime_roots` before
     proceeding; uses `mkdir(exist_ok=False)` without `parents=True`.
   - `get_session_metadata()`: calls `_validate_session_runtime_roots`.
   - `list_session_metadata()`: calls `_validate_session_runtime_roots`;
     checks `is_symlink()` before `is_dir()` for each entry; uses
     `resolve_session_storage_paths` for path-safe discovery; rejects
     leaf metadata symlinks.
   - `_discover_occupied_numeric_ids()`: checks `is_symlink()` before
     `exists()` for both parent directories and child entries.

2. **`tests/unit/test_session_metadata.py`:** 22 new tests added:
   - `TestFsync` (3 tests): fsync called on success, fsync failure →
     `StorageError`, no session dirs on fsync failure.
   - `TestRootValidation` (7 tests): missing Sessions/raw sessions on
     allocate/create/list/get_active_session, no parent recreation.
   - `TestRootSymlinkValidation` (5 tests, skipped when OS lacks symlink
     support): live/dangling symlink Sessions/raw sessions, file
     replacing directory.
   - `TestDiscoverySymlinkSafety` (5 tests, skipped when OS lacks symlink
     support): live/dangling raw session dir symlink, live/dangling
     metadata symlink, external target not modified.
   - `TestAuditFailureIntegrity` (2 tests): audit intent failure prevents
     all mutation; audit committed failure leaves persisted data intact.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_metadata.py` — 61 passed, 14 skipped
- `uv run pytest tests/unit/test_session_runtime.py` — 17 passed
- `uv run pytest tests/contract/test_boundaries.py tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py` — 123 passed, 14 skipped
- `uv run pytest tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py tests/contract/test_boundaries.py` — 123 passed, 14 skipped (reverse order)
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py tests/unit/test_world_time.py tests/unit/test_world_time_repository.py tests/unit/test_audit_protocol.py tests/contract/test_boundaries.py` — 371 passed, 29 skipped
- `uv run pytest` (full suite) — **2182 passed, 85 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 200 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Correction commit SHA:** (set after commit)
**Commit message:** `fix: harden session metadata persistence (S6-C02)`

**Explicit deferrals:**

- S6-03 (append-only event JSONL logging) is NOT started.
- S6-04 (session end, touched IDs, processing pending) is NOT started.
- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or event schema implemented.

### S6-C03 — Event validation / portability / strict-reader hardening

**Review base:** `623fb9ca81821bffb80bec52230f9e0df32c1ded`

**Historical workflow note:**

```
S6-03 implementation was published as 3145165...
followed by docs-only commit 623fb9c...
published history preserved; no rewrite
```

**Confirmed defects:**

```
C03-1  os.O_BINARY used directly; breaks POSIX/macOS
C03-2  canonical RawSessionEvent fields are not validated before append
C03-3  invalid input may mutate events.jsonl before verification rejects it
C03-4  evt_000 is accepted although event IDs require numeric >= 1
C03-5  strict JSONL reader does not reject duplicate event IDs
C03-6  duplicate regression incorrectly tests allocator instead of parser/list reader
C03-7  event repository does not require metadata.json to exist
C03-8  runtime roots are not fully revalidated after durable audit intent
C03-9  os.write OSError can leak as raw OSError instead of StorageError
C03-10 required audit/race/write/fsync/finalization storage tests are missing
```

**Production fixes:**

1. **`src/dnd_assistant/storage/session_events.py`:**
   - **C03-1:** `os.O_BINARY` replaced with `getattr(os, "O_BINARY", 0)` module-level
     constant for POSIX/macOS portability.
   - **C03-2/3/4:** `RawSessionEvent.__init__()` now validates all canonical fields
     through dedicated helpers:
     - `_validate_event_id()` — strict str, printable, no whitespace, `^evt_[0-9]+$`,
       numeric part >= 1.
     - `_validate_aware_datetime()` — must be timezone-aware.
     - `_validate_world_tick_value()` — uses `TypeAdapter(WorldTick)` for canonical
       strict-int validation (rejects bool, float, str).
     - `_validate_event_type()` — strict str, non-empty, printable, no whitespace.
     - Extra-field collision with canonical keys and JSON-compatible value validation
       are now enforced in `__init__()`.
     - Validation happens at candidate construction time, **before** audit intent.
   - **C03-5:** `_parse_events_jsonl()` now tracks `seen_ids` and rejects duplicate
     `event_id` values across lines with `StorageError`.
   - **C03-7:** New `_validate_metadata_exists()` helper checks that `metadata.json`
     exists, is not a symlink, and is not a directory.  Called in both `list_events()`
     and `append_event()`.
   - **C03-8:** Post-intent reauthorization now calls `_validate_session_runtime_roots()`
     again and revalidates metadata sidecar existence.
   - **C03-9:** `os.write()` in `_append_event_line()` is now wrapped in its own
     `try/except OSError` that translates to `StorageError` with cause chaining.
   - Full persisted-event equality check: `persisted_event != candidate` now checks
     all fields, not just `event_id`.

2. **`tests/unit/test_session_events.py`:** Updated all append tests to create
   `metadata.json` via new `_create_session_dir()` helper.  Symlink tests updated
   to unlink events.jsonl before creating symlinks.

3. **`tests/unit/test_session_events_c03.py`:** New test file (43 tests) covering:
   - `TestRawSessionEventValidation` (22 tests): evt_000/evt_00/evt_-1/uppercase/
     whitespace/naive-datetime/bool-float-str-world_tick/empty-whitespace-type/
     extra-field-collision/non-JSON-extra/nan-extra rejection; leading-zero acceptance.
   - `TestDuplicateDetectionInParser` (4 tests): duplicate IDs in parser and
     `list_events`; evt_000 in parser and deserialize.
   - `TestMetadataExistence` (4 tests): missing metadata on list/append; live/dangling
     metadata symlink rejection.
   - `TestPortability` (1 test): `_O_BINARY` is defined as int.
   - `TestAuditSuccess` (8 tests): intent/committed phases, operation name,
     entity_id=None, session ID, source, exact before_hash, exact after_hash.
   - `TestAuditFailure` (4 tests): intent failure prevents mutation, after-intent
     concurrency race (ConflictError), append helper failure after intent,
     committed audit failure leaves persisted event.
   - `TestAppendHelperFailure` (2 tests): short write raises StorageError,
     fsync failure raises StorageError, descriptor closed.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_events.py` — 44 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03.py` — 41 passed, 2 skipped
- `uv run pytest tests/unit/test_session_runtime.py` — 29 passed
- `uv run pytest tests/contract/test_boundaries.py tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_runtime.py` — 185 passed, 4 skipped (order A)
- `uv run pytest tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_runtime.py tests/contract/test_boundaries.py` — 185 passed, 4 skipped (order B)
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/unit/test_session_metadata.py tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_runtime.py tests/unit/test_world_time.py tests/unit/test_world_time_repository.py tests/unit/test_audit_protocol.py tests/contract/test_boundaries.py` — 497 passed, 33 skipped
- `uv run pytest` (full suite) — **2308 passed, 89 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 203 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Correction commit SHA:** `b1fda9dd1f509af54d649d5b6ce2e29c660c9f46`
**Commit message:** `fix: harden session event persistence (S6-C03)`

**Explicit deferrals:**

- S6-04 (session end, touched IDs, processing pending) is NOT started.
- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or `touched_entities` semantics.
- No session end, processing_status, corrupt-tail repair, or CLI commands.

### S6-C02F — Event-log fsync test-isolation correction

**Review base:** `b5c7cb80f2afba9e1208e29763a8fcde3a5ef122`

**False-positive root cause:**

The initial S6-C02 fsync tests monkeypatched global `os.fsync`:

```python
monkeypatch.setattr(os, "fsync", failing_fsync)
```

`AuditService.append()` (via `_append_line`) also performs:

```text
write → flush → os.fsync
```

Python's `os` is the same shared module object. Therefore the
monkeypatched `os.fsync` fired during `AuditService.append(intent_record)`
— **before** `_create_exclusive_event_log()` was reached.

The tests passed for the wrong reason:

- `test_fsync_called_on_successful_creation` — `tracking_fsync` called
  `original_fsync` for the audit fsync too, so audit succeeded; the
  `fsync_called` flag was set to `True` by the audit fsync, not by the
  event-log fsync.

- `test_fsync_failure_raises_storage_error` — the failure occurred during
  audit intent. Assertions like "no session dirs" passed because audit
  intent never completed, guaranteeing zero filesystem mutation. This is
  the **audit-intent-failure** contract, not an event-log-fsync contract.

- `test_fsync_failure_does_not_create_session_dir` — same false negative.
  The assertions `assert not (vault_root / "Sessions" / "S006").exists()`
  passed because the failure aborted before any mkdir, not because event-
  log fsync was isolated.

**Production check:**

The production `os.fsync(fd)` implementation at line 316 of
`session_metadata.py` was present and correct.  No production changes were
needed.

**Test corrections (2 new direct helper tests, 1 new integration test):**

1. `test_direct_event_log_fsync_called(tmp_path, monkeypatch)` —
   Calls `_create_exclusive_event_log(path)` directly on a `tmp_path`
   file, monkeypatching `_meta_mod.os.fsync` with a tracking wrapper.
   Does NOT call `create_session()` or involve `AuditService`.  Asserts
   `called`, `path.exists()`, `path.read_bytes() == b""`.

2. `test_direct_event_log_fsync_failure_raises_storage_error(tmp_path,
   monkeypatch)` — Calls `_create_exclusive_event_log(path)` directly,
   monkeypatching `_meta_mod.os.fsync` to raise `OSError`.  Does NOT call
   `create_session()` or involve `AuditService`.  Asserts `StorageError`,
   descriptor was closed (deterministic check by re-opening the file).

3. `test_create_session_event_helper_failure_after_intent(vault_root,
   monkeypatch)` — Patches `_meta_mod._create_exclusive_event_log` with a
   stub that raises `StorageError("simulated events.jsonl durability
   failure")`.  This does NOT affect `AuditService.append()` so the audit
   intent completes successfully.  Asserts:
   - 1 intent audit record present;
   - `metadata.json` does NOT exist;
   - No committed audit record;
   - Partial owned directories MAY exist (not asserted);
   - Pre-existing sessions unchanged.

**Corrected partial-state semantics for event-log failure after intent:**

The previous S6-C02 claimed:

```text
fsync failure → no session dirs
```

This was inaccurate.  The correct semantics are:

- **Audit intent failure (phase: intent append fails):** Zero filesystem
  mutation.  Guaranteed.

- **Event-log initialization/durability failure after intent (event-log
  create or fsync fails):** Partial newly-created directories MAY exist.
  `metadata.json` is absent.  No committed audit record.  S6-05 is
  responsible for recovery.

- **Audit committed failure (phase: committed append fails):** Full
  session persistence already exists.  Intent audit exists.  Committed
  audit absent.  `StorageError` raised.  No rollback.

**Confirmation of preserved contracts:**

- `test_audit_intent_failure_prevents_all_mutation` — unchanged, still
  asserts zero filesystem mutation when audit intent fails.
- `test_audit_committed_failure_leaves_persisted_data` — unchanged, still
  asserts persisted session artifacts remain when audit committed fails.
- All S6-C02 production fixes retained: canonical root validation, no
  `parents=True` bootstrap, discovery symlink ordering, metadata leaf
  safety, audit intent/committed failure semantics.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_metadata.py` — 64 passed, 14 skipped
- `uv run pytest tests/unit/test_session_runtime.py` — 17 passed
- `uv run pytest tests/contract/test_boundaries.py tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py` — 126 passed, 14 skipped
- `uv run pytest tests/unit/test_session_metadata.py tests/unit/test_session_runtime.py tests/contract/test_boundaries.py` — 126 passed, 14 skipped
- `uv run pytest` (full suite) — **2185 passed, 85 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — All files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Correction commit SHA:** (set after commit)
**Commit message:** `test: isolate session event fsync failures (S6-C02F)`

**Explicit deferrals:**

- S6-03 (append-only event JSONL logging) is NOT started.
- S6-04 (session end, touched IDs, processing pending) is NOT started.
- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or event schema implemented.

### S6-C03F — History restoration and final event-failure coverage

**Starting SHA:** `6f8529acd31fd36760f141321b50ec556e04c0e5`

- restored accidentally deleted S6-C02 history from `623fb9c...`
- added repository-level invalid-candidate/no-intent regression (5 cases:
  empty event_type, bool world_tick, naive real_time, canonical extra-field
  collision, non-JSON-compatible extra)
- added direct ``os.write`` OSError translation regression (3 tests:
  ``StorageError`` with cause chaining, descriptor closed, no retry)
- hardened ``_validate_aware_datetime``: requires ``utcoffset() is not None``
  in addition to ``tzinfo is not None``
- S6-04 remains NOT STARTED

**Files changed:**

- `docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md` — restored S6-C02 history;
  added S6-C03F section
- `src/dnd_assistant/storage/session_events.py` — hardened
  ``_validate_aware_datetime`` with ``utcoffset()`` check
- `tests/unit/test_session_events_c03f.py` — new file (9 tests)

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_events.py` — 65 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03.py` — 41 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03f.py` — 9 passed
- `uv run pytest tests/unit/test_session_runtime.py` — 29 passed
- `uv run pytest tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_events_c03f.py tests/unit/test_session_runtime.py` — 144 passed, 4 skipped (order A)
- `uv run pytest tests/unit/test_session_runtime.py tests/unit/test_session_events_c03f.py tests/unit/test_session_events_c03.py tests/unit/test_session_events.py` — 144 passed, 4 skipped (order B)
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/unit/test_session_metadata.py tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_events_c03f.py tests/unit/test_session_runtime.py tests/unit/test_world_time.py tests/unit/test_world_time_repository.py tests/unit/test_audit_protocol.py tests/contract/test_boundaries.py` — 506 passed, 33 skipped
- `uv run pytest` (full suite) — **2317 passed, 89 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 204 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Correction commit:** (reported in Final Report)
**Commit message:** `test: finalize session event hardening (S6-C03F)`

**Explicit deferrals:**

- S6-04 (session end, touched IDs, processing pending) is NOT started.
- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or `touched_entities` semantics.
- No session end, processing_status, corrupt-tail repair, or CLI commands.

### S6-04 — Session end/close immutability + touched IDs + processing pending

**Scope implemented:**

1. **`src/dnd_assistant/storage/types.py`** — added `close_session()` to the
   `SessionMetadataRepository` protocol with full typed signature.

2. **`src/dnd_assistant/storage/session_metadata.py`:**
   - `_authorized_metadata_read()` — shared helper that validates runtime roots,
     resolves paths, and returns validated `RawSessionMetadata` with exact text
     and hash. Used by both `close_session()` and `session_events.py`.
   - `close_session()` — full implementation with:
     - Input validation (EntityId validation via `TypeAdapter`)
     - Path reauthorization and mutation environment validation
     - Exact metadata read with hash snapshot
     - Expected revision check (optimistic concurrency)
     - Closable lifecycle check (status=active, no contradictory finished fields)
     - Finish-time validation (>= start time)
     - Raw events file existence and symlink rejection
     - Fully validated new `Session` construction (status="completed", revision+1)
     - Touched-entity merge (existing order first, new appended, deduplicated)
     - `processing_status` = "pending" in extra fields
     - Unknown extras preservation
     - Audit intent before metadata mutation
     - Post-intent reauthorization (metadata hash + events hash unchanged)
     - Atomic metadata write via `atomic_write_text`
     - Verified read-back (full candidate comparison)
     - Post-write events hash verification
     - Committed audit

3. **`src/dnd_assistant/storage/session_events.py`:**
   - Added lifecycle guard to `append_event()`:
     - Pre-intent: reads authorized metadata, requires `status == "active"`
     - Post-intent recheck: re-reads metadata, verifies hash + status unchanged
     - Post-append recheck: re-reads metadata, detects concurrent close

4. **`src/dnd_assistant/application/session_runtime.py`:**
   - `end_session()` — composes `SessionMetadataRepository`,
     `WorldTimeRepository`, and `SessionEventRepository`:
     - Gets active session (exactly one)
     - Strictly validates event log via `list_events()`
     - Reads canonical current world tick (no mutation)
     - Delegates to `close_session()`

5. **`tests/unit/test_session_close.py`** — new file (40 tests):
   - `TestNormalClose` (13 tests): status, timestamps, revision, processing,
     touched entities, extras preservation, events byte-for-byte unchanged
   - `TestTouchedEntityMerge` (8 tests): existing/supplied merge, dedup,
     invalid input rejection, no-mutation invariant
   - `TestLifecyclePreconditions` (9 tests): stale revision, completed session,
     contradictory active fields, finish time before start, no-mutation
   - `TestPathSafety` (5 tests, 3 symlink-skipped): missing metadata, missing
     events, live/dangling symlink rejection
   - `TestCloseAudit` (9 tests): intent/committed phases, operation name,
     session/entity_id/source/time/hash/model_profile preservation

6. **`tests/unit/test_session_runtime.py`** — 13 new `TestEndSession` tests:
   - Active session close, completed state, audit time, world tick,
     revision, touched IDs, no-active/conflict, world time not mutated,
     post-close get_active_session/record_note/record_event rejection,
     repeated close

7. **`tests/unit/test_session_events.py`**, **`tests/unit/test_session_events_c03.py`**,
   **`tests/unit/test_session_events_c03f.py`** — updated `_create_session_dir`
   helper to produce fully valid Session metadata (required by new lifecycle guard).

**Contract decisions:**

- `close_session()` is a storage-level operation; `end_session()` is the
  application-level orchestration.
- `real_finished_at` = `audit.real_time` (no second independent timestamp).
- `world_tick_end` comes from `WorldTimeRepository.get_current_world_time()`
  (not mutated during close).
- `touched_entity_ids` are validated through canonical `EntityId` via
  `TypeAdapter`. Invalid caller input raises `ValidationError` before any
  audit intent.
- Persisted `touched_entities` that are non-list or contain non-string values
  raise `StorageError` (no silent repair).
- `processing_status` = "pending" is set only on close; no `processing_status`
  is defined for active sessions.
- Unknown extra fields survive close unchanged.
- Event-log lifecycle guard in `append_event()` uses `_authorized_metadata_read`
  for three-phase checking (pre-intent, post-intent, post-append).
- Session domain `Session` remains unchanged (no `touched_entities` or
  `processing_status` fields).

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_close.py` — 37 passed, 3 skipped
- `uv run pytest tests/unit/test_session_events.py` — 65 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03.py` — 43 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03f.py` — 9 passed
- `uv run pytest tests/unit/test_session_runtime.py` — 42 passed
- `uv run pytest tests/contract/test_boundaries.py tests/unit/test_session_close.py tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_events_c03f.py tests/unit/test_session_runtime.py` — 244 passed, 7 skipped (order A)
- `uv run pytest tests/unit/test_session_runtime.py tests/unit/test_session_events_c03f.py tests/unit/test_session_events_c03.py tests/unit/test_session_events.py tests/unit/test_session_close.py tests/contract/test_boundaries.py` — 244 passed, 7 skipped (order B)
- `uv run pytest tests/unit/test_session.py tests/unit/test_session_storage_paths.py tests/unit/test_session_metadata.py tests/unit/test_session_close.py tests/unit/test_session_events.py tests/unit/test_session_events_c03.py tests/unit/test_session_events_c03f.py tests/unit/test_session_runtime.py tests/unit/test_world_time.py tests/unit/test_world_time_repository.py tests/unit/test_audit_protocol.py tests/contract/test_boundaries.py` — 556 passed, 36 skipped
- `uv run pytest` (full suite) — **2367 passed, 92 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 205 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Starting SHA:** `5467d9140fe02ccd38d11a91ed2006318b9b335f`
**Implementation commit:** (reported in Final Report)
**Commit message:** `feat: add session close lifecycle (S6-04)`

**Explicit deferrals:**

- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- S6-07 (Golden-Vault integration) is NOT started.
- S6-08 (Stage-6 review) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or derived session artifacts.
- No recovery/truncation/repair logic.
- No CLI commands for session lifecycle.

### S6-05 — Restart/recovery + corrupt-state/failure-path integrity

**Scope implemented:**

1. `src/dnd_assistant/storage/types.py` — `SessionRecoveryRepository` protocol
   with `inspect_runtime()`, `repair_audit_tail()`, `cleanup_partial_start()`,
   and `repair_event_tail()`.

2. `src/dnd_assistant/storage/session_recovery.py` — new module defining:
   - `RecoveryIssue` — typed issue with code, session_id, operation_id,
     recoverable flag, and detail string.
   - `SessionRecoveryReport` — ordered collection of issues, sorted by
     (code, session_id, operation_id).
   - `RecoveryActionResult` — result of a recovery operation with
     before/after hashes.
   - `_content_hash()` — SHA-256 of UTF-8 content.
   - `_build_partial_start_snapshot()` — deterministic composite hash of
     partial-start artifacts (session dir, raw dir, events.jsonl).
   - `ObsidianSessionRecoveryRepository` — concrete filesystem-backed
     implementation with:
     - **inspect_runtime()**: read-only inspection of audit log, session
       directories, events files, and metadata. Detects: audit_partial_tail,
       audit_corrupt, partial_start, event_partial_tail, event_corrupt,
       metadata_corrupt, multiple_active_sessions, unresolved_audit_intent,
       unsafe_session_path.
     - **repair_audit_tail()**: self-targeting recovery for final audit tail.
       No intent phase (audit cannot write intent into corrupt self).
       Repair modes: append_missing_newline, truncate_invalid_tail.
       Recovery marker appended after verified repair.
     - **cleanup_partial_start()**: two-phase audit (intent → committed)
       cleanup of provably owned partial session starts. Requires unmatched
       session.start intent, safe empty artifacts only. No recursive deletion.
     - **repair_event_tail()**: two-phase audit repair of final event-log
       tail. Valid missing-LF record preserved via append. Invalid incomplete
       tail truncated. Complete earlier events unchanged.

3. `src/dnd_assistant/application/session_recovery.py` — `SessionRecoveryService`
   composing `SessionRecoveryRepository`. No filesystem calls. No model/tool
   imports.

4. `src/dnd_assistant/storage/__init__.py` — added `ObsidianSessionRecoveryRepository`,
   `RecoveryActionResult`, `RecoveryIssue`, `SessionRecoveryReport`,
   `SessionRecoveryRepository` exports.

5. `src/dnd_assistant/application/__init__.py` — added `SessionRecoveryService`
   export.

6. `tests/unit/test_session_recovery.py` — 29 tests covering:
   - `RecoveryIssue`, `SessionRecoveryReport`, `RecoveryActionResult` value
     semantics (construct, defaults, equality, hash, repr).
   - Inspection read-only: no file creation, clean active/completed session.
   - Partial start detection: with intent (recoverable), without intent
     (not recoverable), unexpected file (not recoverable), non-empty events
     (not recoverable).
   - Event tail detection: missing LF (recoverable), incomplete tail
     (recoverable), middle-line corrupt (not recoverable), duplicate IDs
     (not recoverable).
   - Metadata corruption detection.
   - Multiple active sessions detection.
   - Unresolved audit intent diagnostics.
   - Audit tail detection: missing LF (parseable — no issue), incomplete
     tail (recoverable), middle-line corrupt (not recoverable).

7. `tests/unit/test_session_recovery_failures.py` — 22 tests covering:
   - `cleanup_partial_start`: safe cleanup succeeds, only known-empty
     artifacts removed, other sessions untouched.
   - `cleanup_partial_start` failures: unexpected file, non-empty events,
     missing intent all raise StorageError.
   - `cleanup_partial_start` audit: intent+committed records, exact
     before/after composite hash, intent failure → zero cleanup.
   - `repair_event_tail`: missing-LF append, invalid tail truncation,
     clean log raises StorageError, middle-line corrupt raises StorageError.
   - `repair_event_tail` audit: intent+committed, exact hashes, intent
     failure → bytes unchanged.
   - `repair_audit_tail`: missing-LF append, invalid tail truncation,
     middle-line corrupt raises StorageError.
   - `repair_audit_tail` marker: correct semantics (operation, phase,
     session/entity_id None, before/after hashes), race → ConflictError,
     marker append failure → repaired audit remains.

8. `tests/integration/test_session_restart.py` — 7 tests covering:
   - Start → notes/events → destroy → reconstruct → status works.
   - Event ID continuity after reconstruction (evt_001 → evt_002 → evt_003).
   - World time read from persisted world_time.json after reconstruction.
   - Active session can be ended after reconstruction.
   - Completed session survives reconstruction (twice).
   - Closed events readable after reconstruction.
   - Append to completed session still rejected after reconstruction.

**Contract decisions:**

- Recovery is **explicit**, never constructor-side magic. Normal repository
  reads continue to fail loudly on corruption.
- `inspect_runtime()` is read-only — no writes, truncations, or deletions.
- `SessionRecoveryRepository` is a separate persistence aggregate from
  `SessionMetadataRepository`, `SessionEventRepository`, and
  `WorldTimeRepository`.
- Partial-start cleanup requires unmatched `session.start` intent + safe
  empty artifacts. No audit ownership → no auto-recovery.
- No recursive deletion (`shutil.rmtree`). Only exact known-empty artifacts
  are removed.
- Event-tail recovery touches only the final unterminated tail. Complete
  earlier events are never modified.
- Audit-tail recovery is a self-targeting exception: no intent phase
  (audit cannot write intent into corrupt self). Recovery marker appended
  after verified repair.
- No synthesized historical committed records. Unmatched intents are
  reported as diagnostics, not repaired.
- Multiple active sessions are reported but not auto-resolved.
- Corrupt metadata is reported but not reconstructed.
- Restart uses persisted Vault state only — no authoritative in-memory
  session registry. Event IDs allocated from persisted log.
- World time read from persisted `world_time.json` after restart.
- No lock manager — exact hashes + path reauthorization + optimistic race
  detection.
- No recovery of derived files (Session.md, Notes.md, Summary.md, etc.).
- No `conversation.jsonl`.
- No Golden Vault fixture modification.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_recovery.py` — 29 passed
- `uv run pytest tests/unit/test_session_recovery_failures.py` — 22 passed
- `uv run pytest tests/integration/test_session_restart.py` — 7 passed
- `uv run pytest tests/unit/test_session_runtime.py` — 45 passed
- `uv run pytest tests/unit/test_session_events.py` — 65 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03.py` — 41 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03f.py` — 9 passed
- `uv run pytest tests/unit/test_session_close.py` — 37 passed, 3 skipped
- `uv run pytest tests/unit/test_session_close_failures.py` — 30 passed, 1 skipped
- `uv run pytest tests/unit/test_session_event_lifecycle.py` — 4 passed
- `uv run pytest tests/unit/test_audit_protocol.py` — 6 passed
- Boundary order A (boundaries first) — 351 passed, 13 skipped
- Boundary order B (boundaries last) — 351 passed, 13 skipped
- Broader Stage-6 gate — 651 passed, 37 skipped
- `uv run pytest` (full suite) — **2462 passed, 93 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 214 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — No whitespace errors

**Starting SHA:** `16e049c0d5b358e7467ec749fb18e3adcde82aad`
**Implementation commit:** (reported in Final Report)
**Commit message:** `feat: add session runtime recovery (S6-05)`

**Explicit deferrals:**

- S6-06 (CLI orchestration) is NOT started.
- S6-07 (Golden-Vault integration) is NOT started.
- S6-08 (Stage-6 review) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or derived session artifacts.
- No CLI commands for session lifecycle.

**Review base:**
`46a9909967cbfe282c1d05e3d0a3957299d1c19a`

**Confirmed findings:**

- expected_revision lacked strict Revision validation
- world_tick_end lacked strict WorldTick validation
- concrete close_session typing used raw int/Sequence[str] instead of
  Revision/WorldTick/Sequence[EntityId]
- scalar touched_entity_ids (str) silently iterated as characters
- corrupt non-string processing_status silently overwritten
- post-write path reauthorization missing (roots, resolve, mutation env)
- post-write metadata/events symlink/directory safety missing
- append_event missing-metadata error boundary weakened to
  (StorageError, NotFoundError)
- close failure/race regression suite absent
- exact close after_hash audit regression absent
- event close/append race regression suite absent
- application corrupt-log/missing-world-time guards absent

**Production fixes:**

1. **`src/dnd_assistant/storage/session_metadata.py`:**
   - Added canonical `Revision` validation via `TypeAdapter(Revision)`
     before any audit intent or mutation.
   - Added canonical `WorldTick` validation via `TypeAdapter(WorldTick)`.
   - Changed concrete `close_session` signature to use
     `expected_revision: Revision`, `world_tick_end: WorldTick`,
     `touched_entity_ids: Sequence[EntityId]`.
   - Added scalar `str`/`bytes`/`bytearray` rejection for
     `touched_entity_ids` before iteration.
   - Added persisted `processing_status` shape validation: non-str values
     raise `StorageError` before overwrite.
   - Added full `persisted_meta == candidate_meta` equality check.
   - Added post-write path reauthorization:
     `_validate_session_runtime_roots` → `resolve_session_storage_paths`
     → `_validate_mutation_environment`.
   - Added post-write metadata/events safety checks: reject symlinks,
     missing files, directories.
   - Added `from dnd_assistant.domain.calendar import WorldTick` and
     `from dnd_assistant.domain.types import Revision`.

2. **`src/dnd_assistant/storage/session_events.py`:**
   - `append_event` now wraps `_authorized_metadata_read` in a
     `try/except NotFoundError` that translates to `StorageError`,
     restoring the strict contract.
   - Added `from dnd_assistant.errors import NotFoundError`.

3. **`tests/unit/test_session_events.py`:**
   - `test_missing_events_file_append_raises`: changed expected exception
     from `(StorageError, NotFoundError)` to `StorageError` with correct
     match pattern.

4. **`tests/unit/test_session_events_c03.py`:**
   - `test_append_event_missing_metadata_raises`: same strict fix.

5. **`tests/unit/test_session_close_failures.py`** (new — 10 tests):
   - `TestExactCloseAuditHash`: before_hash and after_hash exact audit
     regression.
   - `TestAuditIntentFailure`: intent failure prevents all mutation.
   - `TestAtomicWriteFailure`: atomic write failure after intent leaves
     old metadata intact with intent audit present.
   - `TestMetadataChangedAfterIntent`: competitor metadata after intent
     raises ConflictError.
   - `TestEventsChangedAfterIntent`: competitor event after intent raises
     ConflictError.
   - `TestEventsChangedAfterMetadataClose`: competitor event after
     metadata close raises StorageError; completed metadata remains.
   - `TestCommittedAuditFailure`: committed audit failure leaves completed
     metadata without committed audit.
   - `TestRuntimeRootRace`: missing runtime root after intent raises
     StorageError.
   - `TestPostWriteSymlinkRace`: events symlink after metadata write
     raises StorageError (skipped when OS lacks symlink support).

6. **`tests/unit/test_session_event_lifecycle.py`** (new — 4 tests):
   - `TestClosedSessionEventAppend`: list_events succeeds on closed
     session; append_event raises ConflictError.
   - `TestCloseWinsAfterEventIntent`: close after event intent but before
     append raises ConflictError.
   - `TestCloseWinsAfterEventAppend`: close after physical event append
     raises StorageError.

7. **`tests/unit/test_session_runtime.py`** — 3 new test classes:
   - `TestCorruptEventLogPreventsClose`: corrupt event log prevents
     end_session; active session preserved.
   - `TestMissingWorldTimePreventsClose`: missing world time prevents
     end_session; active session preserved.
   - `TestCloseDelegation`: verifies close_session called exactly once
     with exact arguments (session_id, revision, tick, touched IDs,
     audit context).

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_close.py` — 37 passed, 3 skipped
- `uv run pytest tests/unit/test_session_close_failures.py` — 9 passed, 1 skipped
- `uv run pytest tests/unit/test_session_event_lifecycle.py` — 4 passed
- `uv run pytest tests/unit/test_session_events.py` — 44 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03.py` — 41 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03f.py` — 8 passed
- `uv run pytest tests/unit/test_session_runtime.py` — 45 passed
- Boundary order A (boundaries first) — 260 passed, 8 skipped
- Boundary order B (boundaries last) — 260 passed, 8 skipped
- Broader lifecycle gate — 572 passed, 37 skipped
- `uv run pytest` (full suite) — **2383 passed, 93 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 207 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — No whitespace errors

**Correction commit SHA:** (reported in Final Report)
**Commit message:** `fix: harden session close integrity (S6-C04)`

**Explicit deferrals:**

- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- S6-07 (Golden-Vault integration) is NOT started.
- S6-08 (Stage-6 review) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or derived session artifacts.
- No recovery/truncation/repair logic.
- No CLI commands for session lifecycle.

### S6-C04F — Final close-validation / audit-intent regression coverage

**Starting SHA:** `65a491edd6da360982004dad15eff216a5f636f3`

**Review finding:**

- the S6-C04 test named `TestAuditIntentFailure` actually exercised
  atomic-write failure after a successful intent, not a genuine audit-intent
  failure;
- strict `Revision`/`WorldTick`/scalar `touched_entity_ids`/`processing_status`
  production guards lacked repository-level regression coverage;
- `after_hash` test used reserialization instead of actual persisted bytes.

**Correction tests** (all in `tests/unit/test_session_close_failures.py`):

1. **`TestAtomicWriteFailure`** — renamed from `TestAuditIntentFailure`.
   Proves: audit intent succeeds, `atomic_write_text` fails before replacement,
   `StorageError`, old metadata/events unchanged, session remains active,
   exactly one intent record, zero committed records.

2. **`TestGenuineAuditIntentFailure`** — new. Proves: `AuditService.append`
   raises before writing the intent record, `StorageError`, metadata/events
   unchanged, session remains active, **zero** audit records for the operation,
   `atomic_write_text` call count == 0.

3. **`TestStrictRevisionValidation`** — new parametrized class (6 cases:
   `True`, `False`, `1.0`, `"1"`, `0`, `-1`). Every value: `ValidationError`,
   metadata/events unchanged, zero audit records.

4. **`TestStrictWorldTickValidation`** — new parametrized class (4 invalid
   cases: `True`, `False`, `1.0`, `"15000"`). Same invariants. Also proves
   negative valid tick (`-500`) is accepted.

5. **`TestScalarTouchedEntityIds`** — new parametrized class (3 cases:
   `"npc_varos"`, `b"npc_varos"`, `bytearray(b"npc_varos")`). Every value:
   `ValidationError`, metadata/events unchanged, zero audit records.

6. **`TestProcessingStatusCorruption`** — new parametrized class (4 cases:
   `123`, `None`, `["pending"]`, `{"state": "pending"}`). Every value:
   `StorageError`, metadata/events unchanged, zero audit records, session
   remains active. Also proves pre-existing string `processing_status` is
   accepted and replaced with `"pending"`.

7. **`TestExactCloseAuditHashStrengthened`** — new. `test_after_hash_from_exact_persisted_file`:
   computes expected hash from actual persisted metadata file via
   `_read_exact_text`. Asserts exactly 1 intent + 1 committed record.
   `test_before_hash_with_exact_phase_counts`: same exact-file approach with
   explicit phase counts.

**Production changes:** zero.

**Quality-gate results:**

- `uv run pytest tests/unit/test_session_close_failures.py` — 30 passed, 1 skipped
- `uv run pytest tests/unit/test_session_close.py` — 37 passed, 3 skipped
- `uv run pytest tests/unit/test_session_event_lifecycle.py` — 4 passed
- `uv run pytest tests/unit/test_session_events.py` — 65 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03.py` — 41 passed, 2 skipped
- `uv run pytest tests/unit/test_session_events_c03f.py` — 9 passed
- `uv run pytest tests/unit/test_session_runtime.py` — 45 passed
- Boundary order A (boundaries first) — 281 passed, 8 skipped
- Boundary order B (boundaries last) — 281 passed, 8 skipped
- Broader lifecycle gate — 593 passed, 37 skipped
- `uv run pytest` (full suite) — **2404 passed, 93 skipped — 0 failed, 0 errors**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 207 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — No whitespace errors

**Correction commit:** (reported in Final Report)
**Commit message:** `test: finalize session close hardening (S6-C04F)`

**Explicit deferrals:**

- S6-05 (restart/recovery) is NOT started.
- S6-06 (CLI orchestration) is NOT started.
- S6-07 (Golden-Vault integration) is NOT started.
- S6-08 (Stage-6 review) is NOT started.
- Stage 7 (Tool Registry) remains NOT STARTED.
- No Ollama, ModelGateway, Fast Agent, ChangeSet, or post-session processing.
- No Golden Vault fixture was modified.
- No `Session.md`, `conversation.jsonl`, or derived session artifacts.
- No recovery/truncation/repair logic.
- No CLI commands for session lifecycle.