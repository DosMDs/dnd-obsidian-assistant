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
| S9-04 — Bounded model→tool→model loop + clarification/final-response semantics | DONE | |
| S9-05 — Agent safety/failure hardening + multi-tool-call semantics | DONE | |
| S9-06 — CLI `dnd ask` + mocked end-to-end integration | NOT STARTED | |
| S9-07 — Full Stage-9 historical review / completion | NOT STARTED | |

### Correction passes

| Task | Status |
|---|---|
| S9-C00 — Correct Fast-Agent tool exposure import and permission boundaries | DONE |
| S9-C01 — Fail closed on StrEnum-compatible malformed execution-context fields | DONE |
| S9-C02 — Complete S9-01 structural coverage and verification evidence | DONE |
| S9-C03 — Reconcile Stage-9 task-map documentation after S9-02 | DONE |
| S9-C04 — Harden exact ToolCall binding and TOOL-result serialization evidence | DONE |
| S9-C05 — Correct terminal JSON validation and remove private FastAgent coupling | DONE |
| S9-C06 — Correct S9-C05 verification evidence and Stage-9 line-count record | DONE |
| S9-C07 — Fail closed on inconsistent exposed-tool snapshots in multi-call policy | DONE |
| S9-C08 — Complete structural validation of exposed-tool snapshots | DONE |
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

**`tests/unit/test_agent_tool_result_serialization.py`** (19 tests):
- Result serialisation: empty output, Unicode, real None→null, real False→false, real 0→0, empty string, empty list, empty dict, nested list/dict, deterministic full-string equality, deterministic key order and compact separators (11 tests)
- TOOL message: role, content, tool_name, tool_calls empty, call_id preserved, call_id None (6 tests)
- Serialisation failure: normal output baseline, real serialisation failure with handler count and cause preservation (2 tests)

All 48 tests passing. Full suite 4362 passed, 100 skipped. Ruff clean.

---

## S9-C04 — Harden exact ToolCall binding and TOOL-result serialization evidence

### Defect A — ToolCall membership uses weak Python equality

`_tool_call_in()` used `call.arguments == existing.arguments`, which
conflates distinct JSON types (`0 == False`, `1 == True`) recursively
through dict/list structures. An application caller could change
model-selected argument type and still pass the membership check.

**Fix:** Replaced plain `==` with `_json_args_equal()`, a recursive strict
JSON value comparator that uses `type(left) is not type(right)` to
distinguish `int`, `float`, `bool`, `None`, `str`, `list`, and `dict`.
Dict key order is ignored; list order is preserved. `0 != False`,
`1 != True`, `1 != 1.0`.

### Defect B — broad serialization catch

`_build_tool_message()` wrapped `output.model_dump(mode="json")` with
`except Exception`, violating the narrow public-boundary exception policy.

**Fix:** Replaced with `except PydanticSerializationError` — the concrete
Pydantic Core exception raised when `model_dump(mode="json")` cannot
serialize a validated field value. Unrelated unexpected exceptions now
propagate unchanged.

### Defect C — required None/False serialization tests were false positives

`test_none_value` observed `count == 0` (not None). `test_false_value`
observed `flag is True` (not False).

**Fix:** Added dedicated `NoneOutput`/`BoolOutput`/`IntOutput` schemas with
corresponding handlers that return real `None`, `False`, and `0`. Each
proves the correct JSON representation: `null`, `false`, `0`.

### Defect D — serialization evidence was incomplete

**Deterministic full-string equality:** Added
`test_deterministic_full_string_equality` asserting the exact expected
complete JSON string with `sort_keys=True`, `separators=(",", ":")`,
`ensure_ascii=False`.

**Real serialization failure:** Added
`test_real_serialization_failure_raises_validation_error` using an
`object()` value in an `object`-typed field. Handler executes exactly once.
`PydanticSerializationError` is preserved as `ValidationError.__cause__`.
No retry. No TOOL message returned.

### Regression coverage

**Strict membership (7 tests):** `0→False`, `False→0`, `1→True`,
`True→1`, `1→1.0`, nested `{"x": 0}→{"x": False}`, nested
`[1, False]→[True, 0]`. Every rejection proves `ValidationError` and
zero ToolExecutor calls.

**Dict order equivalence (3 tests):** Different key insertion order at
top level, nested, and mixed types — all accepted.

**Valid call execution (3 tests):** Exact call, equivalent call,
dict-order-different call — all execute exactly once.

**Serialization evidence (4 new):** Real `None→null`, real `False→false`,
real `0→0`, deterministic full-string equality, real serialization failure
with handler count and cause preservation.

### Scope

- No ToolExecutor contract changes.
- No FastAgent/ModelGateway contract changes.
- No second model turn.
- No S9-04 work (no model→tool→model loop).
- No S9-05 work (no multi-call policy).
- No dependency/lockfile changes.
- No protected-harness changes.
- No `DEVELOPMENT_STATUS.md` changes.
- Existing `test_agent_tool_execution.py` (928 lines) unchanged.

### Changed files

- `src/dnd_assistant/application/agent_tool_execution.py`
- `tests/unit/test_agent_tool_execution_boundaries.py`
- `tests/unit/test_agent_tool_result_serialization.py`
- `docs/stages/09_FAST_AGENT.md`

---

## S9-C05 — Correct terminal JSON validation and remove private FastAgent coupling

### Defect A — terminal output does not use Pydantic JSON validation and broad-catches Exception

`_parse_agent_outcome()` performed `json.loads(content)` followed by
`AgentTextOutcome.model_validate(parsed)`, wrapping Pydantic validation in
`except Exception`. This violated the S9-04 requirement for narrow
Pydantic-only exception handling.

**Fix:** Replaced the two-step parse+validate pipeline with a single
`AgentTextOutcome.model_validate_json(content)` call. Only
`PydanticValidationError` is caught and converted to `ModelError`.
Unexpected programming exceptions (e.g. `RuntimeError`) propagate
unchanged. No `json.loads`, no `isinstance(parsed, dict)` manual check,
no `except Exception`.

### Defect B — AgentLoop reaches into private FastAgent state

The second model call used `self._fast_agent._model_gateway.chat_with_tools(...)`,
accessing a private implementation detail of `FastAgent`.

**Fix:** `AgentLoop.__init__()` now stores the supplied `model_gateway` as
`self._model_gateway`. The second model call uses
`self._model_gateway.chat_with_tools(...)` instead. Both turns still
receive the exact same `ModelGateway` instance — no cloning, wrapping,
or second provider resolution.

### Regression coverage (17 new tests)

**Terminal validation (15 tests):**

- Valid respond JSON → `AgentTextOutcome.RESPOND`
- Valid clarify JSON → `AgentTextOutcome.CLARIFY`
- Unicode preserved
- Malformed JSON → `ModelError`, `__cause__` is `PydanticValidationError`
- Schema-invalid JSON (unknown kind) → same cause evidence
- Empty JSON object → same cause evidence
- Missing kind → same cause evidence
- Missing message → same cause evidence
- Extra field → same cause evidence
- Empty message → same cause evidence
- Whitespace-only message → same cause evidence
- JSON array → same cause evidence
- JSON null → same cause evidence
- Wrong field types → same cause evidence
- Unexpected `RuntimeError` from validation entry point → propagates
  unchanged, NOT converted to `ModelError`

**Private-coupling regression (1 test):**

- `AgentLoop` works when `_fast_agent` is replaced with a test double
  that has `decide()` but intentionally no `_model_gateway` attribute

**Same-gateway identity (1 test):**

- Both model turns use the exact same `ModelGateway` instance

### Scope

- No S9-05 work (no multi-tool semantics, no retry, no tool budget > 1)
- No real Ollama/model work
- No ToolExecutor changes
- No ModelGateway contract changes
- No prompt changes
- No protected-harness changes
- No dependency/lockfile changes
- No `DEVELOPMENT_STATUS.md` changes
- `test_agent_loop.py` (969 lines) unchanged
- `test_agent_loop_boundaries.py` grew from 527 to 858 physical lines

### Changed files

- `src/dnd_assistant/application/agent_loop.py`
- `tests/unit/test_agent_loop_boundaries.py`
- `docs/stages/09_FAST_AGENT.md`

---

## S9-C06 — Correct S9-C05 verification evidence and Stage-9 line-count record

### Defect

Independent review found the S9-C05 physical-line count for
`test_agent_loop_boundaries.py` was recorded as 738 instead of the correct
858 physical lines.

Additionally, the S9-C05 Final Report did not demonstrate canonical full
`uv run pytest` because integration tests were excluded from the reported
run.

### Fix

- Corrected the S9-C05 line-count record from `738` to `858` (verified from
  repository bytes: `len(path.read_bytes().splitlines())`).
- Ran canonical `uv run pytest` with no path/marker exclusions to obtain
  the missing full-suite evidence.

### Verification evidence

- `uv run pytest` (no exclusions): **4429 passed, 100 skipped, 0 failed, 0 errors**
- Integration tests were collected and passed by the canonical run
- Exact physical line counts from repository bytes:
  - `agent_loop.py` = 275
  - `test_agent_loop.py` = 969
  - `test_agent_loop_boundaries.py` = 858

### Scope

- No S9-C05 production implementation was changed.
- No production code, tests, dependencies, harness, or configuration were
  modified.
- No S9-05 work was started.
- No real Ollama/model was used.
- Exactly one file changed: `docs/stages/09_FAST_AGENT.md`.

---

## S9-04 — Bounded model→tool→model loop + clarification/final-response semantics

**Accepted starting boundary:** `9806e1840f2d47996e0389709d7179200dc16c99`

### New production modules

- `src/dnd_assistant/prompts/agent_v2.py` — versioned prompt resource with deterministic terminal-text protocol
- `src/dnd_assistant/application/agent_loop.py` — bounded model-tool-model orchestration

### Modified production modules

- `src/dnd_assistant/application/fast_agent.py` — active prompt switched from `agent-v1` to `agent-v2`

### agent-v2 prompt resource

`PROMPT_VERSION = "agent-v2"`. Preserves all player-safety rules from agent-v1 and adds:

- Deterministic terminal-text protocol: `{"kind":"respond","message":"..."}` or `{"kind":"clarify","message":"..."}`
- No Markdown fences, no prose before/after JSON
- `respond` = terminal answer for this run
- `clarify` = model needs additional user information
- Ambiguous/missing write targets → clarify preferred
- Native tool-calling mechanism for tool requests
- Terminal outcome after TOOL result (no second tool request)

### AgentOutcomeKind (StrEnum)

```python
class AgentOutcomeKind(StrEnum):
    RESPOND = "respond"
    CLARIFY = "clarify"
```

### AgentTextOutcome (Pydantic BaseModel)

```python
class AgentTextOutcome(BaseModel):
    kind: AgentOutcomeKind
    message: str  # non-empty, non-whitespace-only
    model_config = {"extra": "forbid", "frozen": True}
```

- `message` validated non-empty and non-whitespace-only via `@field_validator`
- Extra fields forbidden

### AgentRunResult (frozen dataclass)

```python
@dataclass(frozen=True, slots=True)
class AgentRunResult:
    initial_decision: AgentDecision
    tool_execution: AgentToolExecutionResult | None
    final_response: ToolAwareResponse
    outcome: AgentTextOutcome
```

### AgentLoop

```python
class AgentLoop:
    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        model_gateway: ModelGateway,
        tool_catalog: ToolRegistrySchema,
        tool_execution_service: AgentToolExecutionService,
    ) -> None: ...

    def run(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentRunResult: ...
```

### Terminal content parsing (`_parse_agent_outcome`)

- Accepts `ToolAwareResponse` with zero tool calls
- Parses JSON content using `AgentTextOutcome` schema
- Malformed model output → `ModelError` with original cause retained
- Rejects: plain prose, empty content, JSON list, `{}`, missing fields, extra fields, unknown kind, whitespace-only message
- No broad `except Exception`
- No repair of malformed JSON
- No inference from punctuation/question marks

### Direct respond/clarify path

- Zero tool calls in initial response → parse `AgentTextOutcome`
- `model calls = 1`, `tool executions = 0`, `tool_execution = None`
- Both `respond` and `clarify` are terminal
- `clarify` does NOT loop or ask again inside `run()`

### Single-tool path

- Exactly one `ToolCall` in initial response → execute through `AgentToolExecutionService`
- Build follow-up request as exact ordered history: `SYSTEM, USER, ASSISTANT(tool call), TOOL(result)`
- Second model call with exact first-turn exposure snapshot
- `model calls = 2`, `tool executions = 1`

### Hard bound enforcement

- **Initial multi-tool call (2+)**: `ModelError` before any ToolExecutor execution. `model calls = 1`, `tool executions = 0`
- **Post-tool tool call**: `ModelError` without additional execution. First tool executed exactly once. `model calls = 2`, `tool executions = 1`
- **Post-tool multiple tool calls**: Same bounded failure
- No second tool execution, no third model call, no retry

### Tool-execution failure propagation

- `ValidationError`, `NotFoundError`, `ConflictError`, `StorageError`, domain/application errors propagate unchanged
- No second model call after tool-execution failure
- No retry, no replacement tool call

### Second-model-call failure

- `ModelError` from second `chat_with_tools` → propagated unchanged
- Tool may already have succeeded → no rollback, no retry, no third call

### Malformed output after successful tool

- Second response fails `AgentTextOutcome` validation → `ModelError`
- Tool executed exactly once, model called exactly twice
- No tool retry, no third model call, no synthetic response

### Clarification safety

- `clarify` outcome with zero tool execution → safe path for ambiguous writes
- Python never transforms `clarify` into a write call
- No semantic guessing by Python (no `endswith("?")`, no keyword matching)

### WRITE safety

- WRITE tool with audit: handler executes once, TOOL result replayed, final response parsed
- WRITE tool without audit: tool hidden by exposure policy → `ModelError` from `FastAgent.decide()` before loop
- Direct clarification with WRITE authority/tools exposed: zero ToolExecutor calls, zero mutation

### Prompt-v2 switch

- `FastAgent` now imports from `dnd_assistant.prompts.agent_v2`
- `AgentDecision.prompt_version == "agent-v2"`
- `agent_v1.py` preserved unchanged

### Import boundary

Fresh `import dnd_assistant.application.agent_loop` does NOT eagerly load:
- `dnd_assistant.models.ollama`
- `dnd_assistant.storage`
- `dnd_assistant.retrieval`
- `dnd_assistant.cli`

Uses `TYPE_CHECKING` for all heavy imports. Runtime imports of `ChatRequest`, `ChatMessage`, `MessageRole` are deferred into `run()`.

### S9-05 strict deferral

Not implemented: multiple initial tool calls, multiple second-round tool calls, execute-all policy, execute-first policy, parallel calls, atomic batch, partial success, rollback, multi-write ordering, read/write call ordering, multi-round loops, tool-call budget > 1.

### S9-06 strict deferral

Not implemented: `dnd ask` Typer command, Rich rendering, interactive clarification input, CLI composition, live Ollama setup.

### Test evidence

**`tests/unit/test_agent_loop.py`** (36 tests):

- Direct path: respond JSON, clarify JSON (2 tests)
- Single-tool path: tool→respond, tool→clarify (2 tests)
- Follow-up request: exact history, exposed-tool snapshot reuse, original unchanged (3 tests)
- WRITE safety: with audit executes once, without audit fails (2 tests)
- Clarification safety: zero mutation with WRITE authority (1 test)
- Prompt-v2: version, DATA reference, no invented IDs, clarification, terminal JSON, native tools, no premature success, terminal after tool, active FastAgent uses agent-v2 (9 tests)
- Terminal outcome schema: respond, clarify, Unicode, empty, whitespace, unknown kind, missing kind, missing message, extra field, parse respond, parse clarify, parse plain text, parse empty, parse JSON array, parse empty object, parse with tool calls (16 tests)
- Import boundary (1 test)

**`tests/unit/test_agent_loop_boundaries.py`** (8 tests):

- Initial multi-call: 2 calls, 3 calls (2 tests)
- Post-tool tool call: single, multiple (2 tests)
- Malformed outcome: direct, post-tool (2 tests)
- Second model failure: propagated (1 test)
- Tool-execution failure: no second call (1 test)

All 44 tests passing. Full suite 4412 passed, 100 skipped. Ruff clean.

---

## S9-05 — Agent safety/failure hardening + multi-tool-call semantics

**Accepted starting boundary:** `6d04d9fd9e244650d71832bc829c6ee35a534eb3`

### Final MVP multi-tool policy

```text
0 calls → direct terminal outcome
1 call → READ or WRITE through ToolExecutor
2..4 calls → READ-only sequential batch
5+ calls → reject before execution
multi-call containing WRITE → reject before execution
duplicate non-None call_id → reject before execution
READ batch failure → stop on first failure
model calls remain bounded to 2
tool rounds remain bounded to 1
```

### MAX_TOOL_CALLS_PER_RUN

```python
MAX_TOOL_CALLS_PER_RUN: int = 4
```

Hard bounds:

- maximum model calls = 2
- maximum initial tool calls accepted = 4
- maximum tool executions = 4
- maximum model→tool→model rounds = 1

### AgentRunResult contract evolution

The singular `tool_execution: AgentToolExecutionResult | None` field was replaced with:

```python
tool_executions: tuple[AgentToolExecutionResult, ...]
```

- Direct respond/clarify → `tool_executions == ()`
- Single tool → `len(tool_executions) == 1`
- Multi-READ batch → `len(tool_executions) == number of initial tool calls`

No duplicate singular and plural state is kept.

### Permission classification source

Multi-call batch safety uses `initial_decision.exposed_tools` snapshot.
Each call is matched by exact tool name against `ToolPublicDefinition.permission`.
Only `Permission.READ` batches of 2..4 calls are permitted.

### Sequential READ-batch semantics

Calls execute in model order. No parallelism, sorting, deduplication, or
argument rewriting. Each execution goes through `AgentToolExecutionService`.

### Partial failure policy

If call `i` fails in a READ batch:

- calls `0..i-1` may have completed
- call `i` raises the original exception
- calls `i+1..end` are NOT executed
- no second model call, no retry, no rollback

### Follow-up conversation history

For N successful calls, the follow-up `ChatRequest` has:

```text
SYSTEM
USER
ASSISTANT(tool calls)
TOOL(result for call 0)
TOOL(result for call 1)
...
TOOL(result for call N-1)
```

### Duplicate call_id policy

- Duplicate non-None `call_id` → `ModelError` before any execution
- Multiple calls with `call_id=None` are permitted
- No call_id rewriting

### WRITE safety integration

- Single WRITE with valid AuditContext → executes exactly once
- Multi-call containing WRITE → rejected before execution, even with valid WRITE authority
- No model permission authority: only trusted Python metadata determines safety

### Failure hardening

- Unexpected exceptions from READ execution → propagate unchanged, stop immediately
- Second ModelGateway call fails → no retry, no execution replay
- Terminal AgentTextOutcome validation fails → no retry, no execution replay

### Input immutability

No successful or rejected multi-call run mutates:

- initial `AgentDecision`
- `ToolCall` objects
- `ToolCall.arguments`
- initial `exposed_tools` tuple
- `ToolPublicDefinition` objects
- `ExecutionContext`

### Import boundary

Fresh `import dnd_assistant.application.agent_loop` does NOT eagerly load:

- `dnd_assistant.models.ollama`
- `dnd_assistant.storage`
- `dnd_assistant.retrieval`
- `dnd_assistant.cli`

### Unchanged contracts

- `agent_v2.py` — unchanged
- `FastAgent` — unchanged
- `ModelGateway` — unchanged
- `ToolExecutor` — unchanged
- `ToolRegistry` — unchanged
- `ToolCatalog` — unchanged
- `ToolPublicDefinition` — unchanged
- `AgentToolExecutionService` — unchanged
- `AgentDecision` — unchanged
- `AgentTextOutcome` — unchanged
- `AgentOutcomeKind` — unchanged
- `_parse_agent_outcome` — unchanged

### Test evidence

**`tests/unit/test_agent_loop_multi_tool.py`** (16 tests):

- 2-READ batch success (1 test)
- 4-READ batch success (1 test)
- Execution order == model order (1 test)
- Same READ tool, different arguments (1 test)
- 5-call rejection (1 test)
- 20-call batch rejection (1 test)
- READ+WRITE rejection (1 test)
- WRITE+READ rejection (1 test)
- WRITE+WRITE rejection (1 test)
- READ+READ+WRITE rejection (1 test)
- Duplicate non-None call_id rejection (1 test)
- Multiple None call_id permitted (1 test)
- Inconsistent exposed-snapshot failure (1 test)
- Single READ call unchanged (1 test)
- Single WRITE+audit call unchanged (1 test)
- Direct clarification unchanged (1 test)

**`tests/unit/test_agent_loop_failure_policy.py`** (7 tests):

- Stop-on-first-failure propagation (1 test)
- Unexpected exception propagation (1 test)
- Second-model failure, no retry (1 test)
- Terminal validation failure, no retry (1 test)
- Post-batch tool call rejected (1 test)
- Initial decision unchanged after batch (1 test)
- ToolCall objects unchanged after batch (1 test)

### Verification evidence

- 83 AgentLoop tests passing (36 + 8 + 16 + 7 + 16 boundary/terminal)
- 343 regression tests passing (FastAgent, ToolExecutor, S9-03, Ollama, ModelGateway)
- 456 contract tests passing (boundaries, maintainability, harness)
- Full suite: **4455 passed, 100 skipped, 0 failed, 0 errors**
- Ruff check: clean
- Ruff format: clean
- `git diff --check`: clean
- No protected-harness changes
- No dependency changes
- No real Ollama/model used

## S9-C07 — Fail closed on inconsistent exposed-tool snapshots in multi-call policy

**Status:** DONE

**Starting base:** `fa235835586d23759e0df31e528f301cc4711441`

### Defect

The S9-05 production helper `_reject_multi_call_containing_write` searched `initial_decision.exposed_tools` and stopped at the first matching tool name. A structurally inconsistent snapshot containing duplicate definitions for the same tool name (e.g. READ+WRITE) could make permission classification order-dependent. Additionally, if a malformed `Permission` value (plain string, `None`, foreign StrEnum) reached the policy, the existing code could leak `AttributeError` instead of failing closed with `ModelError`.

### Correction

1. **`_resolve_multi_call_read_tool`** — a new private resolver that:
   - Collects all exposed definitions matching the call name.
   - Raises `ModelError` on 0 matches (missing definition).
   - Raises `ModelError` on 2+ matches (ambiguous duplicate snapshot).
   - Validates that the single matching definition's `permission` is a real canonical `Permission` member via `isinstance(perm, P)`.
   - Raises `ModelError` with `"malformed permission"` for plain strings, `None`, and foreign StrEnum values.
   - Raises `ModelError` if permission is not `Permission.READ`.
   - Returns the unique matching definition on success.

2. **`_reject_multi_call_containing_write`** — updated to delegate to `_resolve_multi_call_read_tool` for each call instead of implementing inline first-match logic.

### New test coverage

**`tests/unit/test_agent_loop_snapshot_policy.py`** (9 tests):

- Missing exposed definition → `ModelError`, zero execution, no second model call
- Duplicate READ+READ definitions → `ModelError`
- Duplicate READ+WRITE definitions → `ModelError`
- Duplicate WRITE+READ definitions → `ModelError` (proves order independence)
- `permission="read"` → `ModelError` (not `AttributeError`)
- `permission="write"` → `ModelError` (not `AttributeError`)
- `permission=None` → `ModelError`
- Foreign StrEnum with value `"read"` → `ModelError`
- Foreign StrEnum with value `"write"` → `ModelError`

All inconsistent-snapshot tests use the S9-C05-style `_FakeFastAgent` test double that bypasses normal `FastAgent.decide()` validation, exercising `AgentLoop` defence in depth.

### Preserved behavior

- Normal 2/4 READ batches still execute sequentially.
- Same READ tool called multiple times with different arguments works.
- Multiple `call_id=None` permitted.
- Mixed WRITE batches (READ+WRITE, WRITE+READ, WRITE+WRITE, READ+READ+WRITE) still reject before any execution.
- Single WRITE+audit call unchanged.
- Single READ call unchanged.
- Direct clarification unchanged.
- 5+ call cap unchanged.
- Duplicate non-None `call_id` unchanged.
- No retry, rollback, second tool round, or transaction semantics added.

### Verification evidence

- 9 new snapshot policy tests: **9 passed, 0 failed, 0 errors**
- 83 AgentLoop tests: **83 passed, 0 failed, 0 errors**
- 343 regression tests (FastAgent, S9-03, Tool Layer, ModelGateway): **343 passed, 0 failed, 0 errors**
- 458 contract tests (boundaries, maintainability, harness): **458 passed, 0 failed, 0 errors**
- Full suite: **4466 passed, 100 skipped, 0 failed, 0 errors**
- Ruff check: clean
- Ruff format: clean
- `git diff --check`: clean
- No protected-harness changes
- No dependency changes
- No real Ollama/model used
- No S9-06 work
- `DEVELOPMENT_STATUS.md` unchanged (S9-05 DONE, S9-06 NOT STARTED)

---

## S9-C08 — Complete structural validation of exposed-tool snapshots

**Status:** DONE

**Starting base:** `104f4dd5e8ab642c412cd7d6bd6d6717018a3ac7`

### Defect

S9-C07 validated matching-name cardinality and Permission but still
dereferenced arbitrary exposed snapshot entries before validating
`ToolPublicDefinition` identity. A manually constructed/corrupted
`AgentDecision` could contain arbitrary objects in
`decision.exposed_tools`, causing incidental `AttributeError` or
accepting duck-typed metadata as trusted policy input instead of
failing closed with `ModelError`.

### Correction

1. **`_validate_exposed_snapshot`** — a new private helper in
   `agent_loop.py` that validates every entry in the exposed-tool
   snapshot before any policy use:
   - Every entry must be a real canonical `ToolPublicDefinition`
     instance via `isinstance(entry, ToolPublicDefinition)`.
   - Each `name` field must be a real `str`, non-empty, and
     non-whitespace-only.
   - Duck-type impostors with matching `name`/`permission` attributes
     fail closed.
   - `object()`, `None`, and arbitrary non-`ToolPublicDefinition`
     objects fail closed.
   - Malformed `name` values (`None`, `False`, `0`, `""`, `"   "`)
     fail closed.
   - Malformed entries unrelated to any called tool (e.g. `object()`
     in a snapshot alongside a valid `read_tool` definition) still
     fail closed before any execution, regardless of position.

2. **Integration point** — `_validate_exposed_snapshot` is called in
   `AgentLoop.run()` after duplicate call-ID rejection and before
   multi-call WRITE safety classification, ensuring all inconsistent
   snapshot failures happen before any tool execution.

3. **No production schema weakening** — `ToolPublicDefinition` and
   `Permission` remain unchanged. Malformed values are injected via
   `ToolPublicDefinition.model_construct(...)` in tests only.

### New test coverage (10 tests)

**`tests/unit/test_agent_loop_snapshot_policy.py`:**

**Malformed snapshot entry (3 tests):**
- `object()` in exposed_tools → `ModelError`, zero execution, no
  second model call
- `None` in exposed_tools → `ModelError`
- Duck-type impostor with `name="read_tool"`, `permission=Permission.READ`
  → `ModelError`

**Malformed name field (5 tests):**
- `name=None` → `ModelError`
- `name=False` → `ModelError`
- `name=0` → `ModelError`
- `name=""` → `ModelError`
- `name="   "` → `ModelError`

**Malformed unrelated entry (2 tests):**
- Malformed entry first, valid entry second → `ModelError`
- Valid entry first, malformed entry second → `ModelError`
  (proves order independence)

All malformed-snapshot tests produce `ModelError` (not `AttributeError`,
not `TypeError`), zero `AgentToolExecutionService` calls, and zero
second `ModelGateway` calls.

### Preserved behavior

- All 9 S9-C07 snapshot policy tests preserved.
- All 16 S9-05 multi-tool policy tests preserved.
- All 7 S9-05 failure policy tests preserved.
- All 36 S9-04 loop tests preserved.
- All 16 S9-04 boundary tests preserved.
- 2 READ calls succeed sequentially.
- 4 READ calls succeed sequentially.
- Same READ tool with different arguments succeeds.
- Multiple `None` call_id values permitted.
- Single READ succeeds.
- Single WRITE+audit succeeds.
- Direct clarification executes zero tools.
- Mixed WRITE batches (READ+WRITE, WRITE+READ, WRITE+WRITE,
  READ+READ+WRITE) → `ModelError`, zero execution, one initial model
  decision only.
- 5+ call cap unchanged.
- Duplicate non-None `call_id` unchanged.
- No retry, rollback, second tool round, or transaction semantics added.

### Verification evidence

- 19 snapshot policy tests: **19 passed, 0 failed, 0 errors**
- 102 AgentLoop tests: **102 passed, 0 failed, 0 errors**
- 343 regression tests (FastAgent, S9-03, Tool Layer, ModelGateway):
  **343 passed, 0 failed, 0 errors**
- 458 contract tests (boundaries, maintainability, harness):
  **458 passed, 0 failed, 0 errors**
- Full suite: **4476 passed, 100 skipped, 0 failed, 0 errors**
- Ruff check: clean
- Ruff format: clean
- `git diff --check`: clean
- No protected-harness changes
- No dependency changes
- No real Ollama/model used
- No S9-06 work
- `DEVELOPMENT_STATUS.md` unchanged (S9-05 DONE, S9-06 NOT STARTED)
- All inconsistent-snapshot failures happen before any tool execution
- No S9-06 work
- No real Ollama/model work