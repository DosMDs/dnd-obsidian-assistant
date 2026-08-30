# D&D Session Assistant — Development Status

**Last updated:** 2026-08-30  
**Current milestone:** `v0.1-dev — Vault Core`  
**Current stage:** `Stage 3 — Vault Repository`  
**Status:** `IN PROGRESS`

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
- [ ] `S3-01` Markdown/YAML document codec
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

**Stage 3 status:** IN PROGRESS — S3-00 complete, S3-01 not started.

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
