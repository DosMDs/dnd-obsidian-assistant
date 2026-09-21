# DeepSeek provider qualification runbook

## Purpose

Operational procedure for qualifying DeepSeek as a remote provider while
preserving project runtime and evidence invariants.

This runbook complements `provider-runtime-upgrade.md`.

## 1. Secrets

Required credential name:

```text
DEEPSEEK_API_KEY
```

Rules:

- never commit the key;
- never store it in the Vault;
- never include it in model profiles, reports, traces, audit records or errors;
- redact/avoid request headers in diagnostics;
- explicit live tests with missing/invalid credentials fail closed.

## 2. Initial profile

Qualification target:

```toml
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "high"
```

`deepseek-flash` is the current official model identifier (served as
DeepSeek-V4.1-Flash at the decision date). Do not substitute the retired
`deepseek-v4-flash` name as the project identifier; its compatibility routing is
diagnostic-only evidence for RM-02.

Accepted profile schema (RM-01, `src/dnd_assistant/models/profiles.py`):

```text
thinking          : bool | None          (flat, optional, provider-gated)
reasoning_effort  : low | high | max     (flat, optional, provider-gated)
```

Canonical project reasoning-effort values are `low`, `high` and `max`
(`ReasoningEffort`). `medium` is a provider compatibility alias and is not a
canonical project value; it is not an enum member and is rejected. Thinking
disabled is represented separately, not as an effort value.

DeepSeek AGENT reasoning contract (fail-closed):

```text
provider=deepseek, role=agent:
  thinking=true  + effort low|high|max   PASS
  thinking=false + effort absent         PASS
  thinking omitted                       FAIL
  thinking=true  + effort omitted        FAIL
  thinking=false + effort present        FAIL
  effort present + thinking omitted      FAIL
  medium / unknown effort                FAIL
```

An AGENT DeepSeek profile must set `thinking` explicitly; it must not fall
through to implicit provider/framework thinking defaults. In RM-01 the
reasoning fields are valid only for `provider="deepseek"` with `role="agent"`;
they are rejected for other providers and other roles (POST_SESSION, BOOTSTRAP,
SUMMARIZER, EMBEDDING). Runtime support for a provider is still established at
the model-construction boundary: profile representability is not provider
support, and unsupported providers continue to fail closed there.

Credential contract (RM-01, `src/dnd_assistant/models/credentials.py`):

```text
provider → environment variable : deepseek -> DEEPSEEK_API_KEY
```

Profile loading performs no environment access. Credential resolution is a
separate machine-local boundary invoked only when a provider transport is
constructed; it returns `pydantic.SecretStr` and fails closed (missing, empty or
whitespace-only) with `CredentialError`, whose text names the environment
variable and never the value. An unknown provider performs no environment
lookup.

RM-01 owns the provider/profile/credential contract and is independently
acceptable: RM-02 follows RM-01 and decides the concrete DeepSeek Pydantic-AI
construction strategy (public built-in path vs narrow public adapter).

Production integration (RM-03): the shared AGENT provider dispatch in
`src/dnd_assistant/composition/agent_model.py` now selects exactly one factory
from the named AGENT profile — `provider="ollama"` →
`build_pydantic_ai_ollama_model()` and `provider="deepseek"` →
`build_pydantic_ai_deepseek_model()` — and fails closed for any other provider.
Provider selection lives below presentation: both `dnd ask` and `dnd tui` reach
it through the same composition, with no provider CLI flag or TUI state. The
canonical profile above is therefore usable for the AGENT role; the credential
is resolved only when the DeepSeek factory is actually selected (an Ollama
profile never reads `DEEPSEEK_API_KEY`), and missing/empty credentials fail
closed with `CredentialError`. `PydanticAIAgentRuntime.run()` keeps its public
synchronous contract while executing one managed public `async with Agent` +
`await Agent.run(...)` run, so provider-owned HTTP clients are closed
deterministically for both Ollama and DeepSeek. This establishes production
wiring only: it is **not** the RM-04 provider/runtime live gate and **not** RM-05
product qualification; no live DeepSeek request or product measurement is part
of RM-03.

## 3. Mandatory pre-product blocker gate

Before any product-v1 measured run, prove the provider protocol in focused
tests/smoke.

DeepSeek thinking tool calls require reasoning continuity across tool
continuation. The test must observe literal outbound/inbound protocol state
without persisting chain-of-thought content.

Primary unresolved blocker (RM-02): pinned Pydantic AI 2.39.0 appears to support
the DeepSeek `reasoning_content` round-trip (its `DeepSeekProvider` profile sets
`openai_chat_thinking_field='reasoning_content'` and
`openai_chat_send_back_thinking_parts='field'`), but explicit thinking /
reasoning-effort behavior for the current official `deepseek-flash` identifier is
**not yet proven**: the pinned model profile gates thinking support on
`deepseek-reasoner` / `deepseek-r1*` / `deepseek-v4-*` names, and the unified
`thinking` setting is silently stripped otherwise. RM-02 resolves this with
executable evidence and decides between Option A (public built-in path) and
Option B (narrow public adapter); the recorded resolution is below.

RM-02 resolution: the blocker is resolved at the source and offline-execution
level and the strategy is **Option B**. Pinned source inspection
(`profiles/deepseek.py`, `providers/deepseek.py`, `models/__init__.py`) confirms
that `deepseek-flash` resolves with `supports_thinking=False` (stripping the
unified `thinking` setting) and with
`openai_supports_forced_tool_choice_with_thinking=True`, which is not truthful
for a V4-family thinking model. RM-02 therefore adds a narrow public adapter
(`src/dnd_assistant/models/pydantic_ai_deepseek.py`) that applies a minimal
public `profile=` override (`supports_thinking=True`,
`thinking_always_enabled=False`,
`openai_supports_forced_tool_choice_with_thinking=False`) and maps the RM-01
contract through public provider-specific settings
(`extra_body={"thinking":{"type":"enabled"|"disabled"}}` and
`openai_reasoning_effort=<low|high|max>`); it does not use the stripped unified
`thinking` setting, copy the built-in provider profile, or patch framework
internals.

Deterministic offline evidence (`tests/unit/test_pydantic_ai_deepseek_factory.py`,
`tests/integration/test_pydantic_ai_deepseek_compatibility.py`) proves the
canonical `deepseek-flash` identifier, the thinking toggle, `reasoning_effort`
(low/high/max), `tool_choice="auto"`, `reasoning_content` → `ThinkingPart`
conversion and replay on the tool-continuation request, and the absence of
reasoning text / prompts / credentials / authorization headers from captured
evidence.

The live wire confirmation was executed once and **passed**: the explicit opt-in
spike (`tests/integration/test_pydantic_ai_deepseek_live_spike.py`, `deepseek`
marker, hard budget 4 model HTTP requests, zero retries) ran with
`DND_ASSISTANT_DEEPSEEK_LIVE=1` and a machine-local `DEEPSEEK_API_KEY`. Case A
(thinking enabled, no tools) and Case B (thinking disabled, no tools) each made
exactly one model HTTP request with a valid terminal result; Case C (thinking
enabled with one deterministic READ tool) made exactly two — one tool invocation
plus its continuation — with request 1 carrying tools and `tool_choice="auto"`,
provider reasoning converted to a non-empty `ThinkingPart`, request 2 carrying
assistant `reasoning_content` and the matching tool result while keeping
`tool_choice="auto"`, and a terminal result containing the expected synthetic
tool result. Total model HTTP requests: exactly 4, retries 0. This proves live
protocol compatibility; it is **not** RM-04 provider qualification and **not**
RM-05 product qualification, and no product baseline was measured. Only
structural sanitized evidence was observed (presence/type/category), never
reasoning text, prompts, bodies, headers or credentials.

Required assertions:

```text
request 1:
  tools present
  thinking enabled
  reasoning effort high

response 1:
  tool call present
  provider reasoning field present/handled

request 2:
  tool result present
  required reasoning state preserved
  no duplicate/extra tool execution

final:
  terminal product outcome valid
```

A 400 caused by missing reasoning continuity is a provider compatibility failure,
not a model-quality failure.

## 3a. RM-04 durable provider/runtime live gate

RM-02 proved protocol compatibility once (spike). RM-04 converts that into the
repeatable, opt-in, provider/runtime qualification gate used for future Pydantic
AI upgrades, DeepSeek protocol/adapter changes and pre-RM-05 qualification.

Module: `tests/integration/test_pydantic_ai_deepseek_live_runtime.py`
(`provider_upgrade` + `deepseek`). The RM-02 spike
(`tests/integration/test_pydantic_ai_deepseek_live_spike.py`, marker `deepseek`
only) remains separate historical evidence and is not part of the durable gate.

Durable selection:

```text
uv run pytest -m "provider_upgrade and deepseek"
```

Explicit machine-local configuration:

```text
DND_ASSISTANT_DEEPSEEK_LIVE=1
DND_ASSISTANT_DEEPSEEK_CONFIG=<path-to-models.toml>
DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE=<profile-name>
DEEPSEEK_API_KEY=<secret>
```

Semantics:

```text
selector absent                          SKIP before config/credential/network
selector set + missing config/profile    FAIL before network, zero requests
selector set + non-canonical profile     FAIL before network, zero requests
selector set + missing/empty credential  FAIL before network, zero requests
real provider/runtime failure            FAIL with sanitized classification
```

The selected profile must be `provider=deepseek`, `role=agent`,
`model=deepseek-flash`, `thinking=true`, `reasoning_effort=high`, canonical base
URL `https://api.deepseek.com`. A distinct candidate is never silently
substituted.

Scenarios and hard budget:

```text
D1  production dispatch + runtime, thinking/high, zero tools, terminal RESPOND   1 request
D2  production dispatch + runtime, thinking/high, one READ probe + continuation   2 requests
--------------------------------------------------------------------------------------------
total maximum                                                                    3 requests
retries                                                                          0
```

Both cases use the real production-sensitive path: `_load_profile` ->
`_build_agent_model` -> `build_pydantic_ai_deepseek_model` ->
`PydanticAIAgentRuntime`, with a synthetic context-builder double, no Vault and
no WRITE tool. D2 asserts, structurally only, that request 1 carries tools with
`tool_choice=auto`, that request 2 replays assistant `reasoning_content` with a
matching tool result and `tool_choice=auto`, and that the tool handler executed
exactly once. No reasoning text, prompt, body, header or credential is ever
retained or printed.

Lifecycle ownership: the injected `httpx2.AsyncClient` that carries the
sanitized recorder is **caller-owned test infrastructure** and is closed
explicitly in test cleanup; it is not provider-lifecycle evidence. Provider-owned
Ollama/DeepSeek client closure through the RM-03 managed `Agent`/`Model` context
is proven offline by `tests/unit/test_pydantic_ai_agent_runtime_lifecycle.py`
(part of `provider_upgrade`).

DeepSeek structured output is **not** part of RM-04: project DeepSeek support is
AGENT-role only and the AGENT runtime uses `str | DeferredToolRequests`, not
structured extraction.

## 4. Hidden reasoning policy

Provider reasoning content is transport/runtime state only.

It must not be:

- rendered in TUI/CLI;
- written to raw campaign logs;
- written to audit;
- written to eval reports;
- written to diagnostic traces;
- copied into summaries/recaps.

Only bounded metadata may be persisted, for example:

```text
thinking_enabled=true
reasoning_effort=high
reasoning_tokens=<count if provider supplies usage>
```

## 5. Error classification

Separate:

```text
AUTH
RATE_LIMIT
NETWORK
TIMEOUT
PROVIDER_4XX
PROVIDER_5XX
PROTOCOL_COMPATIBILITY
MODEL_OUTPUT_VALIDATION
PROJECT_POLICY
```

Do not classify all remote failures as model-quality failures.

## 6. Reasoning-effort qualification policy

Canonical project reasoning-effort values:

```text
low
high
max
```

`medium` is a provider compatibility alias (`medium` maps to `high`), not a
canonical project value. Thinking disabled is represented separately from
reasoning effort, not as an effort level.

Initial agent baseline:

```text
high
```

Alternative effort levels require a distinct candidate task.

Suggested interpretation:

```text
low   = latency/cost candidate
high  = default agent candidate
max   = quality-heavy candidate, only if justified by failed/high evidence
```

Do not silently change effort after a measured run.

## 7. Product measurement

After compatibility and production integration are accepted, run one measured
product candidate through the same provider-neutral collector/scorer.

Record at least:

- provider;
- configured model identifier;
- qualification date;
- reasoning effort;
- thinking enabled/disabled;
- Pydantic AI version;
- Python version/platform;
- latency p50/p95;
- request counts;
- tool/handler counts;
- runtime errors;
- safety/quality verdict.

Do not record credentials, full endpoint URLs containing secrets, request bodies
or provider reasoning text.

### 7a. RM-05 explicit live DeepSeek eval path

The explicit live DeepSeek product path is `dnd eval run --runtime deepseek`
(`src/dnd_assistant/composition/eval_deepseek.py`). It reuses the accepted
provider-neutral runner/report machinery unchanged and only swaps the model
operator: the production dispatch `_load_profile -> _build_agent_model ->
build_pydantic_ai_deepseek_model`. The measured candidate is the canonical AGENT
identity only (`provider=deepseek`, `model=deepseek-flash`, `role=agent`,
`thinking=true`, `reasoning_effort=high`, base URL `https://api.deepseek.com`);
any other identity fails closed before credential/network access.

Deterministic ownership is preserved:

```text
warm-up            1 discarded EVAL-P1-001 (policy one-discarded-eval-p1-001)
measured passes    exactly 1 run_dataset(product-v1)
measured samples   13 (13 scenarios x 1 repetition)
requests / turn    at most 2 (DndAgentPolicy allows one deferred batch)
absolute ceiling   14 x 2 = 28 model requests; no retry budget
```

`response_model` reports the public provider-reported `ModelResponse.model_name`
verbatim (an API alias, not a claim about an exact underlying release). If the
identifier is absent it is `not-reported`; if identifiers differ across the run
it is `multiple`. Official DeepSeek documentation is the authority for
`documented_route` (`DeepSeek-V4.1-Flash`); `model` remains `deepseek-flash`.

Output-target preflight runs before any trace open, runtime selection, credential
resolution or model request (`preflight_report_target`). It rejects a missing
parent, a directory target and an existing target when `--overwrite` is absent,
probes destination-directory writability without touching the final target and
always removes its probe. The measured command must **not** pass `--overwrite`.

Trace freshness (append-only trace): the measurement trace path is
measurement-SHA-specific and must **not** already exist, e.g.

```text
$env:TEMP\rm-05-deepseek-<MEASUREMENT-SHA>.jsonl
```

If it exists, stop before measurement rather than append and corrupt request-count
evidence. The generic append-only trace semantics are unchanged.

```powershell
uv run dnd eval run --runtime deepseek --dataset product-v1 `
  --config <machine-local-models.toml> `
  --profile <canonical-deepseek-profile> `
  --output docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json `
  --trace "$env:TEMP\rm-05-deepseek-<MEASUREMENT-SHA>.jsonl"
```

A completed measurement is consumed: no model/profile/prompt/dataset/threshold
change and no second measured pass, whether `accepted=true` or `accepted=false`.

### 7b. RM-05 measured result

```text
measurement SHA          d52536973eb7e6806b06dcae72c007116ca4f476
candidate                deepseek-flash / thinking=true / reasoning_effort=high
profile                  agent-deepseek
frozen artifact          docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json
artifact SHA-256         3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd
artifact bytes / lines   36804 / 1355
accepted                 true
reasons                  []
complete samples         13/13
runtime errors           0
unauthorized WRITE       0 (SYSTEM SAFETY PASS)
false-write quality      0/3 = 0.0 PASS (threshold 0.0)
measured model requests  22
warm-up requests         1
local trace total        23 request_started (non-committed; ceiling 28)
```

The one-time real-secret absence check over the frozen artifact `PASS`ed during
measurement (the value was never printed). The committed frozen-artifact
contract is fully offline and does **not** require `DEEPSEEK_API_KEY`; it
structurally proves the artifact contains no `Authorization`, `reasoning_content`,
`api_key`/credential, config-path, machine user/home path or raw
request-header/body persistence. Report-only metric and sample-score misses
(EVAL-P1-002/004/007) are descriptive and add no acceptance requirement.

The candidate is consumed and must never be rerun. This measured result is a
candidate qualification only: the accepted canonical live baseline remains
`NONE`, and the baseline adoption/closure decision belongs to RM-06.

## 8. External references

- https://api-docs.deepseek.com/guides/thinking_mode/
- https://api-docs.deepseek.com/guides/tool_calls/
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/quick_start/pricing/
