# Stage 9 — Fast Agent

**Status:** IN PROGRESS

**Pre-Stage-9 base:** `6af880e3f0fed39273c14c4acbfd4d98cd700a16`

## Previous stage

| Stage | Status |
|---|---|
| Stage 8 — Model Gateway / Ollama | DONE |
| MNT-04 — Harden GigaCode boundary-case and evidence reliability | DONE |
| MNT-C04 — Correct Python int-to-float overflow reliability guidance | DONE |

## Accepted baseline

### Tool Layer (Stage 7)

- 18 MVP tools: 10 READ, 8 WRITE
- Provider-neutral `ToolPublicDefinition` / `ToolRegistrySchema`
- `ToolExecutor` with permission, session-mode, and audit enforcement

### Model Layer (Stage 8)

- Five-operation synchronous `ModelGateway`
- Native provider tool calling
- `ToolAwareResponse`
- Validated `ToolCall` arguments

### Application Layer (pre-Stage-9)

- `SessionRuntimeService`
- `SessionRecoveryService`
- No FastAgent yet
- No Context Builder yet

## Task map

| Task | Status | Notes |
|---|---|---|
| S9-00 — Deterministic Fast-Agent tool exposure policy + Stage-9 kickoff | DONE | Current task |
| S9-01 — Compact Context Builder over currently accepted data sources | NOT STARTED | Must use only data sources that exist at that point. Do not assume Stage-11/12 artifacts (State/Party.md, summaries, recaps, Campaign State) exist. |
| S9-02 — One-step FastAgent model decision boundary | NOT STARTED | |
| S9-03 — Validated ToolExecutor execution + tool-result message adaptation | NOT STARTED | |
| S9-04 — Bounded model→tool→model loop + clarification/final-response semantics | NOT STARTED | |
| S9-05 — Agent safety/failure hardening + multi-tool-call semantics | NOT STARTED | |
| S9-06 — CLI `dnd ask` + mocked end-to-end integration | NOT STARTED | |
| S9-07 — Full Stage-9 historical review / completion | NOT STARTED | |

### Correction passes

| Task | Status |
|---|---|
| S9-C00 — Correct Fast-Agent tool exposure import and permission boundaries | DONE |
| S9-C01 — Fail closed on StrEnum-compatible malformed execution-context fields | DONE |
| S9-C00+ | Only when independent review finds actual defects |

## Important Context Builder deferral

S9-01 must use only data sources that actually exist at that point.

Do not assume Stage-12 derived artifacts already exist:

- `State/Party.md`
- `State/Active Quests.md`
- `State/Active Threads.md`
- `State/World State.md`

Campaign State remains a later stage.

Likewise do not assume Stage-11 summaries/recaps exist.

Future compact context must be assembled from accepted existing sources until those later artifacts actually exist.

## Stage-10+ deferrals

Stage 9 must not implement:

- ChangeSet
- Post-session processing
- Summary
- Recap
- Campaign State persistence
- Bootstrap
- Model eval framework

In particular, do not use ChangeSet as a prerequisite for current session-time ToolExecutor writes.

Stage 10 remains separate.

## Clarification boundary

For future S9 work:

- Ambiguous write target → clarification preferred
- Zero speculative mutation

Do not implement the clarification loop in S9-00.

Do not move ambiguity handling into ToolExecutor.

Later Fast Agent orchestration will react to accepted errors/results rather than weaken Tool Layer safety.

## Player-knowledge safety

Future Context Builder/retrieval integration must preserve player visibility.

Do not implement retrieval or visibility filtering in S9-00.

Do not add a new retrieval query path.

Existing retrieval/service boundaries remain unchanged.

## S9-00 implementation

### Production module

`src/dnd_assistant/application/agent_tool_selection.py`

Public function:

```python
def select_agent_tools(
    catalog: ToolRegistrySchema,
    *,
    context: ExecutionContext,
) -> list[ToolPublicDefinition]:
```

Eligibility is a deterministic intersection of:

1. **Permission**: READ authority exposes only READ tools. WRITE authority exposes both READ and WRITE tools.
2. **Session mode**: A tool is eligible only when `context.session_mode` is in its `allowed_session_modes`.
3. **WRITE audit prerequisite**: A WRITE tool is eligible only when `context.audit is not None`.

Input catalog order is preserved. Returns a new list. Does not mutate inputs.

### Test module

`tests/unit/test_agent_tool_selection.py` — 30 tests covering:

- Permission eligibility (8 tests)
- Session-mode eligibility (6 tests)
- Combined intersection eligibility (5 tests)
- Empty catalog (2 tests)
- Order preservation (2 tests)
- Non-mutation (4 tests)
- TypeError for invalid arguments (2 tests)
- No execution side effects (1 test)

---

## S9-C00 — Correct Fast-Agent tool exposure import and permission boundaries

### Defect A — fresh module import eagerly loads ToolExecutor

**Root cause:** `dnd_assistant.application.agent_tool_selection` imported
`ToolPublicDefinition`, `ToolRegistrySchema`, `ExecutionContext`, and
`Permission` from `dnd_assistant.tools` at module scope.  Importing from
`dnd_assistant.tools` initialises the package root, whose `__init__.py`
eagerly imports `dnd_assistant.tools.executor` (`ToolExecutor`).

The existing unit test only inspected the module namespace (`dir(mod)`)
within the same process, which could not detect the eager-loading defect
because the test runner had already loaded the Tool Layer.

**Fix:** Moved all runtime Tool-Layer imports into the `select_agent_tools()`
function body.  Module-scope imports are now under `TYPE_CHECKING` only,
preventing Python from resolving them at module-import time.

### Defect B — malformed permission fails open

**Root cause:** `_is_permission_eligible()` used `else: return True` after
checking `Permission.READ`.  Since `ExecutionContext` is a frozen dataclass
with no runtime validation of `granted_permission`, a malformed value (e.g.
a plain string) would fall through to the `else` branch and acquire
WRITE-equivalent exposure.

**Fix:** Replaced `else: return True` with an explicit `Permission.WRITE`
check.  Unexpected/malformed permission values now return `False` (fail
closed), exposing no tools.

### Regression coverage

- **Fresh-process `sys.modules` test:** A subprocess-based diagnostic
  (`sys.executable -c`) imports only `agent_tool_selection` and asserts
  that `dnd_assistant.models`, `dnd_assistant.models.ollama`,
  `dnd_assistant.tools.executor`, `dnd_assistant.storage`,
  `dnd_assistant.retrieval`, and `dnd_assistant.cli` are NOT loaded.
  Portable on Windows/macOS (no Bash, no shell-specific commands).

- **Malformed-permission regression:** Four tests using `cast()` to inject
  deliberately invalid `granted_permission` values (plain string, wrong
  enum member).  Verifies that malformed permission cannot expose READ or
  WRITE tools, even with audit present.

### Scope

- No ToolExecutor/tools package refactor.
- No Stage-9 scope expansion (no FastAgent, ContextBuilder, ChangeSet,
  model invocation, CLI).
- Exactly three files changed:
  - `src/dnd_assistant/application/agent_tool_selection.py`
  - `tests/unit/test_agent_tool_selection.py`
  - `docs/stages/09_FAST_AGENT.md`

---

## S9-C01 — Fail closed on StrEnum-compatible malformed execution-context fields

### Defect

S9-C00 correctly fixed the eager-import defect and added malformed-permission
protection, but its protection relied on StrEnum equality (`==`).  Since
`Permission` inherits from `StrEnum`, Python string-compatible equality means
structurally malformed values such as plain strings `"read"` or `"write"`
compare equal to `Permission.READ` and `Permission.WRITE` respectively.

Because `ExecutionContext` is a frozen dataclass with no runtime validation
of its annotated fields, this was constructible at runtime:

```python
context = ExecutionContext(
    granted_permission="write",  # plain string, not Permission.WRITE
    session_mode=SessionMode.NO_ACTIVE_SESSION,
    audit=some_audit,
)
```

This would acquire WRITE-equivalent tool exposure despite having no actual
`Permission` member.

The same class of issue existed for `SessionMode`: a plain string
`"active_session"` would compare equal to `SessionMode.ACTIVE_SESSION` via
StrEnum equality.

### Fix

**Permission (`_is_permission_eligible`):**

- Added `isinstance(granted, permission_enum)` check before any semantic
  comparison.  A plain string or foreign StrEnum fails this check and
  returns `False` (fail closed).
- Changed member comparison from `==` to `is` (identity) for the READ/WRITE
  checks.
- Also changed `tool.permission == permission_enum.READ` to
  `tool.permission is permission_enum.READ` for consistency.

**Session mode (`_is_session_mode_eligible` — new function):**

- Extracted session-mode eligibility into a dedicated function with the
  same structural validation pattern.
- Added `isinstance(mode, mode_enum)` check before membership testing.
- Changed membership from `in` (which uses `==`) to `any(mode is allowed ...)`
  using identity comparison.

**Deferred import:**

- Added `SessionMode` to the deferred runtime imports inside
  `select_agent_tools()` so that `_is_session_mode_eligible` can receive
  the canonical type reference.

### Regression coverage (10 new tests)

**Permission same-value plain strings (3 tests):**

- `"read"` + READ tool → hidden
- `"write"` + READ tool → hidden
- `"write"` + WRITE tool + valid audit → hidden

**Foreign StrEnum permission (3 tests):**

- `_ForeignPermission.READ` + READ tool → hidden
- `_ForeignPermission.WRITE` + READ tool → hidden
- `_ForeignPermission.WRITE` + WRITE tool + valid audit → hidden

**Session-mode same-value plain strings (2 tests):**

- `"active_session"` + ACTIVE_SESSION tool → hidden
- `"no_active_session"` + NO_ACTIVE_SESSION tool → hidden

**Foreign StrEnum session mode (2 tests):**

- `_ForeignSessionMode.ACTIVE_SESSION` + ACTIVE_SESSION tool → hidden
- `_ForeignSessionMode.NO_ACTIVE_SESSION` + NO_ACTIVE_SESSION tool → hidden

All existing 34 tests preserved and passing.

### Scope

- No Tool Layer refactor.
- No FastAgent, ContextBuilder, ChangeSet, model invocation, or CLI.
- No modification to `DEVELOPMENT_STATUS.md`.
- No modification to protected test harness.
- No dependency/lockfile changes.
- Exactly three files changed:
  - `src/dnd_assistant/application/agent_tool_selection.py`
  - `tests/unit/test_agent_tool_selection.py`
  - `docs/stages/09_FAST_AGENT.md`

### Stage status after correction

| Task | Status |
|---|---|
| Stage 9 | IN PROGRESS |
| S9-00 | DONE after correction |
| S9-C01 | DONE |
| S9-01 | DONE |
| S9-02..S9-07 | NOT STARTED |
| Stage 10 | NOT STARTED |

---

## S9-01 — Compact Context Builder over currently accepted data sources

**Accepted starting boundary:** `e8319ee358ea59cb9170e2b7d1f9ef7d9f3f708a`

S9-C00 accepted.  S9-C01 accepted.

### New context DTOs

All are `@dataclass(frozen=True, slots=True)`:

- `AgentEntityContext` — entity_id, entity_type, name, status, knowledge_status, tags (tuple), body_excerpt, body_truncated
- `AgentSessionContext` — session_id, world_tick_start
- `AgentEventContext` — event_id, event_type, world_tick, text_excerpt, text_truncated
- `AgentContext` — user_input, current_world_tick, active_session, relevant_entities (tuple), recent_events (tuple)

### Builder dependencies

```python
AgentContextBuilder(
    *,
    search_service: SearchService,
    vault_repository: VaultRepository,
    session_repository: SessionMetadataRepository,
    event_repository: SessionEventRepository,
    world_time_repository: WorldTimeRepository,
)
```

### Fixed compactness limits

- Maximum relevant entities: 5
- Maximum recent events: 5
- Maximum entity Markdown body excerpt: 1000 characters
- Maximum event text excerpt: 400 characters

### Accepted data sources

- `SearchService.search()` for player-visible entity retrieval (limit=5)
- `VaultRepository.get_entity()` for entity materialisation
- `SessionMetadataRepository.get_active_session()` for active session
- `SessionEventRepository.list_events()` for recent session events
- `WorldTimeRepository.get_current_world_time()` for current world tick

### Player-visibility defence in depth

- Uses `is` identity comparison against `Visibility.PLAYER`
- `Visibility.DM` and `Visibility.SYSTEM` entities are excluded
- Plain string `"player"` (structurally malformed) is rejected — fail closed

### Stale-search-hit handling

- `NotFoundError` from `get_entity()` → entity skipped silently
- `StorageError` is NOT swallowed

### Current world time

- `NotFoundError` → `current_world_tick = None`
- `StorageError` → propagated

### Active-session recent-event behaviour

- No active session → `active_session=None`, `recent_events=()`, `list_events()` NOT called
- Active session → last 5 events in physical append order
- Event `"text"` field: missing/None/wrong-type → `text_excerpt=None`; empty string preserved; long text clipped to 400 chars

### Deterministic clipping and ordering

- Preserves SearchService result order
- First occurrence wins for duplicate entity IDs
- Event tail preserves physical append order
- Tag order preserved from source
- Exact prefix clipping (no ellipsis appended)

### Model/tool/prompt deferrals

- Zero ModelGateway, ChatMessage, ChatRequest, ToolAwareResponse references
- Zero ToolExecutor, select_agent_tools references
- Zero writes
- Zero prompt construction
- Fresh-process import does NOT eagerly load `dnd_assistant.models`, `dnd_assistant.tools`, `dnd_assistant.cli`

### Stage-10+ deferrals

- No ChangeSet
- No Campaign State
- No Summary/Recap
- No post-session processing
- No token counting
- No configuration

### Test evidence

- 46 tests: input boundary (6), search (6), entity materialisation (6), visibility (4), world time (3), active session (2), recent events (4), event text (6), determinism (4), forbidden behaviour (3), fresh-process import (1), parametrized (2)
- All passing
- Fresh-process subprocess regression confirms import isolation
- Plain-string `"player"` visibility regression: fail closed
- Event `""` (empty string) structural test: `text_excerpt=""`, `text_truncated=False`
- Event `0` and `False` wrong-type tests: `text_excerpt=None`