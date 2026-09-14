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

## Shell

Shell is normal and expected for:

```text
uv
pytest
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

## Detailed project documents

```text
DEVELOPMENT_STATUS.md   canonical current roadmap state
GIGACODE.md             full legacy project instructions (migration reference)
docs/adr/               architecture decisions
docs/stages/            detailed stage history and evidence
docs/migrations/        detailed migration plan/history/evidence
.opencode/agents/       read-only review subagents
```
