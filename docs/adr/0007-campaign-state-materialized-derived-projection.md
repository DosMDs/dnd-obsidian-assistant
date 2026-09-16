# ADR-0007: Campaign State as a materialized derived projection

- **Status:** Accepted
- **Date:** 2026-09-16

## Context

Stage 12 introduces Campaign State: compact current campaign memory for the
application. Stage 2 defined a dormant `CampaignState` domain schema
(`domain/campaign_state.py`) with semantic fields (`current_location`,
`active_quests`, `party_goals`, `important_npcs`, `upcoming_deadlines`,
`unresolved_threads`, `revision`) but no persistence, generation or consumer.
Existing architecture expects derived Stage-12 artifacts (`State/Party.md`,
`State/Active Quests.md`, `State/Active Threads.md`, `State/World State.md`) and
records derived indexes/caches as rebuildable from canonical Vault data
(`docs/stages/09_FAST_AGENT.md`, `docs/development/project-invariants.md`).

The Obsidian Vault is the only canonical campaign Source of Truth. Canonical
writes flow through model output → Python validation → ChangeSet → human review
→ fresh apply preflight → `VaultRepository`.

A review question arose: should Campaign State be a purely on-demand read model
with no durable artifact, or a persisted derived projection?

## Decision

Campaign State is a **materialized derived projection** persisted as
human-readable `State/*.md` files, produced by trusted Python derivation over
canonical evidence.

1. **Not canonical.** `State/*.md` is never a canonical aggregate and never a
   canonical mutation input. Canonical truth remains Vault entities,
   `_system/world_time.json`, raw session evidence, and successfully applied
   mutations.
2. **Discardable and rebuildable.** Deleting `State/*` loses nothing; rebuild
   restores the projection from source evidence.
3. **Deterministic MVP.** The MVP projection makes no model call. Stage-11
   model-generated prose is not a semantic source for current Campaign State in
   the MVP. Model-assisted narrative is a future extension only.
4. **Identity by fingerprint, not revision.** Projection identity/staleness use
   a deterministic input fingerprint over the exact canonical inputs. Entity
   `Revision` optimistic-concurrency semantics are not reused; there is no
   concurrency writer for a derived projection.
5. **Derived-state manifest.** A manifest binds the source-snapshot generation
   fingerprint, the file inventory, and per-file content hashes. Manifest schema
   v2 additionally binds a separate `render_version` (artifact-format identity,
   distinct from the source-input fingerprint). Read-time verification is
   **re-render based**, not hash-trust based: a generation is `CURRENT` only when
   a fresh source derivation has a matching fingerprint *and* the
   deterministically re-rendered expected bytes equal every stored artifact,
   which detects coordinated manual edits of both Markdown and manifest hash.
   The manifest is the publication commit marker (written last) at
   `State/.campaign-state-manifest.json`.
6. **Dedicated storage boundary.** Derived-State persistence uses a trusted
   derived-state store (path safety, atomic replacement, symlink safety).
   Application code does not receive arbitrary filesystem access. The canonical
   `VaultRepository` protocol is not reused for derived files. Each managed
   publication step reauthorizes the derived-state parent directory immediately
   before its atomic replacement, and the manifest is always written last.
7. **Honest semantics.** Session `touched_entities` means only that an entity
   was touched/referenced. It is not interpreted as current location, active
   quest, or important NPC. Recent-session references are named **recently
   touched / recently relevant entities**. Fields with no canonical/evidence
   source (current location, active quests, important NPCs, party goals,
   unresolved threads, upcoming deadlines) are unavailable and omitted, never
   fabricated.
8. **Visibility.** Internal derivation reads the trusted all-visibility
   `VaultRepository` boundary. `SearchService` remains player-only. A
   deterministic player-safe projection excludes DM/SYSTEM material.
9. **Calendar.** `CalendarService` remains the sole owner of campaign-time
   arithmetic. A missing `CalendarDefinition` yields the raw tick and no
   fabricated date.
10. **ChangeSet.** A successful apply does not itself make the projection
    stale. A successful apply may change canonical projection inputs; a fresh
    derivation then recomputes the source identity and a fingerprint mismatch
    determines staleness. An unrelated successful apply that leaves every bound
    source unchanged leaves the fingerprint unchanged. Unapplied/approved
    proposals do not affect derived state. No `CampaignState` ChangeSet
    operation is introduced.
11. **Player-facing State.** The human-readable `State/*.md` files are
    player-facing Vault material and must not contain DM/SYSTEM entity
    references; rendering admits only `Visibility.PLAYER` references. S12-02
    source collection remains internally all-visibility, and S12-04 owns the
    reusable player-safe consumer projection.
12. **No canonical audit for derived rebuilds.** Derived-state publication does
    not append canonical `_system/audit/audit.jsonl` records; State is
    non-canonical and rebuildable, and canonical audit must not be polluted by
    derived refreshes.

The purely on-demand-only alternative is rejected for Stage 12: it would not
provide the durable, human-readable compact memory the roadmap already reserves,
though on-demand derivation remains an internal fallback for a missing file.

## Consequences

### Positive

- Delivers the intended compact campaign memory without creating a second
  Source of Truth.
- Fully rebuildable; corruption/manual edits cannot corrupt canonical data.
- Deterministic and model-free in the MVP.
- Clear separation: Python owns selection/validation/visibility/identity and
  persistence; LLMs own nothing canonical.

### Trade-offs

- Adds a derived filesystem store requiring path/atomicity/symlink discipline.
- Requires staleness/manifest semantics and a rebuild operation.
- Some Stage-2 semantic fields remain unavailable until canonical evidence
  contracts exist.

## Supersedes

Nothing. The earlier S12-00 PLAN draft recommendation of a purely on-demand,
no-artifact design was not accepted and is not part of this decision.

## Update — S12-04 (2026-09-16)

S12-04 established the durable consumer/visibility decisions for Campaign
State without changing the core ADR:

1. **Single player-safe projection boundary.** A pure
   `project_player_campaign_state` is the one reusable boundary that admits
   `Visibility.PLAYER` references and exposes only `entity_id`, `entity_type`
   and `name`.  The internal all-visibility projection is not consumed directly
   by any model-facing path.
2. **Focused consumer, lazy ensure-current.** The Fast Agent consumes Campaign
   State only through a `PlayerCampaignStateProvider` that lazily rebuilds /
   repairs the materialized generation and returns the projected player-safe
   state.  This gives the S12-03 durable materialization a real consumer; there
   is no separate Campaign State rebuild CLI.
3. **Narrow failure normalization.** Only `WORLD_TIME_UNAVAILABLE` and a
   pre-publication source race degrade to unavailable memory; every other
   bounded source failure and all storage failures propagate fail-closed.
4. **Derived writes are not model authorization.** A READ-only `dnd ask` may
   maintain derived `State/*` files; this is trusted Python cache maintenance
   and does not mutate canonical data, append canonical audit, or grant model
   WRITE permission.
5. **No duplicate world time; explicit request identity.** The existing
   `current_world_tick` remains the only model-facing world-time field, and the
   changed deterministic USER contract is identified by `agent-v3` rather than
   silently retaining `agent-v2`.
