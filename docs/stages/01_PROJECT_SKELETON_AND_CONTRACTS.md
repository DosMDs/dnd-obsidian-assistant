# Stage 1 — Project skeleton + contracts

## Objective

Create explicit package boundaries and common project contracts before domain/storage implementation begins.

This stage deliberately contains **no LLM runtime implementation** and **no Vault persistence implementation**.

## Inputs

- project architecture and boundaries;
- implementation roadmap;
- accepted engineering decisions;
- `DEVELOPMENT_STATUS.md`;
- `GIGACODE.md`.

## Expected package areas

```text
src/dnd_assistant/
├── cli/
├── application/
├── domain/
├── storage/
├── retrieval/
├── tools/
├── models/
├── prompts/
└── evals/
```

Tests:

```text
tests/
├── unit/
├── integration/
├── contract/
├── e2e/
└── fixtures/
```

## Interface inventory

The project is expected to expose clear boundaries for:

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

### Rule for signatures

Do not invent weak placeholder types simply to finish the inventory.

If a final method signature depends on a domain concept that is intentionally introduced in Stage 2, document the responsibility here and complete the typed signature together with that domain concept.

## Shared errors

Target hierarchy:

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

Use project errors at architectural boundaries rather than leaking provider/library-specific exceptions into callers.

## Dependency direction

Forbidden examples:

```text
domain -> OllamaProvider
storage -> OllamaProvider
domain -> CLI
storage -> CLI
CalendarService -> LLM
```

Expected orchestration direction:

```text
CLI
 ↓
Application
 ├── domain/service contracts
 ├── retrieval contracts
 ├── storage contracts
 └── ModelGateway contract (later implementation)
```

## Task breakdown

### CTR-001 — Package skeleton

Verify/create importable packages and `__init__.py` files where required.

Do not add placeholder business logic.

### CTR-002 — Error hierarchy

Implement common project errors in a provider-neutral module.

Add unit tests for hierarchy/catch behavior where useful.

### CTR-003 — Core contracts

Create the boundary modules/protocols that can be expressed honestly at this stage.

Prefer `typing.Protocol` when structural interfaces are useful and there is no need for inherited implementation.

Do not introduce a dependency solely to enforce interfaces.

### CTR-004 — Responsibility documentation

Each core interface/module should state:

- what it owns;
- what it must not own;
- which layer may call it;
- expected failure boundary.

### CTR-005 — Contract/import tests

Add tests that verify:

- expected modules import;
- no Ollama/provider import is required for domain/storage import;
- normal pytest collection does not need an Ollama service.

### CTR-006 — Boundary review

Review imports and ensure provider-specific details remain outside domain/storage.

### CTR-007 — Quality gates

Run:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### CTR-008 — Completion record

Review the diff, update `DEVELOPMENT_STATUS.md`, and commit the completed stage/task increment.

## Out of scope

Do not implement yet:

- Entity/Pydantic domain schemas beyond what is necessary for an honest shared error/contract;
- Vault Markdown/YAML persistence;
- atomic writes;
- calendar arithmetic;
- search/FTS;
- sessions;
- ToolExecutor behavior;
- OllamaProvider;
- agent loops;
- ChangeSet.

## Definition of Done

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
- `DEVELOPMENT_STATUS.md` is updated with current status only (detailed completion record goes here).

## Implementation history

### CTR-001 through CTR-007

Package skeleton, error hierarchy, core contracts, responsibility documentation,
contract/import tests, boundary review, and quality gates were implemented as
part of Stage 1.

### CTR-008 — Completion record

Review the diff, update `DEVELOPMENT_STATUS.md` with current status only
(checkbox/state), and record the detailed completion evidence in this stage
document.

### Stage 1 completion

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

**Stage 1 status:** DONE.
