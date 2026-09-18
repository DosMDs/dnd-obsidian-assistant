# D&D Session Assistant — Development Status

**Last updated:** 2026-09-18 (S13-03)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `DONE` (integrated); Stage 13 `IN PROGRESS`; Stage 14 `NOT STARTED`
**Active work:** `S13-03 — Existing Campaign Bootstrap / Mapping` `DONE`; next `S13-04 — Bootstrap ChangeSet Review / Apply`
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
| 13. Bootstrap | IN PROGRESS | S13-01 `DONE`; S13-02 `DONE`; S13-03 `DONE`; next `S13-04`; `docs/stages/13_BOOTSTRAP.md` |
| 14. Evals / Hardening | NOT STARTED | — |

## Current work — S13-03 `DONE`

`S13-03 — Existing Campaign Bootstrap / Mapping` is `DONE` on
`feat/bootstrap` (not yet merged to `main`).  It consumes the accepted S13-02
read-only discovery report (no second filesystem traversal), recognizes
genuinely canonical entities from already-read `ENTITY_CANDIDATE` text through
a filesystem-free storage helper, and maps eligible source material through a
BOOTSTRAP-role heavy model to a deterministic Stage-10 ChangeSet proposal plus
an immutable `_system/bootstrap/<id>.mapping.json` evidence sidecar.  Model
output is untrusted and cannot carry a canonical `EntityId`; binding is exact
and Python-owned; ambiguous, conflicting, unsupported and non-canonical
material becomes typed unresolved diagnostics rather than speculative
mutation.  No canonical campaign mutation, no review/approval/apply and no
derived rebuild.  Stage 13 remains `IN PROGRESS`.

```text
next   S13-04 — Bootstrap ChangeSet Review / Apply
```

S13-04 must decide/enforce the mixed-Vault review/apply readiness prerequisite
before any apply authority; S13-03 explicitly does not implement normalization.

`dnd init` yields a **structurally initialized** Vault, not a session-ready
one: `_system/world_time.json` is deliberately out of scope.  A deterministic
Typer admin surface for the starting world tick is a recorded Stage-13
follow-up decision; the existing `set_world_time` WRITE tool can initialize it.

Textual is presentation-only. Obsidian Vault remains the only campaign Source of
Truth, Python owns trusted domain/application/storage logic, `ToolExecutor` is
the side-effect authorization boundary, and Typer remains supported for
scripting, administration, bootstrap, recovery, diagnostics and evals. UI
enabled/visible state is never authorization.

## Current blockers and prerequisites

```text
No confirmed blocker for Stage 13.
S13-01 and S13-02 are DONE; next planned task S13-03 is not started.
Recorded Stage-13 follow-up (not a blocker):
  deterministic Typer admin surface for starting world time
Known carried-forward limitations (non-blocking for Stage 13):
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
| `docs/development/tui-terminal-smoke.md` | Manual real-terminal smoke protocol/classification |
| `docs/adr/0008-textual-tui-presentation-architecture.md` | Textual TUI presentation architecture decision |
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/stages/README.md` | Stage/track index |
| `docs/development/` | Durable development policies (lazy): invariants, quality gates, workflow |
| `docs/migrations/` | Cross-cutting migration plan/history/evidence |
| `AGENTS.md` | Always-on OpenCode development invariants |
