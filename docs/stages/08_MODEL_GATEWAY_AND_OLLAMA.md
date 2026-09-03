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
| S8-03 | NOT STARTED | Ollama structured generation |
| S8-04 | NOT STARTED | Ollama native tool-calling adapter |
| S8-05 | NOT STARTED | Ollama embeddings |
| S8-06 | NOT STARTED | Provider integration / error hardening / opt-in smoke coverage |
| S8-07 | NOT STARTED | Full Stage-8 historical review / completion |

Correction passes:

| Task | Status | Notes |
|---|---|---|
| S8-C00 | **DONE** | Harden ModelGateway plain-chat and JSON tool-call contracts |
| S8-C02 | **DONE** | Harden ModelProfile base_url endpoint validation |

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
- `tests/unit/test_ollama_provider.py`: 994 lines (under 1000)
- No new correction-history filenames created
- No new maintainability exceptions added

### S8-03+ deferrals

- S8-03 (structured generation): NOT STARTED
- S8-04 (native tool calling): NOT STARTED
- S8-05 (embeddings): NOT STARTED
- S8-06 (provider integration): NOT STARTED
- S8-07 (Stage-8 review): NOT STARTED
- Stage 9 (Fast Agent): NOT STARTED