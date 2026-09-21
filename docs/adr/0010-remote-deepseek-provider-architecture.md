# ADR-0010: Remote DeepSeek provider architecture

- **Status:** Proposed for acceptance
- **Date:** 2026-09-21
- **Milestone:** `v0.5.0 — Accepted Live Model Baseline`
- **Initial task:** `RM-00`

## Context

The repository is currently on `main` after Stage-14 integration. The current MVP
is `RELEASE_READY` under ADR-0009, while the historical accepted-live-model
requirement remains `BLOCKED / UNSATISFIED` and is explicitly deferred to the
post-MVP milestone concept `v0.5.0 — Accepted Live Model Baseline`.

Three local Ollama candidates were consumed under the frozen Stage-14 product
contract and none was accepted. Their evidence is historical and immutable.

The codebase already has provider-neutral concepts (`ModelProfile`,
`ModelGateway`, Pydantic AI `Model`) but production agent composition currently
accepts only `provider="ollama"`, and the live product eval path currently
dispatches only `scripted` and `ollama`.

A remote provider is therefore a bounded infrastructure extension, not a domain
redesign.

## Decision

Add DeepSeek as the first supported remote model provider while preserving the
existing runtime trust boundaries.

Target path:

```text
ModelProfile
  → provider-specific Pydantic AI model construction
  → PydanticAIAgentRuntime
  → DndAgentPolicy
  → PydanticAIToolBridge
  → ToolExecutor
  → trusted application/domain/storage
```

The project becomes **local-first and provider-neutral**. Ollama remains
supported. DeepSeek is an additional provider, not a replacement of the trusted
Python core.

## Initial model choice

The first qualification candidate is:

```text
provider          deepseek
model             deepseek-flash
reasoning_effort  high
thinking          enabled
role              agent
```

At the decision date, `deepseek-flash` routes to DeepSeek V4.1 Flash.

`high` is chosen as the first agent qualification level because the provider
documents it as the normal/default reasoning level for agent workloads.
`low` and `max` remain explicit future comparison candidates; neither becomes an
implicit fallback.

Model name and reasoning effort remain profile configuration and eval evidence,
not domain/application architecture.

## Provider-specific compatibility blocker

DeepSeek thinking-mode tool calling requires assistant `reasoning_content` to be
preserved in subsequent tool-bearing requests. Failure to preserve it causes a
provider protocol failure.

The project currently pins:

```text
pydantic-ai-slim[openai] == 2.39.0
```

Therefore DeepSeek adoption is blocked until executable evidence proves that the
selected Pydantic AI integration path:

1. sends thinking/reasoning settings correctly;
2. preserves provider-required reasoning state across model→tool→model;
3. preserves the existing bounded request/tool budgets;
4. does not persist or present hidden reasoning content;
5. maps provider failures into the existing fail-closed runtime behavior.

No assumption of "OpenAI compatibility" is sufficient evidence by itself.

## Supported implementation strategy

Preferred order:

```text
Pydantic AI public OpenAI-compatible provider/model path
→ public extension point / narrow project-owned adapter if required
→ reject adoption if preserving invariants requires framework-private patching
```

Do not duplicate the agent runtime, ToolExecutor, domain services or Vault write
path for DeepSeek.

## Credentials and data boundary

DeepSeek API credentials are machine-local secrets.

They must not be:

- committed;
- stored in the Vault;
- written to eval reports, audit records or traces;
- echoed in error messages.

Remote-provider profiles may contain non-secret endpoint/model/settings metadata.

The application must send only application-prepared context required by the
request. Remote-provider support is not permission for unrestricted Vault
upload, raw filesystem access or provider-side campaign memory.

## Eval and acceptance

The DeepSeek candidate must be measured against the accepted product eval
contract, preserving the hard safety rules.

A candidate cannot be accepted if:

- SYSTEM SAFETY fails;
- unauthorized WRITE handler execution occurs;
- required runtime/protocol smoke fails;
- the measured report is incomplete;
- provider credentials or hidden reasoning leak into persisted evidence.

The historical three Ollama candidate reports are not modified or reinterpreted.

## Consequences

Positive:

- resolves the architectural dependency on local inference availability;
- creates a realistic path to satisfy the deferred accepted-live-model milestone;
- keeps model selection configurable and benchmark-driven;
- reuses current Pydantic AI/runtime/tool/application boundaries.

Costs/risks:

- network/API availability;
- secret management;
- remote data exposure;
- provider-specific reasoning/tool protocol semantics;
- latency and usage cost;
- dependence on current provider API behavior.

These are provider-infrastructure risks and must remain outside domain/storage
contracts.

## References

Repository:
- `DEVELOPMENT_STATUS.md`
- `docs/adr/0009-release-scope-defers-live-model-qualification.md`
- `docs/development/provider-runtime-upgrade.md`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/pydantic_ai_ollama.py`
- `src/dnd_assistant/composition/agent_model.py`
- `src/dnd_assistant/composition/eval_ollama.py`
- `src/dnd_assistant/cli/eval.py`

Provider:
- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/guides/thinking_mode/
- https://api-docs.deepseek.com/guides/tool_calls/
- https://api-docs.deepseek.com/api/create-chat-completion/
