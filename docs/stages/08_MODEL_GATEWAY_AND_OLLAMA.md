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
| **S8-01** | **DONE** | Model profile schemas + machine profile loader |
| **S8-02** | **DONE** | Ollama transport + health + plain chat |
| **S8-03** | **DONE** | Ollama structured generation |
| S8-04 | **DONE** | Ollama native tool-calling adapter |
| S8-05 | **DONE** | Ollama embeddings |
| S8-06 | NOT STARTED | Provider integration / error hardening / opt-in smoke coverage |
| S8-07 | NOT STARTED | Full Stage-8 historical review / completion |

Correction passes:

| Task | Status | Notes |
|---|---|---|
| S8-C00 | **DONE** | Harden ModelGateway plain-chat and JSON tool-call contracts |
| S8-C01 | **DONE** | Correct Stage-8 verification evidence |
| S8-C02 | **DONE** | Harden ModelProfile base_url endpoint validation |
| S8-C03 | **DONE** | Harden Ollama health and JSON response validation |
| S8-C04 | **DONE** | Correct S8-03 verification evidence and Stage-8 correction index |
| S8-C05 | **DONE** | Harden tool-call structural validation and restore test-harness scope |
| S8-C06 | **DONE** | Harden embedding numeric conversion against oversized JSON integers |

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

**Commit SHA after finalization:** Reported in the S8-C01 Final Report (not embedded in the commit itself).

## S8-01 implementation record

**Starting SHA:** `c708a4820ff22eecf2ebefd52fa03119d43479b6`

**Branch:** `main`

### Scope

Implement typed configuration for runtime model profiles and a deterministic
TOML loader for the machine-local configuration file.

### Profile schema decisions

**ModelProfileRole** — a `StrEnum` with three MVP roles:
- `AGENT = "agent"`
- `SUMMARIZER = "summarizer"`
- `EMBEDDING = "embedding"`

**ModelProfile** — a strict Pydantic model (`extra="forbid"`, `frozen=True`)
with these fields:

| Field | Type | Required | Validation |
|---|---|---|---|
| `provider` | `str` | Yes | Non-empty, not whitespace-only |
| `model` | `str` | Yes | Non-empty, not whitespace-only |
| `base_url` | `str` | Yes | Must start with `http://` or `https://`, must have a host |
| `temperature` | `float \| None` | No | Finite, non-NaN, non-negative |
| `keep_alive` | `str \| None` | No | If provided, non-empty and not whitespace-only |
| `role` | `ModelProfileRole` | Yes | Must be a valid role value |

### Provider-neutrality decision

The `provider` field is a plain `str` with only non-empty validation.
A hypothetical valid provider such as `test-provider` is representable.
No `Literal["ollama"]` restriction — S8-02 may reject non-Ollama profiles
when constructing an Ollama provider.

### Model-name decision

The `model` field is a plain `str` with only non-empty validation.
No hardcoded default model. No concrete model-name dependency in tests.

### Machine/campaign config boundary

Machine configuration lives outside the Vault. The loader is explicitly
path-driven (`load_model_profiles(path: Path)`) and does not access
`~/.config`, `campaign.yaml`, the Vault, or any environment-specific paths.

### TOML loader contract

```python
def load_model_profiles(path: Path) -> ModelProfilesConfig:
```

Uses Python 3.12+ `tomllib` — no new dependency required.

### Top-level machine-config extensibility

The loader parses the full TOML document but only validates the `[profiles.*]`
subsection. Unrelated top-level sections (e.g. `[timeouts]`, `[cache]`) are
intentionally ignored. Unknown keys **inside a profile** are still rejected
via Pydantic's `extra="forbid"`.

### Error mapping

| Condition | Exception | Cause chain |
|---|---|---|
| File does not exist | `NotFoundError` | `FileNotFoundError` |
| Filesystem read failure | `StorageError` | `OSError` (e.g. `PermissionError` on directory) |
| Malformed TOML | `ValidationError` | `tomllib.TOMLDecodeError` |
| Missing `profiles` section | `ValidationError` | — |
| `profiles` not a table/object | `ValidationError` | — |
| Empty profiles mapping | `ValidationError` | — |
| Profile schema violation | `ValidationError` | Pydantic `ValidationError` |
| Invalid role | `ValidationError` | Pydantic `ValidationError` |

No `ModelError` is used for configuration parsing — `ModelError` remains the
model/provider interaction boundary.

### Cross-platform behavior

All implementation uses portable Python APIs (`pathlib.Path`, `tomllib`,
UTF-8). Tests use `tmp_path`, not actual user directories. On Windows,
a directory path raises `StorageError` (via `PermissionError`/`OSError`).

### Tests and quality-gate evidence

```
uv run pytest tests/unit/test_model_profiles.py -v
→ 66 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 284 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ full suite: 0 failed, 0 errors

uv run ruff check .
→ All checks passed

uv run ruff format --check .
→ All files already formatted

git diff --check
→ no whitespace errors
```

### Explicit S8-02+ deferrals

The following are explicitly deferred to S8-02 or later:
- OllamaModelProvider implementation
- Ollama HTTP transport (`/api/chat`, `/api/embed`)
- Health requests and model availability probing
- Tool-schema conversion and structured generation transport
- Native Ollama tool calling
- Embeddings transport
- Fast Agent
- ToolExecutor integration
- Prompt templates
- Model benchmarking
- `dnd doctor` integration
- Session runtime model loading
- Home-directory / CLI default machine-path resolution

## S8-02 implementation record

**Starting SHA:** `fa92750bc2669602e96bf9e1111153e727eff656`

**Branch:** `main`

### Official Ollama endpoints used

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/version` | GET | Ollama reachability / health |
| `/api/tags` | GET | Configured model availability |
| `/api/chat` | POST | Plain (non-tool) multi-turn chat |

### Partial-provider decision

S8-02 implements only `chat()` and `health()` of the eventual five-operation
Ollama ModelGateway implementation.

No placeholder/future methods were added:

- `chat_with_tools` — not implemented, not stubbed
- `generate_structured` — not implemented, not stubbed
- `embed` — not implemented, not stubbed

### HTTP/client ownership decision

`OllamaModelProvider` owns a synchronous `httpx.Client` created on
construction.  An explicit `close()` method releases resources.  No async,
no asyncio, no persistent connection pooling beyond the client's default.

### Profile/provider validation

Constructor rejects non-Ollama profiles:

```python
if profile.provider != "ollama":
    raise ValidationError(...)
```

Uses the existing `dnd_assistant.errors.ValidationError`.  No hardcoded
model name — the profile is the configuration source.

### Endpoint path-preservation strategy

Uses `urllib.parse.urljoin` with a trailing-slash base URL to preserve
existing path prefixes:

```python
urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
```

For `base_url = "https://provider.example/ollama"`:

- `_url("/api/version")` → `https://provider.example/ollama/api/version`
- `_url("/api/chat")` → `https://provider.example/ollama/api/chat`

### Health semantics

Two-step deterministic flow:

1. **GET /api/version** — determines Ollama reachability.
2. **GET /api/tags** — determines configured-model availability.

### Exact model availability matching

Uses exact string match against each entry's `model` and `name` fields.
No fuzzy matching.  No `ollama pull` or automatic model installation.

### Healthy result

```python
ModelHealth(reachable=True, model_available=True)
```

### Missing-model result

```python
ModelHealth(reachable=True, model_available=False, detail="configured model not installed")
```

### Unreachable result

```python
ModelHealth(reachable=False, model_available=False)
```

### HTTP-health failure behavior

Non-success HTTP response from `/api/version` or `/api/tags`:

```python
ModelHealth(reachable=True, model_available=False, detail="HTTP {status} from /api/...")
```

### Malformed-health response behavior

Non-JSON, missing fields, or wrong structure from either endpoint:

```python
ModelHealth(reachable=True, model_available=False, detail="invalid ...")
```

### Plain-chat request payload shape

```json
{
  "model": "<profile.model>",
  "messages": [{"role": "...", "content": "..."}],
  "stream": false
}
```

### `stream=false` confirmation

`"stream": false` is always sent — the MVP gateway is synchronous.

### Temperature mapping

When `profile.temperature is not None`, included inside `"options"`:

```json
"options": {"temperature": 0.7}
```

When `None`, the `"options"` key is omitted entirely.

### `keep_alive` mapping

When `profile.keep_alive is not None`, included at top level:

```json
"keep_alive": "30m"
```

When `None`, the field is omitted.

### Message-role mapping

| Provider-neutral | Ollama JSON |
|---|---|
| `SYSTEM` | `{"role": "system", "content": "..."}` |
| `USER` | `{"role": "user", "content": "..."}` |
| `ASSISTANT` | `{"role": "assistant", "content": "..."}` |

`TOOL` role and assistant `tool_calls` are rejected before any HTTP request.

### Plain-chat tool-history rejection behavior

`chat()` raises `ModelError` before making an HTTP request if:

- Any message has `role == TOOL`
- Any assistant message has non-empty `tool_calls`

### Confirmation rejected tool history makes no HTTP request

The test `test_assistant_with_tool_calls_rejected` verifies via `respx`
that the `/api/chat` route was never called.

### Valid ChatResponse mapping

```python
ChatResponse(
    message=ChatMessage(
        role=MessageRole.ASSISTANT,
        content="Hello.",
    )
)
```

### Thinking-field behavior

Provider-specific `message.thinking` is ignored — not copied into
`content` and not exposed through provider-neutral DTOs.

### Unexpected tool_calls response behavior

If Ollama returns non-empty `message.tool_calls` in a plain chat response,
`ModelError` is raised with a clear diagnostic.

### Connection failure error mapping

`httpx.ConnectError` → `ModelError` with `cause=` chain.

### Timeout error mapping

`httpx.TimeoutException` → `ModelError` with `cause=` chain.

### HTTP 4xx mapping

HTTP 400/404 → `ModelError` with status code in diagnostic.

### HTTP 5xx mapping

HTTP 500/502 → `ModelError` with status code in diagnostic.

### Non-JSON response mapping

Non-JSON HTTP body → `ModelError("Ollama chat returned non-JSON response")`.

### Malformed message mapping

Missing `message` field, wrong type, or empty content → `ModelError`.

### Representative cause-chain proof

```python
httpx.ConnectError → ModelError.__cause__ (verified in test)
httpx.TimeoutException → ModelError.__cause__ (verified in test)
```

### Confirmation no raw httpx/Pydantic errors escape chat()

All provider/network/response failures surface as `ModelError`.  No raw
`httpx.RequestError`, `httpx.TimeoutException`, `httpx.HTTPStatusError`,
`json.JSONDecodeError`, or Pydantic `ValidationError` escapes the public
`chat()` boundary.

### Confirmation no automatic model pull/fallback

`health()` reports `model_available=False` for missing models.
`chat()` raises `ModelError` for a missing model (via HTTP 404 from Ollama).
No `ollama pull`, no `POST /api/pull`, no fallback to another model.

### Confirmation no running Ollama required by normal tests

All tests use `respx` to mock HTTP.  No real network, no Ollama, no Vault.

### Test/mock strategy

- `respx.mock` for HTTP mocking.
- Synchronous `httpx.Client` owned by the provider.
- Each test creates a fresh provider instance and closes it.

### Quality-gate evidence

```
uv run pytest tests/unit/test_ollama_provider.py -v
→ 56 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 290 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3887 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 283 files already formatted

git diff --check
→ no whitespace errors
```

### Scope audit

**Intended scope:**
- `src/dnd_assistant/models/ollama.py` — new
- `tests/unit/test_ollama_provider.py` — new
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md` — updated
- `DEVELOPMENT_STATUS.md` — updated

**Actual changed files (from Git):**
- `src/dnd_assistant/models/ollama.py`
- `tests/unit/test_ollama_provider.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/unit/test_model_profiles.py`
- `tests/contract/`
- `pyproject.toml`
- `uv.lock`

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- `TEST_LEGACY_EXCEPTIONS`: unchanged
- `src/dnd_assistant/models/ollama.py`: 378 lines (under 700)
- `tests/unit/test_ollama_provider.py`: 895 lines (under 1000)
- No new correction-history filenames created
- No new maintainability exceptions added

### S8-03+ deferrals

- S8-03 (structured generation): NOT STARTED
- S8-04 (native tool calling): NOT STARTED
- S8-05 (embeddings): NOT STARTED
- S8-06 (provider integration): NOT STARTED
- S8-07 (Stage-8 review): NOT STARTED
- Stage 9 (Fast Agent): NOT STARTED

## S8-C02 correction record

**Reviewed S8-01 SHA:** `0a61ea4c22642481a782060c1a0b7e40aad72a5f`

### Defect found

The S8-01 `_validate_http_url` function used `str.startswith` and `str.split`
to validate `base_url`. This did not actually verify that a usable hostname
was present. The following malformed values passed validation:

```text
http:///api
https://?query=value
http://\ \ \   (whitespace-only host)
http://#fragment
http://localhost:not-a-port
```

These are not valid machine-provider endpoints because they have no usable
host or contain an invalid port.

### Production fix

**File:** `src/dnd_assistant/models/profiles.py`

Replaced the string-based validation with `urllib.parse.urlsplit` from the
standard library. No new dependency was added.

The validator now deterministically verifies:

1. scheme is exactly `http` or `https` (preserved from S8-01).
2. network location (netloc) is structurally present.
3. a non-empty, non-whitespace hostname exists.
4. when a port is provided, it is a valid integer.

No DNS lookup, HTTP request, or socket connection is performed.

### Provider neutrality preserved

The endpoint contract remains HTTP(S)-only, not Ollama-specific. No
hardcoded `localhost` or `11434` defaults were introduced. Provider names
(`ollama`, `test-provider`, `future-provider`) are unaffected.

### All other S8-01 behavior preserved

- `ModelProfileRole` enum: unchanged.
- `ModelProfile` fields: `provider`, `model`, `base_url`, `temperature`,
  `keep_alive`, `role` — unchanged.
- `ModelProfilesConfig` collection: unchanged.
- `load_model_profiles` loader: unchanged.
- Error mapping: `ValidationError` for profile validation failures.
- `extra="forbid"`, `frozen=True`: unchanged.
- No concrete model-name dependency: unchanged.
- TOML loader tolerates unrelated top-level sections: unchanged.

### Regression coverage

**File:** `tests/unit/test_model_profiles.py` (73 total tests, +7 from S8-01)

Added to `TestModelProfileBaseUrl`:

| Test | What it covers |
|---|---|
| `test_slash_slash_api_rejected` | `http:///api` — no netloc |
| `test_query_only_host_rejected` | `https://?query=value` — no netloc |
| `test_whitespace_host_rejected` | `http://   ` — whitespace-only hostname |
| `test_fragment_only_host_rejected` | `http://#fragment` — no netloc |
| `test_malformed_port_rejected` | `http://localhost:not-a-port` — invalid port |
| `test_endpoint_with_path_accepted` | `https://provider.example/ollama` — path accepted |

Added to `TestLoadModelProfilesFailures`:

| Test | What it covers |
|---|---|
| `test_invalid_base_url_via_loader` | TOML loader maps invalid URL to `DndValidationError` |

Updated existing `test_scheme_only_rejected` match pattern from `"no host"`
to `"no network location"` to match the new error message.

### Verification commands and results

```
uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 287 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3828 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 281 files already formatted

git diff --check
→ no whitespace errors
```

### Direct diagnostic proof

All required malformed URLs rejected:

```text
http:///api                → base_url has no network location (host)
https://?query=value       → base_url has no network location (host)
http://\ \ \ (whitespace)  → base_url has no usable hostname
http://#fragment           → base_url has no network location (host)
http://localhost:not-a-port → base_url has an invalid port
```

All required valid URLs accepted:

```text
http://localhost:11434
http://192.168.1.50:11434
https://some-provider.example
https://provider.example/ollama
```

No DNS lookup, HTTP request, or socket connection performed.

TOML invalid `base_url` maps to `DndValidationError` (not raw Pydantic exception).

### Scope audit

**Intended scope:** `src/dnd_assistant/models/profiles.py`, `tests/unit/test_model_profiles.py`, `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`, `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `src/dnd_assistant/models/profiles.py`
- `tests/unit/test_model_profiles.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:** `src/dnd_assistant/models/types.py`, `src/dnd_assistant/models/gateway.py`, `src/dnd_assistant/models/__init__.py`, `src/dnd_assistant/domain/`, `src/dnd_assistant/storage/`, `src/dnd_assistant/retrieval/`, `src/dnd_assistant/application/`, `src/dnd_assistant/tools/`, `src/dnd_assistant/cli/`, `tests/unit/test_model_gateway_contracts.py`, `tests/contract/`, `pyproject.toml`, `uv.lock`

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- `TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"]` (1477): unchanged
- `src/dnd_assistant/models/profiles.py`: 242 lines (under 700)
- `tests/unit/test_model_profiles.py`: 853 lines (under 1000)
- No new correction-history filenames created
- No new maintainability exceptions added

### Remaining invariants

- No S8-02 implementation (Ollama transport, health, plain chat)
- No S8-03 implementation (structured generation)
- No S8-04 implementation (native tool calling)
- No S8-05 implementation (embeddings)
- No S8-06 implementation (provider integration)
- No S8-07 implementation (Stage-8 review)
- Stage 9 remains NOT STARTED

## S8-C03 correction record

**Reviewed S8-02 SHA:** `65d6afb6af52b58613456c574f79cd66af02bba3`

### Defect A — `/api/version` accepts unusable version values

The S8-02 version check validated only:

```python
isinstance(version_data, dict) and "version" in version_data
```

It did not verify the value itself was usable. Responses such as
`{"version": null}`, `{"version": ""}`, `{"version": "   "}`, and
`{"version": 123}` passed validation.

### Defect B — invalidly encoded non-JSON bodies can leak raw exceptions

`httpx.Response.json()` parses raw response bytes, and malformed byte
encoding may raise `UnicodeDecodeError` instead of `json.JSONDecodeError`.
This affected `health()`, `chat()`, and `_extract_ollama_error()`.

### Production fixes

**File:** `src/dnd_assistant/models/ollama.py`

1. **Version value validation** — Added `_extract_version()` helper that
   requires the version value to be a string whose stripped value is
   non-empty. Returns `None` for null, empty, whitespace-only, or non-string
   values.

2. **JSON-decoding hardening** — Changed all `except json.JSONDecodeError`
   to `except ValueError` around `response.json()` calls, because both
   `json.JSONDecodeError` and `UnicodeDecodeError` are `ValueError`
   subclasses. Each `except ValueError` is scoped to only the
   `response.json()` call.

   Affected locations:
   - `health()` `/api/version` JSON parsing
   - `health()` `/api/tags` JSON parsing
   - `_parse_chat_response()` successful response JSON parsing
   - `_extract_ollama_error()` HTTP error-body JSON parsing

3. **Removed unused `import json`** — No longer needed after changing all
   `json.JSONDecodeError` references to `ValueError`.

4. **Corrected docstring** — Removed misleading "e.g. via a context manager"
   wording from the HTTP client ownership section since no `__enter__` /
   `__exit__` exists.

### Health decoding semantics after correction

For `/api/version`:

- Invalid textual JSON or invalidly encoded bytes → `ModelHealth(reachable=True, model_available=False, detail="invalid version response: non-JSON body")`
- Unusable version value (null, empty, whitespace, non-string) → `ModelHealth(reachable=True, model_available=False, detail="invalid version response: missing or unusable 'version' field")`

For `/api/tags`:

- Invalid textual JSON or invalidly encoded bytes → `ModelHealth(reachable=True, model_available=False, detail="invalid /api/tags response: non-JSON body")`

No raw `UnicodeDecodeError`, `JSONDecodeError`, or `ValueError` escapes
`health()` for malformed provider bodies.

### Plain-chat decoding semantics after correction

For successful HTTP `/api/chat` responses with invalid JSON or invalid
byte encoding → `ModelError("Ollama chat returned non-JSON response")`
with the underlying decoding exception preserved as `__cause__`.

### HTTP error-body extraction after correction

`_extract_ollama_error()` tolerates invalidly encoded response bodies.
Falls back to `"HTTP {status}"` without leaking `UnicodeDecodeError`,
raw binary content, or unbounded body.

### Unchanged transport behavior

Preserved:
- `POST /api/chat`, `GET /api/version`, `GET /api/tags`
- `stream = false`, `temperature` → `options.temperature`, `keep_alive` → top-level
- Exact model matching against `model` and `name` fields
- Path-prefix URL behavior
- No automatic model pull/fallback
- Plain-chat rejection of tool-bearing history
- Thinking-field behavior
- Synchronous `httpx.Client` with explicit `close()` lifecycle

### Regression coverage

**File:** `tests/unit/test_ollama_provider.py` (64 total tests, +8 from S8-02)

| Test | What it covers |
|---|---|
| `test_unusable_version_rejected` (parametrized × 4) | `version: null`, `version: ""`, `version: "   "`, `version: 123` — each rejected with `reachable=True, model_available=False` and `/api/tags` not called |
| `test_invalid_bytes_version_response` | Invalid-byte `/api/version` body → `ModelHealth`, no exception |
| `test_invalid_bytes_tags_response` | Invalid-byte `/api/tags` body after valid version → `ModelHealth`, no exception |
| `test_invalid_bytes_chat_response_raises_model_error` | Invalid-byte HTTP 200 `/api/chat` → `ModelError`, underlying cause preserved |
| `test_invalid_bytes_error_body` | Invalid-byte HTTP error body → `ModelError` with HTTP status |

### Verification commands and results

```
uv run pytest tests/unit/test_ollama_provider.py -v
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 290 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3895 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 283 files already formatted

git diff --check
→ no whitespace errors
```

### Scope audit

**Intended scope:**
- `src/dnd_assistant/models/ollama.py`
- `tests/unit/test_ollama_provider.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `src/dnd_assistant/models/ollama.py`
- `tests/unit/test_ollama_provider.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/unit/test_model_profiles.py`
- `tests/contract/`
- `pyproject.toml`
- `uv.lock`

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- `TEST_LEGACY_EXCEPTIONS`: unchanged
- `src/dnd_assistant/models/ollama.py`: 394 lines (under 700)
- `tests/unit/test_ollama_provider.py`: 992 lines (under 1000)
- No new correction-history filenames created
- No new maintainability exceptions added

## S8-C04 correction record

**Reviewed S8-03 SHA:** `e0f6399810aef19417db0f1469707bb2e43bdc56`

**Reason for correction:** Independent review of S8-03 found three documentation/evidence defects:

1. **Defect A — wrong S8-03 test-file physical-line count.** The committed S8-03 record stated `tests/unit/test_ollama_structured.py = 809 lines`, but the actual physical-line count is 775.

2. **Defect B — Final Report line-count contradictions.** The S8-03 Final Report correctly reported `ollama.py = 544`, `test_ollama_provider.py = 992`, and `test_ollama_structured.py = 775`, but the committed Stage-8 document contained stale values (545, 994, 809 respectively).

3. **Defect C — incomplete Stage-8 correction-pass index.** The correction-pass table listed only S8-C00 and S8-C02, omitting S8-C01 and S8-C03.

**Canonical physical-line counting method:**

```python
from pathlib import Path

paths = (
    Path("src/dnd_assistant/models/ollama.py"),
    Path("tests/unit/test_ollama_provider.py"),
    Path("tests/unit/test_ollama_structured.py"),
)

for path in paths:
    print(path, len(path.read_bytes().splitlines()))
```

**Freshly measured counts (at S8-03 HEAD `e0f63998`):**

| File | Count |
|---|---|
| `src/dnd_assistant/models/ollama.py` | 544 |
| `tests/unit/test_ollama_provider.py` | 992 |
| `tests/unit/test_ollama_structured.py` | 775 |

**Stale S8-03 counts found and corrected:**

| Location | Stale value | Corrected value |
|---|---|---|
| S8-03 Test-file split: `test_ollama_provider.py` was at N lines | 994 | 992 |
| S8-03 Test-file split: `test_ollama_structured.py` (47 tests, N lines) | 809 | 775 |
| S8-03 Maintainability: `ollama.py` | 545 | 544 |
| S8-03 Maintainability: `test_ollama_structured.py` | 809 | 775 |
| S8-03 Maintainability: `test_ollama_provider.py` | 994 | 992 |

**Historical-count preservation audit:**

The S8-C03 record's maintainability section also contained a stale count (`test_ollama_provider.py: 994` at S8-C03 SHA). The actual count at S8-C03 SHA (`8a633b3`) was 992. This was independently verified and corrected as part of this pass.

All other historical counts in earlier records (S8-00, S8-C00, S8-C01, S8-01, S8-C02, S8-02, S8-C03) were verified to match their respective commit SHAs or were left unchanged when the task scope did not authorize their correction.

**Correction-pass table repair:**

Added missing entries:
- S8-C01 — Correct Stage-8 verification evidence
- S8-C03 — Harden Ollama health and JSON response validation
- S8-C04 — Correct S8-03 verification evidence and Stage-8 correction index

**Confirmation production/tests unchanged:**

Zero diff in:
- `src/dnd_assistant/` (all production code)
- `tests/` (all test code)
- `pyproject.toml`
- `uv.lock`
- `.gigacode/`
- `.gigacode_vsc/`

**Verification commands and results:**

```
uv run pytest tests/unit/test_ollama_structured.py -v
→ 47 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_provider.py -v
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 292 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3944 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 284 files already formatted

git diff --check
→ no whitespace errors
```

**Scope audit:**

**Intended scope:** `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`, `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/ollama.py`
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_ollama_structured.py`
- `tests/unit/test_ollama_provider.py`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/unit/test_model_profiles.py`
- `tests/contract/`
- `pyproject.toml`
- `uv.lock`

**Maintainability:**

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- `TEST_LEGACY_EXCEPTIONS["unit/test_retrieval_contracts.py"]` (1477): unchanged
- No new correction-history filenames created
- No new maintainability exceptions added

**S8-04 deferral:**

S8-04 remains NOT STARTED. This correction does not begin S8-04 implementation.

## S8-04 implementation record

**Starting SHA:** `e445868e9bb5416f0e9ec8ee5fcad631c880ea4a`

**Branch:** `main`

### Official Ollama tool-calling endpoint

Uses `POST /api/chat` with the `tools` field containing native Ollama function-calling schemas.

### `chat_with_tools` signature

```python
def chat_with_tools(
    self,
    request: ChatRequest,
    tools: list[ToolPublicDefinition],
) -> ToolAwareResponse:
```

### ModelGateway Protocol unchanged

The `ModelGateway` Protocol already defined `chat_with_tools()` since S8-00. No changes to `gateway.py`, `types.py`, or any provider-neutral DTOs.

### Runtime ToolPublicDefinition import strategy

Uses `TYPE_CHECKING`-only import in `ollama.py`. The concrete `ToolPublicDefinition` is used only for data adaptation (reading `name`, `description`, `input_schema`). No runtime Tool Layer dependency.

### No ToolRegistry/ToolExecutor/handler dependency

Confirmed via clean-import test and all boundary tests (97 passed).

### Production decomposition decision

Created `src/dnd_assistant/models/ollama_tool_adapter.py` (319 lines) to own pure-ish adaptation. `ollama.py` (641 lines) owns HTTP request lifecycle and payload construction.

### Exact ToolPublicDefinition → Ollama mapping

Only `name`, `description`, and `input_schema` are sent. `output_schema`, `permission`, `side_effects`, and `allowed_session_modes` are intentionally excluded.

### Tool ordering behavior

The input `tools` list order is preserved in the outgoing payload.

### Empty tool-list behavior

`chat_with_tools(request, [])` sends `"tools": []` and returns a normal text-only `ToolAwareResponse`.

### Exact native endpoint

`POST /api/chat` with `stream: false`, `temperature` → `options.temperature`, `keep_alive` → top-level. No `format` or `think` sent. No prompt mutation.

### Message mapping

SYSTEM, USER, plain ASSISTANT, ASSISTANT with tool calls, and TOOL result messages are all mapped to their native Ollama equivalents. Parallel history is supported.

### Provider-neutral call_id policy

Native Ollama does not define provider call IDs. Newly parsed `ToolCall` objects use `call_id=None`. Non-null `call_id` or `tool_call_id` in outgoing history is rejected before HTTP.

### Response mapping

Text-only, tool-call-only, and text + tool-call responses are all supported. Content normalization handles empty/missing/None content appropriately.

### ToolCall structure validation

Required: entry is object, `function` exists and is object, `function.name` is non-empty string, `function.arguments` is object/dict. If `type` is present it must be `"function"`. Out-of-allowlist names raise `ModelError`.

### No argument schema validation in ModelGateway

No JSON-Schema validation of arguments against `input_schema` is performed in S8-04. That belongs to the Tool Layer / ToolExecutor.

### HTTP/error mapping

All failures (connection, timeout, HTTP 4xx/5xx, non-JSON, invalid bytes) surface as `ModelError` with cause preservation. No raw httpx/Pydantic/decoding exceptions escape.

### No execution / no agent loop

A single `chat_with_tools()` call produces exactly one provider response. No retry, no agent loop, no automatic tool-result generation.

### Clean-import dependency diagnostic

Importing `dnd_assistant.models.ollama` does not eagerly load `dnd_assistant.tools.executor`.

### Quality-gate evidence

```
uv run pytest tests/unit/test_ollama_tool_calling.py -v
→ 71 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_provider.py -v
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_structured.py -v
→ 47 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 295 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 4018 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 286 files already formatted

git diff --check
→ no whitespace errors
```

### Physical-line counts

- `ollama.py`: 641 (under 700)
- `ollama_tool_adapter.py`: 319 (under 700)
- `test_ollama_tool_calling.py`: 885 (under 1000)

### Maintainability

`PRODUCTION_HARD_LIMIT` (700), `TEST_HARD_LIMIT` (1000), and all legacy exceptions unchanged. No new exceptions added. No dependency changes (`pyproject.toml` and `uv.lock` unchanged).

### Scope audit

**Intended scope:** `src/dnd_assistant/models/ollama.py`, `src/dnd_assistant/models/ollama_tool_adapter.py`, `tests/unit/test_ollama_tool_calling.py`, `tests/contract/test_test_harness_policy.py`, `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`, `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):** same as intended.

**No changes in:** `src/dnd_assistant/models/gateway.py`, `src/dnd_assistant/models/types.py`, `src/dnd_assistant/models/profiles.py`, `src/dnd_assistant/models/__init__.py`, `src/dnd_assistant/domain/`, `src/dnd_assistant/storage/`, `src/dnd_assistant/retrieval/`, `src/dnd_assistant/application/`, `src/dnd_assistant/tools/`, `src/dnd_assistant/cli/`, `tests/unit/test_ollama_provider.py`, `tests/unit/test_ollama_structured.py`, `tests/unit/test_model_gateway_contracts.py`, `tests/unit/test_model_profiles.py`, `tests/contract/test_boundaries.py`, `tests/contract/test_maintainability.py`, `pyproject.toml`, `uv.lock`

### S8-05+ deferrals

S8-05 (embeddings): NOT STARTED. S8-06 (provider integration): NOT STARTED. S8-07 (Stage-8 review): NOT STARTED. Stage 9 (Fast Agent): NOT STARTED.

---

## S8-C05 correction record

**Starting SHA:** `d2f6096b87c9a657acb2633f4591b01599ac93a5`

**Branch:** `main`

**Reviewed S8-04 SHA:** `d2f6096b87c9a657acb2633f4591b01599ac93a5`

### Defect A — falsy malformed `tool_calls` values bypass validation

The S8-04 response parsing used truthiness to decide whether the provider supplied `tool_calls`:

```python
raw_tool_calls = msg_data.get("tool_calls")
tool_calls = ()
if raw_tool_calls:
    tool_calls = _parse_tool_calls(raw_tool_calls, allowed_tool_names)
```

This incorrectly conflated `tool_calls` field absence with present-but-malformed falsy values (`null`, `""`, `{}`, `0`, `false`). When usable assistant text was also present, these responses were silently accepted as text-only responses.

### Defect B — unnecessary test-harness policy expansion

S8-04 modified `tests/contract/test_test_harness_policy.py` to add `unit/test_ollama_tool_calling.py` to `MODULE_LEVEL_OPTIIN`, and added a module-wide `restore_dnd_assistant_modules` fixture plus a permanent `sys.modules`-deletion test to the tool-calling test module. This was outside the original intended S8-04 scope.

### Production fix

**File:** `src/dnd_assistant/models/ollama_tool_adapter.py`

Changed the `tool_calls` presence check from truthiness to explicit field-membership:

```python
if "tool_calls" in msg_data:
    raw_tool_calls = msg_data["tool_calls"]
    tool_calls = _parse_tool_calls(raw_tool_calls, allowed_tool_names)
else:
    tool_calls = ()
```

`_parse_tool_calls()` already validates that the supplied value is a list, so `null`, `""`, `{}`, `0`, and `false` all produce `ModelError` via the existing `isinstance(raw_tool_calls, list)` check.

### Field-presence semantics after correction

| Condition | Behavior |
|---|---|
| `tool_calls` field missing | Accepted as no calls |
| `tool_calls=[]` | Accepted as no calls |
| `tool_calls=[...]` | Parsed normally |
| `tool_calls=None` | `ModelError` |
| `tool_calls=""` | `ModelError` |
| `tool_calls={}` | `ModelError` |
| `tool_calls=0` | `ModelError` |
| `tool_calls=False` | `ModelError` |

### Regression coverage added

**File:** `tests/unit/test_ollama_tool_calling.py`

New class `TestFalsyMalformedToolCalls` (6 parametrized tests):

| Test | What it covers |
|---|---|
| `test_falsy_malformed_rejected[null]` | `tool_calls: null` with usable text → `ModelError` |
| `test_falsy_malformed_rejected[empty_string]` | `tool_calls: ""` with usable text → `ModelError` |
| `test_falsy_malformed_rejected[empty_object]` | `tool_calls: {}` with usable text → `ModelError` |
| `test_falsy_malformed_rejected[zero]` | `tool_calls: 0` with usable text → `ModelError` |
| `test_falsy_malformed_rejected[false]` | `tool_calls: false` with usable text → `ModelError` |
| `test_empty_list_with_text_is_valid` | `tool_calls: []` with usable text → valid text-only response |

Each malformed test verifies the error diagnostic references `tool_calls`. The empty-list test verifies `content == "Usable text"` and `tool_calls == ()`.

### Harness restoration

Removed from `tests/unit/test_ollama_tool_calling.py`:

- Module-level `pytestmark = pytest.mark.usefixtures("restore_dnd_assistant_modules")`
- Permanent `test_ollama_import_does_not_load_tool_executor` test that mutated `sys.modules`

Restored `tests/contract/test_test_harness_policy.py` to pre-S8-04 state:

- Removed `unit/test_ollama_tool_calling.py` from `MODULE_LEVEL_OPTIIN`

After restoration, the module-level opt-in set is:

```python
MODULE_LEVEL_OPTIIN: set[str] = {
    "contract/test_boundaries.py",
}
```

### Direct clean-import diagnostic

Command:

```text
uv run python -c "import sys; import dnd_assistant.models.ollama; bad=sorted(m for m in sys.modules if m.startswith('dnd_assistant.tools')); assert not bad, bad; print('clean')"
```

Result:

```text
clean
```

No `dnd_assistant.tools.*` modules are eagerly loaded by importing `dnd_assistant.models.ollama`. No `ToolExecutor` runtime import.

### Preserved behavior

All accepted S8-04 behavior is preserved:

- Text-only, tool-call-only, and text + tool-call responses
- Parallel calls, duplicate same-name calls
- Allowlist enforcement
- `call_id=None` on returned Ollama calls
- ToolCall validation (entry is object, function exists, name non-empty, arguments object, type check, allowlist)
- Existing truthy malformed cases (`"not a list"`, non-object entries, missing function, etc.)
- HTTP/error mapping, invalid-byte protection
- No execution, no agent loop, one HTTP request per `chat_with_tools` call
- No argument-schema validation in ModelGateway

### Quality-gate evidence

```
uv run pytest tests/unit/test_ollama_tool_calling.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_provider.py -v
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_structured.py -v
→ 47 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 295 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 4023 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 286 files already formatted

git diff --check
→ no whitespace errors
```

### Physical-line counts

```
src\dnd_assistant\models\ollama.py: 641 (under 700)
src\dnd_assistant\models\ollama_tool_adapter.py: 319 (under 700)
tests\unit\test_ollama_tool_calling.py: 918 (under 1000)
```

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- All legacy exceptions: unchanged
- No new exceptions added
- No dependency changes (`pyproject.toml` and `uv.lock` unchanged)

### Scope audit

**Intended scope:** `src/dnd_assistant/models/ollama_tool_adapter.py`, `tests/unit/test_ollama_tool_calling.py`, `tests/contract/test_test_harness_policy.py`, `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`, `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**

- `src/dnd_assistant/models/ollama_tool_adapter.py`
- `tests/unit/test_ollama_tool_calling.py`
- `tests/contract/test_test_harness_policy.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/ollama.py`
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_ollama_provider.py`
- `tests/unit/test_ollama_structured.py`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/unit/test_model_profiles.py`
- `tests/contract/test_boundaries.py`
- `tests/contract/test_maintainability.py`
- `pyproject.toml`
- `uv.lock`

### S8-05+ deferrals

S8-05 (embeddings): NOT STARTED. S8-06 (provider integration): NOT STARTED. S8-07 (Stage-8 review): NOT STARTED. Stage 9 (Fast Agent): NOT STARTED.

## S8-03 implementation record

**Starting SHA:** `8a633b3b467107c96b78fc3a71a125bd3188b563`

**Branch:** `main`

### Official Ollama structured-output mechanism

Uses `POST /api/chat` with the `format` field set to the Pydantic JSON Schema
of the caller's schema:

```json
{
  "model": "...",
  "messages": [...],
  "stream": false,
  "format": { "...caller schema JSON Schema..." }
}
```

### `generate_structured` signature

```python
T = TypeVar("T", bound=BaseModel)

def generate_structured(
    self,
    request: ChatRequest,
    schema: type[T],
) -> T:
```

### Generic Pydantic type decision

Uses `TypeVar("T", bound=BaseModel)` with `pydantic.BaseModel` as the runtime
type bound. The public return type is `T` (the exact validated Pydantic model
type requested by the caller).

### Runtime schema validation

Before any HTTP request, verifies:

```python
isinstance(schema, type) and issubclass(schema, BaseModel)
```

Rejects `int`, `dict`, `str`, ordinary classes, and Pydantic model instances
with `ValidationError`. Rejected schemas never result in an HTTP call.

### `format = schema.model_json_schema()` mapping

The `format` field in the Ollama payload is set to the exact result of
`schema.model_json_schema()`. No manual JSON Schema reconstruction.

### No prompt mutation

Messages in the `ChatRequest` are mapped to the Ollama payload unchanged.
No schema text, system message, or user suffix is injected into the prompt.

### Request mapping reuse

Reuses the same profile-based configuration as `chat()`:
- `model` from profile
- `messages` via `_map_message()`
- `stream: false`
- `temperature` → `options.temperature` (omitted when `None`)
- `keep_alive` → top-level (omitted when `None`)

### No tools or think sent

The structured payload never includes `tools` or `think` fields.

### Tool-history rejection

`generate_structured()` calls `_assert_no_tool_history()` before any HTTP
request, rejecting TOOL-role messages and assistant messages with tool_calls.
Rejected tool-bearing history makes no HTTP request.

### Response message structural validation

The outer Ollama response is validated for:
- top-level JSON object
- `message` field exists and is an object
- `message.role == "assistant"`
- `message.content` is a string
- no unexpected `message.tool_calls`

Malformed responses raise `ModelError`.

### Structured content validation

Uses `schema.model_validate_json(content)` to validate the assistant content
against the exact caller-provided Pydantic schema. This enforces JSON syntax,
field types, required fields, nested schemas, caller-defined validators, and
extra-field policy.

### `ModelError` mapping

All output validation failures cross the provider boundary as `ModelError`:
- invalid JSON in `message.content`
- valid JSON but wrong field type
- missing required field
- schema-specific validator failure
- extra field rejection when the caller schema forbids extras

The underlying Pydantic validation exception is preserved via `cause=`.

### No retry/repair/fallback

No retry with a new prompt, no `"format": "json"` fallback, no JSON repair,
no markdown-fence stripping, no LLM self-correction, no schema simplification,
no fallback model.

### No automatic model mutation

No `ollama pull`, no model fallback, no model selection changes.

### Test-file split

`tests/unit/test_ollama_provider.py` was at 992 lines (TEST_HARD_LIMIT = 1000).
S8-03 tests were created in a new topical module:
`tests/unit/test_ollama_structured.py` (47 tests, 775 lines).

### Mock strategy

All tests use `respx.mock` to mock HTTP. No real Ollama, no network, no Vault.

### Quality-gate evidence

```
uv run pytest tests/unit/test_ollama_structured.py -v
→ 47 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_provider.py -v
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 292 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 3944 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 284 files already formatted

git diff --check
→ no whitespace errors
```

### Scope audit

**Intended scope:**
- `src/dnd_assistant/models/ollama.py`
- `tests/unit/test_ollama_structured.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `src/dnd_assistant/models/ollama.py`
- `tests/unit/test_ollama_structured.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_ollama_provider.py`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/unit/test_model_profiles.py`
- `tests/contract/`
- `pyproject.toml`
- `uv.lock`

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- `TEST_LEGACY_EXCEPTIONS`: unchanged
- `src/dnd_assistant/models/ollama.py`: 544 lines (under 700)
- `tests/unit/test_ollama_structured.py`: 775 lines (under 1000)
- `tests/unit/test_ollama_provider.py`: 992 lines (unchanged, under 1000)
- No new correction-history filenames created
- No new maintainability exceptions added

### S8-04+ deferrals

- S8-04 (native tool calling): NOT STARTED
- S8-05 (embeddings): NOT STARTED
- S8-06 (provider integration): NOT STARTED
- S8-07 (Stage-8 review): NOT STARTED
- Stage 9 (Fast Agent): NOT STARTED

## S8-05 implementation record

**Starting SHA:** `214e75120cd5a892df78e100c176b611bf072e8e`

**Branch:** `main`

### Exact `embed` signature

```python
def embed(self, texts: list[str]) -> list[list[float]]:
```

### Confirmation: all five ModelGateway methods are now implemented

- `chat()` — S8-02
- `chat_with_tools()` — S8-04
- `generate_structured()` — S8-03
- `embed()` — S8-05
- `health()` — S8-02

ModelGateway Protocol unchanged.

### Production decomposition

`embed()` transport method lives in `src/dnd_assistant/models/ollama.py` (699 lines, under 700).

Provider-specific embedding validation/adaptation lives in a new module:
`src/dnd_assistant/models/ollama_embedding_adapter.py` (212 lines, under 700).

### Official native endpoint

`POST /api/embed`

Not `/api/embeddings`, `/api/generate`, `/api/chat`, or `/v1/embeddings`.

### Exact embedding payload shape

```json
{
  "model": "<profile.model>",
  "input": ["text one", "text two"],
  "truncate": false
}
```

### Input always sent as array

Even for a single input, `"input"` is always a JSON array:

```json
"input": ["one"]
```

not:

```json
"input": "one"
```

### Caller-input validation

| Input | Result |
|---|---|
| `[]` | `ValidationError` before HTTP |
| `"hello"` (string) | `ValidationError` before HTTP |
| `("hello",)` (tuple) | `ValidationError` before HTTP |
| `123` (int) | `ValidationError` before HTTP |
| `[123]` (list with int) | `ValidationError` before HTTP |
| `[None]` (list with None) | `ValidationError` before HTTP |
| `[["nested"]]` (list with list) | `ValidationError` before HTTP |

Every invalid caller-input case was proven to make zero HTTP calls.

### Text-preservation decisions

- **Order:** preserved exactly.
- **Duplicates:** preserved — `["same", "same"]` sends two identical entries.
- **Unicode:** preserved — Cyrillic, CJK, Greek sent unchanged.
- **Whitespace:** preserved — leading/trailing spaces not stripped.
- **Empty string:** preserved — `""` sent as-is.

### `truncate` policy

`truncate` is explicitly `False` in every payload.

No silent truncation. No retry with `truncate=True` after a context-length error.

### `keep_alive` mapping

Present in payload when `profile.keep_alive` is not `None`.
Omitted when `None`.

### Temperature policy

`temperature` is **not** sent in the embedding payload, even when the profile has a non-None temperature value.

### Confirmation: no generation-only settings sent

The following fields are absent from the embedding payload:

- `stream`
- `format`
- `tools`
- `think`
- `dimensions`
- `options`

### Profile-role policy

No new hard runtime restriction on `profile.role` inside `embed()`.
Tests use `EMBEDDING` role for clarity, but no provider-level role enforcement was added.

### Response `embeddings` field validation

| Condition | Result |
|---|---|
| Top-level list | `ModelError` |
| Top-level string | `ModelError` |
| Missing `embeddings` | `ModelError` |
| `embeddings` is `None` | `ModelError` |
| `embeddings` is object | `ModelError` |
| `embeddings` is string | `ModelError` |

### Cardinality rule

Exactly one vector per input text is required.

| Input count | Returned vectors | Result |
|---|---|---|
| 2 | 1 | `ModelError` |
| 1 | 2 | `ModelError` |
| 1 | 0 | `ModelError` |

### Vector validation

Each vector must be a non-empty list.

| Condition | Result |
|---|---|
| `None` | `ModelError` |
| string | `ModelError` |
| object | `ModelError` |
| number | `ModelError` |
| `[]` (empty) | `ModelError` |

### Dimension consistency

All returned vectors in a batch must have the same non-zero length.
Ragged dimensions (`[0.1, 0.2]` vs `[0.3, 0.4, 0.5]`) raise `ModelError`.

### Numeric scalar validation

| Scalar value | Result |
|---|---|
| `int` (e.g. `1`) | Accepted, converted to `float(1.0)` |
| `float` (e.g. `2.5`) | Accepted |
| `bool` (`True`, `False`) | `ModelError` |
| `None` | `ModelError` |
| `"0.5"` (string) | `ModelError` |
| `[]` (list) | `ModelError` |
| `{}` (object) | `ModelError` |

### Non-finite value handling

| Value | Result |
|---|---|
| `NaN` | `ModelError` |
| `+Infinity` | `ModelError` |
| `-Infinity` | `ModelError` |

### No renormalization

Returned vectors are not renormalized, rounded, quantized, clipped, or scaled.
Only structural/numeric validation and int→float conversion are performed.

### Successful single-input behavior

```python
result = provider.embed(["hello"])
# → [[0.1, 0.2, 0.3]]
# Every scalar is a Python float
```

### Successful batch behavior

```python
result = provider.embed(["a", "b", "c"])
# → [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]
# Cardinality and order preserved
```

### Duplicate-input result

```python
result = provider.embed(["same", "same"])
# → [[0.1, 0.2], [0.3, 0.4]]
# Two distinct vectors returned, no deduplication
```

### Provider metadata

Fields such as `model`, `total_duration`, `load_duration`, `prompt_eval_count` are silently ignored.

### HTTP failure mapping

| Condition | Public error | Cause preserved |
|---|---|---|
| Connection failure | `ModelError` | `httpx.ConnectError` |
| Timeout | `ModelError` | `httpx.TimeoutException` |
| HTTP 400 with JSON error body | `ModelError` | — |
| HTTP 404 with JSON error body | `ModelError` | — |
| HTTP 500 with JSON error body | `ModelError` | — |
| HTTP 500 non-JSON body | `ModelError` | — |
| HTTP 400 invalid-byte body | `ModelError` | — |
| Success HTTP non-JSON body | `ModelError` | `ValueError` |
| Success HTTP invalid-byte body | `ModelError` | `ValueError` |

HTTP status remains visible in the error message for HTTP failures.

### Exactly-one-request proof

- Success: exactly one `POST /api/embed` request.
- Provider error: exactly one `POST /api/embed` request, no retry.

### No model pull/fallback

No `ollama pull`, no fallback model, no model-name rewriting.

### No persistence/cache/index

No embeddings are written to Vault, SQLite, files, cache, or index.

### No semantic retrieval/vector DB/RAG

S8-05 is strictly the provider-level embedding transport and validation boundary.

### Mock strategy

All tests use `respx.mock` to mock HTTP. No real Ollama, no network, no Vault.

### Quality-gate evidence

```
uv run pytest tests/unit/test_ollama_embeddings.py -v
→ 62 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_provider.py -v
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_structured.py -v
→ 47 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_tool_calling.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py -v
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py -v
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py -v
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py -v
→ 298 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py -v
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 4088 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 288 files already formatted

git diff --check
→ no whitespace errors
```

### Canonical physical-line counts

```
src\dnd_assistant\models\ollama.py: 699 (under 700)
src\dnd_assistant\models\ollama_embedding_adapter.py: 212 (under 700)
tests\unit\test_ollama_embeddings.py: 850 (under 1000)
```

### Maintainability

- `PRODUCTION_HARD_LIMIT` (700): unchanged
- `TEST_HARD_LIMIT` (1000): unchanged
- All legacy exceptions: unchanged
- No new exceptions added
- No dependency changes (`pyproject.toml` and `uv.lock` unchanged)

### Scope audit

**Intended scope:**
- `src/dnd_assistant/models/ollama.py`
- `src/dnd_assistant/models/ollama_embedding_adapter.py`
- `tests/unit/test_ollama_embeddings.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `src/dnd_assistant/models/ollama.py`
- `src/dnd_assistant/models/ollama_embedding_adapter.py`
- `tests/unit/test_ollama_embeddings.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/models/ollama_tool_adapter.py`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_ollama_provider.py`
- `tests/unit/test_ollama_structured.py`
- `tests/unit/test_ollama_tool_calling.py`
- `tests/unit/test_model_profiles.py`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/contract/`
- `tests/conftest.py`
- `tests/fixtures/`
- `pyproject.toml`
- `uv.lock`
- `.gigacode/`
- `.gigacode_vsc/`

### S8-06+ deferrals

S8-06 (provider integration): NOT STARTED. S8-07 (Stage-8 review): NOT STARTED. Stage 9 (Fast Agent): NOT STARTED.

## S8-C06 correction record

**Reviewed S8-05 SHA:** `4e7207ca152a464a61985c66b0e5ec8f0a3fd4a8`

**Branch:** `main`

### Oversized-integer defect

`_validate_scalar()` called `math.isfinite(value)` where `value` could be a
Python `int` larger than the finite representable range of `float`.  For a
JSON integer such as `10**309`, `math.isfinite(10**309)` raises:

```
OverflowError: int too large to convert to float
```

before a project `ModelError` could be produced.  The subsequent
`float(scalar)` call had the same conversion boundary.

Therefore malformed/unrepresentable provider embedding data could leak a raw
Python `OverflowError` across the ModelGateway boundary.

### Correct float-coercion boundary

`_validate_scalar()` was replaced by `_coerce_embedding_scalar()` which:

1. Rejects `bool` before numeric coercion.
2. Rejects non-`int`/`float` types.
3. Performs exactly one authoritative conversion to `float`.
4. Narrowly catches `OverflowError` from `float(value)`.
5. Converts overflow into project `ModelError` with `OverflowError` preserved
   as `__cause__`.
6. Runs `math.isfinite()` on the converted `float`, not on an arbitrary-size
   integer.
7. Returns the already-validated `float`.

`parse_embed_response()` now appends the returned value rather than calling
`float()` a second time.

No broad `except Exception` was introduced.

### Positive oversized integer regression

`OllamaModelProvider.embed(["hello"])` with a response containing `10**309`
raises `ModelError` with `OverflowError` as `__cause__`.  No raw
`OverflowError` escapes.

### Negative oversized integer regression

`OllamaModelProvider.embed(["hello"])` with a response containing `-(10**309)`
raises `ModelError` with `OverflowError` as `__cause__`.  No raw
`OverflowError` escapes.

### Ordinary-int behavior preserved

`[1, 2.5, -3]` → `[1.0, 2.5, -3.0]` — ordinary representable JSON integers
remain accepted.

### NaN/Inf behavior preserved

`NaN`, `+Infinity`, `-Infinity` still produce `ModelError`.

### Cause-chain policy

`OverflowError` is preserved as `ModelError.__cause__` via `from exc`.

### Quality gates

```
uv run pytest tests/unit/test_ollama_embeddings.py
→ 67 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_provider.py
→ 64 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_structured.py
→ 47 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_ollama_tool_calling.py
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_profiles.py
→ 73 passed, 0 failed, 0 errors

uv run pytest tests/unit/test_model_gateway_contracts.py
→ 76 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_boundaries.py
→ 97 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_maintainability.py
→ 298 passed, 0 failed, 0 errors

uv run pytest tests/contract/test_test_harness_policy.py
→ 25 passed, 0 failed, 0 errors

uv run pytest
→ 4093 passed, 95 skipped, 0 failed, 0 errors

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 288 files already formatted

git diff --check
→ no whitespace errors
```

### Fresh physical-line counts

```
src\dnd_assistant\models\ollama.py: 699 (under 700, unchanged)
src\dnd_assistant\models\ollama_embedding_adapter.py: 236 (under 700)
tests\unit\test_ollama_embeddings.py: 929 (under 1000)
```

### Scope audit

**Intended scope:**
- `src/dnd_assistant/models/ollama_embedding_adapter.py`
- `tests/unit/test_ollama_embeddings.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**Actual changed files (from Git):**
- `src/dnd_assistant/models/ollama_embedding_adapter.py`
- `tests/unit/test_ollama_embeddings.py`
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`
- `DEVELOPMENT_STATUS.md`

**No changes in:**
- `src/dnd_assistant/models/ollama.py` (699, unchanged)
- `src/dnd_assistant/models/gateway.py`
- `src/dnd_assistant/models/types.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/__init__.py`
- `src/dnd_assistant/models/ollama_tool_adapter.py`
- `src/dnd_assistant/tools/`
- `src/dnd_assistant/domain/`
- `src/dnd_assistant/storage/`
- `src/dnd_assistant/retrieval/`
- `src/dnd_assistant/application/`
- `src/dnd_assistant/cli/`
- `tests/unit/test_ollama_provider.py`
- `tests/unit/test_ollama_structured.py`
- `tests/unit/test_ollama_tool_calling.py`
- `tests/unit/test_model_profiles.py`
- `tests/unit/test_model_gateway_contracts.py`
- `tests/contract/`
- `tests/conftest.py`
- `tests/fixtures/`
- `pyproject.toml`
- `uv.lock`
- `.gigacode/`
- `.gigacode_vsc/`

### S8-06 deferral

S8-06 remains NOT STARTED. S8-07 remains NOT STARTED. Stage 9 remains NOT STARTED.