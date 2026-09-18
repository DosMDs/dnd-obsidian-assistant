# Stage 13 — Bootstrap

**Status:** `NOT STARTED`

This document is the durable Stage-13 handoff/plan contract produced by TUI-06.
It is **not** Stage-13 implementation and contains no Stage-13 code, tests or
schemas. Current roadmap state lives in `DEVELOPMENT_STATUS.md`.

## Gate

Stage 13 must not begin until the Textual TUI Architecture Track has completed
normal implementation, review, repository integration/status reconciliation and
independent acceptance. TUI-06 completes the review/status/handoff portion; the
ff-only integration remains a separate task (`TUI-M01`). Stage 13 stays `NOT
STARTED` and gated until independent acceptance of `TUI-M01`. Stage 13 is gated,
not `BLOCKED`.

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

These are planned task boundaries only, not yet implemented.

## S13-01 — `dnd init` handoff requirements

S13-01 is the first Stage-13 task. It must decide and test at least:

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
