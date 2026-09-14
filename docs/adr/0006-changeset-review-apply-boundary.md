# ADR-0006: ChangeSet review/apply boundary

- **Status:** Accepted
- **Date:** 2026-09-14
- **Stage:** Stage 10 — ChangeSet (`S10-00`)
- **Baseline:** `feat/changeset` @ `7c331f29cd418e4c4cda6a487fbbf5f1983d20eb`
- **Related:** `docs/stages/10_CHANGESET.md`, ADR-0003 (Pydantic AI runtime migration), ADR-0005 (module and test decomposition policy)

## Context

Long-term campaign memory is written into the Obsidian Vault, which is the only
campaign Source of Truth. Python owns trusted domain/application/storage logic
and `VaultRepository` owns safe persistence. Local LLMs are replaceable
operators whose output is untrusted.

Stage 11 will let a post-session processor propose campaign changes from
untrusted model output. Today the accepted session-time write path is direct:
`ToolExecutor → services → VaultRepository`, with human/model authorization and
repository revisions. There is no batch proposal/review aggregate.

Stage 10 must define a bounded proposal boundary so untrusted structured output
can be reviewed and applied without ever writing canonical files directly,
choosing paths, or escaping revision checks. The architecture must decide what
the ChangeSet **is**, where each responsibility lives, and what atomicity is
actually claimed.

## Decision

### 1. ChangeSet is immutable proposal data

`ChangeSet` is a frozen domain aggregate of ordered semantic operations plus
proposal provenance. It is **not**:

- a workflow object;
- a storage transaction;
- a generic JSON Patch;
- a filesystem patch format;
- model write authority.

It contains no review lifecycle state, no approval, no apply result and no
filesystem paths.

### 2. Review/approval state is application-owned

Validation, preflight, review, approval/rejection, fingerprint binding, apply
orchestration and conflict handling live in the application layer. Proposal
review state is not a field of the immutable ChangeSet.

### 3. Storage remains unchanged and policy-free

Stage 10 introduces no ChangeSet policy into `storage/`. It reuses existing
`VaultRepository` primitives (`create_entity`, `get_entity`, `list_entities`,
`patch_entity`, `append_entity_fact`), their optimistic revisions, path safety,
atomic writes and two-phase audit.

### 4. `VaultRepository` remains the sole persistence authority

An approved ChangeSet is applied by an application applier that calls only
`VaultRepository` methods. It must never use `Path.write_text`, `open(...)`,
raw filesystem mutation, shell commands, or model/framework callbacks for Vault
changes.

### 5. Whole-ChangeSet transactionality is not claimed

The architecture distinguishes three levels explicitly:

```text
full semantic preflight                    YES  (implemented by validation)
filesystem atomic write per document       YES  (existing repository)
whole-ChangeSet transaction / rollback     NO   (does not exist; not claimed)
```

If a write fails after preflight, applied documents remain. MVP policy is
stop-on-first-write-failure plus a structured apply result, per-document
audit and revisions. A staging/rollback mechanism is a separate future task.

### 6. Domain update fields are an explicit semantic allowlist

The domain defines `EntityFieldUpdate` as the explicit set of fields a Stage-10
proposal is allowed to change. It is **not** an automatic mirror of
`storage.patch.EntityPatch` and is not subject to a permanent equality/parity
contract. Application mapping must prove each allowed field maps safely into
the existing repository `EntityPatch`. A future storage-only `EntityPatch`
capability must not automatically expand ChangeSet authority.

### 7. Fingerprint ownership belongs to the application review layer

Canonical deterministic proposal serialization, `ChangeSetFingerprint`,
approval/rejection and review-to-content binding belong to `S10-03` in the
application layer. The immutable domain ChangeSet contains no SHA-256 or
approval mechanics.

Rationale:

- the domain aggregate describes a proposal, not a persisted/reviewed artifact;
- hashing and serialization are review/application concerns that may evolve
  independently of the semantic schema;
- keeping approval out of the domain prevents lifecycle/status mutation pressure
  on an immutable object;
- binding approval to exact content (not just a `changeset_id`) prevents a
  reviewed proposal from being swapped before apply, without weakening domain
  purity.

## Consequences

### Positive

- clear trust boundary: untrusted proposals → validated → reviewed → applied via
  `VaultRepository` only;
- domain/storage stay provider-free and policy-free;
- repository revision, path, atomic-write and audit authority is preserved;
- no false atomicity guarantees;
- explicit allowlist prevents accidental authority creep from storage changes;
- review/apply mechanics can evolve without changing the proposal schema.

### Trade-offs

- partial application is possible and must be documented/tested rather than
  hidden (S10-06);
- `EntityFieldUpdate` duplicates the field list already present in
  `EntityPatch`; the duplication is intentional and bounded by an application
  mapping test, not a parity contract;
- proposal persistence between review and apply invocations is still
  unresolved and is owned by `S10-05`.

## Supersedes

None.
