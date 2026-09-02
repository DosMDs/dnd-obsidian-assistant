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
| S7-01 | NOT STARTED | Concrete read-only entity/session tools |
| S7-02 | NOT STARTED | Concrete write entity/session tools |
| S7-03 | NOT STARTED | Calendar/World-time tools |
| S7-04 | NOT STARTED | Provider-native schema adaptation (ModelGateway integration) |
| S7-05 | NOT STARTED | Tool-layer hardening and edge-case coverage |

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
| Handler raises unexpected exception | `ValidationError` |

### AuditContext ownership

- `ExecutionContext.audit` is typed as `Any` to avoid a runtime dependency
  on `storage.audit` at the tools layer.
- Static type checkers see `AuditContext` through a `TYPE_CHECKING` import.
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