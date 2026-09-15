# Stage 11 — Post-session Processor

## Status

```text
Stage 11 — IN PROGRESS
S11-00 — DONE
S11-01 — DONE
S11-02 — DONE
S11-03 — DONE
S11-04 — NOT STARTED
S11-05 — NOT STARTED
S11-06 — NOT STARTED
S11-07 — NOT STARTED
S11-08 — NOT STARTED
S11-09 — NOT STARTED
Stage 12 — NOT STARTED
```

Architecture verdict:

```text
S11_ARCHITECTURE_READY
```

This document is the canonical Stage-11 architecture record and task map. It
describes **contracts and evidence plans**. Implementation begins at S11-01.

## 1. Purpose

Stage 11 provides the heavy post-session processing pipeline. It gathers a
completed session's durable evidence deterministically and turns it into
model-generated, reviewable outputs: a GM/internal **Summary**, a player-facing
**Recap**, and candidate campaign-memory updates expressed as a Stage-10
**ChangeSet proposal**.

Stage 11 builds on the accepted Stage-10 ChangeSet pipeline and must not bypass
it. The canonical lifecycle remains:

```text
raw/session evidence
→ post-session processing
→ ChangeSet proposal
→ validation
→ human review/approval
→ apply
→ VaultRepository
```

Stage 11 stops at proposal creation. It never approves, applies, or synthesizes
approval of a ChangeSet.

## 2. Trust boundary

```text
Obsidian Vault = only campaign Source of Truth
Python         = trusted domain/application/storage/retrieval/calendar logic
LLM/model      = untrusted, replaceable mechanism
```

The model never:

- receives unrestricted filesystem or shell access;
- writes to the Vault;
- performs revision/conflict checks;
- decides that generated campaign facts are canonical;
- bypasses ChangeSet validation/review/apply;
- performs calendar arithmetic that belongs to `CalendarService`;
- receives any tool surface for Stage-11 production.

All canonical campaign mutation introduced by Stage 11 flows exclusively through
the existing Stage-10 `ChangeSet` → review → `apply_changeset` →
`VaultRepository` path. No alternate write path is introduced.

## 3. Durable post-session evidence (input reality)

After `session end`, the durable evidence is:

```text
_system/raw/sessions/<id>/metadata.json   canonical Session + touched_entities
                                          extra (+ legacy processing_status string)
_system/raw/sessions/<id>/events.jsonl    append-only immutable raw events
_system/audit/audit.jsonl                 session.start/event.append/end audit
_system/world_time.json                   current world tick (not session-specific)
```

Findings that shape the design:

- `Sessions/<id>/Session.md` is a reserved path only; production code never
  creates or reads it. It is not a canonical session record.
- `Sessions/<id>/Summary.md` / `Recap.md` / `Notes.md` exist only in the golden
  fixture and are not enforced by production code.
- Raw events carry no per-event `visibility` field.
- No canonical `CalendarDefinition` source is persisted or loaded in production.

## 4. Accepted architecture corrections

The S11-00 PLAN was accepted with five mandatory corrections. They are
authoritative for every later Stage-11 task.

### C1 — Prepared-input fingerprint, not raw-session-only identity

Processing identity is a canonical **full prepared-input fingerprint**. A raw
event hash may be one component, but it is never sufficient.

```text
input_fingerprint = SHA-256(canonical_json(input_identity))
input_identity =
    session_projection          # id, status, real_started_at/finished_at,
                                # world_tick_start/end, revision,
                                # ordered touched_entities
  + ordered_raw_events          # canonical per-event serialization, in order
  + entity_projections          # per referenced entity: stable id, revision,
                                # name, status, visibility, knowledge_status,
                                # tags, bounded body projection
  + context_projection          # the exact deterministic prepared-input document
  + calendar_projection         # raw ticks now; deterministic dates when a
                                # canonical CalendarDefinition source exists
  + processor_version
  + prompt_version
```

`model_profile` shapes generated output, not the prepared input bytes, and is
recorded as execution metadata (not part of `input_fingerprint`). Every
deterministic durable/context input that can affect model input must be included.
A future deterministic calendar projection is included the moment it exists.

### C2 — Input identity separated from execution-attempt identity

```text
input_fingerprint   deterministic identity of prepared processing input
attempt_id / run_id unique identity of one execution attempt
```

Multiple attempts may share one `input_fingerprint` (deliberate rerun, different
`model_profile`, retry after failure). A ChangeSet produced by Stage 11 is
**attempt-scoped** so separate reruns can never collide:

```text
changeset_id = cs_<session_ref>_<attempt_id>
```

Stage-10 `persist_proposal` is immutable/idempotent by `(changeset_id,
fingerprint)`, so a distinct attempt id yields a distinct proposal, while an
exact retry of the same attempt is idempotent.

### C3 — Versioned, immutable generated artifacts (no silent overwrite)

Generated Summary/Recap artifacts are **immutable and versioned per attempt**.
Singleton `Sessions/<id>/Summary.md` / `Recap.md` files are **not** the sole
durable processing outputs.

```text
_system/raw/sessions/<id>/processing/attempts/<attempt_id>/summary.md
_system/raw/sessions/<id>/processing/attempts/<attempt_id>/recap.md
```

Each artifact is created exclusively and never rewritten or truncated. A later
human-facing "latest/current" projection (for example into `Sessions/<id>/`) may
be considered separately, but it is a projection/copy and must not destroy or
replace prior generated artifact content. The projection decision is deferred;
it is not part of S11-00 or of the initial durable contract.

### C4 — Genuinely append-only processing ledger

There is no mutable record whose status silently changes from `started` to
`completed`. Processing history is an append-only event ledger:

```text
_system/raw/sessions/<id>/processing/ledger.jsonl   (append-only, one JSON
                                                      event per line)
```

Event kinds (initial contract; exact schema owned by S11-01/S11-06):

```text
attempt_started       attempt_id, input_fingerprint, processor_version,
                      prompt_version, model_profile, real_time
artifact_persisted    attempt_id, artifact_kind, relative_path, content_hash,
                      real_time
proposal_persisted    attempt_id, changeset_id, changeset_fingerprint, real_time
attempt_completed     attempt_id, outcome (produced | no_changes), real_time
attempt_failed        attempt_id, phase, failure_category, message, real_time
attempt_superseded    attempt_id, superseded_by_attempt_id, reason, real_time
```

State is reconstructed by folding events per `attempt_id`. A terminal event
(`attempt_completed` or `attempt_failed`) defines terminal status; an
`attempt_started` with no terminal event means interrupted/in-progress. Events
are never rewritten or truncated; malformed/partial history fails closed.

### C5 — Ledger is authority; legacy session fields are not

During Stage 11 the durable processing **ledger is the authority** for
processing state. `Session.processed`, `Session.processed_model_profile`, and the
string-only `processing_status` extra are **not** authoritative Stage-11 state
and must not be read as such.

Whether those existing session-metadata fields should later be synchronized is an
explicit **S11-06** decision, made only after crash/idempotency semantics are
implemented and proven.

## 5. Processing eligibility (Python-owned)

Deterministic and evaluated before any model call:

```text
1 session exists and metadata parses
2 status == "completed"
3 real_finished_at and world_tick_end present and consistent
  (world_tick_end >= world_tick_start; real_finished_at >= real_started_at)
4 events.jsonl exists, is readable/safe, and parses strictly (fail closed)
5 session is not the active session
6 touched_entities is a list of valid EntityId strings
7 requested attempt is not already terminal for the same attempt_id
```

The model never decides structural eligibility. `processing_status` is not the
gate.

## 6. Model input contract

Three strictly separated tiers:

```text
canonical durable input   completed Session record, ordered raw events,
                          touched_entities, canonical entity snapshots,
                          current world tick
derived context           Python-resolved entities, canonical visibility/
                          knowledge_status, revisions, tick span, evidence links
model prompt material      bounded deterministic projection of the above
```

Transient framework message history is never canonical input. All model input is
rebuilt deterministically from the tiers above.

## 7. Summary vs Recap semantics

```text
Summary   GM/internal factual artifact; may include DM-visible facts;
          reproducible from the prepared input; never stronger evidence
          than the raw log.
Recap     player-facing narrative; must exclude GM/hidden information.
```

Recap visibility is enforced by a **deterministic** boundary, not prompt wording:
the extraction phase emits per-claim typed structures with `visibility` and
`knowledge_status` plus evidence links; Python constructs the recap model input
only from the player-visible projection and cross-checks claims that reference
canonical entities against those entities' canonical `visibility`. Claims whose
evidence references a non-player entity are excluded from recap by default
(fail-safe). Because raw events have no visibility field, recap-eligible claims
must cite player-visible entity evidence and/or be tagged `player` without
referencing any non-player entity.

## 8. ChangeSet producer contract

Stage 11 emits normal persisted Stage-10 proposals via
`application.changeset_store.persist_proposal`; no parallel format.

```text
changeset_id      cs_<session_ref>_<attempt_id>     (attempt-scoped, C2)
session_ref       real completed session id (R1 resolved)
provenance        MODEL_INFERENCE + model_profile + prompt_version
operations        create_entity first, then update_entity/append_fact, stable order
expected_revision captured from Python reads at processing time; stale revisions
                  fail closed at apply (no rebase)
visibility        canonical Visibility validated by Python, never a raw passthrough
persistence       _system/changesets/<id>.proposal.json (existing store)
```

Model output is untrusted structured input; Python validates, normalizes,
resolves and constructs the immutable `ChangeSet`. Unsupported/ambiguous
operations are omitted and recorded as `unresolved` items, never guessed. If
zero valid operations result, Stage 11 emits a distinct `no_changes` outcome and
no proposal (the domain requires at least one operation). Stage 11 never
approves or applies.

## 9. Entity ambiguity policy

```text
one unambiguous existing entity        -> reference its EntityId
multiple plausible candidates          -> no mutation; record unresolved/ambiguous
genuinely new entity (explicit signal) -> Python-allocated EntityId; create_entity
alias-only mention                     -> resolve; else ambiguity/new-entity path
unresolved reference                   -> record unresolved; omit
```

Canonical rule: `explicit unresolved/clarification/reviewable omission >
speculative mutation`. Duplicate entities are never created because the model
emitted a new name. Internal/DM resolution uses `VaultRepository` reads plus
exact-ID matching; the player-only `SearchService`/`EntityResolver` contracts are
reused only for the player-visible subset.

## 10. Calendar/time policy

All `world_tick` ↔ `GameDate` conversion and game-time arithmetic stay in
`CalendarService`. No canonical `CalendarDefinition` source exists yet, so
Stage 11 passes raw `world_tick` values deterministically and must not fabricate
game dates. The model may phrase supplied deterministic time information but
must never compute campaign time. When a canonical definition source is added,
date projection becomes a deterministic Python step and enters
`calendar_projection` (C1). `TimelineEvent` creation is not a Stage-10 operation
kind and remains out of scope.

## 11. Heavy-model/runtime integration

- Narrow application-owned `PostSessionModel` protocol with typed structured
  methods (extraction and rendering).
- Pydantic AI adapter lives in an isolated `application/pydantic_ai_post_session`
  style module, using `Agent(model, output_type=<PydanticModel>,
  retries={"output": 0})`. No framework retries by policy.
- The heavy model receives **no tools** and no `ToolExecutor` surface.
- Model construction uses a models-layer factory for the post-session role
  (reusing provider/URL/timeout mechanics). `build_pydantic_ai_ollama_model`
  currently rejects non-`AGENT` roles, so S11-03 adds a focused factory and
  decides the role value (`POST_SESSION` recommended; final choice S11-03).
- Canonical tests inject a deterministic fake model; no Ollama is required.
  Live heavy-model smoke/eval is opt-in only.

## 12. Orchestration phases

One bounded application service (`PostSessionProcessor`), explicit phases, not an
autonomous tool-using agent:

```text
1 eligibility (Python, fail closed; no model call)
2 input assembly + entity resolution (Python, deterministic)
3 structured extraction (one model request; untrusted)
4 validate/normalize + resolve + build ChangeSet / no_changes (Python)
5 render Summary (full authorized extraction)
  render Recap (player-only projection)
6 persist, in order:
     ledger attempt_started (already durable before model work)
     artifact_persisted per generated artifact
     proposal_persisted (if any)
     attempt_completed | attempt_failed
7 return aggregate result
```

## 13. Persistence, provenance and restart

```text
_system/raw/sessions/<id>/processing/ledger.jsonl              append-only ledger
_system/raw/sessions/<id>/processing/attempts/<attempt_id>/
        summary.md                                             immutable per attempt
        recap.md                                               immutable per attempt
_system/changesets/<id>.proposal.json                          Stage-10 proposal
```

Every durable artifact carries provenance: `session_ref`, `attempt_id`,
`input_fingerprint`, real timestamp, model profile, prompt/processor version,
artifact type, and ChangeSet id where applicable. No chain-of-thought is
persisted. Model traces/metrics, if stored, are operational metadata only and are
distinct from campaign truth.

Restart: state is reconstructed by reading the ledger and verifying referenced
artifacts/proposals. No hidden process state and no SQLite-only state.

## 14. Reprocessing / idempotency

```text
same input_fingerprint + same attempt_id, terminal  -> idempotent no-op
same input_fingerprint + new attempt_id             -> new attempt (allowed)
different input_fingerprint                         -> new processing input
```

Raw events are immutable and reprocessable. Prior attempts and their generated
artifacts are never overwritten. Multiple ChangeSets from reruns are
distinguished by attempt-scoped `changeset_id`. An already-approved/applied
earlier ChangeSet is never replayed or re-applied by Stage 11; only a new
proposal may be created.

## 15. Failure/restart semantics

```text
model unavailable / timeout          -> ModelError; ledger attempt_failed; no
                                        canonical mutation
malformed structured output          -> ValidationError; attempt_failed
unknown operation kind / bad IDs     -> rejected before persistence
ambiguous entity                     -> unresolved item, not a hard failure
summary produced, ChangeSet failed   -> artifacts persist; attempt_failed;
                                        no proposal; rerun allowed
interrupted processing               -> attempt_started without terminal event;
                                        detected on next run
evidence changed unexpectedly        -> input_fingerprint mismatch; fail closed
duplicate processing request         -> idempotent terminal attempt
```

No partial failure can corrupt canonical campaign state: the only canonical
entity mutation is Stage-10 apply, which Stage 11 never invokes.

## 16. CLI/user flow

```text
dnd session process [SESSION_ID] --vault PATH --config PATH --profile NAME
                    [--latest]
dnd session outputs <SESSION_ID> --vault PATH      (optional read-only)
```

Selector: exactly one of explicit `SESSION_ID` or `--latest`; both or neither
fails safely. Review/approve/apply remain exclusively `dnd changeset ...`. New
CLI logic lives in a focused module; `cli/changeset.py` (666 lines) is not grown.

## 17. Invariants

```text
I1  Vault is the only campaign Source of Truth
I2  Stage 11 creates proposals; it never approves or applies
I3  Every model output is untrusted until Python validates it
I4  The heavy model has no tools, no filesystem, no shell, no Vault write
I5  input_fingerprint binds the full deterministic prepared input (C1)
I6  input identity and attempt identity are distinct (C2)
I7  generated artifacts are immutable/versioned per attempt (C3)
I8  the processing ledger is append-only; history is never rewritten (C4)
I9  the ledger is authoritative; legacy session fields are not (C5)
I10 recap excludes hidden information by deterministic filtering, not prompts
I11 ambiguous references are never speculatively mutated
I12 calendar conversion and arithmetic stay in CalendarService
I13 domain/storage never depend on a concrete model/provider
I14 no new canonical campaign store outside the Vault
```

## 18. Acceptance criteria

Architecture acceptance is proven when later tasks deliver:

1. completed session accepted; active/incomplete/missing/corrupt rejected
   (fail closed, zero model calls);
2. same durable input produces the same `input_fingerprint`; changed input
   produces a different one;
3. `input_fingerprint` is stable across attempts; `attempt_id` is unique and
   attempt-scoped `changeset_id` never collides;
4. generated Summary/Recap are immutable per attempt; reruns never overwrite;
5. ledger is append-only and state is reconstructable after simulated restart;
6. legacy `Session.processed`/`processed_model_profile`/`processing_status` are
   not used as Stage-11 state;
7. recap excludes hidden/GM-only information under a fixture with hidden facts;
8. produced ChangeSet has a real `session_ref`, passes the existing validator,
   remains unapproved, and is consumed by existing `dnd changeset status/review`;
9. ambiguous references are omitted, not mutated; new entities never duplicate
   existing ones;
10. model/provider failure leaves canonical Vault entities unchanged.

## 19. Acceptance → evidence map (planned)

```text
full-input fingerprint binding   -> two prepared-input variants differing only in
                                    entity revision / visibility produce distinct
                                    input_fingerprint; raw-event-only change does too
attempt vs input separation      -> same input_fingerprint, two attempt_ids, two
                                    distinct attempt-scoped changeset_ids
immutable per-attempt artifacts  -> artifact inventory + byte equality across a
                                    rerun; prior attempt files unchanged
append-only ledger               -> line-count monotonic growth; no rewrite;
                                    state reconstruction from ledger alone
ledger authority                 -> injected legacy field changes do not alter
                                    processing decisions
no direct canonical write        -> repository mutation spy; before/after Vault
                                    assertion for the processing path
unapproved proposal              -> persisted proposal read-back + no approval
player recap safe                -> hidden-fact fixture + negative model-input and
                                    output assertions
model-independent tests          -> fake PostSessionModel; no Ollama
```

A green test without the matching semantic assertion does not satisfy a row.

## 20. Out of scope

```text
Stage 12 Campaign State
bootstrap/import
embeddings / vector DB / graph DB
voice / transcription
combat / rules automation
generic RAG framework
new canonical campaign storage outside the Vault
automatic ChangeSet approval / apply
automatic canonical entity mutation from model output
```

## 21. Task map

```text
S11-00  Post-session architecture/contracts/kickoff        DONE
S11-01  post-session input + durable processing schemas    DONE
        (domain schemas, eligibility, fingerprint, append-only ledger
         repository; smallest first BUILD increment)
S11-02  deterministic context assembly + entity resolution DONE
S11-03  heavy-model structured extraction mechanism        NOT STARTED
S11-04  Summary/Recap production + visibility filtering    NOT STARTED
S11-05  ChangeSet producer integration + ambiguity policy  NOT STARTED
S11-06  persistence/rerun/failure semantics (incl. decision NOT STARTED
        on whether to sync legacy session fields)
S11-07  CLI orchestration / end-to-end flow                NOT STARTED
S11-08  hardening / failure injection                      NOT STARTED
S11-09  full Stage-11 review/completion                    NOT STARTED
```

Smallest first BUILD task after S11-00: **S11-01**.

## 22. S11-00 record

```text
Task:              S11-00 — Post-session Processor Architecture & Stage Kickoff
Routing:           PLAN_REQUIRED -> accepted PLAN -> BUILD (documentation-only)
Baseline:          main @ 513401f807e0808c58e6673a3af73911a0c61de4
                   HEAD == origin/main, clean working tree
Branch:            feat/post-session-processor
Verdict:           S11_ARCHITECTURE_READY
Corrections:       C1 full prepared-input fingerprint
                   C2 input identity vs attempt identity
                   C3 immutable/versioned per-attempt artifacts
                   C4 append-only processing ledger
                   C5 ledger is authority; legacy session fields are not
Deliverable:       this stage record + DEVELOPMENT_STATUS reconciliation +
                  docs/stages/README.md index entry
Next task:         S11-01 — post-session input + durable processing schemas
```

## 23. S11-01 record

```text
Task:              S11-01 — Post-session Input + Durable Processing Schemas
Routing:           PLAN_REQUIRED -> accepted PLAN -> BUILD
Baseline:          feat/post-session-processor @
                   15b522f914cf8b7a99456701f9386ea701c0dd54
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             typed prepared-input identity + fingerprint (C1),
                   trusted attempt identity (C2), processing-ledger event
                   schemas (C4), deterministic model-free eligibility (C5),
                   append-only ledger storage; no model/Summary/Recap/
                   ChangeSet/CLI/orchestration work
Deliverable:       5 production modules + focused unit/integration/contract
                   tests + this record + DEVELOPMENT_STATUS reconciliation
Next task:         S11-02 — deterministic context assembly + entity resolution
```

### 23.1 Implemented modules

```text
domain/post_session.py
    PostSessionAttemptId, LedgerEventId, Sha256Fingerprint/InputFingerprint,
    PreparedInputIdentity + component projections,
    ProcessingLedgerEvent union (attempt_started, artifact_persisted,
    proposal_persisted, attempt_completed, attempt_failed, attempt_superseded),
    ProcessingOutcome / ProcessingPhase / FailureCategory / ArtifactKind
application/post_session_identity.py
    POST_SESSION_PROCESSOR_VERSION / POST_SESSION_PROMPT_VERSION constants,
    new_attempt_id(), canonical_prepared_input_bytes(), compute_input_fingerprint()
application/post_session_ledger.py
    new_ledger_event_id(), serialize/parse/fold, record_ledger_event() policy
application/post_session_eligibility.py
    EligibilityReason / EligibilityResult, evaluate_processing_eligibility()
storage/post_session_processing.py
    PostSessionProcessingStore protocol +
    ObsidianPostSessionProcessingStore (opaque append/read placement)
```

### 23.2 Fingerprint contract

```text
input_fingerprint =
  SHA-256(UTF-8(json.dumps(
      PreppedInputIdentity.model_dump(mode="json", exclude_unset=False),
      sort_keys=True, separators=(",", ":"),
      ensure_ascii=False, allow_nan=False)))
```

`PreparedInputIdentity` binds session projection, ordered raw events, ordered
entity projections, deterministic context projection, calendar projection,
`schema_version`, `processor_version` and `prompt_version`.  It contains no
`attempt_id`, no wall-clock attempt time, no model output, no model profile and
no filesystem path.  Golden literal fingerprint tests pin the canonical bytes
so accidental serialization drift is detected.  `attempt_id` is
`att_<uuid4().hex>` generated by trusted Python; it is opaque, path-safe and
never derived from the fingerprint, so multiple attempts may share one input.

### 23.3 Eligibility contract

`evaluate_processing_eligibility(...)` is read-only and model-free.  It checks
completed status, finish time / end tick presence and ordering, strict event
parse, absence of an active-session contradiction, valid `touched_entities`
and (optional) attempt-terminal state.  Legacy `processed`,
`processed_model_profile` and `processing_status` are never read (C5).  A
corrupt ledger raises `StorageError` (uncertain state fails closed); expected
missing/corrupt evidence returns an ineligible result.  Failure performs zero
writes.

### 23.4 Ledger storage, append and duplicate semantics

Path: `_system/raw/sessions/<session_id>/processing/ledger.jsonl`, derived
only from the validated session id.  Append-only: existing bytes are never
rewritten or truncated.  `append_ledger_line` requires a newline-terminated
line; `read_ledger_if_present` returns `None` for a not-created ledger and
fails closed on symlink/directory/non-UTF-8/unreadable content.

Finalized duplicate/idempotency contract:

```text
same event_id + canonically identical payload -> idempotent logical replay
    - sequential retry returns ALREADY_PRESENT with no physical write;
    - a physically duplicated identical line is folded to one logical event
      preserving first-occurrence order; physical bytes are left untouched;
same event_id + different payload -> ConflictError (record) / StorageError (parse)
repeated attempt_id with different events -> valid, not duplicate evidence
```

Post-append verification tolerates unrelated valid concurrent appends: the
previously read bytes must remain an exact prefix, the complete ledger must
parse strictly, and the caller's logical event must be present with exactly
the expected canonical payload.  Any conflicting identity, prefix violation
or malformed/partial evidence fails closed.  There is no sequence number and
no global lock; physical line order is fold order.

### 23.5 Audit/recovery decision (A9, finalized)

The processing ledger is **unaudited durable workflow/control evidence** under
`_system/raw/sessions/<id>/processing/`.  Ledger appends are **not** recorded
in `_system/audit/audit.jsonl`, matching the established Stage-10
`_system/changesets/*.proposal.json` / `*.apply.jsonl` precedent: durable
workflow artifacts written exclusively/append-only with fail-closed readers
and no `AuditContext`.  The ledger is itself the durable, append-only
provenance trail and Stage 11 performs no canonical campaign mutation (I2).

Recovery non-interference (no new R1-style global wedge): session recovery
scans only direct children of `Sessions/` and `_system/raw/sessions/` and
inspects only `metadata.json` / `events.jsonl`; the `processing/` subdirectory
is invisible to `_inspect_sessions`, and `unresolved_audit_intent` only
considers audit-log records for a session, of which the ledger emits none.
Contract/evidence: `test_ledger_operations_do_not_write_audit_records` and the
integration no-mutation assertion.

### 23.6 Evidence

```text
fingerprint binding      tests/unit/post_session/test_identity.py
                         (full-input changes alter it; attempt id / wall clock do not)
identity + schema        tests/unit/post_session/test_domain.py
eligibility              tests/unit/post_session/test_eligibility.py
ledger semantics         tests/unit/post_session/test_ledger.py
storage/append/audit     tests/unit/post_session/test_storage.py
restart / no mutation    tests/integration/test_post_session_processing.py
boundaries               tests/contract/test_post_session_boundaries.py
```

No Ollama is required.  Quality gates run: focused suites, `ruff check`,
`ruff format --check`, `pyright` (0 errors), full `pytest`, `git diff --check`.

### 23.7 Deferred (S11-02+)

Entity/context projection assembly and resolution (S11-02), model adapter and
extraction (S11-03), Summary/Recap artifacts and visibility filtering (S11-04),
ChangeSet producer (S11-05), full attempt-state folding, tail repair and the
legacy-field sync decision (S11-06), CLI (S11-07), hardening (S11-08), Stage-12.

## 24. S11-02 record

```text
Task:              S11-02 — Deterministic Context Assembly + Entity Resolution
Routing:           PLAN_REQUIRED -> accepted PLAN (2 corrections) -> BUILD
Baseline:          feat/post-session-processor @
                   2dba067677c545aa9bd9ea18ad5b6e8067e126d1
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             deterministic, model-free completed-session context assembly:
                   touched-only selection, exact-ID entity resolution, current
                   canonical entity projection, bounded prepared-input identity
                   and fingerprint; no model/Summary/Recap/ChangeSet/CLI work
Deliverable:       application assembler module + schema v2 + focused
                   unit/integration/contract tests + this record +
                   DEVELOPMENT_STATUS reconciliation
Next task:         S11-03 — heavy-model structured extraction mechanism
```

### 24.1 Implemented module

```text
application/post_session_context.py
    ContextFailureReason / PostSessionContextError,
    PreparedPostSessionInput,
    centralized Stage-11 context bounds (MAX_*),
    render_prepared_context(),
    build_post_session_input()
domain/post_session.py
    PreparedEntityProjection + type (EntityType)
    PreparedInputIdentity.schema_version 1 -> 2
application/post_session_identity.py
    POST_SESSION_PROCESSOR_VERSION "1" -> "2"
application/post_session_eligibility.py
    EligibilityResult.session_revision (observed canonical Session.revision)
```

### 24.2 Accepted selection policy

Selection is **trusted structured evidence only**: the validated
`touched_entities` accepted by S11-01 eligibility, normalized by
order-preserving first-occurrence deduplication. There is **no** event-extra
entity-reference field in the current runtime (the allowlist is empty), **no**
inference of `EntityId` from arbitrary strings, and **no** free-text/name/alias
resolution. The player-only `SearchService` / `EntityResolver` contracts are
deliberately not reused for internal DM context. Entity references resolve by
exact stable `EntityId` via `VaultRepository.get_entity`. A missing touched
entity fails closed; a corrupt entity propagates `StorageError`. Each read is
individually revision-consistent; there is no global snapshot, mixed-time
multi-entity reads are accepted, and the fingerprint binds the exact
projections actually read.

### 24.3 Eligibility-revision binding (Correction 2)

A successful `EligibilityResult` now carries the canonical `Session.revision`
observed during eligibility. The builder re-reads session metadata and fails
closed with `STALE_ELIGIBILITY_EVIDENCE` when the revision no longer matches,
when status is no longer `completed`, or when normalized `touched_entities`
differ from the eligibility result. Session-id mismatch and a missing observed
revision fail with `ELIGIBILITY_MISMATCH`; an ineligible result fails with
`SESSION_INELIGIBLE`. The builder does not re-run the eligibility algorithm.
Raw events remain protected by the accepted completed-session immutability
contract; no new locking or snapshot mechanism is introduced.

### 24.4 Prepared-input schema v2

The old contract was insufficient because canonical entity `type` was absent
from `PreparedEntityProjection`, making typed later extraction/binding
impossible. The projection now includes `type (EntityType)` and the prepared
input is `schema_version = 2`; `processor_version` was bumped to `"2"`.
Golden fingerprint evidence in `tests/unit/post_session/test_identity.py` was
re-pinned. Ledger `schema_version` is untouched.

`PreparedEntityProjection` fields: `id, type, revision, name, status,
visibility, knowledge_status, tags, body_projection`. Deferred deliberately:
`created_session`, `last_seen_session`, `created_at`, `updated_at`, and
storage-level `extra_frontmatter`/`aliases` (needed only by S11-05 binding).

### 24.5 Context bounds (Correction 1)

One centralized, project-owned, character/count-based policy in
`application/post_session_context.py`:

```text
MAX_RAW_EVENTS              = 2000
MAX_RAW_EVENT_EXTRA_CHARS   = 8000
MAX_TOTAL_RAW_EVENT_CHARS   = 2_000_000
MAX_ENTITY_PROJECTIONS      = 200
MAX_ENTITY_BODY_CHARS       = 4000
MAX_TOTAL_CONTEXT_CHARS     = 4_000_000
```

Every ceiling is explicit fail-closed `INPUT_TOO_LARGE`. **Entity bodies are
never truncated**: an over-limit body is rejected, never sliced, and no
truncation marker exists. Canonical evidence is never silently discarded.
Changing any bound is processor semantics and must trigger a
`processor_version` review/bump.

### 24.6 Rendering and calendar policy

`PreparedContextProjection.text` is a pure derived rendering of the structured
session/event/entity/calendar projections, computed in the same pass, so it
cannot diverge from what the fingerprint binds. Only raw `world_tick` start/end
are projected; the current world tick is deliberately not read (a moving clock
must not re-key identical session evidence) and no game dates are fabricated.

### 24.7 Evidence

```text
assembler / bounds / determinism   tests/unit/post_session/test_context.py
eligibility revision binding       tests/unit/post_session/test_eligibility.py
schema v2 + golden fingerprint     tests/unit/post_session/test_identity.py
real-Vault end-to-end/no mutation  tests/integration/test_post_session_context.py
read-only / no-model boundaries    tests/contract/test_post_session_boundaries.py
```

No Ollama is required. Quality gates: focused suites, `ruff check`,
`ruff format --check`, `pyright` (0 errors), full `pytest`, `git diff --check`.

### 24.8 Deferred (S11-03+)

Heavy-model adapter/extraction (S11-03), Summary/Recap artifacts and visibility
filtering (S11-04), ChangeSet producer + canonical binding/ambiguity and
alias resolution (S11-05), full attempt-state folding, tail repair and the
legacy-field sync decision (S11-06), CLI (S11-07), hardening (S11-08),
Stage-12.

## 25. S11-03 record

```text
Task:              S11-03 — Heavy-model Structured Extraction Mechanism
Routing:           PLAN_REQUIRED -> accepted PLAN (2 corrections) -> BUILD
Baseline:          feat/post-session-processor @
                   2c1b75f50902a2d9c74345d716593e8ae41531c6
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             bounded heavy-model structured-extraction boundary:
                   trusted request construction, application-owned protocol,
                   untrusted versioned extraction schema, Python semantic
                   validation, Pydantic AI structured-output adapter with zero
                   project tools, POST_SESSION model role/factory; no Summary/
                   Recap, no ChangeSet, no persistence/ledger/CLI
Deliverable:       4 production modules + profile/factory + prompt-version
                   rebinding + focused unit/integration/contract tests + this
                   record + DEVELOPMENT_STATUS reconciliation
Next task:         S11-04 — Summary/Recap production + visibility filtering
```

### 25.1 Implemented modules

```text
domain/post_session_extraction.py
    PostSessionExtraction + ExtractedClaim / ExtractedEntityMention /
    ExtractedEntityCandidate / ExtractedAttribute,
    ExtractionVisibilityHint / ExtractionKnowledgeHint / ClaimKind,
    project-owned structural bounds, POST_SESSION_EXTRACTION_SCHEMA_VERSION
prompts/post_session_extraction_v1.py
    POST_SESSION_EXTRACTION_PROMPT_ID + fixed extraction instruction
application/post_session_extraction.py
    PostSessionExtractionRequest + ExpectedEntityBinding,
    build_post_session_extraction_request(), PostSessionExtractionModel
    protocol, ExtractionFailureReason / PostSessionExtractionError,
    validate_post_session_extraction(), run_post_session_extraction(),
    ExtractionProvenance / AcceptedPostSessionExtraction
application/pydantic_ai_post_session.py
    PydanticAIPostSessionExtractionModel (zero project tools,
    retries={"tools": 0, "output": 0}, UsageLimits(request_limit=1))
models/profiles.py
    ModelProfileRole.POST_SESSION
models/pydantic_ai_ollama.py
    shared role-aware _build_ollama_model() +
    build_pydantic_ai_post_session_model() (AGENT factory unchanged)
```

### 25.2 Trusted request construction (Correction 1)

The public entrypoint `run_post_session_extraction(model, prepared, ...)`
accepts only the accepted `PreparedPostSessionInput` and derives the request
internally through `build_post_session_extraction_request`.  `session_ref`,
`input_fingerprint`, `context_text`, expected event ids, expected entity
bindings and version fields all originate from the same fingerprinted input;
no caller parameter can substitute them.  `ExpectedEntityBinding`
(`entity_id`, `entity_type`) replaces a bare id set so semantic validation can
prove canonical type binding.  The adapter still uses `context_text` as the
model-visible context; the structured binding snapshot is Python-owned only.

### 25.3 Schema, visibility, knowledge, candidates

The extraction is an untrusted semantic representation, not a ChangeSet.
Evidence event ids are mandatory (min 1) on every claim, mention and candidate.
Visibility and knowledge are distinct untrusted hint enums, never canonical
`Visibility`/`KnowledgeStatus`.  New-entity candidates carry no final
`EntityId` and no create operation.  `extra="forbid"` structurally excludes
`expected_revision`/operation fields.  Unsupported entity types are rejected at
schema level.

### 25.4 Semantic binding policy

Unknown evidence ids fail closed (`INVALID_EVIDENCE_REFERENCE`).  A claimed
existing entity id is trusted only when selected in the prepared input **and**
the declared type matches the canonical prepared type; otherwise it is cleared
from the sanitized extraction and recorded as an `UnresolvedEntityReference`
(`NOT_IN_PREPARED_INPUT` / `TYPE_MISMATCH` / `NO_CANDIDATE_ID`) for S11-05.
Evidence normalization is applied at every evidence-bearing level (claim,
mention and candidate): every event id is validated against the prepared input
and order-preserving first-occurrence deduplicated, and the sanitized accepted
extraction carries the normalized tuple.  A mention's normalized evidence and
sanitized candidate id are returned together, so clearing a fabricated or
type-mismatched id does not discard normalization.  Duplicate claim/mention ids
and duplicate `candidate_id` fail closed with distinct reasons
(`DUPLICATE_CLAIM_ID` / `DUPLICATE_MENTION_ID` / `DUPLICATE_CANDIDATE_ID`); all
three map to the durable `INVALID_OUTPUT` category.  Total-size/mention-count
bounds fail closed.

### 25.5 Error mapping (observed Pydantic AI 2.39 path)

`UnexpectedModelBehavior` (output retries exhausted) -> `INVALID_STRUCTURED_OUTPUT`.
`ModelHTTPError` -> `MODEL_INVOCATION_FAILED`.  `ModelAPIError` is classified
by its observed public cause chain: `openai.APITimeoutError` -> `MODEL_TIMEOUT`,
`openai.APIConnectionError` -> `MODEL_UNAVAILABLE`, otherwise
`MODEL_INVOCATION_FAILED`.  Any other `AgentRunError` ->
`MODEL_INVOCATION_FAILED`, preserving `__cause__`.  `PostSessionExtractionError`
subclasses `ModelError` and maps `reason` to the durable `FailureCategory`.
No broad `OSError` classification is used.

### 25.6 Prompt-version rebinding

`POST_SESSION_PROMPT_VERSION` is now bound to `POST_SESSION_EXTRACTION_PROMPT_ID`
(`post-session-extraction-v1`): the extraction-stage prepared prompt material
(context rendering + fixed instruction) participating in the prepared-input
fingerprint.  The golden fingerprint literal in
`tests/unit/post_session/test_identity.py` was re-pinned.  Summary/Recap
rendering prompts (S11-04) remain a separate contract.

### 25.7 Evidence

```text
schema / bounds / extra-forbid     tests/unit/post_session/test_extraction_domain.py
request binding / semantic rules   tests/unit/post_session/test_extraction_policy.py
adapter zero-tools / retries / err tests/unit/post_session/test_pydantic_ai_post_session.py
POST_SESSION role / factory        tests/unit/test_model_profiles.py,
                                   tests/unit/test_pydantic_ai_ollama.py
real-Vault zero-write              tests/integration/test_post_session_extraction.py
dependency boundaries              tests/contract/test_post_session_boundaries.py
```

Observed adapter facts: `info.function_tools == ()`, one output-tool
(`final_result`), exactly one model request under an output-validation failure.
No Ollama is required.  Quality gates: focused suites, `ruff check`,
`ruff format --check`, `pyright` (0 errors), full `pytest`, `git diff --check`.

### 25.8 Deferred (S11-04+)

Summary/Recap artifacts and visibility filtering (S11-04), ChangeSet producer +
canonical binding/ambiguity and alias resolution (S11-05), full attempt-state
folding, tail repair and the legacy-field sync decision (S11-06), CLI (S11-07),
hardening (S11-08), Stage-12.
