# D&D Session Assistant — Development Status

**Last updated:** 2026-09-20 (S14-08)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `DONE` (integrated); Stage 13 `DONE` (integrated); Stage 14 `IN PROGRESS`
**Active work:** `S14-07 — Opt-in Live Ollama Model Baseline + Latency Metrics + Frozen Report` `BLOCKED`; `S14-08 — TUI / Cross-Platform Hardening Evidence` `DONE`; next `S14-09` `NOT STARTED`
**Current branch:** `feat/evals-hardening`

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
| 14. Evals / Hardening | IN PROGRESS | S14-01 … S14-06 `DONE`; S14-07 `BLOCKED` (implementation complete, live candidate not accepted); S14-08 `DONE`; S14-09 `NOT STARTED`; `docs/stages/14_EVALS_AND_HARDENING.md` |

## Current work — S14-08 `DONE`

Stage 13 is `DONE` and integrated into `main`; its detailed evidence lives in
`docs/stages/13_BOOTSTRAP.md`.  Stage 14 — Evals / Hardening is the active
roadmap stage.  `S14-00` (accepted planning / architecture / evidence
investigation) and the accepted Stage-14 architecture contract, gap matrix and
task decomposition are recorded in `docs/stages/14_EVALS_AND_HARDENING.md`.

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
unchanged).  Stage 14 remains `IN PROGRESS`.

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
remains `BLOCKED`; Stage 14 remains `IN PROGRESS`.

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

```text
done     S14-01 — contract / status / golden-campaign qualification   DONE
done     S14-02 — deterministic eval contract and scoring foundation  DONE
done     S14-03 — offline scripted-model full-sequence regression     DONE
done     S14-04 — untrusted-input / path-safety gap closure           DONE
done     S14-05 — provider/runtime upgrade regression gate            DONE
done     S14-06 — scriptable eval runner + product dataset            DONE
blocked  S14-07 — opt-in live Ollama baseline + latency + frozen report BLOCKED
done     S14-08 — TUI / cross-platform hardening evidence             DONE
next     S14-09 — final Stage-14 review / release-readiness closure   NOT STARTED
```

`dnd init` still yields a **structurally initialized** Vault; it becomes
session-ready only after `dnd time init` (or the existing `set_world_time` WRITE
tool) initializes `_system/world_time.json` and `bootstrap finalize` certifies
readiness.

Textual is presentation-only. Obsidian Vault remains the only campaign Source of
Truth, Python owns trusted domain/application/storage logic, `ToolExecutor` is
the side-effect authorization boundary, and Typer remains supported for
scripting, administration, bootstrap, recovery, diagnostics and evals. UI
enabled/visible state is never authorization.

## Current blockers and prerequisites

```text
S14-07 BLOCKED: no accepted canonical live baseline exists.  TWO measured live
  candidates were separately qualified and neither was accepted:
    qwen3.5:9b       2 runtime errors (EVAL-P1-007, EVAL-P1-009); frozen v2 report
                     s14-07-product-v1-ollama-baseline.json
    ministral-3:8b   4 runtime errors (EVAL-P1-002, 004, 006, 010); frozen v3
                     report s14-07-product-v1-ollama-ministral3-8b-candidate.json
  Both frozen reports are preserved; no rerun and no model/profile change after
  measurement.  A new accepted baseline requires a further distinct, explicit
  candidate/qualification decision (never a retry of an existing candidate).
Stage 13 is `DONE` and integrated.
Known carried-forward limitations (non-blocking for Stage 14):
  Windows Terminal real-terminal smoke          MANUAL PASS (S14-08)
  macOS real-terminal smoke                     SKIPPED_CAPABILITY
  f5 terminal-level portability                 MANUAL PASS (S14-08; convenience alias, not a guarantee)
  external OS/process kill                      not preventable by the TUI
  thread-worker cancellation                    fail-closed, not rollback
  Windows/macOS symlink-junction discovery       capability-gated tests
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
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/stages/README.md` | Stage/track index |
| `docs/development/` | Durable development policies (lazy): invariants, quality gates, workflow |
| `docs/migrations/` | Cross-cutting migration plan/history/evidence |
| `AGENTS.md` | Always-on OpenCode development invariants |
