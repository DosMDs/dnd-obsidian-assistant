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

### Stage status after correction

| Task | Status |
|---|---|
| Stage 9 | IN PROGRESS |
| S9-00 | DONE after correction |
| S9-01..S9-07 | NOT STARTED |
| Stage 10 | NOT STARTED |