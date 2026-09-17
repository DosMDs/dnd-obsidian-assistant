# Stage documentation

## Responsibility split

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap and migration-task state |
| `docs/stages/NN_*.md` | Detailed per-stage plans, implementation history, correction records, review evidence, and completion records |
| `docs/migrations/*.md` | Detailed cross-cutting architecture/runtime migration plan, task history, qualification evidence, and final migration review |
| `docs/adr/*.md` | Significant architecture/workflow decisions, rationale, constraints, and accepted/rejected outcomes |

`DEVELOPMENT_STATUS.md` stores current state only — not detailed historical reports.

Detailed ordinary stage records belong in `docs/stages/`. Cross-cutting migration evidence belongs in `docs/migrations/`; architecture decisions belong in `docs/adr/`. Do not duplicate full Final Reports across these surfaces.

## Index

| Stage | Document |
|---|---|
| Stage 1 — Project skeleton + contracts | `01_PROJECT_SKELETON_AND_CONTRACTS.md` |
| Stage 2 — Domain schemas | `02_DOMAIN_SCHEMAS.md` |
| Stage 3 — Vault Repository | `03_VAULT_REPOSITORY.md` |
| Stage 4 — Calendar | `04_CALENDAR.md` |
| Stage 5 — Retrieval + Entity Resolution | `05_RETRIEVAL_AND_ENTITY_RESOLUTION.md` |
| Stage 6 — Session Runtime without LLM | `06_SESSION_RUNTIME_WITHOUT_LLM.md` |
| Stage 7 — Tool Registry and Executor | `07_TOOL_REGISTRY_AND_EXECUTOR.md` |
| Stage 8 — Model Gateway / Ollama | `08_MODEL_GATEWAY_AND_OLLAMA.md` |
| Stage 9 — Fast Agent | `09_FAST_AGENT.md` |
| Stage 10 — ChangeSet | `10_CHANGESET.md` |
| Stage 11 — Post-session Processor | `11_POST_SESSION_PROCESSOR.md` |
| Stage 12 — Campaign State | `12_CAMPAIGN_STATE.md` |
| Textual TUI Architecture Track (non-numbered) | `TUI_TEXTUAL_PRESENTATION_TRACK.md` |

## Cross-cutting migrations

Cross-cutting architecture/runtime work that does not belong to a single stage is
recorded under `docs/migrations/`, with the corresponding decision under
`docs/adr/`. Migration records are historical plan/evidence; current roadmap and
migration status is in `DEVELOPMENT_STATUS.md`.

## Provenance

Detailed stage histories through Stage 5 were migrated from `DEVELOPMENT_STATUS.md` after Stage-5 completion at commit `c73913845de19255cf588723ac0d57ad0d916cc9`.

This SHA provides provenance for the pre-normalization status archive in Git history. Git history remains the ultimate historical record of the documentation itself.
