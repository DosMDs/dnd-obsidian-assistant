# D&D Session Assistant — Development Status

**Last updated:** 2026-09-03 (S8-04 completed)
**Current milestone:** `v0.1-dev — Vault Core`
**Roadmap position:** Stage 8 in progress
**Active stage:** Stage 8 — Model Gateway / Ollama
**Stage 8 status:** `IN PROGRESS`
**Started:** 2026-09-02

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
| 6. Session Runtime without LLM | DONE | 2026-08-31 | 2026-09-02 | [`docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md`](docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md) |
| 7. Tool Registry / Executor | DONE | 2026-09-02 | 2026-09-02 | [`docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md`](docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md) |
| 8. Model Gateway / Ollama | IN PROGRESS | 2026-09-02 | — | [`docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`](docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md) |
| 9. Fast Agent | NOT STARTED | — | — | — |
| 10. ChangeSet | NOT STARTED | — | — | — |
| 11. Post-session Processor | NOT STARTED | — | — | — |
| 12. Campaign State | NOT STARTED | — | — | — |
| 13. Bootstrap | NOT STARTED | — | — | — |
| 14. Evals / Hardening | NOT STARTED | — | — | — |

## Current roadmap state

Stage 8 is in progress.

Pre-Stage-8 base:

```
9bca669894b2ae12a62381a2f7b6a5447c44e9cd
```

Detailed history: [`docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`](docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md)

## Current stage tasks

| Task | Status |
|---|---|
| S8-00 — Provider-neutral typed ModelGateway contracts + sync decision | DONE |
| S8-C00 — Harden ModelGateway plain-chat and JSON tool-call contracts | DONE |
| S8-C01 — Correct Stage-8 verification evidence | DONE |
| S8-01 — Model profile schemas + machine profile loader | DONE |
| S8-C02 — Harden ModelProfile base_url endpoint validation | DONE |
| S8-02 — Ollama transport + health + plain chat | DONE |
| S8-C03 — Harden Ollama health and JSON response validation | DONE |
| S8-03 — Ollama structured generation | DONE |
| S8-C04 — Correct S8-03 verification evidence and Stage-8 correction index | DONE |
| S8-04 — Ollama native tool-calling adapter | DONE |
| S8-05 — Ollama embeddings | NOT STARTED |
| S8-06 — Provider integration / error hardening / opt-in smoke coverage | NOT STARTED |
| S8-07 — Full Stage-8 historical review / completion | NOT STARTED |

Details: [`docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md`](docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md)

## Next stage

| Stage | Status |
|---|---|
| Stage 9 — Fast Agent | NOT STARTED |

## Maintenance gate before S6-06

| Task | Status |
|---|---|
| MNT-01 — Maintainability rules + baseline + ratchet | DONE |
| MNT-02 — Behavior-preserving Stage-6 hotspot decomposition | DONE |

## Maintenance gate before Stage 8

| Task | Status |
|---|---|
| MNT-03 — Harden GigaCode task scope/finalization/test-harness reliability | DONE |
| MNT-C01 — Strengthen test-harness opt-in enforcement | DONE |
| MNT-C02 — Make harness semantic detection precise | DONE |
| MNT-C03 — Finalize MNT-C02 committed evidence | DONE |

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
| `docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md` | Stage 6 detailed plan and history |
| `docs/stages/07_TOOL_REGISTRY_AND_EXECUTOR.md` | Stage 7 detailed plan and history |
| `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md` | Stage 8 detailed plan and history |