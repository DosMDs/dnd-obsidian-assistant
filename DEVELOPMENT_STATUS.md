# D&D Session Assistant — Development Status

**Last updated:** 2026-09-15 (S10-06)
**Current milestone:** `v0.3-dev — Fast Assistant`
**Roadmap position:** Stage 9 `DONE`; Stage 10 `IN PROGRESS` (S10-00 architecture/domain contract `DONE`; S10-01 domain schemas `DONE`; S10-02 pure validation/preflight `DONE`; S10-03 review/fingerprint/approval `DONE`; S10-04 applier/revision safety `DONE`; S10-05 CLI workflow + durable proposal store `DONE`; S10-06 failure/partial-application/audit hardening `DONE`)
**Active stage:** Stage 10 — ChangeSet (`IN PROGRESS`)
**Active migration:** PAIM — Pydantic AI Runtime Migration
**Reference main SHA:** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

## Status model

Use only:

- `NOT STARTED`
- `IN PROGRESS`
- `BLOCKED`
- `DONE`

A task is not `DONE` merely because code was generated. Completion requires the implementation/documentation requested, relevant checks, final diff review, commit, push and upstream verification according to repository policy.

## Policy

This file stores **current roadmap state**, not detailed historical reports.

Detailed records belong in:

```text
docs/stages/       stage plan/history/evidence
docs/migrations/   migration plan/history/evidence
docs/adr/          architecture decisions
```

## Stage overview

| Stage | Status | Details |
|---|---|---|
| 0. Environment | DONE | — |
| 1. Project skeleton + contracts | DONE | `docs/stages/01_PROJECT_SKELETON_AND_CONTRACTS.md` |
| 2. Domain schemas | DONE | `docs/stages/02_DOMAIN_SCHEMAS.md` |
| 3. Vault Repository | DONE | `docs/stages/03_VAULT_REPOSITORY.md` |
| 4. Calendar | DONE | `docs/stages/04_CALENDAR.md` |
| 5. Retrieval + Entity Resolution | DONE | `docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md` |
| 6. Session Runtime without LLM | DONE | `docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md` |
| 7. Tool Registry / Executor | DONE | `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` |
| 8. Model Gateway / Ollama | DONE | `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md` |
| 9. Fast Agent | DONE | `docs/stages/09_FAST_AGENT.md` |
| 10. ChangeSet | IN PROGRESS | `docs/stages/10_CHANGESET.md` |
| 11. Post-session Processor | NOT STARTED | — |
| 12. Campaign State | NOT STARTED | — |
| 13. Bootstrap | NOT STARTED | — |
| 14. Evals / Hardening | NOT STARTED | — |

## Current Stage-9 tasks

| Task | Status |
|---|---|
| S9-00 — Deterministic Fast-Agent tool exposure policy + Stage-9 kickoff | DONE |
| S9-01 — Compact Context Builder over accepted data sources | DONE |
| S9-02 — One-step FastAgent model decision boundary | DONE |
| S9-03 — Validated ToolExecutor execution + tool-result adaptation | DONE |
| S9-04 — Bounded model→tool→model loop + clarification/final semantics | DONE |
| S9-05 — Agent safety/failure hardening + multi-tool semantics | DONE |
| S9-06 — CLI `dnd ask` + mocked/parser-backed end-to-end integration | DONE |
| S9-07 — Full Stage-9 historical review / completion | DONE |

`S9-07` completed the full Stage-9 historical/architectural review after the PAIM
final architecture decision (`ACCEPTED`) and reference-runtime retirement
(`PAIM-RETIRE-01`, `DONE`). Stage 9 is now `DONE`.

## Current Stage-10 tasks

| Task | Status |
|---|---|
| S10-00 — Architecture/domain contract and kickoff | DONE |
| S10-01 — ChangeSet + operation domain schemas | DONE |
| S10-02 — Pure validator / whole-batch preflight | DONE |
| S10-03 — Review DTO + approval/rejection + fingerprint binding | DONE |
| S10-04 — ChangeSetApplier + revision/conflict safety | DONE |
| S10-05 — CLI review/apply workflow + proposal persistence decision | DONE |
| S10-06 — Failure / partial-application / audit hardening | DONE |
| S10-07 — Full Stage-10 historical review / completion | NOT STARTED |

`S10-00` completed the trusted ChangeSet architecture/domain contract. Verdict:

```text
S10_ARCHITECTURE_READY
```

Architecture baseline SHA:

```text
7c331f29cd418e4c4cda6a487fbbf5f1983d20eb
```

Detailed record: `docs/stages/10_CHANGESET.md`; decision:
`docs/adr/0006-changeset-review-apply-boundary.md`. `S10-01` implemented the
immutable domain proposal schemas (`domain/changeset.py`); `S10-02` implemented
the pure repository-backed validator / whole-batch preflight
(`application/changeset_validation.py`); `S10-03` implemented the application
review DTOs, canonical serialization, SHA-256 fingerprint and immutable
approval/rejection content binding (`application/changeset_review.py`); `S10-04`
implemented the repository-backed applier with fresh preflight, explicit
update-field mapping, stop-on-first-write-failure and structured APPLIED/PARTIAL/
FAILED results (`application/changeset_apply.py`). `S10-05` implemented the durable
proposal/approval artifact store (`storage/changeset_store.py`,
`application/changeset_store.py`) and the `dnd changeset`
save/review/approve/reject/apply CLI workflow (`cli/changeset.py`). `S10-06`
implemented the append-only apply-attempt artifact, deterministic audit
correlation, truthful commit-state classification, the fail-closed pre-apply
gate and the read-only `dnd changeset status` command
(`application/changeset_status.py`). `S10-07` remains `NOT STARTED`.

## Accepted custom reference baseline

Reference `main` commit after S9-06 correction/reconciliation:

```text
f424a0f659afd5f8bcbce55c4d280cc8e621133f
```

This commit is the behavioral/rollback reference for PAIM. The migration branch does not need to keep a long-lived duplicate production runtime solely for rollback; Git/main provides that reference.

## PAIM — Pydantic AI Runtime Migration

Detailed plan: `docs/migrations/001_PYDANTIC_AI_RUNTIME.md`

Architecture decision: `docs/adr/0003-pydantic-ai-runtime-migration.md`

Active migration branch:

```text
feat/pydantic-ai-runtime
```

PAIM-00 branch kickoff commit:

```text
ac9fd4c7e19475adb2331eb010ce8c78af98b309
```

| Task | Status |
|---|---|
| PAIM-00 — Branch + ADR + project/GigaCode migration context | DONE |
| PAIM-C00 — Reconcile kickoff evidence/status/GigaCode safeguards | DONE |
| PAIM-01 — Candidate dependency/framework qualification | DONE |
| PAIM-C01 — Correct PAIM-01 framework-semantics evidence | DONE |
| PAIM-C02 — Close unknown-tool retry-count evidence gap | DONE |
| PAIM-02 — Critical blocker gate | DONE |
| PAIM-C03 — Correct PAIM-02 public extension path | DONE |
| PAIM-C04 — Complete PAIM-C03 executable evidence | DONE |
| PAIM-03 — Migration-specific test harness hardening | DONE |
| PAIM-C05 — Restore PAIM history and close PAIM-03 evidence | DONE |
| PAIM-C06 — Close Q8 HTTP client lifecycle evidence | DONE |
| PAIM-04 — ToolRegistry → framework Toolset → ToolExecutor bridge | DONE |
| PAIM-C07 — Harden PAIM-04 bridge authority | DONE |
| PAIM-C08 — Prevent same-registry snapshot-copy authority expansion | DONE |
| PAIM-05 — Explicit DndAgentPolicy | DONE |
| PAIM-C09 — Seal DndAgentPolicy batch input boundary | DONE |
| PAIM-06 — Context/dependencies integration | DONE |
| PAIM-C10 — Seal Pydantic AI run dependency binding | DONE |
| PAIM-C11 — Restore PAIM-06 history and seal prepared-run boundary | DONE |
| PAIM-C12 — Restore exact PAIM historical text | DONE |
| PAIM-07 — Replace one-step FastAgent mechanics | DONE |
| PAIM-C13 — Close PAIM-07 runtime evidence gaps | DONE |
| PAIM-C14 — Make PAIM-07 evidence literal and exact | DONE |
| PAIM-08 — Replace bounded AgentLoop mechanics | DONE |
| PAIM-C15 — PAIM-08 structural preflight and parity evidence | DONE |
| PAIM-C16 — Close literal PAIM-08 evidence and restore migration history | DONE |
| PAIM-C17 — Complete literal PAIM-08 runtime evidence | DONE |
| PAIM-C18 — Close final PAIM-08 evidence defects | DONE |
| PAIM-09 — Ollama integration decision gate | DONE |
| PAIM-C19 — Close PAIM-09 factory/runtime evidence defects | DONE |
| PAIM-C20 — Seal PAIM-09 transport and continuation evidence | DONE |
| PAIM-10 — Sync/thread-safety gate | DONE |
| PAIM-C21 — Seal PAIM-10 literal thread evidence | DONE |
| PAIM-11 — Full Stage-9 behavioral parity | DONE |
| PAIM-C22 — Seal PAIM-11 behavioral parity evidence | DONE |
| PAIM-C23 — Finalize exact Stage-9 parity contracts | DONE |
| PAIM-C24 — Close final PAIM-11 evidence bookkeeping | DONE |
| PAIM-C25 — Correct final PAIM-11 audit metadata | DONE |
| PAIM-12 — Real Ollama smoke/performance | DONE |
| PAIM-C26 — Seal PAIM-12 live runtime evidence | DONE |
| PAIM-13 — Eval comparison against reference | DONE |
| PAIM-C27 — Correct PAIM-13 reference/eval harness | DONE |
| PAIM-C28 — Make PAIM-13 harness live-ready | DONE |
| PAIM-C29 — Freeze and validate PAIM-13 measured harness | DONE |
| PAIM-C30 — Finalize PAIM-13 measurement harness | DONE |
| PAIM-C31 — Seal PAIM-13 measured gate enforcement | DONE |
| PAIM-C32 — Seal PAIM-13 warm-up preflight | DONE |
| PAIM-C33 — Seal PAIM-13 live environment preflight | DONE |
| PAIM-C34 — Restore migration history append-only integrity | DONE |
| PAIM-C35 — Restore green formatting baseline | DONE |
| PAIM-C36 — Reconcile Ruff with append-only migration history | DONE |
| PAIM-C37 — Seal offline construction preflight for PAIM-13 live eval | DONE |
| PAIM-C38 — Establish explicit Ollama request-timeout parity | DONE |
| PAIM-C39 — Correct unauthorized WRITE accounting and blocker evidence | DONE |
| PAIM-C40 — Correct PAIM-C39 evidence bookkeeping | DONE |
| PAIM-C41 — Restore green baseline and correct C40 evidence | DONE |
| PAIM-C42 — Seal PAIM-13 pre-live evidence boundaries | DONE |
| PAIM-C43 — Restore CountingModelGateway Protocol compatibility | DONE |
| PAIM-14 — Remove superseded generic custom runtime code | DONE |
| PAIM-15 — Final architecture review: ACCEPTED/PARTIAL/REJECTED | DONE |
| PAIM-RETIRE-01 — Retire executable reference agent runtime + reference-only tests | DONE |

## PAIM outcome policy

Allowed outcomes:

```text
ACCEPTED
  Pydantic AI becomes primary generic agent runtime.

PARTIAL
  Pydantic AI is retained for compatible generic mechanics;
  documented incompatible components remain custom.

REJECTED
  runtime migration branch is not merged;
  findings/ADR are preserved in main;
  custom runtime remains canonical.
```

`PARTIAL` is a valid successful outcome. Architecture is not weakened merely to achieve `ACCEPTED`.

## Repository-wide Pyright gate (PYR-01)

PYR-01 established reproducible repository-wide type checking and finalized it as
a mandatory development gate.

Canonical configuration: `pyrightconfig.json` (Python 3.12, `include` = `src`,
`tests`). Canonical gate: `uv run pyright` — must complete with 0 errors.

| Task | Status |
|---|---|
| PYR-01A — Remove production Pyright diagnostics | DONE |
| PYR-01B — Remove tool/test Pyright diagnostics | DONE |
| PYR-01C — Align repository/service test doubles with protocols | DONE |
| PYR-01D — Remove PAIM/reference/support Pyright diagnostics | DONE |
| PYR-01E — Final repository-wide Pyright gate and documentation | DONE |

Repository-wide Pyright: 0 errors / 0 warnings (`src`: 0/0, `tests`: 0/0).

## Active next task

```text
PAIM-C39 — DONE
PAIM-C40 — historical correction record retained
PAIM-C41 — DONE
PAIM-C42 — DONE
PAIM-C43 — DONE
PAIM-13 — DONE
PAIM-13 attempt #1 — INCOMPLETE (fixture construction failure, corrected by PAIM-C37)
PAIM-13 attempt #2 — INCOMPLETE (tool chat timeout, corrected by PAIM-C38)
PAIM-13 attempt #3 — COMPLETE MEASUREMENT / VERDICT INVALIDATED
PAIM-13 measured attempt #4 — VALID / passes comparison gates (see Layer-A correction below)
PAIM-14 — DONE
PAIM-15 — DONE (verdict: ACCEPTED)
PAIM-RETIRE-01 — DONE
```

Active next:

```text
Stage 10 — ChangeSet (IN PROGRESS; next S10-07 — Full Stage-10 historical review / completion)
```

## PAIM-15 final architecture review — verdict `ACCEPTED`

Completed 2026-09-14 on `feat/pydantic-ai-runtime`.

### Migration verdict

```text
ACCEPTED
```

The verdict means:

- production `dnd ask` uses the Pydantic AI runtime;
- `ToolExecutor`, `DndAgentPolicy`, authorization, exposure policy and Vault
  boundaries remain project-owned;
- no superseded custom agent runtime is instantiated by production;
- the executable reference runtime is temporarily retained **only** as explicit
  test/evidence infrastructure pending `PAIM-RETIRE-01`.

### Current production architecture

```text
CLI (cli/ask.py)
→ PydanticAIAgentRuntime (application/pydantic_ai_agent_runtime.py)
→ DndAgentRunPreparer / DndAgentPolicy (application/pydantic_ai_run_deps.py,
  application/dnd_agent_policy.py)
→ PydanticAIToolBridge (application/pydantic_ai_tool_bridge.py)
→ ToolExecutor (tools/executor.py)
→ services
→ VaultRepository
```

### Neutral shared contracts (PAIM-15 extraction)

PAIM-15 moved the production-shared provider-neutral DTOs/helpers out of the
reference-runtime modules into:

```text
src/dnd_assistant/application/agent_contracts.py
```

The production Pydantic runtime (`pydantic_ai_agent_runtime.py`,
`pydantic_ai_fast_agent.py`) now imports shared contracts **only** from
`agent_contracts`, never from `application.fast_agent`,
`application.agent_loop` or `application.agent_tool_execution`. A new
`tests/contract/test_boundaries.py` AST scan enforces this for normal and
deferred/call-time imports.

### Reference runtime classification

```text
application/fast_agent.py::FastAgent                          TEST/REFERENCE ONLY
application/agent_loop.py::AgentLoop                          TEST/REFERENCE ONLY
application/agent_tool_execution.py::AgentToolExecutionService TEST/REFERENCE ONLY
```

`ModelGateway` and native `OllamaModelProvider` are retained as
provider-neutral/non-agent model infrastructure (embeddings, structured
generation, health). They are **not** part of the current `dnd ask` production
orchestration path.

### PAIM-13 Layer-A evidence correction

The production architecture verdict does not depend on live model behavior. The
following applies to the historical PAIM-13 measured attempt #4 evidence:

- **Layer B (full-turn) remains valid** runtime/full-turn parity evidence.
- **Layer-A metrics that depend on `ToolCall` observation from attempt #4 are
  not valid evidence**: the Layer-A observers read the wrong `ToolCall` field
  (`tc.tool_name` instead of the canonical `tc.name`), so emitted tool calls
  were swallowed as observation errors (corrected by PAIM-EVAL-CORR-01).
- Do **not** claim that all historical `BOTH_FAIL` scenarios were caused by
  this defect.
- Do **not** reinterpret the invalid Layer-A tool metrics as actual model
  failures or passes.
- Historical append-only evidence is unchanged; the migration document carries
  the appended reinterpretation record.

No live Ollama rerun was performed in PAIM-15.


### PAIM-14 production cutover and reference classification

The production `dnd ask` CLI composition was cut over to the project-owned
Pydantic AI runtime boundary:

```text
cli/ask.py → AskRuntime.agent_runtime
cli/agent_runtime.py
  → build_pydantic_ai_ollama_model(profile)
  → PydanticAIToolBridge(registry=tool_registry)
  → DndAgentRunPreparer(context_builder, tool_catalog, bridge)
  → PydanticAIAgentRuntime(run_preparer, model)
```

`ToolExecutor`, `DndAgentPolicy`, tool exposure policy and READ/WRITE
authorization remain project-owned and unchanged.

Post-cutover reference re-inspection found **no** superseded generic runtime
component with zero remaining consumers. The custom `FastAgent`, `AgentLoop`,
`ModelGateway` and native `OllamaModelProvider` are retained as explicit
`KEEP_FOR_TEST_REFERENCE` infrastructure because PAIM-11 parity and the
PAIM-13 live-eval reference side still require them. Cleanup of that
reference surface is deferred to the PAIM-15 final architecture review.

A contract boundary guard now prevents production CLI composition from
re-importing the retained reference runtime (`tests/contract/test_boundaries.py`).

Full literal evidence: `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` section 75.

### PAIM-C43 typed-contract correction

PAIM-C43 supersedes the typed-contract gap missed by PAIM-C42. The
reference-side test wrapper `CountingModelGateway` declared
`chat() -> ToolAwareResponse`, `generate_structured(...) -> Any` and
`health() -> Any`, which are not structurally compatible with the canonical
`ModelGateway` Protocol (`chat() -> ChatResponse`,
`generate_structured(schema: type[T]) -> T`, `health() -> ModelHealth`).
Pyright rejected the wrapper wherever a `ModelGateway` was required, even
though the PAIM-C42 runtime counter tests passed.

PAIM-C43 corrects only the test-harness decorator typing (the production
Protocol is unchanged). Targeted Pyright evidence: 7 relevant compatibility
errors before, 0 after, 0 new relevant errors. See
`docs/migrations/001_PYDANTIC_AI_RUNTIME.md` section 73 for literal evidence.
PAIM-C42's historical evidence is unchanged.

### PAIM-13 attempt #3 result

The single measured invocation completed with 28 passed, 1 failed.

The failing test was `TestPaim13FullTurnAggregate::test_report_full_turn_aggregate`:

```text
Candidate has 3 unauthorized WRITE handler executions.
This is a critical PAIM-13 failure.
```

**PAIM-C39 correction:** The aggregate WRITE blocker verdict has been
invalidated. The old aggregate counted every successful observation with
any WRITE handler as unauthorized, without inspecting scenario expectations.
E13-R08 explicitly expects `write_quest_status(name="Moon Gate", status="completed")`
and ran 3 repetitions — all 3 candidate observations passed exact full-turn
scoring. After correction, the deterministic regression tests prove that
3 correct R08-style observations produce 0 unauthorized WRITE handler
executions.

The measurement itself remains valid historical evidence. The blocker
interpretation was invalid.

### PAIM-13 attempt #4 result

The single canonical measured invocation completed successfully:

```text
29 passed, 1 warning in 379.76s
```

All emitted reference/candidate metric deltas were `+0.0000`:

```text
Layer A: SCENARIO_SUCCESS 0.2778 vs 0.2778; CLARIFICATION 1.0000 vs 1.0000
Layer B: SCENARIO_MAJORITY_SUCCESS 8/9 vs 8/9; TOTAL_MODEL_REQUESTS 42 vs 42;
         UNAUTHORIZED_WRITE_HANDLER_COUNT 0 vs 0
```

`E13-R08` passed 3/3 for both runtimes under the corrected C39
expectation-aware WRITE accounting. No scenario expectation, scoring
formula, metric threshold, WRITE rule or measurement geometry was changed.

The measurement fired no PAIM-C31 hard blockers, but its interpretation is
bounded: **Layer B (full-turn) is valid runtime/full-turn evidence**, while the
**Layer-A metrics that depend on `ToolCall` observation are not valid evidence**
(the observers read the wrong `ToolCall` field; corrected by PAIM-EVAL-CORR-01).
Do not reinterpret the invalid Layer-A tool metrics as actual model failures or
passes, and do not attribute every historical `BOTH_FAIL` scenario to the
observer defect. See the PAIM-15 Layer-A correction record above and the
appended reinterpretation in section 76 of the migration document.

Outcome:

```text
VALID comparison-gate result for Layer B;
Layer-A ToolCall-observation metrics superseded by PAIM-EVAL-CORR-01
```

Full literal evidence: `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` section 74.

## PAIM-RETIRE-01 — reference-runtime retirement DONE

Completed 2026-09-14 on `feat/pydantic-ai-runtime`.

The executable custom/reference agent runtime retained through PAIM-15 was
retired:

```text
application/fast_agent.py::FastAgent                           REMOVED
application/agent_loop.py::AgentLoop                           REMOVED
application/agent_tool_execution.py::AgentToolExecutionService REMOVED
```

Retained:

```text
agent_contracts.py             neutral shared contracts
DndAgentPolicy                 batch-admission policy
PydanticAIAgentRuntime / PydanticAIFastAgent
PydanticAIToolBridge → ToolExecutor → services → VaultRepository
ModelGateway + native Ollama    non-agent provider infrastructure
general eval infrastructure    reusable for Stage 14
```

Reference-only/parity tests and migration-comparison harnesses were removed;
direct shared-contract coverage migrated to `tests/unit/test_agent_contracts.py`.
Stage-9 safety coverage remains on the accepted Pydantic AI runtime.
`tests/contract/test_boundaries.py` protects the accepted dependency shape
(CLI/Pydantic runtime must not regain obsolete/custom orchestration or native
provider dependencies).

Literal evidence: `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` section 77.

Full-suite result after retirement: 4932 passed, 114 skipped.

Next task after retirement was `S9-07` (now `DONE`; see Stage-9 completion record).
Stage 10 (`NOT STARTED`) is the next roadmap stage.

## S9-07 — Stage-9 completion DONE

Completed 2026-09-14 on `feat/pydantic-ai-runtime`.

S9-07 performed the full historical/architectural review of Stage 9 after the
accepted Pydantic AI migration and reference-runtime retirement. Verdict:

```text
STAGE9_READY_FOR_COMPLETION
```

All Stage-9 responsibilities map to current owners on the accepted Pydantic AI
runtime; every critical runtime safety invariant has literal surviving
executable coverage; no production framework callback bypasses `ToolExecutor`;
`dnd ask` composes the accepted runtime; the retired reference runtime has no
executable consumer. No blocking Stage-9 defect was found.

Detailed record: `docs/stages/09_FAST_AGENT.md` (S9-07 section).

## Current blockers

```text
No confirmed PAIM-13 runtime regression blocker.
Attempt #3 aggregate WRITE blocker was invalidated by PAIM-C39.
Attempt #4 Layer B measured VALID; Layer-A ToolCall-observation metrics invalid.
PAIM-14 production cutover complete; no removable superseded runtime remained.
PAIM-15 migration verdict ACCEPTED; shared contracts extracted to agent_contracts.
PAIM-RETIRE-01 complete; executable reference agent runtime retired.
S9-07 review complete; no blocking Stage-9 defect; Stage 9 DONE.
S10-00 architecture/domain contract complete; verdict S10_ARCHITECTURE_READY.
S10-01 immutable ChangeSet/operation domain schemas complete in domain/changeset.py.
S10-02 pure validator/whole-batch preflight complete in application/changeset_validation.py.
S10-03 review/fingerprint/approval complete in application/changeset_review.py.
S10-04 applier/revision safety complete in application/changeset_apply.py.
S10-05 proposal/approval artifact store + `dnd changeset` CLI workflow complete.
S10-06 apply-attempt evidence + audit correlation + status hardening complete.
Known limitation R1: an intent-only ChangeSet audit record with a real session_ref
can still participate in global session-recovery blocking; no repair action added.
No confirmed Stage-10 blocker; no model-generated ChangeSet producer exists yet.
```

Active next:

```text
Stage 10 — ChangeSet (IN PROGRESS; next S10-07 — Full Stage-10 historical review / completion)
```

PAIM-02 blocker gate result: **PASS** (corrected by PAIM-C03)

PAIM-C03 re-proved the blocker gate using the intended public extension
points:

```text
ExternalToolset
+
HandleDeferredToolCalls
+
DeferredToolRequests.calls
+
DeferredToolResults (via requests.build_results(calls=...))
+
existing ToolExecutor
```

The tested architecture path:
```text
frozen app snapshot
-> ExternalToolset (no Python handler)
-> HandleDeferredToolCalls handler receives COMPLETE batch
-> application full-batch admission
-> ToolExecutor sequentially
-> DeferredToolResults (via build_results)
-> agent continues IN THE SAME RUN
-> terminal model response
```

Key differences from PAIM-02 evidence:
- No `@agent.tool_plain(requires_approval=True)` decorators
- No `DeferredToolRequests` as output type
- `DeferredToolRequests.approvals` is empty (all calls in `.calls`)
- Model->tools->model cycle stays inside ONE `agent.run_sync()`
- `UsageLimits(request_limit=N)` bounds total model requests
- Framework catches unknown/hidden/duplicate-ID tools before deferred handler

All 16 hard-gate scenarios pass. No selective custom requirement is needed
for the ExternalToolset path — application-owned batch admission and
sequential ToolExecutor execution are part of the intended architecture.

Known risks documented in PAIM-02 evidence (unchanged):
- default concurrent multi-tool execution (overridden by application
  sequential execution via ToolExecutor);
- default tool semantic retries (disabled via retries={"tools": 0});
- sync-tool worker-thread execution (PAIM-10 gate).

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state |
| `docs/stages/09_FAST_AGENT.md` | Detailed Stage-9 history/reference behavior |
| `docs/stages/10_CHANGESET.md` | Stage-10 architecture record and task map |
| `docs/adr/0006-changeset-review-apply-boundary.md` | ChangeSet review/apply architecture decision |
| `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` | PAIM task plan/history/evidence |
| `docs/adr/0003-pydantic-ai-runtime-migration.md` | Migration architecture/rollback decision |
| `AGENTS.md` | Always-on OpenCode development invariants |
| `.opencode/skills/pydantic-ai-migration/SKILL.md` | PAIM implementation/review workflow |
| `docs/migrations/002_OPENCODE_DEVELOPMENT_TOOLING.md` | OpenCode development-tooling cutover record |
