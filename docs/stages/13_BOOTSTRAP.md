# Stage 13 — Bootstrap

**Status:** `IN PROGRESS` (S13-01 `DONE`, S13-02 `DONE`)

This document is the durable Stage-13 handoff/plan contract produced by TUI-06.
It is **not** Stage-13 implementation and contains no Stage-13 code, tests or
schemas. Current roadmap state lives in `DEVELOPMENT_STATUS.md`.

## Gate

The Textual TUI prerequisite is satisfied (the accepted track was integrated
by `TUI-M01`). Stage 13 is `IN PROGRESS`; `S13-01` and `S13-02` are `DONE`; the
next task is `S13-03 — Existing Campaign Bootstrap / Mapping`. There is no
current Stage-13 blocker.

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

These are dependency-ordered task boundaries. `S13-01` and `S13-02` are
implemented/`DONE`; `S13-03` … `S13-05` remain planned boundaries and are not
yet implemented.

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
- **Safety:** the root is resolved once; descendant symlinks/junctions/reparse
  redirects are never followed; each descendant directory is re-authorized
  (not symlink/junction, contained, still a directory) immediately before its
  scan, narrowing the OS-level TOCTOU window; reads re-authorize containment and
  use `O_NOFOLLOW` where available; hidden dirs, `.obsidian`/`.git`, OS metadata
  and editor temp/backup files are excluded (casefold-equivalently), while the
  hidden Campaign State manifest is intentionally not blanket-excluded.
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
residual:    the pre-descent re-authorization narrows but cannot atomically
             eliminate the OS-level TOCTOU window between the check and
             os.scandir; on platforms without O_NOFOLLOW the pre-open redirect
             check is the residual best-effort read guard
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
