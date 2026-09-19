# D&D Session Assistant — Development Status

**Last updated:** 2026-09-19 (S13-05)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `DONE` (integrated); Stage 13 `DONE`; Stage 14 `NOT STARTED`
**Active work:** `S13-05 — Bootstrap Completion / Validation / Derived Rebuild` `DONE`; next `Stage 14 — Evals / Hardening`
**Current branch:** `feat/bootstrap`

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
| 13. Bootstrap | DONE | S13-01 … S13-05 `DONE`; `docs/stages/13_BOOTSTRAP.md` |
| 14. Evals / Hardening | NOT STARTED | — |

## Current work — S13-05 `DONE`

`S13-05 — Bootstrap Completion / Validation / Derived Rebuild` is `DONE` on
`feat/bootstrap` (not yet merged to `main`).  `dnd bootstrap finalize` runs a
recovery preflight, requires an initialized Vault with a strict valid canonical
repository, requires canonical world time and no active session, then runs one
fresh S13-02 discovery + S13-03 mapping through the accepted
`BootstrapRuntime.run(persist=True)` (existing BOOTSTRAP role/prompt/schema/
binder/producer; no second implementation).  It performs an immediate semantic
source-fingerprint recheck before any normal mapping terminal status, so a stale
persisted proposal is never advertised as `PENDING_CHANGESET`.  Completion is a
typed non-boolean result; incomplete canonical coverage is never acknowledgeable,
ordinary unresolved diagnostics require `--acknowledge-unresolved`, and
`COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED` never claims complete historical
knowledge.  Derived maintenance rebuilds Campaign State and FTS independently
(no transaction/rollback), verifies `CURRENT`/freshness literally and rechecks
final source stability.  `dnd time init --vault PATH --world-tick INTEGER` adds
the deterministic, model-free initialize-once starting-world-time admin surface
(recovery preflight + repository audit); no completion marker and no
`Campaign/Bootstrap.md` are created.  Stage 13 is `DONE`.

```text
next   Stage 14 — Evals / Hardening (NOT STARTED)
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
No confirmed blocker for Stage 13.  Stage 13 is DONE.
Known carried-forward limitations (non-blocking for Stage 13):
  Windows Terminal real-terminal smoke          SKIPPED_CAPABILITY
  macOS real-terminal smoke                     SKIPPED_CAPABILITY
  f5 terminal-level portability                 SKIPPED_CAPABILITY
  external OS/process kill                      not preventable by the TUI
  thread-worker cancellation                    fail-closed, not rollback
  Windows/macOS symlink-junction discovery       capability-gated tests
  TUI campaign-state concurrency timing flake    passed on isolated/module rerun
```

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state (this file) |
| `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` | Textual TUI track plan/history/evidence (TUI-00…TUI-06) |
| `docs/stages/13_BOOTSTRAP.md` | Durable Stage-13 handoff/plan contract (dnd init vs bootstrap) |
| `docs/development/tui-terminal-smoke.md` | Manual real-terminal smoke protocol/classification |
| `docs/adr/0008-textual-tui-presentation-architecture.md` | Textual TUI presentation architecture decision |
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/stages/README.md` | Stage/track index |
| `docs/development/` | Durable development policies (lazy): invariants, quality gates, workflow |
| `docs/migrations/` | Cross-cutting migration plan/history/evidence |
| `AGENTS.md` | Always-on OpenCode development invariants |
