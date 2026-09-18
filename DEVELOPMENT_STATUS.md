# D&D Session Assistant — Development Status

**Last updated:** 2026-09-18 (TUI-06)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `IN PROGRESS` (integration pending); Stage 13 `NOT STARTED`; Stage 14 `NOT STARTED`
**Active work:** Textual TUI Architecture Track — TUI-06 `DONE`; next `TUI-M01` (ff-only integration); Stage 13 is gated on independent acceptance of `TUI-M01`
**Current branch:** `feat/textual-tui`

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
| Textual TUI Architecture Track (non-numbered) | IN PROGRESS | integration pending; `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` |
| 13. Bootstrap | NOT STARTED | Gated on `TUI-M01` acceptance (not `BLOCKED`); `docs/stages/13_BOOTSTRAP.md` |
| 14. Evals / Hardening | NOT STARTED | — |

## Current work — Textual TUI Architecture Track

TUI-00 … TUI-05 are `DONE`; TUI-06 (full track review / status cleanup /
Stage-13 handoff / OpenCode inspection-permission hardening) is `DONE`. The
implementation itself is complete and reviewed on `feat/textual-tui`. What
remains is **repository integration**, which is deliberately kept as a separate
bounded task:

```text
next   TUI-M01 — ff-only integrate feat/textual-tui into main
```

`main` is an ancestor of the reviewed feature head, so a fast-forward-only
integration path is available. Stage 13 remains gated until
`TUI-M01` receives independent acceptance; only then does the next work become
`S13-01 — Vault Initialization Contract + dnd init`.

Textual is presentation-only. Obsidian Vault remains the only campaign Source of
Truth, Python owns trusted domain/application/storage logic, `ToolExecutor` is
the side-effect authorization boundary, and Typer remains supported for
scripting, administration, bootstrap, recovery, diagnostics and evals. UI
enabled/visible state is never authorization.

## Current blockers and prerequisites

```text
No confirmed blocker for the Textual TUI Architecture Track or Stage 13.
Sequencing gate (not a blocker): Stage 13 must not begin until TUI-M01
integration is independently accepted.
Known carried-forward limitations (non-blocking for Stage 13):
  Windows Terminal real-terminal smoke          SKIPPED_CAPABILITY
  macOS real-terminal smoke                     SKIPPED_CAPABILITY
  f5 terminal-level portability                 SKIPPED_CAPABILITY
  external OS/process kill                      not preventable by the TUI
  thread-worker cancellation                    fail-closed, not rollback
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
