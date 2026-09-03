# Stage 8 — Model Gateway / Ollama

## Stage objective

Establish the provider-neutral ModelGateway typed contract, implement the
Ollama provider, and integrate it with the existing Tool Layer handshake.

## Architectural boundaries

- ModelGateway is a `typing.Protocol` — concrete providers are replaceable.
- All five canonical operations are synchronous for MVP.
- Provider-neutral DTOs live in `dnd_assistant.models.types` with no
  imports from storage, retrieval, application, CLI, or Ollama.
- `chat_with_tools()` accepts `ToolPublicDefinition` via TYPE_CHECKING-only
  import to keep the gateway module lightweight.
- Provider/network failures surface as `ModelError` (existing in `errors.py`).
- No Fast Agent, no tool execution, no prompt templates in this stage.

## Pre-Stage-8 base

```
9bca669894b2ae12a62381a2f7b6a5447c44e9cd
```

## Sync MVP decision

Stage 1 deferred the sync/async decision until Stage 8.  The Stage-8 MVP
ModelGateway is **synchronous** (`def`, not `async def`).

Rationale:

- Current Typer/application/runtime stack is synchronous.
- Current trusted Python services and ToolExecutor are synchronous.
- httpx already supports synchronous transport.
- Introducing async through the whole application would add complexity
  without an MVP requirement.
- A future async provider/gateway may be added separately without changing
  this MVP contract retroactively.

## Provider-neutral gateway contract

Five canonical synchronous operations:

| Operation | Input | Output |
|---|---|---|
| `chat` | `ChatRequest` | `ChatResponse` |
| `chat_with_tools` | `ChatRequest` + `list[ToolPublicDefinition]` | `ToolAwareResponse` |
| `generate_structured` | `ChatRequest` + `type[T]` (Pydantic) | `T` |
| `embed` | `list[str]` | `list[list[float]]` |
| `health` | — | `ModelHealth` |

## Stage-7 ToolPublicDefinition handshake

`chat_with_tools()` consumes `ToolPublicDefinition` from the Tool Layer
via a `TYPE_CHECKING`-only import in `gateway.py`.  This ensures:

- Runtime import of `dnd_assistant.models.gateway` does not eagerly load
  `dnd_assistant.tools`, storage, retrieval, application, CLI, or Ollama.
- The existing boundary tests (`test_gateway_does_not_import_tools`, etc.)
  continue to pass.

## S8 task map

| Task | Status | Notes |
|---|---|---|
| **S8-00** | **DONE** | Provider-neutral typed ModelGateway contracts + sync decision |
| S8-01 | NOT STARTED | Model profile schemas + machine profile loader |
| S8-02 | NOT STARTED | Ollama transport + health + plain chat |
| S8-03 | NOT STARTED | Ollama structured generation |
| S8-04 | NOT STARTED | Ollama native tool-calling adapter |
| S8-05 | NOT STARTED | Ollama embeddings |
| S8-06 | NOT STARTED | Provider integration / error hardening / opt-in smoke coverage |
| S8-07 | NOT STARTED | Full Stage-8 historical review / completion |

Correction passes:

| Task | Status | Notes |
|---|---|---|
| S8-C00 | **DONE** | Harden ModelGateway plain-chat and JSON tool-call contracts |

## S8-00 implementation record

### Changed files

- `src/dnd_assistant/models/types.py` — new: provider-neutral DTOs
- `src/dnd_assistant/models/gateway.py` — rewritten: ModelGateway Protocol
- `src/dnd_assistant/models/__init__.py` — updated: public exports
- `tests/unit/test_model_gateway_contracts.py` — new: 64 tests
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md` — new: this document
- `docs/stages/README.md` — updated: Stage-8 index entry
- `DEVELOPMENT_STATUS.md` — updated: Stage 8 IN PROGRESS

### Quality-gate evidence

- 64 passed (gateway contract tests)
- 97 passed (boundary tests) — zero diff in `test_boundaries.py`
- 284 passed (maintainability tests) — no ceiling changes
- 25 passed (test harness policy tests)
- Full pytest suite: 3752 passed, 95 skipped, 0 failed, 0 errors
- Ruff check: All checks passed
- Ruff format: 279 files already formatted

## S8-C00 correction record

**Reviewed SHA:** `1040880543c9a3589cee569e92a810a7ed0ce4c5` (S8-00 implementation commit)

### Defects found

1. **ChatResponse plain-chat semantics** — `ChatResponse` accepted assistant messages containing `tool_calls`, even though `chat()` is the plain-chat operation. Tool-calling responses belong in `ToolAwareResponse` (returned by `chat_with_tools()`).

2. **Non-finite float values in ToolCall.arguments** — `ToolCall.arguments: dict[str, JsonValue]` accepted `float("nan")`, `float("inf")`, and `float("-inf")` without rejection. These are not valid JSON values and must be rejected recursively at any nesting depth.

### Production fixes

**File:** `src/dnd_assistant/models/types.py`

- **ChatResponse fix:** Added `@model_validator(mode="after")` method `_no_tool_calls` that raises `ValueError` if `self.message.tool_calls` is non-empty. This rejects both `tool_calls-only` and `content + tool_calls` assistant messages while preserving the existing `_role_is_assistant` validator.

- **ToolCall strict JSON fix:** Added `_reject_non_finite()` recursive validator function that traverses dicts and lists to reject `NaN`, `+Infinity`, and `-Infinity` at any nesting depth. Created `FiniteJsonValue = Annotated[JsonValue, AfterValidator(_reject_non_finite)]` type alias and changed `ToolCall.arguments` type from `dict[str, JsonValue]` to `dict[str, FiniteJsonValue]`.

### Regression coverage added

**File:** `tests/unit/test_model_gateway_contracts.py` (76 total tests, +12 from S8-00)

- `TestChatResponse.test_tool_calls_only_rejected` — ASSISTANT + tool_calls only rejected
- `TestChatResponse.test_text_and_tool_calls_rejected` — ASSISTANT + content + tool_calls rejected
- `TestToolCall.test_nan_at_top_level_rejected` — NaN at top level
- `TestToolCall.test_infinity_at_top_level_rejected` — +Infinity at top level
- `TestToolCall.test_neg_infinity_at_top_level_rejected` — -Infinity at top level
- `TestToolCall.test_non_finite_nested_in_dict_rejected` — NaN nested in dict
- `TestToolCall.test_non_finite_nested_in_list_rejected` — Infinity nested in list
- `TestToolCall.test_deeply_nested_non_finite_rejected` — -Infinity deeply nested
- `TestToolCall.test_valid_nested_json_accepted` — all valid JSON types accepted (None, bool, int, finite float, str, list, dict)
- `TestMultiToolTurnRepresentation` (3 tests) — multi-tool assistant turn with distinct `call_id` values and corresponding TOOL messages

### Verification commands and results

```
uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 284 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3752 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 279 files already formatted

git diff --check
→ no whitespace errors
```

### Scope audit

**Intended scope:** `src/dnd_assistant/models/types.py`, `tests/unit/test_model_gateway_contracts.py`, `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`, `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `src/dnd_assistant/models/types.py`
- `tests/unit/test_model_gateway_contracts.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:** `src/dnd_assistant/models/gateway.py`, `src/dnd_assistant/domain/`, `src/dnd_assistant/storage/`, `src/dnd_assistant/retrieval/`, `src/dnd_assistant/application/`, `src/dnd_assistant/tools/`, `src/dnd_assistant/cli/`, `src/dnd_assistant/errors.py`, `tests/contract/test_boundaries.py`, `tests/contract/test_maintainability.py`, `tests/contract/test_test_harness_policy.py`, `pyproject.toml`, `uv.lock`

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- `TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"]` (1477): unchanged
- `src/dnd_assistant/models/types.py`: 214 lines (under 700)
- `tests/unit/test_model_gateway_contracts.py`: 610 lines (under 1000)
- No new correction-history filenames created

### Remaining invariants

- Exactly 5 synchronous ModelGateway operations preserved
- `generate_structured` remains generic (`schema: type[T] -> T`)
- Gateway runtime imports remain lightweight (verified by boundary tests)
- `ToolAwareResponse` still accepts text-only, tool-calls-only, and text+tool-calls
- `ChatMessage` assistant role still permits tool calls (needed for `chat_with_tools()` and future Stage-9 conversation history)
- `call_id` remains optional (provider-neutral)
- S8-01 remains NOT STARTED
- Stage 9 remains NOT STARTED

## S8-C01 correction record

**Review base SHA:** `f3c8e00e0d8aa584541faa458b800230163e1b9f`

**Reviewed S8-C00 SHA:** `f3c8e00e0d8aa584541faa458b800230163e1b9f` (S8-C00 is the HEAD commit)

**Reason for correction:** Independent review of S8-C00 found two documentation/evidence defects in the Stage-8 document that were not resolved during S8-C00:

1. Stale S8-00 quality-gate placeholders remained unresolved (three `(reported in Final Report)` entries).
2. Physical-line counts in the Maintainability section (types.py: 218, test_model_gateway_contracts.py: 608) contradicted the S8-C00 Final Report (types.py: 214, test_model_gateway_contracts.py: 610).

**Stale placeholders found:**

Three entries in the S8-00 Quality-gate evidence section:

```
- Full pytest suite: (reported in Final Report)
- Ruff check: (reported in Final Report)
- Ruff format: (reported in Final Report)
```

**How each placeholder was resolved:**

Replaced with actual verification results from the S8-C01 verification run on the current HEAD (`f3c8e00`):

```
- Full pytest suite: 3752 passed, 95 skipped, 0 failed, 0 errors
- Ruff check: All checks passed
- Ruff format: 279 files already formatted
```

**Exact physical-line counting method:**

```python
from pathlib import Path
for path in (
    Path("src/dnd_assistant/models/types.py"),
    Path("tests/unit/test_model_gateway_contracts.py"),
):
    print(path, len(path.read_bytes().splitlines()))
```

This matches the maintainability test semantics: `len(path.read_bytes().splitlines())`.

**Corrected counts:**

- `src/dnd_assistant/models/types.py`: **214** (was 218 in Stage document, was 214 in Final Report)
- `tests/unit/test_model_gateway_contracts.py`: **610** (was 608 in Stage document, was 610 in Final Report)

**Verification commands and results:**

```
uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 284 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3752 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 279 files already formatted

git diff --check
→ no whitespace errors
```

**Actual changed-file inventory (from Git):**

- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**Scope audit:**

Zero diff in:
- `src/dnd_assistant/` (all production code)
- `tests/` (all test code)
- `pyproject.toml`
- `uv.lock`
- `.gigacode/`
- `.gigacode_vsc/`

No maintainability ceiling changes. No boundary-test changes. No test-harness changes. No S8-01 implementation. No Ollama implementation. No Fast Agent implementation.

**Commit SHA after finalization:** (reported in Final Report)