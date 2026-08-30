# D&D Session Assistant — Development Status

**Last updated:** 2026-08-30  
**Current milestone:** `v0.1-dev — Vault Core`  
**Current stage:** `Stage 2 — Domain schemas`  
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
|---|---|---:|---:|
| 0. Environment | DONE | 2026-08-27 | 2026-08-27 |
| 1. Project skeleton + contracts | DONE | 2026-08-27 | 2026-08-30 |
| 2. Domain schemas | IN PROGRESS | 2026-08-30 | — |
| 3. Vault Repository | NOT STARTED | — | — |
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
- [ ] `S2-07` Full Stage 2 verification, diff review and status update

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
