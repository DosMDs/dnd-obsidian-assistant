# ADR-0010: Remote DeepSeek provider architecture

- **Status:** Accepted
- **Date:** 2026-09-21
- **Milestone:** `v0.5.0 — Accepted Live Model Baseline`
- **Initial task:** `RM-00`

This ADR adopts the architecture direction for the post-MVP milestone
`v0.5.0 — Accepted Live Model Baseline`. It does not implement it: no provider
code, dependency, credential use, network/model call or live eval is authorized
by this decision. Current roadmap state remains authoritative in
`DEVELOPMENT_STATUS.md`; this ADR is durable architecture/decision context.

## Context

The repository is currently on `main` after Stage-14 integration. The current MVP
is `RELEASE_READY` under ADR-0009, while the historical accepted-live-model
requirement remains `BLOCKED / UNSATISFIED` and is explicitly deferred to the
adopted post-MVP milestone `v0.5.0 — Accepted Live Model Baseline`.

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

The canonical project model identifier is the current official
`deepseek-flash` (served as DeepSeek-V4.1-Flash at the decision date). The
retired `deepseek-v4-flash` name must **not** be adopted as the project model
identifier merely to work around the pinned Pydantic AI model-profile mismatch;
its temporary compatibility routing may be used only as diagnostic evidence
inside the RM-02 spike.

The canonical project reasoning-effort values are `low`, `high` and `max`,
matching documented DeepSeek OpenAI-format effort control. `medium` is a
provider compatibility alias, not a canonical project value. Thinking disabled
is represented separately from reasoning effort, not as an effort level.

`high` is the initial agent qualification level because the provider documents
it as the default reasoning level for agent workloads (thinking enabled by
default). `low` and `max` remain explicit future comparison candidates; neither
becomes an implicit fallback.

Model name and reasoning effort remain profile configuration and eval evidence,
not domain/application architecture.

## Provider-specific compatibility blocker

DeepSeek thinking-mode tool calling requires assistant `reasoning_content` to be
preserved in subsequent tool-bearing requests. Failure to preserve it causes a
provider protocol failure (HTTP 400).

The project currently pins:

```text
pydantic-ai-slim[openai] == 2.39.0
```

Repository/API inspection at the decision date found:

- the pinned Pydantic AI ships a `DeepSeekProvider` (OpenAI-compatible), whose
  model profile configures `openai_chat_thinking_field='reasoning_content'` and
  `openai_chat_send_back_thinking_parts='field'`, citing DeepSeek's
  "pass reasoning_content back" requirement — so the reasoning round-trip
  mechanism **appears** supported for the pinned version;
- however, the same pinned version recognizes thinking support only for
  `deepseek-reasoner` / `deepseek-r1*` / `deepseek-v4-*` model names, and its
  unified `thinking` setting is silently stripped when the profile does not
  declare thinking support.

Therefore explicit thinking/reasoning-effort behavior for the current official
`deepseek-flash` identifier is **not yet proven**. This is the primary unresolved
blocker and must be resolved by executable RM-02 evidence, not by assumption or
by switching the project model identifier to a retired name.

DeepSeek adoption is blocked until executable evidence proves that the selected
Pydantic AI integration path:

1. sends thinking/reasoning settings correctly for `deepseek-flash`;
2. preserves provider-required reasoning state across model→tool→model;
3. preserves the existing bounded request/tool budgets;
4. does not persist or present hidden reasoning content;
5. maps provider failures into the existing fail-closed runtime behavior.

No assumption of "OpenAI compatibility" is sufficient evidence by itself.

## Supported implementation strategy

Preferred order:

```text
A. Pydantic AI public OpenAI-compatible built-in provider/model path
B. narrow project-owned adapter using public Pydantic AI extension points
C. reject adoption if preserving invariants requires framework-private patching
```

The concrete A-vs-B decision belongs to `RM-02` and must be made from executable
evidence. `RM-01` owns the provider/profile/credential contract independently and
must be implementable and acceptable without depending on a future `RM-02`
result. Do not duplicate the agent runtime, ToolExecutor, domain services or
Vault write path for DeepSeek.

## RM-02 resolution: Option B (public profile override)

`RM-02` resolved the supported-implementation-strategy question from pinned
source inspection plus deterministic offline execution. The selected strategy is
**Option B** — a narrow project-owned adapter using only public Pydantic AI
extension points — because the pinned built-in DeepSeek profile is not
capability-truthful for the canonical `deepseek-flash` identifier:

- `pydantic_ai.profiles.deepseek.deepseek_model_profile` recognizes thinking
  support only for `deepseek-reasoner` / `deepseek-r1*` / `deepseek-v4-*` names,
  so `deepseek-flash` resolves with `supports_thinking=False` and the unified
  `thinking` setting is stripped before reaching the wire;
- `DeepSeekProvider.model_profile` derives
  `openai_supports_forced_tool_choice_with_thinking` from the same outdated
  `is_v4` model-name test, so it incorrectly reports forced tool choice as
  supported for `deepseek-flash` while thinking is active.

The accepted concrete mechanism is
`src/dnd_assistant/models/pydantic_ai_deepseek.py`:
`build_pydantic_ai_deepseek_model()` constructs the public `DeepSeekProvider` and
`OpenAIChatModel`, applies a minimal public `profile=` override
(`supports_thinking=True`, `thinking_always_enabled=False`,
`openai_supports_forced_tool_choice_with_thinking=False`), and maps the RM-01
contract through public provider-specific settings
(`extra_body={"thinking":{"type":"enabled"|"disabled"}}` and
`openai_reasoning_effort=<low|high|max>`). It does not copy the built-in
provider profile, duplicate OpenAI transport or message/reasoning mapping,
subclass the provider, or patch framework-private state.

The `reasoning_content` round-trip is provided by the pinned provider profile
(`openai_chat_thinking_field='reasoning_content'`,
`openai_chat_send_back_thinking_parts='field'`) and is independent of the
thinking-capability flag; offline tests confirm conversion to `ThinkingPart` and
replay on the tool-continuation request.

Live confirmation is pending: `RM-02` provides an explicit opt-in live spike
(`tests/integration/test_pydantic_ai_deepseek_live_spike.py`, `deepseek` marker,
hard budget of 4 HTTP model requests, zero retries) but the machine-local
`DEEPSEEK_API_KEY` was unavailable at implementation time, so no real-provider
request was executed and `RM-02` remains `BLOCKED` on that live evidence. This
decision does not authorize production DeepSeek dispatch: `composition/
agent_model.py` and the production CLI/TUI remain Ollama-only; `RM-03` owns
production integration.

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
