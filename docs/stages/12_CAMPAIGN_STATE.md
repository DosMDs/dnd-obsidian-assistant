# Stage 12 — Campaign State

## Objective

Provide **compact current campaign memory** for the application by materializing
a trusted, deterministic, discardable **derived projection** of canonical
campaign evidence into human-readable `State/*.md` files.

Stage 12 does not introduce a new canonical aggregate. It derives a projection
over sources that are already canonical and rebuilds it on demand.

This document is the S12-00 architecture/contracts/kickoff record. Production
schema and services begin in S12-01.

## Architectural position

```text
canonical Vault entities / world time / raw session evidence
        │  (trusted Python reads)
        ▼
trusted deterministic derivation + validation + visibility
        │
        ▼
materialized derived projection:  State/*.md  (+ derived-state manifest)
```

- Canonical Source of Truth is unchanged: Obsidian Vault entities,
  `_system/world_time.json`, raw session metadata/events, and successfully
  applied canonical mutations.
- `State/*.md` is **derived memory**, never canonical truth, never a canonical
  mutation surface, and safe to delete.
- LLMs are not part of the Stage-12 MVP contract (see §6).

## 1. Derived, not canonical

`State/*.md` must never become an independent canonical mutation surface.

- The only writers are trusted Python services. No model and no State-file
  writer may bypass trusted Python ownership.
- No `CampaignState` ChangeSet operation is introduced merely to mutate a
  derived projection.
- Canonical writes continue to flow only through the model-output → Python
  validation → ChangeSet → human review → fresh apply preflight →
  `VaultRepository` path. Campaign State is not that path.
- Derived-State persistence uses a **dedicated trusted storage/repository
  boundary** (a derived-state store comparable in discipline to
  `_system/changesets`). Application code does not receive arbitrary filesystem
  access, and the canonical `VaultRepository` protocol is not reused for
  derived files.
- Every derived projection is fully discardable: deleting `State/*` loses no
  canonical information and rebuild restores the projection from source
  evidence.
- A human edit to a `State/*.md` file changes its content hash relative to the
  derived-state manifest, so it is detected as tampered/stale and overwritten
  on rebuild. A manual edit can never silently become canonical input.

## 2. Honest semantics — recently touched is not current/active/important

Stage 2 introduced a dormant `CampaignState` schema with semantic fields
(`current_location`, `active_quests`, `important_npcs`, `party_goals`,
`upcoming_deadlines`, `unresolved_threads`). Those fields imply semantics that
**current canonical evidence does not establish**.

In particular, session `touched_entities` means only that an entity was
**touched/referenced during a session**. It does **not** mean:

```text
touched location → current_location        (rejected)
touched quest    → active_quest            (rejected)
touched NPC      → important_npc           (rejected)
```

Stage 12 therefore names any recent-session reference honestly as **recently
touched / recently relevant entities**. It does not invent status vocabularies,
importance, current location, goals, threads, or deadlines. Where no
canonical/evidence source proves a field's actual meaning, the field is
**unavailable** (omitted), never fabricated.

The existence of a field in the Stage-2 schema is **not** evidence that it is
safely derivable. The Stage-2 schema is treated as an input hypothesis, not an
accepted Stage-12 design.

## 3. Semantic ownership matrix

Legend: derivable = deterministic from current accepted evidence.

| Semantic area | Source | Derivable today | Rule / prerequisite | Visibility | Provenance |
|---|---|---|---|---|---|
| current world time / date | `CurrentWorldTime` + `CalendarService` | tick yes; date only with a supplied `CalendarDefinition` | read canonical tick; `GameDate` via `CalendarService`; **omit date** when no definition | internal + player (tick/date) | world_time revision + `calendar_id` |
| recent session contribution | session metadata + `events.jsonl` | yes | last N completed sessions; ordered touched entity IDs + recent events, projected as **recently touched** | internal; player subset only | session id + revision |
| recently touched entities | entity IDs from recent accepted sessions | yes | resolve each reference by exact `EntityId` via `VaultRepository.get_entity`; validate existence/type; **labeled recent** | internal; player projection only for PLAYER entities | source session id(s) + entity revision |
| current location | none canonical | **no** | no canonical "current location" marker; a touched location is not a current location | n/a | n/a |
| active quests | none canonical | **no** | no fixed quest-status/"active" vocabulary; touched quests are not active quests | n/a | n/a |
| important NPCs | none canonical | **no** | no canonical importance/relevance marker | n/a | n/a |
| party goals | none canonical | **no** | no canonical owner; model prose is out of MVP scope | n/a | n/a |
| unresolved threads | none canonical | **no** | no canonical owner; model prose is out of MVP scope | n/a | n/a |
| upcoming deadlines | `TimelineEvent` schema only | **no** | prerequisite: canonical TimelineEvent persistence/collection + `CalendarDefinition`; not pulled into Stage 12 | n/a | n/a |

A field marked unavailable is explicitly omitted from the projection. Missing
semantic evidence must never produce a synthesized value.

## 4. Materialized projection identity

The projection is one logically consistent generation:

- **Authoritative inputs:** entities (id + revision, all visibility), current
  world time (tick + revision), session metadata (id + revision,
  `touched_entities`), and `calendar_id` when available.
- **Input fingerprint:** deterministic SHA-256 over a canonical serialization of
  exactly those inputs, mirroring the Stage-11 input-fingerprint approach. It is
  the projection's identity and staleness key.
- **Manifest:** a derived-state manifest binds the generation fingerprint, the
  rendered file inventory, and each file's content hash.

Entity `Revision` semantics are **not** reused. There is no optimistic
concurrency writer for a derived projection; a fingerprint manifest is the
correct identity mechanism.

## 5. Rebuild, staleness, corruption, manual edits

- **Stale when:** the current-input fingerprint differs from the manifest
  fingerprint; a bound entity/session/world-time revision changed; or a
  successful canonical apply occurred.
- **Missing State:** consumers report the projection as unavailable; an
  explicit rebuild materializes it.
- **Corrupt State / manifest:** fail closed with `StorageError`; never parsed as
  canonical; rebuild overwrites.
- **After canonical entity / world-time / session change:** stale → rebuild.
- **After a successful ChangeSet apply:** stale → rebuild reflects the new
  canonical result.
- **After an unapplied or merely approved ChangeSet:** no effect. Persisted
  proposals under `_system/changesets/` are not inputs and cannot alter State.
- **After manual/external edit:** content hash mismatch vs manifest → treated as
  stale/tampered; overwritten on rebuild; never canonical.
- **Atomic replacement:** each file is written via temporary file + atomic
  replacement after validation; the manifest is written after file
  replacements, so a half-finished rebuild is detectable and never consumed as
  current.
- **Rebuild boundary:** an application service orchestrates derivation and
  delegates persistence to the derived-state store. No direct filesystem access
  in application logic.
- **Rebuild failure halfway:** the manifest does not match current inputs, so
  the old/partial generation is classified stale; consumers either use the last
  fully verified generation or report unavailable.

Byte-for-byte determinism is claimed only while the projection is fully
deterministic. If a model-assisted extension is ever accepted, the contract
becomes provenance/reproducibility (same input fingerprint + model profile +
prompt version + recorded output hash), not false byte equality.

## 6. Deterministic MVP vs future model assistance

```text
Python-owned (MVP, required)
  source selection; reference/entity validation; identity; visibility filtering;
  calendar arithmetic; rendering; input fingerprint; content hashing;
  staleness detection; atomic materialization; rebuild orchestration.
```

- The Stage-12 MVP is fully deterministic and makes **no model call**.
- Stage-11 model-generated Summary/Recap/extraction prose is **not** used as a
  semantic source for current Campaign State in the MVP.
- Model-assisted derived narrative is an explicit **future extension** only, and
  must not participate in the initial deterministic contract. If later accepted:
  it operates only over trusted prepared evidence; output is derived, never
  canon; provenance binds model profile + prompt version + input fingerprint;
  player projections exclude DM/SYSTEM material; model output is never treated
  as evidence that a canonical fact exists.

## 7. Visibility boundary

- Internal derivation reads the trusted all-visibility boundary
  (`VaultRepository.list_entities` / `get_entity`), matching the accepted
  Stage-11 post-session context boundary.
- `SearchService` remains **player-visible only** and is not weakened or used
  as an internal all-visibility source.
- A deterministic **player-safe projection** admits only `Visibility.PLAYER`
  values; DM/SYSTEM material must never enter it, including by stable-ID
  reference.

## 8. CalendarService authority

- `CalendarService` remains the sole deterministic owner of campaign-time
  arithmetic.
- Campaign State reads the canonical `WorldTick` from `WorldTimeRepository` and
  converts through `CalendarService`.
- When no `CalendarDefinition` is available, the raw canonical tick may remain
  available but a `GameDate` is **never fabricated**.

## 9. ChangeSet interaction

Campaign State observes canonical change only after a **successful** apply.

```text
proposal persisted        → no derived-state change
proposal approved         → no derived-state change
apply attempted/failed    → no derived-state change
apply succeeded           → existing projection becomes stale / rebuild eligible
canonical Vault changed   → derived inputs change → fingerprint mismatch
```

No recompute-after-apply hook and no `CampaignState` ChangeSet operation are
introduced. State is rebuilt lazily from current canonical reads. Stage-10's
operation set and Stage-11's accepted producer subset are not expanded.

## 10. `CampaignState` v1 reconciliation

- `domain/campaign_state.py` v1 is dormant production dead code: it has no
  reader, writer, path, serializer, or production consumer; only unit tests and
  a static fixture reference it.
- Stage 12 will replace/adjust it (in S12-01, not in S12-00) to become the typed
  in-memory materialized-projection contract (`schema_version = 2`), with
  `revision` replaced by the input fingerprint and with honest
  recently-touched/unavailable semantics.
- No v1 data migration is required because no production v1 artifact exists.
- Any schema change is an implementation task; S12-00 records the decision only.

## 11. Non-goals

```text
new canonical aggregate or canonical mutation surface for Campaign State
model/LLM semantic source in the MVP
TimelineEvent persistence (would be needed for upcoming deadlines)
CalendarDefinition persistence
Bootstrap / import (Stage 13)
evals / final hardening (Stage 14)
embeddings / vector DB / graph DB / RAG
```

## 12. Task map

```text
S12-00  architecture/contracts/kickoff                          (docs-only BUILD)
S12-01  typed derived-state contract (CampaignState v2 + manifest/fingerprint)
S12-02  deterministic source collection / evidence binding
S12-03  materialization + rebuild/staleness/corruption (State/*.md)
S12-04  visibility projection + focused consumer integration
S12-05  hardening / failure injection
S12-06  full Stage-12 review / completion
```

- **S12-00** — architecture/contracts/kickoff; docs only. Smallest first BUILD
  increment; completed by this record.
- **S12-01** — smallest first BUILD task after S12-00: typed derived-state
  contract + manifest/fingerprint; domain + tests.
- **S12-02** — deterministic collection/binding of canonical entities, sessions,
  world time; fail-closed reference handling; application + tests.
- **S12-03** — derived-state store + materialization service; atomic writes;
  staleness/corruption/rebuild; application + storage + tests.
- **S12-04** — explicit player-safe projection + one focused consumer (e.g. a
  read-only query); other consumers deferred.
- **S12-05** — failure injection, tamper/manual-edit, DM/SYSTEM leakage,
  Windows/macOS path and Unicode hardening.
- **S12-06** — review/completion.

Deferred beyond Stage 12: model-assisted narrative for party goals/unresolved
threads, `upcoming_deadlines` (needs TimelineEvent persistence), canonical
Location/Quest/NPC selection vocabularies, Bootstrap (Stage 13), evals
(Stage 14).

## 13. Acceptance → future evidence

| Criterion | Future literal evidence |
|---|---|
| canonical mutation → rebuild reflects it | mutate an entity via `VaultRepository`; rebuild; assert State equals new canonical values |
| delete all State files → rebuild | delete `State/*`; rebuild; assert deterministic byte/semantic equality (no model in MVP) |
| unapplied ChangeSet → no State change | persist an unapplied proposal; assert manifest fingerprint and State bytes unchanged |
| successful apply → stale / rebuild reflects canon | apply a ChangeSet; assert fingerprint mismatch (stale), then rebuild reflects applied entity state |
| manual/corrupt State artifact → never canonical | edit/corrupt a State file; assert content-hash mismatch → stale/tampered; no canonical read path consumes it; rebuild overwrites |
| DM/SYSTEM evidence → absent from player projection | DM/SYSTEM fixture; internal projection may contain it, player projection negative assertion |
| missing semantic evidence → omitted, never fabricated | no sessions / no location; field omitted or explicitly unavailable |
| missing CalendarDefinition → no fabricated GameDate | absent definition: raw tick present, game date omitted; explicit error/omission, never synthesized |
| no model requirement in MVP | Stage-12 tests use no Ollama/model double; import-boundary assertions |

A green test without the matching semantic assertion does not satisfy a row.

## 14. S12-00 record

```text
Task:              S12-00 — Campaign State Architecture / Contracts / Stage Kickoff
Routing:           PLAN_REQUIRED -> accepted corrected PLAN -> BUILD (documentation-only)
Branch:            feat/campaign-state
Baseline:          main @ aec41021f10f0a15c7eb7ef1f2ca83aa87fdbee4
Scope:             docs/stages/12_CAMPAIGN_STATE.md (new)
                   docs/adr/0007-campaign-state-materialized-derived-projection.md (new)
                   DEVELOPMENT_STATUS.md (compacted)
No production/test/schema/dependency changes.
```
