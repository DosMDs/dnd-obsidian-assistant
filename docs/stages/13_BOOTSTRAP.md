# Stage 13 — Bootstrap

**Status:** `DONE` (S13-01 … S13-05 `DONE`)

This document is the durable Stage-13 handoff/plan contract produced by TUI-06.
It is **not** Stage-13 implementation and contains no Stage-13 code, tests or
schemas. Current roadmap state lives in `DEVELOPMENT_STATUS.md`.

## Gate

The Textual TUI prerequisite is satisfied (the accepted track was integrated
by `TUI-M01`). Stage 13 is `DONE`; `S13-01` … `S13-05` are `DONE`. There is no
current Stage-13 blocker and no planned Stage-13 follow-up: the deterministic
starting-world-time admin surface is implemented by S13-05.

## Two different onboarding scenarios

Stage 13 contains **two distinct operations** that must never be conflated.

### A. New / selected Obsidian Vault initialization — `dnd init`

Conceptual CLI:

```text
dnd init --vault <path>
```

Purpose: deterministically initialize the D&D Session Assistant layer inside the
selected Obsidian Vault.

Characteristics (non-negotiable for `dnd init`):

```text
model-free
deterministic
safe
non-destructive
preserves unrelated existing Obsidian content
performs no speculative inference
does NOT scan/import existing campaign notes
```

`dnd init` is **not** existing-campaign import. It must never silently become
bootstrap/import.

### B. Existing campaign bootstrap

Separate, later operation (S13-02 … S13-05):

```text
discover / analyze existing campaign material
map / import / normalize into canonical structures
handle ambiguity safely (clarify / unresolved instead of speculative mutation)
model-derived changes only through ChangeSet review / apply
```

## Task decomposition (provisional dependency order)

```text
S13-01  Vault Initialization Contract + `dnd init`
S13-02  Existing Vault Discovery / Analysis
S13-03  Existing Campaign Bootstrap / Mapping
S13-04  Bootstrap ChangeSet Review / Apply
S13-05  Bootstrap Completion / Validation / Derived Rebuild
```

These are dependency-ordered task boundaries. `S13-01` … `S13-05` are
implemented/`DONE`.

## S13-01 — original handoff requirements (historical)

Before implementation, the S13-01 handoff required the task to decide and test
at least:

```text
accepted input Vault states (empty directory vs existing Obsidian Vault)
required D&D Assistant directory/file structure
campaign identity/config creation
safe-path / symlink / junction policy
collision policy
idempotency / re-run behavior
partial-initialization recovery
atomic writes
audit/bootstrap provenance where appropriate
preservation of unrelated user files
Windows/macOS path behavior
UTF-8 / Cyrillic
```

Detailed schemas are intentionally not frozen here.

## S13-01 — implementation record (`DONE`)

S13-01 implemented deterministic, model-free structural initialization via
`dnd init --vault <path>`.

### Ownership

```text
cli/init.py                            Russian presentation only
composition/vault_initialization.py    AuditService factory + concrete initializer
application/vault_initialization.py    state machine, identity decision, typed result
storage/vault_initialization.py        layout, path authorization, mutation, audit
storage/atomic.py                      exclusive create-once publish primitive
domain/types.py                        CampaignId (loose validated identity)
```

`storage/types.py`, `storage/vault_repository.py`, `storage/session_*`,
`storage/world_time.py`, the ChangeSet/post-session runtimes, `retrieval`,
`tools`, `models` and `tui` are unchanged.

### Campaign config boundary

`_system/campaign.yaml` is **campaign/application configuration**, not a
domain aggregate.  A full `domain.CampaignConfig` model was deliberately
**not** created.  Storage validates only the S13-01 core envelope
(`schema_version == 1`, valid `campaign_id`); any additional existing keys
are opaque, forward-compatible storage data that is accepted and preserved
but never claimed as semantically validated.  A newly initialized Vault
writes only:

```yaml
schema_version: 1
campaign_id: <generated once>
```

No campaign name, calendar, perspective or feature flag is inferred or
written.  The injectable identity factory is called only when the preflight
confirms the marker is genuinely absent.

### State semantics

```text
config absent + compatible topology   -> CREATED
config valid + full safe layout       -> ALREADY_INITIALIZED (zero writes)
config valid + safe missing dirs      -> COMPLETED_PARTIAL (audited repair)
config invalid / conflicting / unsafe -> fail closed
```

`_system/campaign.yaml` is the single authoritative initialization commit
marker.  "Committed" (valid marker) is distinct from "complete" (valid
marker + all required managed directories + safe topology).  A partial
layout is never described as operationally complete.

### Exclusive publication

`storage.atomic.exclusive_atomic_write_text` writes a validated temp sibling
and publishes it with `os.link` (atomic create-if-absent), then unlinks the
temp.  There is **no** `open(target, "x")`, direct-streaming or `os.replace`
fallback.  Unsupported hard-link publication fails with `StorageError` and
leaves no target.  Only the current operation's temp path is cleaned; no
wildcard deletion of crash leftovers.

### Audit

The concrete storage initializer owns the audit mechanics; the application
depends only on the `VaultInitializer` protocol.  Sequence: read-only
preflight → bootstrap `_system/` + `_system/audit/` (documented narrow
pre-audit edge) → durable `vault.initialize` intent → create remaining
directories → exclusive config publish → re-read/validate → committed
record.  If final committed-audit append fails after the filesystem commit,
`StorageError` is raised, the already-committed state is stated explicitly,
nothing is rolled back and success is not reported.  Concurrent losers adopt
the winner's identity and never write candidate-specific hashes.

### Path policy

Selected Vault root symlink/junction is resolved once to the physical
authoritative root.  Every managed descendant is checked before every
create/publish for live symlink, dangling symlink and Windows
junction/reparse redirect; containment is re-verified against the resolved
root.  `mkdir(parents=True)` is never used across unverified managed
descendants.  Missing Vault root is rejected; `.obsidian/` is neither
required nor created/modified.

### Managed layout

Fresh init creates exactly: `Sessions/`, `_system/`, `_system/raw/`,
`_system/raw/sessions/`, `_system/audit/`, `Characters/`,
`Characters/NPCs/`, `Locations/`, `Quests/`, `Items/`,
`_system/campaign.yaml` (plus `_system/audit/audit.jsonl` on first audit).
Entity directories are derived from `EntityDirectory`.  Derived artifacts
are **not** created: FTS SQLite, `_system/indexes/`, `State/`, Campaign-State
files, caches/embeddings, post-session artifacts.

### World time

`_system/world_time.json` is explicitly **out of scope**: no `world_tick=0`,
no `--world-tick`, no world-time CLI command and no change to the existing
world-time repository/tool contract.  Postcondition: `dnd init` yields a
**structurally initialized** Vault, not a session-ready one.  The existing
`set_world_time` WRITE tool can initialize the starting tick.  A
deterministic Typer admin surface for starting world time remains a recorded
Stage-13 follow-up decision.

### Evidence (this task)

```text
unit:        config codec / managed layout / application state machine
integration: fresh create, unrelated-content preservation, golden copy,
             zero-write rerun (bytes+mtime+audit count), partial repair,
             file-where-dir conflict, invalid config never overwritten,
             symlink/junction rejection (deterministic + capability-gated),
             resolved root link, no-scan sentinels, no write outside Vault,
             dir-creation failure safe rerun, audit intent failure,
             committed-audit failure semantics, unsupported hard-link failure,
             concurrent init one identity, no derived data, Unicode Vault path
cli:         Russian success/already/partial/error output and exit codes
boundary:    AST layer-boundary + no-scan + CLI-no-filesystem-mutation checks
gates:       pytest (7034 passed, 135 skipped), ruff check, ruff format --check,
             pyright (0 errors), uv lock --check, git diff --check
```


## S13-02 — implementation record (`DONE`)

S13-02 implemented a deterministic, model-free, **strictly read-only** discovery
contract over an already initialized Vault.

### Ownership

```text
storage/vault_discovery.py        inventory, redirect safety, bounded reads,
                                  S13-01 precondition validation, fs issues
application/vault_discovery.py    path classification, frontmatter probe,
                                  ephemeral typed report, discovery service
storage/__init__.py               re-exports the new storage discovery types
```

`vault_initialization.py`, `vault_repository.py`, `storage/paths.py`,
`storage/markdown.py`, retrieval/models/tools/TUI and
`tests/contract/test_boundaries.py` are unchanged.  No CLI or composition
surface was added (the bootstrap user workflow belongs to S13-03).

### Contract

- **Initialized-Vault precondition:** the storage capability validates
  `_system/campaign.yaml` with the S13-01 `parse_campaign_config` contract and
  exposes the validated `campaign_id`; the application layer never opens or
  parses the marker and receives no filesystem authority.
- **Strictly read-only:** no directory creation, no canonical write, no audit
  append, no ChangeSet/derived work.  The result is ephemeral.
- **Path classification ≠ semantic validation:** a file under a managed entity
  directory is `ENTITY_CANDIDATE`, not a proven Entity; canonical Entity
  validation stays with the repository/mapping contract.  Other classes:
  `SESSION_SOURCE`, `USER_SOURCE`, `APPLICATION_CONFIG`, `APPLICATION_RAW`,
  `APPLICATION_CONTROL`, `DERIVED`, `UNSUPPORTED`.
- **Source extensions** (opaque bounded text containers, no parsers):
  `.md`, `.markdown`, `.txt`, `.json`, `.jsonl`, `.yaml`, `.yml`, `.csv`,
  `.html`, `.htm`.  Application-owned `_system`/`State` namespaces take
  precedence, so raw/audit/ChangeSet/derived files are never imported merely
  because they are text-readable.
- **Frontmatter** is structural only: `ABSENT`/`PRESENT`/`UNTERMINATED`; valid
  delimiters with invalid YAML remain `PRESENT`.  No YAML parser runs.
- **Derived Campaign State leaves** are recognized via the storage-owned
  `ARTIFACT_FILENAMES` / `MANIFEST_FILENAME` (no duplicated path constants).
- **`_system` minimum inclusion:** read the campaign marker; inventory
  `world_time.json` and raw/audit/ChangeSet/index/cache/trace content is
  classified ineligible and not content-read.
- **Casefold reserved namespaces:** `_system`, `State`, `Sessions` and the entity
  directories (plus managed `_system` subnamespaces and derived State leaves)
  match casefold-equivalently, so `_SYSTEM/raw/...` is `APPLICATION_RAW` and
  never `USER_SOURCE`; case-distinct physical entries still retain
  deterministic `CASE_ALIAS` reporting.
- **Safety:** the root is resolved once; detected descendant
  symlinks/junctions/reparse redirects are rejected rather than followed; each
  descendant directory is re-authorized (not symlink/junction, contained, still
  a directory) immediately before its scan, narrowing but not atomically
  eliminating the OS-level TOCTOU window; reads re-authorize containment and use
  `O_NOFOLLOW`, which protects the final opened file component where available
  and does not make intermediate parent-component traversal atomic; hidden dirs,
  `.obsidian`/`.git`, OS metadata and editor temp/backup files are excluded
  (casefold-equivalently), while the hidden Campaign State manifest is
  intentionally not blanket-excluded.  Each omitted entry is recorded as typed,
  informational `ExcludedEntry` metadata (relative path + directory flag) on the
  inventory/report; excluded material never becomes inventory or content, so the
  metadata grants no read authority and only lets application coverage policy
  judge whether an exclusion could hide a canonical entity file.  Static
  redirects fail closed; no absolute atomic/no-follow guarantee is claimed.
- **Bounds:** the `20_000` traversal ceiling bounds filesystem entries
  *encountered* (files, directories, redirects, excluded and non-regular
  entries), is enforced lazily without materializing a directory listing, and
  overflow is a fatal `StorageError` with **no partial report**.  Source reads
  are bounded *at read time*: `read_text(relative_path, max_bytes)` retains at
  most `min(per-file limit, remaining aggregate budget)` bytes and reads one
  extra sentinel byte only to detect overflow.  Per-file content `1 MiB`,
  aggregate content `64 MiB` (enforced against actual reads), depth `32`.
  Per-file/aggregate limits produce explicit `SKIPPED`/issue states.  Content is
  read in deterministic Vault-relative casefold + exact order.
- **Failure isolation:** per-file unreadable/invalid-UTF-8/oversize/redirect
  are isolated `DiscoveryIssue`s; only root/precondition/traversal-overflow are
  fatal.

### S13-02 correction pass

A bounded correction pass tightened the trusted boundary after the initial
commit: (C1) the read primitive no longer reads to EOF before enforcing the
byte ceiling, (C2) the application passes the effective
`min(per-file, remaining aggregate)` budget into the bounded read so a source
growing between inventory and read cannot exceed the aggregate budget, (C3) the
traversal ceiling now bounds encountered filesystem entries and no
`list(scandir)` materialization occurs, (C4) descendant directories are
re-authorized immediately before descent, and (C5) reserved namespaces are
matched casefold-equivalently.

### Evidence (this task)

```text
unit:        precondition, inventory, exclusions, hidden-manifest handling,
             case-alias, deterministic Unicode/Cyrillic order, traversal/depth
             bounds (encountered-entry ceiling incl. directories and excluded
             entries, huge-directory bound), bounded-read sentinel limit
             (observed os.read bytes), zero-budget empty read, pre-descent
             directory re-authorization, mixed-case reserved namespaces,
             exact/handled reads, redirect rejection, classification,
             frontmatter probe, service policy
integration: golden-Vault copytree classification, zero-write tree bytes+mtime
             and audit-bytes snapshot, no new paths, invalid-UTF-8 isolation,
             binary/unknown inventory-only, unterminated frontmatter, symlink
             and junction not followed, no outside-Vault read, traversal-overflow
             fatal with no partial report, aggregate/per-file limits, source
             growth after inventory cannot exceed the aggregate budget
contract:    AST boundaries (no model/retrieval/TUI; no marker parser or
             os/pathlib authority in application; no repository/audit/markdown/
             entity import; Campaign State layout ownership reuse; no
             filesystem mutation calls)
gates:       pytest (7146 passed, 141 skipped), ruff check, ruff format --check,
             pyright (0 errors), uv lock --check, git diff --check,
             maintainability contract (no ceiling increased)
capability:  real symlink/junction discovery tests are capability-gated
             (SKIPPED_CAPABILITY where the host cannot create links); the
             pre-descent re-authorization branch is additionally covered
             capability-independently via monkeypatched redirect presentation
residual:    re-authorization narrows but cannot atomically eliminate the
             OS-level TOCTOU window between authorization and the following
             path-based scan/open (adversarial concurrent replacement); static
             redirects fail closed; O_NOFOLLOW protects only the final opened
             file component where the platform exposes it and does not make
             intermediate parent-component traversal atomic
```

## S13-03 — implementation record (`DONE`)

S13-03 implemented a deterministic, read-only **existing-campaign bootstrap
mapping** pipeline that consumes the S13-02 discovery report and produces a
reviewable Stage-10 ChangeSet proposal plus an immutable mapping-evidence
sidecar.  It performs no canonical campaign mutation, no review/approval/apply
and no derived rebuild.

### Ownership

```text
domain/bootstrap_extraction.py             untrusted bounded extraction schema (no EntityId)
storage/bootstrap_types.py                 pure recognition result types (no YAML codec)
storage/bootstrap_canonical.py             filesystem-free canonical parse helper
storage/bootstrap_evidence.py              immutable _system/bootstrap evidence store
application/bootstrap_input.py             eligibility/order/batching/semantic fingerprint
application/bootstrap_canonical.py         read-only canonical projection
application/bootstrap_binding.py           exact type-constrained binding index
application/bootstrap_entity_id.py         deterministic campaign-scoped allocator
application/bootstrap_extraction.py        request/model protocol/semantic validator/merge
application/bootstrap_result.py            result + unresolved vocabulary
application/bootstrap_changeset.py         deterministic ChangeSet producer
application/bootstrap_evidence.py          evidence schema/serialization/persistence policy
application/bootstrap_mapping.py           orchestration + typed run result
application/pydantic_ai_bootstrap.py       zero-tool Pydantic AI extraction adapter
prompts/bootstrap_extraction_v1.py         versioned prompt
composition/bootstrap.py                   discovery/probe/model lifetime/persistence wiring
cli/bootstrap.py                           Russian `dnd bootstrap map` presentation
models/profiles.py                         BOOTSTRAP role
models/pydantic_ai_ollama.py               BOOTSTRAP model factory
application/changeset_validation.py        narrow read-only `EntityReadSource` preflight protocol
storage/__init__.py, cli/main.py           re-exports / command registration
```

### Contract

- **No second traversal:** canonical recognition parses only already-read
  `ENTITY_CANDIDATE` text through the filesystem-free storage helper; S13-02
  remains the single trusted traversal/read boundary.  `storage/paths.py` and
  `storage/vault_discovery.py` are unchanged.
- **Canonical projection:** reliably parsed, uniquely identified, type-matched
  documents are bindable; duplicate ids, directory/type mismatches and other
  parsed conflicts are non-bindable but still block duplicate creation.
  Malformed notes yield no identity and remain source evidence.  The projection
  exposes only the narrow read/list surface (`EntityReadSource`) required by
  `validate_changeset`; it is not a writable repository.  `ObsidianVaultRepository`
  strictness is unchanged.
- **Trust:** the model never emits, copies or selects a canonical `EntityId`,
  revision, path or ChangeSet operation; the extraction schema cannot represent
  them.  Binding is exact type-constrained name then alias only; fuzzy/FTS and
  the player resolver never authorize a bootstrap mutation.
- **Semantic fingerprint:** derived only from eligible source classes
  (`ENTITY_CANDIDATE`, `SESSION_SOURCE`, `USER_SOURCE`) with stable `src_<32hex>`
  references and whole-document SHA-256; application-owned config/raw/control,
  derived and unsupported artifacts are excluded, so persisting
  `_system/changesets/**` and `_system/bootstrap/**` never changes the semantic
  input fingerprint.  Batches are deterministic (200 000 chars/batch, max 16).
- **ChangeSet:** `Provenance.BOOTSTRAP`, `session_ref=None`, `create_entity` and
  `append_fact` only; `update_entity` is refused.  Python-owned defaults
  (`status="unknown"`, `visibility=dm`, `knowledge_status=inferred`, no session
  refs).  Deterministic proposal id `cs_bootstrap_<32hex>`; preflight is a
  proposal-consistency check against the read-only projection, not final apply
  safety.  `NO_CHANGES` is a typed outcome, never an empty ChangeSet.
- **Evidence:** immutable `_system/bootstrap/<changeset_id>.mapping.json`
  (workflow/control; `APPLICATION_CONTROL` under S13-02) binds the exact
  proposal id + fingerprint, campaign, semantic input fingerprint, model
  identity, versions, source evidence, operation provenance and unresolved
  conflicts.  Proposal persistence precedes evidence persistence; an evidence
  failure is reported truthfully as partial workflow persistence with no
  rollback.
- **No implicit world time:** starting world tick is never inferred or written.
- **CLI:** `dnd bootstrap map --vault --config --profile [--dry-run]` renders a
  Russian summary and explicitly states the proposal is not approved/applied,
  that canonical data was not changed, and that bootstrap review/apply is the
  next Stage-13 step (S13-04).  It does not advertise the generic
  `dnd changeset review` path for the bootstrap scenario.

### Correction pass incorporated

```text
C1  no second filesystem traversal; recognition consumes S13-02 text
C2  parsed conflicting canonical identities block duplicate creation
C3  CanonicalStateSnapshot is read-only; validator uses a narrow protocol
C4  semantic fingerprint excludes application-owned/derived artifacts
C5  source_ref is >=128 bits (src_<32hex>)
C6  bootstrap model schema carries no canonical EntityId at all
C7  exact-only Python-owned binding; no fuzzy/FTS mutation authority
C8  same normalized new display name across types => unresolved
C9  snapshot preflight documented as proposal validation, not apply safety
C10 mixed-Vault review/apply readiness owned by S13-04
C11 CLI does not promise generic review/apply usability
C12 immutable evidence sidecar retained
C13 NO_CHANGES is not a completion claim
```

### S13-03 correction pass (C1-C7)

A focused correction pass tightened the accepted mapping architecture (C1-C6)
and, in a further additive pass, closed the silent-exclusion false-coverage
condition (C7):

```text
C1 batching bounds the exact rendered model-visible batch text (markers,
   class/path metadata, separators, source refs), not only source body length;
   a single non-fitting rendered source is TOO_LARGE, never truncated/split
C2 explicit canonical-coverage state from the S13-02 report: unreadable
   ENTITY_CANDIDATE or a discovery issue on a managed entity namespace makes
   coverage incomplete and returns typed NO_CHANGES with
   canonical_coverage_incomplete diagnostics and no model call/mutation
C3 conflicting canonical ids contribute an explicit blocked set; a proposed
   create whose allocated id matches a conflicting identity is refused even
   when the display name differs
C4 changeset_id material includes processor_version, campaign_id, semantic
   input fingerprint, model_profile, prompt_version and extraction schema
   version; the semantic input fingerprint stays source-only
C5 the evidence sidecar stores the bootstrap extraction schema version, not
   the evidence-artifact schema version; the two version domains stay decoupled
C6 trusted merge deterministically scopes batch-local candidate/claim/reference
   ids and conflict groups by batch index, so independent batches may reuse
   local ids without false cross-batch conflicts; run-wide candidate/claim/
   reference/total-char bounds fail through the typed OUTPUT_BOUNDS_EXCEEDED
   contract
C7 silent S13-02 exclusions no longer produce false canonical coverage.  The
   S13-02 traversal remains the only filesystem traversal; it now records each
   omitted entry as typed informational ExcludedEntry metadata (relative path +
   directory flag), carried on VaultSourceInventory and VaultDiscoveryReport.
   CanonicalCoverage.complete now means no known S13-02 read/traversal/exclusion
   condition can hide a canonical .md entity from the report-derived
   recognition universe.  An excluded directory inside/equal to a managed
   entity namespace (arbitrary .md descendants possible) or an excluded .md file
   inside a managed namespace yields CANONICAL_COVERAGE incomplete with no model
   call and NO_CHANGES/no ChangeSet.  Root .git/.obsidian, OS metadata that
   cannot be a canonical .md file (e.g. Characters/NPCs/.DS_Store) and other
   harmless exclusions do not block bootstrap.  The check is deliberately .md
   because the strict canonical repository recognizes only .md entity files.
   Excluded material is never fed to the model; canonical parsing, exact binding
   and proposal identity are unchanged.  The documented OS-level TOCTOU
   limitation remains; no atomic filesystem snapshot is claimed.
```

### Evidence (this task)

```text
unit:        extraction domain bounds/no-identity, input preparation/fingerprint
             (application-artifact exclusion, source_ref >=128-bit, batching,
             oversize skip, Cyrillic), extraction request/semantic validation/
             merge, canonical projection and conflicts, exact binding, allocator,
             producer (Bootstrap provenance, deterministic id, cross-type name
             conflict, duplicate/conflict blocking, system exclusion),
             evidence serialization/persistence, orchestration, adapter,
             BOOTSTRAP role/builder/composition
integration: real temp-Vault mapping+persistence (only workflow artifacts
             change, canonical files bytes+mtime stable, no audit append),
             rediscovery fingerprint stability after persistence, same-id
             different-content fail-closed, strict VaultRepository still fails
             closed on a malformed historical note, Russian CLI presentation,
             dry-run persists nothing, no filesystem read after report,
             runtime evidence stores the extraction schema version
correction:  rendered-batch-bound adversarial (many empty/tiny sources/long
             paths), coverage fail-closed (unreadable ENTITY_CANDIDATE and
             managed-namespace issue) with no model call, conflicting-id
             collision with different display name, proposal-id sensitivity to
             processor/prompt/extraction-schema version, evidence extraction
             version independence, deterministic cross-batch id scoping and
             false-conflict avoidance, run-wide typed overflow; C7 real
             discovery+mapping exclusion regressions (excluded managed subtree
             and excluded managed .md file => typed ExcludedEntry metadata,
             coverage incomplete, no model call, NO_CHANGES/no ChangeSet; root
             .git/.obsidian and .DS_Store remain excluded without blocking)
contract:    AST layer boundaries (domain/storage/application/adapter/
             composition/CLI); pure application modules hold no filesystem or
             YAML authority; binding does not import the player resolver
gates:       pytest (7305 passed, 141 skipped), ruff check, ruff format --check,
             pyright (0 errors), uv lock --check, git diff --check,
             maintainability contract (all production modules <=700 physical
             lines; storage/vault_discovery 695; bootstrap_changeset 593)
```

## S13-04 — implementation record (`DONE`)

S13-04 implemented the trusted bootstrap review/approval/apply workflow over the
persisted S13-03 proposal + immutable mapping evidence.  It performs **no model
call**, no historical-file normalization and no S13-05 completion work.

### Ownership

```text
application/bootstrap_review.py            artifact/review DTOs, proposal
                                           inspection, bounded source views,
                                           build_bootstrap_review, bundle loading
application/bootstrap_evidence_validation.py  evidence/source cross-validation,
                                           operation provenance and freshness
application/bootstrap_readiness.py         typed approval / preconditions / apply
                                           readiness gates + typed strict probe
application/bootstrap_apply.py             bootstrap orchestration over the
                                           existing Stage-10 applier/ledger
composition/bootstrap_review_apply.py      concrete stores/repository/discovery/
                                           audit wiring
cli/bootstrap_review.py                    Russian review/approve/reject/apply
application/changeset_review.py            annotation narrowed to EntityReadSource
cli/changeset.py                           mandatory BOOTSTRAP generic-apply
                                           guard + generic-status Stage-10 warning
cli/main.py                                registers the bootstrap review commands
storage/**, domain/**, storage/vault_discovery.py, application/bootstrap_changeset.py
                                           unchanged
```

### Contract

- **Artifact binding:** the proposal is loaded through the Stage-10 store; the
  evidence sidecar is optional at load time (S13-03 allows partial persistence)
  and malformed evidence fails closed with `StorageError`.  The evidence is bound
  to the exact `changeset_id`, the recomputed proposal fingerprint, BOOTSTRAP
  provenance, `session_ref is None`, the current campaign and one exact evidence
  record per operation.  Filename identity is never trusted.
- **Structural evidence cross-validation:** unique evidence/projection
  `source_ref`s, exact source set, operation indices exactly `0..N-1`, no
  duplicate operation evidence, `create_entity` candidate / `append_fact` claim
  provenance, **at least one `source_ref` on every supported operation**
  (`MISSING_SOURCE_PROVENANCE` otherwise), every operation and unresolved
  `source_ref` present in the evidence sources, and `update_entity` rejected.
  Descriptor-vs-projection field checks run only when the semantic input
  fingerprint still matches, so a changed source is reported as staleness rather
  than evidence corruption (both fail closed).
- **Freshness:** `prepare_bootstrap_input(fresh S13-02 report).input_fingerprint`
  must equal the evidence `input_fingerprint`; campaign identity must match.
  `_system/changesets/**` and `_system/bootstrap/**` never affect the fingerprint.
- **Review state (`BootstrapReviewState`):** `REVIEWABLE` / `STALE_SOURCE` /
  `NOT_REVIEWABLE`.  A real Stage-10 `ChangeSetReview` is produced only for a
  reviewable, coverage-complete, projection-consistent proposal; otherwise only a
  weaker `BootstrapProposalInspection` exists.  Source content previews are
  bounded (`10` previews, `2 000` chars each, `12 000` aggregate) and are rendered
  only when fresh; stale proposals show metadata/hash/path plus explicit status.
- **Approval gate:** evidence binding + freshness + complete canonical coverage +
  projection consistency; a strict repository is deliberately **not** required,
  so a mixed historical Vault may still be approved.  Unresolved items require
  explicit `--acknowledge-unresolved`.
- **Apply readiness (`BootstrapApplyReadiness`):** typed `READY` / `MISSING_EVIDENCE`
  / `EVIDENCE_MISMATCH` / `STALE_SOURCE` / `INCOMPLETE_CANONICAL_COVERAGE` /
  `PROJECTION_INCONSISTENT` / `UNRESOLVED_NOT_ACKNOWLEDGED` / `STRICT_REPOSITORY_NOT_READY`
  / `CHANGESET_PREFLIGHT_FAILED` / `NOT_APPLICABLE`.  Strict availability is a
  typed read-only `StrictRepositoryProbe` (`repository` present with no issue, or
  an absent repository plus a typed `StrictRepositoryIssue` category preserving
  the original project failure; never a bare `None` sentinel).  The probe is a
  read-only `validate_changeset` through `EntityReadSource` (no audit intent, no
  mutation) and classifies failures by typed project errors only — never by
  parsing exception messages.
- **Apply pipeline:** load proposal -> BOOTSTRAP provenance -> evidence ->
  freshness/coverage/projection -> acknowledgement -> exact approval binding ->
  strict readiness + strict preflight -> `load_apply_attempts` + audit ->
  `assert_changeset_applicable` -> `apply_changeset(..., source="bootstrap_apply")`
  -> `record_apply_attempt(..., source="bootstrap_apply")`.  No second applier,
  no rollback/transaction, no bootstrap retry path; `apply_changeset` still runs
  its own fresh strict preflight immediately before the first write.
- **Generic surfaces:** `dnd changeset apply` refuses a BOOTSTRAP-provenance
  proposal before any entity mutation and directs to
  `dnd bootstrap apply <id> --vault ...`; `dnd changeset status` states that its
  applicability result is generic Stage-10 recovery state only and is not
  bootstrap apply readiness.  `application.changeset_status` semantics are
  unchanged.
- **Reject:** a rejection binds to the exact BOOTSTRAP proposal content and is
  allowed with missing/malformed evidence, stale source, incomplete coverage or
  a non-ready strict repository; apply readiness is not required, and the
  proposal is loaded directly through the Stage-10 proposal loader (the evidence
  sidecar is never read to reject).  The existing immutable `ChangeSetApproval` /
  `persist_approval` contract is reused.
- **Mixed Vault:** automatic normalization is **rejected**.  A mixed Vault is
  reviewable when evidence/freshness/coverage allow it, but canonical apply is
  blocked with zero entity writes and zero ChangeSet operation audit intent;
  the user remedies the Vault manually, re-runs `dnd bootstrap map`, and reviews a
  new proposal identity.  An approval never survives a changed semantic input
  fingerprint.
- **No model / no S13-05:** no profile construction, Pydantic AI/Ollama call,
  extraction, Campaign State/index rebuild, world-time init or completion marker.
  Successful apply explicitly states that Stage 13 bootstrap is not yet complete.

### S13-04 correction pass

A bounded correction pass decomposed and tightened the accepted S13-04
architecture without changing its safety model:

```text
C1 the evidence/source cross-validation and freshness logic moved to the
   focused application bootstrap_evidence_validation.py; bootstrap_review.py
   keeps only artifact/review DTOs, proposal inspection, bounded source views
   and build_bootstrap_review (both modules comfortably below 600 lines)
C2 the strict repository `None` sentinel was replaced by the typed
   StrictRepositoryProbe / StrictRepositoryIssue contract; constructor failures
   are surfaced with their typed project category and detail, never discarded
C3 every supported operation now requires at least one source reference
   (MISSING_SOURCE_PROVENANCE), in addition to the existing unknown-source rule
C4 compose_bootstrap_proposal loads the proposal directly through the Stage-10
   proposal loader and no longer reads the evidence sidecar, so rejection is
   available with missing or malformed evidence
```

### Evidence (this task)

```text
unit:        evidence binding/operation/source tamper matrix (including missing
             operation source provenance), review states, preview bounds,
             approval/preconditions/apply readiness, real apply_bootstrap_changeset
             orchestration (applicability gate, PARTIAL preservation,
             attempt-persistence failure, fresh Stage-10 preflight race), CLI
             Russian presentation and exit codes
integration: strict Vault review->approve->apply (real repository, audit source
             bootstrap_apply), second-apply blocked, mixed Vault review works but
             apply blocked with zero writes, duplicate canonical ids blocked,
             generic approval + stale source blocked, missing evidence blocked,
             unresolved acknowledgement required, source change blocked,
             generic apply refused and generic status warning, typed strict-probe
             construction failure with zero writes, reject with missing/malformed
             evidence and non-BOOTSTRAP refusal
contract:    AST layer boundaries for the new application/composition/CLI
             modules (no provider/presentation/filesystem, no model
             construction, CLI write-free) + mandatory generic guard presence
gates:       targeted S13-04 correction (867 passed), full pytest (7393 passed,
             141 skipped), ruff check, ruff format --check (601 files), pyright
             (0 errors), uv lock --check, git diff --check, maintainability
             contract (production/vault_discovery/bootstrap_changeset/
             test_boundaries unchanged; new modules <=700, new tests <=1000)
```

S13-04 stops after human-reviewed canonical apply and durable Stage-10 apply
evidence.  It does not implement Campaign State rebuild, FTS/index rebuild,
bootstrap completion markers, session-ready certification, starting world-time
initialization or final unresolved-resolution workflow — those belong to S13-05.

## S13-05 — implementation record (`DONE`)

S13-05 implemented the deterministic, fail-closed bootstrap **finalization**
workflow that decides explicit completion, rebuilds the disposable derived
projections and certifies session-runtime prerequisites.  It performs **no
canonical mutation**: the only canonical write in S13-05 is the separate
``dnd time init`` admin command.

### Ownership

```text
application/bootstrap_completion.py        typed completion vocabulary + closure policy
composition/bootstrap_completion.py        ordered finalization pipeline
composition/index_rebuild.py               shared UI-agnostic FTS rebuild/verify
composition/world_time.py                  world-time repository factory
cli/bootstrap_finalize.py                  Russian `dnd bootstrap finalize`
cli/time.py                                Russian `dnd time init`
cli/main.py                                registration + index rebuild routed through composition
```

### Contract

- **Fresh closure assessment, not historical apply.**  Completion never accepts an
  earlier applied BOOTSTRAP ChangeSet as proof.  It reruns the accepted S13-02
  discovery and the accepted S13-03 ``BootstrapRuntime.run(report, persist=True)``
  pipeline (existing BOOTSTRAP role/prompt/schema/binder/producer) once.  Python
  decides completion from the typed mapping result; the model never decides.
  Multi-cycle bootstrap and no-change-from-start bootstrap are both supported; no
  "latest ChangeSet" pointer and no second apply ledger exist.  Old S13-03
  evidence is historical and is never refreshed or mutated.
- **Immediate source-stability recheck (ordering).**  After the single mapping run
  the pipeline recomputes a fresh semantic fingerprint *before* returning any
  normal mapping terminal status.  A mismatch returns
  ``SOURCE_CHANGED_DURING_VALIDATION`` (primary), never ``PENDING_CHANGESET``;
  persisted proposal/evidence remain truthful workflow artifacts and the user
  reruns mapping/finalize.
- **Typed non-boolean status.**  ``BootstrapCompletionStatus`` distinguishes
  ``COMPLETE`` / ``COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED`` / ``PENDING_CHANGESET``
  / ``CANONICAL_COVERAGE_INCOMPLETE`` / ``UNRESOLVED_NOT_ACKNOWLEDGED`` /
  ``UNINITIALIZED_VAULT`` / ``RECOVERY_BLOCKED`` / ``CANONICAL_NOT_READY`` /
  ``WORLD_TIME_UNINITIALIZED`` / ``WORLD_TIME_INVALID`` /
  ``ACTIVE_SESSION_PRESENT`` / ``MAPPING_FAILED`` /
  ``PROPOSAL_PERSISTENCE_FAILED`` / ``EVIDENCE_PERSISTENCE_FAILED`` /
  ``SOURCE_CHANGED_DURING_VALIDATION`` / ``CAMPAIGN_STATE_REBUILD_FAILED`` /
  ``FTS_REBUILD_FAILED`` / ``DERIVED_VERIFICATION_FAILED``.  Sub-failures are
  preserved in ``issues`` and never concealed by the primary status.
- **Incomplete canonical coverage is never acknowledgeable.**
  ``CANONICAL_COVERAGE_INCOMPLETE`` blocks completion and derived rebuild, and
  ``--acknowledge-unresolved`` cannot override it.  This includes the accepted
  S13-03 no-model coverage-incomplete ``NO_CHANGES`` path (zero model calls, zero
  derived writes).  Ordinary unresolved diagnostics are the only acknowledgeable
  category; no reason-specific automatic acceptance is introduced.
- **Prerequisites.**  Strict canonical validation uses only
  ``ObsidianVaultRepository.list_entities()`` (malformed Markdown, duplicate
  ``EntityId``, type/directory mismatch, unsafe path and corrupt audit topology
  all block).  World time is required (raw ``world_tick`` exposed) and active
  session blocks finalization; a session-repository ``ConflictError``/
  ``StorageError`` fails closed as ``RECOVERY_BLOCKED``/``CANONICAL_NOT_READY``
  rather than masquerading as an ordinary active session.
- **Derived rebuild semantics.**  Campaign State and FTS are independent
  disposable stores with no whole-finalization transaction and no rollback.  A
  ``CampaignStateSourceChangedError`` is classified as
  ``SOURCE_CHANGED_DURING_VALIDATION`` and **no not-yet-started derived
  maintenance** is begun after it; an ordinary Campaign State storage failure
  still allows the independent FTS attempt and vice versa.  Verification is
  literal: Campaign State ``inspect == CURRENT`` and FTS
  ``verify_freshness(fresh documents)``; a final semantic source-stability check
  must still match.
- **Starting world time admin surface.**
  ``dnd time init --vault PATH --world-tick INTEGER`` is model-free, first
  validates the S13-01 initialized-Vault precondition in read-only fashion
  through the trusted ``ObsidianVaultInitializer.inspect()`` capability (valid
  ``_system/campaign.yaml`` marker, known campaign identity, no missing managed
  directories), then runs the recovery preflight, then uses
  ``ObsidianWorldTimeRepository.initialize_current_world_time`` with the shared
  ``build_audit_context`` (source ``cli``, prefix ``cli-time-init``), validates a
  raw signed ``WorldTick``, initializes revision 1 once, refuses an existing
  ``world_time.json`` and never infers/converts a tick or parses a calendar.  An
  absent marker or an incomplete layout is refused with instructions to run/rerun
  ``dnd init``; this surface never initializes or repairs the Vault.  No
  ``set``/``advance`` surface is added.  This closes the recorded Stage-13
  follow-up: a freshly initialized campaign can become session-ready without an
  LLM write tool call.
- **Shared FTS composition.**  ``composition/index_rebuild.py`` owns the single
  canonical-documents read and the
  ``SqliteFtsIndex.rebuild``/``verify_freshness`` calls used by both
  ``dnd index rebuild`` and bootstrap finalization; the existing CLI behavior is
  preserved and the FTS source-fingerprint algorithm is not duplicated.

### Historical `Campaign/Bootstrap.md` reconciliation

The original Stage-13 architecture sketch expected a ``Campaign/Bootstrap.md``
imported-history boundary.  That sketch is **superseded for the MVP** by the
accepted reviewed bootstrap workflow: imported knowledge becomes canonical only
through reviewed/applied ChangeSets plus immutable mapping evidence under
``_system/bootstrap/**``, and system-observed history lives in Sessions/raw
data.  No canonical ``Campaign`` document schema, repository or audited writer
exists, so creating an ad-hoc Markdown file would bypass the ``VaultRepository``/
audit boundary.  ``Campaign/Bootstrap.md`` is therefore deliberately **not**
part of Stage 13 (not an unfinished requirement).

### Completion marker

No ``_system/bootstrap/*completion*`` artifact is created.  Current operational
readiness is re-derived on demand; a durable marker would itself need freshness/
invalidation semantics after later sessions and canonical changes and would risk
becoming a second Source of Truth.  Existing durable workflow evidence remains
sufficient.

### Evidence (this task)

```text
unit:        closure classification matrix (coverage-incomplete never
             acknowledgeable; partial evidence persistence; proposal; unresolved;
             clean no-changes), status/result `completed` semantics,
             `dnd time init` help/negative tick/audit intent+committed/refusal
integration: clean NO_CHANGES -> COMPLETE with Campaign State CURRENT + verified
             FTS and no historical ChangeSet; negative world tick;
             coverage-incomplete NO_CHANGES + --acknowledge-unresolved ->
             CANONICAL_COVERAGE_INCOMPLETE with zero model calls and zero derived
             writes; persisted proposal + source drift -> SOURCE_CHANGED (not
             PENDING) with workflow artifacts retained and zero derived writes;
             stable proposal -> PENDING_CHANGESET loadable by the S13-04 bundle
             loader; partial evidence persistence -> EVIDENCE_PERSISTENCE_FAILED;
             partial persistence + drift -> SOURCE_CHANGED with persistence
             failure retained in diagnostics; CampaignStateSourceChangedError ->
             SOURCE_CHANGED with FTS not started; ordinary Campaign State failure
             -> CAMPAIGN_STATE_REBUILD_FAILED with FTS retained/verified;
             multiple-active-session conflict -> RECOVERY_BLOCKED (not
             ACTIVE_SESSION_PRESENT); malformed canonical note blocked before the
             model; missing world time blocked; uninitialized Vault; source drift
             after derived rebuild; Russian CLI COMPLETE/PENDING rendering and
             exit codes
contract:    AST layer boundaries for the new application/composition/CLI
             modules (pure application policy, no presentation in composition,
             CLI write-free, model-free time CLI) + FTS composition reuse and
             main-CLI routing
gates:       targeted S13-05 suites (846 passed with maintainability contract),
             full pytest (7441 passed, 141 skipped; one pre-existing timing-flaky
             TUI concurrency test passed on isolated and module rerun),
             ruff check, ruff format --check (611 files), pyright (0 errors),
             uv lock --check, git diff --check, maintainability contract
```

## Stage-13 Source-of-Truth rules carried forward

```text
Vault remains the only canonical campaign Source of Truth
derived data (indexes, Campaign State, caches) remains rebuildable
stable IDs / revisions / provenance / visibility remain mandatory
safe traversal / path policy
clarification / unresolved handling instead of speculative mutation
model-generated or inferred writes use ChangeSet review / apply
Campaign State / indexes rebuilt from canonical Vault
```

## Surfaces

Typer is the primary bootstrap/administration surface. A future TUI
progress/review surface is optional and is not required for S13-01.

## Non-goals of this document

```text
no `dnd init` implementation
no BootstrapService implementation
no bootstrap traversal / import / mapping implementation
no bootstrap ChangeSet code
no Stage-13 tests
```

## References

- `DEVELOPMENT_STATUS.md` — canonical current roadmap state.
- `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` — TUI track review/handoff.
- `docs/adr/0008-textual-tui-presentation-architecture.md` — presentation-layer ADR.
- `docs/development/project-invariants.md` — durable architecture/Vault invariants.
