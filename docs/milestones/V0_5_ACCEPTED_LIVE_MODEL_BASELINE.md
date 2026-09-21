# v0.5.0 — Accepted Live Model Baseline

- **Status:** adopted post-MVP milestone
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

Implement the minimum provider-neutral configuration changes needed for
DeepSeek:

- typed provider discrimination;
- reasoning/thinking settings only where supported;
- machine-local credential lookup contract;
- secret-safe errors/metadata;
- no Vault configuration coupling.

RM-01 must be independently implementable and acceptable as the typed
provider/profile/credential contract. Its acceptance must **not** depend on a
future RM-02 result: it defines the contract, not the concrete DeepSeek
construction strategy.

No product live run.

### RM-02 — DeepSeek protocol compatibility spike + A/B architecture decision

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

No product baseline measurement yet.

### RM-03 — Production agent composition integration

Extend shared presentation-neutral production composition so an AGENT profile
can select `ollama` or `deepseek`.

Do not fork the agent runtime.

Typer and Textual must continue to use the same application behavior.

### RM-04 — DeepSeek live smoke / provider gate

Add explicit opt-in live provider tests and update the provider/runtime upgrade
runbook.

Normal `uv run pytest` remains secret/network independent.

Required live configuration must fail rather than silently skip when explicitly
requested and invalid.

### RM-05 — Product-v1 DeepSeek candidate qualification

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
