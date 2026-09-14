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
- At cutover (OC-05), all tracked legacy GigaCode artifacts (`.gigacode/`,
  `.gigacode_vsc/gigacode.jsonc`, `GIGACODE.md`, `README_GIGACODE_SETUP.md`)
  were retired; current canonical surfaces no longer reference them. Untracked
  local GigaCode session state remains on disk intentionally (see §10).

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
| OC-02C | Correction: make plan-first workflow mandatory | DONE |
| OC-03 | Migrate `.gigacode/skills/*` to OpenCode-era skills | DONE |
| OC-03A | Remove or isolate legacy development-agent artifacts | DONE |
| OC-04 | DeepSeek V4.1 Flash development-agent qualification | DONE |
| OC-05 | Complete cutover; retire tracked GigaCode tooling | DONE |
| OC-06 | (planned; defined by its Task Contract) | FUTURE / PLANNED |

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

## 6. OC-02C correction

- Made plan-first mandatory for every development task, replacing the earlier
  conditional wording that limited read-only PLAN behavior to multi-file,
  architectural, migration, storage or risky changes.
- Added a compact always-on invariant to `AGENTS.md` and the full procedure
  (lifecycle, session boundaries, PLAN REPORT/STOP, acceptance boundary,
  same-session BUILD, state-change stop condition, correction = new
  task/session/PLAN, two-phase BUILD handoff) to
  `docs/development/task-workflow.md`; `quality-and-evidence.md` was not
  changed.
- `docs/adr/0001-development-workflow-vscode-gigacode.md` retains its original
  conditional PLAN wording as historical evidence from an accepted, dated ADR,
  not current workflow policy.

## 7. OC-03 scope

- Created `.opencode/skills/` as the sole canonical OpenCode-era skill root,
  with one `SKILL.md` per migrated skill (17 total): stage-workflow,
  pre-finalization-audit, correction-review, code-review, eval-harness,
  pydantic-ai-migration, testing, bug-fix, implement-feature, domain-model,
  vault-repository, calendar-service, retrieval-entity-resolution,
  session-runtime, tool-layer, model-gateway, changeset.
- Ported/merged/rewrote the 17 `.gigacode/skills/*` sources and reconciled the
  11 pre-existing `.agents/skills/*` copies; generic durable policy is
  referenced from `AGENTS.md`/`docs/development/*` rather than duplicated.
- Scoped frontmatter to `name` + `description`; skills remain on-demand and are
  not globally injected through `opencode.json`.
- Legacy sources (`.gigacode/skills/`, `.agents/`, `.codex/`) and
  `docs/development/review-workflow.md` were left untouched; deletion/cleanup
  belongs to later cutover tasks. Pydantic AI migration remains a dedicated
  skill, not merged into `model-gateway`.

## 8. OC-03A scope

- Removed the untracked foreign/compatibility surfaces `.agents/`,
  `.codex/` and `docs/development/review-workflow.md` after confirming they
  were untracked, contained no secret/local-credential content, and were fully
  superseded by `.opencode/skills/` and `.opencode/agents/`.
- Migrated only the durable host-neutral review-orchestration procedure from
  `review-workflow.md` into `.opencode/skills/code-review/SKILL.md`; the
  Codex-specific TOML agents, branch names and setup references were not
  migrated.
- Isolated tracked legacy GigaCode artifacts from the active OpenCode workflow
  without deleting them: removed `GIGACODE.md` from `AGENTS.md` navigation and
  replaced GigaCode-era examples in `docs/development/quality-and-evidence.md`
  with OpenCode-era paths.
- Deferred physical retirement: `.gigacode/`, `.gigacode_vsc/`, `GIGACODE.md`
  and `README_GIGACODE_SETUP.md` remain in place because canonical/status/test
  references still cite them. Their removal belongs to a coordinated cutover
  task (OC-05), not OC-03A; no runtime/application behavior changed.
- Historical ADR, migration, maintenance and stage evidence were left
  untouched.

## 9. OC-04 scope

- Qualified `deepseek/deepseek-flash` as the default OpenCode development-agent
  model under a frozen external suite (SHA-256 recorded in
  `003_DEEPSEEK_DEVELOPMENT_AGENT_QUALIFICATION.md`).
- Result: **ACCEPTED** (weighted score 92/100; zero critical failures; recorded
  weakness: Q8 skill selection).
- `opencode.json`, `AGENTS.md`, `.opencode/skills/*` and `.opencode/agents/*`
  were not modified; the qualification ran in a disposable system-temp worktree
  that was removed afterward.

## 10. OC-05 scope

- Retired **42 tracked GigaCode artifacts**: the `.gigacode/` tree (21 rules, 17
  skills, local-instruction example), `.gigacode_vsc/gigacode.jsonc`,
  `GIGACODE.md` and `README_GIGACODE_SETUP.md`. Every deletion was mapped to a
  canonical replacement (AGENTS.md, `docs/development/*`, `.opencode/skills/*`,
  `opencode.json`) before removal.
- Reconciled current references: replaced the deleted-GigaCode PAIM guidance
  pointers in `DEVELOPMENT_STATUS.md` with canonical OpenCode-era references, and
  retargeted the test-policy docstring citations in
  `tests/contract/test_test_harness_policy.py` to
  `docs/development/quality-and-evidence.md` and
  `docs/development/maintainability.md` (docstrings only; assertions unchanged).
- The canonical OpenCode developer surface is `AGENTS.md`, `opencode.json`,
  `.opencode/skills/` (17 skills), `.opencode/agents/` (3 agents),
  `docs/development/` and vendor-neutral `.vscode/` configuration.
- Historical references to deleted `.gigacode/*` paths in `docs/adr/*`,
  `docs/stages/*`, `docs/maintenance/*` and `docs/migrations/001_*` were
  preserved unchanged; Git history retains the retired artifacts.
- User-local untracked/ignored GigaCode state (`.gigacode/.gitignore`,
  `.gigacode_vsc/.gitignore`, `.gigacode_vsc/agent-manager.json`,
  `.gigacode_vsc/plans/*`) and the root `.gitignore` legacy protections were
  intentionally left untouched; they are session state, not active tooling, and
  do not influence OpenCode discovery.
