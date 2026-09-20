# D&D Session Assistant — Development Status

**Last updated:** 2026-09-20 (S14-M01-INTEGRATION)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
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
`RELEASE_READY` under the prospective release scope recorded in ADR-0009; no
accepted canonical live-model baseline currently exists.

`dnd init` still yields a **structurally initialized** Vault; it becomes
session-ready only after `dnd time init` (or the existing `set_world_time` WRITE
tool) initializes `_system/world_time.json` and `bootstrap finalize` certifies
readiness.

Textual is presentation-only. Obsidian Vault remains the only campaign Source of
Truth, Python owns trusted domain/application/storage logic, `ToolExecutor` is
the side-effect authorization boundary, and Typer remains supported for
scripting, administration, bootstrap, recovery, diagnostics and evals. UI
enabled/visible state is never authorization.

## Current blockers, deferrals and prerequisites

```text
Stage 14 is `DONE` and integrated into `main`; the current MVP release is
`RELEASE_READY` under the prospective release scope recorded in ADR-0009.
RELEASE_READY does NOT mean a
canonical local live model has been validated: no accepted canonical live-model
baseline currently exists.
S14-07 is BLOCKED / UNSATISFIED (canonical task status `BLOCKED`), disposition
  DEFERRED_TO_FUTURE_SCOPE (descriptive disposition metadata, not a fifth task
  status).  The requirement is removed from current MVP release closure criteria
  and carried to the non-stage post-MVP milestone
  `v0.5.0 — Accepted Live Model Baseline`; no Stage 15 and no future task are
  created now.
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
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/stages/README.md` | Stage/track index |
| `docs/development/` | Durable development policies (lazy): invariants, quality gates, workflow |
| `docs/migrations/` | Cross-cutting migration plan/history/evidence |
| `AGENTS.md` | Always-on OpenCode development invariants |
