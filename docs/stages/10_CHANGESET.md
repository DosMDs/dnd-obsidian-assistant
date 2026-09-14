# Stage 10 — ChangeSet

## Status

```text
Stage 10 — IN PROGRESS
S10-00 — DONE
S10-01 — DONE
S10-02 — NOT STARTED
S10-03 — NOT STARTED
S10-04 — NOT STARTED
S10-05 — NOT STARTED
S10-06 — NOT STARTED
S10-07 — NOT STARTED
Stage 11 — NOT STARTED
```

Accepted architecture baseline SHA:

```text
7c331f29cd418e4c4cda6a487fbbf5f1983d20eb
```

Architecture verdict:

```text
S10_ARCHITECTURE_READY
```

This document is the canonical Stage-10 architecture record and task map. It
describes **contracts and evidence plans**. `S10-01` implemented the immutable
domain proposal schemas only; no validation/preflight, review, fingerprint or
apply implementation exists yet, and `S10-02` onward remain `NOT STARTED`.

## 1. Purpose

Stage 10 establishes the trusted domain/application boundary through which
later post-session model output can propose campaign changes without ever
gaining direct Vault authority.

Canonical lifecycle:

```text
untrusted proposal
→ ChangeSet
→ validate
→ human review
→ apply
→ VaultRepository
```

The LLM/framework may eventually produce structured proposals. It must never:

```text
write Vault files
choose arbitrary filesystem paths
bypass ChangeSet validation
bypass human review
bypass revision/conflict checks
bypass VaultRepository
```

## 2. Source-of-Truth and trusted-boundary rules

Preserved throughout Stage 10:

```text
Obsidian Vault = only Source of Truth
Python owns domain logic and validation
VaultRepository owns safe persistence
LLM output is untrusted
stable IDs
revisions
provenance
visibility
atomic writes
audit log
clarification > speculative mutation
```

Derived indexes/cache/embeddings remain rebuildable from the Vault. Domain and
storage must not depend on Ollama, Pydantic AI or any concrete model/provider.

Model output is untrusted until validated by Python. Framework tool exposure,
filtering or approval is not an authorization boundary.

## 3. Ownership by layer

```text
domain/
    immutable ChangeSet and ChangeOperation schemas
    semantic operation kinds
    revision/precondition value contracts
    explicit semantic allowlist of updatable entity fields

application/
    pure validation
    whole-batch preflight
    review policy
    approval / rejection representation
    proposal serialization and fingerprint binding (S10-03)
    apply orchestration
    conflict handling
    review DTO/rendering (Russian user text at CLI)

storage/
    existing repository primitives only
    no ChangeSet policy; unchanged

models/
    future structured proposal generation only
    no apply authority; no Stage-10 surface

cli/
    human review/apply surface (S10-05)
```

Deviation from an automatic field mirror: `storage.patch.EntityPatch` lives in
storage and must not become a domain dependency. The domain defines its own
explicit update payload (`EntityFieldUpdate`), and application code later proves
that every allowed ChangeSet update field maps safely into the existing
repository `EntityPatch`. Storage-only capability must not automatically expand
ChangeSet authority.

## 4. Immutable ChangeSet proposal

The ChangeSet is immutable proposal data (`frozen=True`, `extra="forbid"`).
Proposed shape:

```text
schema_version: Literal[1] = 1
changeset_id:   validated opaque unique string
provenance:     proposal provenance (domain Provenance + optional model/profile info)
session_ref:    optional origin session reference
operations:     ordered tuple of ChangeOperations (min length 1, order = apply order)
```

The aggregate deliberately contains no review lifecycle state, no approval, no
apply result, no timestamps added merely for workflow convenience, and no
filesystem paths. Review/apply state belongs to the application layer.

`ChangeSetId` is a validated opaque string (not derived from name or path). Its
uniqueness is what allows deterministic per-operation audit ids such as
`<changeset_id>:<index>`.

## 5. Constrained operation model

Stage 10 uses explicit semantic operations — not generic JSON Patch, not
free-form dictionaries, not arbitrary Markdown replacement, not filesystem
paths. Discriminated union on `kind`; each operation is frozen with
`extra="forbid"`.

```text
CreateEntityOperation
    entity_id, entity type and canonical field payload
    precondition: the EntityId must not exist

UpdateEntityOperation
    entity_id, mandatory expected_revision, explicit field allowlist (>= 1 field)

AppendFactOperation
    entity_id, mandatory expected_revision, validated fact text
```

Quest status changes are expressed as the generic updatable `status` field in
`UpdateEntityOperation`; no dedicated quest operation is introduced. The
repository owns Markdown bullet rendering for facts.

## 6. Stable-ID / create semantics

```text
the model never supplies a filesystem path as entity identity
the trusted proposal author allocates the canonical EntityId when constructing
the immutable ChangeSet (before review)
anonymous/opaque storage filenames remain repository-owned
```

`CreateEntityOperation` carries an explicit `entity_id`. Duplicate behavior:

```text
same entity_id created twice in one ChangeSet → deterministic validation failure
entity_id already present in the Vault → deterministic conflict (I6)
```

New entities are referenced by later operations using the same `entity_id`.
An application `EntityIdAllocator` utility (injectable for determinism) is
planned for future proposal authors so identity is never taken from raw model
text.

## 7. Revision / conflict semantics

```text
UpdateEntityOperation and AppendFactOperation always require expected_revision
CreateEntityOperation proves non-existence instead
```

Existing repository revision rules are reused unchanged. The applier does not
rebase, auto-merge or silently retry. If the stored revision differs from the
reviewed `expected_revision`, apply fails closed with a conflict and performs
zero overwrite. A reviewed ChangeSet is approved against exact content, so a
change after review cannot be silently applied.

## 8. Multi-operation preflight and atomicity

Strong preference implemented at the validation layer:

```text
validate entire ChangeSet
→ resolve all targets (in-memory projection, no filesystem writes)
→ validate all revisions/preconditions
→ validate cross-operation relationships
→ only then begin mutation
```

An invalid later operation must not cause an earlier mutation merely because it
appeared first (I5). Same-batch dependencies (for example, create an entity and
then append a fact to it) are resolved deterministically during preflight using
the same revision rule the repository applies; unresolvable references are
rejected before any mutation (I10).

Atomicity is stated explicitly and honestly:

```text
full semantic preflight                       YES  (S10-02)
filesystem atomic write per document          YES  (existing VaultRepository)
whole-ChangeSet transaction / rollback        NO   (does not exist; not claimed)
```

If a write fails after preflight, already-applied documents remain. The
canonical MVP policy is **stop on first write failure**, return a structured
apply result describing applied and pending operations, and rely on
per-document intent/committed audit records plus revisions. A staging/rollback
mechanism is deliberately out of Stage-10 MVP scope and would require a
separate explicit task.

## 9. Human review

MVP requires human review before model-generated changes are applied.

```text
unreviewed proposal → cannot apply
rejected proposal   → cannot apply
```

Lifecycle/review state lives **outside** the immutable ChangeSet in
application-owned DTOs:

```text
ValidationResult     pure preflight outcome
ChangeSetFingerprint canonical hash of the exact proposal content (S10-03)
ChangeSetApproval    approved/rejected decision bound to changeset_id + fingerprint
ApplyResult          structured apply outcome
```

Approval is bound to the exact proposal content. Fingerprint/hash mechanics are
an application review concern and are deferred to `S10-03`; they do not belong
in the domain schema. A fingerprint mismatch is rejected. No general workflow
engine or state machine is introduced.

## 10. Proposal provenance vs repository audit

Proposal provenance (domain `Provenance` enum: manual/session/bootstrap/import/
model_inference, plus optionally origin session and model/profile identity)
describes **how the proposal entered the system**. Repository audit
(`AuditRecord.source`) describes **which application actor performed the write**
and remains owned by storage. These are distinct and must not be conflated or
duplicated.

The applier will construct one `AuditContext` per operation, mapping proposal
provenance into session/model fields and using a deterministic operation id.
The repository's existing two-phase intent/committed audit is unchanged. If
needed, model metadata is retained only where it supports
reproducibility/audit.

## 11. Apply authority

Canonical apply path (implemented in `S10-04`):

```text
Approved ChangeSet
→ ChangeSetApplicationService / ChangeSetApplier (application)
→ complete preflight against current state (fail-closed)
→ VaultRepository.create_entity / patch_entity / append_entity_fact
→ repository-owned revision + atomic write + audit
```

The applier must never use `Path.write_text`, `open(...)`, raw filesystem
mutation, shell commands, or model/framework callbacks for Vault changes. All
campaign mutation flows through project-owned persistence services.

I1 (no arbitrary path authority) is enforced structurally: the untrusted
schemas simply have no path field at all, and `extra="forbid"` rejects a
smuggled one.

## 12. Failure model

Existing project errors are reused where semantics already fit; no parallel
exception hierarchy is introduced.

```text
invalid operation / malformed ChangeSet   → ValidationError
unknown entity                            → NotFoundError
wrong entity type                         → ValidationError
revision conflict                         → ConflictError
duplicate create                          → ConflictError / ValidationError
cross-operation conflict                  → ValidationError
unsafe target                             → structurally impossible (no path fields)
not approved / rejected / mismatch        → ValidationError
repository write failure                  → StorageError
partial application                       → structured ApplyResult (no exception type)
```

Preflight reports issues as data; apply raises mapped project errors.

## 13. Review / rendering

`S10-03` plans a deterministic structured review DTO (per operation: kind,
target identity, current vs proposed state, expected revision, provenance) with
rendering kept separate from mutation authority. The CLI-facing text is Russian
per project invariant 3; the structured DTO stays language-neutral. Stage-11
summary/recap UI is explicitly out of scope.

## 14. Accepted Stage-10 task decomposition

```text
S10-00 — Architecture/domain contract and kickoff
S10-01 — ChangeSet + operation domain schemas
S10-02 — Pure validator / whole-batch preflight
S10-03 — Review DTO + approval/rejection + fingerprint binding
S10-04 — ChangeSetApplier + revision/conflict safety
S10-05 — CLI review/apply workflow + proposal persistence decision
S10-06 — Failure / partial-application / audit hardening
S10-07 — Full Stage-10 historical review / completion
```

Tests are implemented alongside each task. `S10-05` explicitly owns the
unresolved proposal-persistence decision (where a proposal lives between
separate review and apply CLI invocations); it is not solved in `S10-00`.

Ownership notes:

- `S10-01` owns only ChangeSet and operation domain schemas; it contains no
  fingerprint/hash logic and no review lifecycle state.
- `S10-03` owns canonical deterministic serialization, `ChangeSetFingerprint`,
  approval/rejection, review-to-content binding and mismatch rejection.
- `S10-02` and `S10-04` own pure preflight and the real repository-backed apply
  path respectively.

## 15. Invariants I1–I10 and evidence plan

These are the literal executable evidence targets for the tasks that implement
them; they are not yet executed at S10-00.

| # | Invariant | Planned literal evidence (owner) |
|---|---|---|
| I1 | No arbitrary path authority | Schema field-set assertion (no path/file/filename/target_path) + `extra="forbid"` rejection (S10-01); applier AST scan for IO imports (S10-04) |
| I2 | Validation is side-effect free | Repository spy: write-call count == 0 for valid and invalid input (S10-02) |
| I3 | Review required | Apply with absent/rejected approval → rejection, write-call count == 0 (S10-03/S10-04) |
| I4 | Stale revision fail-close | Real temp Vault: review rev 4 → mutate to 5 → conflict, content unchanged (S10-04) |
| I5 | Whole-batch preflight | `[valid op, invalid op]` → invalid preflight, op 1 not written (S10-02/S10-06) |
| I6 | Duplicate create fails | Create existing `EntityId` → conflict; in-batch duplicate → deterministic validation failure (S10-02/S10-04) |
| I7 | Repository is sole persistence authority | Apply uses only `VaultRepository` methods; `Path.write_text` monkeypatch proves never hit (S10-04/S10-06) |
| I8 | Canonical revision behavior preserved | After apply, persisted revision == before + 1 and `updated_at == audit.real_time` (S10-04) |
| I9 | Proposal provenance preserved | Serialize/re-parse ChangeSet preserves provenance verbatim (S10-01) |
| I10 | Cross-operation consistency | `[create X, append fact to X]` resolves via projection and applies in order; unresolvable reference rejected before mutation, zero writes (S10-02) |

## 16. Explicit non-goals

```text
no Stage-11 implementation
no LLM ChangeSet generation yet
no automatic approval/apply of model output
no LLM filesystem access
no generic JSON Patch
no arbitrary file editing
no VaultRepository redesign without proven need
no vector DB or embeddings
no workflow/state-machine framework
no DB-backed canonical ChangeSet state
no branch merges
no deletion of the completed PAIM branch
```

## 17. S10-00 record

```text
Task:              S10-00 — ChangeSet Architecture & Domain Contract
Routing:           PLAN_REQUIRED
Baseline:          feat/changeset @ 7c331f29cd418e4c4cda6a487fbbf5f1983d20eb
                   upstream origin/feat/changeset, clean working tree
Verdict:           S10_ARCHITECTURE_READY
Accepted amendments:
  A — fingerprint/review mechanics owned by application review layer (S10-03);
      domain ChangeSet remains free of approval mechanics
  B — EntityFieldUpdate is an explicit semantic allowlist; no permanent parity
      contract with storage EntityPatch; storage capability must not expand
      ChangeSet authority
Deliverable:       this stage record + ADR-0006 + status updates
Next task:         S10-01 — ChangeSet + operation domain schemas
```

## 18. S10-01 record

```text
Task:              S10-01 — ChangeSet + operation domain schemas
Routing:           DIRECT
Baseline:          feat/changeset @ f5dcff58444882e821b8544ac7e845d103028b7e
                   upstream origin/feat/changeset, clean working tree
```

Implemented the immutable Stage-10 proposal schemas only, in:

```text
src/dnd_assistant/domain/changeset.py
```

Contracts:

```text
ChangeSetId         validated opaque proposal id (distinct from EntityId)
ProposalProvenance  provenance + optional model_profile/prompt_version
EntityFieldUpdate   semantic allowlist (name, status, visibility,
                    knowledge_status, created_session, last_seen_session, tags)
CreateEntityOperation  kind="create_entity"
UpdateEntityOperation  kind="update_entity" + mandatory expected_revision
AppendFactOperation    kind="append_fact" + mandatory expected_revision
ChangeOperation     discriminated union on `kind` (no generic fallback)
ChangeSet           schema_version=1, changeset_id, provenance, session_ref,
                    ordered non-empty operations
```

All models are `frozen=True` with `extra="forbid"`. `EntityFieldUpdate`
preserves "unset" versus "explicit None" (only nullable session fields accept
explicit `None`) and serializes only explicitly supplied fields so
`model_dump`/`model_validate` round-trips are lossless. No filesystem path,
fingerprint/hash, approval/review state or storage DTO appears in the domain
schemas.

Evidence:

```text
tests/unit/test_changeset_domain.py   143 tests (allowlist, immutability,
                                      union, round-trip, I1 path-field absence)
tests/contract/test_boundaries.py     domain.changeset import boundary
                                      (no storage/application/models/tools/
                                      retrieval/cli; no pathlib/os/hashlib)
```

Gates:

```text
uv run pytest tests/unit/test_changeset_domain.py -q   143 passed
uv run pytest tests/contract/test_boundaries.py -q     104 passed
uv run ruff check .                                    All checks passed
uv run ruff format --check .                           356 files already formatted
uv run pyright                                          0 errors, 0 warnings
uv run pytest                                           5080 passed, 114 skipped
```

No validator/preflight (S10-02), review/fingerprint (S10-03), applier (S10-04) or
CLI (S10-05) behavior was implemented. No `EntityIdAllocator` was introduced.

```text
Next task:         S10-02 — Pure validator / whole-batch preflight (NOT STARTED)
```
