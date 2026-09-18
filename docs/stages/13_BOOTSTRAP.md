# Stage 13 — Bootstrap

**Status:** `IN PROGRESS` (S13-01 `DONE`, S13-02 `DONE`, S13-03 `DONE`)

This document is the durable Stage-13 handoff/plan contract produced by TUI-06.
It is **not** Stage-13 implementation and contains no Stage-13 code, tests or
schemas. Current roadmap state lives in `DEVELOPMENT_STATUS.md`.

## Gate

The Textual TUI prerequisite is satisfied (the accepted track was integrated
by `TUI-M01`). Stage 13 is `IN PROGRESS`; `S13-01`, `S13-02` and `S13-03` are
`DONE`; the next task is `S13-04 — Bootstrap ChangeSet Review / Apply`. There
is no current Stage-13 blocker.

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

These are dependency-ordered task boundaries. `S13-01`, `S13-02` and `S13-03`
are implemented/`DONE`; `S13-04` and `S13-05` remain planned boundaries and are
not yet implemented.

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
  intentionally not blanket-excluded.  Static redirects fail closed; no
  absolute atomic/no-follow guarantee is claimed.
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

### S13-03 correction pass (C1-C6)

A focused correction pass tightened the accepted mapping architecture:

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
             false-conflict avoidance, run-wide typed overflow
contract:    AST layer boundaries (domain/storage/application/adapter/
             composition/CLI); pure application modules hold no filesystem or
             YAML authority; binding does not import the player resolver
gates:       pytest (7298 passed, 141 skipped), ruff check, ruff format --check,
             pyright (0 errors), uv lock --check, git diff --check,
             maintainability contract (all production modules <=700 physical
             lines; bootstrap_changeset 593)
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
