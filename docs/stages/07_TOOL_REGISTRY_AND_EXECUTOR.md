# Stage 7 — Tool Registry and Executor

## Objective

Establish the deterministic Python Tool Layer between future agent/model
code and existing trusted Python services. Stage 7 provides the typed
provider-neutral contracts, registry, and execution pipeline that concrete
campaign tools will use in later increments.

Stage 7 is strictly LLM-free, Ollama-free, ModelGateway-free, Fast-Agent-free,
provider-schema-free, and ChangeSet-free.

## Dependency on accepted stages

| Stage | Dependency |
|---|---|
| Stage 1 — Project skeleton + contracts | Error hierarchy (`DndAssistantError`, `ValidationError`, `NotFoundError`, `ConflictError`) |
| Stage 3 — Vault Repository | `AuditContext` (TYPE_CHECKING-only reference in `ExecutionContext`) |
| Stage 6 — Session Runtime | Session-mode vocabulary (independent but referenced by `SessionMode`) |

## Planned task map

| Task | Status | Description |
|---|---|---|
| S7-00 | DONE | Foundational contracts: typed metadata, ToolRegistry, ToolExecutor, permissions, side effects, session modes, tests, documentation |
| S7-C00 | DONE | Correction pass for S7-00: fix exception handling, audit typing, handler typing, tool-name validation, documentation, status normalization |
| S7-C01 | DONE | Finalize Stage-7 status/document consistency after S7-C00 review |
| S7-C02 | DONE | Correct Stage-7 malformed status-table separator |
| S7-01 | DONE | Entity read tools |
| S7-C03 | DONE | Harden entity read-tool safety |
| S7-C04 | DONE | Finalize S7-01/C03 documentation and boundary contracts |
| S7-02 | DONE | Session read tools |
| S7-C05 | DONE | Strengthen session read public DTO contracts |
| S7-03 | NOT STARTED | Session mutation tools |
| S7-04 | NOT STARTED | World-time read + deterministic calendar read surface |
| S7-05 | NOT STARTED | World-time mutation tools |
| S7-06 | NOT STARTED | Safe entity mutation tools |
| S7-07 | NOT STARTED | Cross-family integration / public registry schema / Golden-Vault hardening |
| S7-08 | NOT STARTED | Full Stage-7 historical review / verification / completion |

## S7-00 scope and contracts

### Module shape

```
src/dnd_assistant/tools/
    __init__.py    — public exports (ToolRegistry, ToolExecutor, Permission,
                     SideEffect, SessionMode, ToolDefinition, ExecutionContext)
    types.py       — Permission, SideEffect, SessionMode, ToolDefinition,
                     ToolBinding, ExecutionContext, convert_validation_error
    registry.py    — ToolRegistry: register, lookup, list
    executor.py    — ToolExecutor: validated execution pipeline
```

### Permission semantics

- `Permission.READ` — may invoke only READ-permission tools.
- `Permission.WRITE` — may invoke both READ and WRITE tools.
- This is a minimal MVP boundary, not RBAC.

### Side-effect semantics

- `SideEffect.ENTITY_MUTATION` — mutates campaign entities.
- `SideEffect.SESSION_MUTATION` — mutates session state.
- `SideEffect.WORLD_TIME_MUTATION` — mutates world time.
- READ tools must have an empty side-effect set.
- WRITE tools must declare at least one supported side effect.

### Session-mode semantics

- `SessionMode.NO_ACTIVE_SESSION` — no active session exists.
- `SessionMode.ACTIVE_SESSION` — an active session exists.
- A ToolDefinition must allow one or both modes.
- These are execution-state vocabulary, not `Session.status` values.

### ToolDefinition metadata

- `name` — deterministic snake_case machine name (validated).
- `description` — non-empty printable text.
- `input_schema` — Pydantic `BaseModel` subclass.
- `output_schema` — Pydantic `BaseModel` subclass.
- `permission` — `Permission` enum.
- `side_effects` — `frozenset[SideEffect]`.
- `allowed_session_modes` — `frozenset[SessionMode]`.
- Immutable (`frozen=True`, `extra="forbid"`).
- Pydantic validation errors are converted to project `ValidationError`.

### ToolRegistry behavior

- `register(definition, handler)` — register a tool.
- `get(name)` — returns `ToolBinding`.
- `get_definition(name)` — returns `ToolDefinition`.
- `list_definitions()` — deterministic sorted-by-name listing.
- `__len__()` — count of registered tools.
- Does NOT execute handlers.
- No filesystem access.
- No dependency on storage, domain, models, retrieval, application, CLI, Ollama.

### ToolExecutor execution order

1. Registry lookup.
2. Raw input validation against `ToolDefinition.input_schema`.
3. Permission validation.
4. Allowed-session-mode validation.
5. WRITE AuditContext prerequisite.
6. Handler invocation exactly once.
7. Output validation against `ToolDefinition.output_schema`.
8. Return typed output.

### Error mapping

| Condition | Exception |
|---|---|
| Unknown tool name | `NotFoundError` |
| Invalid input/output | `ValidationError` |
| Permission denied | `ConflictError` |
| Session mode denied | `ConflictError` |
| WRITE without AuditContext | `ValidationError` |
| Handler raises `DndAssistantError` | Propagated unchanged |
| Handler raises unexpected exception | Propagated unchanged (programming bugs, runtime failures remain visible) |

### AuditContext ownership

- `ExecutionContext` is a frozen dataclass (not a Pydantic model) to avoid
  a runtime dependency on `storage.audit` at the tools layer.
- `audit: AuditContext | None` is the canonical type; static type checkers
  see the real type through a `TYPE_CHECKING` import.
- ToolExecutor checks that `audit is not None` for WRITE invocations.
- ToolExecutor does NOT create or write audit records.
- The existing application/repository pattern owns mutation audit.

### Boundary/import verification

- `tools.registry` does not import `storage`, `domain`, `models`.
- `tools.executor` does not import `storage` (runtime), `domain`, `models`,
  `application`, `ollama`.
- `tools.types` does not import `storage`, `domain`, `models`, `ollama`.
- `dnd_assistant.tools` does not trigger `ollama` import.
- `application.session_runtime` does not import `tools`.
- All existing boundary tests pass.

### Explicit deferrals from S7-00

- Concrete entity/session/calendar tools.
- OpenAI/Ollama function-calling JSON adapters.
- Generic plugin framework, DI framework, IAM/RBAC system, middleware
  framework, event bus, or speculative abstractions.
- Tool-invocation trace/audit subsystem.
- Async execution.
- `ToolError` hierarchy (existing `DndAssistantError` subclasses suffice).

## S7-00 completion evidence

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/types.py` | **NEW** — Permission, SideEffect, SessionMode, ToolDefinition, ToolBinding, ExecutionContext, convert_validation_error |
| `src/dnd_assistant/tools/registry.py` | **REPLACED** — deferred docstring with executable ToolRegistry |
| `src/dnd_assistant/tools/executor.py` | **NEW** — ToolExecutor with full execution pipeline |
| `src/dnd_assistant/tools/__init__.py` | **REPLACED** — empty file with public exports |
| `tests/unit/test_tool_types.py` | **NEW** — 32 tests for type definitions |
| `tests/unit/test_tool_registry.py` | **NEW** — 16 tests for registry behavior |
| `tests/unit/test_tool_executor.py` | **NEW** — 20 tests for executor pipeline |
| `tests/contract/test_boundaries.py` | **UPDATED** — added executor/types boundary tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **NEW** — this document |
| `docs/stages/README.md` | **UPDATED** — added Stage 7 entry |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — Stage 7 IN PROGRESS, S7-00 DONE |

### Test results

- 68/68 tool layer unit tests pass.
- 59/59 boundary tests pass (including 9 new executor/types tests).
- 226/226 maintainability tests pass.
- Full `uv run pytest`: all tests pass.

### Quality gates

- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Commit

- SHA: (reported in Final Report)
- Message: `feat: establish tool registry and executor core (S7-00)`

### Stage status

- Stage 7 remains **IN PROGRESS**.
- S7-01 has **NOT** been started.

---

## S7-C00 — Correction record

### Defects found

1. **C00-1**: `ToolExecutor.execute()` caught arbitrary `Exception` from handler and converted to `ValidationError`, masking programming bugs and runtime failures.
2. **C00-2**: `convert_validation_error()` was too broad — accepted any `Exception` and converted `ValueError`, `TypeError`, and generic `Exception` into project `ValidationError`.
3. **C00-3**: `ExecutionContext.audit` was typed as `Any` with a non-existent `TYPE_CHECKING` import, providing no static type safety.
4. **C00-4**: `Handler = Callable[..., BaseModel]` was too weak — didn't represent actual handler signature or allow non-BaseModel return values.
5. **C00-5**: Tool-name validation used `str.isalnum()` which accepts non-ASCII Unicode letters, contradicting the documented "lowercase ASCII" contract.
6. **C00-6**: Stage-7 task map incorrectly included S7-04 "Provider-native schema adaptation (ModelGateway integration)" which belongs to Stage 8.
7. **C00-7**: `DEVELOPMENT_STATUS.md` had duplicate "Current stage tasks" sections — one still containing the entire completed Stage-6 task list.
8. **C00-8**: Markdown table separators had wrong column counts in `DEVELOPMENT_STATUS.md` (6 columns for 5-column header) and `docs/stages/README.md` (3 columns for 2-column header).

### Root cause

S7-00 implementation was reviewed and merged without a focused architectural review pass.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/types.py` | **REWRITTEN** — `ExecutionContext` changed from Pydantic model to frozen dataclass with `AuditContext \| None`; `convert_validation_error` → `convert_pydantic_validation_error` (narrow, only accepts `PydanticValidationError`); `Handler` tightened to `Callable[[BaseModel, ExecutionContext], object]`; tool-name validation uses explicit ASCII regex `^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$` |
| `src/dnd_assistant/tools/executor.py` | **EDITED** — removed broad `except Exception` handler wrapper; input/output validation uses narrow `convert_pydantic_validation_error`; added `PydanticValidationError` import; removed unused `DndAssistantError` import |
| `src/dnd_assistant/tools/__init__.py` | **EDITED** — export `convert_pydantic_validation_error` |
| `tests/unit/test_tool_types.py` | **EDITED** — updated conversion tests for narrow helper; added 6 non-ASCII/underscore tool-name rejection tests; fixed `ExecutionContext` frozen test for dataclass `FrozenInstanceError` |
| `tests/unit/test_tool_executor.py` | **EDITED** — added `test_handler_runtime_error_propagates_unchanged` regression; `write_context` fixture uses real `AuditContext` instead of `object()` |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — corrected task map (removed Stage-8 S7-04, added S7-C00..S7-08); corrected error mapping; corrected AuditContext documentation; added this correction record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — removed duplicate Stage-6 task section; fixed table separator column count |
| `docs/stages/README.md` | **EDITED** — fixed table separator column count |

### Corrected contracts

- **Exception propagation**: Handler `RuntimeError`, `TypeError`, `AssertionError` etc. propagate unchanged. Only `DndAssistantError` subclasses are propagated as-is (no wrapping). Only `PydanticValidationError` from input/output schema validation is converted to project `ValidationError`.
- **Input/output validation conversion**: `convert_pydantic_validation_error()` accepts only `PydanticValidationError`. Non-Pydantic exceptions raise `TypeError`.
- **ExecutionContext.audit type**: `AuditContext | None` via `TYPE_CHECKING` import. No runtime storage dependency. Frozen dataclass instead of Pydantic model.
- **Handler type**: `Callable[[BaseModel, ExecutionContext], object]`.
- **Tool-name grammar**: `^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$` — rejects Cyrillic, CJK, accented Latin, leading/trailing/double underscores.

### Regression tests added

- `test_handler_runtime_error_propagates_unchanged` — handler `RuntimeError("boom")` reaches caller as `RuntimeError`.
- `test_cyrillic_name_rejected` — `инструмент` rejected.
- `test_cjk_name_rejected` — `工具` rejected.
- `test_accented_latin_rejected` — `éxample` rejected.
- `test_leading_underscore_rejected` — `_tool` rejected.
- `test_trailing_underscore_rejected` — `tool_` rejected.
- `test_double_underscore_rejected` — `tool__name` rejected.
- `test_rejects_non_pydantic_exception` — `convert_pydantic_validation_error(ValueError(...))` raises `TypeError`.

### Quality-gate evidence

- 74/74 tool layer unit tests pass (was 68/68 before corrections).
- 59/59 boundary tests pass.
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Commit

- SHA: (reported in Final Report)
- Message: `fix: correct foundational tool contracts (S7-C00)`

### Stage status

- Stage 7 remains **IN PROGRESS**.
- S7-01 has **NOT** been started.

---

## S7-C01 — Correction record

### Scope

Documentation-only consistency pass. No production code or test behavior changed.

### Defects found

1. **C01-1**: `DEVELOPMENT_STATUS.md` Stage-7 task map was incomplete — listed only S7-00 and S7-C00. S7-01 through S7-08 were missing.
2. **C01-2**: No S7-C01 entry existed in either `DEVELOPMENT_STATUS.md` or the Stage-7 task map.

### Changes

| File | Change |
|---|---|
| `DEVELOPMENT_STATUS.md` | Restored full Stage-7 task map (S7-00..S7-08) with correct statuses; added S7-C01 as DONE |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | Added S7-C01 to task map; appended this correction record |

### Stage status

- Stage 7 remains **IN PROGRESS**.
- S7-01 remains **NOT STARTED**.

---

## S7-C02 — Correction record

### Scope

Documentation-only consistency pass. No production code or test behavior changed.

### Defects found

1. **C02-1**: `DEVELOPMENT_STATUS.md` Current stage tasks table had a malformed Markdown separator — `|---|---|---|` (3 columns) for a 2-column header `| Task | Status |`.

### Changes

| File | Change |
|---|---|
| `DEVELOPMENT_STATUS.md` | Corrected table separator from `|---|---|---|` to `|---|---|` |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | Added S7-C02 to task map; appended this correction record |

### Stage status

- Stage 7 remains **IN PROGRESS**.
- S7-01 is **DONE**.

---

## S7-01 — Entity read tools

### Scope

Implement two concrete entity read tools (`search_entities` and `get_entity`)
that expose existing deterministic Python retrieval/storage behaviour through
the ToolRegistry/ToolExecutor contracts.

### Module shape

```
src/dnd_assistant/tools/
    entity_reads.py    — NEW: search_entities and get_entity tools
```

### search_entities

- Input: `SearchEntitiesInput` (text, optional entity_types, limit).
- Output: `SearchEntitiesOutput` (ordered list of `EntitySearchResult`).
- Flow: `SearchQuery` → `SearchService.search()` → hydrate through
  `VaultRepository.get_entity()` → fail-closed consistency checks →
  typed output.
- Preserves SearchService ordering.

### get_entity

- Input: `GetEntityInput` (entity_id).
- Output: `GetEntityOutput` (Entity + Markdown body).
- Flow: `SearchService.get_by_id()` (player-visibility gate) →
  requested-ID vs SearchHit-ID consistency check →
  `VaultRepository.get_entity()` using original requested ID →
  hydrated-document ID consistency check → player-visibility check →
  typed output.

### SearchService visibility-gate decision

`SearchService` is the player-visibility gate. Only `Visibility.PLAYER`
entities may be returned. `None` from `get_by_id` produces a generic
`NotFoundError` indistinguishable from "entity does not exist".

### Fail-closed hydration design

After hydration, two consistency checks are enforced:

1. `doc.entity.id == requested_id` (hydrated document matches the
   original validated input).
2. `doc.entity.visibility == Visibility.PLAYER` (no DM/system entity
   leaks through a compromised or inconsistent gate).

Both failures raise `StorageError` with a non-disclosing generic message
that does not reveal hidden entity IDs, visibility values, or filesystem
details.

### Input/output DTOs

- `SearchEntitiesInput` — validated text, optional entity_types, limit (>= 1).
- `SearchEntitiesOutput` — ordered list of `EntitySearchResult`.
- `EntitySearchResult` — entity_id, entity_type, name, status, match_kind,
  optional score.
- `GetEntityInput` — validated EntityId.
- `GetEntityOutput` — Entity + body (extra_frontmatter deferred).

### Registration/composition design

`register_entity_read_tools(registry, *, search_service, repository)` is
the public registration API. It accepts a `ToolRegistry` instance (typed
and validated with `isinstance`) and wires both tools with their
dependencies via closures.

### extra_frontmatter deferral

`GetEntityOutput` does not include `extra_frontmatter`. The S7-01 scope
does not yet have an accepted stable model-facing serialisation contract
for arbitrary unknown YAML values.

### Core-package lightweight-import decision

`dnd_assistant.tools.__init__` does not import `entity_reads`. Concrete
tools must be imported explicitly by composition code. This keeps the
core package import lightweight and avoids eager loading of retrieval
and storage contracts at package root.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/entity_reads.py` | **NEW** — search_entities and get_entity tools |
| `tests/unit/test_entity_read_tools.py` | **NEW** — handler behaviour, executor integration, mutation-safety tests |
| `tests/contract/test_boundaries.py` | **UPDATED** — added tools-package lightweight-import tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **UPDATED** — added S7-01 to task map; this record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-01 DONE |

### Tests and quality gates

- 68 tool layer unit tests pass (including 27 new entity-read tests).
- 65 boundary tests pass (including 6 new tools-package tests).
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Explicit non-goals

- Session read tools (S7-02).
- Session mutation tools (S7-03).
- World-time tools (S7-04, S7-05).
- Entity mutation tools (S7-06).
- Cross-family integration (S7-07).
- Provider schema adaptation.
- ModelGateway/Ollama integration.
- Fast Agent.
- ChangeSet.
- Post-session processing.
- Global registry bootstrap.

### S7-01 completion state

- S7-01 is **DONE**.
- Stage 7 remains **IN PROGRESS**.

---

## S7-C03 — Correction record

### Defects found

1. **C03-1**: `get_entity` did not check `requested_id == hit.entity_id`
   before hydration. If `SearchService.get_by_id(A)` incorrectly returned
   a hit for B, the handler would hydrate B and return a perfectly valid
   PLAYER B to the caller, bypassing the intended identity chain.

2. **C03-2**: Fail-closed consistency errors revealed internal state:
   - `StorageError` messages included `hit.entity_id`, `doc.entity.id`,
     and `visibility.value` (e.g. `"dm"`, `"system"`).
   - `NotFoundError` for gate-None included the requested entity ID.
   These disclosures could leak hidden campaign state to a model caller.

3. **C03-3**: `register_entity_read_tools` used `registry: object` with a
   `hasattr(registry, "register")` duck-type check, providing no static
   type safety and accepting any object with a `register` method.

4. **C03-5**: Stage-7 documentation had a duplicated S7-C02 record and
   contradictory status text (`"S7-01 is DONE"` followed by
   `"S7-01 remains NOT STARTED"`). No real S7-01 implementation record
   existed.

### Root cause

S7-01 was implemented without a formal identity-chain review. The
requested-ID vs SearchHit-ID check was not part of the original design.
Error messages were written for developer debugging rather than
model-facing safety. Registration typing used weak duck-typing inherited
from earlier prototype conventions. Documentation was not reviewed after
the S7-01 merge.

### Test decomposition

The C03 test surface is split into three focused modules:

- `test_entity_read_tool_contracts.py` — DTO / registration contracts
- `test_entity_read_tools.py` — handler / executor / mutation-safety behavior
- `test_entity_read_tool_safety.py` — identity-chain and non-disclosing safety regressions

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/entity_reads.py` | **EDITED** — added requested-ID vs SearchHit-ID check; hydrate via `requested_id`; non-disclosing error messages; `ToolRegistry` type + `isinstance` check |
| `tests/unit/test_entity_read_tool_contracts.py` | **NEW** — DTO validation, registration metadata, registration API contracts |
| `tests/unit/test_entity_read_tools.py` | **EDITED** — removed DTO/registration tests (moved to contracts file); added C03 regression tests for identity chain and non-disclosing errors |
| `tests/unit/test_entity_read_tool_safety.py` | **NEW** — identity-chain and non-disclosing safety regressions |
| `tests/contract/test_boundaries.py` | **UPDATED** — added entity_reads import-boundary tests (no models/CLI/Ollama/application) |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — removed duplicate C02 record; corrected S7-01 status; added real S7-01 record; added this correction record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-C03 DONE |

### Corrected safety contracts

- **Identity chain**: `requested_id == hit.entity_id` is checked before
  hydration. Repository hydration uses the original validated
  `requested_id`, not an independently trusted value from SearchHit.
- **Non-disclosing errors**: All consistency failures raise `StorageError`
  with generic messages (`"Entity read consistency check failed"`,
  `"Entity search hydration consistency check failed"`). No hidden entity
  ID, visibility value, or filesystem detail is exposed.
- **Registration typing**: `register_entity_read_tools` accepts
  `registry: ToolRegistry` with `isinstance(registry, ToolRegistry)`
  validation.

### Regression tests added

- `test_requested_a_hit_b_raises_storage_error`
- `test_requested_a_hit_b_repository_not_called`
- `test_requested_a_hit_b_error_does_not_reveal_b`
- `test_requested_a_hit_a_hydrated_b_raises_storage_error`
- `test_requested_a_hit_a_hydrated_b_error_does_not_reveal_b`
- `test_requested_a_hit_a_hydrated_dm_system_raises_storage_error`
- `test_hydrated_dm_error_does_not_reveal_visibility`
- `test_requested_a_hit_a_player_a_returns_success`
- `test_gate_none_repository_not_called`
- `test_search_hit_id_hydrated_different_id_raises_storage_error`
- `test_search_hit_id_hydrated_different_id_error_non_disclosing`
- `test_search_hit_hydrated_dm_raises_storage_error`
- `test_search_hit_hydrated_dm_error_non_disclosing`
- `test_search_hydrated_player_success`
- `test_search_fail_closed_error_does_not_leak_details`
- `test_search_fail_closed_on_id_mismatch_does_not_leak_ids`

### Quality-gate evidence

- All entity-read handler tests pass.
- All entity-read contract tests pass.
- All boundary tests pass (including 7 new entity_reads boundary tests).
- Maintainability tests pass (test-module decomposition within limits).
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Commit

- SHA: (reported in Final Report)
- Message: `fix: harden entity read tools (S7-C03)`

### Stage status

- Stage 7 remains **IN PROGRESS**.
- S7-02 remains **NOT STARTED**.

---

## S7-C04 — Correction record

### Scope

Documentation and boundary-contract correction pass. No production behavior changed.

### Defects found

1. **C04-1**: S7-C03 was missing from the canonical Stage-7 task map.
2. **C04-2**: Positive-import boundary tests (`test_entity_reads_imports_domain`,
   `test_entity_reads_imports_retrieval`, `test_entity_reads_imports_storage`)
   encoded incidental runtime import structure rather than dependency-boundary
   contracts.
3. **C04-3**: S7-C03 `Files changed` inventory omitted
   `tests/unit/test_entity_read_tool_safety.py`.

### Changes

| File | Change |
|---|---|
| `tests/contract/test_boundaries.py` | **EDITED** — removed positive-import assertions for `entity_reads` (domain, retrieval, storage); preserved negative contracts (models, CLI, application, Ollama) |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — restored S7-C03 to task map; added S7-C04 to task map; added C03 test decomposition section; corrected C03 file inventory; appended this correction record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — added S7-C04 DONE |

### Corrected contracts

- **Boundary tests assert only prohibited dependencies**: `entity_reads` must not
  import `models`, `cli`, `application`, or `ollama`. Downward imports to
  `domain`, `retrieval`, and `storage` are allowed but not required — no positive
  assertion locks in incidental transitive import structure.
- **Task map completeness**: S7-C03 and S7-C04 appear exactly once in the
  canonical Stage-7 task map.

### Quality-gate evidence

- All boundary tests pass.
- All maintainability tests pass.
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Commit

- SHA: (reported in Final Report)
- Message: `test: finalize entity read boundaries (S7-C04)`

### Stage status

- Stage 7 remains **IN PROGRESS**.
- S7-01 remains **DONE**.
- S7-C03 remains **DONE**.
- S7-02 is **DONE**.
- Stage 8 remains **NOT STARTED**.

---

## S7-02 — Session read tools

### Scope

Implement four provider-neutral session read tools that expose existing
deterministic Python session read behaviour through the ToolRegistry/
ToolExecutor contracts.

### Exact tool surface

Registered exactly:

```
get_active_session
get_session
list_sessions
list_session_events
```

### Module shape

```
src/dnd_assistant/tools/session_reads.py    — NEW: all four session read tools
```

One cohesive module. No directory hierarchy for four small tools.

### Runtime/repository dependency decisions

| Tool | Dependency | Method |
|---|---|---|
| `get_active_session` | `SessionRuntimeService` | `get_active_session()` |
| `get_session` | `SessionMetadataRepository` | `get_session_metadata()` |
| `list_sessions` | `SessionMetadataRepository` | `list_session_metadata()` |
| `list_session_events` | `SessionEventRepository` | `list_events()` |

### Input/output DTOs

| DTO | Fields | Notes |
|---|---|---|
| `GetActiveSessionInput` | (empty) | `extra="forbid"` |
| `GetActiveSessionOutput` | `session: Session \| None` | `None` = no active session |
| `GetSessionInput` | `session_id: str` | strict string validation |
| `GetSessionOutput` | `session: Session` | canonical Session only |
| `ListSessionsInput` | (empty) | `extra="forbid"` |
| `ListSessionsOutput` | `sessions: list[Session]` | repository order preserved |
| `ListSessionEventsInput` | `session_id: str` | strict string validation |
| `ListSessionEventsOutput` | `events: list[SessionEventResult]` | physical append order |
| `SessionEventResult` | `event_id, real_time: AwareDatetime, world_tick, type, extra_fields` | provider-neutral DTO |

### Session metadata extra_fields deferral

`RawSessionMetadata.extra_fields` is intentionally excluded from
`GetSessionOutput` and `ListSessionsOutput`.  Public model-facing
serialisation for arbitrary session metadata extras is deferred.

### Raw event extra_fields exposure decision

Unlike metadata extras, event `extra_fields` are actual event payload
content and are necessary to preserve notes and event-specific data.
`SessionEventResult.extra_fields` is typed as `dict[str, JsonValue]`.

### Ordering semantics

- `get_session`: deterministic (single ID lookup).
- `list_sessions`: preserves `SessionMetadataRepository` session-ID sorted order.
- `list_session_events`: preserves exact physical append order from
  `SessionEventRepository`.
- `get_active_session`: returns the single active session or `None`.

### Recovery/preflight deferral

Session recovery inspection and repair operations are intentionally NOT
exposed as tools in S7-02.  Recovery preflight belongs to S7-03.

### Registration/composition design

```python
def register_session_read_tools(
    registry: ToolRegistry,
    *,
    runtime_service: SessionRuntimeService,
    session_repository: SessionMetadataRepository,
    event_repository: SessionEventRepository,
) -> None:
```

Uses `isinstance(registry, ToolRegistry)` validation consistent with
corrected entity-read registration.  Dependencies are supplied by
trusted composition code.

### Fail-closed consistency

`get_session` verifies `metadata.session.id == requested_id` after
repository lookup.  A mismatch raises `StorageError` with a generic
non-disclosing message.

### No-mutation guarantee

All four tools are `Permission.READ` with empty `side_effects`.  No
audit context required.  Tests prove that mutation operations
(`start_session`, `end_session`, `allocate_next_session_id`,
`create_session`, `close_session`, `append_event`) are never called.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/session_reads.py` | **NEW** — get_active_session, get_session, list_sessions, list_session_events |
| `tests/unit/test_session_read_tool_contracts.py` | **NEW** — 52 DTO/registration/contract tests |
| `tests/unit/test_session_read_tools.py` | **NEW** — 32 handler/executor/no-mutation tests |
| `tests/contract/test_boundaries.py` | **UPDATED** — added session_reads negative import tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **UPDATED** — added this record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-02 DONE |

### Tests and quality gates

- 52/52 session-read contract tests pass.
- 32/32 session-read behaviour tests pass.
- 68/68 boundary tests pass (including 3 new session_reads tests).
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Explicit non-goals

- Session mutation tools (S7-03).
- World-time tools (S7-04, S7-05).
- Entity mutation tools (S7-06).
- Cross-family integration (S7-07).
- Recovery inspection/repair tools.
- Provider schema adaptation.
- ModelGateway/Ollama integration.
- Fast Agent.
- ChangeSet.
- Post-session processing.
- Global registry bootstrap.

### Completion state

- S7-02 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-03 remains **NOT STARTED**.

---

## S7-C05 — Correction record

### Defects found

1. **C05-1**: `GetActiveSessionOutput.session` typed as `object | None` instead of `Session | None`.
2. **C05-2**: `GetSessionOutput.session` typed as `object` instead of `Session`.
3. **C05-3**: `ListSessionsOutput.sessions` typed as `list[object]` instead of `list[Session]`.
4. **C05-4**: `SessionEventResult.real_time` typed as `object` instead of `AwareDatetime`.
5. **C05-5**: No output-validation regression tests proving arbitrary non-Session values are rejected.
6. **C05-6**: No ToolExecutor regression proving malformed handler output is caught by schema validation.
7. **C05-7**: Missing root `dnd_assistant.tools` / `application` lightweight-import boundary test.

### Root cause

S7-02 was implemented with weak `object`-typed public DTO fields instead of
reusing the canonical `Session` domain model and `AwareDatetime`. The original
implementation deferred typed contracts in favour of opaque field types.

### Corrected contracts

| DTO | Before (S7-02) | After (S7-C05) |
|---|---|---|
| `GetActiveSessionOutput.session` | `object \| None` | `Session \| None` |
| `GetSessionOutput.session` | `object` | `Session` |
| `ListSessionsOutput.sessions` | `list[object]` | `list[Session]` |
| `SessionEventResult.real_time` | `object` | `AwareDatetime` |

The canonical `Session` domain model is imported at runtime (not
`TYPE_CHECKING`) so Pydantic can generate meaningful provider-neutral JSON
schemas. `AwareDatetime` enforces timezone-aware datetime validation; naive
datetimes are rejected. Pydantic's standard coercion of ISO strings and Unix
timestamps to aware datetimes is preserved.

### Regression tests added

- `TestGetActiveSessionOutputValidation.test_string_rejected`
- `TestGetActiveSessionOutputValidation.test_incomplete_dict_rejected`
- `TestGetActiveSessionOutputValidation.test_integer_rejected`
- `TestGetSessionOutputValidation.test_string_rejected`
- `TestGetSessionOutputValidation.test_integer_rejected`
- `TestGetSessionOutputValidation.test_incomplete_dict_rejected`
- `TestListSessionsOutputValidation.test_list_with_string_rejected`
- `TestListSessionsOutputValidation.test_list_with_incomplete_dict_rejected`
- `TestSessionEventResultValidation.test_naive_datetime_rejected`
- `TestSessionEventResultValidation.test_string_real_time_coerces_to_aware`
- `TestSessionEventResultValidation.test_integer_real_time_coerces_to_aware`
- `TestSessionEventResultValidation.test_aware_datetime_accepted`
- `TestToolExecutorIntegration.test_faulty_handler_non_session_output_rejected`
- `test_tools_package_does_not_import_application` (boundary)

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/session_reads.py` | **EDITED** — replaced `object` field types with `Session` / `AwareDatetime`; added runtime imports |
| `tests/unit/test_session_read_tool_contracts.py` | **EDITED** — added 12 output-validation regression tests |
| `tests/unit/test_session_read_tools.py` | **EDITED** — added ToolExecutor faulty-output regression test |
| `tests/contract/test_boundaries.py` | **EDITED** — added `test_tools_package_does_not_import_application` |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — corrected S7-02 DTO table; added this correction record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — added S7-C05 DONE |

### Quality-gate evidence

- 64/64 session-read contract tests pass (was 52).
- 33/33 session-read behaviour tests pass (was 32).
- 69/69 boundary tests pass (was 68).
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — no formatting issues.
- `git diff --check` — no whitespace errors.

### Commit

- SHA: (reported in Final Report)
- Message: `fix: strengthen session read schemas (S7-C05)`

### Stage status

- S7-02 remains **DONE**.
- S7-C05 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-03 is **DONE**.
- Stage 8 remains **NOT STARTED**.

---

## S7-03 — Session mutation tools

### Scope

Implement four provider-neutral session mutation tools that expose existing
deterministic Python session mutation behaviour through the ToolRegistry/
ToolExecutor contracts.  Every mutation performs a read-only recovery
preflight before delegating to `SessionRuntimeService`.

### Exact tool surface

Registered exactly:

```
start_session
record_event
record_note
end_session
```

### Module shape

```
src/dnd_assistant/tools/session_mutations.py    — NEW: all four session mutation tools
```

One cohesive module. No directory hierarchy for four tools.

### Permission and side-effect metadata

All four tools are WRITE tools:

```python
permission = Permission.WRITE
side_effects = frozenset({SideEffect.SESSION_MUTATION})
```

### Session-mode contracts

| Tool | Allowed mode |
|---|---|
| `start_session` | `NO_ACTIVE_SESSION` only |
| `record_event` | `ACTIVE_SESSION` only |
| `record_note` | `ACTIVE_SESSION` only |
| `end_session` | `ACTIVE_SESSION` only |

### Recovery preflight

Every mutation handler calls `SessionRecoveryService.inspect_runtime()` after
ToolExecutor validation and immediately before the runtime mutation.

If `report.has_issues` is True, a generic `ConflictError` is raised:

```
Session runtime requires explicit recovery before mutation
```

The error does not expose filesystem paths, raw recovery detail text,
operation IDs, alternate/corrupt session IDs, or audit hashes.

Recovery repair methods (`repair_audit_tail`, `cleanup_partial_start`,
`repair_event_tail`) are never called from S7-03 tools.

### Preflight ordering

```
invalid input            → no recovery inspection → no runtime mutation
READ permission          → no recovery inspection → no runtime mutation
wrong SessionMode        → no recovery inspection → no runtime mutation
missing AuditContext     → no recovery inspection → no runtime mutation
valid WRITE invocation   → recovery inspection → runtime mutation
recovery issues present  → recovery inspection → runtime mutation zero times
```

### AuditContext ownership

`AuditContext` comes from `context.audit` (the trusted `ExecutionContext`).
Tools never generate `operation_id`, call `datetime.now()`, change `real_time`,
`source`, `session`, `model_profile`, or `prompt_version`.

The exact same `AuditContext` object is passed to `SessionRuntimeService`.

### Input/output DTOs

| DTO | Fields | Notes |
|---|---|---|
| `StartSessionInput` | (empty) | `extra="forbid"` |
| `StartSessionOutput` | `session: Session` | Canonical Session |
| `RecordEventInput` | `event_type: str`, `extra_fields: dict[str, JsonValue] \| None` | Strict string validation, `extra="forbid"` |
| `RecordEventOutput` | `event: SessionEventResult` | Reuses S7-02 DTO |
| `RecordNoteInput` | `text: str` | Strict string validation, `extra="forbid"` |
| `RecordNoteOutput` | `event: SessionEventResult` | Reuses S7-02 DTO |
| `EndSessionInput` | `touched_entity_ids: list[EntityId]` | Default `[]`, `extra="forbid"` |
| `EndSessionOutput` | `session: Session` | Canonical Session |

### Runtime delegation

All mutation behaviour delegates to `SessionRuntimeService`:

| Tool | Runtime method |
|---|---|
| `start_session` | `runtime_service.start_session(audit=context.audit)` |
| `record_event` | `runtime_service.record_event(event_type, extra_fields=..., audit=...)` |
| `record_note` | `runtime_service.record_note(text, audit=...)` |
| `end_session` | `runtime_service.end_session(touched_entity_ids=..., audit=...)` |

No direct repository calls. No direct filesystem access. No direct audit writes.
No world_tick calculation. No session-ID allocation. No revision calculation.

### Event DTO reuse

`RecordEventOutput` and `RecordNoteOutput` reuse `SessionEventResult` from
`session_reads.py`.  The raw `RawSessionEvent` returned by the runtime is
converted to `SessionEventResult` preserving `event_id`, `real_time`,
`world_tick`, `type`, and `extra_fields` by value.

### No world-time logic in tools

S7-03 tools never accept or calculate `world_tick`, `world_tick_start`,
or `world_tick_end`.  `SessionRuntimeService` reads the canonical persisted
world time from `WorldTimeRepository`.

### Registration API

```python
def register_session_mutation_tools(
    registry: ToolRegistry,
    *,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
) -> None:
```

Uses `isinstance(registry, ToolRegistry)` validation consistent with
existing entity-read and session-read registration.

### No lower-layer duplication

`session_mutations.py` does not directly call:
- `SessionMetadataRepository.create_session`
- `SessionMetadataRepository.close_session`
- `SessionEventRepository.append_event`
- `WorldTimeRepository.get_current_world_time`
- `AuditService.append`

Those belong behind `SessionRuntimeService`.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/session_mutations.py` | **NEW** — start_session, record_event, record_note, end_session |
| `tests/unit/test_session_mutation_tool_contracts.py` | **NEW** — 71 DTO/registration/contract tests |
| `tests/unit/test_session_mutation_tools.py` | **NEW** — 32 handler/executor/delegation tests |
| `tests/unit/test_session_mutation_tool_safety.py` | **NEW** — 21 permission/mode/audit/recovery safety tests |
| `tests/contract/test_boundaries.py` | **UPDATED** — added 4 session_mutations negative import tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **UPDATED** — added this record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-03 DONE |

### Tests and quality gates

- 71/71 session-mutation contract tests pass.
- 32/32 session-mutation behaviour tests pass.
- 21/21 session-mutation safety tests pass.
- 73/73 boundary tests pass (was 69, +4 new session_mutations tests).
- Full `uv run pytest`: 3266 passed, 95 skipped, 0 failed, 0 errors.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Explicit non-goals

- World-time read tools (S7-04).
- World-time mutation tools (S7-05).
- Entity mutation tools (S7-06).
- Cross-family integration (S7-07).
- Recovery mutation/repair tools.
- Provider schema adaptation.
- ModelGateway/Ollama integration.
- Fast Agent.
- ChangeSet.
- Post-session processing.
- Global registry bootstrap.

### Completion state

- S7-03 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-04 remains **NOT STARTED**.
- Stage 8 remains **NOT STARTED**.