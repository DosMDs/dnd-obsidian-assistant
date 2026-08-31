# Stage 2 — Domain schemas

## Objective

Design and implement the core domain schemas and deterministic validation
contracts for Entity, foundational domain types, Session, TimelineEvent, and
CampaignState, without persistence, calendar arithmetic, model-provider, or
tool-layer dependencies.

## Tasks

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

## Definition of Done

- All core domain types implemented and tested
- Entity schema with `extra="forbid"`, revision, timestamps, session refs
- Session schema with world_tick range, status, processed flag
- TimelineEvent schema with TemporalCertainty, temporal consistency validation
- CampaignState compact snapshot with EntityId references
- No storage implementation
- No calendar arithmetic
- No retrieval/entity resolution
- No session runtime
- No ModelGateway/Ollama dependency
- Domain dependency direction is clean
- Quality gates pass

## Implementation history

### S2-06 deferred contract review

Reviewed Stage 1 deferred contracts against completed Stage 2 domain schemas
(EntityId, EntityType, KnowledgeStatus, Visibility, Provenance, Revision,
Entity, Session, TimelineEvent, TemporalCertainty, CampaignState).

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
- No Stage 2 domain type provides sufficient semantics to finalize any deferred
  typed signature without inventing placeholder DTOs, persistence semantics,
  calendar types, tool metadata, provider types, or sync/async decisions that
  belong to later stages.
- `models/gateway.py` correctly avoids importing domain types; adding typed
  signatures with domain models would reverse the intended dependency direction.
- No production-code contract changes required.
- No placeholder DTOs or speculative APIs introduced.
- Existing deferred-contract documentation is accurate and not stale.

### Stage 2 completion (S2-07)

**Review range:** `5a38ea0..HEAD` (pre-Stage-2 boundary through S2-06)

**Implemented domain types/models:**
- `EntityId` — validated printable-Unicode string identifier
- `EntityType` — MVP-only: npc, location, quest, item
- `KnowledgeStatus` — epistemic: confirmed, reported, rumor, inferred, unknown
- `Visibility` — player, dm, system
- `Provenance` — manual, session, bootstrap, import, model_inference
- `Revision` — strict int >= 1, no bool/string coercion
- `Entity` — base schema with schema_version, id, type, name, status, visibility,
  knowledge_status, session refs, timestamps, revision, tags; `extra="forbid"`
- `Session` — schema with id, type discriminator, status, real timestamps,
  world_tick range, processed flag, model profile, revision; `extra="forbid"`
- `TemporalCertainty` — exact, approximate, range, unknown (separate from
  KnowledgeStatus)
- `TimelineEvent` — schema with id, type discriminator, name, status, certainty,
  importance, world_tick fields with model-level temporal consistency validation,
  location, visibility, revision; `extra="forbid"`
- `CampaignState` — compact snapshot with EntityId references (current_location,
  active_quests, important_npcs, upcoming_deadlines) and printable-string lists
  (party_goals, unresolved_threads); `extra="forbid"`

**Architectural boundaries confirmed:**
- `EntityType` is MVP-only (no timeline_event, campaign_state, session added)
- `TemporalCertainty` is separate from `KnowledgeStatus`
- No Stage 4 calendar implementation
- No storage implementation
- No retrieval implementation
- No session runtime implementation
- No tool-layer implementation
- No ModelGateway implementation/provider coupling
- No CampaignState processing implementation
- All deferred contracts remain correctly assigned to later stages
- Domain dependency direction is clean

**Final quality-gate results:**
- `uv run pytest tests/unit/test_domain_types.py` — 53 passed
- `uv run pytest tests/unit/test_entity.py` — 119 passed
- `uv run pytest tests/unit/test_session.py` — 103 passed
- `uv run pytest tests/unit/test_timeline_event.py` — 137 passed
- `uv run pytest tests/unit/test_campaign_state.py` — 89 passed
- `uv run pytest tests/unit/test_imports.py tests/unit/test_gateway_protocol.py
  tests/unit/test_audit_protocol.py tests/unit/test_tool_registry_protocol.py` — 13 passed
- `uv run pytest` (full suite) — 551 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 66 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S2-07:** None

**Code/test changes during S2-07:** None (only DEVELOPMENT_STATUS.md updated)

**Stage 2 status:** DONE.