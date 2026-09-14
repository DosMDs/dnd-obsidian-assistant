# D&D Session Assistant — OpenCode repository instructions

OpenCode is a **development agent** for this repository. It is not the
application's runtime model. Development tooling must not change application
runtime behavior or architecture.

## Project identity

Local, offline-first Python application for long-term D&D/RPG campaign memory.
Durable campaign state lives in an Obsidian Vault. Python owns trusted domain,
application, storage, retrieval, calendar and tool-execution logic. Local LLMs
are replaceable operators used for language understanding, tool selection,
extraction, summaries and recaps.

## Status authority

`DEVELOPMENT_STATUS.md` is the canonical current roadmap state. Historical
chats, Final Reports and context snapshots do **not** override it. Read it
before planning. Current code/contracts and Git evidence establish what exists;
do not infer status from historical reports.

## Architecture trust boundary

```text
Obsidian Vault   = the only campaign Source of Truth
Python           = trusted domain / application / storage logic
ToolExecutor     = trusted side-effect authorization boundary
LLM / framework  = untrusted, replaceable mechanism
```

Model or framework output is untrusted until validated by Python. Framework
tool exposure, filtering or approval is **not** an authorization boundary.
Runtime LLM/agent code must never receive arbitrary filesystem or shell access
to the Vault. Every Vault write flows through `ToolExecutor` / domain/application
services / `VaultRepository`. Domain and storage must not depend on Ollama,
Pydantic AI or any concrete model/provider.

## Developer-agent role and startup discipline

Before editing:

```text
read DEVELOPMENT_STATUS.md
capture branch / HEAD / upstream / working tree
inspect relevant docs, code and tests
identify the owning layer and intended diff
map each acceptance criterion to literal evidence
```

Do not invent missing APIs when repository evidence can answer the question;
inspect the code first.

## Adaptive task routing

Classify the task before editing. Task size changes routing depth, not whether
the routing decision is made.

```text
DIRECT
  - clear owning layer
  - clear expected diff
  - no material architecture choice
  - no project-boundary risk
  - known correction / execution / accepted-plan implementation

PLAN_REQUIRED
  - architecture or owning layer unclear
  - public/domain/storage/runtime contract changes
  - multiple architectural layers
  - Vault / ToolExecutor / Source-of-Truth risk
  - migration/refactor/removal uncertainty
  - eval/scoring/measurement methodology changes
  - repeated correction / root cause unclear
```

`build` is the default agent. The `plan` primary agent is the explicit read-only
agent for PLAN_REQUIRED work; PLAN never mutates repository state and never
automatically transitions to BUILD. A correction does not automatically require
PLAN: non-semantic corrections to an already accepted plan use DIRECT execution
or a short revalidation. Detailed procedure: docs/development/task-workflow.md.

## Scope discipline

Make the smallest coherent change and stay within the authorized task scope.
Report unrelated defects instead of absorbing them. Do not silently broaden
task or stage scope. **Never automatically begin the next roadmap task after
completing the current one.**

## Quality and evidence

```text
claim strength <= evidence strength
```

A green test does not prove an unasserted behavior. Select quality gates from
the actual final Git diff, not the task title. Preserve literal measurements
and separate measured results from historical claims. No findings is not proof
of checks that were not run.

`uv run pyright` is the canonical repository-wide type gate for Python code and
test changes and must complete with 0 errors. Pytest green does not override
Pyright failure, and Pyright green does not replace pytest or Ruff. Details:
`docs/development/quality-and-evidence.md`.

## Source editing

Mutate repository text through OpenCode's structured `edit` / `write` /
`apply-patch` facilities. Do not automatically fall back to:

```text
Python rewrite scripts
PowerShell text generation
shell redirection
sed / perl bulk mutation
base64 reconstruction
```

as source editors.

## Context and token economy

Use the smallest sufficient context. This is a durable project rule, canonical
form: **minimize context, not rigor**.

- Search before reading large files.
- Prefer LSP definitions/references/symbols over broad code scanning.
- Read only relevant sections of large files where possible.
- Do not repeatedly read unchanged files without a concrete reason.
- Load detailed policies/skills only when relevant to the current task.
- Do not globally load large development documents.
- Pass subagents only the task, diff and evidence they need.
- Reuse already collected literal evidence instead of rerunning expensive work.
- Keep Final Reports concise and evidence-oriented.

Token economy must never weaken architecture, safety, acceptance coverage, tests
or evidence quality.

## Shell

Shell is normal and expected for:

```text
uv
pytest
pyright
ruff
git
diagnostics
project CLI
```

## Git finalization

When a Task Contract requires normal Git finalization:

```text
run gates
→ stage only task files
→ one coherent commit
→ ordinary push
→ verify HEAD == upstream
→ clean task-owned working tree
```

An authorized Task Contract is the confirmation; ordinary commit/push does
**not** require a second confirmation, and does not require interactive
approval merely because it is Git.

Always forbidden without explicit architecture/user authorization:

```text
git push --force / --force-with-lease
git reset --hard
published-history rewrite
destructive rebase
destructive branch deletion / git clean
```

## Detailed policy documents

Durable detail is lazy/on-demand, not always-on. Read the relevant document
when its trigger applies:

```text
docs/development/task-workflow.md
  every development task (adaptive routing, session boundaries, Git finalization)

docs/development/quality-and-evidence.md
  tests / evals / parity / acceptance evidence / quality-gate selection

docs/development/editing-and-recovery.md
  source mutation or an edit/write tool failure

docs/development/untrusted-boundaries.md
  untrusted input / provider / parser / numeric boundary

docs/development/maintainability.md
  large module or test growth / refactor / ratchet change

docs/development/project-invariants.md
  architecture / product scope / Vault write safety / platform / UI
```

## Detailed project documents

```text
DEVELOPMENT_STATUS.md   canonical current roadmap state
docs/development/       durable OpenCode-era development policies (lazy)
docs/adr/               architecture decisions
docs/stages/            detailed stage history and evidence
docs/migrations/        detailed migration plan/history/evidence
.opencode/agents/       read-only review subagents
```
