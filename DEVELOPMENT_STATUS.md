# D&D Session Assistant — Development Status

**Last updated:** 2026-08-30  
**Current milestone:** `v0.1-dev — Vault Core`  
**Current stage:** `Stage 3 — Vault Repository`  
**Status:** `IN PROGRESS` (S3-01 complete, S3-02 not started)

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
| 3. Vault Repository | IN PROGRESS | 2026-08-30 | — |
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

**Stage 3 status:** IN PROGRESS — S3-00 (kickoff + storage contracts) is the active task.

## Stage 3 — Vault Repository

### Goal

Implement the trusted Vault persistence layer for Obsidian Markdown/YAML entities, providing create, read, update, and append operations with atomic writes, optimistic concurrency, path safety, Markdown body preservation, and audit logging.

### Tasks

- [x] `S3-00` Stage kickoff + repository/storage contracts
- [x] `S3-01` Markdown/YAML document codec
- [ ] `S3-02` Vault path safety + entity directory/discovery policy
- [ ] `S3-03` Atomic write primitive
- [ ] `S3-04` AuditRecord + AuditService
- [ ] `S3-05` create_entity / get_entity / list_entities
- [ ] `S3-06` patch_entity + optimistic concurrency
- [ ] `S3-07` append_entity_fact
- [ ] `S3-08` integration/failure tests
- [ ] `S3-09` full Stage 3 verification/diff/status

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

**Review range:** S3-01 completion through S3-02

**Changes:**

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
3. **tests/unit/test_storage_paths.py** (new) — 58 tests (55 pass, 3 symlink tests skipped on Windows without symlink privileges):
   - `TestDiscoveredEntityFile` — 7 tests: construct, equality, inequality, hashable, repr, non-Discovered comparison
   - `TestHasTraversal` — 8 tests: simple, nested, `..` rejection, nested `..`, absolute, Windows absolute, Unicode, spaces
   - `TestResolveVaultRoot` — 5 tests: existing dir, missing, file, string path, canonical resolution
   - `TestEntityDirectoryFn` — 6 tests (4 parametrized): all four EntityTypes, rooted under vault, invalid root
   - `TestResolveEntityPath` — 12 tests: simple, nested, Unicode, spaces, `..` rejection, nested `..`, absolute, wrong directory escape, non-Markdown, missing root, uppercase `.MD`
   - `TestDiscoverEntityFiles` — 12 tests: finds `.md`, ignores non-Markdown, nested subdirs, scoped to type, all-types, ignores unrelated dirs, missing dir yields empty, file-as-dir error, deterministic ordering (single type + across types), filename-not-entity-id
   - `TestSymlinkSafety` — 3 tests (skipped when `_can_symlink()` is False): directory symlink not traversed, file symlink not returned, symlink doesn't escape entity directory
   - `TestFilesystemErrors` — 1 test: monkeypatched `iterdir` failure raises `StorageError`
   - Import/boundary — 6 tests: module importable, API re-exported, no model/retrieval/tool imports, no markdown codec import

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
- Results are deterministically ordered by Vault-relative POSIX path (casefold)

**Symlink policy established:**
- Discovery does NOT follow symlinked directories
- Symlinked files are NOT treated as entity-file candidates
- A symlink must never allow discovery to escape the vault root or an approved entity directory
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

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_paths.py` — 55 passed, 3 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 162 passed, 3 skipped
- `uv run pytest` (full suite) — 713 passed, 3 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 72 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-02:** None

**Code/test changes during S3-02:** 4 files (2 modified, 2 new), focused on path safety and entity discovery only.

**Scope exclusions confirmed:**
- No Markdown parsing changes
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No duplicate EntityId checks, repository ID index/cache, SQLite
- No filename generation or directory creation for entity persistence
- No atomic write, fsync, audit JSONL, revision increments, locks, migrations
- No Calendar, Retrieval/EntityResolver, Session runtime, Tool layer, ModelGateway, or ChangeSet

**Stage 3 status:** IN PROGRESS — S3-02 complete, S3-03 not started.

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
