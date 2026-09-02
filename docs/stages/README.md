# Stage documentation

## Responsibility split

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state |
| `docs/stages/NN_*.md` | Detailed per-stage plans, implementation history, correction records, review evidence, and completion records |

`DEVELOPMENT_STATUS.md` stores current roadmap state only — not detailed historical reports.

Detailed task/correction/review records belong in `docs/stages/`.

## Index

| Stage | Document |
|---|---|---|
| Stage 1 — Project skeleton + contracts | `01_PROJECT_SKELETON_AND_CONTRACTS.md` |
| Stage 2 — Domain schemas | `02_DOMAIN_SCHEMAS.md` |
| Stage 3 — Vault Repository | `03_VAULT_REPOSITORY.md` |
| Stage 4 — Calendar | `04_CALENDAR.md` |
| Stage 5 — Retrieval + Entity Resolution | `05_RETRIEVAL_AND_ENTITY_RESOLUTION.md` |
| Stage 6 — Session Runtime without LLM | `06_SESSION_RUNTIME_WITHOUT_LLM.md` |
| Stage 7 — Tool Registry and Executor | `07_TOOL_REGISTRY_AND_EXECUTOR.md` |

## Provenance

Detailed stage histories through Stage 5 were migrated from `DEVELOPMENT_STATUS.md`
after Stage-5 completion at commit `c73913845de19255cf588723ac0d57ad0d916cc9`.

This SHA provides provenance for the pre-normalization status archive in Git history.

Git history remains the ultimate historical record of the documentation itself.