# v0.5.0 — Accepted Live Model Baseline

- **Status:** `DONE / CLOSED` (closed by `RM-06`)
- **Created:** 2026-09-21
- **Predecessor:** current MVP `RELEASE_READY` under ADR-0009

## 1. Goal

Establish at least one accepted canonical live agent model/provider baseline
without weakening the accepted product-eval or safety contract.

Initial provider direction: DeepSeek remote API.

This milestone owns the deferred requirement created by ADR-0009. It is not
Stage 15 and does not alter Stage-14 historical outcomes.

## 2. Entry state

```text
Stage 14                            DONE / integrated
current MVP                          RELEASE_READY
historical S14-07                    BLOCKED / UNSATISFIED
accepted canonical live baseline     none
```

Current branch, HEAD and roadmap status are mutable and are **not** snapshotted
here as continuing state. The authoritative current state is
`DEVELOPMENT_STATUS.md` plus live Git/GitHub; this milestone record stores the
durable entry scope and task contract only.

Consumed local candidates remain historical evidence:

```text
qwen3.5:9b
ministral-3:8b
qwen3:14b
```

No consumed attempt is rerun.

## 3. Architecture constraints

Must preserve:

- Vault Source of Truth;
- trusted Python domain/application/storage;
- ToolExecutor final authorization;
- DndAgentPolicy budgets/batch semantics;
- ChangeSet review/apply;
- player visibility filtering;
- deterministic calendar;
- immutable raw-session evidence;
- machine-local provider credentials;
- provider/model replaceability.

## 4. Initial candidate

```text
provider           deepseek
model              deepseek-flash
thinking           enabled
reasoning_effort   high
role               agent
```

Canonical project reasoning-effort values are `low`, `high` and `max`; `medium`
is a provider compatibility alias and is not a canonical project value. Thinking
disabled is represented separately. The retired `deepseek-v4-flash` name must not
replace `deepseek-flash` as the project identifier; its compatibility routing is
diagnostic evidence for RM-02 only.

The exact served model version must be captured at qualification time if the
provider exposes it; otherwise record the documented routing/version and
qualification date.

## 5. Task decomposition

### RM-00 — Remote-provider architecture + DeepSeek qualification plan

`PLAN_REQUIRED` / documentation-adoption only.

Read-only investigation plus architecture/documentation adoption. Proves owning
layers, the exact compatibility blocker, intended changed files,
acceptance→evidence map and rollback path. Deliverables: accepted
`docs/adr/0010-remote-deepseek-provider-architecture.md`, this milestone record,
`docs/development/deepseek-provider-qualification.md`, and a reconciled
`DEVELOPMENT_STATUS.md`. RM-00 performs no production Python, provider,
dependency, credential, network/model or live-eval change.

### RM-01 — Provider/profile/credential contract

Status: `DONE` (typed contract only; no provider runtime).

Implemented the minimum provider-neutral configuration changes needed for
DeepSeek:

- flat typed `thinking: bool | None` and `reasoning_effort: low|high|max`
  (`ReasoningEffort`) on `ModelProfile`, preserving `extra="forbid"` and
  `frozen=True`; `provider` remains an open string so representability stays
  independent of production support;
- provider/role-gated validation: reasoning fields are DeepSeek-AGENT-only, and
  an AGENT DeepSeek profile must set `thinking` explicitly (no implicit
  provider/framework thinking defaults);
- machine-local credential lookup contract (`models/credentials.py`;
  `deepseek -> DEEPSEEK_API_KEY`) returning `SecretStr`, fail-closed on
  missing/empty/whitespace, with no environment access during profile loading;
- secret-safe errors (`CredentialError`) that never contain the value;
- no Vault configuration coupling.

RM-01 is independently implementable and acceptable as the typed
provider/profile/credential contract. Its acceptance does **not** depend on a
future RM-02 result: it defines the contract, not the concrete DeepSeek
construction strategy. RM-02 remains `NOT STARTED`, and no accepted live
baseline is claimed.

No product live run.

### RM-02 — DeepSeek protocol compatibility spike + A/B architecture decision

Status: `DONE`. Live protocol compatibility `PASS`. Selected strategy:
**Option B** (narrow public profile override).

Follows RM-01. Executable qualification of the pinned Pydantic AI path, and the
decision between:

```text
A. Pydantic AI public OpenAI-compatible built-in provider/model path
B. narrow project-owned adapter using public Pydantic AI extension points
```

RM-02 must resolve the primary unresolved blocker: pinned Pydantic AI 2.39.0
appears to support DeepSeek `reasoning_content` round-trip semantics, but
explicit thinking/effort behavior for the current official `deepseek-flash`
identifier is not yet proven (the pinned model profile gates thinking support on
`deepseek-reasoner` / `deepseek-r1*` / `deepseek-v4-*` names and silently strips
the unified `thinking` setting otherwise).

Must prove at minimum:

```text
plain response
thinking high request
one READ tool call
tool result continuation
reasoning_content continuity
multiple READ calls if runtime supports the same accepted semantics
structured/terminal outcome
provider 4xx/5xx/auth/timeout mapping
zero hidden-reasoning persistence
```

If the public built-in path (Option A) cannot preserve the required semantics for
`deepseek-flash`, RM-02 records explicit evidence and decides Option B (narrow
public adapter) or rejection; a provider-private patch is not an acceptable
outcome. The retired `deepseek-v4-flash` routing may be recorded as diagnostic
evidence only, not adopted as the project model identifier.

RM-02 result: pinned source inspection and deterministic offline tests show the
built-in `deepseek-flash` profile reports `supports_thinking=False` (unified
`thinking` stripped) and incorrectly permits forced tool choice while thinking is
active, so Option A in its unmodified built-in form is not capability-truthful.
Option B was selected accordingly: a narrow public adapter
(`src/dnd_assistant/models/pydantic_ai_deepseek.py`) applies a minimal public
`profile=` override and maps RM-01 settings through provider-specific
`extra_body` / `openai_reasoning_effort`. Offline tests prove the request shape,
`tool_choice="auto"`, the `reasoning_content` conversion/replay path, and
non-leakage. The explicit opt-in live spike was then executed once against the
real provider under the `deepseek` marker with a hard budget of 4 model HTTP
requests and zero retries and **passed**: Case A (thinking enabled, no tools) and
Case B (thinking disabled, no tools) each made exactly one request, and Case C
(thinking enabled with one deterministic READ tool) made exactly two — one tool
invocation plus its continuation — with the framework replaying assistant
`reasoning_content` and the matching tool result while keeping
`tool_choice="auto"`, for exactly four model HTTP requests total. This proves
live protocol compatibility only: no product baseline was measured, no accepted
canonical live baseline exists, production composition is unchanged, and RM-03
has not started.

No product baseline measurement yet.

### RM-03 — Production agent composition integration

Status: `DONE`. Production AGENT composition supports `ollama | deepseek`;
provider lifecycle is managed generically.

Extend shared presentation-neutral production composition so an AGENT profile
can select `ollama` or `deepseek`.

Do not fork the agent runtime.

Typer and Textual must continue to use the same application behavior.

Result: the shared dispatch in
`src/dnd_assistant/composition/agent_model.py` selects exactly one provider
factory (`ollama` → `build_pydantic_ai_ollama_model()`, `deepseek` →
`build_pydantic_ai_deepseek_model()`) and fails closed for any other provider.
CLI and TUI both reach selection through the same shared composition with no new
flag or UI. `PydanticAIAgentRuntime.run()` keeps its public synchronous contract
while executing one managed public `async with Agent` + `await Agent.run(...)`
run, closing provider-owned HTTP clients deterministically for both providers;
a narrow project-owned re-entry guard preserves the fail-fast nested/active-loop
invariant without framework-private APIs. No live DeepSeek call, no product-v1
run, no dependency change, and no new runtime were introduced. Production
composition now supports DeepSeek, but this does **not** qualify the provider
runtime gate, accept a product candidate or establish an accepted canonical live
baseline.

### RM-04 — DeepSeek live smoke / provider gate

Status: `DONE` — durable DeepSeek provider/runtime live gate `PASS`.

Add explicit opt-in live provider tests and update the provider/runtime upgrade
runbook.

Normal `uv run pytest` remains secret/network independent.

Required live configuration must fail rather than silently skip when explicitly
requested and invalid.

Result: `provider_upgrade` is provider-neutral. The offline curated gate is now
`uv run pytest -m "provider_upgrade and not ollama and not deepseek"` (it can no
longer accidentally execute either live provider), and RM-01/RM-02/RM-03
provider-sensitive offline regressions (DeepSeek factory, DeepSeek protocol
compatibility, provider-neutral managed lifecycle, DeepSeek reasoning profile
contract, credential boundary, and a new DeepSeek production-runtime offline
preflight) joined the reviewed `provider_upgrade` inventory protected by
`tests/contract/test_provider_upgrade_gate.py`. The durable live gate
(`tests/integration/test_pydantic_ai_deepseek_live_runtime.py`,
`provider_upgrade + deepseek`) runs only via
`uv run pytest -m "provider_upgrade and deepseek"`, requires explicit opt-in
(`DND_ASSISTANT_DEEPSEEK_LIVE=1` plus `DND_ASSISTANT_DEEPSEEK_CONFIG`,
`DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE`, `DEEPSEEK_API_KEY`), skips before any
config/credential/network access when the selector is absent, fails before
network on missing/invalid/non-canonical configuration, and exercises the real
production path `_load_profile -> _build_agent_model ->
build_pydantic_ai_deepseek_model -> PydanticAIAgentRuntime` with a synthetic
context and one READ-only probe. Hard budget: D1 = 1 and D2 = 2 model HTTP
requests (total 3, zero retries); D2 structurally proves `tool_choice=auto`,
assistant `reasoning_content` replay with a matching tool result, and exactly
one handler execution. The historical RM-02 spike remains separate
(`deepseek` only, not `provider_upgrade`). No production Python changed, no
product-v1 ran, and no accepted canonical live baseline exists.

### RM-05 — Product-v1 DeepSeek candidate qualification

Status: `DONE` — measured DeepSeek candidate product qualification `PASS`.
Candidate consumed; rerun prohibited.

After RM-01…04 acceptance only.

One bounded measured candidate run:

```text
dataset           product-v1
sample plan       single-pass-v1
prompt            agent-v3
provider          deepseek
model             deepseek-flash
reasoning_effort  high
```

Preserve the existing warm-up/measurement/frozen-report discipline unless RM-00
finds a provider-specific measurement requirement that is accepted
prospectively before the run.

A measured run is consumed and must not be casually rerun.

Result: Measurement SHA `d52536973eb7e6806b06dcae72c007116ca4f476`.

The explicit live path `dnd eval run --runtime deepseek`
(`src/dnd_assistant/composition/eval_deepseek.py`) reuses the accepted
provider-neutral runner/report machinery and the shared production
`_build_agent_model` dispatch; it validates the canonical DeepSeek AGENT identity
before credential/network access, runs one discarded `EVAL-P1-001` warm-up, then
exactly one measured `run_dataset(product-v1)` pass. Measured candidate:
`deepseek` / `deepseek-flash` / thinking=true / `reasoning_effort=high` / role
`agent`, profile `agent-deepseek`, Pydantic AI 2.39.0, `response_model`
`deepseek-flash`, `documented_route` `DeepSeek-V4.1-Flash`.

Literal hard results:

```text
complete measured samples          13/13 (13 decision + 13 full-turn)
runtime errors                     0
unauthorized WRITE executions      0 (SYSTEM SAFETY PASS)
false-write quality                0/3 = 0.0 PASS (threshold 0.0)
accepted                           true
reasons                            []
measured model requests            22 (warm-up 1; trace total 23; ceiling 28)
```

Frozen artifact:
`docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json`
(SHA-256 `3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd`,
36804 bytes, 1355 lines), bound by
`tests/contract/test_eval_rm05_deepseek_frozen_candidate.py`. Report-only metric
and sample-score misses (EVAL-P1-002/004/007) remain descriptive and add no
acceptance requirement. The one-time real-secret absence check over the frozen
JSON `PASS`ed and is recorded as measurement evidence; it is not
secret-dependent test logic.

RM-05 did **not** establish an accepted canonical live baseline. Baseline
adoption/closure remains RM-06.

### RM-06 — Accepted-baseline decision + closure

If RM-05 passes:

- freeze evidence;
- record accepted canonical live baseline;
- update `DEVELOPMENT_STATUS.md`;
- update provider/runtime runbook;
- close the ADR/milestone documentation.

If RM-05 fails:

- freeze the failed result;
- do not relax thresholds;
- use the failure evidence to decide whether a distinct candidate
  (`low`, `max`, or another model) deserves a new task.

## 6. Hard acceptance criteria

The milestone is complete only when a live candidate has all of:

```text
complete measured dataset
SYSTEM SAFETY PASS
unauthorized WRITE handler executions = 0
product quality gate PASS
no provider/protocol runtime errors
required tool/structured-output semantics PASS
no secret leakage
no hidden reasoning leakage
frozen report + contract binding
normal repository gates green
independent GitHub verification complete
```

## 7. Non-goals

Not part of this milestone unless separately justified:

- provider failover/routing marketplace;
- automatic cloud/local fallback;
- Qwen/other providers;
- embeddings/vector DB;
- prompt redesign to rescue a candidate after measurement;
- relaxing the product dataset or safety gates;
- storing provider conversation state as campaign memory.

## 8. Closure / outcome (`RM-06`)

**Milestone status:** `DONE / CLOSED`. **`RM-06` status:** `DONE`.

All task history above is preserved unchanged as the durable entry scope and task
contract. This section is additive and records only the closure outcome.

### 8.1 Accepted canonical live baseline

The RM-05 frozen measured candidate was adopted by RM-06 as the canonical
accepted live qualification baseline:

```text
provider             deepseek
model                deepseek-flash
role                 agent
thinking             true
reasoning_effort     high
dataset              product-agent v1
dataset fingerprint  e4a473401ff93dc94c1ccb45ccc0d8cdcddaf6fe34a68c31918cac0216915057
sample plan          single-pass-v1
sample fingerprint   696448e51c9e280203b941f52c34b9076d0611e585ad2074f72bd13bc7c8b2ca
prompt               agent-v3
measurement SHA      d52536973eb7e6806b06dcae72c007116ca4f476
qualification date   2026-09-21
response model       deepseek-flash
documented route     DeepSeek-V4.1-Flash
```

This is specifically the **AGENT** baseline. The project's DeepSeek support is
AGENT-role only; structured-output semantics were not part of this
qualification (see §8.3).

### 8.2 Canonical frozen evidence

```text
artifact          docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json
artifact SHA-256  3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd
bytes / lines     36804 / 1355
contract          tests/contract/test_eval_rm05_deepseek_frozen_candidate.py
```

The frozen JSON itself is the machine-readable canonical evidence. No
`canonical_baseline.json`, registry, symlink or copied artifact was created. The
artifact is immutable; adopting it as canonical did not modify it, its contract,
its thresholds or the product contract.

The candidate is **consumed** and must never be rerun.

### 8.3 Hard acceptance criteria closure

```text
complete measured dataset                       PASS (13/13/13)
SYSTEM SAFETY PASS                              PASS
unauthorized WRITE handler executions = 0        PASS
product quality gate PASS                       PASS (0/3 = 0.0)
no provider/protocol runtime errors             PASS (0)
required AGENT tool / continuation semantics    PASS
structured-output semantics                     NOT APPLICABLE
no secret leakage                               PASS
no hidden reasoning leakage                     PASS
frozen report + contract binding                PASS
normal repository gates green                   PASS (RM-05 Phase A / Phase C)
independent GitHub verification complete        PASS (artifact + contract + Git history)
```

`structured-output semantics` is **`NOT APPLICABLE`**: project DeepSeek support
is AGENT-role only and the AGENT runtime uses `str | DeferredToolRequests`, not
structured extraction. This milestone did **not** qualify DeepSeek
structured-output behavior and must never be read as doing so.

Report-only metric and sample-score misses (EVAL-P1-002/004/007) remain
descriptive and add no acceptance requirement; `oracle_consistency_required` is
`false` for this live candidate.

### 8.4 Baseline adoption does not change runtime defaults

Accepting the qualification baseline did **not**:

```text
change CLI or TUI defaults
commit any machine-local models.toml
hardcode agent-deepseek as a global runtime profile
remove Ollama support
enable cloud fallback
```

Model selection remains machine-local configuration. The baseline means this
provider/model/settings/product-contract combination is the accepted reference
qualification; it is not a default that every machine must use.

### 8.5 Qualification-time route vs future provider routing

`documented_route = DeepSeek-V4.1-Flash` is **qualification-time evidence**. It
is not an immutable guarantee that the remote alias will forever route to the
same server model. A future provider-side routing/protocol change is handled
prospectively by `docs/development/provider-runtime-upgrade.md`, not by
reinterpreting this frozen artifact.

### 8.6 Stage-14 preservation

This closure does not rewrite Stage-14 history. `S14-07` remains `BLOCKED` /
`UNSATISFIED` with disposition `DEFERRED_TO_FUTURE_SCOPE`. The requirement
deferred by ADR-0009 was later fulfilled prospectively by this separate v0.5.0
workstream; S14-07 is **not** retroactively passed or marked `DONE`, and no
Stage-14 frozen artifact or contract test was changed.
