# D&D Session Assistant — Development Status

**Last updated:** 2026-08-31
**Current milestone:** `v0.1-dev — Vault Core`
**Roadmap position:** Stage 5 completed
**Active stage:** None
**Next stage:** Stage 6 — Session Runtime without LLM
**Next stage status:** `NOT STARTED`

## Status model

Use only:

- `NOT STARTED`
- `IN PROGRESS`
- `BLOCKED`
- `DONE`

A task is not `DONE` merely because code was generated. Completion requires
the implementation, required tests, successful relevant checks, and final
diff review.

## Policy

This file stores **current roadmap state**, not detailed historical reports.

Detailed task/correction/review records belong in `docs/stages/`.

## Stage overview

| Stage | Status | Started | Completed | Details |
|---|---|---|---|---|
| 0. Environment | DONE | 2026-08-27 | 2026-08-27 | — |
| 1. Project skeleton + contracts | DONE | 2026-08-27 | 2026-08-30 | [`docs/stages/01_PROJECT_SKELETON_AND_CONTRACTS.md`](docs/stages/01_PROJECT_SKELETON_AND_CONTRACTS.md) |
| 2. Domain schemas | DONE | 2026-08-30 | 2026-08-30 | [`docs/stages/02_DOMAIN_SCHEMAS.md`](docs/stages/02_DOMAIN_SCHEMAS.md) |
| 3. Vault Repository | DONE | 2026-08-30 | 2026-08-30 | [`docs/stages/03_VAULT_REPOSITORY.md`](docs/stages/03_VAULT_REPOSITORY.md) |
| 4. Calendar | DONE | 2026-08-30 | 2026-08-31 | [`docs/stages/04_CALENDAR.md`](docs/stages/04_CALENDAR.md) |
| 5. Retrieval + Entity Resolution | DONE | 2026-08-31 | 2026-08-31 | [`docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md`](docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md) |
| 6. Session Runtime without LLM | NOT STARTED | — | — | — |
| 7. Tool Registry / Executor | NOT STARTED | — | — | — |
| 8. Model Gateway / Ollama | NOT STARTED | — | — | — |
| 9. Fast Agent | NOT STARTED | — | — | — |
| 10. ChangeSet | NOT STARTED | — | — | — |
| 11. Post-session Processor | NOT STARTED | — | — | — |
| 12. Campaign State | NOT STARTED | — | — | — |
| 13. Bootstrap | NOT STARTED | — | — | — |
| 14. Evals / Hardening | NOT STARTED | — | — | — |

## Current roadmap state

Stage 5 is complete.

Captured Stage-5 implementation review-head:

```
a1247eb7dfa496ed6cab39ff9f08e9b8ddbe7ae4
```

Stage-5 completion/status SHA:

```
c73913845de19255cf588723ac0d57ad0d916cc9
```

Detailed history: [`docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md`](docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md)

## Next stage

**Stage 6 — Session Runtime without LLM**

Status: `NOT STARTED`

Do not start automatically.

## Current blockers

None known.

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state |
| `docs/stages/README.md` | Documentation index and responsibility split |
| `docs/stages/01_PROJECT_SKELETON_AND_CONTRACTS.md` | Stage 1 detailed plan and history |
| `docs/stages/02_DOMAIN_SCHEMAS.md` | Stage 2 detailed plan and history |
| `docs/stages/03_VAULT_REPOSITORY.md` | Stage 3 detailed plan and history |
| `docs/stages/04_CALENDAR.md` | Stage 4 detailed plan and history |
| `docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md` | Stage 5 detailed plan and history |