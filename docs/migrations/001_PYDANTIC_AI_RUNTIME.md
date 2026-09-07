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

- No production runtime changes
- No dependency changes
- No PAIM-02 implementation
- No ToolExecutor/FastAgent/AgentLoop changes
- No Vault/domain/storage changes

### Changed files

```text
tests/integration/test_pydantic_ai_qualification.py
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused qualification tests | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Full pytest (excl real Ollama) | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Evidence quality

The tests now explicitly distinguish:

```text
model invocation count  —  proven by FunctionModel closure counter
tool handler invocation count  —  proven by tool_plain closure counter
```

PAIM-C01 retry evidence is now executable rather than inferred.

### Next task

```text
PAIM-02 — Critical blocker gate
```

## 9. Blocker criteria

A framework behavior is a potential blocker when project invariants cannot be implemented through public/supported APIs without large fragile workaround.

Examples:

- cannot preflight complete mixed tool batch before any execution;
- cannot guarantee ToolExecutor-only side effects;
- framework forces retries that can repeat writes;
- sync/thread behavior breaks trusted storage assumptions and requires domain redesign;
- Ollama integration loses critical tool/structured-output correctness;
- maintaining project semantics requires effectively rewriting the framework run loop internally.

## 10. Escape hatch levels

### Level 1 — supported extension

Use hooks/toolsets/custom model/provider/output validator/public graph API.

### Level 2 — selective custom component

Keep/implement only the problematic component, e.g. native Ollama adapter.

### Level 3 — reject migration

Do not merge runtime branch. Preserve findings and continue custom implementation from `main`.

## 11. Rollback/rejection documentation

If `REJECTED`, record:

- exact Pydantic AI version;
- Ollama version/model where relevant;
- failing invariant;
- minimal reproduction/test;
- framework issue/limitation reference;
- attempted public extension points;
- why custom workaround was rejected;
- implications for future custom runtime design.

Port this conclusion back to `main` as documentation even though runtime changes are not merged.

## 12. No-double-runtime rule

Reference comparison may temporarily instantiate old/new mechanics in tests or spike modules.

Final migration branch before merge must not expose two equal-status production agent runtimes selected by config merely to avoid deleting old code.

The fallback is Git/main, not a permanent feature flag.

## 13. Dependency/upgrade policy

- exact framework candidate chosen by PAIM-01;
- lock exact transitive resolution via `uv.lock`;
- no unrelated dependency upgrades;
- later Pydantic AI upgrade = standalone maintenance task;
- provider/framework release notes and regression tests required.

## 14. Completion order

```text
S9-06 accepted baseline
→ PAIM-00..15
→ outcome
→ S9-07 Stage-9 final historical review
→ Stage 9 DONE
→ Stage 10
```

## 15. PAIM-01 completion record

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `1733d303cffd1dacdd1d7610ce1cab2853094777`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Candidate

| Field | Value |
|---|---|
| Package | `pydantic-ai-slim[openai]` |
| Exact version | `2.39.0` |
| Direct dependency spec | `pydantic-ai-slim[openai]==2.39.0` |
| Resolved Pydantic AI version | `2.39.0` |
| Python version | `3.12.11` |
| OS | `Windows-11-10.0.26200-SP0` |

### Deterministic qualification results

All 14 tests in `tests/integration/test_pydantic_ai_qualification.py` pass.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| Q1 | Import and exact version | PASS | `pydantic_ai.__version__ == "2.39.0"`; Agent, OllamaModel, OpenAIChatModel, TestModel, OpenAIProvider all importable |
| Q2 | Synchronous entry point | PASS | `agent.run_sync("test")` returns `AgentRunResult` with `output` attribute |
| Q3 | Plain text response | PASS | `TestModel(custom_output_text=...)` returns exact expected string |
| Q4 | Structured output | PASS | `TestModel(custom_output_args=...)` with `output_type=QualificationResult` returns validated `BaseModel` instance |
| Q5 | Single function tool | PASS | Tool called exactly once; result appears in output |
| Q6 | Multiple tool calls | PASS | Both tools called in single `ModelResponse`; **sequential** execution observed |
| Q7 | Custom Ollama base URL | PASS | `OllamaProvider(base_url="http://my-ollama:11434/v1")` correctly stores URL; `OpenAIProvider` also works with `/v1` suffix |
| Q8 | Connection failure | PASS | `ModelAPIError` raised for unreachable endpoint |
| Q8 | Unknown tool call | PASS | `UserError` raised for unregistered tool |
| Q8 | Structured output validation failure | PASS | `UnexpectedModelBehavior` raised with "Exceeded maximum output retries" |
| Q8 | Output retry behavior | PASS | Default 1 retry exhausted before raising |

### Real Ollama evidence

| Field | Value |
|---|---|
| Ollama version | `0.33.3` |
| Model | `huihui_ai/qwen3.5-abliterated:35b` |
| Base URL | `http://localhost:11434/v1` |
| Plain response | PASS — `"smoke test ok"` returned correctly |
| Structured output | PASS — `SmokeResult(answer='hello', score=42)` returned and validated |
| Provider used | `OllamaProvider` (official Pydantic AI Ollama provider) |

### Observed framework semantics

| Aspect | Observation |
|---|---|
| Structured-output mode | **ToolOutput** (default when `output_type` is a Pydantic model — framework creates synthetic tool for output schema) |
| Multi-tool execution | **Sequential** — tools executed one after another in main thread |
| Retry behavior | Default 1 output validation retry; automatic transport retries observed in OpenAI client (transparent to application) |
| Public exception classes | `ModelAPIError` (base, extends `RuntimeError`), `ModelHTTPError` (extends `ModelAPIError`), `UserError` (extends `Exception`), `UnexpectedModelBehavior` (extends `RuntimeError`) |
| Ollama endpoint path | `<base_url>/chat/completions` — base URL should include `/v1` for Ollama compatibility |

### Architecture confirmation

- No FastAgent replacement
- No AgentLoop replacement
- No ToolExecutor bridge yet
- No Vault access
- No domain/storage framework dependency
- No PAIM-02 implementation
- Qualification tools are harmless in-memory functions only
- No production source modules modified

### Changed files

```text
pyproject.toml
uv.lock
tests/integration/test_pydantic_ai_qualification.py
tests/integration/test_pydantic_ai_ollama_smoke.py
DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused qualification tests | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 14 passed |
| Real Ollama smoke | `uv run pytest tests/integration/test_pydantic_ai_ollama_smoke.py -v` | 2 passed |
| Relevant existing provider tests | `uv run pytest tests/integration/test_ollama_provider_integration.py` | 8 passed (in full suite) |
| Full pytest (excl real Ollama) | `uv run pytest --ignore=tests/integration/test_pydantic_ai_ollama_smoke.py` | 4575 passed, 100 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 327 files already formatted |
| uv lock consistency | `uv lock --check` | Resolved 51 packages |
| git diff --check | `git diff --check` | No whitespace errors |

### Dependency review

- **Direct dependency added:** `pydantic-ai-slim[openai]==2.39.0`
- **Required transitive additions:** `openai==3.8.0`, `pydantic-graph==2.39.0`, `jiter==0.16.0`, `tiktoken==0.14.0`, `regex==2026.9.3`, `sniffio==1.3.1`, `charset-normalizer==3.5.1`, `httpcore2==2.12.0`, `httpx2==2.12.0`, `requests==2.34.2`, `urllib3==2.7.0`, `truststore==0.10.4`, `griffelib==2.3.0`, `genai-prices==0.1.6`, `logfire-api==5.0.0`, `opentelemetry-api==1.44.0`
- **No unrelated direct upgrades**
- **Existing `httpx>=0.28.1`** resolved to `httpx2==2.12.0` (transitive via openai SDK; coexists with project's httpx)

### Qualification decision

```
QUALIFIED
```

All 8 qualification dimensions pass. The framework provides:
- Deterministic test facilities (`TestModel`) for offline testing
- Public Ollama provider (`OllamaModel` + `OllamaProvider`) with custom base URL support
- Structured output via ToolOutput mode
- Sequential synchronous tool execution
- Predictable exception hierarchy for failure handling
- No architectural boundary violations required

The observed sequential multi-tool execution and default retry behavior are documented for PAIM-02 evaluation but do not block qualification.

### Next task

```text
PAIM-02 — Critical blocker gate
```

## 16. PAIM-C01 correction record

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `49b7fd3391ef165dd94964ac034feb1ad5de9d91`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

Independent review identified several inaccurate claims in the PAIM-01
qualification evidence. PAIM-C01 corrects these without changing the
PAIM-01 qualification outcome.

### Defect A — multi-tool execution semantics

**Original PAIM-01 claim:** `call_order == ["a", "b"]` proves sequential
multi-tool execution; sync tools execute in main thread.

**Correction:** Two concurrently scheduled short functions may append in
model-emission order without being sequential. The claim was insufficient.

**Corrected evidence (A1 — default concurrency):**

Two async tools with a synchronisation barrier (`tool_a` waits until
`tool_b` has started) prove that under the default parallel execution mode
both tools are **concurrently active** (`max_active >= 2`).

```text
test_q6a_default_multi_tool_concurrency: PASS
max_active >= 2  (both tools overlapped)
```

**Corrected evidence (A2 — explicit sequential mode):**

Using `agent.parallel_tool_call_execution_mode("sequential")`, tool_b
starts only after tool_a finishes (`max_active <= 1`).

```text
test_q6b_explicit_sequential_mode: PASS
max_active <= 1  (no overlap)
```

**Corrected evidence (A3 — sync tool thread behavior):**

A synchronous `tool_plain` tool executes on a **worker thread**, not the
calling thread.

```text
test_q6c_sync_tool_worker_thread: PASS
tool_thread_id != calling_thread_id
```

### Defect B — unknown-tool test methodology

**Original PAIM-01 claim:** `TestModel(call_tools=["nonexistent_tool"])`
proves unknown-tool behavior. Documented as `UserError`.

**Correction:** `TestModel` may fail while preparing its deterministic setup
rather than emulating a provider response containing an unknown function
call. Not a valid runtime unknown-tool test.

**Corrected evidence (B1 — default retry behavior):**

Using `FunctionModel` that returns a raw `ModelResponse` with a
`ToolCallPart` for `"nonexistent_tool"`, the framework emits a
`RetryPromptPart` (semantic retry round) before eventually raising
`UnexpectedModelBehavior`. No application tool handler executes.

```text
test_q8b_unknown_tool_default_retry: PASS
UnexpectedModelBehavior raised after retry exhaustion
no application tool handler executed
```

**Corrected evidence (B2 — zero retries):**

With `Agent(retries={"tools": 0})`, the framework raises a terminal
exception without a semantic retry round. No application tool handler
executes.

```text
test_q8b_unknown_tool_zero_retries: PASS
terminal exception raised (UserError or UnexpectedModelBehavior)
no application tool handler executed
```

### Defect C — overstated Ollama endpoint evidence

**Original PAIM-01 claim:** Q7 proves `<base>/chat/completions` endpoint
path.

**Correction:** The test only proves that `OllamaProvider` and
`OpenAIProvider` accept and store a custom `base_url` ending in `/v1`. It
does not independently capture the exact outgoing HTTP request path.

**Corrected evidence:** Claims narrowed to:

```text
OllamaProvider accepts custom base_url ending in /v1
OpenAIProvider with /v1 suffix works for Ollama
Real Ollama smoke succeeds through that configured base URL
```

### Defect D — overstated smoke assertions

**Original PAIM-01 claim:** `"smoke test ok"` returned correctly;
`SmokeResult(answer='hello', score=42)` returned.

**Correction:** The actual test assertions were:

```text
plain: non-empty string output
structured: validated SmokeResult with non-empty answer and positive score
```

Documentation now matches the exact asserted contract.

### Defect E — machine-specific default model

**Original PAIM-01:** Smoke file contained `huihui_ai/qwen3.5-abliterated:35b`
as project-level default.

**Correction:** Removed. Smoke tests now require explicit configuration via
`DND_ASSISTANT_OLLAMA_SMOKE_CONFIG=<base_url>,<model>`. If absent, tests
skip. If malformed, clear test/configuration error.

### Effective corrected PAIM-01 findings

| Aspect | Corrected finding |
|---|---|
| Multi-tool representation | PASS |
| Default multi-tool execution | **parallel/concurrent** |
| Explicit whole-run sequential mode | PASS |
| Sync tool execution | **worker thread** |
| Unknown tool default | semantic retry behavior (RetryPromptPart → exhaustion) |
| Unknown tool retries=0 | terminal failure without retry |
| Ollama base URL | custom base_url accepted and stored |
| Ollama smoke | non-empty text; validated structured output |

### Qualification classification

```
QUALIFIED WITH OBSERVED LIMITATIONS
```

Observed limitations:

- default multi-tool execution is concurrent (not sequential);
- default semantic tool retry is non-zero (retry round before exhaustion);
- sync tools are offloaded to worker threads.

These are not PAIM rejection conditions by themselves because later gates
(PAIM-02, PAIM-10) can potentially constrain them using supported public
APIs (`parallel_tool_call_execution_mode`, `retries` parameter).

### Architecture confirmation

- No production runtime changes
- No ToolExecutor bridge
- No FastAgent/AgentLoop replacement
- No PAIM-02 implementation
- No dependency change
- No Vault/domain/storage changes

### Changed files

```text
tests/integration/test_pydantic_ai_qualification.py
tests/integration/test_pydantic_ai_ollama_smoke.py
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused qualification tests | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Default smoke (no config) | `uv run pytest tests/integration/test_pydantic_ai_ollama_smoke.py -v` | 2 skipped |
| Real Ollama smoke | `uv run pytest tests/integration/test_pydantic_ai_ollama_smoke.py -v` | (explicit config, reported in Final Report) |
| Full pytest (excl real Ollama) | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Next task

```text
PAIM-02 — Critical blocker gate
```

## 18. PAIM-02 completion record — critical blocker gate

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `464d1619b72c7e03baec1a6d5f853402ef382174`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Framework path tested

The tested design used public Pydantic AI 2.39.0 APIs:

```text
frozen app snapshot (tuple[ToolDefinition, ...])
-> @agent.tool_plain(requires_approval=True) for each tool
-> Agent(output_type=str | DeferredToolRequests)
-> agent.run_sync() returns DeferredToolRequests
-> application full-batch preflight (preflight_batch)
-> ToolExecutor sequentially for approved calls
-> DeferredToolResults(calls={id: result}) constructed directly
-> second agent.run_sync(message_history=..., deferred_tool_results=...)
```

Note: `ExternalToolset` and `HandleDeferredToolCalls` are not available in
Pydantic AI 2.39.0. The equivalent public extension point is
`requires_approval=True` on tool definitions combined with
`DeferredToolRequests` as output type.

### Hard-gate matrix

| Gate | Result | Model requests | Deferred batches | ToolExecutor calls | Project handler calls | Rejection/execution layer |
|---|---|---|---|---|---|---|
| BG-01 READ+READ | PASS | 1 | 1 | 2 | 2 | ToolExecutor (sequential) |
| BG-02 READ+WRITE | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-02 WRITE+READ | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-03 WRITE+WRITE | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-04 >4 | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-05 duplicate ID | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-06 hidden/frozen | PASS | 1 | 1 | 0 | 0 | Application preflight |
| BG-07 unknown | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-08 invalid args | PASS | 1 | 0 | 0 | 0 | Framework (UnexpectedModelBehavior) |
| BG-09 single READ | PASS | 1 | 1 | 1 | 1 | ToolExecutor |
| BG-10 single WRITE | PASS | 1 | 1 | 1 | 1 | ToolExecutor |
| BG-11 permission denial | PASS | 1 | 1 | 0 | 0 | ToolExecutor (ConflictError) |
| BG-11 missing audit | PASS | 1 | 1 | 0 | 0 | ToolExecutor (ValidationError) |
| BG-12 second-round tool | PASS | 2 | 2 | 1 | 1 | Application policy (no second execute) |

### Request/retry evidence

- **request_limit:** `UsageLimits(request_limit=1)` allows one model request
  and returns `DeferredToolRequests`. With deferred tools, the framework
  makes one model request per `run_sync` call. The deferred tool mechanism
  does not consume additional model requests within the same `run_sync`.
- **Tool retries:** `retries={"tools": 0}` disables semantic tool retries.
  Unknown tool with zero retries produces `model_requests == 1` and
  `handler_calls == 0`.
- **No semantic retry occurred** in any test (all use `retries={"tools": 0}`).

### Frozen exposure evidence

- Snapshot contains exactly 3 definitions: `read_alpha`, `read_beta`,
  `write_alpha`.
- Live-registry mutation: `hidden_tool` registered after snapshot creation.
- Model-requested hidden tool: `hidden_tool`.
- Rejection layer: application `preflight_batch` (tool not in frozen
  snapshot).
- ToolExecutor/handler counts: 0 for hidden tool, 0 for all project handlers.

### ToolExecutor boundary

Every successful project tool execution in the tested design went through:

```text
ToolExecutor.execute()
```

No framework route could invoke project handlers directly because all tools
use `requires_approval=True`. The framework never executes the handler — it
collects the deferred calls and returns them as `DeferredToolRequests`.
Application code provides results via `DeferredToolResults(calls={id: result})`,
which bypasses framework handler execution entirely.

### Public extension points used

Exact Pydantic AI 2.39.0 public APIs used:

- `Agent(model, output_type=str | DeferredToolRequests, retries={"tools": 0})`
- `@agent.tool_plain(requires_approval=True)`
- `agent.run_sync(prompt)` — returns `DeferredToolRequests`
- `agent.run_sync(prompt, message_history=..., deferred_tool_results=...)`
- `DeferredToolRequests.approvals` — list of `ToolCallPart`
- `DeferredToolResults(calls={id: result}, approvals={})`
- `FunctionModel(function=...)` — for deterministic model responses
- `TestModel(call_tools=[...])` — for deterministic tool-call scenarios
- `UsageLimits(request_limit=N)`
- `ToolCallPart`, `ModelResponse`

**Private API usage: none.**

### Discovered limitations

#### Framework defaults (not blockers)

| Default | Mitigation |
|---|---|
| Concurrent multi-tool execution | Application executes sequentially via ToolExecutor |
| Tool validation before deferral | Framework validates args before deferring; with `retries=0`, invalid args raise `UnexpectedModelBehavior` immediately (fail-closed) |
| Unknown tool raises `UnexpectedModelBehavior` | Correct fail-closed behavior — no handler executes |
| Sync tools on worker threads | PAIM-10 gate owns this evaluation |

#### Application-required policy

1. **All tools must use `requires_approval=True`** — this is the interception
   mechanism that prevents framework handler execution.
2. **Agent must use `output_type=str | DeferredToolRequests`** — this is
   required for the framework to return deferred tool calls instead of
   executing them.
3. **Two-phase execution** — first `run_sync` collects deferred calls,
   application preflights and executes via ToolExecutor, second `run_sync`
   with `message_history` + `deferred_tool_results` completes the agent flow.
4. **Second-round tool rejection** — application policy must detect and
   reject a second `DeferredToolRequests` batch. The framework does not
   enforce this automatically.
5. **`retries={"tools": 0}`** — required to prevent semantic retry rounds
   that could repeat tool calls.

#### Actual blockers

**None.** All hard Stage-9 invariants are demonstrably implementable using
public Pydantic AI 2.39.0 APIs plus application-owned policy.

### Gate decision

```
PASS WITH SELECTIVE CUSTOM REQUIREMENT
```

The selective custom requirement is the application-owned batch preflight
and sequential ToolExecutor execution. This is not a framework limitation —
it is the intended architecture where Pydantic AI handles generic
model/tool-call mechanics and the application owns safety policy.

The `requires_approval=True` + `DeferredToolRequests` pattern is a
documented public extension point, not a private API workaround.

### Changed files

```text
tests/integration/test_pydantic_ai_blocker_gate.py       (new)
tests/integration/test_pydantic_ai_blocker_execution.py   (new)
DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

No `src/` changes. No `pyproject.toml` or `uv.lock` changes.

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Blocker gate tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| Blocker execution tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 7 passed |
| Existing qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Tool executor tests | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Full pytest (excl real Ollama) | `uv run pytest --ignore=tests/integration/test_pydantic_ai_ollama_smoke.py` | 4598 passed, 100 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 329 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

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

Pydantic AI 2.39.0 auto-assigns unique `tool_call_id` values when the constructor argument is omitted. The executable test does **not** prove behavior when `tool_call_id` is explicitly set to `None` — the test only omits the argument. The documented claim that explicit `None` is preserved is removed because it is unsupported by executable evidence.

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


## 22. PAIM-C05 correction record — restore PAIM history and close PAIM-03 evidence

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `2fd1d3f7633205b342678728ba08a5e7a74bd011`
**Parent historical reference SHA:** `19933320bcacc52f32f5693f962743e7874c113f`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-03 was required to append a completion record to the migration history
document. Instead, its commit destructively replaced the document, deleting
approximately 536 lines of historical content including:

- §9 Blocker criteria
- §10 Escape hatch levels
- §11 Rollback/rejection documentation
- §12 No-double-runtime rule
- §13 Dependency/upgrade policy
- §14 Completion order
- §15 PAIM-01 completion record
- §16 PAIM-C01 correction record
- §18 PAIM-02 completion record

PAIM-C05 restores all accidentally deleted content from the parent commit
(`19933320bcacc52f32f5693f962743e7874c113f`) while preserving the valid
PAIM-03 harness implementation and completion record.

### Restoration method

All historical content was restored from the parent commit at
`19933320bcacc52f32f5693f962743e7874c113f`. The PAIM-03 completion record
was retained unchanged. No Git history was rewritten — the restoration is
a forward correction commit.

### PAIM-03 harness preserved

The following PAIM-03 deliverables remain intact:

- `tests/support/__init__.py` — unchanged
- `tests/support/pydantic_ai_runtime.py` — unchanged
- `tests/integration/test_pydantic_ai_blocker_gate.py` — unchanged
- `tests/integration/test_pydantic_ai_blocker_execution.py` — unchanged
- `tests/integration/test_pydantic_ai_blocker_limits.py` — unchanged
- All blocker-gate test assertions — unchanged
- HTTP isolation via custom `httpx2.AsyncBaseTransport` — retained

### Defect C — HTTP request-capture evidence

The `test_q8_connection_failure` test in
`tests/integration/test_pydantic_ai_qualification.py` was enhanced to
capture and assert intercepted request evidence:

- `captured_requests` list collects every `httpx2.Request` passed to the
  transport
- After the expected `ModelAPIError`, the test asserts:
  - `captured_requests` is non-empty
  - Every captured request uses `https` scheme
  - Every captured request targets `pydantic-ai-test.invalid`
  - No request targets `localhost`, `127.0.0.1`, or `::1`
  - The first request URL contains `/chat/completions`
  - The first request uses `POST` method
- The injected `httpx2.AsyncClient` is explicitly closed through the
  `try/finally` lifecycle

### Defect D — unsupported explicit-None claim narrowed

The PAIM-C04 record previously stated:

> When explicitly set to `None`, `None` is preserved.

This claim was not supported by executable evidence — the test only omits
the `tool_call_id` argument rather than explicitly passing `None`. The
claim has been replaced with:

> The executable test does **not** prove behavior when `tool_call_id` is
> explicitly set to `None` — the test only omits the argument. The
> documented claim that explicit `None` is preserved is removed because
> it is unsupported by executable evidence.

The application policy for duplicate non-null ID rejection remains
unchanged and is independently tested.

### Changed files

```text
tests/integration/test_pydantic_ai_qualification.py
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

No `tests/support/` changes. No blocker-test changes. No `src/` changes.
No `pyproject.toml` or `uv.lock` changes.

### Quality gates

(Reported in Final Report)

### Architecture confirmation

- PAIM-03 harness implementation retained intact
- No production `src/` changes
- No runtime migration
- No Toolset production bridge
- No DndAgentPolicy
- No PAIM-04 implementation
- No dependency changes

### Effective migration status after correction

```text
PAIM-03 — DONE
PAIM-C05 — DONE
PAIM-04 — NOT STARTED
```

PAIM-02 effective blocker decision remains: **PASS**

No migration blocker is introduced by PAIM-C05.

### Next task

```text
PAIM-04 — ToolRegistry → framework Toolset → ToolExecutor bridge
```

Do not begin PAIM-04 automatically.

## 23. PAIM-C06 correction record — Close Q8 HTTP client lifecycle evidence

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `f0c118cdc5062764676d833601ee1b84b95bbf11`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C05 incorrectly claimed that the injected `httpx2.AsyncClient` was
explicitly closed in the `test_q8_connection_failure` finally block. The
actual `finally` body checked for a running event loop and then executed
`pass` — no close operation was performed.

PAIM-C06 adds executable explicit closure and asserts the underlying client
is closed.

### Corrected lifecycle behavior

The `finally` block now uses the supported public async API:

```python
openai_client: AsyncOpenAI | None = None
try:
    openai_client = AsyncOpenAI(http_client=mock_client, ...)
    ...
finally:
    if openai_client is not None:
        asyncio.run(openai_client.close())
    else:
        asyncio.run(mock_client.aclose())
```

`AsyncOpenAI.close()` is an async method that closes the underlying HTTP
client. `asyncio.run()` is used because the synchronous pytest test returns
to a context with no running asyncio loop.

### Executable close assertion

After cleanup, the test proves the client is actually closed:

```python
assert openai_client.is_closed(), "AsyncOpenAI client was not closed"
assert mock_client.is_closed, "underlying httpx2 AsyncClient was not closed"
```

Both assertions use the public `is_closed` API:
- `AsyncOpenAI.is_closed()` — method returning `True` after close
- `httpx2.AsyncClient.is_closed` — property returning `True` after close

### Exact path evidence

The captured request path assertion was changed from a substring check to an
exact path match:

```python
# Before:
assert "/chat/completions" in str(first.url)

# After:
assert first.url.path == "/v1/chat/completions"
```

The actual captured path is `/v1/chat/completions` (the base URL
`https://pydantic-ai-test.invalid/v1` combined with the OpenAI SDK's
default `/chat/completions` suffix).

### Lifecycle evidence summary

| Evidence | Value |
|---|---|
| ModelAPIError type | `pydantic_ai.exceptions.ModelAPIError` |
| Captured requests | 1 |
| Method | POST |
| Host | `pydantic-ai-test.invalid` |
| Path | `/v1/chat/completions` |
| Real network | NO (mocked transport) |
| AsyncOpenAI close called | YES (`asyncio.run(openai_client.close())`) |
| AsyncOpenAI is_closed | True |
| Underlying httpx2 AsyncClient is_closed | True |

### Changed files

```text
tests/integration/test_pydantic_ai_qualification.py
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused Q8 test | `uv run pytest tests/integration/test_pydantic_ai_qualification.py::test_q8_connection_failure -v` | 1 passed |
| Full qualification suite | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Blocker gate tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| Blocker execution tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| Blocker limits tests | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| Tool executor tests | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Full pytest | `uv run pytest` | 4606 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 332 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Architecture confirmation

- No `src/` changes
- No dependency changes
- PAIM-03 harness unchanged
- PAIM-04 not started

### Next task

```text
PAIM-04 — ToolRegistry → framework Toolset → ToolExecutor bridge
```

Do not begin PAIM-04 automatically.

## 24. PAIM-04 completion record — ToolRegistry → framework Toolset → ToolExecutor bridge

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `bdebdc28c7091a518f1fc2ae42d88888466b4196`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Production bridge

| Field | Value |
|---|---|
| Module | `src/dnd_assistant/application/pydantic_ai_tool_bridge.py` |
| Public classes | `PydanticAIToolSnapshot`, `PydanticAIToolBridge` |
| Constructor dependency | `ToolRegistry` (one canonical registry) |
| Snapshot representation | `dataclass(frozen=True, slots=True)` with `tuple[ToolDefinition, ...]` |

### Snapshot evidence

| Property | Result |
|---|---|
| Canonical source | `ToolRegistry` |
| Input | Selected `Sequence[ToolPublicDefinition]` |
| Stored authority | `tuple[ToolDefinition, ...]` (project-owned, immutable) |
| Empty snapshot | `names == ()`, `ExternalToolset` with zero tools |
| Live-registry mutation | Old snapshot unchanged; new tool absent from fresh `ExternalToolset` |
| Source-list mutation | Snapshot unchanged after caller clears list |
| Framework-toolset mutation | `toolset_a.tool_defs.clear()` does not affect `toolset_b` from same snapshot |

### Translation evidence

For a representative READ tool (`read_alpha`):

| Field | Framework exposure |
|---|---|
| Project name → framework name | `"read_alpha"` → `"read_alpha"` |
| Description preserved | `"A read-only test tool"` → `"A read-only test tool"` |
| Input schema preserved | `AlphaInput.model_json_schema()` → `parameters_json_schema` |
| Output schema exposed to framework | **No** (stays in project snapshot) |
| Permission metadata as framework authority | **No** (stays in project snapshot) |
| Python handler attached | **No** (schema-only `ExternalToolset`) |

### Malformed snapshot evidence

| Scenario | Result |
|---|---|
| Duplicate name | `ValidationError` — "Duplicate tool name" |
| Unknown name | `ValidationError` — "not registered in the canonical ToolRegistry" |
| Permission mismatch | `ValidationError` — "permission mismatch" |
| Session-mode mismatch | `ValidationError` — "allowed_session_modes mismatch" |
| Description mismatch | `ValidationError` — "description mismatch" |
| Input schema mismatch | `ValidationError` — "input_schema mismatch" |

### Execution evidence

| Scenario | Bridge reached | ToolExecutor authority | Handler calls | Result |
|---|---|---|---|---|
| READ valid | Yes | Yes | 1 | `ToolOutput(result="alpha:hello")` |
| JSON-string object | Yes | Yes | 1 | `ToolOutput(result="alpha:x")` |
| Malformed JSON | Yes | No (fail closed) | 0 | `ValidationError` |
| Non-object JSON | Yes | No (fail closed) | 0 | `ValidationError` |
| Schema-invalid dict | Yes | Yes | 0 | `ValidationError` from ToolExecutor |
| Hidden live tool | Yes | No (fail closed) | 0 | `ValidationError` — "not in the frozen exposure" |
| Unknown tool | Yes | No (fail closed) | 0 | `ValidationError` — "not in the frozen exposure" |
| WRITE valid | Yes | Yes | 1 | `ToolOutput(result="write:test")` |
| READ→WRITE denial | Yes | Yes | 0 | `ConflictError` — "Permission denied" |
| Missing audit | Yes | Yes | 0 | `ValidationError` — "requires a non-None AuditContext" |
| Session denial | Yes | Yes | 0 | `ConflictError` — "Session mode" |

### Exception propagation

| Scenario | Result |
|---|---|
| Handler raises `RuntimeError` | Propagates unchanged |
| Handler returns incompatible output | `ValidationError` from ToolExecutor propagates |

### Scope confirmation

| Component | Status |
|---|---|
| `ToolRegistry` | Unchanged |
| `ToolExecutor` | Unchanged |
| Tool Layer has Pydantic AI dependency | **No** |
| `FastAgent` | Unchanged |
| `AgentLoop` | Unchanged |
| `AgentToolExecutionService` | Unchanged |
| `select_agent_tools` | Unchanged |
| `HandleDeferredToolCalls` production runtime | Not implemented |
| PAIM-05 implementation | Not started |
| `pyproject.toml` | Unchanged |
| `uv.lock` | Unchanged |

### Quality gates

| Gate | Command | Result |
|---|---|---|
| New bridge tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | 27 passed |
| Tool registry | `uv run pytest tests/unit/test_tool_registry.py -v` | 16 passed |
| Tool catalog | `uv run pytest tests/unit/test_tool_catalog.py -v` | 33 passed |
| Tool executor | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Agent tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | 44 passed |
| Agent tool execution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | 29 passed |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | 361 passed |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Canonical full suite | `uv run pytest` | 4636 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 334 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_tool_bridge.py          (new, 351 lines)
tests/unit/test_pydantic_ai_tool_bridge.py                        (new, 783 lines)
DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

### Architecture confirmation

- Tool Layer (`src/dnd_assistant/tools/`) has no Pydantic AI dependency
- `pyproject.toml` and `uv.lock` unchanged
- No `FastAgent`, `AgentLoop`, `select_agent_tools`, or `AgentToolExecutionService` changes
- No `HandleDeferredToolCalls` production runtime
- No PAIM-05 implementation
- No Vault/domain/storage/retrieval/cli changes

### Next task

```text
PAIM-05 — Explicit DndAgentPolicy
```

Do not begin PAIM-05 automatically.


## 25. PAIM-C07 completion record — Harden PAIM-04 bridge authority

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `69d8faa4f07fdfbdcb7f04ffa7abe1b73ebc2ffc`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Defects found

| Defect | Description |
|---|---|
| A — Snapshot not bound to issuing bridge | `execute()` verified only snapshot type and tool name membership. A snapshot from Bridge A could conceptually authorise execution through Bridge B if the tool name existed in Registry B. |
| B — Enum comparison not identity-safe | `_verify_metadata_match` used `set ==` for session-mode and side-effect collections, allowing foreign same-value `StrEnum` impostors and plain strings to pass. |
| C — Missing structural `ToolCallPart` validation | `execute()` type-annotated `tool_call: ToolCallPart` but did not validate runtime type before accessing `.tool_name`. |
| D — Handler counts inferred | PAIM-04 handler-count table was documented from inference rather than executable test assertions. |

### Snapshot provenance mechanism

Each `PydanticAIToolBridge` owns one private opaque token (`self._snapshot_owner_token = object()`).

`freeze()` produces snapshots via `PydanticAIToolSnapshot._create(definitions=..., owner_token=self._snapshot_owner_token)`.

`PydanticAIToolSnapshot._create()` is a `@staticmethod` internal factory. The public dataclass-generated constructor requires an explicit `_owner_token` argument, which callers outside the bridge cannot supply without access to the bridge's private token.

`_validate_snapshot()` proves:
1. Correct runtime type (`isinstance(snapshot, PydanticAIToolSnapshot)`).
2. Owner token identity (`snapshot._owner_token is self._snapshot_owner_token`).
3. No duplicate names in stored definitions.
4. Every stored definition is still the exact canonical registered object (`binding.definition is td`).

### API hardening

The `to_external_toolset()` method moved from `PydanticAIToolSnapshot` to `PydanticAIToolBridge`:

```python
# Before:
snapshot.to_external_toolset()

# After:
bridge.to_external_toolset(snapshot)
```

Both `to_external_toolset()` and `execute()` call `_validate_snapshot()` first, ensuring foreign/cross-bridge snapshots are rejected at both the framework-exposure and execution boundaries.

### Cross-bridge proof

Constructed:
- Registry A: tool `"same_tool"` → handler A (increments `alpha_a`)
- Registry B: tool `"same_tool"` → handler B (increments `alpha_b`)
- Bridge A freezes snapshot with `"same_tool"`
- Bridge B rejects `bridge_b.execute(snapshot_a, ...)` with `ValidationError`
- Handler A calls: 0, Handler B calls: 0

Also proved: `bridge_b.to_external_toolset(snapshot_a)` raises `ValidationError`.

### Forged/manual snapshot proof

A snapshot constructed via `PydanticAIToolSnapshot._create(definitions=..., owner_token=object())` with a random token is rejected by both `execute()` and `to_external_toolset()` with `ValidationError`.

### Tampered-copy proof

`dataclasses.replace(snapshot, definitions=...)` with an extra unregistered definition produces a snapshot whose `_owner_token` still matches the bridge, but whose extra definition fails the canonical-registry identity check. Rejected with `ValidationError`.

### Exact enum evidence

| Scenario | Textual value matches canonical | Runtime type canonical | Result |
|---|---|---|---|
| ForeignPermission.READ | yes | no | `ValidationError` — "not a valid Permission" |
| ForeignSessionMode.ACTIVE_SESSION | yes | no | `ValidationError` — "not the expected enum type" |
| ForeignSideEffect.ENTITY_MUTATION | yes | no | `ValidationError` — "not the expected enum type" |
| Plain string `"read"` | yes | no | `ValidationError` — "not a valid Permission" |

### Structural call evidence

| Input | Exception type | Handler calls |
|---|---|---|
| `object()` as `tool_call` | `ValidationError` — "must be a ToolCallPart" | 0 |
| `object()` as `snapshot` | `ValidationError` — "must be a PydanticAIToolSnapshot" | 0 |
| `object()` as `execution_context` | `ValidationError` — "must be an ExecutionContext" | 0 |

### Metadata drift evidence

| Drift type | Result |
|---|---|
| Side-effect drift (READ tool with ENTITY_MUTATION) | `ValidationError` — "cardinality mismatch" |
| Output-schema drift | `ValidationError` — "output_schema mismatch" |

### Handler-count evidence

The following handler-count assertions are now executable:

| Scenario | Required project-handler count | Asserted |
|---|---|---|
| BR-10 valid READ | exactly 1 | `counters.alpha == 1` |
| BR-11 JSON-object string | exactly 1 | `counters.alpha == 1` |
| BR-12 malformed JSON | 0 | `counters.alpha == 0` |
| BR-13 non-object JSON | 0 | `counters.alpha == 0` |
| BR-14 schema-invalid args | 0 | `counters.alpha == 0` |
| BR-15 hidden live tool | 0 | `counters.alpha == 0, beta == 0, write == 0` |
| BR-16 unknown tool | 0 | `counters.alpha == 0, beta == 0, write == 0` |
| BR-17 valid WRITE | exactly 1 | `counters.write == 1` |
| BR-18 permission denial | 0 | `counters.write == 0` |
| BR-19 missing audit | 0 | `counters.write == 0` |
| BR-20 session denial | 0 | `call_count == 0` |
| handler RuntimeError | exactly 1 | `call_count == 1` |
| output-validation failure | exactly 1 | `call_count == 1` |

### Constructor validation

`PydanticAIToolBridge(registry=object())` raises `TypeError("registry must be a ToolRegistry instance")` immediately.

### Narrowed exception handling

`freeze()` now catches only `NotFoundError` (the expected project-level unknown-tool error) instead of broad `Exception`. Unexpected programming/runtime exceptions remain visible.

### Scope confirmation

| Component | Status |
|---|---|
| `ToolRegistry` | Unchanged |
| `ToolExecutor` | Unchanged |
| Tool Layer has Pydantic AI dependency | **No** |
| `FastAgent` | Unchanged |
| `AgentLoop` | Unchanged |
| `select_agent_tools` | Unchanged |
| `AgentToolExecutionService` | Unchanged |
| `HandleDeferredToolCalls` production runtime | Not implemented |
| PAIM-05 implementation | Not started |
| `pyproject.toml` | Unchanged |
| `uv.lock` | Unchanged |

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_tool_bridge.py          (modified, 520 lines)
tests/unit/test_pydantic_ai_tool_bridge.py                        (modified, 880 lines)
tests/unit/test_pydantic_ai_tool_bridge_authority.py              (new, 545 lines)
DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Bridge tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | 30 passed |
| Authority tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | 14 passed |
| Tool registry | `uv run pytest tests/unit/test_tool_registry.py -v` | 16 passed |
| Tool catalog | `uv run pytest tests/unit/test_tool_catalog.py -v` | 33 passed |
| Tool executor | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Agent tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | 44 passed |
| Agent tool execution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | 29 passed |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | 361 passed |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Canonical full suite | `uv run pytest` | 4655 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 335 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Effective PAIM-04 decision

```
ACCEPTED
```

PAIM-C07 corrects the four documented authority defects in PAIM-04. The original PAIM-04 handler-count table was not executable evidence until C07. All handler counts are now executable assertions.

### Next task

```text
PAIM-05 — Explicit DndAgentPolicy
```

Do not begin PAIM-05 automatically.


## 26. PAIM-C08 completion record — Prevent same-registry snapshot-copy authority expansion

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `26c7238e0a6c3a9f2ebce0fd8aaf40d08a9e1c33`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Defect description

PAIM-C07 correctly prevented cross-bridge snapshots, random-token forged
snapshots, unregistered-definition tampering, foreign enum metadata, and
malformed framework calls. However, an issued snapshot could still be
expanded with another **canonical definition from the same registry** using
`dataclasses.replace()`.

The copied snapshot inherited the legitimate bridge `_owner_token`. Both
definitions were canonical objects from the same registry. Therefore the
C07 checks — owner token identity, unique names, registry lookup,
`binding.definition is td` — all passed.

This let an ordinary copied snapshot expand authority beyond its original
exposure.

### Pre-fix logic

```text
original exposure:  read_alpha (READ)
canonical hidden:   write_alpha (WRITE, registered in same ToolRegistry)
owner token matched: yes (inherited via dataclasses.replace)
canonical identity matched: yes (write_alpha is a canonical registry object)
why C07 accepted:   issuance was not tracked — only structural/identity
                    checks were performed
```

### Issuance mechanism

The fix treats each snapshot as an **issued capability** by object identity.

**PydanticAIToolSnapshot** changes:

```python
@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
```

- `eq=False` ensures equality is identity-based. A `dataclasses.replace()`
  copy is not equal to the original and cannot be accepted by the issuance
  registry.
- `weakref_slot=True` enables weak-reference support so the bridge can
  track snapshots without preventing garbage collection.

**Bridge** changes:

```python
self._issued_snapshots: weakref.WeakSet[PydanticAIToolSnapshot] = weakref.WeakSet()
```

During `freeze()`:

```python
snapshot = PydanticAIToolSnapshot._create(...)
self._issued_snapshots.add(snapshot)
return snapshot
```

During `_validate_snapshot()` — new step 3:

```text
1. runtime type
2. owner token identity
3. exact issued-instance membership (snapshot not in self._issued_snapshots?)
4. duplicate/name integrity
5. canonical definition identity
```

A `WeakSet` is used so completed turn-local snapshots are not retained
indefinitely.

### Exact-instance semantics

With issuance tracking:

```text
original snapshot returned by freeze()   → valid
dataclasses.replace(snapshot)            → new object, NOT issued → invalid
dataclasses.replace(snapshot, defs=...)  → new object, NOT issued → invalid
manually constructed snapshot            → NOT issued → invalid
snapshot from another bridge             → NOT issued by this bridge → invalid
```

The snapshot is a capability, not a serialisable DTO.

### Same-registry copy evidence

| Scenario | Definition canonical in same registry | Owner token preserved | Result | Handler calls |
|---|---|---|---|---|
| Add hidden WRITE | yes | yes | `ValidationError` | 0 read_alpha, 0 write_alpha |
| Replace READ A with READ B | yes | yes | `ValidationError` | 0 read_alpha, 0 read_beta |
| Reorder exposed definitions | yes | yes | `ValidationError` | 0 read_alpha, 0 read_beta |

### Forgery evidence

| Scenario | to_external_toolset | execute |
|---|---|---|
| Random owner token | `ValidationError` — "different bridge" | `ValidationError` — "different bridge" |
| Correct stolen owner token but non-issued object | `ValidationError` — "not issued by this bridge" | `ValidationError` — "not issued by this bridge" |
| Cross-bridge object | `ValidationError` — "different bridge" | `ValidationError` — "different bridge" |

The correct-owner-token test deliberately accesses `bridge._snapshot_owner_token`
(private internals) in a negative test to prove issuance identity is the
stronger boundary. Production callers must not do this.

### Preserved C07 protections

All C07 protections remain intact and are independently tested:

- Foreign-StrEnum impostor rejection (C07-E1 through C07-E4)
- Structural ToolCallPart validation (C07-T1 through C07-T3)
- Metadata drift rejection (side-effect, output-schema)
- Cross-bridge snapshot rejection
- Forged/manual snapshot rejection
- ToolCallPart argument parsing
- ToolExecutor remains sole execution boundary
- No framework handler decorators in bridge source

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_tool_bridge.py          (modified)
tests/unit/test_pydantic_ai_tool_bridge_authority.py              (modified)
DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

No Tool Layer changes. No `pyproject.toml` or `uv.lock` changes.

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Bridge tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | 30 passed |
| Authority tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | 19 passed |
| Tool registry | `uv run pytest tests/unit/test_tool_registry.py -v` | 16 passed |
| Tool catalog | `uv run pytest tests/unit/test_tool_catalog.py -v` | 33 passed |
| Tool executor | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| Agent tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | 44 passed |
| Agent tool execution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | 29 passed |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | 361 passed |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Canonical full suite | `uv run pytest` | 4660 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 335 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Scope confirmation

| Component | Status |
|---|---|
| `ToolRegistry` | Unchanged |
| `ToolExecutor` | Unchanged |
| Tool Layer has Pydantic AI dependency | **No** |
| `FastAgent` | Unchanged |
| `AgentLoop` | Unchanged |
| `select_agent_tools` | Unchanged |
| `AgentToolExecutionService` | Unchanged |
| `HandleDeferredToolCalls` production runtime | Not implemented |
| PAIM-05 implementation | Not started |
| `pyproject.toml` | Unchanged |
| `uv.lock` | Unchanged |

### Effective PAIM-04 decision

```
ACCEPTED
```

C07's tampered-copy proof covered an extra unregistered ToolDefinition.
Independent review found that `dataclasses.replace()` could still add another
canonical ToolDefinition already registered in the same ToolRegistry.
Because the copied snapshot retained the bridge owner token and every added
definition passed canonical identity checks, the copied object could expand
the original exposure authority.

PAIM-C08 closes this by requiring exact bridge-issued snapshot identity.

Effective C07 evidence remains valid for its other corrections.

### Next task

```text
PAIM-05 — Explicit DndAgentPolicy
```

Do not begin PAIM-05 automatically.


## 27. PAIM-05 completion record — Explicit DndAgentPolicy

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `f71a5ebadf1b22db0fa624c4f193b0b62ab893ef`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Policy API

| Field | Value |
|---|---|
| Module | `src/dnd_assistant/application/dnd_agent_policy.py` |
| Public classes | `DndAgentPolicy`, `DndAgentBatchAdmission`, `AdmittedToolCall` |
| Public constants | `MAX_TOOL_CALLS_PER_RUN=4`, `MAX_MODEL_REQUESTS_PER_RUN=2`, `MAX_DEFERRED_TOOL_BATCHES_PER_RUN=1` |
| Run-local mutable state | `_batch_observed: bool` — whether a deferred batch has been observed |
| Constructor | `DndAgentPolicy(*, tool_bridge, snapshot)` — validates snapshot at construction |
| Admission method | `admit_tool_batch(tool_calls: Sequence[ToolCallPart]) -> DndAgentBatchAdmission` |

### Snapshot authority

| Scenario | Result |
|---|---|
| Cross-bridge snapshot | `ValidationError` — "different bridge" |
| Copied snapshot (`dataclasses.replace`) | `ValidationError` — "not issued" |
| Stolen owner token but non-issued snapshot | `ValidationError` — "not issued" |
| Live-registry hidden tool | `ModelError` — "not in the frozen exposure" |

### Admission matrix

| Scenario | Result | Admitted count | Handler calls |
|---|---|---|---|
| POL-01 single READ | admitted | 1 | 0 |
| POL-02 single WRITE | admitted | 1 | 0 |
| POL-03 2 READ | admitted | 2 | 0 |
| POL-04 4 READ | admitted | 4 | 0 |
| POL-05 5 READ | `ModelError` | 0 | 0 |
| POL-06 READ+WRITE | `ModelError` | 0 | 0 |
| POL-07 WRITE+WRITE | `ModelError` | 0 | 0 |
| POL-08 duplicate ID | `ModelError` | 0 | 0 |
| POL-09 distinct IDs | admitted | 2 | 0 |
| POL-10 repeated same READ name | admitted | 2 | 0 |
| POL-11 hidden tool | `ModelError` | 0 | 0 |
| POL-12 unknown tool | `ModelError` | 0 | 0 |

### Second-batch evidence

| Scenario | Result |
|---|---|
| First valid → second valid | `ModelError` — "already been observed" |
| First rejected → second valid | `ModelError` — "already been observed" |
| New policy instance | fresh state — second batch admitted |
| Empty batch → subsequent first real batch | empty: `ValidationError`; real: admitted |

### Separation of responsibilities

| Property | Evidence |
|---|---|
| Policy parses args | **No** — malformed args `"{broken"` admitted by policy |
| Policy executes handlers | **No** — all handler counters are 0 across all 45 tests |
| Policy calls ToolExecutor | **No** — no ToolExecutor import in policy module |
| Single WRITE admitted by policy | **Yes** |
| Same WRITE rejected by ToolExecutor under READ context | `ConflictError` — "Permission denied" |

### Admission immutability

| Property | Assertion |
|---|---|
| `DndAgentBatchAdmission` frozen | `AttributeError` on `.calls.append()` |
| `calls` is tuple | `isinstance(admission.calls, tuple)` |
| `AdmittedToolCall` frozen | `AttributeError` on `.tool_name = ...` |
| Canonical definition identity | `admission.calls[0].definition is snapshot.definitions[0]` |
| Order preservation | batch order `[read_beta, read_alpha]` → positions 0, 1 |

### Scope confirmation

| Component | Status |
|---|---|
| Tool Layer (`src/dnd_assistant/tools/`) | Unchanged |
| `FastAgent` | Unchanged |
| `AgentLoop` | Unchanged |
| `AgentToolSelection` | Unchanged |
| `AgentToolExecutionService` | Unchanged |
| No `Agent` production runtime | Confirmed |
| No `HandleDeferredToolCalls` production runtime | Confirmed |
| No PAIM-06 implementation | Confirmed |
| `pyproject.toml` | Unchanged |
| `uv.lock` | Unchanged |

### Bridge extension

`PydanticAIToolBridge` gained one public method:

```python
def validate_snapshot(self, snapshot: PydanticAIToolSnapshot) -> None:
    self._validate_snapshot(snapshot)
```

The existing C07/C08 `_validate_snapshot` logic (owner token, issued-instance membership, duplicate names, canonical definition identity) is unchanged.

### C08 evidence caveat

The independent-review C08 caveat about `read_beta` handler counters in A2/A3 tests is acknowledged. PAIM-05 does not modify `tests/unit/test_pydantic_ai_tool_bridge_authority.py`. The caveat does not affect PAIM-05 acceptance because the policy's own handler-count evidence uses dedicated `HandlerCounters` instances with exact assertions.

### Tests

| File | Lines | Tests |
|---|---|---|
| `tests/unit/test_dnd_agent_policy.py` | ~895 | 45 |

### Quality gates

| Gate | Command | Result |
|---|---|---|
| New policy tests | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | 45 passed |
| Bridge tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | 30 passed |
| Authority tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | 19 passed |
| Agent loop | `uv run pytest tests/unit/test_agent_loop.py -v` | 36 passed |
| Agent tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | 44 passed |
| Agent tool execution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | 29 passed |
| Tool registry | `uv run pytest tests/unit/test_tool_registry.py -v` | 16 passed |
| Tool catalog | `uv run pytest tests/unit/test_tool_catalog.py -v` | 33 passed |
| Tool executor | `uv run pytest tests/unit/test_tool_executor.py -v` | 21 passed |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | 361 passed |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Canonical full suite | `uv run pytest` | 4708 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 337 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Changed files

```text
src/dnd_assistant/application/dnd_agent_policy.py          (new)
src/dnd_assistant/application/pydantic_ai_tool_bridge.py   (modified)

tests/unit/test_dnd_agent_policy.py                        (new)

DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

No Tool Layer changes. No `pyproject.toml` or `uv.lock` changes.

### Effective PAIM-05 decision

```
ACCEPTED
```

### Next task

```text
PAIM-06 — Context/dependencies integration
```

Do not begin PAIM-06 automatically.


## 28. PAIM-C09 completion record — Seal DndAgentPolicy batch input boundary

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `b0447f29e321136ef8c7a403bb91c08f0c4148fe`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Defect description

The `DndAgentPolicy.admit_tool_batch()` method was type-annotated as
`Sequence[ToolCallPart]` but did not enforce this at runtime. Non-Sequence
inputs such as `object()`, generators, or iterators could leak a Python
`TypeError` from `len()` or `not tool_calls` rather than a project-level
`ValidationError`. The policy also re-read the caller-owned mutable
`Sequence` across several preflight passes, meaning a concurrent or
malicious caller could mutate the batch between admission phases.

### Correction

**Runtime Sequence check** — Before any structural or content validation,
the input is checked against `collections.abc.Sequence`:

```python
if not isinstance(tool_calls, collections.abc.Sequence):
    raise ValidationError(
        f"Tool-call batch must be a Sequence, got {type(tool_calls).__name__}"
    )
```

**Immutable tuple capture** — After the runtime check, the batch is
immediately frozen into a `tuple`:

```python
calls: tuple[ToolCallPart, ...] = tuple(tool_calls)
```

All subsequent preflight passes (`_validate_batch_structure`,
`_reject_duplicate_call_ids`, `_resolve_calls`, size check, WRITE policy)
use only this tuple. The caller-owned mutable sequence is never re-read.

### Structural boundary evidence

| Input | Exception type | State consumed | Subsequent valid batch admitted |
|---|---|---|---|
| `object()` | `ValidationError` — "Sequence" | NO | YES |
| Generator expression | `ValidationError` — "Sequence" | NO | YES |
| `["not_a_tool_call_part"]` | `ValidationError` — "ToolCallPart" | NO | YES |
| Normal list | Admitted | YES | N/A (second batch rejected) |

### State-consumption semantics preserved

| Scenario | First batch result | Second batch result |
|---|---|---|
| Empty `[]` | `ValidationError` — "must not be empty" | Admitted (state not consumed) |
| `object()` | `ValidationError` — "Sequence" | Admitted (state not consumed) |
| Generator | `ValidationError` — "Sequence" | Admitted (state not consumed) |
| Non-ToolCallPart string list | `ValidationError` — "ToolCallPart" | Admitted (state not consumed) |
| 5 calls | `ModelError` — "Maximum 4" | `ModelError` — "already been observed" |
| READ+WRITE | `ModelError` — "WRITE" | `ModelError` — "already been observed" |

### Mutable-list capture evidence

A normal list `[read_alpha, read_beta]` is admitted. After `admit_tool_batch()`
returns, the original list is cleared. The admission result is independent of
caller mutation:

```python
assert len(admission.calls) == 2
assert admission.calls[0].tool_name == "read_alpha"
assert admission.calls[1].tool_name == "read_beta"
```

### POL-11 counter evidence correction

The hidden-tool zero-handler test previously created a disconnected
`counters2 = HandlerCounters()` that was not wired to the hidden handler.
This was replaced with a real invocation counter:

```python
hidden_calls = 0

def hidden_handler(inp, ctx):
    nonlocal hidden_calls
    hidden_calls += 1
    return ToolOutput(result="hidden")

registry.register(hidden_canonical, hidden_handler)
# ... policy rejects hidden_tool ...
assert hidden_calls == 0
```

### Scope confirmation

| Component | Status |
|---|---|
| `src/dnd_assistant/application/dnd_agent_policy.py` | Modified (321 lines, +23) |
| Tool Layer | Unchanged |
| `FastAgent` | Unchanged |
| `AgentLoop` | Unchanged |
| `AgentToolSelection` | Unchanged |
| `AgentToolExecutionService` | Unchanged |
| `PydanticAIToolBridge` | Unchanged |
| No `HandleDeferredToolCalls` production runtime | Confirmed |
| No PAIM-06 implementation | Confirmed |
| `pyproject.toml` | Unchanged |
| `uv.lock` | Unchanged |

### Changed files

```text
src/dnd_assistant/application/dnd_agent_policy.py          (modified)

tests/unit/test_dnd_agent_policy.py                        (modified)

DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

No Tool Layer changes. No `pyproject.toml` or `uv.lock` changes.

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused policy tests | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | 51 passed |
| Bridge tests | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | 30 passed |
| Bridge authority | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | 19 passed |
| Agent loop | `uv run pytest tests/unit/test_agent_loop.py -v` | 36 passed |
| Agent tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | 44 passed |
| Agent tool execution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | 29 passed |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | 366 passed |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Canonical full suite | `uv run pytest` | 4714 passed, 95 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 337 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Effective PAIM-05 decision

```
ACCEPTED
PAIM-C09 — DONE
```

### Next task

```text
PAIM-06 — Context/dependencies integration
```

Do not begin PAIM-06 automatically.
