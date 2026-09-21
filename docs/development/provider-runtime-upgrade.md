# Provider / runtime upgrade runbook

Operational maintenance procedure for changing the Pydantic AI runtime,
the Ollama runtime, or model/profile configuration. This is a future-facing
runbook, not migration history. Historical Pydantic AI migration evidence lives
in `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` and
`docs/adr/0003-pydantic-ai-runtime-migration.md`.

The project owns policy and consequences; Pydantic AI and Ollama are
replaceable mechanisms. Framework tool exposure/filtering/approval is **not**
an authorization boundary. Every side effect still flows through
`DndAgentPolicy` → `PydanticAIToolBridge` → `ToolExecutor` → application /
`VaultRepository`.

## 1. Scope and vocabulary

This runbook applies when a change touches any of:

- the Pydantic AI package family resolved through `uv.lock`;
- the Ollama runtime binary;
- a remote provider protocol/API compatibility surface or the project-owned
  remote-provider adapter (currently the DeepSeek adapter);
- a model/profile value that changes provider behavior.

It does **not** apply to ordinary product work that merely happens to live in a
repository containing Pydantic AI.

## 2. Trigger classes

| Class | Trigger | Notes |
|---|---|---|
| U1 | Pydantic AI framework/package change (`pydantic-ai-slim`, `pydantic-ai`, `pydantic-graph`, or directly coupled OpenAI client changes produced by lock resolution) | Provider integration may have changed |
| U2 | Ollama runtime binary change | No Python dependency bump may occur |
| U3 | model / profile value change (model tag, temperature, timeout, role profile, base-URL semantics), for any provider including DeepSeek | Config-only; may accompany U1/U2/U5 or stand alone |
| U4 | no provider/runtime-related change | No special gate required |
| U5 | remote-provider compatibility change: the DeepSeek provider protocol/API surface, or the project-owned DeepSeek adapter (`src/dnd_assistant/models/pydantic_ai_deepseek.py`) | External/API or adapter code; a DeepSeek *model/profile value* change stays U3, not U5 |

A change is only a U4 when it touches none of the U1–U3/U5 surfaces. The
existence of Pydantic AI in the repository is not by itself a trigger.

Each applicable change must have exactly one primary trigger classification:
DeepSeek model/profile **values** are classified U3; only the DeepSeek
protocol/API compatibility surface or adapter code is U5. A single change may
*additionally* accompany another class, but it is not simultaneously the primary
trigger of two classes.

## 3. Baseline capture (before any change)

```text
clean working tree
exact starting SHA
exact current direct pin (pyproject.toml)
exact accepted/current runtime versions (uv.lock for Python; external for Ollama)
uv lock --check
```

Record the accepted/current version of every affected component. For Ollama,
record the runtime version as **external evidence** (e.g. `/api/version`); it is
never derivable from `pyproject.toml` or `uv.lock`.

## 4. Authoritative upstream review

Before changing a pin or runtime, review the authoritative sources and record
the result for each relevant theme.

Sources:

```text
Pydantic AI
  https://github.com/pydantic/pydantic-ai/releases
  https://ai.pydantic.dev/changelog/         (canonical changelog)
  https://ai.pydantic.dev/upgrade/           (upgrade guide, when present)

Ollama
  https://github.com/ollama/ollama/releases
  native endpoints /api/version, /api/tags (already read by the live gate)

DeepSeek (remote provider protocol/API, for U5)
  https://api-docs.deepseek.com/guides/thinking_mode/
  https://api-docs.deepseek.com/guides/tool_calls/
  https://api-docs.deepseek.com/api/create-chat-completion/
```

Recorded review fields (required):

```text
accepted/current version
candidate version
review date
authoritative release/changelog source
reviewed range (accepted .. candidate)
relevant compatibility / breaking notes
relevant issue references
unresolved upstream risks
```

Targeted themes to review rather than "read all issues":

```text
tools / toolsets / exposure preparation
DeferredToolRequests / DeferredToolResults
HandleDeferredToolCalls / capability behavior
Agent.run_sync
UsageLimits
tool retries / output retries
parallel vs sequential tool execution
worker-thread behavior
OllamaProvider / OllamaModel
OpenAI-compatible tool messages
structured output / ToolOutput
exception / error mapping
```

Classification per theme: `REVIEWED`, `NOT APPLICABLE`, `OPEN RISK`.

Do not encode a specific "latest" version as policy. Versions recorded by a
past review are dated evidence only; a new upgrade re-runs this review.

## 5. Candidate isolation

- Start from a clean worktree and an ordinary forward task branch.
- Change only the intended direct pin, profile value, or runtime input.
- Do not bundle unrelated dependency upgrades.
- Do not edit `uv.lock` by hand.

## 6. pyproject / profile diff

Review the exact diff of `pyproject.toml` and any configuration/profile change.
For U3, the diff is config-only and must not silently pull a package change.

## 7. uv lock workflow

Supported command shapes (narrowest first):

```text
uv lock --upgrade-package <name>     # update one package's resolution
uv lock                              # reconcile after a pin edit
uv lock --check                      # verify the lock is up to date
```

Then classify every `uv.lock` change:

```text
TARGET                the intended package (and its direct metadata)
REQUIRED_TRANSITIVE   a legitimate consequence of the target change
UNRELATED             anything else
```

Any `UNRELATED` upgrade blocks acceptance until justified or removed. Do not
require a byte-identical lock outside the expected dependency closure;
transitive changes can be legitimate.

## 8. Offline curated gate

```text
uv run pytest -m "provider_upgrade and not ollama and not deepseek"
```

This selection is deterministic, offline and requires no running Ollama, no
internet and no secrets. It is the curated Pydantic AI / provider / runtime
regression gate for **all** supported providers. The provider-specific live
markers must be excluded explicitly: a durable live module carries
`provider_upgrade + deepseek`, so an older `provider_upgrade and not ollama`
expression would incorrectly collect DeepSeek live tests. Its reviewed
inventory is protected by `tests/contract/test_provider_upgrade_gate.py`.

For a U3 profile change, also run the profile/provider tests it affects
(provider factory, composition, profile validation) even if they are outside
the marker selection.

## 9. Static / repository gates

```text
uv run pyright
uv run ruff check .
uv run ruff format --check .
git diff --check
```

## 10. Canonical suite

```text
uv run pytest
```

One canonical run after focused/affected/static gates are stable. Follow
`docs/development/quality-and-evidence.md` for failure-loop and rerun policy.

## 11. Live compatibility gates

Mandatory for every applicable U1/U2 and for U5 (DeepSeek protocol/adapter
changes); for a U3 model/profile change when provider interaction is involved.
Each provider has its own explicit live selection.

### 11.1 Ollama live gate

```text
uv run pytest -m "provider_upgrade and ollama"
```

Live configuration:

```text
integration/test_pydantic_ai_ollama_smoke.py
    DND_ASSISTANT_OLLAMA_SMOKE_CONFIG=<base_url>,<model_name>
integration/test_pydantic_ai_ollama_live_runtime.py
    DND_ASSISTANT_PAIM12_CONFIG=<path-to-models.toml>
    DND_ASSISTANT_PAIM12_AGENT_PROFILE=<profile-name>
```

The two Ollama live modules have distinct roles:

```text
integration/test_pydantic_ai_ollama_smoke.py
    standalone OllamaModel/OllamaProvider + real structured output
integration/test_pydantic_ai_ollama_live_runtime.py
    production factory/runtime + real tool continuation
```

### 11.2 DeepSeek durable live gate

```text
uv run pytest -m "provider_upgrade and deepseek"
```

Live configuration:

```text
DND_ASSISTANT_DEEPSEEK_LIVE=1
DND_ASSISTANT_DEEPSEEK_CONFIG=<path-to-models.toml>
DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE=<profile-name>
DEEPSEEK_API_KEY=<secret>
```

The selected profile must be the canonical AGENT identity
(`provider=deepseek`, `model=deepseek-flash`, `thinking=true`,
`reasoning_effort=high`, canonical base URL). The gate exercises the real
production path `_load_profile -> _build_agent_model -> factory ->
PydanticAIAgentRuntime` with a synthetic context, zero tools (D1) and exactly
one deterministic READ probe (D2); hard budget 3 model HTTP requests, zero
retries. Full procedure: `docs/development/deepseek-provider-qualification.md`.

Do **not** use bare `-m deepseek` as the maintenance gate: it also collects the
historical RM-02 protocol-compatibility spike
(`integration/test_pydantic_ai_deepseek_live_spike.py`, marker `deepseek`, **not**
`provider_upgrade`), which is separate focused evidence and would spend extra
requests. RM-02 spike selection (diagnostic only):

```text
uv run pytest -m "deepseek and not provider_upgrade"
```

Do not add latency or product-quality thresholds here. Product-quality
measurement belongs to the prospective `v0.5.0 — Accepted Live Model Baseline`
product-qualification workflow (RM-05), not to this compatibility gate.

## 12. Model-quality gate handoff

The provider/runtime live gate proves **compatibility only**; it never proves
model-quality acceptance.

A model/profile candidate that requires product qualification must pass the
current accepted product-eval contract before it can become an accepted
baseline. The `v0.5.0 — Accepted Live Model Baseline` workstream performed this
(`RM-05` measured product-v1 DeepSeek candidate qualification; `RM-06`
accepted-baseline decision / closure).

### 12.1 Accepted canonical baseline

An accepted canonical live baseline now exists:

```text
provider             deepseek
model                deepseek-flash
role                 agent
thinking             true
reasoning_effort     high
dataset              product-agent v1
sample plan          single-pass-v1
prompt               agent-v3
qualification date   2026-09-21
measurement SHA      d52536973eb7e6806b06dcae72c007116ca4f476
artifact             docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json
artifact SHA-256     3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd
contract             tests/contract/test_eval_rm05_deepseek_frozen_candidate.py
```

This is the accepted **AGENT** qualification baseline. It covers AGENT tool /
continuation semantics; it does **not** qualify structured-output behavior
(project DeepSeek support is AGENT-role only and the AGENT runtime uses
`str | DeferredToolRequests`). `documented_route = DeepSeek-V4.1-Flash` is
qualification-time evidence, not a perpetual routing guarantee. The artifact is
immutable; no future task mutates, copies or reuses it as a live candidate.

### 12.2 Prospective requalification policy

```text
U1/U5 (provider-framework / protocol / adapter change)
  → run the applicable offline + live provider/runtime gates before trusting
    compatibility

U3 materially different model/profile value
  → a distinct qualification candidate
  → never mutate or reuse the frozen accepted artifact
  → apply the then-current accepted product-eval contract and make an explicit
    acceptance decision

material remote provider-side routing / API change
  → the frozen artifact remains historical accepted qualification evidence
  → requalify current provider/runtime compatibility under this runbook
  → run a distinct product qualification when product identity materially
    changes
```

A frozen remote baseline does not prove that an external alias will forever
behave identically. Baseline comparison is available through the existing
`dnd eval report --input <candidate> --baseline <accepted-artifact>` path; the
accepted artifact is supplied explicitly and no repository default/registry is
introduced. A newer accepted baseline supersedes the current one prospectively
only through another explicit baseline-adoption task.

This is a prospective, provider-neutral rule. It is not bound to the historical
Stage-14 task `S14-07` (which remains `BLOCKED` / `UNSATISFIED`, with its
consumed candidates and the ADR-0009 deferral preserved as history; that
requirement was later fulfilled by the separate `v0.5.0` workstream).

## 13. Outcome classification

### ACCEPTED

```text
intended version/profile diff only
required upstream changes reviewed
lock diff classified (no unresolved UNRELATED)
offline curated gate green
static/repository gates green
canonical suite green
required live gate green
no architecture/safety regression
HEAD/upstream evidence complete
```

### BLOCKED

```text
required live environment unavailable when live evidence is mandatory
unresolved upstream risk
candidate cannot be tested
unresolved unrelated lock changes
```

BLOCKED is not a failed product candidate; it is incomplete evidence.

### REJECTED

The candidate demonstrably violates a project invariant or required runtime
behavior. Record exactly:

```text
candidate version
failing invariant
minimal reproducible failing test
observed error
whether the failure is framework/provider/model-specific
rollback result
```

### SKIPPED_CAPABILITY

Only for a genuinely unavailable capability that this runbook explicitly marks
non-blocking. Never use it to hide a required provider smoke for an upgrade
that is being accepted.

## 14. Rollback / rejection

```text
ordinary forward task branch
small version/profile diff
no history rewrite
revert the candidate diff, or abandon the task branch
```

Git is the rollback mechanism. Do not keep a permanent dual runtime and do not
add a fallback-provider feature flag merely to accommodate an incompatible
upgrade.

## 15. Final evidence checklist

```text
baseline SHA and clean start
accepted version -> candidate version
review date and authoritative sources
reviewed range and compatibility notes
pyproject.toml diff
uv.lock diff classified TARGET / REQUIRED_TRANSITIVE / UNRELATED
offline curated gate result
canonical suite result
live gate result (or explicit BLOCKED reason)
outcome classification
HEAD == upstream and clean worktree
```
