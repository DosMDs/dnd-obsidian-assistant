# D&D Session Assistant — Development Status

**Last updated:** 2026-09-16 (S12-03 + S12-03-C1)
**Current milestone:** `v0.3-dev — Fast Assistant`
**Roadmap position:** Stage 11 `DONE`; Stage 12 `IN PROGRESS`
**Active stage:** Stage 12 — Campaign State (S12-04 next)
**Current branch:** `feat/campaign-state`

## Status model

Use only: `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `DONE`.

A task is not `DONE` merely because code was generated. Completion requires the
requested implementation/documentation, relevant checks, final diff review and,
when required, commit/push/upstream verification.

This file stores **current roadmap state**, not a detailed history. Detailed
records live in `docs/stages/`, `docs/migrations/`, `docs/adr/` and Git.

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
| 12. Campaign State | IN PROGRESS | `docs/stages/12_CAMPAIGN_STATE.md` |
| 13. Bootstrap | NOT STARTED | — |
| 14. Evals / Hardening | NOT STARTED | — |

## Current state — Stage 12

S12-00 `DONE` — architecture/contracts/kickoff. S12-01 `DONE` — typed
derived-state contract. S12-02 `DONE` — deterministic, read-only source
collection / evidence binding. Campaign State is a **materialized derived projection**
persisted as human-readable `State/*.md`, produced by trusted Python derivation
over canonical Vault/session/world-time evidence. It is not a canonical
aggregate, is discardable/rebuildable, has no canonical mutation surface and no
model call in the MVP. Architecture:
`docs/adr/0007-campaign-state-materialized-derived-projection.md` and
`docs/stages/12_CAMPAIGN_STATE.md`.

S12-01 delivered `domain/campaign_state.py` (`CampaignState` v2 + recently
touched reference + input identity + manifest DTOs) and
`application/campaign_state_identity.py` (canonical source-snapshot
fingerprint). The fingerprint binds source revisions, the selection limit and
the complete `CalendarDefinition`; raw session events are excluded. No storage
I/O, materialization, source collection or model call was introduced.

S12-02 delivered `application/campaign_state_source.py`: a read-only,
deterministic, model-free collector that selects eligible completed sessions,
validates touched evidence, binds current canonical entities by exact
`EntityId`, reads canonical world time, optionally binds a supplied calendar
definition, and returns `CampaignState` plus its full
`CampaignStateInputIdentity`/fingerprint. S12-02-C1 corrected completed-session
lifecycle validation to not require monotonic in-session world ticks. Still no
persistence/render/model.

Fields with no canonical/evidence source (current location, active quests,
important NPCs, party goals, unresolved threads, upcoming deadlines) are
**unavailable** and omitted; session `touched_entities` is reported only as
recently touched, never as current/active/important.

S12-03 delivered physical derived-state persistence:
`State/World State.md`, `State/Recently Touched.md` and
`State/.campaign-state-manifest.json` (manifest written last). A fresh
pre-publication re-derivation gates publication (fingerprint mismatch aborts,
zero writes); read-time verification safely classifies
`MISSING`/`OUTDATED`/`CORRUPT`/`UNVERIFIABLE`/`STALE`/`CURRENT`, requiring an
exact deterministic re-render byte match (manifest hashes are not a trust
anchor). Manifest schema v2 separates `render_version` from the source-input
fingerprint. State files are player-facing: DM/SYSTEM references are excluded
from rendered bytes; internal source collection stays all-visibility. Rebuilds
append no canonical audit. No model call, no canonical ChangeSet operation and
no CLI were introduced.

Next: S12-04 — visibility projection + focused consumer integration. A
successful apply is not itself an independent staleness signal; a fresh
derivation's fingerprint comparison determines it.

## Current blockers and prerequisites

```text
No confirmed blocker for Stage 12.
Known source gaps (accepted limitations, not blockers):
  TimelineEvent has no persistence/collection -> upcoming_deadlines unavailable.
  No canonical CalendarDefinition source -> game date omitted unless supplied.
  No canonical status/importance/selection vocabulary for quests/NPCs/location.
```

## Maintainability constraints

```text
tests/contract/test_boundaries.py is at the 1000-line ceiling (zero headroom);
add new boundary coverage in a focused new test module instead.
Production modules: hard 700-line limit with pinned legacy exceptions.
cli/changeset.py (666) is close to the production ceiling.
Symlink safety tests may skip on Windows hosts without symlink capability.
Parent-directory fsync is not implemented; durable-write evidence proves
process-crash (not machine/power-loss) semantics of newly created entries.
```

## Operational invariants

- Obsidian Vault is the only campaign Source of Truth; all Vault writes flow
  through `ToolExecutor` / domain-application services / `VaultRepository`.
- LLM/framework output is untrusted until validated by Python; framework
  exposure/filtering/approval is not an authorization boundary.
- Domain/storage must not depend on Ollama, Pydantic AI or any concrete
  provider; runtime LLM/agent code never receives arbitrary Vault filesystem or
  shell access.
- `SearchService` is player-visible only; internal derivation uses the trusted
  all-visibility `VaultRepository` read boundary.
- Derived stores (FTS index, and later `State/*.md`) are always rebuildable from
  canonical Vault/raw data.
- Production `dnd ask` uses the Pydantic AI runtime; project-owned boundaries
  (`ToolExecutor`, policy, authorization, Vault) remain custom. Details:
  `docs/adr/0003-pydantic-ai-runtime-migration.md`.
- Quality gates for any change: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pyright` (0 errors). A green pytest
  does not override Pyright failure.

## Immediate next step

```text
S12-00 DONE — architecture/contracts/kickoff
S12-01 DONE — typed derived-state contract (CampaignState v2 + manifest/fingerprint)
S12-02 DONE — deterministic source collection / evidence binding
S12-03 DONE — materialization + rebuild/staleness/corruption
S12-04 Next — visibility projection + focused consumer integration
S12-05      — hardening / failure injection
S12-06      — full Stage-12 review / completion
```

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state |
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/stages/11_POST_SESSION_PROCESSOR.md` | Stage-11 architecture/history |
| `docs/stages/10_CHANGESET.md` | Stage-10 architecture/history |
| `docs/adr/0006-changeset-review-apply-boundary.md` | ChangeSet review/apply decision |
| `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` | PAIM plan/history/evidence |
| `docs/adr/0003-pydantic-ai-runtime-migration.md` | Migration architecture/rollback decision |
| `AGENTS.md` | Always-on OpenCode development invariants |
| `docs/development/` | Durable development policies (lazy) |
