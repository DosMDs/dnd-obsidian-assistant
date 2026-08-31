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
- [ ] `S6-01` Canonical current-world-time persistence boundary
- [ ] `S6-02` Raw session metadata persistence + ID allocation + start/status lifecycle
- [ ] `S6-03` Append-only raw note/event JSONL logging
- [ ] `S6-04` Session end/close immutability + touched IDs + processing pending
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
**Final SHA:** `d68c5dd51c377b98d7d03d475630469ceb5f4758`
**Commit message:** `feat: define session storage path contracts (S6-00)`

**Known deferred items:**

- `S6-01` and subsequent Stage-6 tasks are NOT started.
- Stage 7 remains NOT STARTED.
- No ADR was created — the path layout follows the existing Golden Vault
  convention and does not introduce a new architectural decision.