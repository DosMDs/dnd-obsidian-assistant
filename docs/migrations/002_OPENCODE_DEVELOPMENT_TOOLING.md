# Migration 002 — OpenCode development tooling

## 1. Purpose

Record the migration of the repository's durable developer-tooling rules from
the GigaCode-era corpus into a smaller, vendor-neutral OpenCode-era policy
structure, while minimizing always-on context and preserving every important
invariant.

This is a **development-tooling** migration only. It does not change application
runtime behavior or architecture.

## 2. Relationship to the application roadmap

- The application roadmap and stage/migration state remain canonical in
  `DEVELOPMENT_STATUS.md` and are untouched by this migration.
- This document is the canonical status/history record for the separate
  developer-tooling migration. The plan is to keep OC status here rather than in
  `DEVELOPMENT_STATUS.md` until cutover.
- Legacy GigaCode artifacts (`.gigacode/`, `.gigacode_vsc/`, `GIGACODE.md`,
  `README_GIGACODE_SETUP.md`) remain in place as source/reference material until
  cutover.

## 3. Branch and base

```text
Branch:  chore/opencode-migration
Base:    ef38f08  (application-branch tip when OC foundation work began)
Upstream: origin/chore/opencode-migration
OC foundation commits:
  3efcb38  chore: add OpenCode development foundation        (OC-00/OC-01)
  a46ec4e  chore: harden OpenCode agent permissions          (OC-01C)
  442dfeb  chore: add OpenCode Python LSP support            (OC-01LSP)
```

## 4. OC task sequence

| Task | Focus | Status |
|---|---|---|
| OC-00 | OpenCode migration inventory | DONE |
| OC-01 | OpenCode development foundation (AGENTS.md, opencode.json, agents) | DONE |
| OC-01C | Harden OpenCode agent permissions | DONE |
| OC-01LSP | OpenCode Python LSP support | DONE |
| OC-02 | Consolidate durable development rules into lazy OpenCode-era policies | DONE |
| OC-03 | Migrate `.gigacode/skills/*` to OpenCode-era skills | PLANNED |
| OC-04 | (planned; defined by its Task Contract) | PLANNED |
| OC-05 | (planned; defined by its Task Contract) | PLANNED |
| OC-06 | (planned; defined by its Task Contract) | PLANNED |

## 5. OC-02 scope

- Migrated the durable meaning of all 21 `.gigacode/rules/*.md` files into a
  compact always-on `AGENTS.md` plus six lazy policy documents under
  `docs/development/`:
  `task-workflow.md`, `quality-and-evidence.md`, `editing-and-recovery.md`,
  `untrusted-boundaries.md`, `maintainability.md`, `project-invariants.md`.
- Added context/token economy as an explicit always-on invariant
  (`minimize context, not rigor`).
- Detailed policy documents are **not** globally injected through
  `opencode.json`; `AGENTS.md` carries concise read-when triggers.
- `.gigacode/rules/*` were not deleted or edited; skills migration is deferred
  to OC-03.

Detailed Final Reports are intentionally not duplicated here.
