# D&D Session Assistant — Development Status

**Last updated:** 2026-09-17 (TUI-00)
**Current milestone:** `v0.4.5-dev — Interactive TUI`
**Roadmap position:** Stage 12 `DONE`; Textual TUI Architecture Track `IN PROGRESS`; Stage 13 `NOT STARTED`; Stage 14 `NOT STARTED`
**Active work:** Textual TUI Architecture Track (next: TUI-01); Stage 13 — Bootstrap is gated on TUI-track completion
**Current branch:** `feat/textual-tui`

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
| 12. Campaign State | DONE | `docs/stages/12_CAMPAIGN_STATE.md` |
| Textual TUI Architecture Track (non-numbered) | IN PROGRESS | `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` |
| 13. Bootstrap | NOT STARTED | Gated on TUI-track completion (not `BLOCKED`) |
| 14. Evals / Hardening | NOT STARTED | — |

## Current work — Textual TUI Architecture Track

After Stage 12, the accepted product direction is a post-Stage-12 Textual TUI
presentation track, followed by Stage 13 and Stage 14. The track is recorded in
`docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md`; the architecture decision is
`docs/adr/0008-textual-tui-presentation-architecture.md`.

TUI-00 `DONE` — repository presentation architecture / ADR / track
alignment (docs-only). Dependency-ordered track: TUI-00 … TUI-06.

Textual is presentation-only. Obsidian Vault remains the only campaign Source of
Truth, Python owns trusted domain/application/storage logic, `ToolExecutor` is
the side-effect authorization boundary, and Typer remains supported for
scripting, administration, bootstrap, recovery, diagnostics and evals. UI
enabled/visible state is never authorization.

Stage 13 must not begin until the TUI track has completed normal implementation,
review, repository integration/status reconciliation and independent acceptance
(TUI-06). Stage 13 is `NOT STARTED` and gated, not `BLOCKED`.

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

S12-04 delivered the player-safe projection and its focused Fast-Agent
consumer. `application/campaign_state_projection.py` is the single pure
projection (PLAYER-only `entity_id`/`entity_type`/`name`);
`application/campaign_state_consumer.py` lazily rebuilds/repairs the derived
generation and projects it through a `PlayerCampaignStateProvider`.
`AgentContextBuilder` consumes only that capability, and
`build_agent_request` always serializes an explicit bounded `campaign_memory`
(`MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES` + UTF-8 `MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES`;
no partial ids/names). `current_world_tick` stays the only model-facing
world-time field; campaign memory stays distinct from `relevant_entities`.  The
changed deterministic USER contract is identified by `prompts/agent_v3.py`
(`PROMPT_VERSION = "agent-v3"`); `agent_v1`/`agent_v2` are preserved.  Only
`WORLD_TIME_UNAVAILABLE` and a pre-publication source race degrade to
unavailable memory; other source failures and storage failures propagate.  A
READ-only `dnd ask` may maintain derived `State/*` files (non-canonical cache
maintenance) without canonical mutation, canonical audit, or model WRITE
authorization.

S12-05 delivered the hardening / failure-injection pass over the accepted
S12-02→S12-04 pipeline (no new semantics, consumer, CLI, model call or
dependency). Hidden-data noninterference is now proven by equality, not sentinel
absence: the all-visibility generation fingerprint was removed from PLAYER-facing
`State/World State.md` (render version bumped `"2"`→`"3"`; derivation version,
manifest schema and `agent-v3` unchanged; render `"2"` is `OUTDATED`). The
dot-prefixed manifest is documented as an **internal** integrity/freshness
artifact outside the PLAYER equality contract (no confidentiality claim).
`ObsidianDerivedStateStore` now applies full existing-`State/` authorization
(not symlink, not junction/reparse, real directory, resolved containment) on
every read and before every managed replacement, closing a Windows-junction
escape; hard links are accepted because `os.replace` swaps the directory entry.
Deterministic interleavings, reader races, publication-phase failure injection
and cross-generation replay never produce a false `CURRENT`, so the no-lock MVP
is retained. Lazy provider repairs `MISSING/STALE/CORRUPT/OUTDATED`; source
failures before `publish()` write nothing; audit taxonomy unchanged.

S12-06 `DONE` — full Stage-12 historical review/completion. The complete
S12-00→S12-05 range was reviewed (architecture, domain/schema, source
collection, fingerprint identity, materialization/path authority, status/
concurrency, PLAYER noninterference, Fast-Agent/agent-v3, search isolation,
ChangeSet isolation, calendar, line counts). Three literal completion
regressions were added with no production-code change: both-artifact
coordinated tamper (both Markdown artifacts edited, both manifest hashes
recomputed) is `CORRUPT`, never `CURRENT`; a manifest `os.replace` failure
through the real shared `atomic_write_text` leaves no temp orphan, preserves
the previous manifest bytes and never yields `CURRENT`; and an unrelated
`State/My Notes.md` survives a real source-changed rebuild while the managed
generation stays `CURRENT`. Stage 12 is `DONE`; the Textual TUI Architecture
Track is the next roadmap work (Stage 13 follows after the track completion
gate).
A successful apply is not itself an independent staleness signal; a fresh
derivation's fingerprint comparison determines it.

## Current blockers and prerequisites

```text
No confirmed blocker for Stage 13.
Sequencing gate (not a blocker): Stage 13 must not begin until the Textual TUI
  Architecture Track completes implementation, review, integration/status
  reconciliation and independent acceptance (TUI-06).
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
S12-04 DONE — visibility projection + focused Fast-Agent consumer integration
S12-05 DONE — hardening / failure injection / cross-platform safety
S12-06 DONE — full Stage-12 review / completion
TUI-00 DONE — repository presentation architecture / ADR / track alignment (docs-only)
Next: TUI-01 — Textual dependency qualification + minimal spike
Stage 13 — Bootstrap (NOT STARTED; gated on TUI-track completion, not BLOCKED)
```

## Documentation map

| File | Role |
|---|---|
| `DEVELOPMENT_STATUS.md` | Compact canonical current roadmap state |
| `docs/stages/12_CAMPAIGN_STATE.md` | Stage-12 architecture, task map, acceptance evidence |
| `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` | Textual TUI track plan/history/evidence (TUI-00…TUI-06) |
| `docs/adr/0007-campaign-state-materialized-derived-projection.md` | Campaign State architecture decision |
| `docs/adr/0008-textual-tui-presentation-architecture.md` | Textual TUI presentation architecture decision |
| `docs/stages/11_POST_SESSION_PROCESSOR.md` | Stage-11 architecture/history |
| `docs/stages/10_CHANGESET.md` | Stage-10 architecture/history |
| `docs/adr/0006-changeset-review-apply-boundary.md` | ChangeSet review/apply decision |
| `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` | PAIM plan/history/evidence |
| `docs/adr/0003-pydantic-ai-runtime-migration.md` | Migration architecture/rollback decision |
| `AGENTS.md` | Always-on OpenCode development invariants |
| `docs/development/` | Durable development policies (lazy) |
