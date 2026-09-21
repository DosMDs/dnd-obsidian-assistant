# D&D Session Assistant — Development Status

**Last updated:** 2026-09-21 (RM-06 DONE; TUI-UX-01 DONE)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Post-MVP workstream:** `v0.5.0 — Accepted Live Model Baseline` (`DONE / CLOSED`; `RM-00` architecture/docs `DONE`; `RM-01` provider/profile/credential contract `DONE`; `RM-02` protocol compatibility spike `DONE` — Option B, live protocol compatibility `PASS`; `RM-03` production AGENT composition `DONE`; `RM-04` durable DeepSeek provider/runtime live gate `DONE` — `PASS`; `RM-05` product-v1 DeepSeek candidate qualification `DONE` — measured candidate `PASS` (`accepted=true`, 13/13, 0 runtime errors, 0 unauthorized WRITE, quality 0/3 PASS), candidate consumed; `RM-06` accepted-baseline decision/closure `DONE` — accepted canonical live baseline: `deepseek` / `deepseek-flash` / role `agent` / thinking=true / `reasoning_effort=high`, frozen RM-05 artifact)
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `DONE` (integrated); Stage 13 `DONE` (integrated); Stage 14 `DONE` (integrated into `main`; accepted live-model baseline deferred — ADR-0009)
**Active work:** Stage 14 `DONE` and integrated into `main`; current MVP release `RELEASE_READY`; `S14-07 — Opt-in Live Ollama Model Baseline + Latency Metrics + Frozen Report` `BLOCKED` / UNSATISFIED (disposition `DEFERRED_TO_FUTURE_SCOPE`); `S14-07-DIAG-03` `DONE`; `S14-07-QUAL-03` measured / not accepted; `S14-08 — TUI / Cross-Platform Hardening Evidence` `DONE`; `S14-09 — Final Stage-14 Review / Release-Readiness Closure` `DONE`; `S14-10-RELEASE-SCOPE-DECISION` `DONE` (ADR-0009)
**Current branch:** `main`

## Status model

Use only: `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `DONE`.

A task is not `DONE` merely because code was generated. Completion requires the
requested implementation/documentation, relevant checks, final diff review and,
when required, commit/push/upstream verification.

This file stores **current roadmap state**, not a detailed history. Detailed
records live in `docs/stages/`, `docs/migrations/`, `docs/adr/` and Git. Required
quality gates are selected from the actual final diff per
`docs/development/quality-and-evidence.md`; durable architecture/scope rules live
in `docs/development/project-invariants.md`.

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
| 10. ChangeSet | DONE | `docs/stages/10_CHANGESET.md` |
| 11. Post-session Processor | DONE | `docs/stages/11_POST_SESSION_PROCESSOR.md` |
| 12. Campaign State | DONE | `docs/stages/12_CAMPAIGN_STATE.md` |
| Textual TUI Architecture Track (non-numbered) | DONE | Integrated into `main`; `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` |
| 13. Bootstrap | DONE | S13-01 … S13-05 `DONE`; integrated into `main`; `docs/stages/13_BOOTSTRAP.md` |
| 14. Evals / Hardening | DONE | S14-01 … S14-06 `DONE`; S14-07 `BLOCKED` / UNSATISFIED (no accepted canonical live baseline; disposition `DEFERRED_TO_FUTURE_SCOPE`); S14-08 `DONE`; S14-09 `DONE`; S14-10 `DONE`; integrated into `main`; release `RELEASE_READY`; `docs/stages/14_EVALS_AND_HARDENING.md`; `docs/adr/0009-release-scope-defers-live-model-qualification.md` |

## Current work — Stage 14 `DONE` (integrated into `main`); current MVP release `RELEASE_READY`

Stage 13 is `DONE` and integrated into `main`; its detailed evidence lives in
`docs/stages/13_BOOTSTRAP.md`.  Stage 14 — Evals / Hardening is `DONE` and
integrated into `main` under the prospective current-MVP release scope recorded
in ADR-0009.  `S14-00` (accepted
planning / architecture / evidence investigation) and the accepted Stage-14
architecture contract, gap matrix and task decomposition are recorded in
`docs/stages/14_EVALS_AND_HARDENING.md`.

`S14-01` created that durable record and reconciled this status surface; the
golden fixture is qualified and unchanged.

`S14-02 — Deterministic Eval Contract & Scoring Foundation` is `DONE`: the
provider-neutral deterministic eval contract and scoring foundation now live in
`src/dnd_assistant/evals/` (contracts, scoring, metrics, WRITE execution
accounting), with one deterministic scoring implementation, stable metric
identities, explicit `is_write` metadata (no tool-name-prefix inference),
true multisets for unordered calls, and explicit missing/error/zero-denominator
semantics.  The historical `tests/support/pydantic_ai_eval.py` was removed and
its four literal consumers migrated.  No CLI, composition wiring, dataset,
live-model run, report writer or dependency was added.

`S14-03 — Offline Scripted-Model Full-Sequence Regression` is `DONE`: one
deterministic offline cross-stage integration regression
(`tests/integration/test_bootstrap_full_sequence_fs.py`) proves the accepted
Stage-13 bootstrap workflow end-to-end through the real production boundaries
(`dnd init` -> `dnd time init` -> first fresh `BootstrapRuntime.run(persist=True)`
finalize -> `PENDING_CHANGESET` -> review -> explicit content-bound approval ->
real Stage-10/`VaultRepository` apply -> fresh second finalize ->
`NO_CHANGES`/`COMPLETE` -> Campaign State `CURRENT` + verified FTS).  A
golden-derived temporary pre-init Vault preserves historical raw session
material while excluding assistant-owned initialization/derived/workflow state.
Only the model/extraction operator is replaced by a local scripting double; no
production behavior, dependency, CLI, dataset or live-model surface changed.
The tracked golden fixture is read-only and its bytes are proven unchanged.

`S14-04 — Untrusted-Input / Path-Safety Gap Closure` is `DONE`: one new
deterministic offline cross-layer integration regression
(`tests/integration/test_agent_untrusted_input_safety.py`) drives model-generated
path-shaped arguments through the real production path
(`compose_ask_runtime` → 12-tool registry → `DndAgentPolicy` →
`PydanticAIToolBridge` → `ToolExecutor` → real registered handler → real
repository/storage).  It proves path-shaped `session_id` is rejected by the real
`storage/session_paths.py` validator for both `get_session` and
`list_session_events`; path-shaped `EntityId` remains logical data with no
filesystem authority; a model-generated `patch_entity` WRITE call invokes the
real handler but authorizes zero canonical mutation; and path-shaped note/fact
content is persisted verbatim as content.  A test-local outside-Vault sentinel
proves containment/non-interference (bytes and inventory unchanged, secret marker
never returned), which is explicitly not a syscall-level non-read proof.  The
conclusion is `NO PRODUCTION DEFECT`; no production, dependency or CLI surface
changed.

`S14-05 — Provider/Runtime Upgrade Regression Gate` is `DONE`: it adds the
future-upgrade operational runbook
(`docs/development/provider-runtime-upgrade.md`), the `provider_upgrade` pytest
marker, a curated offline selection
(`uv run pytest -m "provider_upgrade and not ollama"`) and an opt-in live
selection (`uv run pytest -m "provider_upgrade and ollama"`), plus a static
selection-integrity contract (`tests/contract/test_provider_upgrade_gate.py`).
It performs **no** version bump: the `pydantic-ai-slim[openai]==2.39.0` pin,
`uv.lock`, `src/` and runtime configuration are unchanged.

`S14-06 — Scriptable Eval Runner + Product Dataset (Offline Mode) + Reporting` is
`DONE`: it adds the product-owned offline eval execution surface — a versioned
Russian product dataset (`product-agent` v1, 13 `EVAL-P1-*` cases, sample plan
`single-pass-v1`), deterministic dataset/sample-plan fingerprints, expected-sample
completeness, a versioned JSON report (`report_schema_version = 1`) with strict
round-trip serialization and baseline comparison, a synthetic in-memory fixture
over the **real** production runtime and the four real tool registration
functions, an offline `scripted-oracle` model recorder (`RecordingPydanticModel`),
observation collection for both layers from one run, and the `dnd eval run|report`
CLI.  System safety is a hard zero-unauthorized-WRITE-execution invariant; the
product-quality gate `false_write_tool_call_rate <= 0.0` uses the existing S14-02
denominator (3 for product-v1).  No live Ollama run, no frozen live baseline, no
latency acceptance and **no dependency change** (`pyproject.toml`/`uv.lock`
unchanged).

`S14-07-QUAL-02 — Distinct Live Candidate Qualification` is `BLOCKED`.  A
distinct second candidate (`ministral-3:8b`, explicit machine-local profile
`agent-ministral3-8b`) was measured exactly once against the unchanged
product-v1 / single-pass-v1 / agent-v3 contracts at HEAD
`9f25913bbe8d49cd82da7c169c3f3798ab668640`.  The run produced 13/13 complete
samples with SYSTEM SAFETY PASS and `false_write_tool_call_rate` 0/3/0.0 PASS,
but **4 runtime errors** (`EVAL-P1-002`, `EVAL-P1-004`, `EVAL-P1-006`,
`EVAL-P1-010`), so the candidate was **not accepted**.  Schema-v3
`failure_diagnostic` evidence classifies every failure as `project_policy`
(`ModelError`, request index 0, cause chain `["ValidationError"]`): the model
emitted zero tool calls and free-text/JSON that failed `AgentTextOutcome`
validation.  The result is frozen at
`docs/evidence/evals/s14-07-product-v1-ollama-ministral3-8b-candidate.json`
(SHA-256 `f44fc02fd86f38f36bec9a99bc238514e2f3ec60647f62456bd9ec27a5ab631e`) and
bound by `tests/contract/test_eval_ministral_frozen_candidate.py`.  No rerun,
no model/profile switch, no prompt/dataset/runtime/policy change; `S14-07`
remains `BLOCKED`.

`S14-07 — Opt-in Live Ollama Model Baseline + Latency Metrics + Frozen Report` is
`BLOCKED`.  The implementation is complete and fully qualified offline
(implementation commit `10356b0be8e2a5ddd4a858ce49144243ee006e9a`): an explicit
`dnd eval run --runtime ollama` path (required `--config`/`--profile`, rejected
for `scripted`), production-factory model construction before any HTTP request,
`OllamaModelProvider.health()` + `/api/version` preflight, one discarded
`EVAL-P1-001` warm-up, one measured product-v1 execution through the existing
recorder/collector, report schema v2 with structured decision/full-turn
`p50/p95` latency (existing nearest-rank helper) and report-only latency deltas.
The ONE measured live run (`agent-qwen35-9b` / `qwen3.5:9b`, Ollama 0.34.2,
Pydantic AI 2.39.0) produced 13/13 complete samples with SYSTEM SAFETY PASS and
`false_write_tool_call_rate` 0/3/0.0 PASS, but **2 runtime errors**
(`EVAL-P1-007`, `EVAL-P1-009`), so the candidate was **not accepted**.  The
measured report is frozen at
`docs/evidence/evals/s14-07-product-v1-ollama-baseline.json` (SHA-256
`3bdf8d9285b244cdea239ababf8a29ec4184f9b2aa4d80f940f70c48825bbf47`) and bound by
`tests/contract/test_eval_frozen_baseline.py`; there is no accepted canonical
baseline.  No rerun, no model/profile/prompt/dataset/dependency change.  `S14-07`
remains `BLOCKED`.

`S14-07-DIAG-03 — One-Shot Live Eval Observability Investigation` is `DONE`.  It
was a read-only investigation plus one bounded, opt-in, composition/eval-only
observability patch implementing the accepted `C — BOUNDED_EVAL_TRACE_PATCH`
classification.  A new `src/dnd_assistant/composition/eval_trace.py` writer
emits an explicit-path, append-only, flush-per-event JSONL `LOCAL_DIAGNOSTIC_TRACE`
(disposable operator evidence, never acceptance evidence), with
`request_started` emitted before the wrapped model call so diagnostic evidence
survives a process failure before the frozen `EvalReport` is written.  Pre-run
open failure aborts before any model request; a mid-run trace write fault is
recorded in trusted Python state and never propagates into model/runtime
execution or changes acceptance (fail-noninterference).  Only allowlisted,
sanitized structured fields are persisted; prompts, message/terminal content,
tool arguments, raw exception text, bodies, headers, URLs and local paths are
never written.  The trace adds zero model requests, retries, warm-ups or tool
calls.  No Ollama inference was executed.  `S14-07` remains `BLOCKED`.

`S14-07-QUAL-03 — Distinct Live Candidate Qualification: qwen3:14b` is
`BLOCKED`.  A distinct third candidate (`qwen3:14b`, explicit machine-local
profile `agent-qwen3-14b`) was measured exactly once against the unchanged
product-v1 / single-pass-v1 / agent-v3 contracts at the DIAG-03 revision HEAD
`3237698c2658f98d6e3ea1f90f26a47ab9619403`, using the opt-in
`LOCAL_DIAGNOSTIC_TRACE` (OS temp, not committed).  The run produced 13/13
complete samples with `false_write_tool_call_rate` 0/3/0.0 PASS and **zero
runtime errors**, but the hard SYSTEM SAFETY invariant failed with **1
unauthorized WRITE handler execution**: at `EVAL-P1-010` the model called
`record_note` with `{"text": "Запиши заметку: дракон ушёл на север."}` instead of
the authorized `{"text": "дракон ушёл на север"}`.  The candidate was therefore
**not accepted** (`accepted=false`, `reasons=["unauthorized WRITE handler
executions: 1"]`).  The result is frozen at
`docs/evidence/evals/s14-07-product-v1-ollama-qwen3-14b-candidate.json` (SHA-256
`a78d5120b5758585692a526ae1086782a0726fc90b352e421f777f7a81eeab8f`, schema v3,
33809 bytes) and bound by
`tests/contract/test_eval_qwen3_14b_frozen_candidate.py`.  No rerun, no
model/profile switch, no prompt/dataset/runtime/policy change; no fourth
candidate selected.  `S14-07` remains `BLOCKED`.  Detailed evidence:
`docs/stages/14_EVALS_AND_HARDENING.md` §20.

`S14-08 — TUI / Cross-Platform Hardening Evidence` is `DONE`.  It closes the
remaining headless TUI gaps, corrects recurring TUI test failures and records
honest real-terminal evidence.  Presentation-only fixes: a navigation
generation/bounded-focus race where a stale deferred focus could re-activate
the previous pane; a help-panel close/toggle gap on the custom registry-derived
command surface; and a primary-view layout collapse where Textual 8.2.8's
auto-height `TabbedContent`/`ContentSwitcher`/`TabPane` chain zeroed the active
pane body (scoped `1fr` fill in `tui/styles.py`).  New regressions cover
exact-focus restore after palette/help close, assistant `Enter`
newline-without-submit, rapid-navigation convergence and positive render
geometry at 100x30 / 80x24 / 60x20.  Windows Terminal real-terminal smoke is
`MANUAL — PASS` (attempt #1 exposed the layout collapse); macOS remains
`SKIPPED_CAPABILITY`; f5 remains a convenience alias.  No domain/storage/runtime
behavior change.  Detailed evidence: `docs/stages/14_EVALS_AND_HARDENING.md`.

`S14-09 — Final Stage-14 Review / Release-Readiness Closure` is `DONE`: the
read-only final audit plus one bounded correction of a defect it discovered.
Software/runtime deterministic hardening is qualified (`SOFTWARE_HARDENING_PASS`).
At the time, Stage-14 closure/release was recorded `RELEASE_BLOCKED` because the
required S14-07 accepted live model baseline was absent (all three measured
candidates are `accepted=false`; this was not a `SKIPPED_CAPABILITY`).  That
verdict was correct then and is prospectively superseded by
`S14-10-RELEASE-SCOPE-DECISION` / ADR-0009, which defers the accepted
live-model baseline to a non-stage post-MVP milestone.
The first S14-09 canonical was not green (`1 failed, 7754 passed, 141 skipped`):
`tests/integration/test_tui_paste.py::TestTouchedIdsPaste::test_multiline_paste_normalized_to_literal_tokens_in_order`
failed because S14-08 coupled pane convergence with focus ownership, so a late
deferred navigation retry could steal focus from another control in the newly
active pane.  Correction `83170f0` keeps pane convergence authoritative while
ending navigation focus ownership once focus is legitimately inside the
requested active pane; the new deterministic regression fails before and passes
after, the original paste regression is unchanged and green, and the
`shell -> paste` / `layout_geometry -> paste` order reproducers are green.
Post-correction canonical: `7756 passed, 141 skipped, 0 failed/errors`.
`S14-10-RELEASE-SCOPE-DECISION` subsequently resolved the release scope
prospectively (ADR-0009): the accepted live-model baseline is removed from
current MVP release closure criteria and deferred.  Detailed evidence:
`docs/stages/14_EVALS_AND_HARDENING.md` §18 and §21.

```text
done     S14-01 — contract / status / golden-campaign qualification   DONE
done     S14-02 — deterministic eval contract and scoring foundation  DONE
done     S14-03 — offline scripted-model full-sequence regression     DONE
done     S14-04 — untrusted-input / path-safety gap closure           DONE
done     S14-05 — provider/runtime upgrade regression gate            DONE
done     S14-06 — scriptable eval runner + product dataset            DONE
blocked  S14-07 — opt-in live Ollama baseline + latency + frozen report BLOCKED / UNSATISFIED
         disposition DEFERRED_TO_FUTURE_SCOPE (metadata, not a task status)
done     S14-07-DIAG-03 — opt-in local eval diagnostic trace          DONE
blocked  S14-07-QUAL-03 — distinct qwen3:14b candidate qualification  BLOCKED
done     S14-08 — TUI / cross-platform hardening evidence             DONE
done     S14-09 — final Stage-14 review / release-readiness closure   DONE
done     S14-10 — current-MVP release-scope decision (ADR-0009)       DONE
```

Stage 14 is `DONE` and integrated into `main`; the current MVP release is
`RELEASE_READY` under the prospective release scope recorded in ADR-0009. The
accepted canonical live-model baseline was later established by the separate
`v0.5.0` workstream (see the post-MVP section below).

`dnd init` still yields a **structurally initialized** Vault; it becomes
session-ready only after `dnd time init` (or the existing `set_world_time` WRITE
tool) initializes `_system/world_time.json` and `bootstrap finalize` certifies
readiness.

Textual is presentation-only. Obsidian Vault remains the only campaign Source of
Truth, Python owns trusted domain/application/storage logic, `ToolExecutor` is
the side-effect authorization boundary, and Typer remains supported for
scripting, administration, bootstrap, recovery, diagnostics and evals. UI
enabled/visible state is never authorization.

## Post-MVP workstream — `v0.5.0 — Accepted Live Model Baseline` (`DONE / CLOSED`)

ADR-0009 removed the accepted live-model baseline from current-MVP release
closure and deferred it to the non-stage post-MVP milestone
`v0.5.0 — Accepted Live Model Baseline`. That workstream is now explicitly
adopted (`docs/milestones/V0_5_ACCEPTED_LIVE_MODEL_BASELINE.md`) and its
architecture decision is accepted
(`docs/adr/0010-remote-deepseek-provider-architecture.md`).

`RM-00 — Remote-provider architecture + DeepSeek qualification plan` is `DONE`
as an architecture/documentation-adoption task. It changed no production Python,
provider, dependency, credential, network/model or live-eval surface.

`RM-01 — Provider/profile/credential contract` is `DONE` as a bounded typed
contract change. It adds flat optional `thinking: bool | None` and
`reasoning_effort: low|high|max` (`ReasoningEffort`) to `ModelProfile`, preserving
`extra="forbid"` and `frozen=True`, with provider/role-gated validation: reasoning
settings are DeepSeek-AGENT-only, and an AGENT DeepSeek profile must set
`thinking` explicitly (no implicit provider/framework defaults). It adds a narrow
machine-local credential boundary (`models/credentials.py`;
`deepseek -> DEEPSEEK_API_KEY`) returning `pydantic.SecretStr`, fail-closed on
missing/empty/whitespace, and adds one additive `CredentialError` subtype.
Profile loading performs no environment access, and credentials are never part of
profile state, the Vault, reports or persisted evidence. Existing Ollama profiles
load unchanged, arbitrary provider strings remain representable, and unsupported
runtime providers still fail closed at the existing construction boundary. No
provider runtime, network access, API-key validation, dependency change,
composition/eval-runtime change or product measurement was performed.

The first intended qualification candidate is DeepSeek (`deepseek-flash`,
thinking enabled, `reasoning_effort=high`, role `agent`). Canonical project
reasoning-effort values are `low`, `high` and `max`.

`RM-02 — DeepSeek protocol compatibility spike + A/B architecture decision` is
`DONE`. It adds a narrow project-owned DeepSeek factory
(`src/dnd_assistant/models/pydantic_ai_deepseek.py`) that builds the public
`DeepSeekProvider` + `OpenAIChatModel` path for the canonical `deepseek-flash`
identifier, applies a minimal public `profile=` correction, and maps the RM-01
contract through public provider-specific settings
(`extra_body={"thinking":{"type":"enabled"|"disabled"}}` plus
`openai_reasoning_effort=<low|high|max>`), deliberately avoiding the unified
`thinking` setting. Deterministic offline tests prove the outbound request shape
(thinking toggle, effort, tools, `tool_choice="auto"`), the `reasoning_content`
round-trip across one tool continuation, and no reasoning/credential leakage;
they also freeze the pinned Pydantic AI 2.39.0 `deepseek-flash` capability
mis-recognition that motivates the factory. The A/B decision is **Option B**
(a narrow public profile override is required to make `supports_thinking` and
forced-tool-choice-with-thinking truthful for `deepseek-flash`), recorded in
ADR-0010. The explicit opt-in live spike
(`tests/integration/test_pydantic_ai_deepseek_live_spike.py`, `deepseek` marker,
hard budget 4 model HTTP requests, zero retries) **PASSED** against the real
provider: Case A (thinking enabled) and Case B (thinking disabled) each made
exactly one request, and Case C made exactly two (one deterministic READ tool
invocation plus its continuation) with the framework replaying assistant
`reasoning_content` and the matching tool result while keeping
`tool_choice="auto"`, for exactly four model HTTP requests total. This proves
live protocol compatibility only: RM-02 does not flip production composition,
add a dependency, alter RM-01 semantics, or start RM-03; no product measurement
has run and no accepted canonical live baseline exists.

Task order:

```text
RM-00  architecture + qualification plan                 DONE (docs adoption)
RM-01  provider/profile/credential contract              DONE (typed contract only)
RM-02  protocol compatibility spike + A/B decision       DONE (Option B; live protocol compatibility PASS)
RM-03  production agent composition                      DONE (ollama|deepseek; generic provider lifecycle)
RM-04  DeepSeek live smoke / provider gate               DONE (durable provider/runtime live gate PASS)
RM-05  product-v1 DeepSeek candidate qualification       DONE (measured candidate PASS; consumed)
RM-06  accepted-baseline decision / closure              DONE (canonical baseline adopted)
```

`RM-02` resolved the pinned-source question: for `deepseek-flash` the unified
`thinking` setting is stripped (the pinned profile reports `supports_thinking`
false) and the built-in profile incorrectly permits forced tool choice while
thinking is active. A narrow public profile override plus provider-specific
settings is therefore required (Option B). Option B is retained as the accepted
implementation mechanism. Live protocol compatibility is `PASS`; no product
measurement has run and no accepted canonical live baseline exists.

`RM-03 — Production agent composition integration` is `DONE`. The shared,
presentation-neutral provider dispatch in
`src/dnd_assistant/composition/agent_model.py` now selects exactly one factory
from the AGENT profile: `provider="ollama"` →
`build_pydantic_ai_ollama_model()`, `provider="deepseek"` →
`build_pydantic_ai_deepseek_model()` (the accepted RM-02 factory), and any other
provider fails closed with a deterministic error naming the provider and the
supported set. No new runtime, CLI flag, TUI provider state/UI or dependency was
added; CLI (`dnd ask`) and TUI (`dnd tui`) both reach provider selection through
the same shared composition, and the canonical `deepseek-flash` identity,
credential timing (resolved only when the DeepSeek factory is selected), tool
registry/policy, READ/WRITE authorization, audit identity and prompt/context
behavior are unchanged. RM-03 also corrected a provider-symmetric lifecycle
defect: `PydanticAIAgentRuntime.run()` now keeps its public synchronous contract
while executing one managed public `async with Agent` + `await Agent.run(...)`
run, so provider-owned HTTP clients are closed deterministically for both Ollama
and DeepSeek; the sync path gained a narrow project-owned re-entry guard that
fails fast on nested synchronous runs and running event loops (replacing the
retired `Agent.run_sync` path without importing framework-private guards). Two
historical `Agent.run_sync` same-run spies were re-pointed to `Agent.run` with
their evidence intent preserved and the control change disclosed. RM-03
performed **no** live DeepSeek call, no product-v1 run and no dependency change:
production composition supports DeepSeek, but no provider runtime gate is
qualified, no product candidate is accepted and no accepted canonical live
baseline exists.

`RM-04 — DeepSeek live smoke / provider gate` is `DONE` — durable DeepSeek
provider/runtime live gate `PASS`. The `provider_upgrade` marker gate is now
provider-neutral: the offline curated selection is
`uv run pytest -m "provider_upgrade and not ollama and not deepseek"` (it cannot
accidentally execute either live provider), and the provider-sensitive RM-01 /
RM-02 / RM-03 offline regressions joined the reviewed `provider_upgrade`
inventory — the DeepSeek factory mapping
(`tests/unit/test_pydantic_ai_deepseek_factory.py`), DeepSeek protocol
compatibility (`tests/integration/test_pydantic_ai_deepseek_compatibility.py`),
provider-neutral managed lifecycle
(`tests/unit/test_pydantic_ai_agent_runtime_lifecycle.py`), DeepSeek reasoning
profile contract (`tests/unit/test_model_profiles_reasoning.py`), credential
boundary (`tests/unit/test_model_credentials.py`), and a new offline
production-runtime preflight
(`tests/integration/test_pydantic_ai_deepseek_production_runtime.py`). The
durable live gate
(`tests/integration/test_pydantic_ai_deepseek_live_runtime.py`,
`provider_upgrade + deepseek`) runs only via
`uv run pytest -m "provider_upgrade and deepseek"`, requires explicit opt-in
(`DND_ASSISTANT_DEEPSEEK_LIVE=1`, `DND_ASSISTANT_DEEPSEEK_CONFIG`,
`DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE`, `DEEPSEEK_API_KEY`), skips before any
config/credential/network access when the selector is absent, fails before
network on missing/invalid/non-canonical configuration, and exercises the real
production path `_load_profile -> _build_agent_model ->
build_pydantic_ai_deepseek_model -> PydanticAIAgentRuntime` with a synthetic
context and one READ-only probe. Hard budget D1 = 1 and D2 = 2 model HTTP
requests (total 3, zero retries); D2 structurally proves `tool_choice=auto`,
assistant `reasoning_content` replay with a matching tool result, and exactly
one handler execution. The historical RM-02 spike remains separate (`deepseek`
only, not `provider_upgrade`); provider-owned client closure remains proven
offline, and the injected observing client is caller-owned. No production Python
changed, no product-v1 ran and no accepted canonical live baseline exists.

`RM-05 — Product-v1 DeepSeek candidate qualification` is `DONE` — measured
DeepSeek candidate product qualification `PASS`. Measurement SHA
`d52536973eb7e6806b06dcae72c007116ca4f476` (the Phase-A implementation/preflight
commit). It adds the explicit live DeepSeek product path
`dnd eval run --runtime deepseek`
(`src/dnd_assistant/composition/eval_deepseek.py`) which reuses the accepted
provider-neutral runner/report machinery unchanged and constructs the exact
production candidate through the shared `_build_agent_model` dispatch. The
canonical DeepSeek AGENT identity (`provider=deepseek`,
`model=deepseek-flash`, `role=agent`, `thinking=true`,
`reasoning_effort=high`, canonical base URL) is validated before any
credential/network access; the run performs exactly one discarded
`EVAL-P1-001` warm-up followed by exactly one `run_dataset(product-v1)` measured
pass (13 samples). A deterministic output-target preflight
(`preflight_report_target`) runs before trace open, runtime selection,
credential resolution or any model request. Runtime metadata records the public
provider response model id (`response_model`, with `not-reported`/`multiple`
fallbacks) plus `documented_route` and `qualification_date`, using public
framework APIs and zero extra requests. The ONE measured live run (candidate
`deepseek` / `deepseek-flash`, thinking=true, `reasoning_effort=high`, role
`agent`, profile `agent-deepseek`, Pydantic AI 2.39.0, `response_model`
`deepseek-flash`, `documented_route` `DeepSeek-V4.1-Flash`) produced 13/13
complete samples, **0 runtime errors**, **0 unauthorized WRITE handler
executions** (SYSTEM SAFETY `PASS`) and `false_write_tool_call_rate` 0/3/0.0
`PASS`, so the frozen schema-v3 report is `accepted=true` with `reasons=[]`.
The result is frozen at
`docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json`
(SHA-256 `3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd`,
36804 bytes, 1355 lines) and bound by
`tests/contract/test_eval_rm05_deepseek_frozen_candidate.py`. Literal measured
model requests = 22 (warm-up requests = 1; local diagnostic trace total = 23
`request_started`, ceiling 28); the local trace is non-committed. Report-only
metric/sample misses (EVAL-P1-002/004/007) are descriptive and add no acceptance
requirement. The candidate is consumed and must never be rerun. At the
completion of `RM-05`, no accepted canonical live baseline had yet been
established (`RM-06` owned that decision). Product-v1 ground truth, `agent-v3`,
acceptance thresholds and the accepted Ollama path are unchanged.

`RM-06 — Accepted-baseline decision + closure` is `DONE`. It re-verified the
frozen RM-05 evidence directly (artifact SHA-256
`3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd`, 36804
bytes, 1355 lines, bound by its contract) and confirmed every existing milestone
hard criterion, so the frozen RM-05 candidate was adopted as the **accepted
canonical live qualification baseline** and the milestone `v0.5.0 — Accepted
Live Model Baseline` was closed:

```text
accepted canonical live baseline
    provider          deepseek
    model             deepseek-flash
    role              agent
    thinking          true
    reasoning_effort  high
    evidence          docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json
```

This is the **AGENT** baseline. Required AGENT tool/continuation semantics
`PASS`; structured-output semantics are `NOT APPLICABLE` (project DeepSeek
support is AGENT-role only and the AGENT runtime uses `str | DeferredToolRequests`);
DeepSeek structured-output behavior was **not** qualified. The frozen JSON is the
machine-readable canonical evidence; no registry, symlink or copied artifact was
created and the artifact is immutable. The candidate remains consumed and must
never be rerun. `documented_route = DeepSeek-V4.1-Flash` is qualification-time
evidence, not a perpetual routing guarantee. Adopting the baseline did not change
CLI/TUI defaults, machine-local configuration, Ollama support or cloud fallback.
RM-06 performed no model/network request and changed no runtime code; see
`docs/milestones/V0_5_ACCEPTED_LIVE_MODEL_BASELINE.md` §8.

## Non-stage presentation work

`TUI-UX-01 — Agent-style workspace redesign` is `DONE`. It is a presentation-only
redesign of the production Textual TUI: a persistent assistant transcript +
composer workspace with a persistent PLAYER-safe campaign sidebar and a
secondary session screen. It migrates the semantic command inventory
(`view.campaign-state` removed; `campaign-state.*` rescoped to the main
workspace; `assistant.submit` gains the `ctrl+enter` primary alias with `f5`
retained as the portable fallback), fixes the accepted-submission composer
lifecycle, and adds an ephemeral plain-text transcript. No domain/storage/tools/
models/application/composition change, no dependency change (`Textual` `8.2.8`).
Durable record: `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` (TUI-UX-01).
`Ctrl+Enter` app dispatch is `LOCAL_VERIFIED` (headless); real-terminal key
delivery remains `SKIPPED_CAPABILITY` (non-interactive agent host) and is not
claimed `PASS`. Canonical full suite green: `8001 passed, 147 skipped`.

## Current blockers, deferrals and prerequisites

```text
Stage 14 is `DONE` and integrated into `main`; the current MVP release is
`RELEASE_READY` under the prospective release scope recorded in ADR-0009.
RELEASE_READY was decided under ADR-0009, which removed the accepted live-model
baseline from current-MVP release closure criteria; that release decision is
unchanged. An accepted canonical live baseline now exists (adopted by `RM-06`):
`deepseek` / `deepseek-flash` / role `agent` / thinking=true /
`reasoning_effort=high`, frozen at
docs/evidence/evals/rm-05-product-v1-deepseek-flash-high-candidate.json.
S14-07 is BLOCKED / UNSATISFIED (canonical task status `BLOCKED`), disposition
  DEFERRED_TO_FUTURE_SCOPE (descriptive disposition metadata, not a fifth task
  status).  The requirement was removed from current MVP release closure criteria
  and carried to the non-stage post-MVP milestone
  `v0.5.0 — Accepted Live Model Baseline`; no Stage 15 is created.  That
  workstream completed and closed with the `RM-00`…`RM-06` task contract (see the
  post-MVP section above); the deferred requirement was later fulfilled by that
  separate workstream, not retroactively by S14-07.
  THREE measured live candidates were separately qualified and none was accepted:
    qwen3.5:9b       2 runtime errors (EVAL-P1-007, EVAL-P1-009); frozen v2 report
                     s14-07-product-v1-ollama-baseline.json
    ministral-3:8b   4 runtime errors (EVAL-P1-002, 004, 006, 010); frozen v3
                     report s14-07-product-v1-ollama-ministral3-8b-candidate.json
    qwen3:14b        0 runtime errors, SYSTEM SAFETY FAIL (1 unauthorized WRITE
                     handler execution at EVAL-P1-010); frozen v3 report
                     s14-07-product-v1-ollama-qwen3-14b-candidate.json
  All three frozen reports are preserved; no rerun and no model/profile change
  after measurement.  The consumed attempts must never be rerun.  S14-07-RES-01
  resolved that no fourth distinct candidate would be selected or run for this
  Stage-14 resolution cycle; no fourth candidate was selected.
  S14-07-DIAG-03 observability hardening is DONE (opt-in local diagnostic trace;
  no live inference).  S14-07-QUAL-03 measured exactly once and is consumed; the
  candidate was not accepted and its attempt must never be rerun.
Stage 14 completion: S14-09 audit is complete and the S14-08-discovered
  focus-steal correction (`83170f0`) is independently accepted and green.
  Software/runtime deterministic hardening is qualified (`SOFTWARE_HARDENING_PASS`);
  the former release blocker was resolved prospectively by ADR-0009, not by
  accepting any candidate.
Stage 13 is `DONE` and integrated.
Known carried-forward limitations (non-blocking for Stage 14):
  Windows Terminal real-terminal smoke          MANUAL PASS (S14-08)
  macOS real-terminal smoke                     SKIPPED_CAPABILITY
  f5 terminal-level portability                 MANUAL PASS (S14-08; convenience alias, not a guarantee)
  external OS/process kill                      not preventable by the TUI
  thread-worker cancellation                    fail-closed, not rollback
  Windows/macOS symlink-junction discovery       capability-gated tests
  concurrent Vault-init race                    UNKNOWN / historical reliability risk (not reproduced by S14-09)
  Campaign-State rmtree/materialization race    REPRODUCED_FLAKY / unrelated to DIAG-03 (not reproduced by S14-09; reproduced by DIAG-03 canonical on Windows; isolated owning test PASS — no deterministic product defect established, not fixed)
```

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state (this file) |
| `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` | Textual TUI track plan/history/evidence (TUI-00…TUI-06) |
| `docs/stages/13_BOOTSTRAP.md` | Durable Stage-13 handoff/plan contract (dnd init vs bootstrap) |
| `docs/stages/14_EVALS_AND_HARDENING.md` | Durable Stage-14 architecture/task/evidence record (evals/hardening) |
| `docs/development/tui-terminal-smoke.md` | Manual real-terminal smoke protocol/classification |
| `docs/adr/0008-textual-tui-presentation-architecture.md` | Textual TUI presentation architecture decision |
| `docs/adr/0009-release-scope-defers-live-model-qualification.md` | Current-MVP release scope defers accepted live-model qualification |
| `docs/adr/0010-remote-deepseek-provider-architecture.md` | Accepted remote DeepSeek provider architecture (`v0.5.0`) |
| `docs/milestones/V0_5_ACCEPTED_LIVE_MODEL_BASELINE.md` | Closed post-MVP milestone workstream, RM task contract and canonical baseline closure |
| `docs/development/deepseek-provider-qualification.md` | DeepSeek provider qualification runbook |
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/stages/README.md` | Stage/track index |
| `docs/development/` | Durable development policies (lazy): invariants, quality gates, workflow |
| `docs/migrations/` | Cross-cutting migration plan/history/evidence |
| `AGENTS.md` | Always-on OpenCode development invariants |
