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
| S7-01 | NOT STARTED | Entity read tools |
| S7-02 | NOT STARTED | Session read tools |
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