# Stage 11 — Post-session Processor

## Status

```text
Stage 11 — DONE
S11-00 — DONE
S11-01 — DONE
S11-02 — DONE
S11-03 — DONE
S11-04 — DONE
S11-05 — DONE
S11-06 — DONE
S11-07 — DONE
S11-08 — DONE
S11-09 — DONE
Stage 12 — NOT STARTED
```

Architecture verdict:

```text
S11_ARCHITECTURE_READY
```

This document is the canonical Stage-11 architecture record, task map and
implementation history. The contract and evidence-plan sections retain their
original wording; the per-task records below describe what each task deferred
at the time it ran and are not rewritten after later tasks complete. Stage 11
is complete (see the S11-09 completion record).

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
(fail-safe).

Finalized by S11-04 (supersedes earlier permissive wording): because raw events
have no visibility field, **a claim is recap-eligible only when its untrusted
`visibility_hint` is `player` AND it has at least one canonical resolved
entity binding AND every referenced canonical entity is `Visibility.PLAYER`
AND it carries no unresolved reference.** A player-hinted claim with no
canonical entity binding is excluded (`no_canonical_player_safe_evidence`);
`ExtractionVisibilityHint` never authorizes player disclosure by itself.
Excluded claims are dropped whole; a hidden entity name is never redacted out
of surrounding claim text. New-entity candidates never enter Recap.

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
S11-03  heavy-model structured extraction mechanism        DONE
S11-04  Summary/Recap production + visibility filtering    DONE
S11-05  ChangeSet producer integration + ambiguity policy  DONE
S11-06  persistence/rerun/failure semantics (incl. decision DONE
        on whether to sync legacy session fields)
S11-07  CLI orchestration / end-to-end flow                DONE
S11-08  hardening / failure injection                      DONE
S11-09  full Stage-11 review/completion                    DONE
```

Smallest first BUILD task after S11-00 was **S11-01** (historical).

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

## 26. S11-04 record

```text
Task:              S11-04 — Summary/Recap Production + Deterministic Visibility Filtering
Routing:           PLAN_REQUIRED -> accepted PLAN (5 corrections) -> BUILD
Baseline:          feat/post-session-processor @
                   fb04a1b9f72a6284e636929b1e90c2430df8852a
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             in-memory Summary/Recap generation over accepted S11-03
                   extraction: deterministic player-safe Recap filtering,
                   complete provenance binding, structurally distinct request
                   types, provider-neutral rendering protocol, Pydantic AI
                   rendering adapter, separate render prompts; no persistence/
                   ledger/audit/ChangeSet/CLI/S11-05/Stage-12
Deliverable:       7 production modules + 1 bounded adapter refactor + focused
                   unit/integration/contract tests + this record +
                   DEVELOPMENT_STATUS reconciliation
Next task:         S11-05 — ChangeSet producer integration + ambiguity policy
```

### 26.1 Implemented modules

```text
domain/post_session_artifacts.py
    POST_SESSION_RENDER_SCHEMA_VERSION, MAX_RENDER_BODY_CHARS,
    RenderOutcome, PostSessionRenderOutput (multi-line Markdown body validation)
application/post_session_visibility.py
    RecapEntityRef, SummaryEntityRef (SYSTEM structurally rejected),
    RecapClaimProjection, SummaryClaimProjection,
    SummaryUnresolvedReferenceProjection, SummaryCandidateProjection,
    Recap/Summary exclusion reasons + diagnostics,
    project_recap(), project_summary()
application/post_session_rendering.py
    SummaryRenderRequest, RecapRenderRequest (structurally distinct),
    PostSessionRenderingModel protocol, deterministic serializers,
    RenderingProvenance, RenderedPostSessionArtifact,
    RenderingFailureReason / PostSessionRenderingError,
    _verify_provenance(), generate_summary(), generate_recap()
application/pydantic_ai_post_session_rendering.py
    PydanticAIPostSessionRenderingModel (zero project tools,
    retries={"tools": 0, "output": 0}, UsageLimits(request_limit=1))
application/pydantic_ai_model_errors.py
    ModelFailureKind + classify_model_api_error() shared neutral classifier
prompts/post_session_summary_v1.py, prompts/post_session_recap_v1.py
    distinct artifact-generation prompt ids + instructions
application/pydantic_ai_post_session.py
    bounded behavior-preserving refactor: private classifier now delegates to
    the shared neutral classifier (S11-03 behavior unchanged)
```

### 26.2 Finalized Summary authorization algorithm

For every accepted claim, Python builds a `SummaryClaimProjection` unless it
references a canonical entity that is unavailable or `Visibility.SYSTEM`, in
which case the whole claim is excluded (`REFERENCES_SYSTEM_ENTITY` /
`REFERENCES_UNAVAILABLE_ENTITY`).  PLAYER and DM canonical entities are
eligible.  SYSTEM entity metadata/body/text never reaches the Summary model
input; SYSTEM rejection is also structural (`SummaryEntityRef` validator).
Unresolved references and new-entity candidates enter Summary only as
structurally distinct non-canonical material. `visibility_hint` /
`knowledge_hint` are exposed as untrusted labels only.

### 26.3 Finalized Recap authorization algorithm

```text
claim eligible  <=>  visibility_hint == PLAYER
                AND  has >= 1 canonical resolved entity binding
                AND  every referenced canonical entity is Visibility.PLAYER
                AND  contains no unresolved reference
```

Bounded exclusion reasons: `visibility_hint_not_player`,
`contains_unresolved_reference`, `no_canonical_player_safe_evidence`,
`references_non_player_entity`, `references_unavailable_entity`.  Exclusion is
whole-claim; hidden text is never redacted out.  Candidates and unresolved
references never enter Recap.  Canonical prepared entity visibility always
outranks the untrusted model hint.

### 26.4 Structurally distinct requests and provenance binding

`SummaryRenderRequest` and `RecapRenderRequest` are separate frozen models.
The Recap type has no field able to carry unresolved references, candidates,
DM/SYSTEM projections, canonical bodies, the full extraction or the full
prepared context.  Before any model call, `generate_summary` / `generate_recap`
verify `session_ref`, `input_fingerprint`, `processor_version`,
`prompt_version`, `extraction_schema_version` and the extraction's own
`schema_version` against the prepared input; any mismatch raises
`PROVENANCE_MISMATCH` (durable `FINGERPRINT_MISMATCH`) with zero renderer calls.

### 26.5 EMPTY outcome and render prompts

`RenderOutcome.RENDERED` requires a non-empty `content`; `RenderOutcome.EMPTY`
requires `content is None` and is produced deterministically with **zero model
calls** when no claim is Recap-eligible.  Model-generated empty/whitespace
output remains an error (`EMPTY_OUTPUT`).  Summary/Recap render prompt ids are
distinct from `POST_SESSION_PROMPT_VERSION` and do not participate in
`input_fingerprint`; only the exact rendering inputs are reproducible, not the
model prose.

### 26.6 No persistence

S11-04 writes nothing.  Success, EMPTY and render-failure paths leave the Vault
byte-identical with no ledger, audit or ChangeSet artifact.  Durable EMPTY
representation is an S11-06 decision.

### 26.7 Evidence

```text
render output schema / bounds     tests/unit/post_session/test_artifacts_domain.py
visibility policy / binding /     tests/unit/post_session/test_rendering_policy.py
  canaries / EMPTY
Pydantic AI rendering adapter     tests/unit/post_session/test_pydantic_ai_post_session_rendering.py
real-Vault zero-write + canary    tests/integration/test_post_session_rendering.py
dependency boundaries             tests/contract/test_post_session_boundaries.py
S11-03 adapter regression         tests/unit/post_session/test_pydantic_ai_post_session.py
```

Actual model-visible canary proofs: the serialized `RecapRenderRequest` passed
to the capturing fake contains no DM/SYSTEM/unresolved/candidate canary, and an
echo renderer's resulting Recap body is likewise clean; the Summary request
contains the authorized DM canary and no SYSTEM canary.  Adapter tests inspect
the actual `FunctionModel` message payload.  No Ollama is required.  Quality
gates: focused suites, `ruff check`, `ruff format --check`, `pyright` (0
errors), full `pytest`, `git diff --check`.

### 26.8 Deferred (S11-05+)

ChangeSet producer + canonical binding/ambiguity and alias resolution (S11-05),
artifact/ledger persistence + durable EMPTY representation + attempt-state
folding + legacy-field sync decision (S11-06), CLI orchestration (S11-07),
hardening (S11-08), Stage-11 review (S11-09), Stage-12.

## 27. S11-05 record

```text
Task:              S11-05 — ChangeSet Producer Integration + Ambiguity Policy
Routing:           PLAN_REQUIRED -> accepted PLAN (2 correction rounds) -> BUILD
Baseline:          feat/post-session-processor @
                   91922cc945160ee2c7a6fd57335e592b69999d0f
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             deterministic, model-free post-session ChangeSet production
                   over the accepted S11-03 extraction: create_entity (Python
                   defaults + deterministic candidate EntityId) and append_fact
                   (whole-claim exact binding), type-aware exact name/alias
                   resolution, full prepared-vs-current stale detection,
                   whole-Vault duplicate prevention, final Stage-10 preflight;
                   no update_entity, no persistence/ledger/review/apply/CLI
Deliverable:       5 production modules + 1 retrieval helper extraction + focused
                   unit/integration/contract tests + this record +
                   DEVELOPMENT_STATUS reconciliation
Next task:         S11-06 — persistence/rerun/failure semantics
```

### 27.1 Implemented modules

```text
retrieval/exact_matching.py
    normalize_exact_text (strip -> NFC -> casefold) and fail-closed
    extract_exact_aliases; the single shared exact-text/alias grammar
retrieval/search.py (refactor, behavior-preserving)
    _normalize_text / _extract_aliases delegate to the shared helper
application/entity_id_allocator.py
    CANDIDATE_ENTITY_ID_ALLOCATOR_VERSION, candidate_identity_material,
    canonical_candidate_identity_bytes, allocate_candidate_entity_id
application/post_session_provenance.py
    extraction_binding_mismatches (shared S11-04/S11-05 binding policy)
application/post_session_binding.py
    ExactMatchIndex, build_exact_index, resolve_mention_targets,
    any_type_exact_matches, prepared_projection_matches
application/post_session_changeset.py
    PostSessionChangeFailureReason / PostSessionChangeError,
    PostSessionChangeUnresolvedReason / PostSessionChangeUnresolved,
    PostSessionOperationProvenance, PostSessionChangeOutcome,
    PostSessionChangePlanResult, produce_post_session_changeset
application/post_session_rendering.py (refactor, behavior-preserving)
    _verify_provenance delegates to the shared binding helper
```

### 27.2 Operation support matrix

```text
create_entity   YES  genuine ExtractedEntityCandidate
append_fact     YES  existing prepared entity, whole-claim exact binding
update_entity   NO   no typed canonical field-update semantic in S11-03;
                     deriving it from prose is forbidden
```

### 27.3 Finalized create/default policy

`create_entity` is emitted only for a genuine candidate after duplicate
prevention. The only model-derived fields are `display_name` and `entity_type`;
every other field is Python-owned:

```text
status="unknown"      Visibility.DM      KnowledgeStatus.INFERRED
created_session = last_seen_session = real session_ref      tags=()
```

`candidate.attributes`, `candidate.summary`, `visibility_hint` and
`knowledge_hint` never influence any emitted field. `update_entity` semantics
(e.g. converting "became hostile" into `status=...`) are not implemented.

### 27.4 EntityId allocator policy

```text
material = {allocator_version="post-session-entity-id-v1", session_ref,
            entity_type.value, normalize_exact_text(display_name)}
bytes    = compact key-sorted UTF-8 JSON, allow_nan=False
entity_id= "ent_" + sha256(bytes).hexdigest()[:32]
```

Evidence event refs and model `candidate_id` are excluded, so the same semantic
candidate over the same session allocates the same `EntityId` across attempts
regardless of the evidence the model selected. Identity is candidate-scoped
(not attempt-scoped). Two distinct candidates in one extraction producing the
same allocation identity fail closed (`entity_id_collision`); neither create is
emitted. No randomness exists in the allocator.

### 27.5 Internal exact resolver and alias policy

Binding uses `VaultRepository` reads only (`list_entities`), builds a type-aware
exact index (`(entity_type, normalized name)`, `(entity_type, normalized
alias)`), and resolves `exact stable ID -> exact canonical name -> exact
canonical alias`. Name tier outranks alias tier. A name/alias belonging only to
another `EntityType` stays unresolved. No fuzzy/FTS/substring binding. The
player-only `SearchService` / `EntityResolver` / `VaultSearchService` are not
imported or used; only the pure `retrieval.exact_matching` helper is shared.
Aliases come from canonical `extra_frontmatter["aliases"]` under the existing
fail-closed grammar. A resolved target outside the prepared entity set is
rejected (`target_not_in_prepared_context`).

### 27.6 Whole-claim ambiguity policy

```text
0 unique canonical targets                 -> omit claim (no_canonical_target)
1 unique target + any unresolved mention   -> omit WHOLE claim (unresolved_reference)
>1 distinct target ids                     -> omit WHOLE claim (unsupported_multi_target)
1 unique target + zero unresolved mentions -> append eligible
```

Multiple mentions resolving to the same `EntityId` remain one valid target. A
claim is never appended to one entity while another mention is unresolved. A
`FACT`/`EVENT` claim is appendable; `RELATIONSHIP`/`OTHER` are omitted with
`unsupported_claim_kind`.

### 27.7 Stale / duplicate / revision policy

For every mutation target, current canonical state is compared field-by-field
against the prepared projection: `id`, `type`, `revision`, `name`, `status`,
`visibility`, `knowledge_status`, `tags`, and the **full body**. Any difference
is `stale_prepared_entity` and is never rebased, even when the numeric revision
is unchanged by an external editor. `PLAYER` and `DM` targets may receive
proposals; `SYSTEM` targets cannot (`system_entity_excluded`). Exact
duplicate facts already present in the body (or already emitted in the batch)
are suppressed with `duplicate_fact`; no fuzzy/semantic comparison is used.
Same-entity append expected revisions are `R, R+1, ...` in final order.

Candidate duplicate prevention scans the whole current Vault including SYSTEM
and all entity types: an existing allocated id (same vs different identity),
any exact normalized name/alias match, and multiple matches respectively yield
`duplicate_existing_entity` / `entity_id_collision` / `ambiguous_exact_match`;
no fuzzy create decision exists.

### 27.8 Ordering, preflight, NO_CHANGES and persistence

```text
order            create_entity (candidate order), then append_fact (claim order)
final gate       every non-empty ChangeSet passes validate_changeset(changeset, repository)
failure          invalid preflight fails closed (CHANGESET_PREFLIGHT_FAILED)
zero operations  NO_CHANGES, changeset=None, never an empty ChangeSet
provenance       Provenance.MODEL_INFERENCE + extraction model_profile/prompt_version
identity         changeset_id = cs_<session_ref>_<attempt_id>
persistence      S11-05 writes nothing; Stage-10 persist_proposal is S11-06
```

S11-05 calls only `list_entities` (binding) plus the read-only preflight. It
creates no approval, applies nothing, mutates no canonical entity, writes no
audit or ledger record, and therefore introduces no R1-style recovery wedge.

### 27.9 Evidence

```text
shared helper + retrieval delegation  tests/unit/post_session/test_retrieval_exact_matching.py
allocator determinism/material         tests/unit/post_session/test_entity_id_allocator.py
type-aware exact binding + stale       tests/unit/post_session/test_changeset_binding.py
producer policy/idempotency/preflight  tests/unit/post_session/test_changeset_producer.py
real-Vault zero-write/stale/ambiguity  tests/integration/test_post_session_changeset.py
dependency boundaries                  tests/contract/test_post_session_boundaries.py
```

No Ollama is required. Quality gates: focused suites, `ruff check`,
`ruff format --check`, `pyright` (0 errors), full `pytest`, `git diff --check`.

### 27.10 Deferred (S11-06+)

Artifact/ledger persistence + durable EMPTY representation + attempt-state
folding + legacy-field sync decision (S11-06), CLI orchestration (S11-07),
hardening (S11-08), Stage-11 review (S11-09), Stage-12.

## 28. S11-06 record

```text
Task:              S11-06 — Persistence / Rerun / Failure Semantics
Routing:           PLAN_REQUIRED -> accepted PLAN (2 correction rounds) ->
                   accepted final correction (portable interprocess ledger lock)
                   -> BUILD
Baseline:          feat/post-session-processor @
                   5f30632fba9e1120ab053fcfdcf8bcf38f71b566
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             crash-aware durable processing workflow: full structural
                   attempt-state fold; atomic per-attempt claim; portable
                   interprocess ledger lock + single-write append; immutable
                   per-attempt Summary/Recap/workflow persistence; durable EMPTY
                   recap; terminal integrity verification; same-attempt
                   idempotency; interrupted/orphan-claim policy; bounded typed
                   failure recording; legacy-field no-sync decision; no CLI
Deliverable:       6 production modules + 2 storage changes + focused
                   unit/integration/contract tests + this record +
                   DEVELOPMENT_STATUS reconciliation
Next task:         S11-07 — CLI orchestration / end-to-end flow
```

### 28.1 Implemented modules

```text
domain/post_session.py                         edit (PersistedArtifactKind;
                                               ArtifactPersisted uses it;
                                               ProcessingOutcome docstrings)
domain/post_session_workflow.py                new  (workflow evidence schema +
                                               MAX_WORKFLOW_ARTIFACT_BYTES=2_000_000,
                                               MAX_WORKFLOW_DIAGNOSTIC_CHARS=2000)
application/post_session_attempt_state.py      new  (structural fold only)
application/post_session_integrity.py          new  (terminal integrity verifier)
application/post_session_persistence.py        new  (artifact bytes/hash/bounds,
                                               EMPTY placeholder, workflow build)
application/post_session_clock.py              new  (injectable real-time)
application/post_session_processor.py          new  (orchestrator)
application/post_session_processor_support.py  new  (result contracts + durable
                                               event helpers)
storage/post_session_processing.py             edit (portable interprocess lock +
                                               single O_APPEND write hardening)
storage/post_session_artifacts.py              new  (atomic claim + immutable
                                               artifact store)
```

### 28.2 Structural fold vs terminal integrity (accepted correction C2)

`fold_attempt_state` owns only structural/event-sequence invariants:
`event_before_start`, `multiple_started`, `duplicate_artifact_slot`,
`multiple_proposal_events`, `multiple_terminal`, `event_after_terminal`,
`session_ref_mismatch`, plus the bounded states `NOT_STARTED`, `STARTED`,
`COMPLETED`, `FAILED`, `SUPERSEDED`.  A legacy completed ledger folds to
`COMPLETED` and is **never** reclassified as malformed; old ledger lines are
never rewritten or migrated.

S11-06 artifact/proposal inventory, existence, hash and fingerprint
completeness live in `application/post_session_integrity.py`
(`verify_terminal_integrity`), which reports `TERMINAL_EVIDENCE_INCOMPLETE`,
`ARTIFACT_MISSING`, `ARTIFACT_HASH_MISMATCH`, `ARTIFACT_PATH_MISMATCH`,
`PROPOSAL_MISSING`, `PROPOSAL_FINGERPRINT_MISMATCH`, `UNEXPECTED_PROPOSAL`,
`WORKFLOW_EVIDENCE_INVALID` or `WORKFLOW_EVIDENCE_INCONSISTENT`.  A legacy
completed ledger therefore fails closed with `terminal_evidence:*` while
remaining structurally `COMPLETED`.

### 28.3 PersistedArtifactKind / ArtifactKind separation (accepted correction C3)

`ArtifactKind` stays render-only (`SUMMARY`, `RECAP`) and remains the type of
`RenderingProvenance.artifact_kind` and the S11-04 render APIs.
`PersistedArtifactKind` (`SUMMARY`, `RECAP`, `WORKFLOW`) owns the durable
`ArtifactPersisted.artifact_kind`, the storage slot/path mapping, the
attempt-state slot map and terminal integrity.  Overlapping JSON values
(`"summary"` / `"recap"`) are byte-identical, so existing S11-01 ledger history
parses and re-serializes unchanged; a render path can never receive a
`WORKFLOW` kind.

### 28.4 Same-attempt concurrency: atomic claim (accepted correction C1)

The append-then-reread design was replaced by an atomic per-attempt claim
(`_system/raw/sessions/<id>/processing/attempts/<attempt_id>/` via
`mkdir(exist_ok=False)`) performed **before** `AttemptStarted`.  Exactly one
racer creates the claim; a loser gets `ALREADY_EXISTS`, fails closed with zero
ledger writes and zero model calls and requires a new attempt id.  The claim is
**not** state authority: claim-exists + ledger `NOT_STARTED` is uncertain
pre-start evidence (orphan claims are never auto-deleted).  Artifact persistence
requires the already-claimed directory and never races to create it.  The claim
solves same-attempt execution ownership; it does not replace the ledger.

### 28.5 Ledger append hardening: portable interprocess lock

`ObsidianPostSessionProcessingStore` now serializes every ledger read/write with
a per-session interprocess lock (`processing/ledger.lock`; POSIX
`fcntl.flock(LOCK_EX)` / Windows `msvcrt.locking(LK_NBLCK)` retry loop).  The
lock file is synchronization infrastructure only: no payload, not state, not
evidence, not an artifact slot, never audited; the descriptor is always closed
in `finally` and the lock is always released.  The Windows retry loop retries
only classified lock *contention* (`errno.EACCES`/`errno.EDEADLK` or the
sharing/lock-violation `winerror` values); every other `OSError` is a permanent
failure that propagates and is mapped to `StorageError`, never spun on.  An
unlock failure on an otherwise successful operation is a `StorageError`; when
the locked operation already failed, a secondary unlock failure is suppressed so
the primary failure is preserved.  The append encodes the complete line once and
performs exactly one
`O_APPEND|O_CREAT|O_BINARY` `os.write`; a short write fails closed and never
appends the remainder, and the ledger is never truncated or repaired.  Platform
imports are isolated so the storage module imports on Windows and POSIX.
`record_ledger_event` keeps its read -> append -> post-read exact-prefix /
strict-parse / event-presence verification, which tolerates unrelated
concurrent appenders.

### 28.6 Terminal idempotency, current-input binding, interruption

```text
same input_fingerprint + same attempt_id + COMPLETED
    -> verify artifact existence/hash/path + proposal fingerprint/inventory
    -> ALREADY_TERMINAL, zero model calls, zero writes
same terminal attempt + changed current input   -> FINGERPRINT_MISMATCH, fail closed
same attempt_id + STARTED (no terminal)         -> INTERRUPTED, never reruns model
same attempt_id + orphan claim (ledger NOT_STARTED) -> INTERRUPTED (uncertain), new attempt
new trusted attempt_id over same input          -> allowed (new artifacts + changeset id)
```

A terminal attempt is never returned on `attempt_id` alone: the processor always
rebuilds the prepared input and compares the fresh `input_fingerprint` with
`attempt_started.input_fingerprint` first.

### 28.7 Artifact layout, immutability and durable EMPTY

```text
_system/raw/sessions/<session_id>/processing/attempts/<attempt_id>/summary.md
.../recap.md
.../workflow.json
```

Storage derives all paths itself (validated session id + `att_<32hex>` attempt
id; no caller path; traversal/symlink/leaf rejection).  Absent -> exclusive
create + fsync + exact read-back verification -> `CREATED`; identical existing
bytes -> `ALREADY_PRESENT` (zero write); differing bytes -> `ConflictError`.
A durably EMPTY Recap is persisted as the deterministic Python-owned
`EMPTY_RECAP_ARTIFACT_TEXT` placeholder with a normal `artifact_persisted`
event, so EMPTY is never inferred from file absence and every completed attempt
has a verifiable Recap artifact.  Summary is always a RENDERED body.

### 28.8 Workflow evidence, provenance and bounds (accepted correction C4)

`AttemptWorkflowEvidence` durably retains rendering provenance/outcome for
Summary and Recap, extraction provenance and the full S11-05 change plan
(outcome, unresolved diagnostics, operation provenance, produced
`changeset_id`/fingerprint).  It is derived workflow evidence, not campaign
truth, not a parallel ChangeSet and not a processing-state authority; it is
referenced by an `artifact_persisted` event and hash-verified on restart.

`schema_version` is exactly `Literal[1]` (`POST_SESSION_WORKFLOW_SCHEMA_VERSION
= 1`).  A hash-consistent persisted artifact carrying any other integer
(`0`, `2`, ...) is not valid workflow evidence: it fails closed as
`WORKFLOW_EVIDENCE_INVALID` via terminal integrity.  No migration is performed
and existing v1 artifacts are unchanged.

`MAX_WORKFLOW_ARTIFACT_BYTES = 2_000_000` is validated over the exact canonical
UTF-8 bytes that would be persisted (justified by the bounded S11-03 extraction
of at most 500 000 chars); exceeding it fails closed with no write and an
`AttemptFailed` when recording succeeds.  Each diagnostic `detail` is
deterministically truncated to `MAX_WORKFLOW_DIAGNOSTIC_CHARS = 2000` on a
character boundary (canonical campaign evidence is never truncated).

### 28.9 Persistence order and crash windows

```text
attempt_started durable (pre-model) -> summary.md -> artifact_persisted
-> recap.md -> artifact_persisted -> workflow.json -> artifact_persisted
-> [proposal persisted + verified -> proposal_persisted]
-> attempt_completed
```

Crash windows are classified: after claim before start -> uncertain pre-start
(new attempt); after start before/among artifacts -> interrupted/STARTED (no
model on retry); after proposal file before `proposal_persisted` or before
`attempt_completed` -> interrupted, proposal remains independently reviewable;
uncertain `attempt_completed` append -> re-fold and return success only when the
exact logical terminal event is proven present, otherwise fail closed.  No
cross-file atomicity is claimed.

### 28.10 Orphan proposal semantics

A Stage-11-produced proposal is a complete standalone Stage-10 workflow
artifact; human review + exact-fingerprint approval + fresh apply preflight
remain mandatory, and Stage-11 terminal state neither grants nor revokes Stage-10
apply authority.  A proposal surviving a crash may remain reviewable, but its
existence never makes Stage-11 infer `COMPLETED`; a `STARTED`/`FAILED` attempt
stays `STARTED`/`FAILED` per the ledger.  No Stage-10 ownership gate or parallel
ChangeSet format is introduced.

For a structurally completed `NO_CHANGES` terminal, terminal integrity verifies
**both** that no `proposal_persisted` ledger event was recorded **and** that no
Stage-10 proposal artifact exists for the attempt's deterministic changeset id
`cs_<session_ref>_<attempt_id>` (via `ChangeSetStore.read_proposal_if_present`).
An orphan proposal file without a `proposal_persisted` event fails closed as
`UNEXPECTED_PROPOSAL`, as does malformed/unreadable candidate state.  The orphan
is neither deleted nor mutated and never alters the ledger fold.

### 28.11 Failure recording and typed wording (accepted correction C5)

After `attempt_started` is durable, any caught failure appends exactly one
bounded `AttemptFailed`; `message` is project-owned wording, never
`sanitize(str(exc))`:

```text
extraction  -> "Post-session extraction failed: <reason>"
rendering   -> "Post-session rendering failed: <reason>"
validation  -> "Post-session ChangeSet production failed: <reason>"
persistence -> "Artifact persistence failed" | "ChangeSet proposal conflict" |
               "Processing storage failure" | "Workflow evidence invalid: <reason>"
unexpected  -> "Internal processing error"
```

Phase/category mapping: extraction->`EXTRACTION`, ChangeSet->`VALIDATION`,
rendering->`RENDERING`, artifact/proposal/storage->`PERSISTENCE`, unexpected->
the active phase with `INTERNAL_ERROR`.  No traceback, raw model output,
provider body, absolute path or exception repr is persisted.  If recording the
failure itself fails, `PostSessionFailureRecordingError` is raised and the
attempt remains `STARTED` (interrupted); a terminal state is never claimed.

### 28.12 Legacy Session-field decision (accepted C5 outcome)

```text
Session.processed / Session.processed_model_profile / processing_status
remain unchanged and NON-authoritative; S11-06 does not synchronize them.
```

Reasons: the ledger is already the accepted authority; `SessionMetadataRepository`
exposes no post-close mutation for these fields (adding one would create a new
audited mutation/recovery surface); completed-session metadata is prepared-input
evidence; and `PreparedSessionProjection` carries `Session.revision`, so any
metadata mutation would perturb future input fingerprints.

### 28.13 R1 / zero canonical mutation

Ledger, lock and attempt artifacts are unaudited workflow evidence and never
write `_system/audit/audit.jsonl`; `processing/` remains invisible to generic
session recovery (the only new durable files are `ledger.jsonl` and the
synchronization-only `ledger.lock`).  The processor never calls
`create_entity`/`patch_entity`/`append_entity_fact`/`apply_changeset`; the only
writes are the processing ledger, attempt-local artifacts and the existing
Stage-10 `persist_proposal`.

### 28.14 Evidence

```text
structural fold / legacy COMPLETED      tests/unit/post_session/test_attempt_state.py
terminal integrity reasons              tests/unit/post_session/test_integrity.py
workflow schema/bounds/multibyte        tests/unit/post_session/test_workflow_domain.py
artifact store + claim + immutability   tests/unit/post_session/test_artifact_persistence.py
portable lock / short write / release   tests/unit/post_session/test_ledger_lock.py
multiprocessing append concurrency      tests/unit/post_session/test_ledger_append_concurrency.py
typed failure mapping                   tests/unit/post_session/test_processor_failure_mapping.py
idempotency / rerun / interruption /    tests/integration/test_post_session_processor.py
  crash windows / zero mutation
failure wording / conflicts /           tests/integration/test_post_session_processor_failure.py
  uncertain terminal / record failure
restart + lock file                     tests/integration/test_post_session_processing.py
boundary contract                       tests/contract/test_post_session_boundaries.py
maintainability (<=700 production)      tests/contract/test_maintainability.py
```

No Ollama is required.  Gates run: focused suites, `ruff check`,
`ruff format --check`, `pyright` (0 errors), full `pytest` (6044 passed,
120 skipped), `git diff --check`.

### 28.15 Deferred (S11-07+)

CLI orchestration (S11-07), lease/heartbeat-based interrupted finalization,
supersession API, human-facing latest projection, hardening/failure injection
(S11-08), Stage-11 review (S11-09), Stage-12.

## 29. S11-07 record

```text
Task:              S11-07 — CLI Orchestration / End-to-End Flow
Routing:           PLAN_REQUIRED -> accepted PLAN (2 mandatory corrections) ->
                   BUILD
Baseline:          feat/post-session-processor @
                   4ff387c3506569b41f6a82784b710d9d3d776592
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             focused CLI exposure of the accepted S11-06 processor:
                   `dnd session process` selector + POST_SESSION runtime
                   composition/model lifetime + typed result rendering + exit
                   codes + recovery preflight; read-only integrity-verified
                   `dnd session outputs`; no processing/model/storage policy in
                   Typer; no ChangeSet approve/apply
Deliverable:       2 new CLI modules + 1 new application read-model + command
                   registration + focused unit/integration/contract tests +
                   this record + DEVELOPMENT_STATUS reconciliation
Next task:         S11-08 — hardening / failure injection
```

### 29.1 Implemented modules

```text
cli/post_session.py                     new  (Typer commands + Russian rendering;
                                              selector validation; exit codes)
cli/post_session_runtime.py             new  (POST_SESSION profile loading,
                                              metadata selector composition,
                                              concrete dependency wiring,
                                              model lifetime)
application/post_session_outputs.py     new  (read-only ledger attempt query,
                                              reuses fold_attempt_state +
                                              verify_terminal_integrity)
cli/main.py                             edit (register `process`/`outputs` on the
                                              existing session_app)
```

The application processor and its support module remain protocol-only and
concrete-storage-free; all concrete wiring stays in the CLI composition module.

### 29.2 Exact command syntax

```text
dnd session process [SESSION_ID] --vault PATH --config PATH --profile NAME [--latest]
dnd session outputs <SESSION_ID> --vault PATH
```

`process` is registered on the existing `session` group (`start`/`status`/`end`
unchanged); `outputs` is added alongside it. Registration happens through
`cli.post_session.register_session_process_commands(session_app)` so
`cli/session.py` never imports `cli/post_session.py` (no circular CLI import).

### 29.3 Selector and `--latest` policy

```text
exactly one of SESSION_ID / --latest required; both or neither -> CLI error
  before any model construction, attempt claim or write
explicit SESSION_ID -> resolved via SessionMetadataRepository.get_session_metadata
  (missing session -> bounded error, zero model construction)
--latest  -> completed sessions only; ordering key
  (real_finished_at, id_rank); id_rank is numeric-aware for ^S(\d+)$
  zero completed            -> bounded error
  completed missing finish  -> fail closed (never silently skipped for an
                               older valid session)
  active sessions           -> excluded, never block
  corrupt metadata          -> list_session_metadata fails closed
```

`--latest` means the latest **completed** session, not the latest unprocessed
session. Repeated invocation is a deliberate new attempt (new trusted id), so an
already-terminal session is never skipped.

### 29.4 POST_SESSION profile / model wiring

- `_load_post_session_profile` selects exactly `ModelProfileRole.POST_SESSION`;
  a missing profile or any other role (AGENT/SUMMARIZER/EMBEDDING) raises
  `ValidationError` before model construction; `dnd ask` remains AGENT-only and
  unchanged.
- `_build_post_session_model` calls the accepted
  `build_pydantic_ai_post_session_model` (never the AGENT factory).
- One underlying configured model backs both
  `PydanticAIPostSessionExtractionModel` and
  `PydanticAIPostSessionRenderingModel`; both adapters expose zero
  project/action tools.
- `ModelExecutionIdentity(profile=profile_name, model=profile.model,
  provider=profile.provider)` is derived from trusted configuration only.
- The runtime owns model lifetime; `close()` is idempotent and is invoked from
  the command `finally` (success, processor failure, rendering failure and
  recording-uncertainty paths all close exactly once).

### 29.5 Attempt id

One normal `process` invocation generates exactly one
`application.post_session_identity.new_attempt_id()` and passes it verbatim to
`run_post_session_processing`. No `--attempt-id` option. The id is printed so
durable artifacts/proposals can be correlated.

### 29.6 Result / exit-code mapping

```text
COMPLETED (PRODUCED or NO_CHANGES) -> 0
ALREADY_TERMINAL                   -> 0
INELIGIBLE / INTERRUPTED / FAILED  -> 1
selector/config/profile/input error-> 1
PostSessionFailureRecordingError   -> 1
```

Rendering is Russian and truthful: produced proposals are stated to be
**proposal-only, unapproved and unapplied**, with the only suggested next step
`dnd changeset review <id> --vault ...`; NO_CHANGES explicitly states no
ChangeSet was created and campaign entities were not modified; EMPTY recap is
reported from the processor flag and the placeholder body is never printed;
INTERRUPTED never claims retry/rollback; FAILED prints only phase/category,
recording status and the processor-owned reason (never provider/model detail).

### 29.7 Error boundary (Correction 2)

`cli/post_session.py` catches only `PostSessionFailureRecordingError` and
`DndAssistantError`. There is no broad `except Exception`; programming errors
are not swallowed. Expected model/provider failures already cross the accepted
S11-03/S11-04/S11-06 typed error boundaries (adapter -> `PostSessionExtractionError`
/ `PostSessionRenderingError` -> bounded `AttemptFailed` -> typed result).
Provider/model canaries injected through this normal typed path are proven
absent from CLI output.

### 29.8 `session outputs` (Correction 1)

Read-only, ledger-authoritative, no config/profile/model. It first verifies the
session exists through `SessionMetadataRepository`:

```text
existing session + no processing ledger -> exit 0, "Попыток обработки нет"
missing session                         -> exit non-zero, bounded not-found
```

For every attempt it calls `fold_attempt_state`; a structural `COMPLETED`
attempt is only surfaced as verified after `verify_terminal_integrity` succeeds
against the real artifact/changeset stores. Any integrity failure fails closed
(non-zero), shows the attempt id and the bounded `TerminalIntegrityReason`, and
prints no artifact bodies. Terminal-integrity rules are not duplicated in
`application/post_session_outputs.py`; it only loads the ledger, reads
artifacts/proposals through protocols and calls the existing verifier. STARTED /
FAILED / SUPERSEDED states remain inspectable without being presented as
completed outputs. No legacy `Session.processed` field is read.

### 29.9 No approval/apply and no canonical mutation

`process` never imports or calls `build_changeset_review`, `persist_approval`,
`persist_proposal` (processor-owned) or `apply_changeset`; it has no
`--yes/--approve/--apply`. Integration tests prove a produced proposal leaves no
approval artifact, no apply-attempt artifact, unchanged canonical entity bytes
and an unchanged audit log. `session outputs` is read-only and writes nothing.
Processing still performs no canonical entity mutation or audit growth.

### 29.10 Evidence

```text
unit   selector validation / latest selection / profile loading /
       result rendering / exit codes / model lifetime / recording-uncertainty
       tests/unit/test_cli_post_session.py
unit   outputs read-model grouping/order/non-completed
       tests/unit/post_session/test_outputs.py
integration  produced / no_changes / empty / zero-model-work / latest /
       failures / recording-uncertainty / outputs integrity
       tests/integration/test_cli_post_session.py
contract     CLI composition boundaries + outputs read-model purity
       tests/contract/test_post_session_boundaries.py
```

No Ollama is required. Verified: invalid selector, missing explicit session,
no `--latest` candidate, blocking recovery and wrong-role profile all produce
zero model construction and zero Stage-11 attempt writes.

### 29.11 Deferred (S11-08+)

Hardening/failure injection (S11-08), Stage-11 review (S11-09), lease/heartbeat
interrupted finalization, supersession API, human-facing latest
Summary/Recap projection (never a mutable overwrite), Stage 12.

## 30. S11-08 record

```text
Task:              S11-08 — Hardening / Failure Injection
Routing:           PLAN_REQUIRED -> accepted PLAN (5 corrections) -> BUILD
Baseline:          feat/post-session-processor @
                   ff3509571ccbb24de10010bae0de3a435d78553d
                   HEAD == origin/feat/post-session-processor, clean tree
Scope:             test-heavy failure-injection hardening of the accepted
                   S11-01..S11-07 pipeline: storage faults, abrupt crash
                   windows, corrupt/tampered durable evidence, concurrency,
                   model/provider failures, resource bounds, privacy canaries,
                   path/symlink topology, restart/rerun edges, CLI error
                   surfaces and Stage-10 proposal interaction
Deliverable:       11 new test/support modules + 1 focused edit to an existing
                   integrity test module + this record +
                   DEVELOPMENT_STATUS reconciliation
Production edits:  NONE (no DEFECT_FIX / DECOMPOSITION required)
Next task:         S11-09 — full Stage-11 review/completion
```

### 30.1 Implemented test-only modules

```text
tests/support/post_session_faults.py           delegating fault stores +
                                               AbruptProcessCrash(BaseException)
tests/support/post_session_truth.py            literal canonical-truth snapshot /
                                               attempt-artifact byte snapshot
tests/unit/post_session/test_hardening_ledger.py     fsync-uncertain append,
                                                     no-reread contract, permanent lock
tests/unit/post_session/test_hardening_storage.py    read-back orphan, cleanup,
                                                     concurrent same-slot, symlink topology
tests/unit/post_session/test_hardening_bounds.py     remaining S11-02 ceilings
tests/unit/post_session/test_hardening_unicode.py    NFC/NFD/casefold candidate identity
tests/unit/post_session/test_hardening_cli.py        CLI typed-except source guard
tests/unit/post_session/test_integrity.py            edit: produced terminal +
                                                     PROPOSAL_FINGERPRINT_MISMATCH +
                                                     WORKFLOW_EVIDENCE_INCONSISTENT reasons
tests/integration/test_post_session_hardening.py     pre-start, AttemptStarted
                                                     uncertainty, extraction/rendering
                                                     typed failures, artifact orphans,
                                                     proposal orphan reviewability,
                                                     zero-rewrite idempotency,
                                                     changed-input retries, interrupted
                                                     matrix, rerun semantics, privacy canaries
tests/integration/test_post_session_corruption.py    all 9 TerminalIntegrityReason via
                                                     `session outputs`, structural conflicts,
                                                     proposal persistence failure,
                                                     NO_CHANGES tamper, R1 ownership,
                                                     CLI privacy and model-close
tests/integration/test_post_session_concurrency.py   same-attempt single owner,
                                                     different attempts, concurrent reads
tests/integration/test_post_session_paths.py         Unicode/space Vault root,
                                                     Unicode session id, symlink topology
```

### 30.2 Hardening / failure matrix covered

```text
pre-start failures                 invalid attempt id, corrupt ledger, oversized input,
                                   orphan claim -> zero model / no Stage-11 attempt write
AttemptStarted uncertainty         definite-before-write and written-but-reported-failed
                                   append; STARTED re-fold on the same attempt; no auto
                                   second append; claim remains unusable
extraction typed failures          MODEL_UNAVAILABLE/MODEL_TIMEOUT/MODEL_INVOCATION_FAILED/
                                   INVALID_STRUCTURED_OUTPUT/INVALID_EVIDENCE_REFERENCE ->
                                   bounded typed attempt_failed, no later durable outputs
rendering failures                 Summary vs Recap unavailable/timeout separately; no
                                   artifacts persisted; deterministic EMPTY recap = zero
                                   Recap model calls
artifact persistence faults        read-back mismatch orphan, write/fsync cleanup,
                                   concurrent identical/different bytes
artifact orphan windows            summary/recap/workflow file without event -> STARTED,
                                   never completion, no model resume
proposal orphan / reviewability    file without event -> STARTED, ordinary Stage-10
                                   proposal remains reviewable, never auto-approved
terminal idempotency               ALREADY_TERMINAL with zero model calls and exact
                                   artifact/ledger/audit/proposal byte equality
changed current input              raw event, session metadata and canonical entity change
                                   -> fingerprint_mismatch, zero model, no rewrite
interrupted restart matrix         start-only + summary/recap/workflow/proposal file/event
                                   -> INTERRUPTED, zero model
different-attempt rerun            independent namespaces; same candidate EntityId while
                                   no proposal is applied; campaign truth unchanged
applied-create rerun               explicit Stage-10 review/approve/apply, then rerun ->
                                   whole-Vault duplicate prevention, no duplicate create
privacy canaries                   durable recap.md excludes DM/SYSTEM/unresolved/candidate;
                                   durable summary excludes SYSTEM; CLI prints no bodies
TerminalIntegrityReason            all 9 reasons fail closed through `session outputs`
workflow corruption                invalid JSON/version/hash/path + INCONSISTENT
                                   (session_ref/attempt_id/fingerprint/produced/changeset)
proposal corruption                missing/fingerprint mismatch/orphan/unexpected/storage fail
structural ledger                  malformed/multiple_started/event_after_terminal at
                                   processor and outputs, fail closed without repair
ledger/lock                        fsync uncertainty, permanent lock failure, short write
                                   (existing), symlinked lock (existing)
bounds                             remaining S11-02 input ceilings; existing output/workflow
                                   byte bounds retained
Unicode/path                       Unicode+space Vault root, Unicode session id, traversal
                                   rejection, symlinked processing directory
R1 recovery                        processing state is not a recovery blocker; ChangeSet-owned
                                   intent does not block processing; failures add no audit
                                   repair action
Stage-10 boundary                  proposal immutability/approval/apply remain mandatory and
                                   unchanged; Stage-11 terminal state is not an approval
                                   authority
```

### 30.3 Real defects found / fixed

```text
None.  No production change was required; all S11-08 evidence was obtained
through test-only fault injection.  No production failpoint/framework was added.
```

### 30.4 Residual limitations

```text
Power-loss / parent-directory fsync
    All durable write primitives (attempt claim mkdir, artifact exclusive create,
    ledger create/append, proposal create) fsync the file but never the parent
    directory.  Current implementation and tests therefore prove/process-test
    *process-crash* semantics; they do NOT independently prove machine/power-loss
    durability of newly created directory entries.  Parent-directory fsync is not
    implemented and no stronger durability claim is made.

POSIX / macOS lock backend
    The POSIX fcntl.flock path is not executed in this Windows environment.  It is
    guarded/import-isolated and covered by platform-specific classification tests,
    but remains an honest unexecuted-platform limitation.

Symlink capability
    Symlink-gated hardening tests skip where the host cannot create symlinks
    (observed on this Windows host).  The symlink-safety logic is exercised for
    import/is_symlink classification; live symlink rejection coverage depends on
    a symlink-capable host/CI.

Concurrency determinism
    Same-attempt single-owner evidence uses deterministic multiprocessing
    Event/Value synchronization (model enters and blocks; contender cannot enter).
    No timing-only sleeps are used.
```

### 30.5 Evidence

```text
fault injection / crash windows   tests/integration/test_post_session_hardening.py
corruption / CLI / R1 / Stage-10  tests/integration/test_post_session_corruption.py
same/different attempt + reads    tests/integration/test_post_session_concurrency.py
path / Unicode / symlink          tests/integration/test_post_session_paths.py
unit storage/ledger/bounds/unicode/CLI  tests/unit/post_session/test_hardening_*.py
terminal integrity reasons        tests/unit/post_session/test_integrity.py (extended)
maintainability (<=700/<=1000)    tests/contract/test_maintainability.py (unchanged, green)
```

No Ollama is required.  Gates run: focused hardening suites, S11 + Stage-10
regressions, `ruff check`, `ruff format --check`, `pyright` (0 errors), full
`pytest` (6240 passed, 124 skipped) and `git diff --check`.

### 30.6 Deferred (S11-09+)

Full Stage-11 historical/architecture conformance review, documentation/status
reconciliation, merge/completion readiness and the final Stage-11 verdict
(S11-09); plus lease/heartbeat interrupted finalization, supersession API,
human-facing latest projection and Stage 12.

## 31. S11-09 record

```text
Task:              S11-09 — Full Stage-11 Historical Review / Completion
Routing:           PLAN_REQUIRED -> accepted PLAN
                   (1 mandatory test-harness correction,
                    1 documentation-clarity requirement) -> BUILD
Baseline:          feat/post-session-processor @
                   3738c6092934c50f53b5b51ab6c752c80102a44f
                   HEAD == origin/feat/post-session-processor, clean tree
Pre-Stage-11 base: 513401f807e0808c58e6673a3af73911a0c61de4
Immutable review range:
                   513401f807e0808c58e6673a3af73911a0c61de4
                   .. 3738c6092934c50f53b5b51ab6c752c80102a44f
Review base:       513401f807e0808c58e6673a3af73911a0c61de4
Review head:       3738c6092934c50f53b5b51ab6c752c80102a44f
Finalization:      1 corrected test-harness file + this record +
                   DEVELOPMENT_STATUS reconciliation committed on top of the
                   reviewed implementation head (SHA in Git history; the
                   historical review range itself is not rewritten)
Verdict:           STAGE11_READY_FOR_COMPLETION
```

### 31.1 Commit inventory / classification

15 Stage-11-owned commits in the immutable range; **0 unrelated/concurrent**;
no merge commits. 10 stage implementations, 3 stage corrections, 2
documentation corrections:

```text
15b522f  S11-00  docs/kickoff            architecture + DEVELOPMENT_STATUS + index
2dba067  S11-01  implementation           input + durable processing schemas
2c1b75f  S11-02  implementation           deterministic context assembly
7dac72f  S11-03  implementation           bounded structured extraction
5fa39a6  S11-03  correction               normalize extraction evidence
fb04a1b  S11-03  correction               accept explicit null candidate id
2c66fc6  S11-04  implementation           Summary/Recap + visibility filtering
91922cc  S11-04  documentation correction mark S11-03 DONE
5f30632  S11-05  implementation           ChangeSet producer + ambiguity policy
5e9a59a  S11-06  implementation           durable persistence/rerun/failure
4ff387c  S11-06  correction               lock failure/schema version/NO_CHANGES
50b7e2c  S11-07  implementation           CLI orchestration + verified outputs
ff35095  S11-07  documentation correction finalize status header
60013b2  S11-08  implementation           hardening/failure injection (test-only)
3738c60  S11-08  test correction           orphan-artifact assertion + wording
```

### 31.2 Git-derived changed-file summary

95 changed files (`+24267 / -59`) from `git diff --name-status 513401f..3738c60`:
new `domain/post_session*.py` (4), new `application/post_session_*.py` +
`entity_id_allocator.py` + `pydantic_ai_post_session*.py` (21), new
`storage/post_session_{processing,artifacts}.py` (2), new prompts (3), new
`retrieval/exact_matching.py`, new `cli/post_session{,_runtime}.py` (2), 45
test/support modules, and documentation. Pre-existing files modified:
`models/profiles.py` (+1 enum member), `models/pydantic_ai_ollama.py` (additive
POST_SESSION factory over a shared private helper), `retrieval/search.py`
(pure delegation to `exact_matching`, net −26 lines), `cli/main.py` (+2
registration lines), three test modules, `DEVELOPMENT_STATUS.md`,
`docs/stages/README.md`.

### 31.3 Architecture-invariant verdict

```text
I1  Vault is the only campaign Source of Truth                 PASS
I2  Stage 11 creates proposals; never approves/applies          PASS
I3  model output untrusted until Python validates              PASS
I4  heavy model has no tools/filesystem/shell/Vault write      PASS
I5  input_fingerprint binds the prepared source/context input   PASS (scope see 31.7)
I6  input identity vs attempt identity distinct                PASS
I7  immutable/versioned per-attempt artifacts                   PASS
I8  append-only processing ledger                              PASS
I9  ledger authoritative; legacy session fields are not        PASS
I10 Recap hidden-data filtering deterministic Python            PASS
I11 ambiguous references never speculatively mutated            PASS
I12 calendar conversion/arithmetic stays CalendarService         PASS
I13 domain/storage concrete-model/provider-independent          PASS
I14 no new canonical campaign store outside the Vault           PASS
```

No blocking defect; architecture conformance `ACCEPTED`.

### 31.4 Original acceptance-criteria evidence

```text
1  completed accepted; invalid/incomplete rejected pre-model   test_eligibility.py; hardening pre-start
2  same input -> same fingerprint; changed -> different         test_identity.py; test_context.py; hardening
3  fingerprint stable across attempts; attempt-scoped changeset test_identity.py; test_post_session_processor.py
4  immutable per-attempt Summary/Recap; rerun no overwrite      test_artifact_persistence.py; test_post_session_processor.py
5  append-only ledger; reconstructable after restart            test_storage.py; test_post_session_processing.py
6  legacy Session processing fields not Stage-11 state          test_eligibility.py; production audit
7  Recap excludes hidden/GM material                            test_post_session_hardening.py durable canary
8  real session_ref, validates, unapproved, consumed by changeset test_post_session_changeset.py; boundaries
9  ambiguity omitted; candidates never duplicate                test_changeset_producer.py; applied-create rerun
10 model/provider failure leaves canonical state unchanged      test_post_session_processor.py; processor_failure
```

### 31.5 S11-08 hardening evidence

```text
crash/restart windows        test_post_session_hardening.py
corruption (all 9 reasons)   test_post_session_corruption.py
concurrency (same/diff)      test_post_session_concurrency.py
idempotency / zero-rewrite   test_post_session_hardening.py:586-609
privacy canaries (durable)   test_post_session_hardening.py:874-915
path/symlink topology        tests/unit/post_session/test_hardening_storage.py; test_post_session_paths.py
R1 ownership                 test_post_session_corruption.py:401-463
Stage-10 compatibility       test_post_session_boundaries.py; corruption
```

### 31.6 Test-quality review and corrected test-harness defect

The S11-08 `or True` issue remains corrected. Final review additionally found
one **`TEST_HARNESS_DEFECT`** (not a Stage-11 production defect) in
`tests/integration/test_post_session_concurrency.py`:

```text
Before
    test_concurrent_ledger_reads_never_observe_partial_records looped
    ``while not done.is_set()`` with no deadline and no liveness check, and
    depended on the scheduler-dependent ``assert reads >= 1``.
    A writer that died before ``done.set()`` could spin the parent forever.

After (bounded deterministic protocol)
    writer process: signal READY -> wait for START (fail closed on timeout)
    -> perform writes -> signal DONE on the normal path.
    parent: wait READY with timeout; signal START; read in a loop bounded by
    writer liveness AND a monotonic deadline (``_QUEUE_TIMEOUT``); then one
    guaranteed read; join with timeout; assert not alive; assert exitcode 0;
    final strict parse; exact event count.
    No ``time.sleep``, no timing threshold used as correctness evidence.
```

The semantic property is retained: every observed snapshot is read through
`load_ledger_events`, which strictly parses and must never raise on a torn
record; final exact event-count validation is retained. No production
concurrency behavior changed. No production failpoint or global lock added.
Remaining non-blocking test-quality observations (from the accepted PLAN) are
recorded, not corrected in S11-09.

### 31.7 Fingerprint / rendering-contract scope statement

```text
input_fingerprint
    deterministic identity of the prepared source/context input
    + the extraction prompt contract. It is NOT a fingerprint of every
    model call and NOT the entire execution recipe.

render prompt/schema versions
    immutable attempt artifact/workflow provenance; they are NOT part of
    prepared-input identity.

Changing a rendering prompt/schema does not rewrite an existing attempt;
same-attempt terminal evidence remains immutable; a new execution attempt is
required to produce outputs under a new rendering contract.
```

No production fingerprint change was made in S11-09;
`POST_SESSION_PROCESSOR_VERSION` and the fingerprint schemas are unchanged.

### 31.8 Known limitations

```text
NON_BLOCKING_ACCEPTED
    no parent-directory fsync / no independently proven power-loss durability
    POSIX/macOS flock backend not executed on the current Windows host
    symlink-safety tests capability-gated on the current host
    render prompt/schema versions are not part of input_fingerprint (31.7)
    Recap filters typed bindings; hidden names in otherwise player-safe claim
    free text are not redacted (accepted S11-04 policy)

DEFERRED
    lease/heartbeat interrupted-attempt reclamation
    supersession API
    human-facing mutable/latest Summary/Recap projection
```

### 31.9 Maintainability pressures

```text
production (<=700)  post_session_changeset.py 666; post_session_extraction.py 648;
                    cli/post_session.py 479; storage/post_session_processing.py 480
tests (<=1000)      test_post_session_hardening.py 949; test_post_session_boundaries.py 855;
                    test_changeset_producer.py 762; test_cli_post_session.py 727
ceiling (pre-existing) tests/contract/test_boundaries.py 1000 (zero headroom)
pre-existing          cli/changeset.py 666
```

No speculative decomposition performed.

### 31.10 Platform evidence classification

```text
LOCAL_VERIFIED (Windows host)
    full pytest / ruff / pyright gates; multiprocessing spawn concurrency;
    msvcrt ledger-lock backend.

NOT_EXECUTED_HERE
    POSIX/macOS fcntl.flock backend; symlink-enabled rejection tests where the
    host lacks symlink capability.

REMOTE_GIT_VERIFIED
    pushed SHA/history after finalization (HEAD == upstream).
```

### 31.11 Quality gates

```text
focused
    tests/integration/test_post_session_concurrency.py          3 passed
    tests/unit/post_session                        385 passed, 6 skipped
    tests/integration -k post_session              126 passed, 1 skipped (475 deselected)
    tests/contract/test_post_session_boundaries.py
      + tests/contract/test_maintainability.py     667 passed
    Stage-10 / R1 / CLI / model-profile regressions 713 passed, 3 skipped
full
    uv run ruff check .                            All checks passed
    uv run ruff format --check .                   464 files already formatted
    uv run pyright                                  0 errors, 0 warnings, 0 informations
    uv run pytest                                   6240 passed, 124 skipped
    git diff --check                                clean
```

No live Ollama, no network.

### 31.12 Merge readiness

```text
main is the exact pre-Stage-11 base (513401f) or divergence fully understood
feature branch contains all 15 Stage-11 commits
working tree clean
no unresolved blocker
full gates green
docs/status final
=> MERGE_READY
```

Merging is a separate action and was **not** performed in S11-09.

### 31.13 Final Stage-11 verdict

```text
Stage 11: DONE
S11-09: DONE
Architecture conformance: ACCEPTED
Stage acceptance: STAGE11_READY_FOR_COMPLETION
Merge readiness: MERGE_READY
Next: Stage 12 planning/kickoff
```
