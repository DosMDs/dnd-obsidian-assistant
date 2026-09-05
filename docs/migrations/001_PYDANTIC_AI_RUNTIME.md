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
PAIM-01 — Candidate dependency/framework qualification
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
