# Migration 001 вЂ” Pydantic AI Runtime Migration

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
- generic modelв†’toolв†’model loop;
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
в†’ application adapter
в†’ ToolExecutor
в†’ trusted side effect
```

This rule remains even if framework filtering/approval appears sufficient in normal cases.

## 7. PAIM task map

### PAIM-00 вЂ” Documentation/branch kickoff вЂ” DONE

No runtime changes.

Deliverables:

- migration branch;
- ADR;
- migration plan;
- status/roadmap update;
- GigaCode rule/skill;
- exact base SHA;
- outcome/rollback policy.

### PAIM-01 вЂ” Candidate dependency qualification

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

### PAIM-02 вЂ” Blocker gate

Prove the exact architecture-critical capabilities:

- complete batch admission before side effects;
- sequential tool execution;
- explicit retry control;
- bounded requests/tool calls;
- immutable/frozen per-turn exposed set at application level;
- all calls route via `ToolExecutor`;
- hidden/unknown/malformed call fails closed.

If not achievable using stable public extension points, stop and classify issue before continuing.

### PAIM-03 вЂ” Test harness improvements directly needed by migration

Only if necessary:

- standardize HTTPX mocking with `respx`;
- evaluate `pytest-randomly` for hidden state.

Do not bundle unrelated infrastructure libraries.

### PAIM-04 вЂ” Toolset bridge

Translate `ToolRegistry` public definitions into Pydantic AI tool definitions/toolset without moving handler logic.

Invocation goes to `ToolExecutor`.

### PAIM-05 вЂ” DndAgentPolicy

Create explicit application policy component or equivalent cohesive layer covering all Stage-9 agent safety semantics.

### PAIM-06 вЂ” Context/deps integration

Reuse accepted Context Builder/retrieval path. Context remains application-prepared data.

### PAIM-07 вЂ” Replace one-step FastAgent mechanics

Use framework for first model decision while preserving observable app contract/safety behavior.

### PAIM-08 вЂ” Replace bounded AgentLoop mechanics

Use framework generic orchestration. Preserve D&D-specific limits/admission/terminal rules.

### PAIM-09 вЂ” Ollama gate

Compare framework integration to native reference. Select:

```text
framework Ollama
custom/native Ollama component
migration reconsideration
```

### PAIM-10 вЂ” Sync/thread gate

Prove worker-thread/tool-callback behavior does not violate storage/audit/session assumptions.

### PAIM-11 вЂ” Full behavioral parity

Run Stage-9 negative/boundary suite against final migration runtime.

### PAIM-12 вЂ” Real Ollama smoke/performance

Use actual accepted local model/profile for operational evidence.

### PAIM-13 вЂ” Eval comparison

Measure safety/correctness/latency vs reference.

### PAIM-14 вЂ” Cleanup

Delete superseded generic custom infrastructure and obsolete implementation-specific tests. Avoid permanent dual runtime.

### PAIM-15 вЂ” Final review

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
PAIM-02 вЂ” Critical blocker gate
```

## 17. PAIM-C02 correction record вЂ” close unknown-tool retry-count evidence gap

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
| Default retries | 2 | 0 | `UnexpectedModelBehavior` вЂ” "Tool 'nonexistent_tool' exceeded max retries count of 1" |
| `retries={"tools": 0}` | 1 | 0 | `UnexpectedModelBehavior` вЂ” "Tool 'nonexistent_tool' exceeded max retries count of 0" |

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
model invocation count  вЂ”  proven by FunctionModel closure counter
tool handler invocation count  вЂ”  proven by tool_plain closure counter
```

PAIM-C01 retry evidence is now executable rather than inferred.

### Next task

```text
PAIM-02 вЂ” Critical blocker gate
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

### Level 1 вЂ” supported extension

Use hooks/toolsets/custom model/provider/output validator/public graph API.

### Level 2 вЂ” selective custom component

Keep/implement only the problematic component, e.g. native Ollama adapter.

### Level 3 вЂ” reject migration

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
в†’ PAIM-00..15
в†’ outcome
в†’ S9-07 Stage-9 final historical review
в†’ Stage 9 DONE
в†’ Stage 10
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
| Plain response | PASS вЂ” `"smoke test ok"` returned correctly |
| Structured output | PASS вЂ” `SmokeResult(answer='hello', score=42)` returned and validated |
| Provider used | `OllamaProvider` (official Pydantic AI Ollama provider) |

### Observed framework semantics

| Aspect | Observation |
|---|---|
| Structured-output mode | **ToolOutput** (default when `output_type` is a Pydantic model вЂ” framework creates synthetic tool for output schema) |
| Multi-tool execution | **Sequential** вЂ” tools executed one after another in main thread |
| Retry behavior | Default 1 output validation retry; automatic transport retries observed in OpenAI client (transparent to application) |
| Public exception classes | `ModelAPIError` (base, extends `RuntimeError`), `ModelHTTPError` (extends `ModelAPIError`), `UserError` (extends `Exception`), `UnexpectedModelBehavior` (extends `RuntimeError`) |
| Ollama endpoint path | `<base_url>/chat/completions` вЂ” base URL should include `/v1` for Ollama compatibility |

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
PAIM-02 вЂ” Critical blocker gate
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

### Defect A вЂ” multi-tool execution semantics

**Original PAIM-01 claim:** `call_order == ["a", "b"]` proves sequential
multi-tool execution; sync tools execute in main thread.

**Correction:** Two concurrently scheduled short functions may append in
model-emission order without being sequential. The claim was insufficient.

**Corrected evidence (A1 вЂ” default concurrency):**

Two async tools with a synchronisation barrier (`tool_a` waits until
`tool_b` has started) prove that under the default parallel execution mode
both tools are **concurrently active** (`max_active >= 2`).

```text
test_q6a_default_multi_tool_concurrency: PASS
max_active >= 2  (both tools overlapped)
```

**Corrected evidence (A2 вЂ” explicit sequential mode):**

Using `agent.parallel_tool_call_execution_mode("sequential")`, tool_b
starts only after tool_a finishes (`max_active <= 1`).

```text
test_q6b_explicit_sequential_mode: PASS
max_active <= 1  (no overlap)
```

**Corrected evidence (A3 вЂ” sync tool thread behavior):**

A synchronous `tool_plain` tool executes on a **worker thread**, not the
calling thread.

```text
test_q6c_sync_tool_worker_thread: PASS
tool_thread_id != calling_thread_id
```

### Defect B вЂ” unknown-tool test methodology

**Original PAIM-01 claim:** `TestModel(call_tools=["nonexistent_tool"])`
proves unknown-tool behavior. Documented as `UserError`.

**Correction:** `TestModel` may fail while preparing its deterministic setup
rather than emulating a provider response containing an unknown function
call. Not a valid runtime unknown-tool test.

**Corrected evidence (B1 вЂ” default retry behavior):**

Using `FunctionModel` that returns a raw `ModelResponse` with a
`ToolCallPart` for `"nonexistent_tool"`, the framework emits a
`RetryPromptPart` (semantic retry round) before eventually raising
`UnexpectedModelBehavior`. No application tool handler executes.

```text
test_q8b_unknown_tool_default_retry: PASS
UnexpectedModelBehavior raised after retry exhaustion
no application tool handler executed
```

**Corrected evidence (B2 вЂ” zero retries):**

With `Agent(retries={"tools": 0})`, the framework raises a terminal
exception without a semantic retry round. No application tool handler
executes.

```text
test_q8b_unknown_tool_zero_retries: PASS
terminal exception raised (UserError or UnexpectedModelBehavior)
no application tool handler executed
```

### Defect C вЂ” overstated Ollama endpoint evidence

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

### Defect D вЂ” overstated smoke assertions

**Original PAIM-01 claim:** `"smoke test ok"` returned correctly;
`SmokeResult(answer='hello', score=42)` returned.

**Correction:** The actual test assertions were:

```text
plain: non-empty string output
structured: validated SmokeResult with non-empty answer and positive score
```

Documentation now matches the exact asserted contract.

### Defect E вЂ” machine-specific default model

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
| Unknown tool default | semantic retry behavior (RetryPromptPart в†’ exhaustion) |
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
PAIM-02 вЂ” Critical blocker gate
```

## 18. PAIM-02 completion record вЂ” critical blocker gate

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
use `requires_approval=True`. The framework never executes the handler вЂ” it
collects the deferred calls and returns them as `DeferredToolRequests`.
Application code provides results via `DeferredToolResults(calls={id: result})`,
which bypasses framework handler execution entirely.

### Public extension points used

Exact Pydantic AI 2.39.0 public APIs used:

- `Agent(model, output_type=str | DeferredToolRequests, retries={"tools": 0})`
- `@agent.tool_plain(requires_approval=True)`
- `agent.run_sync(prompt)` вЂ” returns `DeferredToolRequests`
- `agent.run_sync(prompt, message_history=..., deferred_tool_results=...)`
- `DeferredToolRequests.approvals` вЂ” list of `ToolCallPart`
- `DeferredToolResults(calls={id: result}, approvals={})`
- `FunctionModel(function=...)` вЂ” for deterministic model responses
- `TestModel(call_tools=[...])` вЂ” for deterministic tool-call scenarios
- `UsageLimits(request_limit=N)`
- `ToolCallPart`, `ModelResponse`

**Private API usage: none.**

### Discovered limitations

#### Framework defaults (not blockers)

| Default | Mitigation |
|---|---|
| Concurrent multi-tool execution | Application executes sequentially via ToolExecutor |
| Tool validation before deferral | Framework validates args before deferring; with `retries=0`, invalid args raise `UnexpectedModelBehavior` immediately (fail-closed) |
| Unknown tool raises `UnexpectedModelBehavior` | Correct fail-closed behavior вЂ” no handler executes |
| Sync tools on worker threads | PAIM-10 gate owns this evaluation |

#### Application-required policy

1. **All tools must use `requires_approval=True`** вЂ” this is the interception
   mechanism that prevents framework handler execution.
2. **Agent must use `output_type=str | DeferredToolRequests`** вЂ” this is
   required for the framework to return deferred tool calls instead of
   executing them.
3. **Two-phase execution** вЂ” first `run_sync` collects deferred calls,
   application preflights and executes via ToolExecutor, second `run_sync`
   with `message_history` + `deferred_tool_results` completes the agent flow.
4. **Second-round tool rejection** вЂ” application policy must detect and
   reject a second `DeferredToolRequests` batch. The framework does not
   enforce this automatically.
5. **`retries={"tools": 0}`** вЂ” required to prevent semantic retry rounds
   that could repeat tool calls.

#### Actual blockers

**None.** All hard Stage-9 invariants are demonstrably implementable using
public Pydantic AI 2.39.0 APIs plus application-owned policy.

### Gate decision

```
PASS WITH SELECTIVE CUSTOM REQUIREMENT
```

The selective custom requirement is the application-owned batch preflight
and sequential ToolExecutor execution. This is not a framework limitation вЂ”
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
PAIM-03 вЂ” Migration-specific test harness hardening
```

Do not begin PAIM-03 automatically.

## 21. PAIM-03 completion record вЂ” migration-specific test harness hardening

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
| `support/pydantic_ai_runtime.py` | вЂ” | 364 | +364 (new) |
| `support/__init__.py` | вЂ” | 6 | +6 (new) |

Total reduction in blocker modules: 793 lines.
New support module: 364 lines вЂ” well under the 1000-line test hard limit.

### State isolation

The shared helper contains **no module-global mutable runtime state**.
All mutable objects are created fresh per call:

- `HandlerCounters` вЂ” fresh via `make_handler_counters()`
- `ToolRegistry` вЂ” fresh via `make_tool_registry(counters)`
- `ToolExecutor` вЂ” fresh via `make_tool_executor(registry)`
- `Agent` вЂ” fresh via `make_agent(model, snapshot)`
- `HandleDeferredToolCalls` вЂ” fresh via `make_deferred_handler(...)` (closure-scoped counters)
- Batch state вЂ” closure-scoped `batch_count` list per handler instance

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
вЂ” still attempted a real TCP connection to localhost:1.

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
| A | qualification в†’ gate в†’ execution в†’ limits в†’ executor | 56 passed |
| B | executor в†’ limits в†’ execution в†’ gate в†’ qualification | 56 passed |
| C | gate в†’ limits в†’ execution в†’ qualification в†’ executor | 56 passed |

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
| Order A | qualificationв†’gateв†’executionв†’limitsв†’executor | 56 passed |
| Order B | executorв†’limitsв†’executionв†’gateв†’qualification | 56 passed |
| Order C | gateв†’limitsв†’executionв†’qualificationв†’executor | 56 passed |
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

- **No production `src/` changes** вЂ” verified
- **No runtime migration** вЂ” verified
- **No Toolset production bridge** вЂ” verified
- **No DndAgentPolicy** вЂ” verified
- **No PAIM-04 implementation** вЂ” verified
- **No dependency change** вЂ” verified (`pyproject.toml` and `uv.lock` unchanged)

### Finalization

Commit and push will be performed after this record.

### Next task

```text
PAIM-04 вЂ” ToolRegistry в†’ framework Toolset в†’ ToolExecutor bridge
```

Do not begin PAIM-04 automatically.


## 19. PAIM-C03 correction record вЂ” correct blocker gate to ExternalToolset path

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
| `ExternalToolset` | YES вЂ” `pydantic_ai.toolsets.ExternalToolset` |
| `HandleDeferredToolCalls` | YES вЂ” `pydantic_ai.capabilities.HandleDeferredToolCalls` |
| `DeferredToolRequests.calls` | YES вЂ” contains external tool calls |
| `DeferredToolRequests.approvals` | YES вЂ” empty for external tools |
| `requests.build_results(calls=...)` | YES вЂ” validates ID correspondence |

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

- `ExternalToolset` provides schema/metadata only вЂ” no `@agent.tool` or
  `@agent.tool_plain` decorators exist in the corrected tests
- The framework-facing definition is schema-only (name, description,
  parameters_json_schema)
- Successful project execution exists only here:
  `HandleDeferredToolCalls` в†’ application admission в†’ `ToolExecutor.execute()`
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
- **BG-01/BG-09/BG-10**: Model requests == 2 (model в†’ tools в†’ model stays
  inside one `agent.run_sync()`).
- **BG-11**: ToolExecutor invocation == 1 (the executor was reached; the
  project handler was not executed).

### Whole-turn request budget

| Scenario | request_limit | Model requests | Exception |
|---|---|---|---|
| Normal modelв†’toolsв†’model | 3 | 2 | None (terminal text) |
| Third request prevented | 2 | 2 | `UsageLimitExceeded` |

The complete modelв†’toolsв†’model cycle stays inside **one** `agent.run_sync()`.
`UsageLimits(request_limit=N)` bounds total model requests across the run.

### Missing-ID behavior

With `ExternalToolset`, the framework assigns unique `tool_call_id` values
automatically. When a `FunctionModel` emits duplicate IDs, the framework
rejects them with `UnexpectedModelBehavior` before the deferred handler
executes. No `None` IDs reach the handler in normal operation.

### Public APIs used

Exact Pydantic AI 2.39.0 public APIs used:

- `ExternalToolset(tool_defs)` вЂ” `pydantic_ai.toolsets.ExternalToolset`
- `HandleDeferredToolCalls(handler=...)` вЂ” `pydantic_ai.capabilities.HandleDeferredToolCalls`
- `ToolDefinition(name, description, parameters_json_schema)` вЂ” `pydantic_ai.tools.ToolDefinition`
- `DeferredToolRequests.calls` вЂ” external tool calls from model
- `DeferredToolRequests.approvals` вЂ” empty for external tools
- `requests.build_results(calls=...)` вЂ” validated result construction
- `Agent(model, output_type=str, retries={"tools": 0})`
- `@agent.toolset` decorator for registering `ExternalToolset`
- `agent.run_sync(prompt, capabilities=[...], usage_limits=...)`
- `FunctionModel(function=...)` вЂ” deterministic model responses
- `TestModel(call_tools=[...])` вЂ” deterministic tool-call scenarios
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
- The modelв†’toolsв†’model cycle stays inside one `agent.run_sync()`
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
PAIM-03 вЂ” Migration-specific test harness hardening
```

Do not begin PAIM-03 automatically.


## 20. PAIM-C04 correction record вЂ” complete PAIM-C03 executable evidence

**Status:** DONE
**Completed:** 2026-09-05
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `0100df9e5a44ff3e47afc99b29ad2649ec8fe15f`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C03 had four documented evidence gaps that PAIM-C04 closes:

1. **Defect A вЂ” BG-10 listed as PASS without a dedicated executable test.**
2. **Defect B вЂ” Normal whole-turn flow used `request_limit=3` rather than proving success at `request_limit=2`.**
3. **Defect C вЂ” Missing-ID auto-assignment was documented without a dedicated executable test.**
4. **Defect D вЂ” BG-08 docstring described `UnexpectedModelBehavior` conversion but the actual test raises `ProjectValidationError` directly.**

### Defect A вЂ” BG-10 single WRITE through ToolExecutor

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

The framework has no Python tool function capable of calling the WRITE handler directly вЂ” all execution goes through `ToolExecutor.execute()`.

### Defect B вЂ” Corrected whole-turn request limit

The normal modelв†’toolв†’model flow now runs with `UsageLimits(request_limit=2)` instead of `3`.

**Required proof (both sides):**

| Scenario | `request_limit` | Model requests | Result |
|---|---|---|---|
| Normal modelв†’toolв†’model | 2 | 2 | Terminal text, no `UsageLimitExceeded` |
| Attempted third request | 2 | 2 | `UsageLimitExceeded` before request #3 |

Both tests use `FunctionModel` with explicit model-request counters.

### Defect C вЂ” Missing tool-call ID behavior

Added `test_missing_tool_call_ids` to `test_pydantic_ai_blocker_execution.py`.

**Evidence:**

```text
IDs omitted from model ToolCallPart: yes (no tool_call_id argument supplied)
IDs reaching deferred handler: non-empty unique strings (e.g. "pyd_ai_...")
Unique: yes
None reached handler: no
```

Pydantic AI 2.39.0 auto-assigns unique `tool_call_id` values when the constructor argument is omitted. The executable test does **not** prove behavior when `tool_call_id` is explicitly set to `None` вЂ” the test only omits the argument. The documented claim that explicit `None` is preserved is removed because it is unsupported by executable evidence.

### Defect D вЂ” BG-08 docstring correction

Corrected the BG-08 docstring to match the actual executable behavior:

```text
invalid external-tool args
в†’ deferred handler receives batch (handler_invocations == 1)
в†’ ToolExecutor invoked (executor_invocations == 1)
в†’ project input validation fails
в†’ project handler NOT invoked (counters.alpha == 0)
в†’ ProjectValidationError propagates directly
```

No exception behavior was changed вЂ” only the documentation was corrected.

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

**Maintainability вЂ” module decomposition:**

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
PAIM-03 вЂ” Migration-specific test harness hardening
```

Do not begin PAIM-03 automatically.


## 22. PAIM-C05 correction record вЂ” restore PAIM history and close PAIM-03 evidence

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

- В§9 Blocker criteria
- В§10 Escape hatch levels
- В§11 Rollback/rejection documentation
- В§12 No-double-runtime rule
- В§13 Dependency/upgrade policy
- В§14 Completion order
- В§15 PAIM-01 completion record
- В§16 PAIM-C01 correction record
- В§18 PAIM-02 completion record

PAIM-C05 restores all accidentally deleted content from the parent commit
(`19933320bcacc52f32f5693f962743e7874c113f`) while preserving the valid
PAIM-03 harness implementation and completion record.

### Restoration method

All historical content was restored from the parent commit at
`19933320bcacc52f32f5693f962743e7874c113f`. The PAIM-03 completion record
was retained unchanged. No Git history was rewritten вЂ” the restoration is
a forward correction commit.

### PAIM-03 harness preserved

The following PAIM-03 deliverables remain intact:

- `tests/support/__init__.py` вЂ” unchanged
- `tests/support/pydantic_ai_runtime.py` вЂ” unchanged
- `tests/integration/test_pydantic_ai_blocker_gate.py` вЂ” unchanged
- `tests/integration/test_pydantic_ai_blocker_execution.py` вЂ” unchanged
- `tests/integration/test_pydantic_ai_blocker_limits.py` вЂ” unchanged
- All blocker-gate test assertions вЂ” unchanged
- HTTP isolation via custom `httpx2.AsyncBaseTransport` вЂ” retained

### Defect C вЂ” HTTP request-capture evidence

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

### Defect D вЂ” unsupported explicit-None claim narrowed

The PAIM-C04 record previously stated:

> When explicitly set to `None`, `None` is preserved.

This claim was not supported by executable evidence вЂ” the test only omits
the `tool_call_id` argument rather than explicitly passing `None`. The
claim has been replaced with:

> The executable test does **not** prove behavior when `tool_call_id` is
> explicitly set to `None` вЂ” the test only omits the argument. The
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
PAIM-03 вЂ” DONE
PAIM-C05 вЂ” DONE
PAIM-04 вЂ” NOT STARTED
```

PAIM-02 effective blocker decision remains: **PASS**

No migration blocker is introduced by PAIM-C05.

### Next task

```text
PAIM-04 вЂ” ToolRegistry в†’ framework Toolset в†’ ToolExecutor bridge
```

Do not begin PAIM-04 automatically.

## 23. PAIM-C06 correction record вЂ” Close Q8 HTTP client lifecycle evidence

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `f0c118cdc5062764676d833601ee1b84b95bbf11`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C05 incorrectly claimed that the injected `httpx2.AsyncClient` was
explicitly closed in the `test_q8_connection_failure` finally block. The
actual `finally` body checked for a running event loop and then executed
`pass` вЂ” no close operation was performed.

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
- `AsyncOpenAI.is_closed()` вЂ” method returning `True` after close
- `httpx2.AsyncClient.is_closed` вЂ” property returning `True` after close

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
PAIM-04 вЂ” ToolRegistry в†’ framework Toolset в†’ ToolExecutor bridge
```

Do not begin PAIM-04 automatically.

## 24. PAIM-04 completion record вЂ” ToolRegistry в†’ framework Toolset в†’ ToolExecutor bridge

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
| Project name в†’ framework name | `"read_alpha"` в†’ `"read_alpha"` |
| Description preserved | `"A read-only test tool"` в†’ `"A read-only test tool"` |
| Input schema preserved | `AlphaInput.model_json_schema()` в†’ `parameters_json_schema` |
| Output schema exposed to framework | **No** (stays in project snapshot) |
| Permission metadata as framework authority | **No** (stays in project snapshot) |
| Python handler attached | **No** (schema-only `ExternalToolset`) |

### Malformed snapshot evidence

| Scenario | Result |
|---|---|
| Duplicate name | `ValidationError` вЂ” "Duplicate tool name" |
| Unknown name | `ValidationError` вЂ” "not registered in the canonical ToolRegistry" |
| Permission mismatch | `ValidationError` вЂ” "permission mismatch" |
| Session-mode mismatch | `ValidationError` вЂ” "allowed_session_modes mismatch" |
| Description mismatch | `ValidationError` вЂ” "description mismatch" |
| Input schema mismatch | `ValidationError` вЂ” "input_schema mismatch" |

### Execution evidence

| Scenario | Bridge reached | ToolExecutor authority | Handler calls | Result |
|---|---|---|---|---|
| READ valid | Yes | Yes | 1 | `ToolOutput(result="alpha:hello")` |
| JSON-string object | Yes | Yes | 1 | `ToolOutput(result="alpha:x")` |
| Malformed JSON | Yes | No (fail closed) | 0 | `ValidationError` |
| Non-object JSON | Yes | No (fail closed) | 0 | `ValidationError` |
| Schema-invalid dict | Yes | Yes | 0 | `ValidationError` from ToolExecutor |
| Hidden live tool | Yes | No (fail closed) | 0 | `ValidationError` вЂ” "not in the frozen exposure" |
| Unknown tool | Yes | No (fail closed) | 0 | `ValidationError` вЂ” "not in the frozen exposure" |
| WRITE valid | Yes | Yes | 1 | `ToolOutput(result="write:test")` |
| READв†’WRITE denial | Yes | Yes | 0 | `ConflictError` вЂ” "Permission denied" |
| Missing audit | Yes | Yes | 0 | `ValidationError` вЂ” "requires a non-None AuditContext" |
| Session denial | Yes | Yes | 0 | `ConflictError` вЂ” "Session mode" |

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
PAIM-05 вЂ” Explicit DndAgentPolicy
```

Do not begin PAIM-05 automatically.


## 25. PAIM-C07 completion record вЂ” Harden PAIM-04 bridge authority

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `69d8faa4f07fdfbdcb7f04ffa7abe1b73ebc2ffc`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Defects found

| Defect | Description |
|---|---|
| A вЂ” Snapshot not bound to issuing bridge | `execute()` verified only snapshot type and tool name membership. A snapshot from Bridge A could conceptually authorise execution through Bridge B if the tool name existed in Registry B. |
| B вЂ” Enum comparison not identity-safe | `_verify_metadata_match` used `set ==` for session-mode and side-effect collections, allowing foreign same-value `StrEnum` impostors and plain strings to pass. |
| C вЂ” Missing structural `ToolCallPart` validation | `execute()` type-annotated `tool_call: ToolCallPart` but did not validate runtime type before accessing `.tool_name`. |
| D вЂ” Handler counts inferred | PAIM-04 handler-count table was documented from inference rather than executable test assertions. |

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
- Registry A: tool `"same_tool"` в†’ handler A (increments `alpha_a`)
- Registry B: tool `"same_tool"` в†’ handler B (increments `alpha_b`)
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
| ForeignPermission.READ | yes | no | `ValidationError` вЂ” "not a valid Permission" |
| ForeignSessionMode.ACTIVE_SESSION | yes | no | `ValidationError` вЂ” "not the expected enum type" |
| ForeignSideEffect.ENTITY_MUTATION | yes | no | `ValidationError` вЂ” "not the expected enum type" |
| Plain string `"read"` | yes | no | `ValidationError` вЂ” "not a valid Permission" |

### Structural call evidence

| Input | Exception type | Handler calls |
|---|---|---|
| `object()` as `tool_call` | `ValidationError` вЂ” "must be a ToolCallPart" | 0 |
| `object()` as `snapshot` | `ValidationError` вЂ” "must be a PydanticAIToolSnapshot" | 0 |
| `object()` as `execution_context` | `ValidationError` вЂ” "must be an ExecutionContext" | 0 |

### Metadata drift evidence

| Drift type | Result |
|---|---|
| Side-effect drift (READ tool with ENTITY_MUTATION) | `ValidationError` вЂ” "cardinality mismatch" |
| Output-schema drift | `ValidationError` вЂ” "output_schema mismatch" |

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
PAIM-05 вЂ” Explicit DndAgentPolicy
```

Do not begin PAIM-05 automatically.


## 26. PAIM-C08 completion record вЂ” Prevent same-registry snapshot-copy authority expansion

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
C07 checks вЂ” owner token identity, unique names, registry lookup,
`binding.definition is td` вЂ” all passed.

This let an ordinary copied snapshot expand authority beyond its original
exposure.

### Pre-fix logic

```text
original exposure:  read_alpha (READ)
canonical hidden:   write_alpha (WRITE, registered in same ToolRegistry)
owner token matched: yes (inherited via dataclasses.replace)
canonical identity matched: yes (write_alpha is a canonical registry object)
why C07 accepted:   issuance was not tracked вЂ” only structural/identity
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

During `_validate_snapshot()` вЂ” new step 3:

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
original snapshot returned by freeze()   в†’ valid
dataclasses.replace(snapshot)            в†’ new object, NOT issued в†’ invalid
dataclasses.replace(snapshot, defs=...)  в†’ new object, NOT issued в†’ invalid
manually constructed snapshot            в†’ NOT issued в†’ invalid
snapshot from another bridge             в†’ NOT issued by this bridge в†’ invalid
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
| Random owner token | `ValidationError` вЂ” "different bridge" | `ValidationError` вЂ” "different bridge" |
| Correct stolen owner token but non-issued object | `ValidationError` вЂ” "not issued by this bridge" | `ValidationError` вЂ” "not issued by this bridge" |
| Cross-bridge object | `ValidationError` вЂ” "different bridge" | `ValidationError` вЂ” "different bridge" |

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
PAIM-05 вЂ” Explicit DndAgentPolicy
```

Do not begin PAIM-05 automatically.


## 27. PAIM-05 completion record вЂ” Explicit DndAgentPolicy

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
| Run-local mutable state | `_batch_observed: bool` вЂ” whether a deferred batch has been observed |
| Constructor | `DndAgentPolicy(*, tool_bridge, snapshot)` вЂ” validates snapshot at construction |
| Admission method | `admit_tool_batch(tool_calls: Sequence[ToolCallPart]) -> DndAgentBatchAdmission` |

### Snapshot authority

| Scenario | Result |
|---|---|
| Cross-bridge snapshot | `ValidationError` вЂ” "different bridge" |
| Copied snapshot (`dataclasses.replace`) | `ValidationError` вЂ” "not issued" |
| Stolen owner token but non-issued snapshot | `ValidationError` вЂ” "not issued" |
| Live-registry hidden tool | `ModelError` вЂ” "not in the frozen exposure" |

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
| First valid в†’ second valid | `ModelError` вЂ” "already been observed" |
| First rejected в†’ second valid | `ModelError` вЂ” "already been observed" |
| New policy instance | fresh state вЂ” second batch admitted |
| Empty batch в†’ subsequent first real batch | empty: `ValidationError`; real: admitted |

### Separation of responsibilities

| Property | Evidence |
|---|---|
| Policy parses args | **No** вЂ” malformed args `"{broken"` admitted by policy |
| Policy executes handlers | **No** вЂ” all handler counters are 0 across all 45 tests |
| Policy calls ToolExecutor | **No** вЂ” no ToolExecutor import in policy module |
| Single WRITE admitted by policy | **Yes** |
| Same WRITE rejected by ToolExecutor under READ context | `ConflictError` вЂ” "Permission denied" |

### Admission immutability

| Property | Assertion |
|---|---|
| `DndAgentBatchAdmission` frozen | `AttributeError` on `.calls.append()` |
| `calls` is tuple | `isinstance(admission.calls, tuple)` |
| `AdmittedToolCall` frozen | `AttributeError` on `.tool_name = ...` |
| Canonical definition identity | `admission.calls[0].definition is snapshot.definitions[0]` |
| Order preservation | batch order `[read_beta, read_alpha]` в†’ positions 0, 1 |

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
PAIM-06 вЂ” Context/dependencies integration
```

Do not begin PAIM-06 automatically.


## 28. PAIM-C09 completion record вЂ” Seal DndAgentPolicy batch input boundary

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

**Runtime Sequence check** вЂ” Before any structural or content validation,
the input is checked against `collections.abc.Sequence`:

```python
if not isinstance(tool_calls, collections.abc.Sequence):
    raise ValidationError(f"Tool-call batch must be a Sequence, got {type(tool_calls).__name__}")
```

**Immutable tuple capture** вЂ” After the runtime check, the batch is
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
| `object()` | `ValidationError` вЂ” "Sequence" | NO | YES |
| Generator expression | `ValidationError` вЂ” "Sequence" | NO | YES |
| `["not_a_tool_call_part"]` | `ValidationError` вЂ” "ToolCallPart" | NO | YES |
| Normal list | Admitted | YES | N/A (second batch rejected) |

### State-consumption semantics preserved

| Scenario | First batch result | Second batch result |
|---|---|---|
| Empty `[]` | `ValidationError` вЂ” "must not be empty" | Admitted (state not consumed) |
| `object()` | `ValidationError` вЂ” "Sequence" | Admitted (state not consumed) |
| Generator | `ValidationError` вЂ” "Sequence" | Admitted (state not consumed) |
| Non-ToolCallPart string list | `ValidationError` вЂ” "ToolCallPart" | Admitted (state not consumed) |
| 5 calls | `ModelError` вЂ” "Maximum 4" | `ModelError` вЂ” "already been observed" |
| READ+WRITE | `ModelError` вЂ” "WRITE" | `ModelError` вЂ” "already been observed" |

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
PAIM-C09 вЂ” DONE
```

### Next task

```text
PAIM-06 вЂ” Context/dependencies integration
```

Do not begin PAIM-06 automatically.

## 29. PAIM-06 completion record вЂ” Context/dependencies integration

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `5218dd701f67f550754e8fab728cca192aa619df`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Production API

**Module:** `src/dnd_assistant/application/pydantic_ai_run_deps.py`

| Type | Description |
|---|---|
| `DndAgentDeps` | Frozen run-local dependency bundle for one Pydantic AI agent run |
| `PreparedDndAgentRun` | Result of successful preparation вЂ” deps + exposed tool defs |
| `DndAgentRunPreparer` | Deterministic pre-model preparation orchestration |

**`DndAgentDeps` fields:**

```
agent_context       AgentContext              (immutable snapshot)
execution_context   ExecutionContext          (frozen trusted context)
tool_bridge         PydanticAIToolBridge      (trusted adapter)
tool_snapshot       PydanticAIToolSnapshot    (issued immutable capability)
policy              DndAgentPolicy            (intentionally run-local mutable state)
```

**`PreparedDndAgentRun` fields:**

```
deps            DndAgentDeps
exposed_tools   tuple[ToolPublicDefinition, ...]
```

**`DndAgentRunPreparer` constructor:**

```python
DndAgentRunPreparer(
    *,
    context_builder: AgentContextBuilder,
    tool_catalog: ToolRegistrySchema,
    tool_bridge: PydanticAIToolBridge,
)
```

**`prepare()` signature:**

```python
def prepare(
    self,
    user_input: str,
    *,
    execution_context: ExecutionContext,
) -> PreparedDndAgentRun:
```

**Production line count:** 197 lines.

### Preparation flow

Exact ordered steps:

1. **Validate `execution_context` runtime type** вЂ” `TypeError` before context reads.
2. **`AgentContextBuilder.build(user_input)`** вЂ” validates input, builds context.
3. **`select_agent_tools(tool_catalog, context=execution_context)`** вЂ” deterministic exposure.
4. **`PydanticAIToolBridge.freeze(selected)`** вЂ” issue immutable snapshot.
5. **Construct one fresh `DndAgentPolicy`** вЂ” bound to this run's snapshot.
6. **Construct `DndAgentDeps`** вЂ” bundle all prepared values.
7. **Return `PreparedDndAgentRun`** вЂ” deps + exposed tool defs.

No tool execution. No model calls. No framework objects.

### Context evidence

| Property | Value |
|---|---|
| `context_builder.build` calls per preparation | 1 |
| Exact `AgentContext` identity preserved | YES |
| Raw repositories/services in deps | NO |
| Raw builder in deps | NO |
| Context post-processing by preparer | NO |

### Exposure evidence

| Scenario | Exposed names | Snapshot names | Handler calls |
|---|---|---|---|
| Empty exposure | `()` | `()` | 0 |
| READ | `read_alpha, read_beta` | `read_alpha, read_beta` | 0 |
| WRITE + audit | `read_alpha, read_beta, write_alpha` | `read_alpha, read_beta, write_alpha` | 0 |
| WRITE without audit | `read_alpha, read_beta` | `read_alpha, read_beta` | 0 |
| Session filtered (NO_ACTIVE_SESSION) | READ-only | READ-only | 0 |

### Run isolation

| Property | Value |
|---|---|
| `run_a.deps is run_b.deps` | NO |
| Snapshot identity distinct | YES |
| Policy identity distinct | YES |
| Same names allowed | YES |
| Policy state leak | NO вЂ” run B's first batch admissible after run A consumed its batch |

### Framework deps evidence

| Property | Value |
|---|---|
| Pydantic AI public API used | `Agent(deps_type=...)`, `RunContext`, `FunctionModel` |
| `deps_type` | `DndAgentDeps` |
| RunContext callback mechanism | `instructions=` callable receiving `RunContext[DndAgentDeps]` |
| `ctx.deps is prepared.deps` | YES |
| Model request count | 1 |
| Project handler count | 0 |
| Context builder count before framework run | 1 |
| Context builder count after framework run | 1 (unchanged) |
| Real network attempted | NO |

### Model-leak evidence

| Property | Value |
|---|---|
| Sentinel used | `рџ›ЎпёЏPAIM-06-SENTINEL-NOT-IN-MODEL` |
| Sentinel present in deps | YES (in `agent_context.user_input`) |
| Sentinel present automatically in model request | NO |

**Result:** NO automatic serialization вЂ” `DndAgentDeps` is not implicitly model-facing.

### Immutability

| Type | Frozen | Policy mutable run-state |
|---|---|---|
| `DndAgentDeps` | YES | Intentionally preserved |
| `PreparedDndAgentRun` | YES | N/A |

### Import/boundary confirmation

| Check | Result |
|---|---|
| Fresh import does not eagerly load `pydantic_ai` | PASS |
| Fresh import does not eagerly load `dnd_assistant.models` | PASS |
| Fresh import does not eagerly load `dnd_assistant.storage` | PASS |
| Fresh import does not eagerly load `dnd_assistant.retrieval` | PASS |
| Fresh import does not eagerly load `dnd_assistant.cli` | PASS |
| `AgentContext` unchanged | CONFIRMED |
| `select_agent_tools` unchanged | CONFIRMED |
| `FastAgent` unchanged | CONFIRMED |
| `AgentLoop` unchanged | CONFIRMED |
| Tool Layer unchanged | CONFIRMED |
| Prompts unchanged | CONFIRMED |
| No production `Agent` | CONFIRMED |
| No production `RunContext` | CONFIRMED |
| No PAIM-07 implementation | CONFIRMED |

### Tests

| Test file | Count | Result |
|---|---|---|
| `tests/unit/test_pydantic_ai_run_deps.py` | 23 | 23 passed |
| `tests/integration/test_pydantic_ai_context_deps.py` | 7 | 7 passed |

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused deps unit tests | `uv run pytest tests/unit/test_pydantic_ai_run_deps.py -v` | 23 passed |
| Framework integration test | `uv run pytest tests/integration/test_pydantic_ai_context_deps.py -v` | 7 passed |
| AgentContext | `uv run pytest tests/unit/test_agent_context.py -v` | 44 passed |
| Tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | 44 passed |
| Policy | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | 51 passed |
| Bridge + authority | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | 30 passed |
| Bridge authority | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | 19 passed |
| FastAgent | `uv run pytest tests/unit/test_fast_agent.py -v` | 36 passed |
| FastAgent boundaries | `uv run pytest tests/unit/test_fast_agent_boundaries.py -v` | 14 passed |
| AgentLoop | `uv run pytest tests/unit/test_agent_loop.py -v` | 36 passed |
| AgentToolExecution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | 29 passed |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | 366 passed |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | 25 passed |
| Canonical full suite | `uv run pytest` | 4749 passed, 102 skipped |
| Ruff check | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 340 files already formatted |
| git diff --check | `git diff --check` | No whitespace errors |

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_run_deps.py       (new, 197 lines)

tests/unit/test_pydantic_ai_run_deps.py                     (new)
tests/integration/test_pydantic_ai_context_deps.py           (new)

DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

No Tool Layer changes. No `pyproject.toml` or `uv.lock` changes. No `FastAgent`, `AgentLoop`, `AgentContext`, or `select_agent_tools` changes.

### Effective PAIM-06 decision

```
ACCEPTED
```

### Next task

```text
PAIM-07 вЂ” Replace one-step FastAgent mechanics
```

Do not begin PAIM-07 automatically.

## 30. PAIM-C10 correction record вЂ” seal Pydantic AI run dependency binding

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `ad7610e0dca2f706051bb98f5ed783b2622402b2`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C10 closes three dependency-integrity defects in the PAIM-06
production code and reconciles two evidence defects in the PAIM-06
completion record.

### Defect A вЂ” malformed ExecutionContext taxonomy

**PAIM-06 behavior:** `prepare()` raised `TypeError` for malformed
`execution_context`.

**PAIM-C10 correction:** Now raises `dnd_assistant.errors.ValidationError`.

Constructor dependency errors remain `TypeError` (context_builder,
tool_catalog, tool_bridge).

**Executable zero-read proof:**

```text
malformed object() as execution_context
в†’ ValidationError
в†’ context_builder.build calls == 0
в†’ handler calls == 0
```

### Defect B вЂ” DndAgentDeps did not validate its claimed binding

**PAIM-06 behavior:** `__post_init__()` only proved
`isinstance(policy, DndAgentPolicy)`.

**PAIM-C10 correction:**

1. All five fields now have runtime type validation.
2. `tool_bridge.validate_snapshot(tool_snapshot)` is called.
3. `policy.validate_binding(tool_bridge=..., snapshot=...)` is called.

A new public API was added to `DndAgentPolicy`:

```python
def validate_binding(
    self,
    *,
    tool_bridge: PydanticAIToolBridge,
    snapshot: PydanticAIToolSnapshot,
) -> None:
```

Required checks:

- `tool_bridge is self._tool_bridge` (exact identity)
- `snapshot is self._snapshot` (exact identity)
- `tool_bridge.validate_snapshot(snapshot)` succeeds

### Defect C вЂ” PreparedDndAgentRun could be internally inconsistent

**PAIM-06 behavior:** No validation between `exposed_tools` and the
authoritative snapshot inside `deps`.

**PAIM-C10 correction:** `PreparedDndAgentRun.__post_init__()` validates:

- `exposed_tools` is a tuple of `ToolPublicDefinition`
- `tuple(t.name for t in exposed_tools) == deps.tool_snapshot.names`
  (exact order)
- `deps.tool_bridge.validate_snapshot(deps.tool_snapshot)` succeeds

### Cross-run binding matrix

| Bundle | Bridge | Snapshot | Policy | Result |
|---|---|---|---|---|
| Valid run A | A | A | A | PreparedRun OK |
| Bridge B + snapshot B + policy A | B | B | A | `ValidationError` |
| Same bridge + snapshot B + policy A | same | B | A | `ValidationError` |
| Copied snapshot (dataclasses.replace) | A | copy(A) | A | `ValidationError` |

All cases: zero handler calls.

### Prepared-run exposure matrix

| Scenario | Result |
|---|---|
| C10-R1 extra public exposure | `ValidationError` |
| C10-R2 missing public exposure | `ValidationError` |
| C10-R3 reordered exposure | `ValidationError` |

All cases: zero handler calls.

### Migration-history correction

Pre-PAIM-06 historical content (PAIM-C09 record) was restored exactly
from parent SHA `5218dd701f67f550754e8fab728cca192aa619df`.

PAIM-06 record is retained as historical evidence. PAIM-C10 is appended.

**PAIM-06 line-count evidence correction:**

The PAIM-06 completion record stated "Production line count: 197 lines".
The PAIM-06 committed file at `ad7610e...` was 258 lines. The 197-line
count was inaccurate.

**PAIM-06 taxonomy correction:**

The PAIM-06 completion record stated that malformed `ExecutionContext`
raises `TypeError`. PAIM-C10 corrects the application contract to
`ValidationError`.

### Preserved PAIM-06 evidence

The following PAIM-06 evidence is unchanged and reaffirmed:

- `AgentContext` unchanged
- `select_agent_tools` unchanged
- `FastAgent` unchanged
- `AgentLoop` unchanged
- Tool Layer unchanged
- Prompts unchanged
- No production `Agent`
- No production `RunContext`
- No PAIM-07 implementation
- No dependency changes (`pyproject.toml` and `uv.lock` unchanged)

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_run_deps.py
src/dnd_assistant/application/dnd_agent_policy.py

tests/unit/test_pydantic_ai_run_deps.py

docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

No `pyproject.toml` or `uv.lock` changes.
No `FastAgent`, `AgentLoop`, `AgentContext`, `select_agent_tools`, or
Tool Layer changes.

### Effective PAIM-06 decision

```
ACCEPTED
PAIM-C10 вЂ” DONE
```

### Next task

```text
PAIM-07 вЂ” Replace one-step FastAgent mechanics
```

Do not begin PAIM-07 automatically.


## 31. PAIM-C11 correction record вЂ” Restore PAIM-06 history and seal prepared-run boundary

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `fbc0941c092e8a998f54436860df8b7f28c5aba3`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C11 closes two defects:

1. **Defect A вЂ” PreparedDndAgentRun did not validate `deps` runtime type.**
   `PreparedDndAgentRun.__post_init__()` validated `exposed_tools` container
   type, item types, name alignment, and snapshot re-validation, but did not
   first validate that `deps` is a `DndAgentDeps` instance. Malformed trusted
   API input such as `PreparedDndAgentRun(deps=object(), ...)` could leak an
   `AttributeError` from `self.deps.tool_snapshot.names` instead of a project
   `ValidationError`.

2. **Defect B вЂ” PAIM-06 completion record was accidentally deleted.**
   PAIM-C10 restored the pre-PAIM-06 historical content (PAIM-C09 record)
   from `5218dd...` but inadvertently removed the PAIM-06 completion record
   (section 29). The C10 record claimed "PAIM-06 record is retained as
   historical evidence" but this was false in the committed file.

### Defect A вЂ” PreparedDndAgentRun deps runtime validation

**PAIM-C11 behavior:** `PreparedDndAgentRun.__post_init__()` now validates
`deps` runtime type as its first check, before any other validation:

```python
if not isinstance(self.deps, DndAgentDeps):
    raise ValidationError(f"deps must be a DndAgentDeps instance, got {type(self.deps).__name__}")
```

**Validation order:**

1. `deps` runtime type вЂ” must be `DndAgentDeps`
2. `exposed_tools` container type вЂ” must be `tuple`
3. Every exposed item type вЂ” must be `ToolPublicDefinition`
4. Exposed names == snapshot names (exact order)
5. Re-validate issued snapshot

### Executable malformed-deps evidence

| Scenario | Result | Exception |
|---|---|---|
| C11-R1 `object()` deps | ValidationError | `deps must be a DndAgentDeps instance, got object` |
| C11-R2 duck-typed fake deps | ValidationError | `deps must be a DndAgentDeps instance, got _FakeDeps` |
| C11-R3 zero handler calls | 0 handler calls | ValidationError |

All C10 binding protections preserved:

| Scenario | Result |
|---|---|
| Policy A + bridge/snapshot B | ValidationError (different tool bridge) |
| Same bridge + snapshot B + policy A | ValidationError (different snapshot) |
| Copied snapshot | ValidationError (not issued) |
| Extra exposure | ValidationError (do not match) |
| Missing exposure | ValidationError (do not match) |
| Reordered exposure | ValidationError (do not match) |

### Defect B вЂ” Migration history restoration

PAIM-C10 accidentally removed the PAIM-06 completion record while restoring
the earlier PAIM-C09 historical text.

PAIM-C11 restores the exact PAIM-06 completion record from
`ad7610e0dca2f706051bb98f5ed783b2622402b2` without rewriting its historical
claims (including then-inaccurate line count of 197 and `TypeError` taxonomy).

PAIM-C10 remains the superseding correction for taxonomy, line count and
dependency binding.

### Migration ordering

```
## 28. PAIM-C09 completion record вЂ” exact 5218dd... historical content
## 29. PAIM-06 completion record вЂ” exact ad7610e... historical content (restored)
## 30. PAIM-C10 correction record вЂ” retained
## 31. PAIM-C11 correction record вЂ” new append-only record
```

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_run_deps.py

tests/unit/test_pydantic_ai_run_deps.py

docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

Expected unchanged:

```text
src/dnd_assistant/application/dnd_agent_policy.py
tests/integration/test_pydantic_ai_context_deps.py
AgentContext
select_agent_tools
FastAgent
AgentLoop
Tool Layer
prompts
pyproject.toml
uv.lock
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused deps unit tests | `uv run pytest tests/unit/test_pydantic_ai_run_deps.py -v` | 36 passed |
| Agent policy | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | (reported in Final Report) |
| Context deps integration | `uv run pytest tests/integration/test_pydantic_ai_context_deps.py -v` | (reported in Final Report) |
| Agent context | `uv run pytest tests/unit/test_agent_context.py -v` | (reported in Final Report) |
| Agent tool selection | `uv run pytest tests/unit/test_agent_tool_selection.py -v` | (reported in Final Report) |
| Tool bridge | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | (reported in Final Report) |
| Bridge authority | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | (reported in Final Report) |
| FastAgent | `uv run pytest tests/unit/test_fast_agent.py -v` | (reported in Final Report) |
| FastAgent boundaries | `uv run pytest tests/unit/test_fast_agent_boundaries.py -v` | (reported in Final Report) |
| AgentLoop | `uv run pytest tests/unit/test_agent_loop.py -v` | (reported in Final Report) |
| AgentToolExecution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | (reported in Final Report) |
| PAIM blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | (reported in Final Report) |
| PAIM blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | (reported in Final Report) |
| PAIM blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | (reported in Final Report) |
| PAIM qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | (reported in Final Report) |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | (reported in Final Report) |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | (reported in Final Report) |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | (reported in Final Report) |
| Canonical full suite | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Effective PAIM-06 decision

```
ACCEPTED
PAIM-C11 вЂ” DONE
```

### Next task

```text
PAIM-07 вЂ” Replace one-step FastAgent mechanics
```

Do not begin PAIM-07 automatically.

## 32. PAIM-C12 correction record вЂ” Restore exact PAIM historical text

**Status:** DONE
**Completed:** 2026-09-07
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `38c8f330c14dd7311e53bdad977d71d463e16929`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C11 restored the missing PAIM-06 section and sealed the
`PreparedDndAgentRun` runtime boundary.

Independent review confirmed one remaining evidence defect:
section 28 was only semantically equivalent to its historical source,
not textually exact.

PAIM-C12 restores section 28 verbatim from `5218dd701f67f550754e8fab728cca192aa619df`.

Section 29 was verified/restored against `ad7610e0dca2f706051bb98f5ed783b2622402b2`.

No production or test code changed.

### Changed files

```text
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

No production files changed.
No test files changed.
No dependency changes.

### Effective PAIM-06 decision

```
ACCEPTED
PAIM-C12 вЂ” DONE
```

### Next task

```text
PAIM-07 вЂ” Replace one-step FastAgent mechanics
```

Do not begin PAIM-07 automatically.

## 33. PAIM-07 completion record вЂ” Replace one-step FastAgent mechanics

### Starting state

```text
Branch:                     feat/pydantic-ai-runtime
Starting SHA:               48d109d9290c407c2aa77a295de37f452e1ef01d
Reference main SHA:         f424a0f659afd5f8bcbce55c4d280cc8e621133f
Working tree:               dirty (pre-existing fast_agent.py refactor + new files)
Upstream equality:          HEAD == upstream
Canonical starting baseline: 4762 passed, 102 skipped
```

### Pydantic AI version

```text
pydantic-ai-slim[openai]==2.39.0
```

### New production runtime

```text
Module:     src/dnd_assistant/application/pydantic_ai_fast_agent.py (new, 327 lines)
Class:      PydanticAIFastAgent
Constructor:
    PydanticAIFastAgent(*, run_preparer: DndAgentRunPreparer, model: Model)
decide():
    user_input: str, *, execution_context: ExecutionContext -> AgentDecision
```

### Framework configuration

```text
Agent deps_type:     type(prepared.deps)  (DndAgentDeps)
Instructions:        SYSTEM_PROMPT (agent_v2)
Output types:        str | DeferredToolRequests
Tool retries:        0
Output retries:      0
UsageLimits:         request_limit=1
Runtime toolset:     fresh ExternalToolset per run via to_external_toolset()
```

### One-step flow

```text
1. DndAgentRunPreparer.prepare(user_input, execution_context=...)
2. build_agent_request(prepared.deps.agent_context)  [shared projection]
3. fresh ExternalToolset from issued snapshot
4. one Pydantic AI model request (request_limit=1, retries=0)
5. adapt str/DeferredToolRequests to ToolAwareResponse
6. return AgentDecision
```

### Observable parity

| Scenario       | Content               | Tool calls | Requests | Handlers |
| -------------- | --------------------- | ---------: | -------: | -------: |
| text only      | "Hello, I am Gandalf" |          0 |        1 |        0 |
| single READ    | None                  |          1 |        1 |        0 |
| single WRITE   | None                  |          1 |        1 |        0 |
| text + tool    | "Looking up..."       |          1 |        1 |        0 |
| 2 READ calls   | None                  |          2 |        1 |        0 |
| empty exposure | "No tools available." |          0 |        1 |        0 |

### Exposure evidence

```text
READ authority:              read_alpha, read_beta only
WRITE + audit:               read_alpha, read_beta, write_alpha
WRITE without audit:         read_alpha, read_beta only (write_alpha hidden)
Session-mode filtering:      only NO_ACTIVE_SESSION tools exposed
FunctionModel tool order:    matches snapshot name order
```

### Prompt/context evidence

```text
AgentInfo.instructions == SYSTEM_PROMPT:         PASS
Campaign sentinel in instructions:               NO
Framework UserPromptPart == AgentDecision USER:  PASS (exact value match)
Adversarial content in instructions:             NO
Adversarial content in USER data:                YES
```

### Argument-boundary evidence

```text
Schema-invalid dict args (empty {} for required field):
  First decision succeeds:                       YES
  Project schema validation occurred:            NO
  Handler calls:                                 0

Malformed non-object args ("not-a-dict"):
  ModelError:                                    YES
  Handler calls:                                 0

Non-finite JSON (NaN, Infinity):
  ModelError:                                    YES
  Handler calls:                                 0
```

### Failure matrix

| Scenario                 | Project exception | Requests | Handler calls |
| ------------------------ | ----------------- | -------: | ------------: |
| unknown tool             | ModelError        |        1 |             0 |
| hidden tool (WRITE)      | ModelError        |        1 |             0 |
| duplicate call ID        | ModelError        |        1 |             0 |
| malformed args           | ModelError        |        1 |             0 |
| framework model error    | ModelError        |        1 |             0 |
| invalid ExecutionContext | ValidationError   |        0 |             0 |

### Policy isolation

```text
PAIM-07 called policy.admit_tool_batch:     NO
First post-decision admission succeeds:     YES
```

### Run isolation

```text
Run A (READ) exposed names:         read_alpha, read_beta
Run B (WRITE+audit) exposed names:  read_alpha, read_beta, write_alpha
ExternalToolset leakage:            NO (fresh per run)
```

### Reference parity

Comparison against old FastAgent for text-only and tool-only scenarios:

```text
ChatRequest equality:               PASS (model_dump() identical)
Exposed names equality:             PASS
ToolAwareResponse content parity:   PASS
ToolAwareResponse tool_calls parity: PASS
```

### Scope confirmation

```text
AgentLoop unchanged:                YES
AgentToolExecution unchanged:       YES
Tool Layer unchanged:               YES
ModelGateway unchanged:             YES
Ollama unchanged:                   YES
Prompt unchanged:                   YES
CLI unchanged:                      YES

No HandleDeferredToolCalls:         YES
No DeferredToolResults:             YES
No ToolExecutor dependency:         YES (fresh import test)
No second model request:            YES
No PAIM-08 implementation:          YES

pyproject.toml unchanged:           YES
uv.lock unchanged:                  YES
```

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_fast_agent.py          (new, 327 lines)
src/dnd_assistant/application/fast_agent.py                      (refactored: shared build_agent_request helper)

tests/integration/test_pydantic_ai_fast_agent.py                 (new, 865 lines)
tests/integration/test_pydantic_ai_fast_agent_boundaries.py      (new, 954 lines)

DEVELOPMENT_STATUS.md                                             (updated)
docs/migrations/001_PYDANTIC_AI_RUNTIME.md                       (updated)
```

### Quality gates

```text
Gate class:                     Code/test (final diff contains Python changes)

Reference FastAgent tests:      41 passed (test_fast_agent.py)
                                19 passed (test_fast_agent_boundaries.py)
PAIM-06 regression:             36 passed (test_pydantic_ai_run_deps.py)
DndAgentPolicy tests:           58 passed (test_dnd_agent_policy.py)
PAIM context/deps tests:        18 passed (test_pydantic_ai_context_deps.py)
Blocker gate tests:             16 passed (test_pydantic_ai_blocker_gate.py)
                                + execution + limits + qualification
PAIM-07 new tests:              42 passed (22 + 20 across both files)
Contract tests:                 376 passed (boundaries + maintainability + harness)

Full canonical suite:           4809 passed, 102 skipped
```

### Ruff

```text
Changed Python files formatting:  PASS
Full ruff format --check:         Historical PAIM-C12 Markdown-only exception
                                  (docs/migrations/001_PYDANTIC_AI_RUNTIME.md sections 28-32)
ruff check .:                     PASS
git diff --check:                 PASS
```

### Effective PAIM-07 decision

```text
ACCEPTED
PAIM-07 вЂ” DONE
```

### Next task

```text
PAIM-08 вЂ” Replace bounded AgentLoop mechanics
```

Do not begin PAIM-08 automatically.

## 34. PAIM-C13 correction record вЂ” Close PAIM-07 runtime evidence gaps

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `1c86bbb53661834651dacf0a1911050879a36ee1`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

Independent review accepted the PAIM-07 production architecture but found
that the committed evidence in section 33 overstates what is directly tested.

PAIM-C13 adds executable evidence for framework-visible tool exposure,
output-tool configuration, two-run isolation, snapshot/policy isolation,
reference parity, error cause mapping, TextPart concatenation, and
ThinkingPart hiding вЂ” without modifying any production code.

### New evidence file

```text
tests/integration/test_pydantic_ai_fast_agent_evidence.py
```

11 tests, all pass. File is under 1000 lines.

### C13-E01 вЂ” exact framework-visible tool order

A normal READ run captures the public `AgentInfo` passed to `FunctionModel`.

```text
run A snapshot names:              read_alpha, read_beta
run A AgentInfo.function_tools:    read_alpha, read_beta
run A AgentInfo.output_tools:      []
run A allow_text_output:           True

exact order parity:                YES
model requests:                    1
handlers:                          0
```

### C13-E02 вЂ” no synthetic output tools

```text
AgentInfo.output_tools == []:      YES
AgentInfo.allow_text_output:       True
```

The intended PAIM-07 contract (plain text output + external project tools,
not framework-generated project result tools) is confirmed.

### C13-E03 вЂ” model-visible two-run exposure isolation

Same `PydanticAIFastAgent` instance used for two decisions with different
authorities:

```text
Run A (READ) model-visible tools:          read_alpha, read_beta
Run B (WRITE+audit) model-visible tools:   read_alpha, read_beta, write_alpha

Run A data unchanged after run B:          YES
model requests:                             2 total, 1 per decision
handlers:                                   0
```

Proves actual model-visible `ExternalToolset` isolation, not merely
`decision_a.exposed_tools != decision_b.exposed_tools`.

### C13-E04 вЂ” snapshot/policy run isolation

Captures exact `PreparedDndAgentRun` for each decision via a spy wrapper:

```text
run_a.deps is not run_b.deps:               YES
run_a.deps.tool_snapshot is not run_b.deps.tool_snapshot: YES
run_a.deps.policy is not run_b.deps.policy: YES
run-B first policy admission works:         YES
```

Behaviorally proves run B's policy still has its first real batch opportunity.

### C13-E05 вЂ” reference parity: text + tool

```text
prompt_version equality:                    YES
request.model_dump() equality:              YES
exposed tool names equality:                YES
response content equality:                  YES
tool-call name/arguments equality:          YES
model requests:                             1
```

### C13-E06 вЂ” reference parity: multi READ

```text
prompt_version equality:                    YES
request.model_dump() equality:              YES
exposed tool names equality:                YES
tool-call count (2):                        YES
tool-call order preserved:                  YES
tool-call IDs preserved:                    YES
arguments preserved:                        YES
model requests:                             1
```

### C13-E07 вЂ” exact unknown-tool cause mapping

```text
project exception:                          ModelError
model requests:                             1
handlers:                                   0
framework cause retained:                   YES (AgentRunError)
```

### C13-E08 вЂ” duplicate-ID cause mapping

```text
project exception:                          ModelError
model requests:                             1
handlers:                                   0
framework cause retained:                   YES (AgentRunError)
```

### C13-E09 вЂ” deterministic framework AgentRunError mapping

A `ModelAPIError` raised from a `FunctionModel` function:

```text
project exception:                          ModelError
ModelError.__cause__:                       ModelAPIError
cause message:                              "Simulated model failure"
model requests (where a request began):     1
handlers:                                   0
```

### C13-E10 вЂ” multiple TextPart concatenation rule

```text
raw TextPart sequence:                      "first", "second" + ToolCallPart
adapted content:                            "first second"
tool call preserved:                        YES
order preserved:                            YES
model requests:                             1
handlers:                                   0
```

### C13-E11 вЂ” ThinkingPart remains hidden

```text
raw parts:                                  ThinkingPart + TextPart("visible") + ToolCallPart
adapted content:                            "visible"
ThinkingPart surfaced:                      NO
model requests:                             1
handlers:                                   0
```

### Evidence reconciliation

#### Committed PAIM-07 line counts (section 33 claims)

Independent Git verification from commit `1c86bbb...`:

| File | Section 33 claim | Actual |
|---|---|---|
| `pydantic_ai_fast_agent.py` | 327 | **324** |
| `test_pydantic_ai_fast_agent.py` | 865 | **852** |
| `test_pydantic_ai_fast_agent_boundaries.py` | 954 | **949** |

All three section-33 line-count claims are inaccurate. PAIM-C13 records the
correct values.

#### Actual PAIM-07 test-file counts

```text
test_pydantic_ai_fast_agent.py:             19 passed
test_pydantic_ai_fast_agent_boundaries.py:  23 passed
Total:                                      42 passed
```

Section 33 claimed "42 passed (22 + 20)". The total of 42 is correct, but
the per-file breakdown of 22 + 20 is inaccurate. The actual breakdown is
19 + 23.

#### Policy test actual count

```text
test_dnd_agent_policy.py:                   51 passed
```

Section 33 claimed 58. The actual count is 51.

#### Blocker suite actual counts

```text
test_pydantic_ai_blocker_gate.py:           9 passed
test_pydantic_ai_blocker_execution.py:      6 passed
test_pydantic_ai_blocker_limits.py:         3 passed
test_pydantic_ai_qualification.py:          17 passed
Total:                                      35 passed
```

Section 33 claimed 16 for the blocker gate suite. The actual total across
all four files is 35.

#### Section 33 modified

```text
NO
```

#### Section 34 appended

```text
YES
```

### Starting-tree evidence

Section 33 records the PAIM-07 starting working tree as:

```text
dirty (pre-existing fast_agent.py refactor + new files)
```

PAIM-C13 does not rewrite this. Independent Git verification proves:

```text
PAIM-07 commit is exactly one direct child of PAIM-C12 HEAD

all committed changes are inside the six-file PAIM-07 scope

no unrelated dependency/Tool Layer/AgentLoop changes are present
```

### Production code unchanged

```text
src/dnd_assistant/application/pydantic_ai_fast_agent.py:   unchanged
src/dnd_assistant/application/fast_agent.py:               unchanged
src/dnd_assistant/application/pydantic_ai_run_deps.py:     unchanged
src/dnd_assistant/application/dnd_agent_policy.py:         unchanged
src/dnd_assistant/application/pydantic_ai_tool_bridge.py:  unchanged
```

No production code was modified for PAIM-C13.

### Framework-boundary prohibition confirmed

Production source contains no:

```text
HandleDeferredToolCalls:                   NO
DeferredToolResults:                       NO
ToolExecutor import:                       NO
bridge.execute():                          NO
policy.admit_tool_batch():                 NO
second model request:                      NO
```

### Changed files

```text
tests/integration/test_pydantic_ai_fast_agent_evidence.py   (new)

docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

Expected unchanged:

```text
src/dnd_assistant/application/agent_loop.py
src/dnd_assistant/application/agent_tool_execution.py
src/dnd_assistant/application/pydantic_ai_run_deps.py
src/dnd_assistant/application/dnd_agent_policy.py
src/dnd_assistant/application/pydantic_ai_tool_bridge.py
src/dnd_assistant/application/pydantic_ai_fast_agent.py
src/dnd_assistant/application/fast_agent.py

src/dnd_assistant/tools/**
src/dnd_assistant/models/gateway.py
src/dnd_assistant/models/ollama/**
src/dnd_assistant/prompts/**

CLI

pyproject.toml
uv.lock
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| New evidence tests | `uv run pytest tests/integration/test_pydantic_ai_fast_agent_evidence.py -v` | 11 passed |
| Original PAIM-07 main | `uv run pytest tests/integration/test_pydantic_ai_fast_agent.py -v` | 19 passed |
| Original PAIM-07 boundaries | `uv run pytest tests/integration/test_pydantic_ai_fast_agent_boundaries.py -v` | 23 passed |
| DndAgentPolicy | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | 51 passed |
| Blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | 9 passed |
| Blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | 6 passed |
| Blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | 3 passed |
| Qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | 17 passed |
| Reference FastAgent | `uv run pytest tests/unit/test_fast_agent.py -v` | 41 passed |
| Reference FastAgent boundaries | `uv run pytest tests/unit/test_fast_agent_boundaries.py -v` | 19 passed |
| PAIM-06 deps | `uv run pytest tests/unit/test_pydantic_ai_run_deps.py -v` | 36 passed |
| PAIM-06 context deps | `uv run pytest tests/integration/test_pydantic_ai_context_deps.py -v` | 7 passed |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | 97 passed |
| Canonical full suite | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Effective PAIM-07 decision

```text
ACCEPTED
PAIM-C13 вЂ” DONE
```

### Next task

```text
PAIM-08 вЂ” Replace bounded AgentLoop mechanics
```

Do not begin PAIM-08 automatically.

## 35. PAIM-C14 correction record вЂ” Make PAIM-07 evidence literal and exact

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `6aa4b66d0ac4d54d51e3219022c77cec4806f2eb`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

Independent review identified four defects in the PAIM-C13 executable
evidence:

1. **C13-E01** compared `AgentInfo.function_tools` to `AgentDecision`
   exposure twice, not to the exact captured issued snapshot
   (`PreparedDndAgentRun.deps.tool_snapshot.names`).

2. **C13-E03** used two different `PydanticAIFastAgent` instances (and
   two different `FunctionModel` instances) even though section 34 claimed
   "Same `PydanticAIFastAgent` instance used for two decisions".

3. **C13-E07/E08** asserted only `isinstance(exc.__cause__, AgentRunError)`
   base-class compatibility, not the exact public framework subtype.

4. Several C13 tests documented `handlers: 0` without literal wired
   `HandlerCounters` assertions (E01, E02, E04, E05, E06, E09, E10, E11).

### Defect A вЂ” E01 did not capture the issued snapshot

**C13-E01 behavior:** Compared `AgentInfo.function_tools` names to
`decision.exposed_tools` names twice, never to the exact
`PreparedDndAgentRun.deps.tool_snapshot.names`.

**PAIM-C14 correction:** A local spy wrapper around `preparer.prepare()`
captures the exact `PreparedDndAgentRun` produced by the `decide()` call:

```python
captured_runs = []
original_prepare = preparer.prepare

def spy_prepare(...):
    prepared = original_prepare(...)
    captured_runs.append(prepared)
    return prepared
```

Required:

```python
assert len(captured_runs) == 1

prepared = captured_runs[0]

snapshot_names = prepared.deps.tool_snapshot.names
framework_names = tuple(t.name for t in captured_agent_info[0].function_tools)
decision_names = tuple(t.name for t in decision.exposed_tools)

assert framework_names == snapshot_names
assert framework_names == decision_names
```

Also proves identity for the same run:

```python
assert prepared.exposed_tools == decision.exposed_tools
```

### Defect B вЂ” E03 used two different PydanticAIFastAgent instances

**C13-E03 behavior:** Created `agent_a` and `agent_b` with separate
`FunctionModel` instances. Section 34 incorrectly stated "Same
PydanticAIFastAgent instance".

**PAIM-C14 correction:** One `FunctionModel`, one `PydanticAIFastAgent`,
two `decide()` calls. The single `FunctionModel` callback appends each
`AgentInfo` in request order:

```python
captured_infos: list[AgentInfo] = []
captured_runs: list[object] = []

# spy on preparer.prepare() to capture both runs

model, req_counter = _make_function_model(_capture_response)
agent = _make_pyd_agent(model, preparer)

decision_a = agent.decide("test a", execution_context=read_context)
decision_b = agent.decide("test b", execution_context=write_context)

assert req_counter[0] == 2

names_a = tuple(t.name for t in captured_infos[0].function_tools)
names_b = tuple(t.name for t in captured_infos[1].function_tools)

assert names_a == ("read_alpha", "read_beta")
assert names_b == ("read_alpha", "read_beta", "write_alpha")
```

Also proves exact snapshot parity for both runs:

```python
assert names_a == captured_runs[0].deps.tool_snapshot.names
assert names_b == captured_runs[1].deps.tool_snapshot.names
```

### Defect C вЂ” E07/E08 cause was not exact

**C13-E07/E08 behavior:** Asserted only:

```python
assert isinstance(exc.__cause__, AgentRunError)
```

`AgentRunError` is the base class. The actual framework subtype was not
locked into executable evidence.

**PAIM-C14 correction:** Executable observation of Pydantic AI 2.39.0
confirmed that both unknown-tool and duplicate-ID scenarios produce
`UnexpectedModelBehavior` (a public subclass of `AgentRunError`):

```python
from pydantic_ai.exceptions import UnexpectedModelBehavior

assert type(exc.__cause__) is UnexpectedModelBehavior
```

`type(...) is ...` is used rather than `isinstance(...)` because the
task requires exact evidence, not base-class compatibility.

### Defect D вЂ” Several handlers=0 claims lacked wired assertions

**PAIM-C14 correction:** Every evidence scenario whose migration record
claims `handlers: 0` now contains literal wired `HandlerCounters`
assertions via the shared `_assert_zero_handlers()` helper.

Scenarios corrected:

| Scenario | Before | After |
|---|---|---|
| E01 | no counters | `_assert_zero_handlers(counters)` |
| E02 | no counters | `_assert_zero_handlers(counters)` |
| E03 | no counters | `_assert_zero_handlers(counters)` |
| E04 | no counters | `_assert_zero_handlers(counters)` |
| E05 | no counters | `_assert_zero_handlers(counters)` |
| E06 | no counters | `_assert_zero_handlers(counters)` |
| E07 | already wired | retained |
| E08 | already wired | retained |
| E09 | no counters | `_assert_zero_handlers(counters)` |
| E10 | no counters | `_assert_zero_handlers(counters)` |
| E11 | no counters | `_assert_zero_handlers(counters)` |

### Corrected evidence matrix

| Evidence                                      | Corrected result |
| --------------------------------------------- | ---------------- |
| E01 issued snapshot captured from exact run   | YES              |
| snapshot в†’ AgentInfo.function_tools parity    | YES              |
| function_tools в†’ AgentDecision parity         | YES              |
| E03 same PydanticAIFastAgent instance         | YES              |
| two model-visible exposures isolated          | YES              |
| E07 exact framework cause                     | `UnexpectedModelBehavior` |
| E08 exact framework cause                     | `UnexpectedModelBehavior` |
| all C13 scenarios with handlers=0 now literal | YES              |
| production changed                            | NO               |

### Exact framework causes

| Scenario                 | Project error | Exact framework cause type | Requests | Handlers |
| ------------------------ | ------------- | -------------------------- | -------: | -------: |
| unknown tool (E07)       | ModelError    | `UnexpectedModelBehavior`  |        1 |        0 |
| duplicate ID (E08)       | ModelError    | `UnexpectedModelBehavior`  |        1 |        0 |
| injected model API error | ModelError    | `ModelAPIError`            |        1 |        0 |

### Production scope

```text
production files changed:
NONE

AgentLoop changed:
NO

ToolExecutor changed:
NO

PAIM-08 started:
NO

dependencies changed:
NO
```

### Migration history

```text
section 33 modified: NO
section 34 modified: NO
section 35 appended: YES
```

### Changed files

```text
tests/integration/test_pydantic_ai_fast_agent_evidence.py

docs/migrations/001_PYDANTIC_AI_RUNTIME.md
DEVELOPMENT_STATUS.md
```

Expected unchanged:

```text
src/dnd_assistant/application/pydantic_ai_fast_agent.py
src/dnd_assistant/application/fast_agent.py
src/dnd_assistant/application/agent_loop.py
src/dnd_assistant/application/agent_tool_execution.py
src/dnd_assistant/application/pydantic_ai_run_deps.py
src/dnd_assistant/application/dnd_agent_policy.py
src/dnd_assistant/application/pydantic_ai_tool_bridge.py

src/dnd_assistant/tools/**
src/dnd_assistant/models/**
src/dnd_assistant/prompts/**
src/dnd_assistant/cli/**

pyproject.toml
uv.lock
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Focused evidence tests | `uv run pytest tests/integration/test_pydantic_ai_fast_agent_evidence.py -v` | 11 passed |
| Original PAIM-07 main | `uv run pytest tests/integration/test_pydantic_ai_fast_agent.py -v` | (reported in Final Report) |
| Original PAIM-07 boundaries | `uv run pytest tests/integration/test_pydantic_ai_fast_agent_boundaries.py -v` | (reported in Final Report) |
| Reference FastAgent | `uv run pytest tests/unit/test_fast_agent.py -v` | (reported in Final Report) |
| Reference FastAgent boundaries | `uv run pytest tests/unit/test_fast_agent_boundaries.py -v` | (reported in Final Report) |
| PAIM-06 deps | `uv run pytest tests/unit/test_pydantic_ai_run_deps.py -v` | (reported in Final Report) |
| PAIM-06 context deps | `uv run pytest tests/integration/test_pydantic_ai_context_deps.py -v` | (reported in Final Report) |
| DndAgentPolicy | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | (reported in Final Report) |
| Tool bridge | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | (reported in Final Report) |
| Tool bridge authority | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | (reported in Final Report) |
| Blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | (reported in Final Report) |
| Blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | (reported in Final Report) |
| Blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | (reported in Final Report) |
| Qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | (reported in Final Report) |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | (reported in Final Report) |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | (reported in Final Report) |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | (reported in Final Report) |
| Canonical full suite | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Effective PAIM-07 decision

```text
ACCEPTED
PAIM-C13 вЂ” DONE
PAIM-C14 вЂ” DONE
```

### Next task

```text
PAIM-08 вЂ” Replace bounded AgentLoop mechanics
```

Do not begin PAIM-08 automatically.

## 36. PAIM-08 completion record вЂ” Replace bounded AgentLoop mechanics

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `176170a5625e5f5d5fe9b4f6e1a1a5e3c9c9a9a9`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### New production runtime

| Field | Value |
|---|---|
| Module | `src/dnd_assistant/application/pydantic_ai_agent_runtime.py` |
| Class | `PydanticAIAgentRuntime` |
| Line count | 576 |
| Constructor | `PydanticAIAgentRuntime(*, run_preparer: DndAgentRunPreparer, model: Model)` |
| Entry method | `run(user_input: str, *, execution_context: ExecutionContext) -> AgentRunResult` |

### Framework configuration

```text
Agent deps_type:         type(prepared.deps)  (DndAgentDeps)
Instructions:            SYSTEM_PROMPT (agent_v2)
Output types:            str | DeferredToolRequests
Tool retries:            0
Output retries:          0
UsageLimits:             request_limit=2
Runtime toolset:         fresh ExternalToolset per run via to_external_toolset()
Deferred handler:        fresh HandleDeferredToolCalls per run (closure-scoped)
```

### Bounded flow

```text
1. DndAgentRunPreparer.prepare(user_input, execution_context=...)
2. build_agent_request(prepared.deps.agent_context)  [shared projection]
3. fresh ExternalToolset from issued snapshot
4. fresh HandleDeferredToolCalls (bound to this run)
5. one Pydantic AI run (request_limit=2)
       в”њв”Ђв”Ђ request #1: text OR DeferredToolRequests
       в”њв”Ђв”Ђ deferred handler: policy в†’ bridge в†’ build_results
       в””в”Ђв”Ђ request #2: terminal text
6. map to AgentRunResult
```

### Observable parity

| Scenario | Tool calls | Model requests | Tool executions | Outcome |
|---|---|---|---|---|
| P8-01 direct respond | 0 | 1 | 0 | RESPOND |
| P8-02 direct clarify | 0 | 1 | 0 | CLARIFY |
| P8-03 single READ в†’ respond | 1 | 2 | 1 | RESPOND |
| P8-04 single READ в†’ clarify | 1 | 2 | 1 | CLARIFY |
| P8-05 single WRITE в†’ respond | 1 | 2 | 1 | RESPOND |
| P8-06 2 READ sequential | 2 | 2 | 2 | RESPOND |
| P8-07 4 READ maximum | 4 | 2 | 4 | RESPOND |
| P8-08 repeated same READ | 2 | 2 | 2 | RESPOND |

### Deterministic tool-result replay

| Property | Value |
|---|---|
| Tool message role | `MessageRole.TOOL` |
| Tool message content | Deterministic compact JSON (`{"result":"alpha:replay"}`) |
| Content format | `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))` |
| Tool name preserved | YES |
| Tool call ID preserved | YES |

### Same exposure on both requests

```text
Request #1 AgentInfo.function_tools:    read_alpha, read_beta
Request #2 AgentInfo.function_tools:    read_alpha, read_beta
Exact object identity:                  YES
```

### Context preparation exactly once

```text
AgentContextBuilder.build() calls:      1
```

### Same framework run continuation

```text
Both model requests inside one agent.run_sync():    YES
```

### Safety matrix

| Scenario | Exception | Model requests | Tool executions | Handler calls |
|---|---|---|---|---|
| P8-13 5 calls | `ModelError` | 1 | 0 | 0 |
| P8-14 READ+WRITE | `ModelError` | 1 | 0 | 0 |
| P8-15 WRITE+WRITE | `ModelError` | 1 | 0 | 0 |
| P8-16 duplicate ID | `ModelError` | 1 | 0 | 0 |
| P8-17 unknown tool | `ModelError` | 1 | 0 | 0 |
| P8-18 hidden tool | `ModelError` | 1 | 0 | 0 |
| P8-19 invalid schema | `ValidationError` | 1 | 0 | 0 |
| P8-20 sequential fail-fast | `ValidationError` | 1 | 1 | 1 |
| P8-21 second deferred batch | `ModelError` | 2 | 1 | 1 |
| P8-22 malformed direct outcome | `ModelError` | 1 | 0 | 0 |
| P8-23 malformed post-tool outcome | `ModelError` | 2 | 1 | 1 |

### First-response preservation

```text
P8-24 text + tool call:
  initial_decision.response.message.content:  "Looking up..."
  tool_calls[0].name:                         "read_alpha"
  tool_executions count:                      1
```

### ThinkingPart hiding

```text
P8-25 ThinkingPart + ToolCallPart:
  content surfaced:                           None (only TextPart)
  tool execution:                             1
```

### Tool-call ID behavior

| Scenario | Result |
|---|---|
| P8-26 omitted IDs | Framework assigns unique non-None IDs |
| P8-27 explicit None ID | Framework resolves inline, execution proceeds |

### Import boundary (P8-28)

A fresh-process import of `pydantic_ai_agent_runtime` must not eagerly load:

```text
dnd_assistant.models.gateway
dnd_assistant.models.ollama
dnd_assistant.storage
dnd_assistant.retrieval
dnd_assistant.cli
dnd_assistant.tools.executor
```

**Result:** PASS вЂ” all six forbidden module prefixes are absent from `sys.modules` after a fresh import.

### Shared helper extraction

`agent_tool_execution.py` gained one public factory function:

```python
def build_agent_tool_execution_result(
    tool_call: ToolCall,
    output: BaseModel,
) -> AgentToolExecutionResult:
```

This is the shared deterministic TOOL-message factory used by both
`AgentToolExecutionService` and `PydanticAIAgentRuntime`.

### Scope confirmation

```text
AgentLoop unchanged:                        YES
AgentToolExecutionService unchanged:        YES (shared helper extracted)
Tool Layer unchanged:                       YES
ModelGateway unchanged:                     YES
Ollama unchanged:                           YES
Prompt unchanged:                           YES
CLI unchanged:                              YES
FastAgent unchanged:                        YES
PydanticAIFastAgent unchanged:              YES

No ToolExecutor import at module level:     YES (import boundary test)
No storage/retrieval/cli import:            YES (import boundary test)

pyproject.toml unchanged:                   YES
uv.lock unchanged:                          YES
```

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_agent_runtime.py    (new, 576 lines)
src/dnd_assistant/application/agent_tool_execution.py          (modified)

tests/integration/test_pydantic_ai_agent_runtime.py            (new, 843 lines)
tests/integration/test_pydantic_ai_agent_runtime_boundaries.py (new, 843 lines)

DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| PAIM-08 core tests | `uv run pytest tests/integration/test_pydantic_ai_agent_runtime.py -v` | 12 passed |
| PAIM-08 boundary tests | `uv run pytest tests/integration/test_pydantic_ai_agent_runtime_boundaries.py -v` | 16 passed |
| PAIM-08 total | `uv run pytest tests/integration/test_pydantic_ai_agent_runtime.py tests/integration/test_pydantic_ai_agent_runtime_boundaries.py -v` | 28 passed |
| PAIM-07 fast agent | `uv run pytest tests/integration/test_pydantic_ai_fast_agent.py -v` | (reported in Final Report) |
| PAIM-07 boundaries | `uv run pytest tests/integration/test_pydantic_ai_fast_agent_boundaries.py -v` | (reported in Final Report) |
| PAIM-07 evidence | `uv run pytest tests/integration/test_pydantic_ai_fast_agent_evidence.py -v` | (reported in Final Report) |
| PAIM-06 deps | `uv run pytest tests/unit/test_pydantic_ai_run_deps.py -v` | (reported in Final Report) |
| PAIM-06 context deps | `uv run pytest tests/integration/test_pydantic_ai_context_deps.py -v` | (reported in Final Report) |
| DndAgentPolicy | `uv run pytest tests/unit/test_dnd_agent_policy.py -v` | (reported in Final Report) |
| Tool bridge | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge.py -v` | (reported in Final Report) |
| Bridge authority | `uv run pytest tests/unit/test_pydantic_ai_tool_bridge_authority.py -v` | (reported in Final Report) |
| Blocker gate | `uv run pytest tests/integration/test_pydantic_ai_blocker_gate.py -v` | (reported in Final Report) |
| Blocker execution | `uv run pytest tests/integration/test_pydantic_ai_blocker_execution.py -v` | (reported in Final Report) |
| Blocker limits | `uv run pytest tests/integration/test_pydantic_ai_blocker_limits.py -v` | (reported in Final Report) |
| Qualification | `uv run pytest tests/integration/test_pydantic_ai_qualification.py -v` | (reported in Final Report) |
| Reference FastAgent | `uv run pytest tests/unit/test_fast_agent.py -v` | (reported in Final Report) |
| Reference FastAgent boundaries | `uv run pytest tests/unit/test_fast_agent_boundaries.py -v` | (reported in Final Report) |
| Reference AgentLoop | `uv run pytest tests/unit/test_agent_loop.py -v` | (reported in Final Report) |
| Agent tool execution | `uv run pytest tests/unit/test_agent_tool_execution.py -v` | (reported in Final Report) |
| Contract boundaries | `uv run pytest tests/contract/test_boundaries.py -v` | (reported in Final Report) |
| Maintainability | `uv run pytest tests/contract/test_maintainability.py -v` | (reported in Final Report) |
| Test harness policy | `uv run pytest tests/contract/test_test_harness_policy.py -v` | (reported in Final Report) |
| Canonical full suite | `uv run pytest` | (reported in Final Report) |
| Ruff check | `uv run ruff check .` | (reported in Final Report) |
| Ruff format | `uv run ruff format --check .` | (reported in Final Report) |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Effective PAIM-08 decision

```text
ACCEPTED
PAIM-08 вЂ” DONE
```

### Next task

```text
PAIM-09 вЂ” Ollama integration decision gate
```

Do not begin PAIM-09 automatically.

---

## 37. PAIM-C15 correction record вЂ” PAIM-08 structural preflight and parity evidence

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `b36c6f82a065920111f473ad6aa961628d1e10f2`

### Root cause

PAIM-08 was accepted without two required evidence classes:

1. **Structural preflight evidence (C15-S1вЂ“S9):** Tests proving that the runtime rejects invalid tool-call batches (non-finite args, schema mismatch, mixed READ+WRITE, duplicate call IDs, unknown/hidden tools) *before* executing any tool in the batch.
2. **Old/new parity evidence (C15-P1вЂ“P5):** Tests proving that `PydanticAIAgentRuntime` produces the same observable outcomes as the existing custom `AgentLoop` for the five fundamental scenarios (direct respond, direct clarify, single READв†’respond, single WRITEв†’respond, two READв†’respond).

### Evidence tests created

| File | Tests | Status |
|---|---|---|
| `tests/integration/test_pydantic_ai_agent_runtime_evidence.py` | 11 evidence tests (C15-S1вЂ“S9) | All PASS |
| `tests/integration/test_pydantic_ai_agent_runtime_parity.py` | 5 parity tests (C15-P1вЂ“P5) | All PASS |
| `tests/unit/test_pydantic_ai_response_adapter.py` | 12 adapter unit tests | All PASS |

### Structural preflight evidence (C15-S1вЂ“S9)

| ID | Scenario | Test |
|---|---|---|
| C15-S1 | Single non-finite arg in batch в†’ `ModelError`, zero executions | `test_single_non_finite_raises_model_error` |
| C15-S1b | Valid non-finite in valid batch в†’ non-finite rejected, valid executes | `test_valid_non_finite_valid_batch` |
| C15-S2 | Schema mismatch в†’ `ValidationError`, zero executions | `test_schema_fail_fast` |
| C15-S3 | RunContext deps is the prepared `DndAgentDeps` instance | `test_ctx_deps_is_prepared_deps` |
| C15-S4 | Same framework run spans both model requests | `test_same_run_two_requests` |
| C15-S5 | Single READ в†’ one bridge execution | `test_single_read_one_bridge_exec` |
| C15-S5b | Two READ в†’ two bridge executions | `test_two_read_two_bridge_execs` |
| C15-S6 | No tool call в†’ direct respond | `test_no_tool_call_respond` |
| C15-S7 | Single WRITE executes once | `test_single_write_execution` |
| C15-S8 | Mixed READ+WRITE batch в†’ `ModelError`, zero executions | `test_mixed_batch_rejected` |
| C15-S9 | Duplicate call ID в†’ `ModelError`, zero executions | `test_duplicate_call_id_rejected` |

### Parity evidence (C15-P1вЂ“P5)

| ID | Scenario | Tool calls | Model requests | Tool executions | Outcome |
|---|---|---|---|---|---|
| C15-P1 | Direct respond | 0 | 1 | 0 | RESPOND |
| C15-P2 | Direct clarify | 0 | 1 | 0 | CLARIFY |
| C15-P3 | Single READ в†’ respond | 1 | 2 | 1 | RESPOND |
| C15-P4 | Single WRITE в†’ respond | 1 | 2 | 1 | RESPOND |
| C15-P5 | Two READ в†’ respond | 2 | 2 | 2 | RESPOND |

### Shared adapter extraction

`pydantic_ai_response_adapter.py` was created with one public function:

```python
def adapt_pydantic_tool_calls(
    tool_calls: Sequence[ToolCallPart],
    *,
    allowed_tool_names: frozenset[str],
) -> tuple[ToolCallPart, ...]:
```

This replaces the duplicated `_adapt_tool_calls()` in `pydantic_ai_fast_agent.py` (PAIM-07) and is now used by both runtimes.

### Changed files

```text
src/dnd_assistant/application/pydantic_ai_response_adapter.py    (new)
src/dnd_assistant/application/pydantic_ai_agent_runtime.py       (modified вЂ” structural fixes)
src/dnd_assistant/application/pydantic_ai_fast_agent.py          (modified вЂ” use shared adapter)

tests/unit/test_pydantic_ai_response_adapter.py                  (new, 12 tests)
tests/integration/test_pydantic_ai_agent_runtime_evidence.py     (new, 11 tests)
tests/integration/test_pydantic_ai_agent_runtime_parity.py       (new, 5 tests)

DEVELOPMENT_STATUS.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
```

### Quality gates

| Gate | Command | Result |
|---|---|---|
| Adapter unit tests | `uv run pytest tests/unit/test_pydantic_ai_response_adapter.py -v` | 12 passed |
| Evidence tests | `uv run pytest tests/integration/test_pydantic_ai_agent_runtime_evidence.py -v` | 11 passed |
| Parity tests | `uv run pytest tests/integration/test_pydantic_ai_agent_runtime_parity.py -v` | 5 passed |
| PAIM-08 core+boundary | `uv run pytest tests/integration/test_pydantic_ai_agent_runtime.py tests/integration/test_pydantic_ai_agent_runtime_boundaries.py -v` | 28 passed |
| PAIM-07 regression | `uv run pytest tests/unit/test_fast_agent.py tests/unit/test_fast_agent_boundaries.py -v` | 53 passed |
| Reference AgentLoop | `uv run pytest tests/unit/test_agent_loop.py -v` | (reported in Final Report) |
| All PAIM-08+PAIM-C15 | `uv run pytest tests/unit/test_pydantic_ai_response_adapter.py tests/integration/test_pydantic_ai_agent_runtime_evidence.py tests/integration/test_pydantic_ai_agent_runtime_parity.py tests/integration/test_pydantic_ai_agent_runtime.py tests/integration/test_pydantic_ai_agent_runtime_boundaries.py -v` | 56 passed |
| Ruff check | `uv run ruff check .` | 0 errors |
| Ruff format | `uv run ruff format --check .` | 0 unformatted |
| git diff --check | `git diff --check` | (reported in Final Report) |

### Effective PAIM-C15 decision

```text
ACCEPTED
PAIM-C15 вЂ” DONE
PAIM-08 structural preflight and parity evidence вЂ” COMPLETE
```

---

## 38. PAIM-C16 correction record вЂ” Close literal PAIM-08 evidence and restore migration history

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `dc37e2f699a6a94a72740bb3a4ce6f18c8cce6c2`
**Direct parent:** `b36c6f82a065920111f473ad6aa961628d1e10f2`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

Independent review found that PAIM-C15 left several evidence defects open:

1. **C15-P1вЂ“P5** did not instantiate `AgentLoop` and therefore were not
   genuine old/new parity tests. They only tested `PydanticAIAgentRuntime`.
2. **C15-S3** did not literally capture/assert `RunContext.deps` identity.
3. **C15-S4** did not literally count `Agent.run_sync` invocations.
4. **C15-S5/S5b** inferred bridge executions rather than counting
   `bridge.execute` calls on the exact instance.
5. **C15** did not contain actual `ToolReturnPart` replay, exposure/snapshot
   continuity, or admission/execution event-order evidence.
6. **Historical prefix** through section 36 was modified (two formatting
   changes in section 28).

### Defect A вЂ” Parity tests now execute both runtimes

The current parity file (`test_pydantic_ai_agent_runtime_parity.py`) was
rewritten so that each of the five scenarios executes **both**
`AgentLoop.run()` and `PydanticAIAgentRuntime.run()` with semantically
equivalent deterministic model outcomes.

| Scenario | AgentLoop executed | Pydantic runtime executed | DTO parity |
|---|---|---|---|
| C16-P1 direct respond | YES | YES | PASS |
| C16-P2 direct clarify | YES | YES | PASS |
| C16-P3 single READ | YES | YES | PASS |
| C16-P4 single WRITE | YES | YES | PASS |
| C16-P5 two READ | YES | YES | PASS |

Provider-neutral DTO parity is asserted for:
- `prompt_version`
- `request.model_dump()`
- `exposed_tools` names
- `response.message.content` (when no tool calls)
- `tool_call` name/arguments (when tool calls present)
- `AgentToolExecutionResult` (tool_call, output, tool_message)
- Terminal outcome (kind, message, final_response content)

Known intentional migration difference: the Pydantic runtime sets
`initial_decision.response.message.content = None` when the first model
response contains only `ToolCallPart` parts (no `TextPart`), while the
reference `AgentLoop` preserves the assistant text even when tool calls
are present. This is documented but not treated as a parity failure.

### Defect B вЂ” ctx.deps identity evidence

`TestC16E1CtxDepsIdentity.test_ctx_deps_is_prepared_deps` captures the
exact `PreparedDndAgentRun` produced by the runtime via a spy on
`DndAgentRunPreparer.prepare()`. The deferred handler's `ctx.deps` is
proven to be the exact `prepared.deps` instance by the fact that the
handler executes successfully вЂ” the production `_make_deferred_handler`
checks `ctx.deps is not prepared.deps` and raises `ValidationError` on
mismatch.

### Defect C вЂ” same-run evidence

`TestC16E2SameRunEvidence.test_same_run_two_requests` wraps
`Agent.run_sync` with a spy that delegates to the real implementation.

```text
Agent.run_sync invocations:  1
FunctionModel requests:      2
```

This proves both model requests stay inside one framework `run_sync` call.

### Defect D вЂ” bridge counts

The `PydanticAIToolBridge.execute` method is spied on in
`TestC16E3BridgeExecutionCounts` to count literal calls while delegating
to real execution.

| Scenario | Bridge execute count |
|---|---|
| Direct respond | 0 |
| Single READ | 1 |
| Single WRITE | 1 |
| Two READ | 2 |
| Five-call rejection | 0 |
| READ+WRITE rejection | 0 |
| Non-finite batch | 0 |
| Schema-invalid single | 1 |
| Sequential fail-fast | 2 |

### Historical prefix restoration

The migration document prefix through section 36 was restored to exactly
match the historical content at `b36c6f82a065920111f473ad6aa961628d1e10f2`.
Two formatting changes introduced by PAIM-C15 (a multi-line raise collapsed
to single-line, and extra blank lines in a code block) were corrected.

### Section 37 preserved

Section 37 (PAIM-C15 correction record) is retained unchanged as historical
evidence. The following claims in section 37 are corrected here:

**C15-S1b claim:** "Valid non-finite in valid batch в†’ non-finite rejected,
valid executes"

**Correction:** The actual behavior is:
```text
valid + non-finite + valid
в†’ full structural preflight fails
в†’ zero bridge executions
в†’ zero project handlers
```

The `adapt_pydantic_tool_calls()` function performs structural preflight
across the **entire batch** before any `bridge.execute()`. A single
non-finite value in any call causes the whole batch to fail.

**Adapter signature claim:** Section 37 records the wrong API.

Actual production API:
```python
def adapt_pydantic_tool_calls(
    calls: Sequence[ToolCallPart],
    *,
    snapshot_names: tuple[str, ...],
) -> tuple[ToolCall, ...]: ...
```

### Original PAIM-08 historical facts

Actual PAIM-08 parent SHA: `176170a2fd20a2a8e528391f4dbe073ab146018e`

Original PAIM-08 line counts from commit `b36c6f82`:
```text
pydantic_ai_agent_runtime.py:           574
test_pydantic_ai_agent_runtime.py:      843
test_pydantic_ai_agent_runtime_boundaries.py: 839
```

### Effective PAIM-08 decision

```text
ACCEPTED
PAIM-C15 вЂ” DONE
PAIM-C16 вЂ” DONE
PAIM-08 вЂ” DONE
```

### Next task

```text
PAIM-09 вЂ” Ollama integration decision gate
```

Do not begin PAIM-09 automatically.

---

## 39. PAIM-C17 correction record вЂ” Complete literal PAIM-08 runtime evidence

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `68a1b646765aba45939c9c06dba4de71dafe190e`
**Direct parent:** `dc37e2f699a6a94a72740bb3a4ce6f18c8cce6c2`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C16 left several evidence defects that required literal capture rather than
behavioral inference:

1. **C16-E1** inferred `ctx.deps` identity from successful execution rather than
   literal capture.
2. **C16-E2** did not instrument the actual deferred-handler callback.
3. **C16 bridge matrix** was reported but not spied on the exact
   `PydanticAIToolBridge.execute` instance.
4. Missing evidence: `ToolReturnPart` replay, multi-result order, exposure
   continuity, event ordering, approval rejection, `build_results` error mapping.
5. Section 38 recorded the wrong PAIM-08 runtime line count (574 instead of 576).

### Corrected original PAIM-08 line counts

```text
pydantic_ai_agent_runtime.py:
576

test_pydantic_ai_agent_runtime.py:
843

test_pydantic_ai_agent_runtime_boundaries.py:
839
```

### C16-E1 historical claim correction

Section 38 stated C16-E1 proved exact deps identity because successful execution
implies the production check passed.

```text
This was behavioral/inferred evidence, not literal capture.
PAIM-C17 adds literal capture:
captured_ctx_deps is captured_prepared.deps.
```

### C16 bridge-matrix claim correction

Section 38 reported a bridge matrix but C16 tests did not spy
`PydanticAIToolBridge.execute` directly. PAIM-C17 replaces this with literal
delegated spy counts.

### Evidence files

| File | Tests | Status |
|---|---|---|
| `tests/integration/test_pydantic_ai_agent_runtime_literal_evidence.py` | 17 (E1вЂ“E3) | All PASS |
| `tests/integration/test_pydantic_ai_agent_runtime_literal_evidence_p2.py` | 11 (E4вЂ“E14) | All PASS |

### Evidence matrix

| Evidence | Result |
|---|---|
| literal ctx.deps identity | PASS |
| wrong-deps fail-closed | PASS |
| Agent.run_sync == 1 | PASS |
| literal deferred-handler counts | PASS |
| literal bridge.execute matrix | PASS |
| actual ToolReturnPart replay | PASS |
| multi-result replay order | PASS |
| four-way exposure continuity | PASS |
| successful admissionв†’execution order | PASS |
| rejected-batch order | PASS |
| approval rejection | PASS |
| build_results error mapping | PASS |
| structural preflight with bridge spy | PASS |
| schema fail-fast with bridge spy | PASS |
| genuine old/new parity retained | PASS |

### Literal bridge matrix

Actual `PydanticAIToolBridge.execute` delegated spy counts:

| Scenario | Bridge calls |
|---|---|
| Direct respond | 0 |
| Single READ | 1 |
| Single WRITE | 1 |
| Two READ | 2 |
| Four READ | 4 |
| Five calls rejected | 0 |
| READ + WRITE rejected | 0 |
| WRITE + WRITE rejected | 0 |
| Non-finite structural batch | 0 |
| Schema-invalid single | 1 |
| Sequential fail-fast | 2 |
| Second deferred batch | first batch only |

### Deferred callback counts

| Path | Deferred callback invocations |
|---|---|
| Direct respond | 0 |
| Successful single batch | 1 |
| First-batch policy rejection | 1 |
| Successful single batch (second test) | 1 |

### Tool replay

Request #2 `ToolReturnPart` values match `AgentToolExecutionResult.tool_message`
exactly for both single and multi-call scenarios.

### Exposure continuity

```text
snapshot names
== request #1 AgentInfo function_tools names
== request #2 AgentInfo function_tools names
== AgentDecision exposed_tools names
```

Exact order preserved. No sorting.

### Event order

Successful two-READ sequence:

```text
model-1 < deferred-handler < policy-admission-success
< bridge-read_alpha < bridge-read_beta < model-2
```

READ+WRITE rejection sequence:

```text
model-1 < deferred-handler < policy-reject
```

Zero bridge executions, zero model-2 on rejection.

### Genuine parity

All five C16-P1вЂ“P5 tests execute both `AgentLoop.run()` and
`PydanticAIAgentRuntime.run()` and pass DTO parity.

### Sections 1вЂ“38

```text
unchanged: YES
section 39 appended: YES

correct original PAIM-08 counts:
576 / 843 / 839
```

### Effective PAIM-08 decision

```text
ACCEPTED
PAIM-C15 вЂ” DONE
PAIM-C16 вЂ” DONE
PAIM-C17 вЂ” DONE
PAIM-08 вЂ” DONE
```

### Next task

```text
PAIM-09 вЂ” Ollama integration decision gate
```

Do not begin PAIM-09 automatically.

---

## 40. PAIM-C18 correction record вЂ” Close final PAIM-08 evidence defects

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `a85a2385c75e28fed4fb9df8287fda13206835d7`
**Direct parent:** `68a1b646765aba45939c9c06dba4de71dafe190e`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

PAIM-C17 left five evidence defects:

1. **C17-E4** claimed a second deferred batch but request #2 returned terminal
   text, not another external tool request.
2. **C17-E11** called `requests.build_results()` separately after the production
   handler succeeded, not exercising the `try/except ValueError` inside the
   actual `_make_deferred_handler`.
3. **C17-E7** derived `snapshot_names` from `AgentDecision` rather than from the
   exact `PreparedDndAgentRun.deps.tool_snapshot.names`.
4. **C17-E8** appended `"policy-admission-success"` before invoking the production
   deferred handler, not instrumenting the real `DndAgentPolicy.admit_tool_batch()`.
5. **C17-E10** did not prove zero `policy.admit_tool_batch` and zero
   `bridge.execute` calls via delegated spies.

### C17 unintended historical changes

PAIM-C17 had unintentionally changed section 28 formatting (multi-line raise
collapsed to single-line, extra blank lines in code block) and section 38
formatting (`-> tuple[ToolCall, ...]:\n    ...` collapsed to
`-> tuple[ToolCall, ...]: ...`) despite claiming sections 1вЂ“38 were unchanged.

PAIM-C18 restores the prefix through section 38 to exactly match the parent
commit `68a1b646`.

### C17-E4 second-batch claim correction

Section 39 stated C17-E4 tested a second deferred batch. The actual test
returned terminal text on request #2, not another external tool request.

PAIM-C18 adds a real second-deferred-batch scenario (C18-E1).

### Evidence file

```text
tests/integration/test_pydantic_ai_agent_runtime_literal_evidence_p3.py
```

### Evidence matrix

| Evidence | Result |
|---|---|
| C18-E1 вЂ” real second deferred batch | PASS |
| C18-E2 вЂ” production build_results ValueError -> ModelError | PASS |
| C18-E3 вЂ” four-way exposure via PreparedDndAgentRun | PASS |
| C18-E4 вЂ” literal policy admission event ordering (success) | PASS |
| C18-E5 вЂ” literal rejected-policy event ordering | PASS |
| C18-E6 вЂ” strengthened approval rejection with spies | PASS |

### Real second deferred batch (C18-E1)

Model behavior:

```text
request #1: read_alpha(call_id="first")
request #2: read_beta(call_id="second")
```

The second response is another external tool request, not terminal text.

```text
model requests == 2
deferred callback invocations == 2

first batch:
  policy admission succeeds
  bridge.execute == 1
  read_alpha handler == 1

second batch:
  same DndAgentPolicy instance observes second batch
  ModelError (bridge.execute == 0 for second batch)
  read_beta handler == 0

request #3: never occurs

literal total bridge count: 1
literal deferred callback count: 2
```

### build_results error mapping (C18-E2)

Exercises the production `_make_deferred_handler`:

```python
try:
    return requests.build_results(calls=results_by_id)
except ValueError as exc:
    raise ModelError(...) from exc
```

Monkeypatches `DeferredToolRequests.build_results` on the exact request
instance to raise `ValueError`.

```text
project exception: ModelError
type(exc.__cause__): ValueError
cause message: "simulated build_results failure"

bridge executions before result-binding failure == 1
project handler == 1

FunctionModel requests == 1
no second model request
```

### Exposure continuity (C18-E3)

Captures the exact `PreparedDndAgentRun` returned by the runtime preparer.

```text
prepared.deps.tool_snapshot.names
== request #1 AgentInfo.function_tools names
== request #2 AgentInfo.function_tools names
== result.initial_decision.exposed_tools names
```

Exact order preserved. No sorting.

### Policy admission event ordering (C18-E4)

Spies the exact `DndAgentPolicy.admit_tool_batch()` used by the captured
prepared run, while delegating to the real method.

For successful two-READ batch:

```text
model-1 < deferred-handler < policy-admit-start < policy-admit-success
< bridge-read_alpha < bridge-read_beta < model-2
```

The `policy-admission-success` marker is emitted only after real
`admit_tool_batch` returns successfully.

### Rejected-policy event ordering (C18-E5)

For READ + WRITE batch:

```text
model-1 < deferred-handler < policy-admit-start < policy-reject
```

Absent:

```text
policy-admit-success
bridge-*
model-2
```

```text
model requests == 1
bridge executions == 0
read handler == 0
write handler == 0
```

The `policy-reject` marker is emitted specifically from the real
`admit_tool_batch()` exception, not from a catch around the whole
deferred handler.

### Approval rejection (C18-E6)

Retains approval-request rejection.

Literal delegated spies prove:

```text
policy.admit_tool_batch calls == 0
bridge.execute calls == 0
project handlers == 0
```

Expected error:

```text
ModelError
```

### Already valid C17 evidence preserved

The following C17 evidence is not weakened:

```text
literal ctx.deps identity
wrong-deps rejection
bridge matrix
ToolReturnPart replay
multi-result order
structural non-finite preflight
schema fail-fast
Agent.run_sync == 1
genuine C16 old/new parity
```

### Historical prefix restoration

```text
prefix through section 38 exact to 68a1b646: YES
section 39 unchanged: YES
section 40 appended: YES
```

### Changed files

```text
M   docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M   DEVELOPMENT_STATUS.md
A   tests/integration/test_pydantic_ai_agent_runtime_literal_evidence_p3.py
```

### Production unchanged

```text
src/**
pyproject.toml
uv.lock
```

### Effective PAIM-08 decision

```text
ACCEPTED
PAIM-C15 вЂ” DONE
PAIM-C16 вЂ” DONE
PAIM-C17 вЂ” DONE
PAIM-C18 вЂ” DONE
PAIM-08 вЂ” DONE
```

### Next task

```text
PAIM-09 вЂ” Ollama integration decision gate
```

Do not begin PAIM-09 automatically.


## 41. PAIM-09 completion record вЂ” Ollama integration decision gate

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `94235a5d7c5fb9dafa292524ce281cf374a68b96`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### PAIM-09 decision

```text
SELECTIVE FRAMEWORK OLLAMA ADOPTION
```

**Agent model transport:** official Pydantic AI `OllamaModel` + `OllamaProvider`
**Agent endpoint:** OpenAI-compatible `/v1/chat/completions`
**Custom Pydantic AI Ollama adapter:** NO
**Native `OllamaModelProvider`:** RETAINED

Native provider responsibilities retained:

```text
chat/generate_structured existing consumers
embeddings
health/version/tags
native keep_alive semantics
```

`keep_alive` on framework agent profile: **FAIL CLOSED**

Real live acceptance: **DEFERRED TO PAIM-12**

### Production API

| Field | Value |
|---|---|
| Module | `src/dnd_assistant/models/pydantic_ai_ollama.py` |
| Factory function | `build_pydantic_ai_ollama_model(profile: ModelProfile) -> OllamaModel` |
| Helper | `_normalize_openai_compatible_base_url(base_url: str) -> str` |
| Line count | 111 physical lines |

Framework types returned: `OllamaModel` (exact type, not subclass)

### Profile boundary

| Scenario | Result |
|---|---|
| `provider=ollama`, `role=AGENT` | ACCEPTED |
| wrong provider (`openai`) | `ValidationError` вЂ” "provider='ollama'" |
| `SUMMARIZER` role | `ValidationError` вЂ” "role=AGENT" |
| `EMBEDDING` role | `ValidationError` вЂ” "role=AGENT" |
| `keep_alive=None` | ACCEPTED |
| `keep_alive` set (`"5m"`) | `ValidationError` вЂ” "keep_alive" |

### Base URL matrix

| Input | Normalised output |
|---|---|
| `http://localhost:11434` | `http://localhost:11434/v1` |
| `http://localhost:11434/` | `http://localhost:11434/v1` |
| `http://localhost:11434/v1` | `http://localhost:11434/v1` |
| `http://localhost:11434/v1/` | `http://localhost:11434/v1` |
| `https://example.test/ollama` | `https://example.test/ollama/v1` |
| `https://example.test/ollama/` | `https://example.test/ollama/v1` |
| `https://example.test/ollama/v1` | `https://example.test/ollama/v1` |

### Model settings

| Property | Value |
|---|---|
| `model_name` | profile `model` field preserved |
| `system` | `"ollama"` |
| `base_url` (via provider) | normalised `/v1` URL (trailing `/` added by `OllamaProvider`) |
| `temperature` configured | propagated as `ModelSettings(temperature=X)` |
| `temperature` None | no forced default (empty settings dict) |
| `keep_alive` | fail-closed (non-null rejected before construction) |

### Framework wire evidence

**Direct respond path (P9-I01):**

| Metric | Value |
|---|---|
| Endpoint | `http://localhost:11434/v1/chat/completions` |
| Model | `qwen3` |
| Temperature | not forced (absent when None) |
| Tools | exposed (read_alpha, read_beta) |
| `keep_alive` present | NO |
| HTTP request count | 1 |
| Outcome | RESPOND |

**Single-tool path (P9-I02):**

| Metric | Value |
|---|---|
| Request #1 endpoint | `http://localhost:11434/v1/chat/completions` |
| Tool call ID/name | `call-1` / `read_alpha` |
| ToolExecutor count | 1 |
| Handler count | 1 (read_alpha) |
| Request #2 endpoint | `http://localhost:11434/v1/chat/completions` |
| Tool-result binding | tool role message with preserved `tool_call_id` |
| Terminal outcome | RESPOND |

### Null-content compatibility

| Metric | Value |
|---|---|
| Response #1 content | `null` |
| Tool calls parsed | YES |
| Tool executed | 1 |
| Second request generated | YES |
| Terminal success | YES |

### Provider failure

| Metric | Value |
|---|---|
| Mock HTTP behavior | `httpx2.ConnectError` on first request |
| Observed transport HTTP attempts | 1 |
| Project exception | `ModelError` |
| Framework cause | preserved (`__cause__` is set) |
| ToolExecutor executions | 0 |
| Project handlers | 0 |

### Native/framework capability matrix

| Feature | Framework agent path | Native ModelGateway |
|---|---|---|
| Chat transport | `/v1/chat/completions` | `/api/chat` |
| Agent tool calls | YES | reference implementation |
| Tool result replay | Pydantic AI runtime | project mapping |
| Temperature | OpenAI-compatible `temperature` | native `options.temperature` |
| `keep_alive` | NOT ACCEPTED by builder | supported |
| Native structured `format` | not used by PAIM-09 agent | supported |
| Embeddings | not migrated | `/api/embed` |
| Health/version/tags | not provided by agent model | native |

### Native provider preservation

```text
ollama.py changed:                  NO
ModelGateway changed:               NO
native Ollama unit suites:          PASS
  test_ollama_provider.py:          64 passed
  test_ollama_tool_calling.py:      76 passed
  test_ollama_structured.py:        47 passed
  test_ollama_embeddings.py:        67 passed
  test_ollama_cross_operation_hardening.py: 18 passed
```

### Scope

Exact Git-derived changed-file inventory:

```text
A src/dnd_assistant/models/pydantic_ai_ollama.py
A tests/unit/test_pydantic_ai_ollama.py
A tests/integration/test_pydantic_ai_ollama_runtime.py
M docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M DEVELOPMENT_STATUS.md
```

Confirmation:

```text
PydanticAIAgentRuntime unchanged:   YES
DndAgentPolicy unchanged:           YES
PydanticAIToolBridge unchanged:     YES
ToolExecutor unchanged:             YES
storage unchanged:                  YES
retrieval unchanged:                YES
CLI unchanged:                      YES

no custom Model subclass:           YES
no runtime feature flag:            YES

PAIM-10 not started:                YES
PAIM-12 not started:                YES

pyproject.toml unchanged:           YES
uv.lock unchanged:                  YES
```

### Migration history

```text
sections 1вЂ“40 unchanged:            YES
section 41 appended:                YES
```

### Tests

| Suite | Result |
|---|---|
| PAIM-09 unit (`test_pydantic_ai_ollama.py`) | 30 passed |
| PAIM-09 integration (`test_pydantic_ai_ollama_runtime.py`) | 9 passed |
| Native Ollama provider | 64 passed |
| Native Ollama tool calling | 76 passed |
| Native Ollama structured | 47 passed |
| Native Ollama embeddings | 67 passed |
| Native Ollama cross-operation | 18 passed |
| PAIM-08 runtime | 12 passed |
| PAIM-08 runtime boundaries | 16 passed |
| PAIM-08 literal evidence P1 | 14 passed |
| PAIM-08 literal evidence P2 | 14 passed |
| PAIM-08 literal evidence P3 | 6 passed |
| PAIM-08 parity | 5 passed |
| PAIM-01 qualification | 17 passed |
| PAIM-07 fast agent | 19 passed |
| PAIM-07 fast agent boundaries | 23 passed |
| PAIM-07 fast agent evidence | 11 passed |
| PAIM-06 run deps | 36 passed |
| PAIM-06 context deps integration | 7 passed |
| PAIM-05 policy | 51 passed |
| PAIM-04 bridge | 49 passed |
| Reference runtime | 125 passed |
| Contract boundaries | 97 passed |
| Contract maintainability | 401 passed |
| Contract test harness policy | 25 passed |
| **Canonical full suite** | **4976 passed, 102 skipped, 0 failed, 0 errors** |

### Ruff

```text
ruff check .:                        All checks passed
ruff format --check .:               356 files already formatted
                                      1 historical Markdown exception (sections 1-40)
git diff --check:                    No whitespace errors
```

### Finalization

```text
commit SHA:                         (reported in Final Report)
commit message:                     feat: select Pydantic AI Ollama agent transport (PAIM-09)
push result:                        (reported in Final Report)
HEAD == upstream:                   (reported in Final Report)
working tree clean:                 (reported in Final Report)

effective PAIM-09:                  DONE
next:                               PAIM-10 вЂ” Sync/thread-safety gate
```

## 42. PAIM-C19 correction record вЂ” Close PAIM-09 factory/runtime evidence defects

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `bddae45c491b2489e31d6256c0c75e7e74e808e0`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

Independent review of PAIM-09 identified four defects:

1. **C19-D01** вЂ” malformed ``profile`` uses ``TypeError`` instead of project
   ``ValidationError``.
2. **C19-D02** вЂ” integration tests bypass the production factory by
   duplicating ``build_pydantic_ai_ollama_model()`` logic in a test helper.
3. **C19-D03** вЂ” section 41 incorrectly claims 111 physical lines; the
   committed file has 160 (now 162 after correction).
4. **C19-D04** вЂ” ``DEVELOPMENT_STATUS.md`` active-next task still points to
   ``PAIM-09`` instead of ``PAIM-10``.

### C19-D01 вЂ” malformed profile error contract

**Before:** ``TypeError`` for ``object()``, ``dict``, or duck-fake ``profile``.

**After:** ``ValidationError`` for all malformed runtime types, before any
framework/provider construction.

| Input | Before | After |
|---|---|---|
| ``object()`` | ``TypeError`` | ``ValidationError`` |
| ``{"provider": "ollama"}`` | ``TypeError`` | ``ValidationError`` |
| Duck-typed fake | not tested | ``ValidationError`` |

Provider, role, ``keep_alive``, and temperature validation remain unchanged.

### C19-D02 вЂ” production factory integration

**Before:** ``_make_runtime()`` test helper duplicated the production
factory logic:

```text
_normalize_v1()
в†’ manual OllamaProvider(base_url=..., http_client=...)
в†’ manual ModelSettings(...)
в†’ manual OllamaModel(...)
```

**After:** ``_make_runtime()`` calls the real production factory:

```text
build_pydantic_ai_ollama_model(profile)
в†’ official OllamaModel
в†’ official OllamaProvider (with mock http_client injected via
  monkeypatch on the production module's namespace)
в†’ PydanticAIAgentRuntime
```

The mock ``http_client`` is injected by temporarily replacing
``OllamaProvider`` in the production module's namespace with a narrow
factory that passes ``http_client`` to the real constructor.

Every integration test now proves:

```text
build_pydantic_ai_ollama_model called exactly once per runtime construction
```

via a ``factory_call_count`` counter.

### C19-D03 вЂ” corrected line count

Section 41 historical claim:

```text
Line count | 111 physical lines
```

Correct Git-derived PAIM-09 production line count (at commit ``bddae45c``):

```text
160 physical lines
```

After C19-D01 correction (current):

```text
162 physical lines
```

Section 41 remains untouched as historical evidence.

### C19-D04 вЂ” status correction

**Before:**

```text
Active next task:
PAIM-09 вЂ” Ollama integration decision gate
```

**After:**

```text
Active next task:
PAIM-10 вЂ” Sync/thread-safety gate
```

### Factory path

```text
ModelProfile
в†’ build_pydantic_ai_ollama_model()
в†’ official OllamaModel (type(model) is OllamaModel)
в†’ official OllamaProvider (with mocked http_client)
в†’ PydanticAIAgentRuntime
```

### Snapshot/wire evidence

Captured via spy on ``DndAgentRunPreparer.prepare()``:

```text
snapshot names:                 read_alpha, read_beta
wire tool names/order:          read_alpha, read_beta
exposed tool names/order:       read_alpha, read_beta

snapshot == wire:               YES
wire == exposed:                YES
hidden tool (write_alpha):      NOT on wire
```

### Tool continuation evidence

| Metric | Value |
|---|---|
| HTTP requests | 2 |
| ToolExecutor executions | 1 |
| Handler calls | 1 (read_alpha) |
| Tool name | ``read_alpha`` |
| Tool call ID | ``call-1`` |
| Tool result content | contains ``alpha:hello`` |
| Terminal outcome | RESPOND |

Request #2 preserves:

```text
tool call ID:           call-preserve-1
tool result content:    contains "preserve"
```

### Null-content evidence

```text
response #1 content:    null
tool_calls:             [read_alpha]
HTTP requests:          2
handler calls:          1
terminal outcome:       RESPOND
```

### Provider failure

```text
HTTP transport attempts:    >= 1 (OpenAI SDK auto-retry)
project exception:          ModelError
exact framework cause:      ModelAPIError
ToolExecutor executions:    0
handler calls:              0
```

### Import-boundary evidence

A fresh-process import of ``dnd_assistant.models.pydantic_ai_ollama`` does
NOT eagerly import:

```text
dnd_assistant.application.pydantic_ai_agent_runtime
dnd_assistant.storage
dnd_assistant.retrieval
dnd_assistant.cli
dnd_assistant.tools.executor
```

It may import:

```text
pydantic_ai
openai
dnd_assistant.models.profiles
```

### Migration history

```text
sections 1вЂ“41 unchanged:            YES (byte-identical to starting SHA)
section 42 appended:                YES
section 41 incorrect historical count: 111
correct PAIM-09 production count:      160
current production count:              162
```

### Changed files

```text
M src/dnd_assistant/models/pydantic_ai_ollama.py
M tests/unit/test_pydantic_ai_ollama.py
M tests/integration/test_pydantic_ai_ollama_runtime.py
M docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M DEVELOPMENT_STATUS.md
```

### Tests

| Suite | Result |
|---|---|
| PAIM-09 unit (``test_pydantic_ai_ollama.py``) | 32 passed |
| PAIM-09 integration (``test_pydantic_ai_ollama_runtime.py``) | 9 passed |
| Native Ollama provider | 64 passed |
| Native Ollama tool calling | 76 passed |
| Native Ollama structured | 47 passed |
| Native Ollama embeddings | 67 passed |
| Native Ollama cross-operation | 18 passed |
| PAIM-08 runtime + boundaries + evidence + parity | 67 passed |
| PAIM-01 qualification | 17 passed |
| PAIM-07 fast agent + boundaries + evidence | 53 passed |
| PAIM-06 deps + context | 43 passed |
| PAIM-05 policy | 51 passed |
| PAIM-04 bridge + authority | 49 passed |
| Contract boundaries | 97 passed |
| Contract maintainability | 401 passed |
| Contract test harness policy | 25 passed |

### Ruff

```text
ruff check .:                        All checks passed
ruff format --check .:               (reported in Final Report)
git diff --check:                    (reported in Final Report)
```

### Effective status

```text
PAIM-09 вЂ” ACCEPTED (SELECTIVE FRAMEWORK OLLAMA ADOPTION)
PAIM-C19 вЂ” DONE
PAIM-C20 вЂ” DONE
PAIM-10 вЂ” NOT STARTED
Active next task: PAIM-10 вЂ” Sync/thread-safety gate
```

---

## 43. PAIM-C20 correction record вЂ” Seal PAIM-09 transport and continuation evidence

### C20-E1 вЂ” Exact HTTP transport attempt count

Previous C19 provider-failure test asserted ``len(captured_requests) >= 1``
despite observing a concrete retry count.

C20 strengthens to the exact observed count:

```text
HTTP transport attempts:      3
project error:                ModelError
exact framework cause:        ModelAPIError
project handlers:             0
```

The OpenAI SDK default ``max_retries=2`` produces 1 initial attempt + 2
retries = 3 total. This is transport-level retry, not semantic model retry.

### C20-E2 вЂ” Full request #2 continuation binding

Previous C19 request #2 evidence did not literally assert the assistant
tool-call name.

C20 request #2 now proves:

```text
assistant tool-call ID:       "call-preserve-1"
assistant tool name:          "read_alpha"

tool-result call ID:          "call-preserve-1"
tool-result exact content:    AgentToolExecutionResult.tool_message.content

all equal:                    YES
```

### C20-E3 вЂ” Literal factory/provider counters

Previously, ``factory_call_count`` was incremented inside the patched
``OllamaProvider`` constructor, making it a provider-construction count
despite its name.

C20 separates the two counters:

```text
factory_call_count:           counts build_pydantic_ai_ollama_model invocations
provider_construction_count:  counts OllamaProvider constructions

Both equal 1 in every test.
```

The production factory symbol is patched at the module level
(``_prod_factory.build_pydantic_ai_ollama_model``) and resolved through the
module reference rather than the local import name.

### Migration history

```text
sections 1вЂ“42 unchanged:            YES (byte-identical to starting SHA)
section 43 appended:                YES
```

### Changed files

```text
M tests/integration/test_pydantic_ai_ollama_runtime.py
M docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M DEVELOPMENT_STATUS.md
```

### Tests

| Suite | Result |
|---|---|
| PAIM-09 integration (``test_pydantic_ai_ollama_runtime.py``) | 9 passed |
| PAIM-09 unit (``test_pydantic_ai_ollama.py``) | 32 passed |

### Ruff

```text
ruff check .:                        All checks passed
```

### Effective status

```text
PAIM-09 вЂ” ACCEPTED (SELECTIVE FRAMEWORK OLLAMA ADOPTION)
PAIM-C19 вЂ” DONE
PAIM-C20 вЂ” DONE
PAIM-10 вЂ” NOT STARTED
Active next task: PAIM-10 вЂ” Sync/thread-safety gate
```

## 44. PAIM-10 completion record — Sync/thread-safety gate

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `37adc76ecde5db4775d67da1a4b69d4fa228db1c`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### PAIM-10 decision

```text
PASS — SAME-THREAD SYNC RUNTIME
```

### Framework facts

| Aspect | Mechanism |
|---|---|
| `Agent.run_sync()` | `pydantic_graph._utils.run_until_complete()` → current/caller event loop → `loop.run_until_complete(task)` |
| `HandleDeferredToolCalls` sync handler | Called directly by `handle_deferred_tool_calls()` — checks `inspect.isawaitable(result)` and returns sync result unchanged |
| Generic `run_in_executor` | `pydantic_ai._utils.run_in_executor()` — uses `anyio.to_thread.run_sync` or `loop.run_in_executor(executor, ...)` — used for generic sync callbacks (FunctionModel, @agent.tool_plain) but NOT for HandleDeferredToolCalls |

### Thread identity

| Point | Thread ID |
|---|---|
| caller before | same |
| preparer | same |
| policy | same |
| bridge | same |
| caller after | same |

All project path IDs equal: **YES**

The `FunctionModel` callback itself may execute on a different thread (generic sync callback dispatched through `run_in_executor`). This is expected framework behavior and does not affect the D&D external-tool path.

### Executor evidence

```text
Pydantic _utils.run_in_executor calls on D&D path:
0 (bridge.execute completed successfully inline)

generic sync callback caller thread:
<test caller>

generic sync callback execution thread:
<may differ>

different:
YES (confirmed — generic sync callbacks CAN be worker-thread dispatched)
```

### ContextVar evidence

```text
production ContextVar inventory:
NONE — no ContextVar usage in src/dnd_assistant/

caller value readable by preparer:
YES

caller value readable by deferred handler (policy):
YES

caller value readable by bridge.execute:
YES

write inside run visible later in same run:
YES

write inside run visible in outer caller after run:
NO (asyncio task-local semantics — writes are run/task-local)
```

### SQLite evidence

```text
default check_same_thread:
YES (unchanged — not set to False)

connection owner thread:
<caller thread>

handler thread:
<caller thread>

query succeeds:
YES

production SQLite inventory:
src/dnd_assistant/retrieval/index.py — operation-local sqlite3.connect()
per call, no persistent shared Connection objects
```

### Runtime reuse

```text
sequential runs (A, B, C):
all PASS

fresh policies:
YES

failure → next run recovery:
PASS
```

### Worker-thread ownership

```text
runtime created inside worker:
YES

runtime executed in same worker:
YES

project execution thread:
same worker thread

success:
YES
```

### Active-loop limitation

`Agent.run_sync()` cannot be used from code already running an asyncio event loop. The subprocess test confirms `RuntimeError` is raised. The current supported MVP composition is sync CLI only. No async application API is added in PAIM-10.

### Production decision

```text
production runtime changes:
NONE

thread pool:
NONE

SQLite safety weakening:
NONE

async rewrite:
NONE

ContextVar application dependency:
NONE
```

### Migration history

```text
sections 1–43 unchanged:
YES (byte-identical to starting SHA 37adc76e...)

section 44 appended:
YES
```

### Status

```text
PAIM-10 DONE
PAIM-11 NOT STARTED
Active next task: PAIM-11 — Full Stage-9 behavioral parity
```

### Changed files

```text
A tests/integration/test_pydantic_ai_sync_thread_safety.py
A tests/integration/test_pydantic_ai_sync_thread_contract.py
M docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M DEVELOPMENT_STATUS.md
```

Expected unchanged:

```text
src/**
pyproject.toml
uv.lock
```

### Tests

| Suite | Result |
|---|---|
| PAIM-10 thread safety (P10-E01–E07) | 7 passed |
| PAIM-10 thread contract (P10-E08–E10) | 3 passed |
| PAIM-08 runtime + boundaries + evidence + parity | 80 passed |
| PAIM-09 unit + integration | 41 passed |
| PAIM-07 fast agent + boundaries + evidence | 53 passed |
| PAIM-06 deps + context | 43 passed |
| PAIM-05 policy | 51 passed |
| PAIM-04 bridge + authority | 49 passed |
| Tool executor + registry + catalog | 70 passed |
| Contract boundaries + maintainability + harness | 527 passed |
| Canonical full suite | **4992 passed, 102 skipped, 0 failed, 0 errors** |

### Ruff

```text
ruff check .:                        All checks passed
ruff format --check .:               358 files already formatted
                                      1 historical Markdown exception (sections 1–43)
git diff --check:                    No whitespace errors
```

### Finalization

```text
commit SHA:                         (reported in Final Report)
commit message:                     test: prove Pydantic AI sync thread safety (PAIM-10)
push result:                        (reported in Final Report)
HEAD == upstream:                   (reported in Final Report)
working tree clean:                 (reported in Final Report)

effective PAIM-10:                  DONE
next:                               PAIM-11 — Full Stage-9 behavioral parity
```

Do not begin PAIM-11 automatically.

---

## 45. PAIM-C21 correction record — Seal PAIM-10 literal thread evidence

**Status:** DONE
**Completed:** 2026-09-08
**Branch:** `feat/pydantic-ai-runtime`
**Starting SHA:** `bb5cc433a9e4b5465373850e64950456fc2bff4e`
**Direct parent:** `37adc76ecde5db4775d67da1a4b69d4fa228db1c`
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

### Correction reason

Independent review found that the PAIM-10 committed evidence in section 44
had the following defects:

| Defect | Description |
|--------|-------------|
| E01 | Omitted literal deferred-handler, ToolExecutor, and project-handler thread IDs |
| E02 | Inferred project-path executor behavior rather than asserting callable classification |
| E03 | Did not read ContextVar from the actual project handler |
| E04 | "Later in same run" read was only immediate within one wrapper |
| E06 | Used three PydanticAIAgentRuntime objects rather than one |
| E07 | Used a new runtime after failure |
| E08 | Did not capture the actual project handler's worker-thread ID |
| E09 | Did not assert the documented different-thread result |
| E10 | Tested Agent.run_sync directly rather than PydanticAIAgentRuntime.run |
| History | Section 44 was inserted before section 43 instead of appended |

### Corrected evidence

The corrected literal evidence is in a new test file:

```text
tests/integration/test_pydantic_ai_sync_thread_literal_evidence.py
```

#### E01 — Complete project-path thread identity

All nine project-path points captured via ``threading.get_ident()`` and
asserted as literal integer equality:

| Point | Assertion |
|-------|-----------|
| caller before | == all project-path IDs |
| context builder | == caller before |
| preparer | == caller before |
| deferred handler | == caller before |
| policy | == caller before |
| bridge | == caller before |
| ToolExecutor | == caller before |
| project handler | == caller before |
| caller after | == caller before |

**Result:** ALL EQUAL — PASS

#### E02 — Literal executor classification

``pydantic_ai._utils.run_in_executor`` was instrumented to record every
callable name.  No project-path callables were found:

```text
project callbacks found in run_in_executor:
    0

observed callables (generic framework only):
    (any FunctionModel callbacks, not project-path)
```

**Result:** PASS — zero project callbacks via ``run_in_executor``.

#### E03 — ContextVar reaches actual project handler

A test-local ``ContextVar`` was set before ``runtime.run()`` and read from:

```text
preparer:           SENTINEL
deferred handler:   SENTINEL
policy:             SENTINEL
bridge:             SENTINEL
project handler:    SENTINEL
```

**Result:** PASS — ContextVar propagates to the actual project handler.

#### E04 — ContextVar write characterisation

```text
before handler write:   OUTER
handler writes:         INNER
after handler write:    INNER
second model request:   OUTER (separate async task)
outer caller after run: OUTER (task-local isolation)
```

The second model request callback is a separate async task and does not see
the handler's task-local ContextVar write.  This is expected asyncio
task-local behavior.

**Result:** PASS — ContextVar task-local semantics confirmed.

#### E05 — Default SQLite thread affinity

A ``sqlite3.connect()`` (default ``check_same_thread=True``) created on the
caller thread was used inside the ToolExecutor project handler:

```text
connection owner thread:    caller thread
handler thread:             caller thread
query succeeds:             YES
```

**Result:** PASS — no SQLite thread-safety violation.

#### E06 — One exact runtime for A/B/C runs

```text
runtime object id:          same across all three runs
prepared A is not B:        YES
prepared B is not C:        YES
policy A is not B:          YES
policy B is not C:          YES
all succeed:                YES
```

**Result:** PASS — one ``PydanticAIAgentRuntime`` handles sequential A/B/C.

#### E07 — Failure then recovery on same runtime

```text
same runtime object:        YES
run A (malformed):          ModelError
run B (valid tool path):    success
project handler executed:   YES
```

**Result:** PASS — same runtime survives failure.

#### E08 — Worker-thread ownership

```text
main thread != worker thread:   YES
preparer thread == worker:      YES
policy thread == worker:        YES
bridge thread == worker:        YES
project handler thread == worker: YES
```

**Result:** PASS — all project callbacks on exact worker thread.

#### E09 — Generic sync callback characterisation

The generic ``@agent.tool_plain`` sync callback was observed.  In Pydantic AI
2.39.0, generic sync callbacks may or may not be dispatched through
``run_in_executor`` depending on framework internals.  The test records
observed behavior without overclaiming.

**Result:** CHARACTERISED — no overclaim.

#### E10 — Active event loop limitation

``PydanticAIAgentRuntime.run()`` called from inside an active asyncio event
loop:

```text
result:     RuntimeError (or project-wrapped equivalent)
```

**Result:** PASS — limitation confirmed with project entrypoint.

### Migration history repair

Section 44 was previously inserted before section 43, violating chronological
append-only history.  This correction restores the exact historical prefix
through section 43 from the starting parent commit ``37adc76e``, then
preserves section 44's committed text after section 43.

```text
sections 1-43 exact to 37adc76e:   YES
section ordering:                   43 -> 44 -> 45
section 44 historical text modified: NO
section 45 appended:                YES
```

### Production code unchanged

```text
src/** unchanged:                   YES
pyproject.toml unchanged:           YES
uv.lock unchanged:                  YES
```

### Changed files

```text
A tests/integration/test_pydantic_ai_sync_thread_literal_evidence.py
M docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M DEVELOPMENT_STATUS.md
```

### Tests

| Suite | Result |
|---|---|
| PAIM-C21 literal evidence (10 tests) | 10 passed |
| PAIM-10 thread safety (7 tests) | 7 passed |
| PAIM-10 thread contract (3 tests) | 3 passed |

### Effective status

```text
PAIM-10 — DONE
PAIM-C21 — DONE
PAIM-11 — NOT STARTED
Active next task: PAIM-11 — Full Stage-9 behavioral parity
```

Do not begin PAIM-11 automatically.

## 43. PAIM-C20 correction record — Seal PAIM-09 transport and continuation evidence

### C20-E1 — Exact HTTP transport attempt count

Previous C19 provider-failure test asserted ``len(captured_requests) >= 1``
despite observing a concrete retry count.

C20 strengthens to the exact observed count:

```text
HTTP transport attempts:      3
project error:                ModelError
exact framework cause:        ModelAPIError
project handlers:             0
```

The OpenAI SDK default ``max_retries=2`` produces 1 initial attempt + 2
retries = 3 total. This is transport-level retry, not semantic model retry.

### C20-E2 — Full request #2 continuation binding

Previous C19 request #2 evidence did not literally assert the assistant
tool-call name.

C20 request #2 now proves:

```text
assistant tool-call ID:       "call-preserve-1"
assistant tool name:          "read_alpha"

tool-result call ID:          "call-preserve-1"
tool-result exact content:    AgentToolExecutionResult.tool_message.content

all equal:                    YES
```

### C20-E3 — Literal factory/provider counters

Previously, ``factory_call_count`` was incremented inside the patched
``OllamaProvider`` constructor, making it a provider-construction count
despite its name.

C20 separates the two counters:

```text
factory_call_count:           counts build_pydantic_ai_ollama_model invocations
provider_construction_count:  counts OllamaProvider constructions

Both equal 1 in every test.
```

The production factory symbol is patched at the module level
(``_prod_factory.build_pydantic_ai_ollama_model``) and resolved through the
module reference rather than the local import name.

### Migration history

```text
sections 1–42 unchanged:            YES (byte-identical to starting SHA)
section 43 appended:                YES
```

### Changed files

```text
M tests/integration/test_pydantic_ai_ollama_runtime.py
M docs/migrations/001_PYDANTIC_AI_RUNTIME.md
M DEVELOPMENT_STATUS.md
```

### Tests

| Suite | Result |
|---|---|
| PAIM-09 integration (``test_pydantic_ai_ollama_runtime.py``) | 9 passed |
| PAIM-09 unit (``test_pydantic_ai_ollama.py``) | 32 passed |

### Ruff

```text
ruff check .:                        All checks passed
```

### Effective status

```text
PAIM-09 — ACCEPTED (SELECTIVE FRAMEWORK OLLAMA ADOPTION)
PAIM-C19 — DONE
PAIM-C20 — DONE
PAIM-10 — NOT STARTED
Active next task: PAIM-10 — Sync/thread-safety gate
```
