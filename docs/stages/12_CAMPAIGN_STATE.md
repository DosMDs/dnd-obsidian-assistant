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

Session `world_tick_start` / `world_tick_end` are signed `WorldTick` values.
The canonical Session and world-time contracts do **not** establish monotonic
in-session world-time progression (`close_session()` accepts any valid
`world_tick_end`; world time may move backwards). Campaign State therefore does
not impose `world_tick_end >= world_tick_start`, and a completed session with a
decreasing tick is a valid source. Only real-time ordering
(`real_finished_at >= real_started_at`) is treated as a lifecycle requirement.

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
| successful apply → fresh derivation recomputes fingerprint | apply a ChangeSet; fresh derivation's fingerprint mismatches the manifest (bound source changed) and rebuild reflects the applied entity state; an unrelated successful apply leaves the fingerprint unchanged |
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

S12-02-C1 correction: Campaign State must not require
`world_tick_end >= world_tick_start`. `WorldTick` is signed and the canonical
Session / world-time contracts establish no monotonic in-session progression;
decreasing game-world time is a valid completed-session source. Only real-time
ordering (`real_finished_at >= real_started_at`) remains a fail-closed
lifecycle requirement.

S12-03 warning: `RelativeArtifactPath` is a **logical** inventory identifier,
not filesystem authority.  Its current validation accepts a `C:/...`
drive-form string (it only rejects a leading `/`, backslashes and
empty/`.`/`..` segments), so S12-03 must not treat it as a safe filesystem
path without its own path-safety layer.

## 17. S12-03 record — materialization / rebuild / staleness / corruption

```text
Task:      S12-03 — materialization + rebuild/staleness/corruption
Routing:   PLAN_REQUIRED -> accepted corrected PLAN -> BUILD
Branch:    feat/campaign-state
Baseline:  028a156ae517a3856e4d4709e6f06d5a555b1f0c (S12-02-C1)
```

### Physical layout

```text
<vault>/State/World State.md                  managed derived artifact
<vault>/State/Recently Touched.md             managed derived artifact
<vault>/State/.campaign-state-manifest.json   derived manifest (commit marker)
```

The manifest is colocated but dot-prefixed so `State/` stays human Markdown in
Obsidian. A single managed root keeps "delete all managed Campaign State files"
an unambiguous reset and gives clean `MISSING` semantics. The manifest is never
part of its own artifact inventory. No `Active Quests`/`Active Threads`/
`Party`/`Current Location` files are created: those semantics remain
unavailable and must not be fabricated. The artifact set renders even with zero
completed sessions, so a successful generation always has a non-empty
inventory.

### Artifact identity / filesystem authority

`CampaignStateArtifact` (domain, `WORLD_STATE` / `RECENTLY_TOUCHED`) is the
trusted allowlist. Physical destinations come exclusively from trusted fixed
Python tables (`storage/derived_state.py::ARTIFACT_FILENAMES` +
`MANIFEST_FILENAME`). Manifest `relative_path` values are inventory/validation
data only: no code path resolves or joins them to the filesystem. The reader
requires the manifest inventory to equal the renderer-owned expected set
exactly (no missing/extra/duplicate/`C:/...`/traversal entries).

### Rendering contract

Pure, deterministic, UTF-8, `\n`-only, exactly one trailing newline,
model-free, wall-clock-free, filesystem-free; owned by
`application/campaign_state_render.py` (no Markdown formatting in domain).

- `World State.md`: current world tick, optional derived `GameDate`, generation
  fingerprint. The date renders the **generic** domain shape
  (`year=…, month=…, day=…, hour=…, minute=…` or
  `year=…, intercalary_day=…, hour=…, minute=…`) with no Gregorian
  month-number assumptions.
- `Recently Touched.md`: entity id, type, display name, visibility, revision and
  source session ids for **`Visibility.PLAYER` references only**.
- One deterministic inline-escaping rule (`escape_inline`) backslash-escapes
  Markdown metacharacters and CR/LF for every user-controlled value (names, ids,
  session ids, calendar names), so a value can never alter the template.
  User-controlled values are rendered as ordinary escaped inline text, never
  inside a Markdown code span: backslash escaping is not interpreted inside
  CommonMark code spans, so a generally printable `EntityId` containing a
  backtick would break the span. `EntityId` validation is not weakened.

### Visibility

S12-02 source collection stays internally all-visibility. The human-readable
`State/*.md` files are player-facing Vault material and must not persist
`Visibility.DM`/`SYSTEM` references; `Recently Touched.md` renders PLAYER
references only, and tests assert DM/SYSTEM names and stable ids never occur in
rendered/persisted artifact bytes. S12-04 still owns the reusable player-safe
consumer projection.

### Manifest v2 / versioning

`DerivedStateManifest` schema → 2, adding `render_version`
(`CAMPAIGN_STATE_RENDER_VERSION`, currently `"2"`). Source-snapshot identity
(`input_fingerprint`, which binds `recent_session_limit` and the complete
`CalendarDefinition` fingerprint) is never overloaded with presentation format
version. A generation persisted with an older render version is classified
`OUTDATED` (rebuild required) even when its source fingerprint still matches.
`recent_session_limit` and the `CalendarDefinition` are **not**
persisted: caller/current trusted configuration is re-supplied and re-bound at
verification. No persisted S12-01 manifest existed, so no physical migration.

### Publication protocol

```text
initial S12-02 build
→ deterministic render candidate
→ fresh S12-02 build with the same derivation configuration
→ fingerprints differ: abort (CampaignStateSourceChangedError), zero writes
→ fingerprints equal: fresh build accepted source witness
→ inspect existing generation against witness
→ fully current: ALREADY_CURRENT (zero publication writes)
→ otherwise publish candidate artifacts, manifest LAST
```

Publication reauthorizes the derived-state parent immediately before **every**
managed replacement (mutation-time reauthorization discipline):

```text
authorize State/
→ authorize/write World State.md
→ reauthorize State/
→ authorize/write Recently Touched.md
→ reauthorize State/
→ authorize/write manifest LAST
```

If `State/` is substituted (e.g. replaced by a symlink) between managed writes,
publication fails closed before the next write and no later artifact or the
manifest is written through the substituted parent. The manifest always gets
its own fresh parent reauthorization. This is not a filesystem transaction and
does not eliminate every OS-level TOCTOU race.

No cross-repository atomic snapshot is claimed: canonical sources may still
change during publication, so read-time freshness verification remains
mandatory and a just-published generation may immediately classify `STALE`.
Partial/mixed generations are never `CURRENT`; the manifest is the commit
marker. No publication lock is required for the MVP.

### Read-time verification / statuses

`MISSING`, `OUTDATED`, `CORRUPT`, `UNVERIFIABLE`, `STALE`, `CURRENT`.

```text
safe topology
→ manifest/schema/render version/exact inventory
→ exact stored artifact hashes match manifest
→ fresh S12-02 derivation (caller config)
→ fingerprint differs: STALE
→ fingerprint equal: deterministically re-render the fresh state and compare
  exact bytes with every stored artifact
→ any byte mismatch: CORRUPT
→ exact match only: CURRENT
```

Manifest hashes are **not** a trust anchor: re-render comparison detects
coordinated manual edits that change both Markdown and the manifest hash.
Unsafe topology/symlink conditions fail closed with `StorageError` and are not
normalized to stale/corrupt statuses. `UNVERIFIABLE` preserves the underlying
source/storage cause.

### No audit

Derived Campaign State rebuilds do **not** append canonical
`_system/audit/audit.jsonl` records: State is non-canonical, rebuilds are
repeatable under identical canonical truth, and writing canonical audit for a
derived refresh would pollute the log. Diagnostics live in the result/status
objects. No new audit subsystem and no `AuditContext` requirement.

### Literal evidence

| Criterion | Literal evidence |
|---|---|
| deterministic render / LF-only / generic date | `tests/unit/test_campaign_state_render.py` |
| player-only State bytes / DM-SYSTEM negative | `test_campaign_state_render.py`, `tests/integration/test_campaign_state_materialization.py` |
| manifest v2 + `render_version` | `tests/unit/test_campaign_state_manifest.py`, `test_campaign_state_render.py` |
| store path/symlink/directory safety, payload-set, CR rejection | `tests/unit/test_campaign_state_store.py` |
| publication gate, `ALREADY_CURRENT`, coordinated edit, malicious manifest path, statuses | `tests/unit/test_campaign_state_materialization.py` |
| freshness, repair, deterministic rebuild, calendar, canonical read-only, manifest-last | `tests/integration/test_campaign_state_materialization.py` |
| mutation-time parent reauthorization between managed writes | `tests/unit/test_campaign_state_store.py::TestMutationTimeReauthorization` |
| layer boundaries | `tests/contract/test_campaign_state_boundaries.py` (render/materialization/store) |

### S12-03-C1 correction

- `ObsidianDerivedStateStore.publish()` reauthorizes the current `State/`
  topology immediately before each managed replacement (artifact, artifact,
  manifest-last); a parent substituted between writes fails closed before the
  next write.
- `Recently Touched.md` renders the entity id as ordinary escaped inline text
  rather than inside a backtick code span, where backslash escaping is not
  interpreted.
- `CAMPAIGN_STATE_RENDER_VERSION` bumped `"1"` → `"2"` (renderer output changed
  without a source-identity change); manifest schema remains v2 and
  `CAMPAIGN_STATE_DERIVATION_VERSION` is unchanged. A generation persisted with
  render version `"1"` is `OUTDATED`.

Not implemented (deferred): CLI, model calls, canonical ChangeSet operations,
TimelineEvent persistence, CalendarDefinition persistence, locking framework,
S12-04 consumer projection.

## 18. S12-04 record — player-safe projection + Focused Fast-Agent consumer

```text
Task:      S12-04 — visibility projection + focused consumer integration
Routing:   PLAN_REQUIRED -> accepted PLAN (+ architect corrections) -> BUILD
Branch:    feat/campaign-state
Baseline:  7b6d63f94b5e9a6d14daf0d8ec1d0c327d32f18a (S12-03-C1)
```

### Player-safe projection

`application/campaign_state_projection.py` is the single reusable
player-visibility boundary over the internally all-visibility
``CampaignState``:

- `project_player_campaign_state(state) -> PlayerCampaignState` is pure,
  deterministic, I/O-free and never mutates the input.
- Only `Visibility.PLAYER` references are admitted; `PlayerCampaignEntityReference`
  carries exactly `entity_id`, `entity_type`, `name` (no visibility, revision,
  provenance session ids or fingerprint).
- Player references are emitted in canonical `entity_id` ascending order.
- `PlayerCampaignStateProvider` (Protocol) is the only capability the Fast-Agent
  context builder consumes.

### Focused consumer (lazy ensure-current)

`application/campaign_state_consumer.py::RebuildPlayerCampaignStateProvider`
composes the S12-03 rebuild service, trusted repositories and a derived-state
store:

```text
rebuild_campaign_state            (lazy ensure-current; PUBLISHED | ALREADY_CURRENT)
  -> trusted typed CampaignState
  -> project_player_campaign_state
  -> PlayerCampaignState
```

`FAST_AGENT_RECENT_SESSION_LIMIT = 5` is the explicit, named production policy
value (no CLI/config expansion; the literal is not duplicated).  Production
uses `calendar_definition=None`: no canonical `CalendarDefinition` source
exists, so no ``GameDate`` is fabricated.

### Graceful vs fail-closed mapping

```text
WORLD_TIME_UNAVAILABLE                    -> None (omit campaign memory, continue)
CampaignStateSourceChangedError (race)    -> None (omit; no retry loop)
INVALID_COMPLETED_SESSION
INVALID_TOUCHED_ENTITIES
MISSING_TOUCHED_ENTITY
INVALID_CALENDAR_INPUT
INVALID_SELECTION_LIMIT
INPUT_TOO_LARGE                            -> propagate CampaignStateSourceError
StorageError (unsafe State topology,
  store/canonical corruption)              -> propagate fail-closed
```

### Agent context + USER request contract

`application/agent_context.py`:

- `AgentCampaignMemoryEntity` (`entity_id`, `entity_type`, `name`) and
  `AgentCampaignMemory` (`recently_touched`, `total_recently_touched`,
  `truncated`), with `AgentContext.campaign_memory: AgentCampaignMemory | None`
  defaulting to `None`.
- `AgentContextBuilder` takes an optional `campaign_state_provider`; it never
  receives repositories, the derived-state store or materialization internals.
- Compactness is a Fast-Agent policy: `MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES = 10`
  and `MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES = 2048`.  `EntityId`/`NameStr` are
  not length-bounded, so both a count bound and a UTF-8 byte budget are
  enforced.  Entries in canonical `entity_id` order are included only while the
  exact `entity_id` + `name` fit the remaining budget; ids/names are never
  truncated and iteration stops before the first non-fitting entry.
  `total_recently_touched` is the full PLAYER count before compacting and
  `truncated = included < total`.  A first entry that alone exceeds the budget
  yields `recently_touched = ()`, `total > 0`, `truncated = True`.
- The ordering is deterministic canonical order, explicitly **not** a relevance
  ranking.  Campaign memory is kept distinct from `relevant_entities`
  (query-derived retrieval) and carries no second tick/date; the existing
  `current_world_tick` remains the only model-facing world-time field.

`application/agent_contracts.py::build_agent_request` keeps explicit field
mapping and always serializes a top-level `campaign_memory` (`null` when
unavailable; otherwise the compact object).  Adding `AgentContext` fields still
does not auto-expose them.

### Prompt/request version — agent-v3

The additive deterministic USER field changes the model-facing request
contract, so the current prompt/request identity is now
`src/dnd_assistant/prompts/agent_v3.py` (`PROMPT_VERSION = "agent-v3"`, system
prompt text identical to v2).  `agent_v1.py` and `agent_v2.py` are preserved
unchanged.  `AgentDecision.prompt_version`, the Pydantic AI runtime prompt
imports and the `dnd ask` audit `prompt_version` all use `agent-v3`.  No
separate request-schema namespace was introduced.

### Lazy materialization / READ-only semantics

Default READ-only `dnd ask` may create/repair managed `State/*` files.  This is
trusted Python derived-cache maintenance, not model WRITE authorization:

- no canonical entity/session/event/world-time mutation;
- no canonical `_system/audit/audit.jsonl` append;
- `ExecutionContext.granted_permission` remains `READ` and only READ tools are
  exposed;
- unsafe `State/` topology still fails closed with `StorageError`;
- no model participates in whether/where derived files are written.

### Literal evidence

| Criterion | Literal evidence |
|---|---|
| PLAYER retained / DM+SYSTEM excluded / deterministic order / no mutation / minimal fields | `tests/unit/test_campaign_state_projection.py` |
| per-reason graceful-vs-propagated mapping / StorageError propagation / explicit policy config | `tests/unit/test_campaign_state_consumer.py` |
| count + UTF-8 byte budget / long ASCII + Cyrillic / never partial id | `tests/unit/test_agent_campaign_memory.py` |
| exact USER JSON shape / always-present `null` / distinct field / hidden-data negative | `tests/unit/test_agent_request_campaign_memory.py` |
| rebuild→project, stale repair, world-time omission, unsafe-symlink fail-closed | `tests/integration/test_s12_04_campaign_memory.py` |
| derived-only writes, no canonical/audit mutation, READ tool exposure | `tests/integration/test_s12_04_campaign_memory.py` |
| fake-model first USER payload player-safe + `agent-v3` | `tests/integration/test_s12_04_campaign_memory.py` |
| composition wires provider + explicit limit + READ context | `tests/unit/test_cli_agent_runtime.py` |
| projection/consumer provider-neutral boundary | `tests/contract/test_campaign_state_boundaries.py` |

### Changed files

```text
src/dnd_assistant/prompts/agent_v3.py                          (new)
src/dnd_assistant/application/campaign_state_projection.py     (new)
src/dnd_assistant/application/campaign_state_consumer.py       (new)
src/dnd_assistant/application/agent_context.py                 (modified)
src/dnd_assistant/application/agent_contracts.py               (modified)
src/dnd_assistant/application/pydantic_ai_fast_agent.py        (agent-v3)
src/dnd_assistant/application/pydantic_ai_agent_runtime.py     (agent-v3)
src/dnd_assistant/cli/agent_runtime.py                         (provider wiring, agent-v3)
tests/unit/test_campaign_state_projection.py                   (new)
tests/unit/test_campaign_state_consumer.py                     (new)
tests/unit/test_agent_campaign_memory.py                       (new)
tests/unit/test_agent_request_campaign_memory.py               (new)
tests/integration/test_s12_04_campaign_memory.py               (new)
tests/unit/test_cli_agent_runtime.py                           (modified)
tests/unit/test_agent_contracts.py                             (agent-v3)
tests/integration/test_pydantic_ai_agent_runtime.py            (agent-v3)
tests/integration/test_pydantic_ai_fast_agent.py               (agent-v3)
tests/integration/test_cli_ask_mocked.py                       (agent-v3)
tests/contract/test_campaign_state_boundaries.py               (projection/consumer boundaries)
docs/stages/12_CAMPAIGN_STATE.md, docs/stages/09_FAST_AGENT.md,
docs/adr/0007-campaign-state-materialized-derived-projection.md,
DEVELOPMENT_STATUS.md
```

No new third-party dependency. No arbitrary filesystem capability reached
application/model code. No Markdown parsing in the consumer path.
`tests/contract/test_boundaries.py` unchanged.

Deferred beyond S12-04: S12-05 hardening/failure injection, S12-06 review.
No model call in derivation; model-assisted narrative, semantic ranking,
TimelineEvent/CalendarDefinition persistence, new ChangeSet operations, DM mode
and Web UI remain out of scope.

## 19. S12-05 record — hardening / failure injection / cross-platform safety

```text
Task:      S12-05 — Campaign State hardening / failure injection
Routing:   PLAN_REQUIRED -> accepted PLAN (+ architect corrections) -> BUILD
Branch:    feat/campaign-state
Baseline:  b501ee6d0ef2ceae95f418ca2325d9f9fd5d4ea1 (S12-04)
```

S12-05 adds no Campaign State semantics, no consumer, no CLI command, no model
call and no dependency. It hardens the accepted S12-02→S12-04 pipeline and fixes
concrete defects found by adversarial tests.

### PLAYER hidden-data noninterference + render v3

S12-04 tests only proved known DM/SYSTEM *sentinels are absent*. S12-05 proves
the stronger property: two internal generations whose PLAYER-visible evidence is
identical while hidden evidence differs (ids, names, revisions, provenance,
count, ordering) must produce **equal** PLAYER-facing output.

A concrete side channel was found and removed: `State/World State.md` rendered
`- Generation fingerprint: <input_fingerprint>` and `input_fingerprint` is
derived from the all-visibility source identity, so a hidden-only canonical
change altered a PLAYER-facing artifact. The generation line is removed and no
player-facing replacement fingerprint is introduced (no consumer needs one;
integrity/freshness remain in the manifest and deterministic re-render
verification). This changes rendered bytes, so
`CAMPAIGN_STATE_RENDER_VERSION` is bumped `"2"` → `"3"`.
`CAMPAIGN_STATE_DERIVATION_VERSION`, the manifest schema version, the
`CampaignState` schema version and `agent-v3` are unchanged. A stored render
version `"2"` classifies `OUTDATED`.

Pairwise equality is asserted for: `State/*.md` artifact bytes,
`PlayerCampaignState`, `AgentCampaignMemory`, exact `build_agent_request` USER
JSON, and the first **actual** Pydantic AI `UserPromptPart`. Adding 100 hidden
references changes none of `total_recently_touched`, `truncated`, included
PLAYER entities, model payload bytes or PLAYER Markdown bytes.

### Manifest visibility semantics

`State/.campaign-state-manifest.json` stays in place and is documented as an
**internal technical integrity/freshness artifact**, outside the PLAYER
semantic-output equality contract. It intentionally contains hidden-dependent
metadata through the all-visibility `input_fingerprint` and therefore may differ
under hidden-only canonical changes. Dot-prefixing, Obsidian hiding and SHA
opacity are **not** claimed to provide confidentiality.

### State-directory authorization (junction / reparse / containment)

`ObsidianDerivedStateStore` previously relied on `Path.is_symlink()` plus a
resolved-containment check that only the **read** path performed.
`_ensure_state_dir` (the write path) checked neither junction/reparse identity
nor resolved containment, so a Windows directory junction at `State/` could
redirect managed writes outside the Vault. Corrected state machine:

```text
State absent
-> ensure candidate is not an existing redirecting object
-> mkdir exact State/
-> full existing-State authorization
State exists -> full existing-State authorization
```

Full existing-State authorization requires: not symlink, not junction/reparse,
real directory, and resolved path contained within the trusted resolved Vault
root. It is applied to the existing normal path, the `FileExistsError` race
branch, immediately after successful `mkdir`, `_resolve_existing_state_dir`, and
every mutation-time `_ensure_state_dir()` call that precedes each artifact and
manifest replacement. `_safe_leaf` also rejects a junction leaf. The shared
atomic writer is unchanged; the residual OS-level TOCTOU between authorization
and `os.replace` is retained and not claimed as a filesystem transaction.

### Publication failure injection / reader races / concurrency

Every injected scenario models both the stored/partial generation **and** the
current canonical-source epoch, and expected status follows actual verifier
order (manifest/schema/render/inventory → artifact hashes → fresh derivation →
fingerprint → deterministic re-render). Corrected distinctions:

```text
old generation A untouched + canonical source B        -> STALE
artifact B differs from old manifest A hash            -> CORRUPT
hidden-only change, identical PLAYER bytes, manifest A -> STALE
full artifacts+manifest B + canonical source B         -> CURRENT
source unchanged, exact generation intact              -> legitimate CURRENT
failure after successful manifest replace              -> post-commit CURRENT
```

Deterministic (no timing/sleep) writer interleavings around artifact 1,
artifact 2 and manifest-last never produce a false `CURRENT`; a coherent stale
generation is `STALE` and a coherent current generation is `CURRENT`. Reader
races couple the observed snapshot to a fresh witness: a coherent old snapshot
is `STALE` when the fresh source is B and `CURRENT` only when the source is still
A. `CURRENT` is verification of the observed generation against the fresh source
witness at verification time, never a lease. No false-CURRENT state was found,
so the accepted **no-lock MVP remains valid**; no locking framework was added.

### Hard links

A managed-leaf hard link is accepted. `os.replace` swaps the managed directory
entry, so the other hard-link name keeps its original inode/content; the
outside object is not mutated. Rejecting hard links would have been unfounded.

### Source-failure / lazy-consumer recovery

Injected `CampaignStateSourceError` and `StorageError` at initial and fresh
pre-publication derivation produce **zero** new publication before `publish()`
is reached; a previously valid generation is never deliberately destroyed.
The lazy provider repairs `MISSING`, `STALE`, `CORRUPT` and `OUTDATED (render
v2)` and returns a PLAYER projection on the next turn. `CampaignStateSourceChangedError`
and `WORLD_TIME_UNAVAILABLE` → `None`; malformed canonical evidence, other source
errors, `StorageError` and unsafe topology propagate fail-closed. No retry loop.

### Unicode / Markdown / hard limits

Adversarial-but-valid printable corpus (Cyrillic, non-BMP emoji, NFC/NFD,
combining marks incl. leading U+0301, Markdown metacharacters mixed with
Unicode, long multibyte names/ids) proves exact UTF-8 serialization with **no
implicit normalization**, NFC ≠ NFD, same input → identical bytes, and no
partial UTF-8 truncation in Fast-Agent compactness. Composed Markdown attacks
cannot create attacker-controlled headings/list/quote/table structure. Actually
non-printable values (newline, NUL, U+200B) are rejected at the canonical domain
boundary; validators were not weakened. Large-input ceilings fail closed with no
silent truncation; Fast-Agent compactness remains the only explicit truncation.

### Audit / READ-only / wording

Successful, partially failed and repaired derived maintenance appends no
canonical audit. A production-composition READ `dnd ask` run keeps
`Permission.READ`, exposes only READ tools, repairs derived `State/*` and leaves
canonical bytes and canonical audit unchanged. `AgentContextBuilder`'s stale
"strictly read-only" wording is reconciled to: no canonical mutation, no
model/tool execution, optional trusted provider may maintain noncanonical derived
`State/*`. Error taxonomy (`MISSING/OUTDATED/CORRUPT/UNVERIFIABLE/STALE/CURRENT`)
is unchanged.

### Literal evidence

| Criterion | Literal evidence |
|---|---|
| PLAYER pairwise noninterference (bytes/projection/memory/USER JSON) | `tests/unit/test_campaign_state_visibility_noninterference.py` |
| no fingerprint line / render v3 | `tests/unit/test_campaign_state_render.py` |
| first actual UserPromptPart equality / READ composition | `tests/integration/test_campaign_state_agent_noninterference.py` |
| junction/containment/race-branch/hard-link | `tests/integration/test_campaign_state_cross_platform_safety.py` |
| publication phase matrix + source-failure zero-write + audit | `tests/unit/test_campaign_state_failure_injection.py` |
| deterministic interleavings / reader races / replay | `tests/integration/test_campaign_state_concurrency.py` |
| Unicode + Markdown adversarial | `tests/unit/test_campaign_state_render_adversarial.py` |
| lazy recovery / junction fail-closed | `tests/integration/test_campaign_state_agent_noninterference.py` |
| selection ceiling boundary | `tests/unit/test_campaign_state_source.py` |
| render v2 → OUTDATED | `tests/unit/test_campaign_state_materialization.py` + lazy recovery |

### Changed files

```text
src/dnd_assistant/storage/derived_state.py                  (junction/containment)
src/dnd_assistant/application/campaign_state_render.py      (fingerprint removal, render v3)
src/dnd_assistant/application/agent_context.py              (wording only)
tests/unit/test_campaign_state_render.py                    (modified)
tests/unit/test_campaign_state_source.py                    (modified)
tests/unit/test_campaign_state_visibility_noninterference.py (new)
tests/unit/test_campaign_state_failure_injection.py         (new)
tests/unit/test_campaign_state_render_adversarial.py        (new)
tests/integration/test_campaign_state_cross_platform_safety.py (new)
tests/integration/test_campaign_state_concurrency.py        (new)
tests/integration/test_campaign_state_agent_noninterference.py (new)
docs/stages/12_CAMPAIGN_STATE.md, docs/adr/0007-...md, DEVELOPMENT_STATUS.md
```

No new third-party dependency. `tests/contract/test_boundaries.py` unchanged.
The real Windows directory-junction test runs on this host (junctions are
creatable without privilege); POSIX/privileged symlink tests skip where the host
lacks capability and are reported as such, never as verified coverage.

Deferred beyond S12-05: nothing further in hardening; S12-06 owns the full
Stage-12 review/completion. Model-assisted narrative, semantic ranking,
TimelineEvent/CalendarDefinition persistence, new ChangeSet operations, DM mode
and Web UI remain out of scope.
