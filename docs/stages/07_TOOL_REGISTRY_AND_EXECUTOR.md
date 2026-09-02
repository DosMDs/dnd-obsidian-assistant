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
| S7-03 | DONE | Session mutation tools |
| S7-04 | DONE | World-time read + deterministic calendar read surface |
| S7-05 | DONE | World-time mutation tools |
| S7-C06 | DONE | Restore S7-05 maintainability ratchet |
| S7-C07 | DONE | Correct S7-C06 verification documentation |
| S7-C08 | DONE | Correct separated maintainability gate count |
| S7-06 | DONE | Safe entity mutation tools |
| S7-07 | DONE | Cross-family integration / public registry schema / Golden-Vault hardening |
| S7-C09 | DONE | Correct S7-07 catalog type safety and verification baseline |
| S7-C10 | DONE | Enforce strict ToolRegistry identity and isolate boundary imports |
| S7-C11 | DONE | Localize sys.modules test isolation and correct S7-C10 history |
| S7-C12 | DONE | Deduplicate import isolation and restore maintainability ratchet |
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
- S7-04 is **DONE**.
- Stage 8 remains **NOT STARTED**.

---

## S7-04 — World-time read and deterministic calendar read tools

### Scope

Implement four provider-neutral world-time read tools that expose the
accepted persisted current-world-time read contract and deterministic
CalendarService read surface through the ToolRegistry/ToolExecutor
contracts.

### Module shape

```
src/dnd_assistant/tools/world_time_reads.py    — NEW: all four world-time read tools
```

### Exact tool surface

Registered exactly:

```
get_world_time
world_tick_to_date
game_date_to_world_tick
time_between_world_ticks
```

### WorldTimeRepository vs CalendarService ownership boundary

- Persisted current time belongs only to `WorldTimeRepository`.
- Calendar/date arithmetic belongs only to `CalendarService`.
- `GameDate` is always derived from canonical `WorldTick`.

### CurrentWorldTime as sole persisted current-time state

`get_world_time` reads `WorldTimeRepository.get_current_world_time()` and
derives `GameDate` through `CalendarService.tick_to_date()`.  No fallback
to tick zero.  `NotFoundError` from uninitialized world time propagates
unchanged.

### Derived GameDate semantics

`GameDate` is derived at read time and returned in the output.  It is not
persisted by these tools.  No second date authority exists.

### calendar_id exposure decision

Every conversion output includes `calendar_service.definition.calendar_id`
so a future model/agent can distinguish which configured calendar produced
a date conversion without receiving the entire `CalendarDefinition`.

### Input/output DTOs

| DTO | Fields | Notes |
|---|---|---|
| `GetWorldTimeInput` | (empty) | `extra="forbid"` |
| `GetWorldTimeOutput` | `world_time: CurrentWorldTime`, `game_date: GameDate`, `calendar_id: str` | Canonical persisted state + derived date + calendar identity |
| `WorldTickToDateInput` | `world_tick: WorldTick` | Strict WorldTick validation |
| `WorldTickToDateOutput` | `game_date: GameDate`, `calendar_id: str` | Pure conversion |
| `GameDateToWorldTickInput` | `game_date: GameDate` | Canonical GameDate |
| `GameDateToWorldTickOutput` | `world_tick: WorldTick`, `calendar_id: str` | Pure reverse conversion |
| `TimeBetweenWorldTicksInput` | `start_tick: WorldTick`, `end_tick: WorldTick` | Two strict WorldTick values |
| `TimeBetweenWorldTicksOutput` | `minutes: int` (strict) | Signed minute difference |

### Definition-dependent date validation conversion

`game_date_to_world_tick` translates `CalendarService.date_to_tick()`
`ValueError` (definition-dependent invalid dates) to project
`ValidationError`.  Unexpected non-`ValueError` exceptions propagate
unchanged.

### Read-only metadata

All four tools:

```python
permission = Permission.READ
side_effects = frozenset()
allowed_session_modes = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
```

No `AuditContext` required.

### Registration/composition design

```python
def register_world_time_read_tools(
    registry: ToolRegistry,
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> None:
```

Uses `isinstance(registry, ToolRegistry)` validation consistent with
existing tool registration APIs.  Dependencies are supplied by trusted
composition code.

### Pure calendar tools performing zero repository access

`world_tick_to_date`, `game_date_to_world_tick`, and
`time_between_world_ticks` operate only on supplied values through
`CalendarService`.  Tests prove `WorldTimeRepository` methods are never
called.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/world_time_reads.py` | **NEW** — get_world_time, world_tick_to_date, game_date_to_world_tick, time_between_world_ticks |
| `tests/unit/test_world_time_read_tool_contracts.py` | **NEW** — 53 DTO/registration/contract tests |
| `tests/unit/test_world_time_read_tools.py` | **NEW** — 28 handler/executor/round-trip tests |
| `tests/contract/test_boundaries.py` | **UPDATED** — added 5 world_time_reads negative import tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **UPDATED** — added this record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-04 DONE |

### Tests and quality gates

- 53/53 world-time read contract tests pass.
- 28/28 world-time read behaviour tests pass.
- 78/78 boundary tests pass (was 73, +5 new world_time_reads tests).
- Full `uv run pytest`: 3357 passed, 95 skipped, 0 failed, 0 errors.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Explicit non-goals

- World-time mutation tools (S7-05).
- Entity mutation tools (S7-06).
- Cross-family integration (S7-07).
- Timeline-event scheduling tools.
- Provider schema adaptation.
- ModelGateway/Ollama integration.
- Fast Agent.
- ChangeSet.
- Post-session processing.
- Global registry bootstrap.

### Completion state

- S7-04 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-05 is **DONE**.
- Stage 8 remains **NOT STARTED**.

---

## S7-05 — World-time mutation tools

### Scope

Implement two provider-neutral world-time mutation tools that expose the
accepted canonical current-world-time mutation capabilities through the
ToolRegistry/ToolExecutor contracts.  Thin adapters over
`WorldTimeRepository` and `CalendarService`.

### Module shape

```
src/dnd_assistant/tools/world_time_mutations.py    — NEW: set_world_time and advance_world_time
```

### Exact tool surface

Registered exactly:

```
set_world_time
advance_world_time
```

### Permission and side-effect metadata

Both tools:

```python
permission = Permission.WRITE
side_effects = frozenset({SideEffect.WORLD_TIME_MUTATION})
allowed_session_modes = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
```

World-time progression is valid both outside and during an active session.
No session-event side effect is emitted.

### AuditContext ownership

`AuditContext` comes only from `ExecutionContext.audit`.  Tools never
generate `operation_id`, call `datetime.now()`, or rebuild `AuditContext`.
The exact same `context.audit` object is passed to the repository.

### set_world_time — two-mode state machine

`expected_revision=None` — initialize only:
- calls `initialize_current_world_time()`
- existing state => `ConflictError`
- never overwrites

`expected_revision=N` — optimistic update:
- calls `set_current_world_time()`
- missing state => `NotFoundError`
- stale revision => `ConflictError`

The caller explicitly declares the expected state.  No read-first branch in
the Tool Layer.

### set_world_time input/output

| DTO | Fields | Notes |
|---|---|---|
| `SetWorldTimeInput` | `world_tick: WorldTick`, `expected_revision: Revision \| None = None` | `None` = initialize; supplied revision = update |
| `SetWorldTimeOutput` | `world_time: CurrentWorldTime`, `game_date: GameDate`, `calendar_id: str` | Persisted state + derived date + calendar identity |

No `GameDate` in input.  No `calendar_id` in input.  No `session_id` in
input.  No `audit` metadata in input.

### advance_world_time — canonical flow

```
1. read persisted CurrentWorldTime (get_current_world_time)
2. calculate candidate WorldTick (CalendarService.advance_world_time)
3. persist through repository (set_current_world_time with caller-supplied expected_revision)
4. derive GameDate from persisted result (CalendarService.tick_to_date)
5. return typed result
```

### advance_world_time input/output

| DTO | Fields | Notes |
|---|---|---|
| `AdvanceWorldTimeInput` | `minutes: int`, `expected_revision: Revision` | Signed minutes; mandatory revision |
| `AdvanceWorldTimeOutput` | `world_time: CurrentWorldTime`, `game_date: GameDate`, `calendar_id: str` | Persisted state + derived date |

`expected_revision` is mandatory — the caller must advance from a revision
it has actually observed.  The tool never substitutes `current.revision`.

### CalendarService arithmetic ownership

`advance_world_time` handler delegates to `CalendarService.advance_world_time()`.
The result is `current_tick + minutes` (via CalendarService), not a
tool-layer calculation.  A distinctive fake offset (+42) in tests proves
the CalendarService result is used.

### Signed-minute behavior

Negative, zero, and positive `minutes` values are all accepted.  No
monotonicity policy is imposed by the Tool Layer.

### No implicit initialization

`advance_world_time` never initializes missing state.  `NotFoundError` from
`get_current_world_time()` propagates unchanged.

### No retry on ConflictError

Stale revision causes `ConflictError` to propagate.  No automatic retry,
no re-read, no silent re-application of the same relative advancement.

### CalendarService ValueError translation

`ValueError` from `CalendarService.advance_world_time()` is translated to
project `ValidationError`.  Unexpected exceptions (`RuntimeError`, etc.)
propagate unchanged.

### Registration API

```python
def register_world_time_mutation_tools(
    registry: ToolRegistry,
    *,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> None:
```

Uses `isinstance(registry, ToolRegistry)` validation.  Dependencies are
supplied by trusted composition code.

### No lower-layer duplication

`world_time_mutations.py` does not directly:
- write `world_time.json`
- calculate revision increments
- write `audit.jsonl`
- calculate elapsed-time arithmetic independently
- create an in-memory authoritative clock
- access filesystem, JSON, or `AuditService`

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/world_time_mutations.py` | **NEW** — set_world_time, advance_world_time |
| `tests/unit/test_world_time_mutation_tool_contracts.py` | **NEW** — DTO/registration/contract tests |
| `tests/unit/test_world_time_mutation_tools.py` | **NEW** — handler/executor/integration tests |
| `tests/contract/test_boundaries.py` | **UPDATED** — added 5 world_time_mutations negative import tests |
| `tests/contract/test_maintainability.py` | **UPDATED** — temporarily added new-file legacy exception for `test_world_time_mutation_tools.py` (subsequently corrected by S7-C06) |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **UPDATED** — added this record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-05 DONE |

### Tests and quality gates

- All world-time mutation contract tests pass.
- All world-time mutation behaviour tests pass.
- All boundary tests pass (including 5 new world_time_mutations tests).
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Explicit non-goals

- Timeline event scheduling tools.
- Entity mutation tools (S7-06).
- Cross-family integration (S7-07).
- Recovery tooling.
- Provider schema adaptation.
- ModelGateway/Ollama integration.
- Fast Agent.
- ChangeSet.
- Post-session processing.
- Global registry bootstrap.

### Completion state

- S7-05 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-06 remains **NOT STARTED**.
- Stage 8 remains **NOT STARTED**.

---

## S7-C06 — Restore S7-05 maintainability ratchet

### Independent-review defect

S7-05 introduced a new test module (`test_world_time_mutation_tools.py`) with
1377 physical lines — exceeding the repository's 1000-line test-module hard
limit.  The same commit then added this file to `TEST_LEGACY_EXCEPTIONS` in
`test_maintainability.py`, incorrectly classifying a newly created file as a
legacy oversized exception.

### Correction

1. **Removed invalid legacy exception**: Deleted `"unit/test_world_time_mutation_tools.py": 1377` from `TEST_LEGACY_EXCEPTIONS`.
2. **Decomposed oversized test module**: Split `test_world_time_mutation_tools.py` (1377 lines) into three cohesive topical modules, each well under the 1000-line hard limit.
3. **No production changes**: `src/dnd_assistant/tools/world_time_mutations.py` is unchanged.
4. **No maintainability-policy weakening**: `TEST_HARD_LIMIT` remains 1000. No new legacy exception added. Pre-existing legacy exceptions otherwise unchanged.

### Final decomposition

| File | Lines | Content |
|---|---|---|
| `tests/unit/test_world_time_mutation_tool_contracts.py` | 428 | DTO validation, registration metadata, registration API |
| `tests/unit/test_world_time_mutation_tools.py` | 998 | Handler behaviour: initialize, update, advance, signed minutes, concurrency, calendar validation |
| `tests/unit/test_world_time_mutation_tool_safety.py` | 477 | Permission gating, audit gating, invalid-input-before-handler, session modes, no implicit initialization |
| `tests/unit/test_world_time_mutation_integration.py` | 89 | Real ObsidianWorldTimeRepository + ToolExecutor end-to-end |

All four files are at or below the `TEST_HARD_LIMIT` of 1000 lines.

### Preserved S7-05 coverage

All original S7-05 behavioural regressions are preserved:

- `set_world_time` expected_revision=None → initialize only
- `set_world_time` expected_revision=N → update only
- No read-before-branch in set_world_time
- `advance_world_time`: get current → CalendarService.advance → repository set
- Caller expected_revision forwarded unchanged (never substituted with current.revision)
- Negative / zero / positive minutes accepted
- Same AuditContext object forwarded
- READ permission rejected before handler
- Missing audit rejected before handler
- Invalid input rejected before handler
- Both session modes accepted
- Repository NotFoundError / ConflictError / StorageError propagation
- CalendarService ValueError → project ValidationError
- RuntimeError propagates unchanged
- No direct filesystem/audit/JSON mutation
- No session event
- No recovery inspection
- Real repository/tool integration

### Documentation correction

The S7-05 `Files changed` inventory now includes `tests/contract/test_maintainability.py`
with an accurate description of the temporary invalid legacy exception that was
subsequently corrected by S7-C06.

### Files changed (S7-C06)

| File | Change |
|---|---|
| `tests/unit/test_world_time_mutation_tools.py` | **EDITED** — removed safety tests and integration test (moved to split files); reduced from 1377 to 998 lines |
| `tests/unit/test_world_time_mutation_tool_safety.py` | **NEW** — safety/permission/audit/invalid-input tests (477 lines) |
| `tests/unit/test_world_time_mutation_integration.py` | **NEW** — real repository integration test (89 lines) |
| `tests/contract/test_maintainability.py` | **EDITED** — removed invalid `test_world_time_mutation_tools.py` legacy exception |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — corrected S7-05 file inventory; added this correction record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — S7-C06 DONE |

### Quality-gate evidence

- 48/48 world-time mutation contract tests pass.
- 30/30 world-time mutation behaviour tests pass.
- 10/10 world-time mutation safety tests pass.
- 2/2 world-time mutation integration tests pass.
- Maintainability: 259/259
- Boundary: 83/83
- 155/155 S7-04 read + core Tool Layer regression tests pass.
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Final maintainability state

- All newly created S7-05/C06 test modules ≤ `TEST_HARD_LIMIT` (1000).
- `TEST_HARD_LIMIT` unchanged.
- No new legacy exception added.
- Pre-existing legacy exceptions otherwise unchanged.
- `"unit/test_world_time_mutation_tools.py"` absent from `TEST_LEGACY_EXCEPTIONS`.

### Stage status

- S7-05 remains **DONE**.
- S7-C06 is **DONE**.
- S7-06 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.

---

## S7-C07 — Correct S7-C06 verification documentation

### Defect

S7-C06 successfully restored the maintainability ratchet, but its canonical
documentation contained stale physical line counts:
- `test_world_time_mutation_tool_safety.py`: documented as 432 lines, actual 477 lines.
- `test_world_time_mutation_integration.py`: documented as 87 lines, actual 89 lines.
- Quality-gate evidence combined maintainability and boundary into a single
  misleading count (342 = 259 + 83) instead of reporting separate results.
  The aggregated count 342 was incorrectly retained as the maintainability-only
  count.

### Correction

- Corrected S7-C06 Final decomposition table to actual physical line counts.
- Corrected S7-C06 Files-changed descriptions to actual physical line counts.
- Separated quality-gate evidence into distinct maintainability and boundary results.
- Verified maintainability ratchet itself was already correct and was not changed.
- No production or test files were modified.

### Actual verified four-file line counts

| File | Lines |
|---|---|
| `tests/unit/test_world_time_mutation_tool_contracts.py` | 428 |
| `tests/unit/test_world_time_mutation_tools.py` | 998 |
| `tests/unit/test_world_time_mutation_tool_safety.py` | 477 |
| `tests/unit/test_world_time_mutation_integration.py` | 89 |

### Quality-gate evidence

- Maintainability: 259/259
- Boundary: 83/83
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Commit

- SHA: (reported in Final Report)
- Message: `docs: correct S7-C06 verification record (S7-C07)`

### Stage status

- S7-C06 remains **DONE**.
- S7-C07 is **DONE**.
- S7-06 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.

---

## S7-C08 — Correct separated maintainability gate count

### Defect

S7-C07 successfully separated maintainability and boundary reporting, but the
old aggregate count 342 (259 + 83) was incorrectly retained as the
maintainability-only count in both the S7-C06 and S7-C07 quality-gate evidence
sections.

### Correction

- Re-ran maintainability suite independently: 259/259.
- Re-ran boundary suite independently: 83/83.
- Corrected S7-C06 quality-gate evidence: `Maintainability: 259/259`, `Boundary: 83/83`.
- Corrected S7-C07 quality-gate evidence: `Maintainability: 259/259`, `Boundary: 83/83`.
- Updated S7-C07 defect narrative to clarify that 342 was the old aggregate
  (259 + 83) and was not a valid maintainability-only count.
- Line-count corrections from S7-C07 remain unchanged: 428/998/477/89.
- Maintainability policy unchanged (`TEST_HARD_LIMIT` = 1000).
- No production or test files modified.

### Quality-gate evidence

- Maintainability: 259/259
- Boundary: 83/83
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Stage status

- S7-C06 remains **DONE**.
- S7-C07 remains **DONE**.
- S7-C08 is **DONE**.
- S7-06 is **DONE**.
- S7-07 remains **NOT STARTED**.
- S7-08 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.

---

## S7-06 — Safe entity mutation tools

### Scope

Implement two concrete entity mutation tools (`patch_entity` and
`append_entity_fact`) that expose already accepted entity mutation
capabilities through the ToolRegistry/ToolExecutor contracts.

### Module shape

```
src/dnd_assistant/tools/
    entity_mutations.py    — NEW: patch_entity and append_entity_fact tools
```

### Exact two-tool surface

Registered exactly:

```
patch_entity
append_entity_fact
```

`create_entity` is NOT implemented.

### Stable-ID-only write policy

Both tools accept only a stable `EntityId` as the mutation target.
No free-text reference, name, alias, or search query is accepted.

No `EntityResolver.resolve()` call exists in these tools.

### SearchService player-visibility authorization

Every mutation handler calls `SearchService.get_by_id(input_model.entity_id)`
before any repository mutation.

- `None` → generic `NotFoundError` ("Entity not found or not accessible").
- Mismatched `hit.entity_id != requested_id` → `StorageError` (fail-closed).

Hidden (DM, SYSTEM) and missing entities all produce the same generic
`NotFoundError`. No visibility value or alternate entity ID is disclosed.

### Generic hidden-vs-missing NotFound behavior

`SearchService.get_by_id()` returns `None` for:
- missing entities;
- `Visibility.DM` entities;
- `Visibility.SYSTEM` entities.

All three cases produce the same generic `NotFoundError`.

### EntityResolver not used

No `EntityResolver` import or call exists in `entity_mutations.py`.

### Module/registration shape

```python
def register_entity_mutation_tools(
    registry: ToolRegistry,
    *,
    search_service: SearchService,
    repository: VaultRepository,
) -> None:
```

Uses `isinstance(registry, ToolRegistry)` validation consistent with
existing tool registration APIs.

### WRITE/ENTITY_MUTATION metadata

Both tools:

```python
permission = Permission.WRITE
side_effects = frozenset({SideEffect.ENTITY_MUTATION})
allowed_session_modes = frozenset({SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION})
```

### Both-session-mode decision

Entity mutation is valid both outside and during an active session.
No session-event side effect is emitted.

### AuditContext ownership

`AuditContext` comes only from `ExecutionContext.audit`. Tools never
generate `operation_id`, call `datetime.now()`, or rebuild `AuditContext`.
The exact same `context.audit` object is passed to the repository.

### PatchEntityInput using canonical EntityPatch

```python
class PatchEntityInput(BaseModel):
    entity_id: EntityId
    expected_revision: Revision
    patch: EntityPatch
```

Uses the existing canonical `EntityPatch` which owns:
- editable-field whitelist;
- omitted-vs-explicit-None semantics;
- non-nullable field checks;
- empty-patch rejection;
- field validation.

### AppendEntityFactInput validation

```python
class AppendEntityFactInput(BaseModel):
    entity_id: EntityId
    expected_revision: Revision
    fact: str
```

The `fact` field is validated at the Tool Layer:
- must be a string;
- non-empty;
- no leading/trailing whitespace;
- printable Unicode (no newlines/control characters).

### Caller-supplied expected_revision

Both tools require `expected_revision` as a mandatory field. The value
is forwarded unchanged to the repository. No read-current-revision
substitution occurs.

### Repository ownership

The repository owns:
- revision increment (exactly +1);
- `updated_at` (set to `audit.real_time`);
- Markdown body preservation for patches;
- Markdown bullet rendering for append;
- atomic writes;
- audit logging (intent/committed).

### Output contracts

```python
class PatchEntityOutput(BaseModel):
    entity: Entity
    body: str


class AppendEntityFactOutput(BaseModel):
    entity: Entity
    body: str
```

Both expose canonical `Entity` + Markdown `body`. No `extra_frontmatter`,
filesystem path, or raw YAML is exposed.

### Returned-ID fail-closed check

After mutation, the handler verifies `document.entity.id == requested_id`.
A mismatch raises `StorageError` with a generic message.

### No automatic session coupling

Entity writes do NOT automatically:
- record a session event;
- record a session note;
- modify `touched_entity_ids`;
- invoke `SessionRuntimeService`;
- invoke `SessionRecoveryService`;
- advance world time.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/entity_mutations.py` | **NEW** — patch_entity, append_entity_fact |
| `tests/unit/test_entity_mutation_tool_contracts.py` | **NEW** — DTO/registration/contract tests |
| `tests/unit/test_entity_mutation_tools.py` | **NEW** — handler/executor/delegation tests |
| `tests/unit/test_entity_mutation_tool_safety.py` | **NEW** — authorization/safety/gating tests |
| `tests/contract/test_boundaries.py` | **UPDATED** — added 4 entity_mutations negative import tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **UPDATED** — added this record |
| `DEVELOPMENT_STATUS.md` | **UPDATED** — S7-06 DONE |

### Tests and quality gates

- All entity mutation contract tests pass.
- All entity mutation behaviour tests pass.
- All entity mutation safety tests pass.
- All boundary tests pass (including 4 new entity_mutations tests).
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Explicit non-goals

- `create_entity` tool.
- `delete_entity` tool.
- `rename_entity` tool.
- `update_quest_status` convenience wrapper.
- `add_relation` tool.
- EntityResolver-based fuzzy write.
- Automatic clarification loop.
- Session event coupling.
- Session touched-entity mutation.
- World-time changes.
- ModelGateway/Ollama integration.
- Fast Agent.
- ChangeSet.
- Post-session processing.
- Global registry bootstrap.
- Cross-family integration (S7-07).

### Completion state

- S7-06 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-07 remains **NOT STARTED**.
- Stage 8 remains **NOT STARTED**.

---

## S7-07 — Cross-family integration, public registry schema, and Golden-Vault hardening

### Scope

Complete Stage-7 implementation by providing:

1. One trusted composition point for the complete accepted MVP Tool Registry.
2. One provider-neutral, JSON-serializable public registry/catalog schema.
3. Cross-family integration against a writable copy of the canonical Golden Vault.

No new domain capabilities, tool families, or provider adapters were added.

### Exact 18-tool MVP surface

**10 READ / 8 WRITE:**

| Family | Tools |
|---|---|
| Entity reads (READ) | `search_entities`, `get_entity` |
| Entity mutations (WRITE) | `patch_entity`, `append_entity_fact` |
| Session reads (READ) | `get_active_session`, `get_session`, `list_sessions`, `list_session_events` |
| Session mutations (WRITE) | `start_session`, `record_event`, `record_note`, `end_session` |
| World-time reads (READ) | `get_world_time`, `world_tick_to_date`, `game_date_to_world_tick`, `time_between_world_ticks` |
| World-time mutations (WRITE) | `set_world_time`, `advance_world_time` |

**Side-effect counts:** ENTITY_MUTATION=2, SESSION_MUTATION=4, WORLD_TIME_MUTATION=2

### Six family registration sources

Composition delegates to the six accepted family registration functions:

- `register_entity_read_tools`
- `register_entity_mutation_tools`
- `register_session_read_tools`
- `register_session_mutation_tools`
- `register_world_time_read_tools`
- `register_world_time_mutation_tools`

### Module shape

```
src/dnd_assistant/tools/
    catalog.py        — NEW: public provider-neutral registry schema
    mvp_registry.py   — NEW: MVP tool registry composition
```

### build_mvp_tool_registry composition API

```python
def build_mvp_tool_registry(
    *,
    search_service: SearchService,
    repository: VaultRepository,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
    session_repository: SessionMetadataRepository,
    event_repository: SessionEventRepository,
    world_time_repository: WorldTimeRepository,
    calendar_service: CalendarService,
) -> ToolRegistry:
```

- Creates one new `ToolRegistry`.
- Registers all six accepted tool families.
- Does NOT instantiate concrete repos/services.
- No global singleton, module-level mutable registry, service locator, or DI framework.
- Dependencies are supplied by trusted outer composition code.

### Public provider-neutral registry schema

**DTO shape:**

```python
class ToolPublicDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    permission: Permission
    side_effects: list[SideEffect]
    allowed_session_modes: list[SessionMode]
    model_config = {"extra": "forbid", "frozen": True}


class ToolRegistrySchema(BaseModel):
    tools: list[ToolPublicDefinition]
    model_config = {"extra": "forbid", "frozen": True}
```

**Catalog builder:**

```python
def build_tool_registry_schema(registry: ToolRegistry) -> ToolRegistrySchema:
```

- Requires an actual `ToolRegistry`.
- Obtains definitions through `registry.list_definitions()`.
- Preserves registry deterministic name ordering.
- Derives schemas only through `definition.input_schema.model_json_schema()` and `definition.output_schema.model_json_schema()`.
- Preserves permission metadata.
- Converts side-effect sets to deterministic lists sorted by enum value.
- Converts allowed session modes to deterministic lists sorted by enum value.
- Returns typed provider-neutral schema.
- Works for any valid `ToolRegistry`, not only the MVP registry.

**Provider-neutral guarantees:**
- No Ollama/OpenAI-specific structures (`type: function`, `function.name`, etc.).
- No `OllamaTool`, `OpenAITool`, `function_call`, `tool_choice`.
- No provider-native schema mapping.
- No handlers, callables, Python class objects, or module paths in serialized payload.
- `model_dump(mode="json")` + `json.dumps(sort_keys=True)` succeeds without custom encoders.

### Root-package export decision

`dnd_assistant.tools.__init__` exports only generic catalog APIs:

- `ToolPublicDefinition`
- `ToolRegistrySchema`
- `build_tool_registry_schema`

`build_mvp_tool_registry` is NOT root-exported.  It must be imported explicitly:

```python
from dnd_assistant.tools.mvp_registry import build_mvp_tool_registry
```

This keeps `import dnd_assistant.tools` lightweight — no concrete family modules, application, retrieval, storage, or calendar modules are eagerly loaded from package root.

### Golden Vault integration

**Copy strategy:** `shutil.copytree` to `tmp_path / "Golden Vault Копия"` (spaces + Unicode for portable Path coverage).

**Source immutability:** SHA-256 snapshot before/after — proven unchanged.

**Real dependency stack:** AuditService, ObsidianVaultRepository, VaultSearchService, ObsidianWorldTimeRepository, ObsidianSessionMetadataRepository, ObsidianSessionEventRepository, SessionRuntimeService, ObsidianSessionRecoveryRepository, SessionRecoveryService, DeterministicCalendarService, build_mvp_tool_registry, ToolExecutor, build_tool_registry_schema.

**Baseline assertions:**
- `world_time.current_world_tick == 13800`, `revision == 1`
- No active session
- Completed sessions S001..S005 exist
- Next session ID is S006
- `npc_varos`: id=`npc_varos`, name=`Магистр Варос`, visibility=PLAYER, revision=4

**Cross-family flows verified:**
- Entity read: `get_entity(npc_varos)` returns revision 4 with body
- Entity patch: `patch_entity` with revision 4 → revision 5, body preserved, extra frontmatter preserved
- Entity append: `append_entity_fact` with revision 4 → revision 5, body prefix preserved
- Hidden entity: `get_entity(npc_archivist_kell)` → NotFoundError; `patch_entity` → NotFoundError
- World-time read: `get_world_time` returns 13800/1
- World-time advance: `advance_world_time(minutes=120, expected_revision=1)` → 13920/2
- Session lifecycle: start S006 → record_note → list_session_events → end_session → get_session → get_active_session=None
- Audit: entity/world-time/session mutations produce audit records (lower-layer owned)
- Permission isolation: READ cannot call WRITE tools; no mutation on denial
- Typed results: ToolExecutor returns registered output models

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/catalog.py` | **NEW** — ToolPublicDefinition, ToolRegistrySchema, build_tool_registry_schema |
| `src/dnd_assistant/tools/mvp_registry.py` | **NEW** — build_mvp_tool_registry composition |
| `src/dnd_assistant/tools/__init__.py` | **EDITED** — added generic catalog exports |
| `tests/unit/test_tool_catalog.py` | **NEW** — 30 catalog unit tests |
| `tests/unit/test_mvp_tool_registry.py` | **NEW** — 21 MVP registry unit tests |
| `tests/integration/test_tool_layer_golden_vault.py` | **NEW** — 26 Golden Vault integration tests (entity, world-time, catalog) |
| `tests/integration/test_tool_layer_golden_vault_session.py` | **NEW** — 17 Golden Vault integration tests (session lifecycle, cross-family audit, permission isolation, typed-result verification) |
| `tests/contract/test_boundaries.py` | **EDITED** — added catalog + mvp_registry boundary tests (9 new) |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — added this record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — S7-07 DONE |

### Tests and quality gates

- 32/32 catalog unit tests pass.
- 21/21 MVP registry unit tests pass.
- 26/26 main Golden Vault integration tests pass (entity, world-time, catalog).
- 17/17 session/cross-family Golden Vault integration tests pass (session lifecycle, cross-family audit, permission isolation, typed-result verification).
- 43/43 combined S7-07 Golden Tool Layer suite passes.
- 96/96 boundary tests pass (was 87, +9 new catalog/mvp_registry tests).
- 93/93 existing Golden retrieval tests pass.
- All existing Golden session tests pass.
- Full `uv run pytest`: all tests pass.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Maintainability

- `catalog.py`: 109 lines, under 700 production hard limit.
- `mvp_registry.py`: under 700 production hard limit.
- `test_tool_catalog.py`: 485 lines, under 1000 test hard limit.
- `test_mvp_tool_registry.py`: 251 lines, under 1000 test hard limit.
- `test_tool_layer_golden_vault.py`: 533 lines, under 1000 test hard limit.
- `test_tool_layer_golden_vault_session.py`: 351 lines, under 1000 test hard limit.
- No new legacy exceptions added.

### Explicit non-goals

- ModelGateway/Ollama integration.
- Provider-native schema adaptation.
- Fast Agent.
- ChangeSet/post-session processing.
- New tool families or domain capabilities.
- S7-08 historical review (not started).
- Stage 8 work (not started).

### Completion state

- S7-07 is **DONE**.
- Stage 7 remains **IN PROGRESS**.
- S7-08 remains **NOT STARTED**.
- Stage 8 remains **NOT STARTED**.

---

## S7-C09 — Correct S7-07 catalog type safety and verification baseline

### Independent review findings

1. **Catalog builder accepted duck-typed registry-like objects**: `build_tool_registry_schema` used `hasattr(registry, "list_definitions")` instead of `isinstance(registry, ToolRegistry)`, allowing any object with a `list_definitions` method to pass as a valid registry.

2. **S7-07 changed-file inventory omitted the split session/cross-family Golden module**: `tests/integration/test_tool_layer_golden_vault_session.py` was created in S7-07 but not listed in the `Files changed` table.

3. **S7-07 test evidence did not distinguish the two Golden modules**: The combined 43/43 count was correct, but the individual module counts (26 main, 17 session) and their distinct responsibilities were not documented.

### Corrections

- `build_tool_registry_schema` now requires `isinstance(registry, ToolRegistry)` via local import, with an MRO-based class-name fallback for resilience against `importlib.reload` patterns in boundary tests. The previous `hasattr(registry, "list_definitions")` duck-type check was removed.
- Regression test added for registry-like impostor (`_FakeRegistryLike` with `list_definitions` → `TypeError`).
- Regression test added for `ToolRegistry` subclass acceptance.
- S7-07 `Files changed` table corrected to include `tests/integration/test_tool_layer_golden_vault_session.py` with its real responsibility.
- S7-07 test evidence corrected to report both Golden modules independently and combined.
- No Stage-8 work was started.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/catalog.py` | **EDITED** — replaced `hasattr` duck-type check with `isinstance(registry, ToolRegistry)` via local import + MRO class-name fallback |
| `tests/unit/test_tool_catalog.py` | **EDITED** — added `test_registry_like_impostor_rejected` and `test_tool_registry_subclass_accepted` regression tests |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — corrected S7-07 file inventory and test evidence; added this correction record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — added S7-C09 DONE |

### Quality-gate evidence

- 32/32 catalog unit tests pass (including 2 new regression tests).
- 21/21 MVP registry unit tests pass.
- 26/26 main Golden Vault integration tests pass.
- 17/17 session/cross-family Golden Vault integration tests pass.
- 43/43 combined S7-07 Golden Tool Layer suite passes.
- 96/96 boundary tests pass.
- 276/276 maintainability tests pass.
- Full `uv run pytest`: 0 failed, 0 errors.
- `uv run ruff check .` — no errors.
- `uv run ruff format --check .` — all files formatted.
- `git diff --check` — no whitespace errors.

### Maintainability

- `catalog.py`: 109 physical lines (under 700 production hard limit).
- `test_tool_catalog.py`: 485 physical lines (under 1000 test hard limit).
- `test_tool_layer_golden_vault.py`: 533 physical lines (under 1000 test hard limit).
- `test_tool_layer_golden_vault_session.py`: 351 physical lines (under 1000 test hard limit).
- No new legacy exceptions added.
- `PRODUCTION_HARD_LIMIT` (700) and `TEST_HARD_LIMIT` (1000) unchanged.

### Golden fixture immutability

- `tests/fixtures/golden_test_vault`: zero diff vs HEAD.
- `tests/integration/conftest.py`: zero diff vs HEAD.  The file was inspected;
  it already matched HEAD.  No restoration command was required.  The final
  full-suite run therefore used the canonical tracked conftest.

  (The S7-C10 correction pass subsequently removed the MRO class-name/module
  fallback from ``catalog.py`` because it weakened strict runtime type safety.)

### Commit

- SHA: (reported in Final Report)
- Message: `fix: correct S7-07 catalog verification (S7-C09)`

### Stage status

- S7-07 remains **DONE**.
- S7-C09 is **DONE**.
- S7-08 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.

---

## S7-C10 — Enforce strict ToolRegistry identity and isolate boundary imports

### Independent-review defect

S7-C09 replaced the original duck-typing check with an ``isinstance`` check
plus an MRO class-name/module-string fallback:

```python
if not isinstance(registry, _ToolRegistry) and not any(
    c.__name__ == "ToolRegistry"
    and getattr(c, "__module__", None) == "dnd_assistant.tools.registry"
    for c in type(registry).__mro__
):
    raise TypeError(...)
```

This violates the public contract.  A class is NOT a real ``ToolRegistry``
merely because its ``__name__`` and ``__module__`` match — these are metadata
attributes that can be fabricated.

### Root cause

The fallback existed only to survive ``sys.modules`` identity churn caused by
boundary-test clean imports.  After a boundary test permanently replaced
``dnd_assistant`` module objects in ``sys.modules``, later unit tests in the
same process would hold references to the original ``ToolRegistry`` class
while the newly imported module graph contained a different ``ToolRegistry``
class, causing false-negative ``isinstance()`` results.

### Correction

1. **Removed MRO/name/module fallback completely** from ``build_tool_registry_schema``.
   The runtime check is now:

   ```python
   if not isinstance(registry, ToolRegistry):
       raise TypeError("registry must be a ToolRegistry instance")
   ```

   No second acceptance branch.  No ``hasattr``, Protocol, class-name check,
   ``__module__`` check, MRO name scan, duck typing, or structural typing
   fallback.

2. **Isolated boundary-test ``sys.modules`` mutations** by adding a root-level
   ``tests/conftest.py`` with an ``autouse=True`` pytest fixture that
   snapshots ``dnd_assistant`` modules before every test across the entire
   suite and restores the exact original module objects after.
   ``_clean_import()`` still gets a genuinely clean import graph for the
   assertion, but the pre-test module state is restored afterward.
   (S7-C11 later localized this mechanism to the tests that actually perform
   ``sys.modules`` clean imports.)

3. **Added spoofed-impostor regression**: a class dynamically created with
   ``name="ToolRegistry"`` and ``__module__="dnd_assistant.tools.registry"``
   is correctly rejected by ``build_tool_registry_schema``.

4. **Added boundary isolation regression**: proves that after a clean-import
   cycle, the original ``ToolRegistry`` class identity is preserved.

5. **Corrected S7-C09 conftest documentation**: the S7-C09 record now
   truthfully states that ``tests/integration/conftest.py`` was inspected
   and already matched HEAD — no restoration command was required.

### Files changed

| File | Change |
|---|---|
| `src/dnd_assistant/tools/catalog.py` | **EDITED** — removed MRO class-name/module fallback; strict ``isinstance(registry, ToolRegistry)`` only; normal module-level import instead of local import |
| `tests/unit/test_tool_catalog.py` | **EDITED** — added ``test_spoofed_class_name_module_impostor_rejected`` regression |
| `tests/conftest.py` | **NEW** — root-level global autouse fixture for module-identity restoration across all tests (subsequently removed/localized by S7-C11) |
| `tests/contract/test_boundaries.py` | **EDITED** — added ``autouse`` fixture ``_restore_dnd_assistant_modules``; added ``test_boundary_restores_module_identity`` regression |
| `tests/unit/test_cli_session.py` | **EDITED** — CLI session import-boundary tests switched to full ``dnd_assistant`` clean import; local restoration added by S7-C11 |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | **EDITED** — corrected S7-C09 conftest history; added this correction record |
| `DEVELOPMENT_STATUS.md` | **EDITED** — added S7-C10 DONE |

### Quality-gate evidence

- All catalog unit tests pass (including spoofed-impostor regression).
- All boundary tests pass (including identity-restoration regression).
- Catalog tests pass after boundary tests in the same process.
- Boundary tests pass after catalog tests in the same process.
- All MVP registry tests pass.
- All Golden Tool Layer integration tests pass.
- Full ``uv run pytest``: 0 failed, 0 errors.
- ``uv run ruff check .`` — no errors.
- ``uv run ruff format --check .`` — all files formatted.
- ``git diff --check`` — no whitespace errors.

### Maintainability

- ``catalog.py``: 109 physical lines (under 700 production hard limit).
- ``test_tool_catalog.py``: under 1000 test hard limit.
- ``test_boundaries.py``: under 1000 test hard limit.
- No new legacy exceptions added.
- ``PRODUCTION_HARD_LIMIT`` (700) and ``TEST_HARD_LIMIT`` (1000) unchanged.

### Golden fixture immutability

- ``tests/fixtures/golden_test_vault``: zero diff vs HEAD.
- ``tests/integration/conftest.py``: zero diff vs HEAD.

### Commit

- SHA: (reported in Final Report)
- Message: ``fix: enforce strict tool registry catalog type (S7-C10)``

### Stage status

- S7-07 remains **DONE**.
- S7-C09 remains **DONE**.
- S7-C10 is **DONE**.
- S7-08 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.

---

## S7-C11 — Localize sys.modules test isolation and correct S7-C10 history

### Independent review

- S7-C10 strict ToolRegistry production fix was correct.
- The module-restoration fixture was implemented globally in ``tests/conftest.py``,
  although only clean-import tests require it.
- S7-C10 historical file inventory omitted ``tests/conftest.py`` and
  ``tests/unit/test_cli_session.py``.

### Correction

- Removed root-level global autouse fixture (``tests/conftest.py`` deleted).
- Boundary module (``tests/contract/test_boundaries.py``) now owns its own
  per-test isolation via a module-local autouse fixture.
- ``TestCliSessionBoundaries`` (``tests/unit/test_cli_session.py``) owns narrow
  class-local isolation for its clean-import tests.
- Strict ``isinstance(registry, ToolRegistry)`` in ``catalog.py`` remains
  unchanged.
- Order regressions pass without global fixture:
  - ``test_boundaries.py`` → ``test_tool_catalog.py``
  - ``test_tool_catalog.py`` → ``test_boundaries.py``
  - ``TestCliSessionBoundaries`` → ``test_tool_catalog.py``
  - ``test_tool_catalog.py`` → ``TestCliSessionBoundaries``
- S7-C10 historical inventory/narrative corrected.
- No S7-08 or Stage-8 work.

### Files changed

| File | Change |
|---|---|
| ``tests/conftest.py`` | **DELETED** — root-level global autouse fixture removed; isolation moved to clean-import modules |
| ``tests/contract/test_boundaries.py`` | **EDITED** — added module-local ``_restore_dnd_assistant_modules`` autouse fixture |
| ``tests/unit/test_cli_session.py`` | **EDITED** — added class-local ``_restore_dnd_assistant_modules`` autouse fixture in ``TestCliSessionBoundaries`` |
| ``docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md`` | **EDITED** — corrected S7-C10 file inventory/narrative; added this correction record |
| ``DEVELOPMENT_STATUS.md`` | **EDITED** — added S7-C11 DONE |

### Quality-gate evidence

- All boundary tests pass.
- All CLI boundary tests pass.
- All catalog tests pass.
- All order-regression pairs pass.
- All MVP registry tests pass.
- All Golden Tool Layer integration tests pass.
- Full ``uv run pytest``: 0 failed, 0 errors.
- ``uv run ruff check .`` — no errors.
- ``uv run ruff format --check .`` — all files formatted.
- ``git diff --check`` — no whitespace errors.

### Maintainability

- ``test_boundaries.py``: under 1000 test hard limit.
- ``test_cli_session.py``: under 1000 test hard limit.
- ``test_tool_catalog.py``: under 1000 test hard limit.
- No new legacy exceptions added.
- ``PRODUCTION_HARD_LIMIT`` (700) and ``TEST_HARD_LIMIT`` (1000) unchanged.

### Golden fixture immutability

- ``tests/fixtures/golden_test_vault``: zero diff vs HEAD.
- ``tests/integration/conftest.py``: zero diff vs HEAD.

### Commit

- SHA: (reported in Final Report)
- Message: ``test: localize module import isolation (S7-C11)``

### Stage status

- S7-07 remains **DONE**.
- S7-C09 remains **DONE**.
- S7-C10 remains **DONE**.
- S7-C11 is **DONE**.
- S7-C12 is **DONE**.
- S7-08 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.

## S7-C12 — Deduplicate import isolation and restore maintainability ratchet

### Independent review

- S7-C11 correctly removed the global autouse fixture from ``tests/conftest.py``.
- However, S7-C11 copied the same module-restoration fixture body into multiple
  test modules (module-level ``@pytest.fixture(autouse=True)`` in 8 unit modules
  plus ``test_boundaries.py`` and ``TestCliSessionBoundaries``).
- The actual S7-C11 diff touched **14 files**, not the 5 listed in its
  ``Files changed`` section.
- The existing ``test_retrieval_contracts.py`` legacy ceiling was increased from
  1477 to 1495 solely because of the duplicated fixture code.

### Correction

- Re-introduced ``tests/conftest.py`` with a single reusable opt-in fixture
  ``restore_dnd_assistant_modules``.
- The fixture is **NOT** ``autouse`` — it has zero effect unless explicitly
  requested via ``@pytest.mark.usefixtures("restore_dnd_assistant_modules")``.
- Removed the duplicated fixture body from all 10 affected test modules.
- Each clean-import test class/function now explicitly opts into the shared
  fixture via ``@pytest.mark.usefixtures``.
- Ordinary behavior tests in the same modules are not affected.
- ``test_retrieval_contracts.py`` physical line count restored to 1476 (below
  the 1477 baseline).
- ``TEST_LEGACY_EXCEPTIONS`` retrieval baseline restored to 1477.
- No other legacy ceiling was increased.
- Production code unchanged.

### Files changed

| File | Change |
|---|---|
| ``tests/conftest.py`` | **RE-CREATED** — single reusable ``restore_dnd_assistant_modules`` fixture (opt-in, not autouse) |
| ``tests/contract/test_boundaries.py`` | **EDITED** — removed local fixture; ``pytestmark = pytest.mark.usefixtures("restore_dnd_assistant_modules")`` |
| ``tests/contract/test_maintainability.py`` | **EDITED** — ``test_retrieval_contracts.py`` baseline restored 1495 → 1477 |
| ``tests/unit/test_calendar_contracts.py`` | **EDITED** — removed local fixture; ``TestImportBoundaries`` opts in |
| ``tests/unit/test_calendar_conversion.py`` | **EDITED** — removed local fixture; ``TestImportBoundaries`` opts in |
| ``tests/unit/test_cli_session.py`` | **EDITED** — removed class-local fixture; ``TestCliSessionBoundaries`` opts in |
| ``tests/unit/test_retrieval_contracts.py`` | **EDITED** — removed local fixture; ``TestBoundaries`` opts in; compacted 2 lines |
| ``tests/unit/test_session_storage_paths.py`` | **EDITED** — removed local fixture; ``TestSessionPathsImportBoundaries`` opts in |
| ``tests/unit/test_storage_atomic.py`` | **EDITED** — removed local fixture; ``TestAtomicImportBoundaries`` opts in |
| ``tests/unit/test_storage_markdown.py`` | **EDITED** — removed local fixture; ``TestMarkdownImportBoundaries`` opts in |
| ``tests/unit/test_storage_paths.py`` | **EDITED** — removed local fixture; ``TestPathsImportBoundaries`` opts in |
| ``tests/unit/test_storage_types.py`` | **EDITED** — removed local fixture; ``TestStorageTypesImportBoundaries`` opts in |
| ``docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md`` | **EDITED** — added this correction record; corrected S7-C11 file inventory/narrative |
| ``DEVELOPMENT_STATUS.md`` | **EDITED** — added S7-C12 DONE |

### S7-C11 historical inventory correction

The actual S7-C11 commit changed these 14 files:

- ``DEVELOPMENT_STATUS.md``
- ``docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md``
- ``tests/conftest.py`` (DELETED)
- ``tests/contract/test_boundaries.py``
- ``tests/contract/test_maintainability.py``
- ``tests/unit/test_calendar_contracts.py``
- ``tests/unit/test_calendar_conversion.py``
- ``tests/unit/test_cli_session.py``
- ``tests/unit/test_retrieval_contracts.py``
- ``tests/unit/test_session_storage_paths.py``
- ``tests/unit/test_storage_atomic.py``
- ``tests/unit/test_storage_markdown.py``
- ``tests/unit/test_storage_paths.py``
- ``tests/unit/test_storage_types.py``

### S7-C11 maintainability-history correction

S7-C11 stated: "No new legacy exceptions added." This was incomplete because
the existing ``test_retrieval_contracts.py`` ceiling was raised:

```
1477 → 1495
```

S7-C12 reverted this increase and restored the accepted 1477 ratchet.

### Quality-gate evidence

- Boundary standalone: 97 passed.
- Catalog standalone: 33 passed.
- Boundary → Catalog: 130 passed.
- Catalog → Boundary: 130 passed.
- CLI boundary standalone: 3 passed.
- CLI boundary → Catalog: 36 passed.
- Catalog → CLI boundary: 36 passed.
- Calendar contracts: all passed.
- Calendar conversion: all passed.
- Retrieval contracts: all passed.
- Session storage paths: all passed.
- Storage atomic: all passed.
- Storage markdown: all passed.
- Storage paths: all passed.
- Storage types: all passed.
- Mixed-order regression (retrieval + catalog + calendar + MVP registry + boundaries): all passed.
- MVP registry: 21 passed.
- Golden Tool Layer (main + session): 43 passed.
- Maintainability: 278 passed.
- Full ``uv run pytest``: 3645 passed, 95 skipped, 0 failed, 0 errors.
- ``uv run ruff check .`` — no errors.
- ``uv run ruff format --check .`` — all files formatted.
- ``git diff --check`` — no whitespace errors.

### Maintainability

- ``PRODUCTION_HARD_LIMIT``: 700 (unchanged).
- ``TEST_HARD_LIMIT``: 1000 (unchanged).
- ``TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"]``: **1477** (restored from S7-C11 temporary 1495).
- No other legacy ceiling increased.
- No new legacy exceptions added.
- ``test_retrieval_contracts.py`` physical lines: 1476 (below 1477 baseline).

### Production diff

**Zero.** No ``src/`` files modified.

### Golden fixture immutability

- ``tests/fixtures/golden_test_vault``: zero diff vs HEAD.
- ``tests/integration/conftest.py``: zero diff vs HEAD.

### Commit

- SHA: (reported in Final Report)
- Message: ``test: deduplicate import isolation (S7-C12)``

### Stage status

- S7-07 remains **DONE**.
- S7-C09 remains **DONE**.
- S7-C10 remains **DONE**.
- S7-C11 remains **DONE**.
- S7-C12 is **DONE**.
- S7-08 remains **NOT STARTED**.
- Stage 7 remains **IN PROGRESS**.
- Stage 8 remains **NOT STARTED**.