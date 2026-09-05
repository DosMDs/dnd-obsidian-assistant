# Migration 001 — Pydantic AI Runtime Migration

## 1. Decision

Project will evaluate and, if gates pass, migrate generic agent/model runtime mechanics to Pydantic AI in a dedicated branch.

This is not a commitment to force full framework adoption. The migration is intentionally reversible and evidence-driven.

Reference custom runtime remains available in `main` and Git history.

## 2. Reference baseline

```text
Repository: DosMDs/dnd-obsidian-assistant
Reference branch: main
Reference SHA: f424a0f659afd5f8bcbce55c4d280cc8e621133f
Date: 2026-09-04
State: S9-06 accepted, S9-07 not started
```

Active migration branch:

```text
feat/pydantic-ai-runtime
```

PAIM-00 kickoff commit:

```text
ac9fd4c7e19475adb2331eb010ce8c78af98b309
```

Optional human-friendly reference tag may be created separately, but branch base SHA is sufficient for rollback/review.

## 3. Why migrate now

The project already has a reliable custom implementation of:

- provider-neutral model protocol;
- native Ollama integration;
- tool-call DTO/validation plumbing;
- one-step FastAgent;
- bounded AgentLoop;
- CLI composition;
- extensive safety tests.

That work provides an unusually strong reference specification. Stage 10+ has not started, so migration can happen before later features depend on the custom runtime shape.

## 4. Target value

Pydantic AI should reduce maintenance of generic infrastructure:

- provider/message protocol details;
- tool-call/tool-result mechanics;
- structured output plumbing;
- generic model→tool→model loop;
- request/tool usage accounting;
- standard tracing/instrumentation.

It must not replace trusted application policy.

## 5. Non-negotiable boundaries

### Must remain custom/project-owned

```text
Domain schemas
VaultRepository
CalendarService
Retrieval/EntityResolver
Session runtime/raw JSONL
ToolRegistry application metadata
ToolExecutor
Permission/session/audit policy
DndAgentPolicy
ChangeSet
Post-session policy
Campaign State policy
Deterministic eval acceptance rules
```

### May move to framework

```text
Agent model protocol
Message/tool-call plumbing
Structured output mechanics
Generic run loop
Tool-result replay
Usage/tracing support
```

## 6. Authorization rule

No framework facility is trusted as the final authorization boundary.

```text
framework-visible tool
→ application adapter
→ ToolExecutor
→ trusted side effect
```

This rule remains even if framework filtering/approval appears sufficient in normal cases.

## 7. PAIM task map

### PAIM-00 — Documentation/branch kickoff — DONE

No runtime changes.

Deliverables:

- migration branch;
- ADR;
- migration plan;
- status/roadmap update;
- GigaCode rule/skill;
- exact base SHA;
- outcome/rollback policy.

### PAIM-01 — Candidate dependency qualification

Build minimal isolated tests/spike using chosen Pydantic AI candidate.

Prove:

- import/runtime compatibility;
- sync entrypoint behavior;
- local Ollama connection;
- structured result;
- single tool;
- multi-tool response;
- custom base URL;
- predictable failure mapping.

No FastAgent replacement yet.

### PAIM-02 — Blocker gate

Prove the exact architecture-critical capabilities:

- complete batch admission before side effects;
- sequential tool execution;
- explicit retry control;
- bounded requests/tool calls;
- immutable/frozen per-turn exposed set at application level;
- all calls route via `ToolExecutor`;
- hidden/unknown/malformed call fails closed.

If not achievable using stable public extension points, stop and classify issue before continuing.

### PAIM-03 — Test harness improvements directly needed by migration

Only if necessary:

- standardize HTTPX mocking with `respx`;
- evaluate `pytest-randomly` for hidden state.

Do not bundle unrelated infrastructure libraries.

### PAIM-04 — Toolset bridge

Translate `ToolRegistry` public definitions into Pydantic AI tool definitions/toolset without moving handler logic.

Invocation goes to `ToolExecutor`.

### PAIM-05 — DndAgentPolicy

Create explicit application policy component or equivalent cohesive layer covering all Stage-9 agent safety semantics.

### PAIM-06 — Context/deps integration

Reuse accepted Context Builder/retrieval path. Context remains application-prepared data.

### PAIM-07 — Replace one-step FastAgent mechanics

Use framework for first model decision while preserving observable app contract/safety behavior.

### PAIM-08 — Replace bounded AgentLoop mechanics

Use framework generic orchestration. Preserve D&D-specific limits/admission/terminal rules.

### PAIM-09 — Ollama gate

Compare framework integration to native reference. Select:

```text
framework Ollama
custom/native Ollama component
migration reconsideration
```

### PAIM-10 — Sync/thread gate

Prove worker-thread/tool-callback behavior does not violate storage/audit/session assumptions.

### PAIM-11 — Full behavioral parity

Run Stage-9 negative/boundary suite against final migration runtime.

### PAIM-12 — Real Ollama smoke/performance

Use actual accepted local model/profile for operational evidence.

### PAIM-13 — Eval comparison

Measure safety/correctness/latency vs reference.

### PAIM-14 — Cleanup

Delete superseded generic custom infrastructure and obsolete implementation-specific tests. Avoid permanent dual runtime.

### PAIM-15 — Final review

Decide `ACCEPTED`, `PARTIAL`, or `REJECTED`.


## 8. PAIM-00 completion record

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Reference/base SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`
**PAIM-00 commit:** `ac9fd4c7e19475adb2331eb010ce8c78af98b309`

Git verification confirms the PAIM-00 commit is a direct child of the accepted reference SHA and that the migration branch is exactly one commit ahead of the reference at this checkpoint. `main` remains at `f424a0f659afd5f8bcbce55c4d280cc8e621133f`.

### Exact PAIM-00 changed-file inventory

```text
.gigacode/rules/40-pydantic-ai-migration.md
.gigacode/skills/pydantic-ai-migration/SKILL.md
DEVELOPMENT_STATUS.md
GIGACODE.md
docs/adr/0003-pydantic-ai-runtime-migration.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
docs/migrations/README.md
docs/stages/09_FAST_AGENT.md
```

All eight changed files are Markdown documentation/agent-instruction files. No Python source, tests, `pyproject.toml`, `uv.lock`, runtime configuration, provider code, tool code or Vault/storage code changed in PAIM-00.

### Evidence note

The repository facts above were independently reconciled from Git after the PAIM-00 commit. This record intentionally does **not** invent command-level test/Ruff results that are not present in the retained repository evidence. PAIM-00 is accepted as the documentation/architecture kickoff; PAIM-C00 reconciles the documentation gaps before PAIM-01.

### Next task

```text
PAIM-02 — Critical blocker gate
```

## 17. PAIM-C02 correction record — close unknown-tool retry-count evidence gap

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `5d41511d7dd1f775c044b14359dc0db6bafa1ab6`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C01 proved that unknown-tool handling:
- eventually fails under default retries;
- fails without retry under `retries={"tools": 0}`;
- never executes an application tool handler.

But it did **not** count model requests. The documented claims about semantic
retry model rounds were inferred rather than executable evidence.

PAIM-C02 adds a model request counter to the `FunctionModel` function and
asserts exact counts, handler counts, and exception types.

### Executable retry evidence

| Scenario | Model requests | Handler calls | Exception |
|---|---|---|---|
| Default retries | 2 | 0 | `UnexpectedModelBehavior` — "Tool 'nonexistent_tool' exceeded max retries count of 1" |
| `retries={"tools": 0}` | 1 | 0 | `UnexpectedModelBehavior` — "Tool 'nonexistent_tool' exceeded max retries count of 0" |

Key findings:

- **Default retries:** `model_requests == 2` proves exactly one semantic retry
  model round occurred (the initial request + one retry). The framework's
  default tool retry count is 1.
- **Zero retries:** `model_requests == 1` proves no semantic retry model round
  occurred. The framework raises `UnexpectedModelBehavior` immediately after
  the single model request.
- **Both cases:** `handler_calls == 0` proves no application tool handler
  executes regardless of retry policy.
- **Exception type:** Both cases raise `UnexpectedModelBehavior` (not
  `UserError`). The broad `pytest.raises((UserError, UnexpectedModelBehavior))`
  in PAIM-C01 is narrowed to exact `UnexpectedModelBehavior`.

### Changed tests

```text
tests/integration/test_pydantic_ai_qualification.py
  - test_q8b_unknown_tool_default_retry: added model_request counter,
    handler counter, exact exception assertions
  - test_q8b_unknown_tool_zero_retries: same corrections
```

### Architecture confirmation

- No production `src/` changes
- No dependency changes
- No PAIM-03 implementation

## 21. PAIM-03 completion record — migration-specific test harness hardening

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `19933320bcacc52f32f5693f962743e7874c113f`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Harness extraction

Created `tests/support/pydantic_ai_runtime.py` (364 lines) as a shared
test-only support module for Pydantic AI blocker-gate tests. The module
extracts all genuinely repeated infrastructure from the three blocker
modules:

| Concept | Previously duplicated in | Now in shared helper |
|---|---|---|
| `AlphaInput`, `BetaInput`, `ToolOutput` schemas | 3 modules | `tests.support.pydantic_ai_runtime` (immutable, safe to reuse) |
| `READ_ALPHA_DEF`, `READ_BETA_DEF`, `WRITE_ALPHA_DEF` | 3 modules | `tests.support.pydantic_ai_runtime` (immutable, safe to reuse) |
| `HandlerCounters` class | 2 modules | `tests.support.pydantic_ai_runtime` |
| `_to_pyd_tool_defs()` | 3 modules | `to_pyd_tool_defs()` |
| `_make_external_toolset()` | 3 modules | `make_external_toolset()` |
| `_make_deferred_handler()` | 3 modules | `make_deferred_handler()` |
| `_make_agent()` | 3 modules | `make_agent()` |
| Fixture factories (counters, registry, executor, contexts, snapshot) | 2 modules | `make_*()` builder functions |

What remained scenario-local:
- All 18 BG test functions with their exact acceptance assertions
- The `test_missing_tool_call_ids` `capturing_handler` (custom ID-capture logic)
- All test-specific `FunctionModel` closures defining scenario-specific model behavior

### Line counts before/after

| File | Before | After | Delta |
|---|---|---|---|
| `test_pydantic_ai_blocker_gate.py` | 979 | 667 | -312 |
| `test_pydantic_ai_blocker_execution.py` | 840 | 556 | -284 |
| `test_pydantic_ai_blocker_limits.py` | 478 | 281 | -197 |
| `test_pydantic_ai_qualification.py` | 483 | 498 | +15 |
| `support/pydantic_ai_runtime.py` | — | 364 | +364 (new) |
| `support/__init__.py` | — | 6 | +6 (new) |

Total reduction in blocker modules: 793 lines.
New support module: 364 lines — well under the 1000-line test hard limit.

### State isolation

The shared helper contains **no module-global mutable runtime state**.
All mutable objects are created fresh per call:

- `HandlerCounters` — fresh via `make_handler_counters()`
- `ToolRegistry` — fresh via `make_tool_registry(counters)`
- `ToolExecutor` — fresh via `make_tool_executor(registry)`
- `Agent` — fresh via `make_agent(model, snapshot)`
- `HandleDeferredToolCalls` — fresh via `make_deferred_handler(...)` (closure-scoped counters)
- Batch state — closure-scoped `batch_count` list per handler instance

Immutable schema classes (`AlphaInput`, `BetaInput`, `ToolOutput`) and
canonical tool-definition constants (`READ_ALPHA_DEF`, `READ_BETA_DEF`,
`WRITE_ALPHA_DEF`) are safe to reuse because they are `BaseModel`/
`ToolDefinition` instances with no mutable shared state.

### Frozen-snapshot semantics preserved

The shared `make_deferred_handler()` still receives the frozen snapshot
as an immutable tuple and resolves tool calls against it at handler time.
A tool registered after snapshot creation (as in BG-06) cannot expand
turn-local authority because the snapshot is captured before handler
creation.

### Canonical duplicate-ID policy preserved

The shared `make_deferred_handler()` preflight uses the exact canonical
rule:

```python
if c.tool_call_id is not None:
    if c.tool_call_id in seen_ids:
        raise RuntimeError(...)
    seen_ids.add(c.tool_call_id)
```

Multiple `None` IDs are not rejected solely for being `None`.

### ToolExecutor-only execution preserved

`make_agent()` creates an `ExternalToolset` with zero Python handler
functions. All successful project execution goes through
`ToolExecutor.execute()` via `make_deferred_handler()`.

### Whole-turn limits preserved

The shared `make_agent()` uses `retries={"tools": 0}`. The shared
`make_deferred_handler()` accepts `reject_second_batch=True` by default.
Tests remain explicit about `UsageLimits(request_limit=N)`.

### HTTP isolation

`test_q8_connection_failure` in `test_pydantic_ai_qualification.py` no
longer attempts a real socket connection to `http://localhost:1/v1`.

**Previous behavior:** `OpenAIProvider(base_url="http://localhost:1/v1", http_client=None)`
— still attempted a real TCP connection to localhost:1.

**New behavior:** A custom `httpx2.AsyncBaseTransport` subclass raises
`httpx2.ConnectError` deterministically without any network I/O:

```python
class _AlwaysFailTransport(httpx2.AsyncBaseTransport):
    async def handle_async_request(self, request):
        raise httpx2.ConnectError("Mocked connection failure")
```

The mock transport is injected through the public `AsyncOpenAI(http_client=...)`
API, which accepts an `httpx2.AsyncClient`. No framework internals are
patched, no `respx` is needed for `httpx2`, and no additional dependency
is required.

**Real socket dependency removed:** yes
**Observable exception type:** `pydantic_ai.exceptions.ModelAPIError`
**Mocked URL:** `https://pydantic-ai-test.invalid/v1`

### Order-dependence evidence

| Run | Module order | Result |
|---|---|---|
| A | qualification → gate → execution → limits → executor | 56 passed |
| B | executor → limits → execution → gate → qualification | 56 passed |
| C | gate → limits → execution → qualification → executor | 56 passed |

All three permutations pass. No order sensitivity was found.

### pytest-randomly decision

```
DO NOT ADD
```

**Reason:** No demonstrated migration-specific need. All three order
permutations pass, fresh-state audit found no leaked global state, and
the canonical full suite passes. Adding `pytest-randomly` would add a
dependency without demonstrated regression value.

**Dependency-file changes:** None. `pyproject.toml` unchanged, `uv.lock`
unchanged.

### Accepted safety evidence

All PAIM-02/C03/C04 safety conclusions remain unchanged:

| Scenario | Result |
|---|---|
| BG-01 READ+READ | PASS |
| BG-02 READ+WRITE / WRITE+READ | PASS |
| BG-03 WRITE+WRITE | PASS |
| BG-04 >4 calls | PASS |
| BG-05 duplicate IDs | PASS |
| BG-06 hidden/frozen | PASS |
| BG-07 unknown tool | PASS |
| BG-08 invalid args | PASS |
| BG-09 single READ | PASS |
| BG-10 single WRITE | PASS |
| BG-11 permission denial | PASS |
| BG-11 missing audit | PASS |
| BG-12 second-round tool | PASS |
| Missing IDs (auto-assignment) | PASS |
| Normal request_limit=2 flow | PASS |
| Third request prevented | PASS |
| Zero semantic retries | PASS |

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Blocker gate tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| Blocker execution tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| Blocker limits tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| Qualification tests | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Tool executor tests | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Ollama smoke (default) | `uv run pytest tests/integration/test_pydantic_ai_ollama_smoke.py -v` | 2 skipped |
| Order A | qualification→gate→execution→limits→executor | 56 passed |
| Order B | executor→limits→execution→gate→qualification | 56 passed |
| Order C | gate→limits→execution→qualification→executor | 56 passed |
| Test-harness contract | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Maintainability contract | `uv run pytest tests/contract/test_maintainability.py -v` | 358 passed |
| Canonical full suite | `uv run pytest` | 4606 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 332 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

Warnings: 1 `DeprecationWarning` from `pydantic_graph/_utils.py` (same as
baseline, associated with `test_bg09_single_read_through_executor`).

### Changed files

```text
tests/support/__init__.py                          (new)
tests/support/pydantic_ai_runtime.py               (new)
tests/integration/test_pydantic_ai_blocker_gate.py
tests/integration/test_pydantic_ai_blocker_execution.py
tests/integration/test_pydantic_ai_blocker_limits.py
tests/integration/test_pydantic_ai_qualification.py
DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

No `src/` changes. No `pyproject.toml` or `uv.lock` changes.
No `tests/conftest.py` changes. No `tests/contract/test_test_harness_policy.py` changes.

### Architecture confirmation

- **No production `src/` changes** — verified
- **No runtime migration** — verified
- **No Toolset production bridge** — verified
- **No DndAgentPolicy** — verified
- **No PAIM-04 implementation** — verified
- **No dependency change** — verified (`pyproject.toml` and `uv.lock` unchanged)

### Finalization

Commit and push will be performed after this record.

### Next task

```text
PAIM-04 — ToolRegistry → framework Toolset → ToolExecutor bridge
```

Do not begin PAIM-04 automatically.


## 19. PAIM-C03 correction record — correct blocker gate to ExternalToolset path

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `aa502278d2f2be7a8498f6b9f03799fdf297560f`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-02 incorrectly stated that `ExternalToolset` and `HandleDeferredToolCalls`
are not available in Pydantic AI 2.39.0. Both are publicly exported and
functional in the installed 2.39.0:

```python
from pydantic_ai.toolsets import ExternalToolset
from pydantic_ai.capabilities import HandleDeferredToolCalls
```

PAIM-02 used `requires_approval=True` + `DeferredToolRequests` as output type
as a workaround. PAIM-C03 re-proves the entire hard blocker gate matrix using
the intended `ExternalToolset` + `HandleDeferredToolCalls` path.

### Correct framework API availability

| API | Available in 2.39.0 |
|---|---|
| `ExternalToolset` | YES — `pydantic_ai.toolsets.ExternalToolset` |
| `HandleDeferredToolCalls` | YES — `pydantic_ai.capabilities.HandleDeferredToolCalls` |
| `DeferredToolRequests.calls` | YES — contains external tool calls |
| `DeferredToolRequests.approvals` | YES — empty for external tools |
| `requests.build_results(calls=...)` | YES — validates ID correspondence |

### Correct architecture path

```text
frozen application tool snapshot
    |
translate to Pydantic AI ToolDefinition[]
    |
ExternalToolset (no Python handler functions)
    |
Agent (output_type=str, retries={"tools": 0})
    |
model requests tools
    |
HandleDeferredToolCalls handler receives COMPLETE batch
    |
application full-batch admission
    |
allowed?
    no ------ fail before ToolExecutor
    yes
        |
ToolExecutor.execute() sequentially
    |
DeferredToolResults (via requests.build_results(calls=...))
    |
agent continues IN THE SAME RUN
    |
terminal model response
```

### Deferred category proof

- `requests.calls` contains all project tool calls
- `requests.approvals` is always empty for external tools
- Results constructed via `requests.build_results(calls=...)` which validates
  that result IDs correspond to pending requests of the correct category
- No project result is supplied through `approvals`

### No framework Python handler

This is a hard invariant proved by the architecture:

- `ExternalToolset` provides schema/metadata only — no `@agent.tool` or
  `@agent.tool_plain` decorators exist in the corrected tests
- The framework-facing definition is schema-only (name, description,
  parameters_json_schema)
- Successful project execution exists only here:
  `HandleDeferredToolCalls` → application admission → `ToolExecutor.execute()`
- All 16 corrected tests use `_make_agent()` which creates an `ExternalToolset`
  with zero Python handler functions

### Corrected hard-gate matrix

| Gate | Result | Model requests | Deferred handler invocations | ToolExecutor invocations | Project handler invocations | Rejection layer |
|---|---|---|---|---|---|---|
| BG-01 READ+READ | PASS | 2 | 1 | 2 | 2 | ToolExecutor (sequential) |
| BG-02 READ+WRITE | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-02 WRITE+READ | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-03 WRITE+WRITE | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-04 >4 | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-05 duplicate ID | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-06 hidden/frozen | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-07 unknown | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-08 invalid args | PASS | 1 | 1 | 1 | 0 | ToolExecutor (ValidationError) |
| BG-09 single READ | PASS | 2 | 1 | 1 | 1 | ToolExecutor |
| BG-10 single WRITE | PASS | 2 | 1 | 1 | 1 | ToolExecutor |
| BG-11 permission denial | PASS | 1 | 1 | 1 | 0 | ToolExecutor (ConflictError) |
| BG-11 missing audit | PASS | 1 | 1 | 1 | 0 | ToolExecutor (ValidationError) |
| BG-12 second-round tool | PASS | 2 | 2 | 1 | 1 | Application policy (no second execute) |

Key differences from PAIM-02 matrix:

- **BG-05/06/07**: Framework catches these before the deferred handler
  (handler_invocations == 0). With `ExternalToolset`, the framework validates
  tool names and duplicate IDs against the toolset definitions before deferring.
- **BG-08**: Framework does NOT validate args with ExternalToolset. Invalid args
  reach the handler, which passes them to ToolExecutor. ToolExecutor validation
  rejects them (handler_invocations == 1, executor_invocations == 1).
- **BG-01/BG-09/BG-10**: Model requests == 2 (model → tools → model stays
  inside one `agent.run_sync()`).
- **BG-11**: ToolExecutor invocation == 1 (the executor was reached; the
  project handler was not executed).

### Whole-turn request budget

| Scenario | request_limit | Model requests | Exception |
|---|---|---|---|
| Normal model→tools→model | 3 | 2 | None (terminal text) |
| Third request prevented | 2 | 2 | `UsageLimitExceeded` |

The complete model→tools→model cycle stays inside **one** `agent.run_sync()`.
`UsageLimits(request_limit=N)` bounds total model requests across the run.

### Missing-ID behavior

With `ExternalToolset`, the framework assigns unique `tool_call_id` values
automatically. When a `FunctionModel` emits duplicate IDs, the framework
rejects them with `UnexpectedModelBehavior` before the deferred handler
executes. No `None` IDs reach the handler in normal operation.

### Public APIs used

Exact Pydantic AI 2.39.0 public APIs used:

- `ExternalToolset(tool_defs)` — `pydantic_ai.toolsets.ExternalToolset`
- `HandleDeferredToolCalls(handler=...)` — `pydantic_ai.capabilities.HandleDeferredToolCalls`
- `ToolDefinition(name, description, parameters_json_schema)` — `pydantic_ai.tools.ToolDefinition`
- `DeferredToolRequests.calls` — external tool calls from model
- `DeferredToolRequests.approvals` — empty for external tools
- `requests.build_results(calls=...)` — validated result construction
- `Agent(model, output_type=str, retries={"tools": 0})`
- `@agent.toolset` decorator for registering `ExternalToolset`
- `agent.run_sync(prompt, capabilities=[...], usage_limits=...)`
- `FunctionModel(function=...)` — deterministic model responses
- `TestModel(call_tools=[...])` — deterministic tool-call scenarios
- `UsageLimits(request_limit=N)`
- `ToolCallPart`, `ModelResponse`, `TextPart`

**Private API usage: none.**

### Corrected gate decision

```
PASS
```

All hard Stage-9 invariants are demonstrably implementable using public
Pydantic AI 2.39.0 APIs:

- `ExternalToolset` provides schema-only tool definitions (no Python handler)
- `HandleDeferredToolCalls` intercepts the complete batch before execution
- Application policy owns batch admission and sequential ToolExecutor execution
- The model→tools→model cycle stays inside one `agent.run_sync()`
- `UsageLimits(request_limit=N)` bounds total model requests

Application-owned batch admission and sequential ToolExecutor execution are
part of the intended project architecture, not a selective custom requirement.

### Changed files

```text
tests/integration/test_pydantic_ai_blocker_gate.py       (rewritten)
tests/integration/test_pydantic_ai_blocker_execution.py   (rewritten)
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

No `src/` changes. No `pyproject.toml` or `uv.lock` changes.

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Blocker gate tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| Blocker execution tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 7 passed |
| Existing qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Tool executor tests | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Full pytest (excl real Ollama) | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Architecture confirmation

- No production runtime migration
- No PAIM-03+ implementation
- No ToolExecutor/FastAgent/AgentLoop changes
- No Vault/domain/storage changes
- No dependency changes
- No `src/` modifications

### Next task

```text
PAIM-03 — Migration-specific test harness hardening
```

Do not begin PAIM-03 automatically.


## 20. PAIM-C04 correction record — complete PAIM-C03 executable evidence

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `0100df9e5a44ff3e47afc99b29ad2649ec8fe15f`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C03 had four documented evidence gaps that PAIM-C04 closes:

1. **Defect A — BG-10 listed as PASS without a dedicated executable test.**
2. **Defect B — Normal whole-turn flow used `request_limit=3` rather than proving success at `request_limit=2`.**
3. **Defect C — Missing-ID auto-assignment was documented without a dedicated executable test.**
4. **Defect D — BG-08 docstring described `UnexpectedModelBehavior` conversion but the actual test raises `ProjectValidationError` directly.**

### Defect A — BG-10 single WRITE through ToolExecutor

Added `test_bg10_single_write_through_executor` to `test_pydantic_ai_blocker_execution.py`.

Uses the same canonical ExternalToolset architecture:

```text
ExternalToolset
HandleDeferredToolCalls
ToolExecutor
UsageLimits(request_limit=2)
retries={"tools": 0}
```

**ExecutionContext:**
- `granted_permission = Permission.WRITE`
- `session_mode = SessionMode.ACTIVE_SESSION`
- `audit = non-None AuditContext`

**Evidence:**

| Metric | Value |
|---|---|
| Model requests | 2 |
| Deferred handler invocations | 1 |
| ToolExecutor invocations | 1 |
| WRITE project handler invocations | 1 |
| Terminal result | `str` |

The framework has no Python tool function capable of calling the WRITE handler directly — all execution goes through `ToolExecutor.execute()`.

### Defect B — Corrected whole-turn request limit

The normal model→tool→model flow now runs with `UsageLimits(request_limit=2)` instead of `3`.

**Required proof (both sides):**

| Scenario | `request_limit` | Model requests | Result |
|---|---|---|---|
| Normal model→tool→model | 2 | 2 | Terminal text, no `UsageLimitExceeded` |
| Attempted third request | 2 | 2 | `UsageLimitExceeded` before request #3 |

Both tests use `FunctionModel` with explicit model-request counters.

### Defect C — Missing tool-call ID behavior

Added `test_missing_tool_call_ids` to `test_pydantic_ai_blocker_execution.py`.

**Evidence:**

```text
IDs omitted from model ToolCallPart: yes (no tool_call_id argument supplied)
IDs reaching deferred handler: non-empty unique strings (e.g. "pyd_ai_...")
Unique: yes
None reached handler: no
```

Pydantic AI 2.39.0 auto-assigns unique `tool_call_id` values when the constructor argument is omitted. When explicitly set to `None`, `None` is preserved.

### Defect D — BG-08 docstring correction

Corrected the BG-08 docstring to match the actual executable behavior:

```text
invalid external-tool args
→ deferred handler receives batch (handler_invocations == 1)
→ ToolExecutor invoked (executor_invocations == 1)
→ project input validation fails
→ project handler NOT invoked (counters.alpha == 0)
→ ProjectValidationError propagates directly
```

No exception behavior was changed — only the documentation was corrected.

### Additional corrections

**Exact model-request counters for BG-01 and BG-09:**

Both tests were converted from `TestModel` to `FunctionModel` with explicit model-request counters. BG-01 and BG-09 now prove `model_requests == 2` with executable evidence rather than inference.

**Duplicate-ID preflight rule:**

The `_make_deferred_handler` preflight logic in both test files was updated to express the canonical application rule:

```python
if c.tool_call_id is not None:
    if c.tool_call_id in seen_ids:
        raise RuntimeError(...)
    seen_ids.add(c.tool_call_id)
```

This correctly allows multiple `None` IDs through without rejecting them merely for both being `None`.

**Maintainability — module decomposition:**

The execution test file exceeded the 1000-line hard limit after additions. The file was decomposed into three topic-oriented modules:

| File | Lines | Responsibility |
|---|---|---|
| `test_pydantic_ai_blocker_gate.py` | 979 | BG-01 through BG-08 (batch admission, mixed, multi-write, size, duplicate ID, hidden, unknown, invalid args) |
| `test_pydantic_ai_blocker_execution.py` | ~848 | BG-09 through BG-12 plus missing-ID and retry (ToolExecutor execution, permission, audit, second round) |
| `test_pydantic_ai_blocker_limits.py` | ~481 | Request-limit defense-in-depth, third-request prevention, zero-retry policy |

### Corrected hard-gate matrix

| Gate | Result | Model requests | Deferred handler invocations | ToolExecutor invocations | Project handler invocations | Rejection layer |
|---|---|---|---|---|---|---|
| BG-01 READ+READ | PASS | **2** | 1 | 2 | 2 | ToolExecutor (sequential) |
| BG-02 READ+WRITE | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-02 WRITE+READ | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-03 WRITE+WRITE | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-04 >4 | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-05 duplicate ID | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-06 hidden/frozen | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-07 unknown | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-08 invalid args | PASS | 1 | 1 | 1 | 0 | ToolExecutor (ProjectValidationError) |
| BG-09 single READ | PASS | **2** | 1 | 1 | 1 | ToolExecutor |
| BG-10 single WRITE | PASS | **2** | 1 | 1 | 1 | ToolExecutor |
| BG-11 permission denial | PASS | 1 | 1 | 1 | 0 | ToolExecutor (ConflictError) |
| BG-11 missing audit | PASS | 1 | 1 | 1 | 0 | ToolExecutor (ValidationError) |
| BG-12 second-round tool | PASS | 2 | 2 | 1 | 1 | Application policy (no second execute) |

Bold values indicate newly executable evidence in PAIM-C04.

### Whole-turn request-budget conclusion

```text
Fast-Agent whole-turn model request budget:
maximum 2
```

Required evidence:

```text
normal 2-request terminal flow with request_limit=2: PASS
third request with request_limit=2: UsageLimitExceeded before request #3
```

### Missing-ID conclusion

Pydantic AI 2.39.0 behavior:

```text
model-supplied IDs: omitted (no tool_call_id argument)
IDs at deferred handler: non-empty unique strings
unique: yes
None reaches application handler: no
```

### Effective PAIM-02 decision

```
PASS
```

PAIM-C04 is an evidence-completion correction, not a new migration architecture. All 18 blocker-gate tests pass with executable evidence.

### Changed files

```text
tests/integration/test_pydantic_ai_blocker_gate.py        (modified)
tests/integration/test_pydantic_ai_blocker_execution.py    (modified)
tests/integration/test_pydantic_ai_blocker_limits.py       (new)
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

No `src/` changes. No `pyproject.toml` or `uv.lock` changes.

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Blocker gate tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| Blocker execution tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| Blocker limits tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| Existing qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Tool executor tests | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Full pytest (excl real Ollama) | `uv run pytest --ignore=tests/integration/test_pydantic_ai_ollama_smoke.py` | 4602 passed, 100 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 330 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Architecture confirmation

- ExternalToolset path retained
- HandleDeferredToolCalls retained
- ToolExecutor-only project execution
- No production `src/` changes
- No dependency changes
- No PAIM-03 implementation

### Next task

```text
PAIM-03 — Migration-specific test harness hardening
```

Do not begin PAIM-03 automatically.
