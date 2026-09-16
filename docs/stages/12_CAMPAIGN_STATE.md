# Stage 12 — Campaign State

## Objective

Provide **compact current campaign memory** for the application by materializing
a trusted, deterministic, discardable **derived projection** of canonical
campaign evidence into human-readable `State/*.md` files.

Stage 12 does not introduce a new canonical aggregate. It derives a projection
over sources that are already canonical and rebuilds it on demand.

This document is the S12-00 architecture/contracts/kickoff record, with the
S12-01 typed-contract decision/evidence appended (§4, §10, §15).  Production
source collection and materialization services begin in S12-02/S12-03.

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
| current world time / date | `CurrentWorldTime` + `CalendarService` | tick yes; date only with a supplied `CalendarDefinition` | read canonical tick; `GameDate` via `CalendarService`; **omit date** when no definition | internal + player (tick/date) | world_time revision + complete `CalendarDefinition` fingerprint |
| recent session contribution | completed session metadata (`touched_entities`) | yes | selected completed sessions; touched entity IDs resolved to canonical entities and projected as **recently touched** | internal; player subset only | session id + revision |
| recently touched entities | entity IDs from recent accepted sessions | yes | resolve each reference by exact `EntityId` via `VaultRepository.get_entity`; validate existence/type; **labeled recent** | internal; player projection only for PLAYER entities | source session id(s) + entity revision |
| raw session events | `events.jsonl` | **no** (S12-01/S12-02) | session metadata revision does **not** bind the exact event stream (`append_event` appends without bumping metadata revision); events are excluded from the source-snapshot identity | n/a | n/a |
| current location | none canonical | **no** | no canonical "current location" marker; a touched location is not a current location | n/a | n/a |
| active quests | none canonical | **no** | no fixed quest-status/"active" vocabulary; touched quests are not active quests | n/a | n/a |
| important NPCs | none canonical | **no** | no canonical importance/relevance marker | n/a | n/a |
| party goals | none canonical | **no** | no canonical owner; model prose is out of MVP scope | n/a | n/a |
| unresolved threads | none canonical | **no** | no canonical owner; model prose is out of MVP scope | n/a | n/a |
| upcoming deadlines | `TimelineEvent` schema only | **no** | prerequisite: canonical TimelineEvent persistence/collection + `CalendarDefinition`; not pulled into Stage 12 | n/a | n/a |

A field marked unavailable is explicitly omitted from the projection. Missing
semantic evidence must never produce a synthesized value.

## 4. Materialized projection identity (S12-01 contract)

The projection is one logically consistent generation.  Its identity is a
**source-snapshot fingerprint**: the deterministic SHA-256 of the exact
canonical input set, not merely "some source revisions".

- **Authoritative inputs (`CampaignStateInputIdentity`):** derivation version;
  the requested recent-session selection limit (an intentional semantic input —
  a different limit defines different selection/freshness semantics and changes
  the fingerprint even when the currently selected set is identical); current
  world time (tick + revision); selected completed sessions (id + revision);
  referenced canonical entities (id, type, name, visibility, revision + source
  session ids); and the supplied `CalendarDefinition`.
- **Source-snapshot semantics:** entity/session/world-time revisions are
  intentional identity inputs.  Any source change — including a revision bump
  with unchanged projected text — changes the fingerprint.  A change outside
  the accepted input contract cannot change it.
- **Canonical collection ordering:** set-like sources (sessions, entities,
  artifact inventory) are normalized ascending and duplicate-free, so caller
  order never becomes part of identity.
- **Calendar-definition identity:** the fingerprint binds the SHA-256 of the
  **complete validated `CalendarDefinition`** (months, intercalary days,
  holidays, epoch, hours/minutes).  `calendar_id` alone is not definition
  identity: two definitions sharing a `calendar_id` but differing in content
  produce different fingerprints.  No canonical `CalendarDefinition` source
  exists yet, so it is caller-supplied and may be absent (`None`).
- **Raw session events are not an input:** session metadata revision is not
  provably bound to the immutable event stream, so events are excluded rather
  than given a fabricated binding.
- **Manifest (`DerivedStateManifest`):** binds the generation fingerprint
  (`input_fingerprint`), `state_schema_version`, and a non-empty artifact
  inventory (logical relative path + per-file content hash).  The manifest is
  never part of its own inventory and contains no filesystem paths.

Entity `Revision` semantics are **not** reused as a concurrency counter. There
is no optimistic-concurrency writer for a derived projection; the
source-snapshot fingerprint manifest is the identity/staleness mechanism.

Ownership: the DTOs are pure domain contracts (`domain/campaign_state.py`);
canonical serialization and SHA-256 computation are application concerns
(`application/campaign_state_identity.py`).  Source collection (S12-02) and
physical persistence (S12-03) are separate.

## 5. Rebuild, staleness, corruption, manual edits

- **Stale when:** a fresh derivation computes a current-input fingerprint that
  differs from the manifest fingerprint. A bound entity/session/world-time
  revision change, or a newly completed session that changes the selected set,
  produces such a mismatch. A successful canonical apply is **not** itself an
  independent staleness signal:
  ```text
  successful apply
  → canonical source set/content may change
  → fresh derivation recomputes source identity
  → fingerprint comparison determines staleness
  ```
  An unrelated successful apply that does not change any bound source leaves
  the fingerprint unchanged.
- **Missing State:** consumers report the projection as unavailable; an
  explicit rebuild materializes it.
- **Corrupt State / manifest:** fail closed with `StorageError`; never parsed as
  canonical; rebuild overwrites.
- **After canonical entity / world-time / session change:** stale → rebuild.
- **After an unapplied or merely approved ChangeSet:** no effect. Persisted
  proposals under `_system/changesets/` are not inputs and cannot alter State.
- **After manual/external edit:** content hash mismatch vs manifest → treated as
  stale/tampered; overwritten on rebuild; never canonical.
- **Pre-publication verification (S12-03 mandatory):** a persisted projection
  must not be declared current merely because an earlier build once produced a
  valid fingerprint.  S12-03 publication must re-derive the source identity
  immediately before publication and abort on any mismatch:
  ```text
  build candidate
  → render candidate
  → fresh source re-derivation using the same selection configuration
  → compare fingerprint
  → mismatch: abort publication
  → match: publish artifacts and manifest-last
  ```
  Read-time staleness verification remains required after publication because
  no atomic transaction spans Vault entities, sessions, world time and
  derived-State files.  The S12-02 collector deliberately accepts a mixed-time
  snapshot for a single build and does not add a retry loop; the fresh
  pre-publication re-derivation is the S12-03 consistency gate.
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
apply succeeded           → canonical sources may change; next fresh derivation
                            recomputes source identity; fingerprint comparison
                            determines staleness (apply alone is not a signal)
canonical Vault changed   → derived inputs change → fingerprint mismatch
```

No recompute-after-apply hook and no `CampaignState` ChangeSet operation are
introduced. State is rebuilt lazily from current canonical reads. Stage-10's
operation set and Stage-11's accepted producer subset are not expanded.

## 10. `CampaignState` v1 reconciliation (completed in S12-01)

- `domain/campaign_state.py` v1 was dormant production dead code: it had no
  reader, writer, path, serializer, or production consumer; only unit tests and
  a static fixture referenced it.
- S12-01 replaced it with the typed in-memory materialized-projection contract
  (`schema_version = 2`): `revision` is gone (replaced by `input_fingerprint`)
  and the unsupported semantic fields (`current_location`, `active_quests`,
  `important_npcs`, `party_goals`, `unresolved_threads`, `upcoming_deadlines`)
  are omitted.  `extra="forbid"` rejects any v1 payload; there is **no v1
  parsing shim** and **no v1 data migration** (no production v1 artifact ever
  existed).
- The static golden `State/World State.md` v1 fixture was obsolete (no test
  parsed it) and was removed; Stage-12 materialization fixtures belong to
  S12-03.
- Generic value types `Sha256Fingerprint` and `RelativeArtifactPath` were
  promoted to `domain/types.py` (with backward-compatible `domain.post_session`
  re-exports), and the canonical session-id validation is exposed as the public
  domain `SessionId` type.

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

### S12-01 literal evidence (typed contract)

| Criterion | Literal evidence |
|---|---|
| v2 shape / strictness | `tests/unit/test_campaign_state.py`: minimal construction, `schema_version=2`, frozen, `extra="forbid"` |
| legacy semantic fields rejected | every v1 field + whole v1 payload → `ValidationError`; no `revision` attribute |
| fingerprint determinism + ordering normalization | `tests/unit/test_campaign_state_identity.py`: same input → equal bytes/digest; entity/session reorder → equal digest |
| source-snapshot sensitivity | tick, world-time revision, session revision, entity revision/name/visibility/type changes each change the digest |
| irrelevant metadata unchanged | repeated serialization stable; wall-clock / raw-event fields rejected as extra |
| duplicate references | duplicate session/entity ids and duplicate artifact paths rejected |
| `source_session_ids` provenance | mandatory, duplicate-free, canonical order, subset of identity sessions |
| calendar definition identity | same `calendar_id` + different structure → different calendar and input fingerprints |
| Unicode canonicalization | Cyrillic golden digest |
| manifest contract | `tests/unit/test_campaign_state_manifest.py`: non-empty inventory, canonical order, duplicate/path/hash validation |
| layer boundaries | `tests/contract/test_campaign_state_boundaries.py`: pure domain, provider-neutral application, promoted-type re-exports |

### S12-02 literal evidence (source collection / evidence binding)

| Criterion | Literal evidence |
|---|---|
| deterministic selection / order independence | `tests/unit/test_campaign_state_source.py`: listing-order independence, tied-finish tie-break, non-numeric ids |
| completed-only eligibility | active sessions never selected; unknown status / malformed completed lifecycle fail closed |
| touched-evidence rules | absent → empty; malformed → fail closed; duplicates collapsed; cross-session provenance union |
| exact entity binding | missing touched entity fail closed; current canonical fields; PLAYER/DM/SYSTEM admitted internally |
| selection-limit identity | `recent_session_limit` strict ≥ 1, required, bound into fingerprint even with identical selected set |
| source-snapshot sensitivity | world-time/session/entity revision change → fingerprint change; unrelated entity change → unchanged |
| world time / calendar | missing world time → `WORLD_TIME_UNAVAILABLE`; absent vs supplied calendar; definition change → fingerprint change |
| read-only / no writes | `tests/integration/test_campaign_state_source.py`: vault bytes and audit log unchanged across a build |
| layer boundaries | `tests/contract/test_campaign_state_boundaries.py`: `campaign_state_source` provider-neutral, no storage/retrieval runtime import, no persistence stdlib |

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

## 15. S12-01 record

```text
Task:      S12-01 — typed derived-state contract (CampaignState v2 + manifest/fingerprint)
Routing:   PLAN_REQUIRED -> accepted PLAN -> BUILD
Branch:    feat/campaign-state
Baseline:  fee00dabb155ae4c94627faf4b920e7fe5ea71ce (S12-00)
Scope:     domain/campaign_state.py (v2 rewrite)
           application/campaign_state_identity.py (new)
           domain/types.py + domain/post_session.py (promoted Sha256Fingerprint,
             RelativeArtifactPath with backward-compatible re-exports)
           domain/session.py (public SessionId) + domain/__init__.py exports
           tests (schema/identity/manifest/boundaries)
           golden fixture cleanup (obsolete State/World State.md)
           Stage-12 docs + DEVELOPMENT_STATUS.md reconciliation
Decisions: source-snapshot identity includes source revisions;
           calendar identity = SHA-256 of the complete CalendarDefinition;
           raw session events excluded from S12-01/S12-02 identity;
           manifest is a logical contract (no filesystem paths, no I/O).
No storage/materialization/model/consumer integration (S12-02..S12-04).
```

## 16. S12-02 record

```text
Task:      S12-02 — deterministic source collection / evidence binding
Routing:   PLAN_REQUIRED -> accepted PLAN -> BUILD
Branch:    feat/campaign-state
Baseline:  0fbd7e70ddbd1da9c43a6eb7600c0a3632c44ece (S12-01)
Scope:     application/campaign_state_source.py (new; read-only collector)
           domain/campaign_state.py (CampaignStateInputIdentity gains the
             validated recent_session_limit identity input; SelectionLimit)
           domain/__init__.py (SelectionLimit export)
           tests/unit/test_campaign_state_source.py (new)
           tests/integration/test_campaign_state_source.py (new)
           tests/unit/test_campaign_state_identity.py (limit binding)
           tests/contract/test_campaign_state_boundaries.py (new-module boundary)
           Stage-12 docs + DEVELOPMENT_STATUS.md reconciliation
Decisions: selection = latest N completed sessions by real_finished_at DESC,
             session_id ASC tie-break only (never listing order / lexical
             chronology / revision / world tick); N explicit, required,
             ceiling-bounded;
           recent_session_limit is bound into the identity/fingerprint;
           malformed completed lifecycle / unknown status / malformed
             touched_entities / missing touched entity fail closed; active
             sessions ignored;
           exact EntityId binding via one all-visibility list_entities()
             snapshot; all visibilities admitted internally;
           mixed-time single-pass snapshot; S12-03 must re-derive and compare
             the fingerprint immediately before publication and again at read
             time (no atomic repository transaction exists);
           raw session events never consulted; no model call; no write.
No derived-state persistence / rendering / manifest / path / atomic write /
CLI / consumer projection (S12-03..S12-04).
```

S12-03 warning: `RelativeArtifactPath` is a **logical** inventory identifier,
not filesystem authority.  Its current validation accepts a `C:/...`
drive-form string (it only rejects a leading `/`, backslashes and
empty/`.`/`..` segments), so S12-03 must not treat it as a safe filesystem
path without its own path-safety layer.
