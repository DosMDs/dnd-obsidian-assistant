# D&D Session Assistant — Development Status

**Last updated:** 2026-09-15 (Stage-11 kickoff)
**Current milestone:** `v0.3-dev — Fast Assistant`
**Roadmap position:** Stage 9 `DONE`; Stage 10 `DONE`; Stage 11 `IN PROGRESS`
**Active stage:** Stage 11 — Post-session Processor
**Active migration:** PAIM — `ACCEPTED`, complete
**Current branch:** `feat/post-session-processor`
**Reference main SHA (PAIM behavioral/rollback reference):** `f424a0f659afd5f8bcbce55c4d280cc8e621133f`

## Status model

Use only:

- `NOT STARTED`
- `IN PROGRESS`
- `BLOCKED`
- `DONE`

A task is not `DONE` merely because code was generated. Completion requires the
implementation/documentation requested, relevant checks, final diff review,
commit, push and upstream verification according to repository policy.

## Policy

This file stores **current roadmap state**, not a detailed historical report.

Detailed records belong in:

```text
docs/stages/       stage plan/history/evidence
docs/migrations/   migration plan/history/evidence
docs/adr/          architecture decisions
```

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
| 11. Post-session Processor | IN PROGRESS | `docs/stages/11_POST_SESSION_PROCESSOR.md` |
| 12. Campaign State | NOT STARTED | — |
| 13. Bootstrap | NOT STARTED | — |
| 14. Evals / Hardening | NOT STARTED | — |

## Current state

### Stage 10 — ChangeSet `DONE`

S10-00..S10-07 all `DONE`; completion verdict `STAGE10_READY_FOR_COMPLETION`,
merge readiness `MERGE_READY`. Stage 10 delivered the trusted ChangeSet pipeline:

```text
domain/changeset.py                    immutable ChangeSet/operation schemas
application/changeset_validation.py    pure repository-backed validator / whole-batch preflight
application/changeset_review.py        review DTOs, SHA-256 fingerprint, approval/rejection binding
application/changeset_apply.py         applier with fresh preflight, revision/conflict safety
application/changeset_store.py         durable proposal/approval artifact store
application/changeset_status.py        applicability gate + append-only apply-attempt audit
storage/changeset_store.py             artifact persistence
cli/changeset.py                       `dnd changeset` save/review/approve/reject/apply/status
```

Architecture decision: `docs/adr/0006-changeset-review-apply-boundary.md`.
Detailed task history/evidence: `docs/stages/10_CHANGESET.md`.

### R1 recovery-ownership known limitation — resolved

R1 (classification B) was the Stage-11 prerequisite that an intent-only ChangeSet
audit record with a real `session_ref` could enter global session-recovery
`unresolved_audit_intent` blocking with no repair action. Resolved on branch
`feat/r1-changeset-recovery-ownership` by the application-owned partition
`application/changeset_recovery.py`, which narrows **blocking scope only**:

- `SessionRecoveryService.inspect_runtime()` still returns the complete raw report;
- `inspect_runtime_partition()` separates `blocking` from `externally_owned` for
  mutation preflight consumers only;
- `storage/session_recovery/*` is unchanged; the affected ChangeSet stays
  permanently UNCONFIRMED/blocked; no repair/replay/resume/rollback command exists.

Resolution verdict `R1_RECOVERY_READY`; evidence in
`docs/stages/10_CHANGESET.md` (R1 resolution section).

### Stage 11 — Post-session Processor `IN PROGRESS`

S11-00 `DONE` — architecture/contracts/kickoff accepted
(`S11_ARCHITECTURE_READY`). Detailed architecture, invariants, task map and
evidence plan: `docs/stages/11_POST_SESSION_PROCESSOR.md`. Next task:
`S11-01 — post-session input + durable processing schemas`. No production
Stage-11 runtime code exists yet.

## Accepted reference baseline

`f424a0f659afd5f8bcbce55c4d280cc8e621133f` is the behavioral/rollback reference
for the PAIM migration. Git/main provides that reference; no duplicate production
runtime is retained for rollback.

## Production architecture (current)

```text
CLI (cli/ask.py)
→ PydanticAIAgentRuntime (application/pydantic_ai_agent_runtime.py)
→ DndAgentRunPreparer / DndAgentPolicy
→ PydanticAIToolBridge
→ ToolExecutor (tools/executor.py)
→ services
→ VaultRepository
```

PAIM-15 verdict `ACCEPTED`: production `dnd ask` uses the Pydantic AI runtime;
`ToolExecutor`, `DndAgentPolicy`, authorization, exposure policy and Vault
boundaries remain project-owned. The superseded custom/reference agent runtime
(`FastAgent`, `AgentLoop`, `AgentToolExecutionService`) was retired by
`PAIM-RETIRE-01`. `ModelGateway` + native Ollama remain non-agent provider
infrastructure. `tests/contract/test_boundaries.py` enforces the accepted
dependency shape.

Details: `docs/migrations/001_PYDANTIC_AI_RUNTIME.md`,
`docs/adr/0003-pydantic-ai-runtime-migration.md`.

## Current blockers and prerequisites

```text
No confirmed blocker for Stage 11 start.
R1 Stage-11 prerequisite resolved by application-owned ownership partition.
No model-generated ChangeSet producer exists yet (Stage 11 does not start it).
Stage 11 is in progress; next task is S11-01.
```

## Known limitations affecting future work

```text
tests/contract/test_boundaries.py is at the 1000-line ceiling (zero headroom).
cli/changeset.py (666 lines) is close to the 700-line production ceiling.
Symlink safety tests may skip on Windows hosts without symlink capability;
no in-repo CI evidence guarantees symlink-capable execution.
```

## Immediate next step

```text
Stage 10 — ChangeSet (DONE)
Stage 11 — Post-session Processor (IN PROGRESS)
  S11-00 DONE — architecture/contracts/kickoff
  S11-01 NOT STARTED — post-session input + durable processing schemas
```

## Operational invariants

- Obsidian Vault is the only campaign Source of Truth; all Vault writes flow
  through `ToolExecutor` / domain-application services / `VaultRepository`.
- LLM/framework output is untrusted until validated by Python. Framework tool
  exposure/filtering/approval is not an authorization boundary.
- Domain/storage must not depend on Ollama, Pydantic AI or any concrete
  provider. Runtime LLM/agent code must never receive arbitrary filesystem or
  shell access to the Vault.
- Quality gates for any change: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv run pyright` with 0 errors. A green
  pytest does not override Pyright failure.

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state |
| `docs/stages/09_FAST_AGENT.md` | Detailed Stage-9 history/reference behavior |
| `docs/stages/10_CHANGESET.md` | Stage-10 architecture record, task map, R1 resolution |
| `docs/stages/11_POST_SESSION_PROCESSOR.md` | Stage-11 architecture, invariants, task map, evidence plan |
| `docs/adr/0006-changeset-review-apply-boundary.md` | ChangeSet review/apply architecture decision |
| `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` | PAIM task plan/history/evidence |
| `docs/adr/0003-pydantic-ai-runtime-migration.md` | Migration architecture/rollback decision |
| `AGENTS.md` | Always-on OpenCode development invariants |
| `.opencode/skills/pydantic-ai-migration/SKILL.md` | PAIM implementation/review workflow |
| `docs/migrations/002_OPENCODE_DEVELOPMENT_TOOLING.md` | OpenCode development-tooling cutover record |
