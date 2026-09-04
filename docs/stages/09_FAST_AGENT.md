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
| S9-00 — Deterministic Fast-Agent tool exposure policy + Stage-9 kickoff | DONE | Completed after S9-C00/S9-C01 |
| S9-01 — Compact Context Builder over currently accepted data sources | DONE | Completed after S9-C02; uses only accepted current data sources |
| S9-02 — One-step FastAgent model decision boundary | DONE | Completed; S9-C03 reconciles documentation only |
| S9-03 — Validated ToolExecutor execution + tool-result message adaptation | DONE | |
| S9-04 — Bounded model→tool→model loop + clarification/final-response semantics | NOT STARTED | |
| S9-05 — Agent safety/failure hardening + multi-tool-call semantics | NOT STARTED | |
| S9-06 — CLI `dnd ask` + mocked end-to-end integration | NOT STARTED | |
| S9-07 — Full Stage-9 historical review / completion | NOT STARTED | |

### Correction passes

| Task | Status |
|---|---|
| S9-C00 — Correct Fast-Agent tool exposure import and permission boundaries | DONE |
| S9-C01 — Fail closed on StrEnum-compatible malformed execution-context fields | DONE |
| S9-C02 — Complete S9-01 structural coverage and verification evidence | DONE |
| S9-C03 — Reconcile Stage-9 task-map documentation after S9-02 | DONE |
| S9-C00+ | Only when independent review finds actual defects |

## S9-02 — One-step FastAgent model decision boundary

**Accepted starting boundary:** `76666cd5ebdfe92106a0e63e0e1489df4d8a0b7e`

### AgentDecision contract

```python
@dataclass(frozen=True, slots=True)
class AgentDecision:
    prompt_version: str
    request: ChatRequest
    exposed_tools: tuple[ToolPublicDefinition, ...]
    response: ToolAwareResponse
```

- `prompt_version` = reproducible prompt identity for tracing/evals
- `request` = exact conversation history used for the first model turn
- `exposed_tools` = exact allowlist snapshot shown to the model for this turn
- `response` = validated provider-neutral `ToolAwareResponse`

No action enum, respond/clarify/tool DTOs, provider-native fields, Ollama metadata, or filesystem paths.

### FastAgent constructor/decide contract

```python
class FastAgent:
    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        model_gateway: ModelGateway,
        tool_catalog: ToolRegistrySchema,
    ) -> None: ...

    def decide(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentDecision: ...
```

Synchronous API. No async.

### agent-v1 prompt resource

`src/dnd_assistant/prompts/agent_v1.py`:

```python
PROMPT_VERSION = "agent-v1"
SYSTEM_PROMPT = "..."
```

The v1 prompt communicates player-facing D&D campaign assistant semantics, context-as-data boundaries, no speculative tool execution, clarification preference, and prohibition of filesystem/shell access.

### Deterministic JSON request format

The USER message content is explicit JSON with `sort_keys=True`, `ensure_ascii=False`, `separators=(",", ":")`, `allow_nan=False`.

Required top-level JSON keys: `user_input`, `current_world_tick`, `active_session`, `relevant_entities`, `recent_events`.

Required active-session object: `session_id`, `world_tick_start`.

Required entity object: `entity_id`, `entity_type`, `name`, `status`, `knowledge_status`, `tags`, `body_excerpt`, `body_truncated`.

Required event object: `event_id`, `event_type`, `world_tick`, `text_excerpt`, `text_truncated`.

### SYSTEM/USER two-message first turn

Exactly two messages: `SYSTEM` (content = `SYSTEM_PROMPT`), `USER` (content = deterministic JSON). No assistant history, no tool-result messages.

### Turn-local exposed-tool snapshot

Calls `select_agent_tools(catalog, context=execution_context)` once per `decide()` invocation. The returned list is converted to a tuple for `AgentDecision.exposed_tools` and passed as a list to `chat_with_tools()`.

### Exact one chat_with_tools call

`ModelGateway.chat_with_tools()` is called exactly once on the successful path. Zero calls to `chat()`, `generate_structured()`, `embed()`, or `health()`. No retry, no fallback, no second turn.

### Application-level tool-name allowlist validation

For every `ToolCall` in `response.message.tool_calls`, the tool name must be present in `exposed_tools` by exact match. Unknown tool names, hidden real tools (permission/audit/session-mode filtered), and mixed allowed/forbidden multi-calls all raise `ModelError`. Zero tool execution.

### Text/tool/text+tool preservation

- Text only: `response.message.content` preserved, `tool_calls == ()`.
- Tool call only: `response.message.content` is `None`, tool call preserved exactly.
- Text + tool call: both preserved.
- Multiple calls: all preserved in original order.

### Multiple-call preservation without execution semantics

Multiple `ToolCall` values are preserved and name-validated. No execution, no ordering/atomicity/execution semantics defined. Those belong to S9-05.

### Prompt_version propagation

`AgentDecision.prompt_version` always equals `PROMPT_VERSION` from the versioned prompt resource (`"agent-v1"`).

### Failure propagation

- `ValidationError` from context builder → propagated, model call count = 0.
- `StorageError` from context builder → propagated, model call count = 0.
- Invalid `execution_context` → `TypeError` from selector, model call count = 0.
- `ModelError` from `chat_with_tools` → same error propagated, exactly one attempted call, no retry.
- Out-of-allowlist `ToolCall` → `ModelError`, no second model call.

No broad `except Exception` in production FastAgent.

### Import boundary

A fresh `import dnd_assistant.application.fast_agent` does NOT eagerly load:
- `dnd_assistant.models.ollama`
- `dnd_assistant.tools.executor`
- `dnd_assistant.storage`
- `dnd_assistant.retrieval`
- `dnd_assistant.cli`

Uses `TYPE_CHECKING` for all heavy imports. Runtime imports of `select_agent_tools`, `ChatMessage`, `ChatRequest`, `MessageRole` are deferred into `decide()`.

### Explicit S9-03 deferral

Not implemented: ToolExecutor invocation, ToolRegistry lookup for execution, input-schema execution validation, output-schema validation, handler execution, tool-result serialization, TOOL ChatMessage creation, assistant/tool history replay.

### Explicit S9-04 deferral

Not implemented: model→tool→model loop, second `chat_with_tools` call, max rounds, final-response classification, clarification classification, clarification loop, retry after tool result.

### Explicit S9-05 deferral

Not implemented: execute all, execute first, atomic multi-call batch, parallel tool execution, partial-success policy, multiple-write ordering policy.

### Test evidence

- 60 tests: request construction (25), context-as-data isolation (3), tool exposure (6), model response (7), tool argument boundary (6), failure propagation (5), determinism/non-mutation (4), no forbidden behaviour (3), fresh-process import (1)
- All passing
- Fresh-process subprocess regression confirms import isolation
- Adversarial context strings (JSON-like, prompt-looking) remain in USER data, not SYSTEM
- Subprocess-based `sys.modules` diagnostic confirms no eager loading of forbidden modules

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
| S9-01 | DONE after correction |
| S9-02 | DONE |
| S9-03..S9-07 | NOT STARTED |
| Stage 10 | NOT STARTED |

---

## S9-C02 — Complete S9-01 structural coverage and verification evidence

### Defect A — `"text": None` was not actually tested

The `_make_event(text=None)` helper used `if text is not None: extras["text"] = text`, so passing `text=None` produced a **missing** `"text"` key, not a present-None value. The existing `test_text_missing_or_none` therefore tested the missing state twice.

**Fix:** Introduced `_TEXT_MISSING = object()` sentinel as the default for `_make_event(text=...)`. When `text is _TEXT_MISSING`, the `"text"` key is omitted. Passing explicit `None` now correctly produces `extra_fields == {"text": None}`.

### Defect B — exact `SearchQuery` preservation was not demonstrated

`FakeSearchService` stored `str(query)` instead of the actual `SearchQuery` object, making it impossible to assert exact text preservation through the query DTO.

**Fix:** `FakeSearchService.last_query` now stores the accepted `SearchQuery` object directly. A new `test_exact_search_query_preserved` test proves that `"  Гэндальф?  "` is preserved exactly through both `context.user_input` and `search_service.last_query.text`, and that `last_limit == 5`.

### Defect C — invalid-input zero-read coverage was incomplete

Only `search.last_query` was checked. The contract requires zero dependency reads across all five Context Builder dependencies.

**Fix:** Added `_call_count` counters to all five fakes (`FakeSearchService.search_call_count`, `FakeVaultRepository.get_entity_call_count`, `FakeSessionMetadataRepository.get_active_session_call_count`, `FakeSessionEventRepository.list_events_call_count`, `FakeWorldTimeRepository.get_current_world_time_call_count`). A parametrized `test_zero_dependency_reads_on_invalid_input` proves all five counters are zero for four representative invalid inputs (empty, whitespace-only, non-string, control-char).

### MNT-04 structural coverage

The `TestEventText` class was rewritten with explicit separate regressions:

| State | `text_excerpt` | `text_truncated` |
|---|---|---|
| Missing | `None` | `False` |
| Present `None` | `None` | `False` |
| `""` | `""` | `False` |
| `0` | `None` | `False` |
| `False` | `None` | `False` |
| `[]` | `None` | `False` |
| `{}` | `None` | `False` |
| Valid short string | preserved exactly | `False` |
| String > 400 | first 400 chars | `True` |

The present-None test proves that `"text" in source.extra_fields` and `source.extra_fields["text"] is None` before calling the builder, preventing false-positive helper bugs.

### Scope

- No S9-01 production code changed (`agent_context.py` unchanged, 331 lines).
- No Stage-9 scope expansion.
- No protected harness changes.
- No dependency/lockfile changes.
- Exactly two files changed:
  - `tests/unit/test_agent_context.py`
  - `docs/stages/09_FAST_AGENT.md`

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

- 52 tests: input boundary (9), search (7), entity materialisation (6), visibility (4), world time (3), active session (2), recent events (4), event text (10), determinism (4), forbidden behaviour (3), fresh-process import (1)
- All passing
- Fresh-process subprocess regression confirms import isolation
- Plain-string `"player"` visibility regression: fail closed
- Event text structural states (MNT-04): missing, present-None, `""`, `0`, `False`, `[]`, `{}`, valid short string, long string > 400 — each tested independently
- Present-None test proves `"text" in event.extra_fields` and `event.extra_fields["text"] is None` before builder call
- Exact `SearchQuery` preservation: `"  Гэндальф?  "` preserved through both `user_input` and `SearchQuery.text`
- Invalid-input zero-read regression: all five dependencies verified untouched
- No S9-01 production code changed

---

## S9-C03 — Reconcile Stage-9 task-map documentation after S9-02

### Defect

Independent review found that the primary/current Task map at the top of this
document contained stale contradictory state:

- S9-01 was listed as `NOT STARTED` despite being completed after S9-C02.
- S9-00 and S9-02 still carried `Current task` notes after their completion.
- This contradicted the already-correct later Stage-9 status section and
  `DEVELOPMENT_STATUS.md`.

### Fix

- S9-00 Task-map row: changed from `DONE | Current task` to `DONE` with
  note `Completed after S9-C00/S9-C01`.
- S9-01 Task-map row: changed from `NOT STARTED` to `DONE` with note
  `Completed after S9-C02; uses only accepted current data sources`.
- S9-02 Task-map row: changed from `DONE | Current task` to `DONE` with
  note `Completed; S9-C03 reconciles documentation only`.

### Scope

- No S9-02 production implementation was changed.
- No S9-03 work was started.
- No tests, dependencies, harness, or configuration were changed.
- Exactly one file changed: `docs/stages/09_FAST_AGENT.md`.

---

## S9-03 — Validated ToolExecutor execution + tool-result message adaptation

**Accepted starting boundary:** `087dd9d7bad25917e263c4e8f542a6ce9e1dddf5`

### New production module

`src/dnd_assistant/application/agent_tool_execution.py`

### AgentToolExecutionResult (frozen dataclass)

```python
@dataclass(frozen=True, slots=True)
class AgentToolExecutionResult:
    tool_call: ToolCall
    output: BaseModel
    tool_message: ChatMessage
```

### AgentToolExecutionService

```python
class AgentToolExecutionService:
    def __init__(self, *, tool_executor: ToolExecutor) -> None: ...

    def execute(
        self,
        decision: AgentDecision,
        tool_call: ToolCall,
        *,
        execution_context: ExecutionContext,
    ) -> AgentToolExecutionResult: ...
```

### Exact pre-execution validation order

1. Reject malformed/non-AgentDecision input → `ValidationError`
2. Reject malformed/non-ToolCall input → `ValidationError`
3. Reject malformed/non-ExecutionContext input → `ValidationError`
4. Exact decision membership: `ToolCall` must be semantically equal to one of `decision.response.message.tool_calls` (same name, same arguments, same call_id) → `ValidationError`
5. Turn-local exposure snapshot: call name must exist in `decision.exposed_tools` by exact name → `ValidationError`
6. Delegate to `ToolExecutor.execute()` with preserved model arguments
7. Deterministic TOOL-result JSON serialisation
8. Return `AgentToolExecutionResult`

### Call-membership rule

Semantic equality: same `name`, same `arguments` (deep dict equality), same `call_id` (or both None). Same name + different arguments is rejected before ToolExecutor. This prevents changing model-selected arguments after the decision.

### Exposed-tool rule

Call name must exist by exact name in `decision.exposed_tools` (defence in depth).

### ToolExecutor invocation shape

```python
self._tool_executor.execute(
    tool_call.name,
    input_data=tool_call.arguments,
    context=execution_context,
)
```

No application-level input schema validation, coercion, defaults, or filtering.

### Output serialisation settings

```python
output.model_dump(mode="json", by_alias=True)
json.dumps(
    json_ready,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
)
```

### TOOL ChatMessage mapping

```python
ChatMessage(
    role=MessageRole.TOOL,
    content=<deterministic JSON>,
    tool_name=tool_call.name,
    tool_call_id=tool_call.call_id,
)
```

### Failure propagation

- Unknown actual-registry tool → `NotFoundError` (propagated unchanged)
- Invalid input → `ValidationError` (propagated unchanged)
- READ context → WRITE tool → `ConflictError` (propagated unchanged)
- Session-mode mismatch → `ConflictError` (propagated unchanged)
- WRITE tool without audit → `ValidationError` (propagated unchanged)
- Invalid output → `ValidationError` after handler exactly once (no retry)
- Domain/project handler error → propagated unchanged
- Unexpected handler exception → propagated unchanged
- Serialisation failure → `ValidationError` (no retry, no second execution)

### S9-04 strict deferral

Zero ModelGateway calls from `agent_tool_execution.py`. No second-turn request construction. No `chat`, `chat_with_tools`, `generate_structured`, `embed`, or `health` calls.

### S9-05 strict deferral

No multi-call execution semantics. No batch result DTO. No atomicity decision. No partial-success policy. No parallelism. The service is a per-call primitive: exactly one supplied `ToolCall` is executed; siblings are not automatically inspected or executed.

### Import boundary

Fresh `import dnd_assistant.application.agent_tool_execution` does NOT eagerly load:
- `dnd_assistant.models.ollama`
- `dnd_assistant.storage`
- `dnd_assistant.retrieval`
- `dnd_assistant.cli`

Uses `TYPE_CHECKING` for all heavy imports. Runtime imports of `AgentDecision`, `ToolCall`, `ExecutionContext`, `ChatMessage`, `MessageRole` are deferred into `execute()` and `_build_tool_message()`.

### Test evidence

Two test modules (stable capability split):

**`tests/unit/test_agent_tool_execution.py`** (29 tests):
- Turn binding: valid execution, semantic equality, same-name/different-args rejection, unrelated call rejection, exposed-tool rejection, malformed decision/call/context rejection, zero executor calls on pre-execution failures (10 tests)
- Trusted execution: READ success, raw argument preservation, Pydantic coercion in ToolExecutor, unknown tool, invalid input, READ→WRITE denial, session-mode denial, WRITE without audit, WRITE+audit success, invalid output after handler, domain error propagation, unexpected exception propagation, no retry after post-handler failure (13 tests)
- Multi-call per-call primitive: execute only supplied call, sibling not automatically executed (2 tests)
- Non-mutation: decision unchanged, tool_call unchanged (2 tests)
- No model invocation: service has no ModelGateway dependency (1 test)
- Fresh-process import isolation (1 test)

**`tests/unit/test_agent_tool_result_serialization.py`** (17 tests):
- Result serialisation: empty output, Unicode, None, False, 0, empty string, empty list, empty dict, nested list/dict, deterministic key order and compact separators (10 tests)
- TOOL message: role, content, tool_name, tool_calls empty, call_id preserved, call_id None (6 tests)
- Serialisation failure: normal output serialises fine (1 test)

All 46 tests passing. Full suite 4345 passed, 100 skipped. Ruff clean.