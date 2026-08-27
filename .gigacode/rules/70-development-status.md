---
apply: ALWAYS
mode: ALL
---
# Development status and stage discipline

- Read `DEVELOPMENT_STATUS.md` before planning implementation work.
- Treat it as the canonical source for the current stage and task state.
- Work within the current roadmap stage unless the user explicitly changes scope.
- Do not automatically advance to the next stage.
- Do not mark a task or stage `DONE` merely because code was generated.
- Completion requires required implementation, tests, successful relevant quality gates, and final diff review.
- If a task is blocked, record the blocker instead of bypassing architecture boundaries.
- Record significant architectural/workflow decisions as ADRs under `docs/adr/`.
- Git commits record concrete changes; Git tags record completed milestones.
- GigaCode is development tooling only and must not leak into application runtime dependencies.
