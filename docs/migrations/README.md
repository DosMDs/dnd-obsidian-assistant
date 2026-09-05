# Architecture/runtime migrations

This directory stores detailed plans/history/evidence for cross-cutting architecture migrations that do not fit cleanly into one ordinary stage task.

Current migration:

```text
001_PYDANTIC_AI_RUNTIME.md
```

Responsibility split:

- `DEVELOPMENT_STATUS.md` — compact current migration/task status;
- `docs/migrations/*.md` — detailed migration plan/history/evidence;
- `docs/adr/*.md` — architecture decision/rationale/outcome;
- `docs/stages/*.md` — stage-specific history and final stage review.

Do not duplicate full migration Final Reports in `DEVELOPMENT_STATUS.md`.
