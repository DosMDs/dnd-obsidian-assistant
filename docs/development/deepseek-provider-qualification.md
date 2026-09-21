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

Exact profile schema is finalized by RM-01; this sample is normative intent, not
permission to bypass current `extra="forbid"` validation.

## 3. Mandatory pre-product blocker gate

Before any product-v1 measured run, prove the provider protocol in focused
tests/smoke.

DeepSeek thinking tool calls require reasoning continuity across tool
continuation. The test must observe literal outbound/inbound protocol state
without persisting chain-of-thought content.

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

## 8. External references

- https://api-docs.deepseek.com/guides/thinking_mode/
- https://api-docs.deepseek.com/guides/tool_calls/
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/quick_start/pricing/
