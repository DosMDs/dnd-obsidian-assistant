# D&D Session Assistant — Development Status

**Last updated:** 2026-08-30
**Current milestone:** `v0.1-dev — Vault Core`
**Current stage:** `Stage 3 — Vault Repository`
**Status:** `DONE`

## Status model

Use only:

- `NOT STARTED`
- `IN PROGRESS`
- `BLOCKED`
- `DONE`

A task is not `DONE` merely because code was generated. Completion requires the implementation, required tests, successful relevant checks, and final diff review.

## Stage progress

| Stage | Status | Started | Completed |
|---|---|---|---|
| 0. Environment | DONE | 2026-08-27 | 2026-08-27 |
| 1. Project skeleton + contracts | DONE | 2026-08-27 | 2026-08-30 |
| 2. Domain schemas | DONE | 2026-08-30 | 2026-08-30 |
| 3. Vault Repository | DONE | 2026-08-30 | 2026-08-30 |
| 4. Calendar | NOT STARTED | — | — |
| 5. Retrieval + Entity Resolution | NOT STARTED | — | — |
| 6. Session Runtime without LLM | NOT STARTED | — | — |
| 7. Tool Registry / Executor | NOT STARTED | — | — |
| 8. Model Gateway / Ollama | NOT STARTED | — | — |
| 9. Fast Agent | NOT STARTED | — | — |
| 10. ChangeSet | NOT STARTED | — | — |
| 11. Post-session Processor | NOT STARTED | — | — |
| 12. Campaign State | NOT STARTED | — | — |
| 13. Bootstrap | NOT STARTED | — | — |
| 14. Evals / Hardening | NOT STARTED | — | — |

## Stage 0 completion record

The user explicitly moved development to the next stage on 2026-08-27.

The environment stage is therefore recorded as `DONE`. Command output and machine-state evidence were not captured in the project chat. If any environment gate later fails, reopen the relevant `ENV-*` task instead of working around it in later layers.

Expected environment gates remain:

```text
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run dnd --help
```

## Stage 1 — Project skeleton + contracts

### Goal

Establish stable project boundaries and shared error contracts **without implementing application features or coupling any core layer to Ollama**.

### Scope

Primary interfaces/contracts to establish or inventory:

- `ModelGateway`
- `VaultRepository`
- `SearchService`
- `EntityResolver`
- `CalendarService`
- `SessionService`
- `ToolRegistry`
- `ToolExecutor`
- `PostSessionProcessor`
- `BootstrapService`
- `AuditService`

Shared error hierarchy:

```text
DndAssistantError
├── ValidationError
├── NotFoundError
├── ConflictError
├── AmbiguousEntityError
├── StorageError
├── ModelError
└── LockError
```

### Tasks

- [x] `CTR-001` Verify/create the package skeleton and importable modules.
- [x] `CTR-002` Add the shared project error hierarchy.
- [x] `CTR-003` Define boundary protocols/interfaces where signatures can be expressed without inventing premature domain models.
- [x] `CTR-004` Document responsibilities and dependency direction for every core interface.
- [x] `CTR-005` Add smoke/contract tests for imports and boundary assumptions.
- [x] `CTR-006` Verify that domain/storage modules do not depend on Ollama/provider implementations.
- [x] `CTR-007` Run targeted tests and project quality gates.
- [x] `CTR-008` Review the diff and update this status file.

### Important constraint

Do **not** use `dict[str, Any]` or placeholder provider-specific types merely to force every future method signature into Stage 1.

If a contract requires a domain type whose semantics belong to Stage 2, define the interface responsibility now and finalize that typed method signature alongside the domain type in Stage 2.

### Definition of Done

- package skeleton imports successfully;
- shared error hierarchy exists and is tested;
- core boundaries are explicit and documented;
- no domain/storage dependency on Ollama or a concrete model;
- no Vault persistence implementation is pulled forward from Stage 3;
- no Calendar implementation is pulled forward from Stage 4;
- relevant tests pass;
- `uv run pytest` passes when feasible;
- `uv run ruff check .` passes;
- `uv run ruff format --check .` passes;
- final diff is reviewed;
- `DEVELOPMENT_STATUS.md` is updated.

### S2-07 Stage 2 completion record

**Review range:** `5a38ea0..HEAD` (pre-Stage-2 boundary through S2-06)

**Implemented domain types/models:**
- `EntityId` — validated printable-Unicode string identifier
- `EntityType` — MVP-only: npc, location, quest, item
- `KnowledgeStatus` — epistemic: confirmed, reported, rumor, inferred, unknown
- `Visibility` — player, dm, system
- `Provenance` — manual, session, bootstrap, import, model_inference
- `Revision` — strict int >= 1, no bool/string coercion
- `Entity` — base schema with schema_version, id, type, name, status, visibility, knowledge_status, session refs, timestamps, revision, tags; `extra="forbid"`
- `Session` — schema with id, type discriminator, status, real timestamps, world_tick range, processed flag, model profile, revision; `extra="forbid"`
- `TemporalCertainty` — exact, approximate, range, unknown (separate from KnowledgeStatus)
- `TimelineEvent` — schema with id, type discriminator, name, status, certainty, importance, world_tick fields with model-level temporal consistency validation, location, visibility, revision; `extra="forbid"`
- `CampaignState` — compact snapshot with EntityId references (current_location, active_quests, important_npcs, upcoming_deadlines) and printable-string lists (party_goals, unresolved_threads); `extra="forbid"`

**Architectural boundaries confirmed:**
- `EntityType` is MVP-only (no timeline_event, campaign_state, session added)
- `TemporalCertainty` is separate from `KnowledgeStatus`
- No Stage 4 calendar implementation (no WorldTick value object, GameDate, CalendarDefinition, CalendarService)
- No storage implementation (no VaultRepository, AuditService, atomic writes)
- No retrieval implementation (no SearchService, EntityResolver)
- No session runtime implementation (no SessionService)
- No tool-layer implementation (no ToolRegistry, ToolExecutor)
- No ModelGateway implementation/provider coupling
- No CampaignState processing implementation (no state generation, ChangeSet application)
- All deferred contracts remain correctly assigned to later stages
- Domain dependency direction is clean (no imports from storage, models, retrieval, tools, application, cli)

**Final quality-gate results:**
- `uv run pytest tests/unit/test_domain_types.py` — 53 passed
- `uv run pytest tests/unit/test_entity.py` — 119 passed
- `uv run pytest tests/unit/test_session.py` — 103 passed
- `uv run pytest tests/unit/test_timeline_event.py` — 137 passed
- `uv run pytest tests/unit/test_campaign_state.py` — 89 passed
- `uv run pytest tests/unit/test_imports.py tests/unit/test_gateway_protocol.py tests/unit/test_audit_protocol.py tests/unit/test_tool_registry_protocol.py` — 13 passed
- `uv run pytest` (full suite) — 551 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 66 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S2-07:** None

**Code/test changes during S2-07:** None (only DEVELOPMENT_STATUS.md updated)

**Stage 3 status:** IN PROGRESS — S3-04 complete.

## Stage 3 — Vault Repository

### Goal

Implement the trusted Vault persistence layer for Obsidian Markdown/YAML entities, providing create, read, update, and append operations with atomic writes, optimistic concurrency, path safety, Markdown body preservation, and audit logging.

### Tasks

- [x] `S3-00` Stage kickoff + repository/storage contracts
- [x] `S3-01` Markdown/YAML document codec
- [x] `S3-02` Vault path safety + entity directory/discovery policy
- [x] `S3-03` Atomic write primitive (corrected: symlink, BaseException, validator transparency, lifecycle)
- [x] `S3-04` AuditRecord + AuditService
- [x] `S3-05` create_entity / get_entity / list_entities
- [x] `S3-06` patch_entity + optimistic concurrency
- [x] `S3-07` append_entity_fact
- [x] `S3-08` integration/failure tests (corrected: race safety + mutation-time reauthorization)
- [x] `S3-09` full Stage 3 verification/diff/status

### S3-00 completion record

**Review range:** `22a21d3..HEAD` (Stage 2 completion through S3-00)

**Changes:**

1. **DEVELOPMENT_STATUS.md** — transitioned to Stage 3 IN PROGRESS, added S3-00 task inventory
2. **storage/types.py** (new) — storage-level types:
   - `VaultDocument` — wraps validated domain `Entity` + `extra_frontmatter` dict + Markdown `body`
   - `EntityDirectory` — StrEnum mapping EntityType to Vault subdirectories (Characters/NPCs, Locations, Quests, Items)
   - `VaultRepository` — runtime-checkable Protocol with create/get/list/patch/append signatures
3. **storage/__init__.py** — exports EntityDirectory, VaultDocument, VaultRepository
4. **storage/audit.py** — updated docstring to reflect Stage 3 ownership (implementation deferred to S3-04)
5. **tests/unit/test_storage_types.py** (new) — 27 tests covering VaultDocument construction/properties, EntityDirectory mapping, VaultRepository protocol structure, import smoke tests, and boundary checks

**Decisions made:**
- `VaultDocument` lives in `storage/` (not `domain/`) — persistence concern, not a domain concept
- Extra frontmatter preserved as `dict[str, object]` — no weakening of `Entity.extra="forbid"`
- `VaultRepository` is a `Protocol` (not ABC) — follows Stage 1 deferred-contract pattern
- `EntityDirectory` is a `StrEnum` — simple, serializable, no premature path abstraction
- Patch/fact DTOs explicitly deferred to S3-06/S3-07 — no placeholder APIs invented

**Decisions intentionally deferred to later S3 tasks:**
- Markdown/YAML parser/serializer (S3-01)
- Filesystem entity scanning and path safety (S3-02)
- Atomic write primitive (S3-03)
- AuditRecord + AuditService (S3-04)
- create/get/list persistence (S3-05)
- patch_entity semantics and revision ownership (S3-06)
- append_entity_fact semantics (S3-07)
- Integration/failure tests (S3-08)
- Full Stage 3 verification (S3-09)

**ADR assessment:** No ADR required. All architectural decisions follow established project patterns (Protocol for deferred contracts, storage-level wrapper for persistence concerns, StrEnum for typed mappings).

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_types.py` — 27 passed
- `uv run pytest` (full suite) — 578 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 68 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S3-00:** None

**Code/test changes during S3-00:** 5 files (3 modified, 2 new), focused on storage contracts only.

### S3-01 completion record

**Review range:** S3-00 completion through S3-01

**Changes:**

1. **storage/markdown.py** (new) — pure-text Markdown/YAML document codec:
   - `parse(text: str) -> VaultDocument` — parses Obsidian Markdown with YAML frontmatter
   - `serialize(document: VaultDocument) -> str` — serializes back to Obsidian Markdown
   - Frontmatter delimiter: standalone `---` at start of document, closing `---` as standalone line
   - CRLF/LF delimiter support; body preservation character-for-character
   - Canonical Entity fields extracted via `Entity.model_validate()`; extras stored in `extra_frontmatter`
   - Collision detection: extra keys overlapping canonical Entity fields rejected with `ValidationError`
   - Non-string YAML keys rejected
   - Uses `ruamel.yaml` with `typ="safe"`, `default_flow_style=False`, `allow_unicode=True`
   - All errors translated to `dnd_assistant.errors.ValidationError` with original cause preserved
2. **storage/__init__.py** — exports `parse`, `serialize`
3. **tests/unit/test_storage_markdown.py** (new) — 71 tests covering:
   - Frontmatter boundary detection (7 tests)
   - Canonical parse (6 tests: minimal, all EntityTypes, tags, session refs, empty body, import)
   - Extra frontmatter (9 tests: scalar, list, nested, boolean, number, null, multiple keys, semantic round trip)
   - Body preservation (11 tests: empty, heading, blank lines, trailing newline, no trailing newline, CRLF source, `---` in body, code fences, wikilinks, Unicode, round trip, only newlines)
   - Invalid documents (15 tests: not a string, missing opener/closer, malformed YAML, sequence/scalar root, missing required fields, invalid type/revision/datetime, non-string keys, empty document, only opener, empty frontmatter)
   - Serialization (9 tests: round trips, collision rejection, canonical-first order, delimiter structure, import)
   - Round-trip integration (9 parametrized cases)
   - Import/boundary tests (5 tests: module importable, re-exported, no model/retrieval/tool imports)

**Codec API established:**
- `parse(text: str) -> VaultDocument`
- `serialize(document: VaultDocument) -> str`

**Frontmatter delimiter rules:**
- Opening `---` must be at position 0 of the document
- Closing `---` must be a standalone line (only whitespace allowed after `---`)
- A `---` inside YAML content (e.g. block scalars) does not terminate frontmatter
- A `---` inside Markdown body is not confused with frontmatter

**Canonical vs extra field split:**
- Canonical fields: `Entity.model_fields.keys()` (derived dynamically from Pydantic model)
- Extra fields: all other YAML mapping keys stored in `VaultDocument.extra_frontmatter`
- Collision during serialization: raises `ValidationError`

**YAML preservation guarantee:**
- Guaranteed: key/value semantic preservation through parse/serialize
- NOT guaranteed: YAML comments, anchors/aliases, scalar quote style, flow/block formatting, exact whitespace, key ordering, byte-identical output

**Markdown body preservation invariant:**
- `VaultDocument.body` is preserved character-for-character through `parse → serialize`
- No `.strip()`, `.rstrip()`, or whitespace normalisation applied

**Validation/error behaviour:**
- All parse/serialize failures produce `dnd_assistant.errors.ValidationError`
- Original parser/Pydantic exception preserved as `cause`
- Malformed documents never produce partially-valid Entity

**Round-trip guarantees:**
- `parse(serialize(document))` preserves: `entity` equality, `extra_frontmatter` semantic equality, `body` exact equality
- `serialize(parse(source))` preserves: semantic frontmatter equivalence, exact body

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_markdown.py` — 71 passed
- `uv run pytest tests/unit/test_storage_types.py` — 27 passed
- `uv run pytest` (full suite) — 652 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 70 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S3-01:** None

**Code/test changes during S3-01:** 3 files (1 modified, 2 new), focused on Markdown/YAML codec only.

**Scope exclusions confirmed:**
- No filesystem access, path validation, atomic writes, audit, repository CRUD, patch, append, locks, migrations, Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet.

### S3-02 completion record

**Review range:** S3-01 completion through S3-02 (including S3-02 correction)

**Changes (original S3-02):**

1. **storage/paths.py** (new) — Vault path safety and entity-file discovery:
   - `DiscoveredEntityFile` — immutable result type with `entity_type` and `path` properties; supports equality, hashing, repr; no EntityId or file contents
   - `entity_directory(vault_root, entity_type)` — resolves canonical entity directory path under vault root
   - `resolve_entity_path(vault_root, entity_type, relative_path)` — safe relative-path resolution with:
     - `..` traversal rejection (structural check, not resolved-path)
     - absolute path rejection
     - containment checks via `pathlib.relative_to` (inside entity directory AND inside vault root)
     - Markdown-only suffix enforcement (case-insensitive)
   - `discover_entity_files(vault_root, entity_type=None)` — recursive Markdown discovery:
     - scans only approved MVP entity directories (Characters/NPCs, Locations, Quests, Items)
     - ignores non-Markdown files, symlinked files, symlinked directories
     - missing entity directory yields zero candidates (no directory creation)
     - canonical entity path that exists as a file raises `StorageError`
     - deterministic ordering by Vault-relative POSIX path (casefold)
     - filesystem `OSError` translated to `StorageError` with cause preserved
   - Internal `_resolve_vault_root` — normalises to canonical absolute resolved path; rejects missing/non-directory roots
   - Internal `_has_traversal` — structural check for `..` components and absolute paths
   - No Markdown parsing, no EntityId inference from filenames, no file reading
2. **storage/__init__.py** — exports `DiscoveredEntityFile`, `discover_entity_files`, `entity_directory`, `resolve_entity_path`
3. **tests/unit/test_storage_paths.py** (new) — 58 tests (55 pass, 3 symlink tests skipped on Windows without symlink privileges)

**S3-02 correction (canonical-directory symlink hardening):**

1. **storage/paths.py** — added `_resolve_entity_directory(root, entity_type)` internal helper that:
   - inspects each existing path component beneath the vault root for symlinks before resolving
   - rejects any symlinked canonical path component with `StorageError`
   - verifies the resolved path remains inside the vault root
   - is reused by `entity_directory()`, `resolve_entity_path()`, and `discover_entity_files()`
   - also fixed stale `entity_dir` variable reference in `resolve_entity_path` error message
2. **storage/paths.py** — strengthened discovery sort key to `(casefolded_path, exact_path)` tuple for deterministic tie-breaking on case-sensitive filesystems
3. **tests/unit/test_storage_paths.py** — added 8 new tests (7 symlink-dependent, 1 source-inspection):
   - `TestCanonicalDirectorySymlinkRejection` class with 7 tests:
     - `test_entity_directory_rejects_direct_symlink_to_outside`
     - `test_discovery_rejects_direct_symlink_to_outside`
     - `test_entity_directory_rejects_symlink_to_another_entity_dir`
     - `test_discovery_rejects_symlink_to_another_entity_dir`
     - `test_parent_symlink_rejected_for_npc`
     - `test_parent_symlink_rejected_for_npc_discovery`
     - `test_parent_symlink_to_another_vault_dir_rejected`
   - `test_deterministic_ordering_tie_breaker` — verifies sort-key tuple contract via source inspection

**Path safety invariants established:**
- Vault root must exist and be a directory; normalised to canonical absolute resolved path
- `..` traversal is rejected structurally (not after resolution) — presence of `..` in any path component is sufficient for rejection
- Absolute paths are rejected at the structural check level
- Every accepted path is contained within its canonical entity directory AND within the vault root (verified via `pathlib.relative_to`)
- Entity paths must have `.md` suffix (case-insensitive)

**Discovery policy established:**
- Only four MVP entity directories are scanned: Characters/NPCs, Locations, Quests, Items
- Other Vault directories (Campaign, Sessions, Lore, etc.) are NOT scanned
- Discovery is recursive within each entity directory
- Symlinked directories are NOT traversed
- Symlinked files are NOT returned
- Missing entity directories yield zero candidates (no directory creation)
- Canonical entity path that exists as a non-directory raises `StorageError`
- Results are deterministically ordered by Vault-relative POSIX path (casefold primary, exact path secondary)

**Symlink policy established:**
- Discovery does NOT follow symlinked directories
- Symlinked files are NOT treated as entity-file candidates
- A symlink must never allow discovery to escape the vault root or an approved entity directory
- **Canonical entity-directory path components beneath the vault root must not be symlinks** — any symlink in the canonical path (e.g. `Vault/Locations` → outside, `Vault/Characters` → outside/NPCs, `Vault/Locations` → `Vault/Quests`) is rejected with `StorageError` before any resolution or discovery occurs
- Tests use `_can_symlink()` runtime check to skip when OS/environment cannot create symlinks

**Filesystem error behaviour:**
- `OSError` during directory iteration is translated to `StorageError` with original cause preserved
- `_resolve_vault_root` translates `OSError`/`RuntimeError` to `StorageError`
- `resolve_entity_path` uses `from None` for containment-check `ValueError` (programmer errors, not filesystem)

**Confirmed: discovery does NOT read/parse Markdown or infer EntityId from filename:**
- `DiscoveredEntityFile` has no `entity_id` attribute
- `paths.py` does not import from `storage.markdown`
- No file contents are read during discovery
- Test `test_filename_not_entity_id` explicitly verifies the absence of `entity_id`

**Quality-gate results (after S3-02 correction):**
- `uv run pytest tests/unit/test_storage_paths.py` — 56 passed, 10 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 163 passed, 10 skipped
- `uv run pytest` (full suite) — 714 passed, 10 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 72 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-02:** Canonical entity-directory resolution (`entity_directory`, `resolve_entity_path`, `discover_entity_files`) did not check whether the canonical directory path itself contained symlinks before calling `.resolve()`, which could allow symlink-based escape or cross-type redirection. Fixed by introducing `_resolve_entity_directory()` with pre-resolution symlink inspection of each existing path component beneath the vault root.

**Code/test changes during S3-02 (original):** 4 files (2 modified, 2 new), focused on path safety and entity discovery only.

**Code/test changes during S3-02 correction:** 2 files modified (storage/paths.py, tests/unit/test_storage_paths.py), focused on canonical-directory symlink hardening and deterministic sort tie-breaker.

**Scope exclusions confirmed:**
- No Markdown parsing changes
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No duplicate EntityId checks, repository ID index/cache, SQLite
- No filename generation or directory creation for entity persistence
- No atomic write, fsync, audit JSONL, revision increments, locks, migrations
- No Calendar, Retrieval/EntityResolver, Session runtime, Tool layer, ModelGateway, or ChangeSet

**Stage 3 status:** IN PROGRESS — S3-04 complete.

### S3-03 completion record

**Review range:** S3-02 correction through S3-03

**Changes:**

1. **storage/atomic.py** (new) — atomic text-write primitive:
   - `atomic_write_text(target, content, *, validator)` — single public function
   - Temporary sibling file created via `tempfile.mkstemp` in the same parent directory as target
   - Temporary naming pattern: `.<target-name>.<random>.tmp`
   - UTF-8 writing with `newline=""` to prevent Windows `\n` → `\r\n` translation
   - Flush + `os.fsync` before validation
   - Required `validator(content)` callback runs after fsync, before `os.replace`
   - `os.replace(temp_path, target_path)` for atomic replacement
   - Target must be absolute; relative paths rejected with `StorageError`
   - Existing target symlink rejected with `StorageError`
   - Existing target directory rejected with `StorageError`
   - Missing parent directory rejected with `StorageError` (no directory creation)
   - Filesystem `OSError` translated to `StorageError` with cause preserved
   - `ValidationError` from validator propagates unchanged (not translated to `StorageError`)
   - Temporary file cleaned up on failure (best-effort, does not mask primary error)
   - No domain Entity import, no Markdown codec import, no audit import

2. **storage/__init__.py** — exports `atomic_write_text`

3. **tests/unit/test_storage_atomic.py** (new) — 36 tests + 1 skipped:

   **Success (11 tests):**
   - Create missing target, replace existing target
   - Unicode preservation (Cyrillic, CJK, Arabic)
   - LF preservation (no `\r\n` translation)
   - CRLF preservation (exact bytes via `read_bytes()`)
   - No trailing-newline modification
   - Trailing newline preserved
   - Mixed newlines preserved
   - Validator called with content
   - No temp files remain after success
   - Validator return value ignored

   **Operation ordering (1 test):**
   - Behavioural verification: `fsync < validator < replace` via monkeypatched `os.fsync`/`os.replace`

   **Validation failure (4 tests):**
   - Existing target unchanged after validator raises `ValidationError`
   - Missing target remains absent
   - Validator exception propagates unchanged (not translated to `StorageError`)
   - Temporary file removed after validation failure

   **fsync failure (3 tests):**
   - `StorageError` raised with `OSError` cause preserved
   - Original target unchanged
   - Temporary file cleaned

   **os.replace failure (3 tests):**
   - `StorageError` raised with `OSError` cause preserved
   - Original target unchanged
   - Temporary file cleaned

   **Temp creation failure (2 tests):**
   - `tempfile.mkstemp` patched to raise `OSError` → `StorageError` with cause
   - Original target unchanged

   **Path state (5 tests):**
   - Missing parent rejected
   - Parent regular file rejected
   - Target directory rejected
   - Target symlink rejected (skipped on Windows without symlink privileges)
   - Relative path rejected

   **Same-directory temp invariant (1 test):**
   - Temp file parent == target parent (verified via `os.replace` interception)

   **Public boundaries (7 tests):**
   - Module importable
   - `atomic_write_text` re-exported from `storage`
   - No `domain.entity` import
   - No `storage.markdown` import
   - No `models` import
   - No `retrieval` import
   - No `tools` import

**Atomic-write API established:**
- `atomic_write_text(target, content, *, validator)` — single function, no classes
- Target must be absolute; parent must exist; target must not be a directory or symlink
- Temporary file created beside target (same filesystem for `os.replace`)
- UTF-8 with `newline=""` — exact newline preservation
- Lifecycle: `write → flush → fsync → validator → close → os.replace`
- `ValidationError` propagates unchanged; `OSError` → `StorageError` with cause
- Best-effort temp cleanup on failure; does not mask primary error

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_atomic.py` — 36 passed, 1 skipped
- `uv run pytest tests/unit/test_storage_atomic.py tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 199 passed, 11 skipped
- `uv run pytest` (full suite) — 750 passed, 11 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 74 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-03:**
- Initial `except Exception` block in `atomic_write_text` re-raised `OSError` directly instead of translating to `StorageError`. Fixed by adding explicit `except OSError` → `StorageError` translation.
- `ValidationError` was not imported in `atomic.py`. Fixed by adding the import.
- CRLF preservation tests used `read_text()` which translates `\r\n` to `\n` on Windows. Fixed by using `read_bytes().decode("utf-8")`.
- Module-level monkeypatches (`atomic_mod._create_temp`, `atomic_mod._write_content`) failed when running in the full test suite due to module identity issues. Fixed by patching `tempfile.mkstemp` via `unittest.mock.patch`.

**Code/test changes during S3-03:** 4 files (2 modified, 2 new), focused on atomic write primitive only.

**Scope exclusions confirmed:**
- No VaultRepository concrete class
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No revision increment or optimistic concurrency
- No audit JSONL or AuditService
- No locks, migrations, directory creation
- No filename generation or stable-ID lookup
- No Markdown codec changes
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet
- S3-04 was NOT started

### S3-03 correction (exception and symlink handling)

**Review range:** S3-03 original through S3-03 correction

**Changes:**

1. **storage/atomic.py** — four corrections:

   **1a. Dangling/broken symlink rejection (Correction 1):**
   - `_validate_target()` now checks `target_path.is_symlink()` **before** `target_path.exists()`.
   - `Path.exists()` follows symlinks and returns `False` for dangling/broken destinations, so the old ordering allowed dangling symlinks to pass through undetected.
   - A dangling symlink is now correctly rejected with `StorageError` (same as any other symlink).

   **1b. `BaseException` removed (Correction 2):**
   - The old `except BaseException: cleanup; raise` block is removed.
   - Cleanup is now structured via `finally:` which runs for all exit paths including `KeyboardInterrupt` and `SystemExit`.
   - `except StorageError: raise` (re-raise without cleanup duplication) + `except Exception: cleanup; raise` + `finally: cleanup` — the `finally` call to `_cleanup_temp` is safe because `_cleanup_temp` already performs best-effort cleanup without masking the active exception.
   - `KeyboardInterrupt` and `SystemExit` now propagate immediately while still getting best-effort temp cleanup from `finally`.

   **1c. Validator exception transparency (Correction 3):**
   - `validator(content)` runs **outside** any `OSError`-translation boundary.
   - Implementation-owned filesystem operations (`_write_and_fsync`, `_os_replace`) each have their own narrow `OSError → StorageError` translation.
   - The validator is called between these operations, so any exception it raises (including `OSError`) propagates unchanged — never translated to `StorageError`.
   - `ValidationError` import removed from `atomic.py` since the module no longer needs to reference it for exception handling.

   **1d. Simplified lifecycle (Correction 4):**
   - `_write_content` + `_flush_and_fsync` + `_close_temp` replaced by single `_write_and_fsync(temp_path, content)` helper.
   - New helper: `open → write → flush → fsync → close` in one context manager — no reopening for fsync, no ceremonial `_close_temp`.
   - `_os_replace(src, dst)` added as a narrow `OSError → StorageError` wrapper for `os.replace`.
   - Final lifecycle: `create temp → write+flush+fsync+close → validate → os.replace`.
   - File descriptor is closed before validation and replacement (Windows-safe).

2. **tests/unit/test_storage_atomic.py** — new tests:

   **TestDanglingSymlink (4 tests, skipped on Windows without symlink privileges):**
   - `test_dangling_symlink_rejected` — dangling symlink raises `StorageError`
   - `test_dangling_symlink_remains_unmodified` — symlink still exists, still dangling after rejection
   - `test_dangling_symlink_no_temp_left` — no temp files remain
   - `test_dangling_symlink_dest_not_created` — nonexistent destination is not created

   **TestValidatorExceptionTransparency (8 tests):**
   - `test_custom_validator_exception_propagates` — `CustomValidationError` escapes unchanged
   - `test_custom_validator_exception_target_unchanged` — existing target preserved
   - `test_custom_validator_exception_temp_cleaned` — temp cleaned after custom exception
   - `test_validator_oserror_propagates_unchanged` — `OSError` from validator is NOT `StorageError`
   - `test_validator_oserror_target_unchanged` — target preserved after validator `OSError`
   - `test_validator_oserror_temp_cleaned` — temp cleaned after validator `OSError`
   - `test_validator_keyboardinterrupt_propagates` — `KeyboardInterrupt` propagates (no `BaseException` catch)
   - `test_validator_keyboardinterrupt_temp_cleaned` — temp cleaned after `KeyboardInterrupt`

**Final exact atomic lifecycle:**

```
create temp
    ↓
open for UTF-8 text writing (newline="")
    ↓
write content
    ↓
flush
    ↓
os.fsync(fd)
    ↓
close (context-manager exit)
    ↓
validator(content)
    ↓
os.replace(temp, target)
```

**Invariant:** `fsync < validate < replace` — file descriptor closed before validate and replace.

**Validator exception semantics:**
- ANY exception from validator propagates unchanged (not translated to `StorageError`)
- This includes `ValidationError`, `OSError`, `KeyboardInterrupt`, `SystemExit`, custom exceptions
- Temp cleanup occurs via `finally` for all paths

**Filesystem OSError translation boundaries:**
- `_create_temp()` — own `OSError → StorageError`
- `_write_and_fsync()` — own `OSError → StorageError`
- `_os_replace()` — own `OSError → StorageError`
- `validator(content)` — NO translation boundary

**`BaseException` confirmation:**
- No `except BaseException` in the codebase
- `KeyboardInterrupt` and `SystemExit` propagate through `finally` cleanup

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_atomic.py` — 44 passed, 5 skipped
- `uv run pytest tests/unit/test_storage_atomic.py tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 207 passed, 15 skipped
- `uv run pytest` (full suite) — 758 passed, 15 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 74 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-03 correction:** Three defects in the original S3-03 implementation:
1. Dangling/broken symlinks were not rejected (symlink check after `exists()` which follows links)
2. `except BaseException` caught `KeyboardInterrupt`/`SystemExit`
3. Validator exceptions (including `OSError`) could be caught by broad `except OSError` and translated to `StorageError`

**Code/test changes during S3-03 correction:** 2 files modified (storage/atomic.py, tests/unit/test_storage_atomic.py), focused on exception and symlink correctness only.

**Scope exclusions confirmed:**
- No VaultRepository concrete class
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No revision increment or optimistic concurrency
- No audit JSONL or AuditService
- No locks, migrations, directory creation
- No filename generation or stable-ID lookup
- No Markdown codec changes
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet
- S3-04 was NOT started

### S3-04 completion record

**Review range:** S3-03 correction through S3-04

**Changes:**

1. **storage/audit.py** (rewritten) — `AuditRecord` schema + `AuditService` implementation:

   **AuditRecord schema:**
   - `schema_version: Literal[1] = 1` — fixed at 1
   - `operation_id: str` — required, validated non-empty printable string
   - `real_time: AwareDatetime` — required, timezone-aware (naive rejected)
   - `session: str | None = None` — optional, validated when present
   - `operation: str` — required, validated non-empty printable string
   - `entity_id: EntityId | None = None` — optional, validated as domain EntityId
   - `before_hash: str | None = None` — optional, validated when present
   - `after_hash: str | None = None` — optional, validated when present
   - `source: str` — required, validated non-empty printable string (NOT domain Provenance)
   - `model_profile: str | None = None` — optional, validated when present
   - `prompt_version: str | None = None` — optional, validated when present
   - `model_config = {"extra": "forbid", "frozen": True}`

   **AuditService public API:**
   - `AuditService(log_path)` — constructor validates path preconditions
   - `.append(record)` — serializes record as JSONL, appends with flush+fsync
   - `.read_all()` — reads all persisted records in append order
   - `.log_path` — property returning the absolute log path

   **JSONL format:**
   - One JSON object per line, followed by `\n`
   - UTF-8 encoding, Unicode preserved, no pretty printing
   - Deterministic serialization via `model_dump(mode="json")` + `json.dumps(ensure_ascii=False, separators=(",", ":"))`

   **Append lifecycle:**
   ```
   open (append mode) → write → flush → fsync → close
   ```

   **Append-only guarantees:**
   - Never truncates or rewrites existing bytes
   - Existing bytes remain exact prefix after append
   - Does NOT use `atomic_write_text` for JSONL append

   **Explicit partial-failure limitation:**
   - Once bytes reach the filesystem, a later failure (e.g. fsync) may leave a complete or partial line
   - No rollback/truncation of uncertain appends
   - Corrupted tails detected during `read_all()`

   **read_all corruption behaviour:**
   - Missing file → empty list
   - Malformed JSON → `StorageError` with line number and cause
   - Invalid AuditRecord → `StorageError` with line number and cause
   - Blank line → `StorageError` with line number
   - Unknown fields in persisted record → `StorageError`
   - No silent skipping of bad records

   **Filesystem error translation:**
   - `OSError` during open/write/flush/fsync → `StorageError` with cause preserved
   - No `except BaseException`
   - `KeyboardInterrupt`/`SystemExit` propagate unchanged

   **Path preconditions:**
   - Must be absolute
   - Parent must exist and be a directory
   - Must not be an existing directory
   - Must not be a symlink (including dangling/broken)
   - No parent directory creation (caller responsibility)
   - Documented: path validation != Vault authorization

   **Architectural boundaries confirmed:**
   - AuditService does NOT touch entity files
   - Does NOT compute entity hashes
   - Does NOT use `atomic_write_text`
   - Does NOT implement repository write/audit orchestration
   - Does NOT import from `models`, `retrieval`, `tools`, `storage.markdown`, `domain.entity`
   - `source` is a validated string, NOT domain `Provenance`

2. **storage/__init__.py** — exports `AuditRecord`, `AuditService`

3. **tests/unit/test_storage_audit.py** (new) — 66 tests (64 passed, 2 skipped):

   **AuditRecord schema (30 tests):**
   - Minimal valid record (1 test)
   - schema_version default and fixed (2 tests)
   - Timezone-aware accepted, naive rejected (2 tests)
   - Full record with all optional fields (1 test)
   - EntityId validation and Unicode (2 tests)
   - Required string validation: empty, whitespace, non-printable for operation_id/operation/source (9 tests)
   - Optional string validation: empty, whitespace, None for session/hash/metadata (9 tests)
   - Unicode allowed in all string fields (1 test)
   - Unknown fields rejected (1 test)
   - Source not restricted to Provenance values (1 test)
   - Frozen immutability (1 test)

   **Service path validation (8 tests):**
   - Absolute accepted, relative rejected, missing parent, parent file, directory, symlink, dangling symlink, log_path property

   **Append (10 tests):**
   - Missing file created, one JSON line, exactly one `\n`, Unicode round-trip, multiple appends preserve order, existing bytes remain prefix, no truncation, fsync called, file closed

   **read_all (8 tests):**
   - Missing file → [], one record, multiple records preserve order, malformed JSON, schema-invalid record, blank line, unknown fields, no silent skip

   **Failure injection (3 tests):**
   - Open/write failure → StorageError with cause
   - fsync failure → StorageError with cause
   - fsync failure does not rewrite history

   **Boundary tests (7 tests):**
   - Module importable, re-exported, no entity/model/retrieval/tools/markdown import, no atomic_write_text usage

**Decisions made:**
- `source` is a validated string (NOT domain `Provenance`) — describes the actor/mechanism that performed the Vault operation, not how campaign knowledge entered the system
- `real_time` is caller-supplied `AwareDatetime` — AuditService does not own the system clock
- JSONL format: one record per line, UTF-8, no pretty printing
- Log path is injected by caller — no hardcoded audit filename
- Append-only: never truncate/rewrite, no rollback on partial failure
- `fsync` after every append
- Corruption detected on read, no automatic repair

**Decisions intentionally deferred to S3-05/S3-06:**
- Entity write + audit consistency semantics must be explicitly designed before repository write operations are accepted. The ordering between `entity atomic write` and `audit append` (and the consequences of one succeeding while the other fails) is not solved by this task.

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_audit.py` — 64 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_audit.py tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py` — 271 passed, 17 skipped
- `uv run pytest` (full suite) — 822 passed, 17 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 75 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-04:** None

**Code/test changes during S3-04:** 4 files (2 modified, 2 new), focused on AuditRecord schema and AuditService only.

**Scope exclusions confirmed:**
- No VaultRepository concrete class
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No revision increment or optimistic concurrency
- No entity hash computation
- No locks, migrations, directory creation
- No filename generation or stable-ID lookup
- No Markdown codec changes
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet
- S3-05 was NOT started

### S3-05 completion record

**Review range:** S3-04 completion through S3-05

**Changes:**

1. **storage/audit.py** — two extensions:

   **AuditRecord.phase field:**
   - Added `phase: Literal["intent", "committed"] = "committed"` — backward-compatible default
   - Old persisted JSON without `phase` loads as `"committed"` (default behavior)
   - `schema_version` not incremented (same unreleased Stage-3 cycle)

   **AuditContext model:**
   - New strict Pydantic model: `operation_id`, `real_time` (AwareDatetime), `source` — required
   - Optional: `session`, `model_profile`, `prompt_version`
   - `extra="forbid"`, `frozen=True`
   - Same validation semantics as corresponding AuditRecord fields
   - Exported from `dnd_assistant.storage`

2. **storage/types.py** — `VaultRepository` Protocol refinement:
   - `create_entity` signature changed from `create_entity(document)` to `create_entity(document, *, audit: AuditContext)`
   - Audit metadata is now required (not optional) for every mutation
   - Read signatures (`get_entity`, `list_entities`) unchanged

3. **storage/vault_repository.py** (new) — `ObsidianVaultRepository` concrete class:
   - Constructor: `ObsidianVaultRepository(vault_root, audit_service)`
   - Validates audit path belongs beneath `<vault_root>/_system/audit/`
   - Rejects symlinked audit path components
   - Requires `_system/audit/` directory to exist

   **get_entity(entity_id):**
   - Scans all entity directories, parses all candidates
   - Detects global duplicate EntityIds (raises ConflictError)
   - Detects directory/type mismatch (raises StorageError)
   - Detects malformed persisted files (raises StorageError)
   - Exact YAML ID lookup only (no filename, no fuzzy, no name)
   - Runtime entity_id validation (invalid input → ValidationError, not NotFoundError)

   **list_entities(entity_type=None):**
   - Same global scan/validation as get_entity
   - Optional type filter
   - Deterministic discovery ordering (from S3-02 paths)
   - Empty list when nothing matches

   **create_entity(document, *, audit):**
   - Full write-ahead audit lifecycle:
     1. Validate audit log readable + operation_id unique
     2. Global snapshot (duplicate EntityId check)
     3. Serialize document
     4. Compute SHA-256 after_hash
     5. Generate opaque UUID filename (`entity-<uuid4hex>.md`)
     6. Append audit `intent` record
     7. `atomic_write_text` with parse validator
     8. Re-read persisted bytes, verify hash
     9. Append audit `committed` record
     10. Return persisted VaultDocument

   **Filename policy:**
   - Opaque UUID-based: `entity-<uuid4hex>.md`
   - ASCII-only, Windows/macOS safe
   - NOT derived from EntityId or display name
   - Collision detection with up to 32 retry attempts
   - Manual user rename does not break get_entity

   **Exact text read policy:**
   - Uses `open(path, encoding="utf-8", newline="")` — no newline translation
   - Invalid UTF-8 → StorageError

   **Persisted corruption policy:**
   - Malformed frontmatter → StorageError (not silently skipped)
   - Invalid Entity schema → StorageError
   - Directory/YAML type mismatch → StorageError
   - Invalid UTF-8 → StorageError

   **Global duplicate-ID policy:**
   - All entity types scanned before any read/list/create
   - Two files with same EntityId → ConflictError
   - Applies even when list_entities has a type filter

   **SHA-256 hash policy:**
   - `hashlib.sha256(exact_text.encode("utf-8")).hexdigest()`
   - Hashes exact serialized UTF-8 content
   - `before_hash = None` for create

   **Audit consistency strategy:**
   - `intent` → atomic write → verified read-back → `committed`
   - Same `operation_id` for both records
   - operation_id reuse rejected with ConflictError

   **Failure matrix:**
   - Corrupt audit preflight → StorageError, no entity mutation
   - Intent append failure → StorageError propagates, no entity mutation
   - Entity write failure → StorageError propagates, intent remains, no entity file
   - Read-back/hash failure → StorageError (entity may be committed), no committed audit
   - Committed-audit failure → StorageError with explicit diagnostic, entity NOT rolled back

   **No rollback/delete after committed mutation:**
   - If entity write succeeds but committed audit fails, entity remains
   - Intent record provides deterministic recoverability

4. **storage/__init__.py** — exports `AuditContext`, `ObsidianVaultRepository`

5. **tests/unit/test_storage_audit.py** — added:
   - `TestAuditRecordPhase` — 6 tests (default, intent, committed, invalid, backward compat, round trip)
   - `TestAuditContext` — 8 tests (minimal, full, naive rejected, empty/whitespace/extra/frozen/unicode)

6. **tests/unit/test_storage_vault_repository.py** (new) — 51 tests:

   **Repository construction (5 tests):**
   - Valid vault + audit, missing vault root, audit outside vault, audit outside _system/audit/, missing _system/audit/

   **Read/list success (12 tests):**
   - Empty vault, empty by type, one NPC, all four types, type-filtered list, Unicode entity/body, extra frontmatter preserved, exact ID lookup, renamed file still found, not found, invalid ID rejected, no filename lookup

   **Corruption handling (6 tests):**
   - Malformed frontmatter, invalid entity schema, directory/type mismatch, duplicate ID across types, duplicate ID same type, type-filtered list still detects global duplicate

   **Create duplicate (3 tests):**
   - Duplicate YAML ID → ConflictError, no target overwritten, audit intent not written

   **Filename policy (7 tests):**
   - `.md` suffix, safe ASCII, not entity ID, not display name, starts with `entity-`, manual rename OK, collision regenerates

   **Audit lifecycle (8 tests):**
   - Exactly 2 records, same operation_id, operation is create_entity, intent then committed, same entity_id, before_hash is None, same after_hash, same context metadata

   **Failure semantics (6 tests):**
   - operation_id reuse rejected, corrupt audit preflight aborts, intent append failure aborts, entity write failure leaves intent, committed audit failure entity still exists

   **Boundary tests (5 tests):**
   - Module importable, re-exported, no models/retrieval/tools imports

7. **DEVELOPMENT_STATUS.md** — updated task status, added S3-05 completion record

**Decisions made:**
- `ObsidianVaultRepository` — explicit concrete name, not `VaultRepository`
- Full `VaultRepository` structural conformance deferred to S3-07 (append_entity_fact)
- Filename: opaque UUID (`entity-<uuid4hex>.md`), not EntityId-derived
- Exact text read: `open(path, encoding="utf-8", newline="")` — no newline translation
- Persisted corruption: always StorageError, never silently skipped
- Directory/type mismatch: StorageError, never silently accepted
- Global duplicate ID: ConflictError, never first-win
- SHA-256 of exact UTF-8 content for audit hashes
- Write-ahead audit: intent before mutation, committed after verified read-back
- No rollback after committed entity write
- No cross-process duplicate-create guarantee (no file locks)
- No patch/revision/append scope creep

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 51 passed
- `uv run pytest tests/unit/test_storage_audit.py` — 78 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py tests/unit/test_storage_audit.py tests/unit/test_storage_vault_repository.py` — 353 passed, 17 skipped
- `uv run pytest` (full suite) — 887 passed, 17 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 77 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-05:** None at original implementation.

**S3-05 correction (audit-path hardening, EntityId validation, filename symlinks, cause preservation):**

1. **storage/vault_repository.py** — six corrections:

   **1a. Audit-path structural traversal rejection (Corrections 1-3):**
   - `_validate_audit_path()` now rejects ANY raw relative component equal to `..` before resolution (structural check, not resolved-path).
   - After symlink inspection of existing components, the audit log path is resolved with `strict=False`.
   - Resolved path is verified to be inside the resolved Vault root (via `relative_to`).
   - Resolved path is verified to be inside the resolved canonical `_system/audit/` directory.
   - No string-prefix containment checks (`str(path).startswith(...)` is never used).
   - The `_system/audit/` directory itself must exist and be a real directory (unchanged).

   **1b. Canonical EntityId runtime validation (Corrections 5-6):**
   - `_validate_entity_id_input()` now delegates to `pydantic.TypeAdapter(EntityId)` instead of duplicating the domain grammar.
   - Invalid input raises `dnd_assistant.errors.ValidationError` with the Pydantic validation failure preserved as `__cause__`.
   - The helper returns the validated value; `get_entity()` compares using that validated result.
   - `EntityId` import added to the module; `TypeAdapter` import added from pydantic.

   **1c. Filename symlink collision (Corrections 7-8):**
   - `_generate_unique_path()` now checks `not candidate.exists() and not candidate.is_symlink()`.
   - A dangling/broken symlink (where `exists()` returns `False`) is correctly treated as occupied.
   - A live symlink to an existing file is also treated as occupied.
   - The symlink is never unlinked or replaced.

   **1d. Committed-audit cause preservation (Correction 9):**
   - The `except StorageError` branch now uses `from exc` and passes `cause=exc` to the new `StorageError`.
   - The original audit `StorageError` is preserved as `__cause__`.

   **1e. Redundant try/except removed (Correction 12):**
   - The `try: atomic_write_text(...) except Exception: raise` wrapper removed — exceptions from `atomic_write_text` propagate naturally.

2. **tests/unit/test_storage_vault_repository.py** — 13 new tests:

   **Audit-path traversal (4 tests):**
   - `test_audit_path_traversal_inside_vault_rejected` — `..` from `_system/audit/` to `_system/other/` rejected
   - `test_audit_path_escape_from_vault_rejected` — `../../../outside/` rejected
   - `test_audit_path_normal_canonical_accepted` — normal path still accepted
   - `test_audit_path_nested_real_directory_accepted` — nested subdirectory under `_system/audit/` accepted

   **Canonical EntityId validation (6 tests):**
   - `test_get_entity_empty_rejected` — empty string rejected
   - `test_get_entity_whitespace_rejected` — leading/trailing whitespace rejected
   - `test_get_entity_non_printable_rejected` — control characters rejected
   - `test_get_entity_unicode_accepted` — printable Unicode accepted
   - `test_get_entity_validation_error_has_cause` — Pydantic cause preserved
   - (Existing `test_get_entity_invalid_id_rejected` unchanged — validates empty via new path)

   **Filename symlink collision (3 tests):**
   - `test_dangling_symlink_skipped` — dangling symlink skipped, entity created with different filename
   - `test_live_symlink_skipped` — live symlink skipped, entity created with different filename
   - `test_exhausted_attempts_raises_storage_error` — all 32 attempts exhausted raises `StorageError`

   **Committed-audit cause preservation (1 test):**
   - `test_committed_audit_failure_preserves_cause` — `exc_info.value.__cause__ is original audit StorageError`

**Quality-gate results (after S3-05 correction):**
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_audit.py` — 78 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py tests/unit/test_storage_audit.py tests/unit/test_storage_vault_repository.py` — 347 passed, 19 skipped
- `uv run pytest` (full suite) — 898 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 77 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-05 correction:** 2 files modified (storage/vault_repository.py, tests/unit/test_storage_vault_repository.py), focused on audit-path safety, canonical EntityId validation, filename symlink handling, and cause preservation.

**Scope exclusions confirmed:**
- No patch_entity, Patch DTO, expected_revision, revision increment, timestamp mutation (S3-06)
- No append_entity_fact (S3-07)
- No locks, rollback/delete transaction, automatic intent reconciliation, audit repair
- No fuzzy search, name/alias lookup, SQLite, FTS, indexes, embeddings, migrations
- No directory/bootstrap initialization, Calendar, Retrieval/EntityResolver, Session runtime, Tool layer, ModelGateway, ChangeSet
- S3-06 was NOT started

**Stage 3 status:** IN PROGRESS — S3-05 complete after correction.

### S3-06 completion record

**Review range:** S3-05 correction through S3-06

**Changes:**

1. **storage/patch.py** (new) — `EntityPatch` DTO:
   - Editable fields: `name`, `status`, `visibility`, `knowledge_status`, `created_session`, `last_seen_session`, `tags`
   - Immutable fields rejected: `schema_version`, `id`, `type`, `created_at`, `updated_at`, `revision`, `body`, `extra_frontmatter`
   - Empty patch rejected (at least one field required)
   - Explicit `None` allowed for nullable fields (`created_session`, `last_seen_session`)
   - Explicit `None` rejected for non-nullable fields (`name`, `status`, `visibility`, `knowledge_status`, `tags`)
   - Unknown fields rejected (`extra="forbid"`)
   - Frozen immutability
   - Canonical domain field validation reused (`NameStr`, `StatusStr`, `SessionRef`, `TagStr`, `Visibility`, `KnowledgeStatus`)

2. **storage/types.py** — `VaultRepository` Protocol:
   - Added `patch_entity(entity_id, patch, *, expected_revision, audit) -> VaultDocument` typed signature
   - Removed deferred-comment placeholder

3. **storage/vault_repository.py** — `ObsidianVaultRepository.patch_entity`:
   - `_StoredEntity` extended with `exact_text` and `content_hash` properties for before-hash computation without re-reading
   - `_REVISION_ADAPTER` TypeAdapter for canonical `Revision` runtime validation
   - `_validate_revision_input()` helper with Pydantic cause preservation
   - Full patch lifecycle:
     1. Validate inputs (EntityId, Revision, EntityPatch)
     2. Validate audit health + operation_id uniqueness
     3. Build clean global snapshot
     4. Find target entity by exact EntityId
     5. Check `expected_revision` against stored revision → `ConflictError` on mismatch
     6. Construct patched Entity through `Entity.model_validate()` (full validation)
     7. Serialize patched document
     8. Compute `before_hash` (from snapshot) and `after_hash`
     9. Append audit `intent` record
     10. Second optimistic check: re-read target file, verify revision + hash unchanged
     11. `atomic_write_text` with parse validator
     12. Re-read and verify persisted content (hash, id, type, revision, updated_at, body)
     13. Append audit `committed` record
     14. Return persisted `VaultDocument`

4. **storage/__init__.py** — exports `EntityPatch`

5. **tests/unit/test_storage_patch.py** (new) — 40 EntityPatch DTO tests:
   - Allowed fields (8 tests)
   - Empty patch rejection (2 tests)
   - Forbidden/immutable fields (9 tests)
   - Explicit None semantics (7 tests)
   - Canonical validation (9 tests)
   - Frozen behaviour (2 tests)
   - model_fields_set introspection (3 tests)

6. **tests/unit/test_storage_patch_repository.py** (new) — 56 repository-level patch tests:
   - Optimistic concurrency (10 tests: 1→2, N→N+1, stale, zero audit, bool/string/zero/negative rejection, cause preservation)
   - Field changes (10 tests: name, status, visibility, knowledge_status, created_session, clear created, last_seen_session, clear last_seen, tags, tags replace)
   - Immutable fields unchanged (4 tests: id, type, created_at, schema_version)
   - Body preservation (6 tests: LF, CRLF, mixed, Unicode, no trailing, trailing)
   - Extra frontmatter preservation (2 tests)
   - Filename/path preservation (3 tests)
   - updated_at/revision metadata (3 tests)
   - Audit lifecycle (8 tests: 2 records, operation, operation_id, entity_id, before_hash, after_hash, hash differs, context metadata)
   - Failure semantics (7 tests: invalid id, not found, operation_id reuse, corrupt audit, intent failure, write failure, committed-audit failure with cause)
   - Concurrent/manual edit detection (2 tests: content change, revision change)
   - Integration cycle (1 test: create → get → patch → get)

7. **tests/unit/test_storage_types.py** — updated protocol test to include `patch_entity` in expected methods, removed deferred-assertion test

**Decisions made:**
- `EntityPatch` — strict Pydantic DTO, `extra="forbid"`, `frozen=True`
- Editable fields: name, status, visibility, knowledge_status, created_session, last_seen_session, tags
- Immutable fields: schema_version, id, type, created_at, updated_at, revision, body, extra_frontmatter
- Omitted vs explicit None: `model_fields_set` determines supplied fields; nullable fields accept explicit None (clear); non-nullable fields reject explicit None
- Empty patch rejected at model-validation level
- Repository owns revision increment: `new_revision = stored_revision + 1`
- Repository owns `updated_at`: set to `audit.real_time`
- First concurrency check: before audit intent (no intent on stale)
- Second pre-write check: after durable intent, re-read target, verify revision + hash
- Body preserved character-for-character through patch
- Extra frontmatter preserved semantically through patch
- Same file/path preserved (no rename, no move)
- Audit: `operation="patch_entity"`, two phases (intent, committed), same operation_id
- Before/after hash: SHA-256 of exact UTF-8 persisted text
- No rollback after committed atomic write
- No cross-process CAS/lock guarantee

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_patch.py` — 40 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest` (full suite) — 993 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 80 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-06:** None

**Code/test changes during S3-06:** 8 files (4 modified, 4 new), focused on EntityPatch DTO and patch_entity implementation only.

**Scope exclusions confirmed:**
- No append_entity_fact (S3-07)
- No arbitrary Markdown replacement
- No arbitrary extra-frontmatter patching
- No entity type migration, ID change, file rename, file move, delete
- No locks, compare-and-swap filesystem primitive, transaction framework
- No automatic intent reconciliation, audit repair
- No FTS, fuzzy lookup, SQLite, indexes, embeddings, migrations
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, ChangeSet
- S3-07 was NOT started

### S3-07 completion record

**Review range:** S3-06 completion through S3-07

**Changes:**

1. **storage/vault_repository.py** — three additions and one refactor:

   **1a. Fact validation (`_validate_fact`):**
   - New private function validating fact contract: must be `str`, non-empty, no leading/trailing whitespace, printable Unicode, no embedded newline/control characters
   - Invalid input raises `ValidationError` with descriptive message

   **1b. Body fact appender (`_append_fact_to_body`):**
   - New private function appending one Markdown bullet (`"- <fact>"`) to existing body
   - Existing body remains exact character-for-character prefix
   - Line-ending policy: empty body → LF; trailing CRLF → CRLF; trailing LF → LF; lone CR → CR; no trailing newline → infer separator from most recent line ending (CRLF wins)
   - No extra blank paragraph unless already present
   - No platform-default newline conversion

   **1c. Shared mutation commit helper (`_commit_entity_mutation`):**
   - New private function owning the common mutation core: serialization, before/after hashes, audit intent, second optimistic check (re-read target, verify revision + hash), `atomic_write_text` with parse validator, verified read-back (hash, id, type, revision, updated_at), committed audit, common failure semantics
   - Used by both `patch_entity` and `append_entity_fact`

   **1d. `patch_entity` refactored to use shared helper:**
   - Steps 7-14 (serialize → committed audit) replaced by single call to `_commit_entity_mutation`
   - All existing patch behaviour preserved (verified by 56 existing patch tests passing unchanged)
   - No change to EntityPatch semantics, revision ownership, updated_at ownership, patch allowed fields, hashes, operation name, audit ordering, second conflict check, filename/path, return semantics

   **1e. `append_entity_fact` implementation:**
   - Full lifecycle: validate inputs → audit health → snapshot → find target → revision check → construct new body → construct candidate Entity → delegate to `_commit_entity_mutation`
   - Same audit two-phase strategy as `patch_entity` with `operation="append_entity_fact"`
   - Same second pre-write revision/hash check
   - Same atomic replacement (no direct file append for entity Markdown)
   - Same failure semantics (no audit intent for invalid input/not found/stale; intent remains on write failure; no rollback after successful atomic write; committed-audit failure preserves cause)

2. **storage/types.py** — `VaultRepository` Protocol:
   - `append_entity_fact` signature updated to require `audit: AuditContext` parameter
   - Docstring updated to describe fact validation contract, Markdown bullet rendering, revision increment, and `updated_at` ownership

3. **tests/unit/test_storage_types.py** — updated protocol test:
   - `test_append_entity_fact_revision_deferred_to_s3_07` replaced by `test_append_entity_fact_revision_semantics` verifying docstring now claims revision increment

4. **tests/unit/test_storage_append_fact.py** (new) — 67 tests:

   **Fact validation (11 tests):**
   - Normal ASCII, Unicode, special characters accepted
   - Empty, whitespace-only, leading whitespace, trailing whitespace, newline, CRLF, tab, non-string rejected

   **Body rendering (8 tests):**
   - Empty body → `"- Fact\n"`, LF trailing, CRLF trailing, no trailing newline, existing blank line, Unicode body/fact, old body exact prefix, fact appears exactly once

   **Entity metadata preservation (13 tests):**
   - id, type, name, status, visibility, knowledge_status, created_session, last_seen_session, created_at, schema_version, tags unchanged
   - revision incremented by 1, updated_at = audit.real_time, updated_at differs from created_at

   **Extra frontmatter preservation (2 tests):**
   - Simple extra keys survive, nested extra keys survive

   **File/path preservation (3 tests):**
   - Same path remains, custom filename preserved, no new file created

   **Audit lifecycle (8 tests):**
   - Exactly 2 records, operation is `append_entity_fact`, same operation_id, same entity_id, same before_hash, same after_hash, before_hash != after_hash, same context metadata

   **Optimistic concurrency (9 tests):**
   - Revision 1→2, N→N+1, stale raises ConflictError, stale produces zero audit records, bool/string/zero/negative revision rejected, repeated append with new revision

   **Failure semantics (7 tests):**
   - Invalid entity_id, not found, operation_id reuse, corrupt audit preflight, intent append failure, entity write failure leaves intent, committed-audit failure entity still has fact, committed-audit failure preserves cause

   **Concurrent/manual edit detection (2 tests):**
   - Manual edit without revision change detected, manual edit with revision change detected

   **Cross-operation integration (1 test):**
   - create → append → patch → append cycle verifies revision compatibility and body content

   **Protocol conformance (1 test):**
   - `isinstance(repo, VaultRepository)` — runtime structural conformance

5. **DEVELOPMENT_STATUS.md** — updated task status, added S3-07 completion record

**Decisions made:**
- `append_entity_fact` requires `audit: AuditContext` (no unaudited overload)
- Fact validation: non-empty, printable, no leading/trailing whitespace, no embedded newlines/controls
- Markdown rendering: `"- <fact>"` bullet, no `## Facts` heading, no timestamps/source labels/operation IDs in body
- Line-ending policy: deterministic, never modifies old body, CRLF-aware
- Existing body remains exact character-for-character prefix
- Entity metadata: only revision (+1) and updated_at (= audit.real_time) change
- Extra frontmatter preserved semantically unchanged
- Same file/path preserved (atomic replacement, not direct file append)
- Shared mutation core (`_commit_entity_mutation`) used by both `patch_entity` and `append_entity_fact`
- `patch_entity` behaviour unchanged by refactoring
- No generic body patch DTO, no fact removal/deduplication/IDs/timestamps, no Provenance blocks
- No S3-08 scope creep

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_append_fact.py` — 67 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest` (full suite) — 1060 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 81 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-07:** None

**S3-07 correction (CRLF inference defect):**

**Review range:** S3-07 original through S3-07 correction

**Root cause:** `_append_fact_to_body()` compared `last_crlf = body.rfind("\r\n")` (start index of `\r\n`) with `last_lf = body.rfind("\n")` (start index of `\n`). For a CRLF sequence, `\n` is at index `last_crlf + 1`, so `last_lf > last_crlf` was always true, causing the code to incorrectly select LF instead of CRLF when the body had no trailing newline but the most recent line ending was CRLF.

**Corrected no-trailing-newline inference algorithm:**
- Find the rightmost `\n` via `body.rfind("\n")`.
- If none exists → default LF.
- If the `\n` is immediately preceded by `\r` → CRLF.
- Otherwise → LF.
- This correctly handles: CRLF history, LF history, mixed history where the most recent actual newline is CRLF, mixed history where the most recent actual newline is LF, and no prior newline at all.

**Changes:**

1. **storage/vault_repository.py** — `_append_fact_to_body()`:
   - Replaced `last_crlf > last_lf` comparison with correct `body[last_lf - 1] == "\r"` check.
   - Added explicit `last_lf == -1` guard for bodies with no prior newline.
   - Removed unused `expected_revision` parameter from `_commit_entity_mutation()` (optional cleanup — the parameter was accepted but never referenced in the body; the helper uses the snapshot's stored revision for its second check).

2. **tests/unit/test_storage_append_fact.py** — 13 new tests:
   - `test_crlf_history_no_trailing_newline` — CRLF body → CRLF separator (exact equality)
   - `test_lf_history_no_trailing_newline` — LF body → LF separator (exact equality)
   - `test_mixed_history_most_recent_crlf` — `"A\nB\r\nC"` → CRLF separator (exact equality)
   - `test_mixed_history_most_recent_lf` — `"A\r\nB\nC"` → LF separator (exact equality)
   - `test_no_previous_newline_fallback_lf` — `"Single line"` → LF fallback (exact equality)
   - `test_old_body_exact_prefix_for_crlf_no_trailing` — prefix invariant for CRLF history
   - `test_old_body_exact_prefix_for_lf_no_trailing` — prefix invariant for LF history
   - `test_old_body_exact_prefix_for_mixed_crlf_last` — prefix invariant for mixed CRLF-last
   - `test_old_body_exact_prefix_for_mixed_lf_last` — prefix invariant for mixed LF-last
   - `test_crlf_body_no_trailing_persisted_crlf` — repository-level CRLF persistence regression (verifies persisted body uses CRLF, original body is exact prefix, revision increments)

**Preserved semantics confirmed:**
- Empty body → `"- Fact\n"`
- Trailing CRLF → CRLF append
- Trailing LF → LF append
- Trailing lone CR → CR append
- No prior newline → LF fallback
- Old body remains exact prefix in every case
- No platform newline conversion
- All other S3-07 semantics unchanged (fact validation, bullet rendering, one fact per call, repository-owned revision +1, updated_at = audit.real_time, extra-frontmatter preservation, exact Entity metadata preservation, same-file atomic replacement, shared `_commit_entity_mutation`, audit intent → second check → atomic write → verified read-back → committed)

**Quality-gate results (after S3-07 correction):**
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py tests/unit/test_storage_audit.py tests/unit/test_storage_vault_repository.py tests/unit/test_storage_patch_repository.py tests/unit/test_storage_append_fact.py` — 479 passed, 19 skipped
- `uv run pytest` (full suite) — 1070 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 81 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-07 correction:** 2 files modified (storage/vault_repository.py, tests/unit/test_storage_append_fact.py), focused on CRLF inference correction and regression tests only.

**Scope exclusions confirmed:**
- No S3-08 integration hardening
- No S3-09 Stage-3 completion
- No new CRUD operations, delete, generic body editing, fact deduplication, provenance body syntax, locks, filesystem CAS, audit reconciliation, migrations
- No Retrieval, Calendar, Session runtime, Tool layer, ModelGateway, ChangeSet
- S3-08 was NOT started

**Code/test changes during S3-07:** 5 files (3 modified, 2 new), focused on append_entity_fact implementation and shared mutation-core refactoring only.

**Scope exclusions confirmed:**
- No generic body patch DTO, body delete/edit, fact removal, fact deduplication, fact IDs, fact timestamps in Markdown, Provenance blocks, Markdown heading management, arbitrary extra-frontmatter update, entity deletion, file rename/move, locks, filesystem CAS, automatic audit reconciliation
- No S3-08 broad hardening
- No S3-09 Stage-3 completion
- No Retrieval, Calendar, Session runtime, Tool Registry, ModelGateway, ChangeSet
- S3-08 was NOT started

### S3-08 correction (race safety + mutation-time path reauthorization)

**Review range:** S3-07 correction through S3-08 correction

**Commit:** `8b7671cee7a95f6bc62476b3b696abcb1fd8ecf0` (original S3-08), corrected in this task.

**Defects discovered during S3-08 review (production code):**

1. **Create target-occupancy race after durable intent.** The create lifecycle had no second pre-write check between audit intent and `atomic_write_text`. An external actor could create a regular file at the generated target path after intent, and `atomic_write_text` would silently replace it.

2. **Create duplicate-EntityId race after initial snapshot.** The initial snapshot confirmed the EntityId was unique, but no fresh snapshot was taken after intent. An external actor could create another entity with the same ID before the atomic write.

3. **Mutation-time authorization gap for long-lived filesystem topology.** Audit path validation and entity path authorization were only performed at repository construction time. A long-lived repository could have its audit directory, entity directory, or target file replaced by symlinks after construction, allowing writes to escape the Vault.

4. **Windows symlink skips prevented path-race scenarios from being exercised.** The original S3-08 symlink tests were all skipped on Windows, so the mutation-time authorization gap was not detected.

**Production code changes (storage/vault_repository.py):**

1. **`_validate_mutation_environment()`** (new) — runtime audit path revalidation called before every mutation. Checks: audit log still beneath `<vault_root>/_system/audit/`, no parent path component became a symlink, audit log itself is not a symlink, canonical `_system/audit/` directory still exists.

2. **`_reauthorize_entity_path()`** (new) — reauthorizes a stored entity path against current filesystem topology using `storage.paths.resolve_entity_path`. Detects symlink redirects, traversal, and path escape.

3. **`_StoredEntity._relative_path`** — new property storing the entity-relative path within the canonical type directory, enabling mutation-time reauthorization.

4. **Create second pre-write check** — after durable intent but before `atomic_write_text`:
   - Mutation environment revalidated (`_validate_mutation_environment`)
   - Target path reauthorized via `resolve_entity_path`
   - Target path must still NOT exist (`ConflictError` if occupied)
   - Target path must NOT be a symlink (`ConflictError` if symlink)
   - Fresh snapshot taken — duplicate EntityId detected (`ConflictError`)
   - On failure: intent remains, no committed record, no entity file

5. **Patch/append mutation-time reauthorization** — `_commit_entity_mutation` now calls `_validate_mutation_environment` and `_reauthorize_entity_path` after intent, before the second read check.

6. **Entry-point mutation environment validation** — `_validate_mutation_environment` called at the start of `create_entity`, `patch_entity`, and `append_entity_fact` (before any work begins).

**No changes to `atomic_write_text` replacement semantics.** The create "must remain absent" invariant is enforced in repository orchestration, not in the atomic primitive.

**ConflictError vs StorageError semantics:**
- `ConflictError` — target became occupied, duplicate EntityId appeared, revision/content changed (state conflict from another valid actor)
- `StorageError` — unsafe filesystem topology (symlink redirect, path escape, corrupt Vault, unsafe audit path)

**Audit intent remains on post-intent conflicts.** No `phase="aborted"` introduced. No audit schema change.

**Residual race still documented:** After the final pre-write check and before `os.replace`, another process could theoretically modify state. No locks/CAS/transaction manager added.

**Test changes (tests/integration/test_vault_repository_path_races.py):**

| Test class | Tests | Status |
|---|---|---|
| TestAuditDirectorySymlinkAfterConstruction | 4 tests (2 existing + 2 new: patch/append variants) | 4 skipped (symlink) |
| TestEntityDirectorySymlinkAfterConstruction | 2 tests (existing, unchanged) | 2 skipped (symlink) |
| TestNestedParentRedirect | 2 tests (1 existing + 1 new: append variant) | 2 skipped (symlink) |
| TestTargetSymlinkAfterIntent | 2 tests (1 existing + 1 new: append variant) | 2 skipped (symlink) |
| TestCreateRaceOccupiedTarget | 2 tests (NEW) | 1 passed, 1 skipped (symlink) |
| TestCreateRaceDuplicateEntityId | 2 tests (1 NEW + 1 existing) | 2 passed |
| TestTempFileCleanup | 3 tests (existing, unchanged) | 3 passed |

**New regression tests:**

- `test_target_occupied_after_intent_rejected` — creates a regular file at the generated target after intent; expects `ConflictError`; verifies intruder file untouched, intent exists, committed absent, no losing entity
- `test_target_becomes_symlink_after_intent_rejected` — replaces generated target with symlink after intent; expects `ConflictError`; skipped on Windows without symlink privilege
- `test_duplicate_id_appears_after_intent` — creates a valid entity with the same EntityId under a different filename after intent; expects `ConflictError`; verifies external entity untouched, only one entity with that ID exists, intent present, committed absent
- `test_audit_dir_symlink_blocks_patch` — audit dir replaced by symlink blocks patch via mutation-time validation
- `test_audit_dir_symlink_blocks_append` — audit dir replaced by symlink blocks append via mutation-time validation
- `test_nested_parent_symlink_blocks_append` — nested entity parent symlink blocks append
- `test_target_symlink_after_intent_append` — target replaced by symlink after intent blocks append

**Mocking policy:** Race tests wrap `AuditService.append` at the instance boundary (real filesystem side effects after intent). No module-identity patching of internal repository functions. `os.replace` patching retained only for temp-file cleanup tests.

**Windows skip policy:** Core create-race tests (occupied target, duplicate EntityId) run on Windows. Symlink-specific tests skip when `can_symlink()` returns False. Production fix supports all platforms.

**Quality-gate results:**

- `uv run pytest tests/integration/test_vault_repository_path_races.py` — 6 passed, 11 skipped
- `uv run pytest tests/integration/` — 49 passed, 11 skipped
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest` (full suite) — 1119 passed, 30 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-08 correction:** 2 files modified (storage/vault_repository.py, tests/integration/test_vault_repository_path_races.py). Focused on race safety and mutation-time reauthorization only.

**Scope exclusions confirmed:**
- No Stage 4 Calendar implementation
- No Retrieval, EntityResolver, Session runtime, ToolRegistry, ToolExecutor, ModelGateway, ChangeSet
- No delete_entity, replace_body, repair_audit, reconcile_intents, lock/unlock API, transactions
- No automatic audit repair, filesystem CAS, multi-process transaction service
- No golden campaign, performance benchmarks, property-based tests
- No locks, CAS, transaction manager
- No audit schema change (no `phase="aborted"`)
- No change to `atomic_write_text` replacement semantics
- S3-09 was NOT started

### S3-08 final correction (stable-target identity)

**Review range:** `473981c` through HEAD

**Root cause of remaining target-identity defect:**

The mutation-time reauthorization helper `_reauthorize_entity_path()` used
`resolve_entity_path()` to verify the target path was still inside the
approved canonical entity directory (containment check).  This is necessary
but not sufficient — an external actor could replace a parent directory
with a symlink to another directory inside the same canonical entity type
directory.  The containment check would pass, but the mutation would
target a different physical file.

Additionally, `_StoredEntity._relative_path` had a silent basename fallback
when the entity-relative path could not be derived from the canonical
entity directory, which could hide failures for nested entities.

**Exact stable-target reauthorization invariant:**

```
current_authorized_path == original_snapshot_path
```

where `original_snapshot_path = target.path`.  Equality of canonical
`Path` values is enforced, not merely containment.

**Production code changes (storage/vault_repository.py):**

1. **`_reauthorize_entity_path()` strengthened:**
   - New `expected_path` parameter (the originally selected entity path
     from the clean snapshot).
   - After `resolve_entity_path()` confirms containment, the resolved
     current path is compared against `expected_path` with `==`.
   - Mismatch raises `StorageError` with both paths in the diagnostic.
   - Path comparison uses canonical `Path` equality (not string).

2. **`_commit_entity_mutation()` updated:**
   - Calls `_reauthorize_entity_path()` with `expected_path=target.path`.

3. **`_StoredEntity.relative_path` derivation hardened:**
   - Silent `Path(path.name)` basename fallback removed.
   - If `path.relative_to(canon_dir)` fails, a `StorageError` is raised
     with the canonical directory path and cause preserved.
   - Every `_StoredEntity` produced by a clean snapshot now has a
     correctly derived entity-relative path.

**Create stable-target check preserved unchanged:**
`create_entity` already performs `reauthorized != target` comparison
after intent.  No changes to create logic.

**Audit revalidation preserved unchanged:**
`_validate_mutation_environment()` and audit parent symlink protection
are unchanged.

**atomic_write_text unchanged:**
No changes to the atomic write primitive.

**No locks/CAS/transaction manager added.**

**Test changes (tests/integration/test_vault_repository_path_races.py):**

| Test class | Tests | Status |
|---|---|---|
| TestStableTargetIdentity | 3 tests (NEW) | 3 passed |
| TestNestedParentRedirectStableTarget | 2 tests (NEW) | 2 skipped (symlink) |
| TestTargetFileSymlinkRedirect | 2 tests (NEW) | 2 skipped (symlink) |

**TestStableTargetIdentity (cross-platform, no symlinks):**
- `test_different_file_under_same_directory_rejected` — two valid normal
  files under the same entity directory; `relative_path` resolves to a
  different file than `expected_path`; expects `StorageError`.
- `test_same_file_under_same_directory_accepted` — same file resolves to
  itself; must succeed.
- `test_nested_entity_relative_path_preserved` — nested path like
  `Allies/Subgroup/entity.md` is preserved exactly and works for
  reauthorization.

**TestNestedParentRedirectStableTarget (symlink-capable):**
- `test_nested_parent_redirect_to_same_type_dir_rejected` — parent
  `Allies/` replaced by symlink to `Other/` (same canonical type dir);
  `Other/entity.md` has identical bytes so revision/hash would match;
  expects `StorageError` from stable-target identity check (not
  `ConflictError`).  Verifies redirected target unchanged, no committed
  audit, intent remains.
- `test_nested_parent_redirect_blocks_append` — same scenario for
  `append_entity_fact`.

**TestTargetFileSymlinkRedirect (symlink-capable):**
- `test_target_file_symlink_redirect_after_intent` — target file replaced
  after intent by a symlink to another file inside the same canonical
  type directory; expects `StorageError` or `ConflictError`; verifies
  redirect target unchanged, no committed audit.
- `test_target_file_symlink_redirect_after_intent_append` — same scenario
  for `append_entity_fact`.

**Residual race statement:**
After target reauthorization + revision/hash second check, there remains
a small TOCTOU window before `os.replace`.  No cross-process lock,
filesystem CAS, or transaction manager is claimed.  Fully race-free
multiprocess writes are not within S3-08 scope.

**Quality-gate results:**

- `uv run pytest tests/integration/test_vault_repository_path_races.py` — 9 passed, 15 skipped
- `uv run pytest tests/integration/` — 52 passed, 15 skipped
- `uv run pytest tests/unit/test_storage_paths.py` — 56 passed, 10 skipped
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest` (full suite) — 1122 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-08 final correction:**
3 files modified (storage/vault_repository.py, tests/integration/test_vault_repository_path_races.py, DEVELOPMENT_STATUS.md).
Focused on stable-target identity enforcement only.

**Scope exclusions confirmed:**
- No new public API
- No S3-09 changes
- No atomic primitive changes
- No locks/CAS/transaction manager
- No Stage 4 Calendar implementation
- No Retrieval, EntityResolver, Session runtime, ToolRegistry, ToolExecutor, ModelGateway, ChangeSet

### S3-09 Stage 3 completion record

**Review boundary:**
- base: `22a21d3f34e6d3d028c644e4fadc7c7e1dd393a8`
- implementation review head: `f4142483e16a06f0238384fbf103a7826d9881a4`
- range: `22a21d3..f414248`

**Historical classification:**
- 17 Stage-3 implementation/correction commits
- 1 concurrent auxiliary commit `a557386` (add golden test vault) inside range — auxiliary fixture content excluded from Stage-3 implementation accounting

**Final implemented components:**
- storage contracts (`VaultDocument`, `EntityDirectory`, `VaultRepository` Protocol)
- Markdown/YAML codec (`parse`, `serialize`)
- Vault path safety and entity discovery (`paths.py`)
- Atomic write primitive (`atomic_write_text`)
- Append-only audit (`AuditRecord`, `AuditContext`, `AuditService`)
- Repository create/read/list (`ObsidianVaultRepository`)
- Optimistic entity patching (`EntityPatch`, `patch_entity`)
- Append entity fact (`append_entity_fact`)
- Integration/failure hardening (race safety, mutation-time reauthorization, stable-target identity)

**Final invariants confirmed:**
- Source-of-Truth safe Vault persistence
- Stable IDs (EntityId, not filename)
- Revision-based optimistic concurrency
- Markdown body preservation character-for-character
- Extra-frontmatter semantic preservation
- Atomic replacement (temp sibling → fsync → validator → os.replace)
- Append-only audit with intent/committed two-phase lifecycle
- Write-ahead intent before any filesystem mutation
- SHA-256 exact content hashes (before/after)
- Mutation-time path reauthorization (environment + stable-target identity)
- Global duplicate EntityId detection
- Failure/recovery semantics (no mutation before intent, intent remains on failure, no rollback after committed write)

**Review findings:** None

**Code/test/doc corrections during S3-09:**
- Fixed trailing whitespace in DEVELOPMENT_STATUS.md line 5
- Updated DEVELOPMENT_STATUS.md to Stage 3 DONE state

**Quality gates:**
- `uv run pytest tests/contract/test_boundaries.py` — 26 passed
- `uv run pytest tests/unit/test_storage_*.py` — 519 passed, 19 skipped
- `uv run pytest tests/integration/` — 52 passed, 15 skipped
- `uv run pytest` (full suite) — 1122 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors (after trailing-whitespace fix)

**Known intentional limitations:**
- No cross-process lock/CAS — residual TOCTOU before final `os.replace`
- Uncertain audit append may leave detectable partial tail
- No automatic audit intent reconciliation/repair
- Symlink tests skipped on Windows without symlink privileges (19 of 34 skipped tests are symlink-dependent)

## Current blockers

None recorded.

## Stage 2 — Domain schemas

### Goal

Design and implement the core domain schemas and deterministic validation contracts for Entity, foundational domain types, Session, TimelineEvent, and CampaignState, without persistence, calendar arithmetic, model-provider, or tool-layer dependencies.

### Tasks

- [x] `S2-00` Fix CLI entrypoint, add `cli/main.py`, add smoke test, verify quality gates.
- [x] `S2-01` Core domain types:
    - EntityId
    - EntityType
    - KnowledgeStatus
    - Visibility
    - Provenance
    - Revision
- [x] `S2-02` Base Entity schema
- [x] `S2-03` Session schema
- [x] `S2-04` TimelineEvent schema
- [x] `S2-05` CampaignState schema
- [x] `S2-06` Review deferred Stage 1 contracts against real domain types
- [x] `S2-07` Full Stage 2 verification, diff review and status update

### S2-06 deferred contract review

Reviewed Stage 1 deferred contracts against completed Stage 2 domain schemas (EntityId, EntityType, KnowledgeStatus, Visibility, Provenance, Revision, Entity, Session, TimelineEvent, TemporalCertainty, CampaignState).

**Contracts with docstring-only files reviewed:**
- `CalendarService` (`domain/calendar.py`) — deferred to Stage 4
- `ModelGateway` (`models/gateway.py`) — deferred to Stage 8
- `AuditService` (`storage/audit.py`) — deferred to Stage 3
- `ToolRegistry` (`tools/registry.py`) — deferred to Stage 7

**Contracts with no source file (inventoried in Stage 1 scope only):**
- `VaultRepository` — deferred to Stage 3
- `SearchService` — deferred to Stage 5
- `EntityResolver` — deferred to Stage 5
- `SessionService` — deferred to Stage 6
- `ToolExecutor` — deferred to Stage 7
- `PostSessionProcessor` — deferred to Stage 11
- `BootstrapService` — deferred to Stage 13

**Result:**
- All current deferrals confirmed correct.
- No Stage 2 domain type provides sufficient semantics to finalize any deferred typed signature without inventing placeholder DTOs, persistence semantics, calendar types, tool metadata, provider types, or sync/async decisions that belong to later stages.
- `models/gateway.py` correctly avoids importing domain types; adding typed signatures with domain models would reverse the intended dependency direction.
- No production-code contract changes required.
- No placeholder DTOs or speculative APIs introduced.
- Existing deferred-contract documentation is accurate and not stale.
