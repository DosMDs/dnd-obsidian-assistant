# D&D Session Assistant — Development Status

**Last updated:** 2026-09-20 (S14-03)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `DONE` (integrated); Stage 13 `DONE` (integrated); Stage 14 `IN PROGRESS`
**Active work:** `S14-03 — Offline Scripted-Model Full-Sequence Regression` `DONE`; next `S14-04 — Untrusted-Input / Path-Safety Gap Closure` `NOT STARTED`
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
| 14. Evals / Hardening | IN PROGRESS | S14-01, S14-02, S14-03 `DONE`; S14-04 next `NOT STARTED`; `docs/stages/14_EVALS_AND_HARDENING.md` |

## Current work — S14-03 `DONE`

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

```text
done     S14-01 — contract / status / golden-campaign qualification   DONE
done     S14-02 — deterministic eval contract and scoring foundation  DONE
done     S14-03 — offline scripted-model full-sequence regression     DONE
next     S14-04 — untrusted-input / path-safety gap closure           NOT STARTED
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
No confirmed blocker for Stage 14.  Stage 13 is `DONE` and integrated.
Known carried-forward limitations (non-blocking for Stage 14):
  Windows Terminal real-terminal smoke          SKIPPED_CAPABILITY
  macOS real-terminal smoke                     SKIPPED_CAPABILITY
  f5 terminal-level portability                 SKIPPED_CAPABILITY
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
