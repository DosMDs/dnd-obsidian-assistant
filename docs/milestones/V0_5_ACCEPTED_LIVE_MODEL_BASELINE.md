# v0.5.0 — Accepted Live Model Baseline

**Status:** proposed post-MVP milestone  
**Created:** 2026-09-21  
**Predecessor:** current MVP `RELEASE_READY` under ADR-0009

## 1. Goal

Establish at least one accepted canonical live agent model/provider baseline
without weakening the accepted product-eval or safety contract.

Initial provider direction: DeepSeek remote API.

This milestone owns the deferred requirement created by ADR-0009. It is not
Stage 15 and does not alter Stage-14 historical outcomes.

## 2. Entry state

```text
main                                6136512ae1ee52fb3bc9cd57adcf80061bf140f9
Stage 14                            DONE / integrated
current MVP                          RELEASE_READY
historical S14-07                    BLOCKED / UNSATISFIED
accepted canonical live baseline     none
```

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

The exact served model version must be captured at qualification time if the
provider exposes it; otherwise record the documented routing/version and
qualification date.

## 5. Task decomposition

### RM-00 — Remote-provider architecture + DeepSeek qualification plan

`PLAN_REQUIRED`.

Read-only investigation. Prove owning layers, exact compatibility blocker,
intended changed files, acceptance→evidence map and rollback path.

### RM-01 — Provider/profile/credential contract

Implement the minimum provider-neutral configuration changes needed for
DeepSeek:

- typed provider discrimination;
- reasoning/thinking settings only where supported;
- machine-local credential lookup contract;
- secret-safe errors/metadata;
- no Vault configuration coupling.

No product live run.

### RM-02 — DeepSeek protocol compatibility spike

Executable qualification of the pinned Pydantic AI path.

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

If the generic Pydantic AI/OpenAI-compatible path fails, decide between a narrow
public adapter and rejection.

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
