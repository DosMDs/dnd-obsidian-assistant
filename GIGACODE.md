# D&D Session Assistant — GigaCode Project Instructions

## Project purpose

D&D Session Assistant is a local, offline-first Python application for long-term D&D/RPG campaign memory.

The durable campaign state lives in an Obsidian Vault. Python owns trusted domain logic, validation, filesystem operations, search, calendar calculations and tool execution. Local LLMs accessed through Ollama are replaceable operators used for language understanding, tool selection, extraction, summaries and recaps.

## Non-negotiable architecture

1. Obsidian Vault is the only canonical Source of Truth.
2. LLM/framework output is untrusted until validated by Python.
3. Runtime LLM/agent code must never get arbitrary filesystem or shell access to the Vault.
4. Every Vault write must flow through `ToolExecutor` / domain/application services / `VaultRepository`.
5. Domain and storage layers must not depend on Ollama, Pydantic AI or any concrete model/provider.
6. SQLite/FTS/cache/embeddings/framework state are derived and rebuildable from Vault/raw history.
7. Game-time arithmetic is deterministic Python `CalendarService` logic using canonical world time types/`world_tick`.
8. Raw session logs are append-only and immutable after session end according to the accepted session contract.
9. Model-generated post-session changes use `ChangeSet -> validate -> review -> apply`.
10. Ambiguous entity resolution prefers clarification over speculative write.
11. Stable IDs, revisions, provenance, visibility, atomic writes and audit logging are core requirements.
12. Do not introduce vector DB, embeddings, LoRA, voice, Web UI, graph DB, combat automation or complex RAG before demonstrated MVP need.
13. MVP application UI is Russian-only. Application-owned CLI/TUI help, prompts, confirmations, statuses, warnings and user-facing errors are Russian.
14. Do not add i18n/locale catalogs or additional interface languages unless product scope explicitly changes.
15. Campaign-facing text uses UTF-8 and supports Cyrillic. Internal identifiers/file/module names and serialized machine enums may remain English.
16. Runtime LLM output intended for the user is requested in Russian unless an explicit later requirement overrides it.
17. Framework tool visibility/filtering/approval is not an authorization boundary; `ToolExecutor` is the final trusted tool execution boundary.

## Dependency order and current migration gate

Base dependency order:

`Environment -> Project contracts -> Domain schemas -> VaultRepository -> Calendar -> Retrieval/EntityResolver -> Session runtime -> Tool layer -> Model/runtime -> Fast Agent -> ChangeSet -> Post-session processing -> Campaign State -> Bootstrap -> Evals/hardening`

Tests are implemented with each stage.

Current special gate after accepted S9-06 and before S9-07/Stage 10:

```text
PAIM — Pydantic AI Runtime Migration
```

Always read `DEVELOPMENT_STATUS.md` before planning. Do not infer current status from this file.

## Development status and documentation

Canonical responsibility split:

```text
DEVELOPMENT_STATUS.md
  compact current roadmap state

docs/stages/*.md
  detailed stage history/evidence

docs/migrations/*.md
  detailed migration plan/history/evidence

docs/adr/*.md
  significant architecture/workflow decisions
```

Do not append full Final Reports or long correction narratives to `DEVELOPMENT_STATUS.md`.

Task completion updates compact status and detailed stage/migration record only where relevant. Final stage/migration reviews keep detailed evidence in the corresponding detailed document.

## PAIM-specific instructions

The accepted custom S9-06 runtime in `main` is the reference/rollback point. PAIM is developed in a separate branch.

Read:

```text
docs/adr/0003-pydantic-ai-runtime-migration.md
docs/migrations/001_PYDANTIC_AI_RUNTIME.md
.gigacode/rules/40-pydantic-ai-migration.md
```

Use `.gigacode/skills/pydantic-ai-migration/SKILL.md` for PAIM implementation/review tasks.

### Framework ownership

Pydantic AI may own generic model/message/tool/structured-output/run-loop mechanics.

It must not own:

```text
domain/storage authority
Vault writes
calendar arithmetic
entity ambiguity policy
permissions/session/audit authorization
raw session truth
ChangeSet apply policy
```

### Migration outcomes

All are valid:

```text
ACCEPTED
PARTIAL
REJECTED
```

Do not weaken architecture merely to avoid `PARTIAL` or `REJECTED`.

### No permanent dual runtime

Short-lived comparison code/tests are allowed for qualification. Do not keep two equal-status production runtimes behind a feature flag merely for rollback. Git/main is the fallback.

### Framework limitation handling

```text
focused reproduction
→ documented public extension point
→ selective custom component if small/cohesive
→ recommend REJECTED if workaround becomes large/fragile/private-internal
```

Do not patch private framework internals as normal architecture.

## Technology baseline

- Python 3.12+
- `uv`
- Typer + Rich
- Pydantic
- ruamel.yaml
- httpx
- watchfiles
- RapidFuzz
- SQLite FTS5 as derived lexical index
- pytest
- Hypothesis
- pytest-cov
- respx where provider HTTP mocking is used
- Ruff
- Ollama as first runtime provider

Pydantic AI is a PAIM candidate dependency until qualification selects and pins an accepted version.

## Cross-platform requirements

The application must run natively on Windows and macOS.

- Use `pathlib.Path`.
- Use UTF-8 explicitly for project-controlled text files.
- Do not hard-code OS-user paths/drive letters.
- Do not require Bash, Make, WSL or GNU-only utilities.
- Prefer portable Python and `uv run ...` commands.
- Avoid `shell=True` and platform-specific shell syntax in application code.
- Filesystem tests use temporary directories; OS-specific semantics require targeted coverage.

## Package boundaries

Expected responsibility layout:

- `cli/`: Typer commands/presentation.
- `application/`: orchestration/use cases/agent application policy.
- `domain/`: pure domain models/rules.
- `storage/`: Vault persistence, atomic writes, audit, locks.
- `retrieval/`: exact/fuzzy/FTS/entity resolution.
- `tools/`: ToolRegistry, ToolExecutor, safe tools.
- `models/` or runtime infrastructure: provider/model adapters and framework integration.
- `prompts/`: versioned prompts.
- `evals/`: deterministic model evaluation logic/data.

Dependency direction points inward. Domain/storage never imports agent/provider framework code.

## Development workflow for GigaCode

Before editing:

1. Inspect relevant code/tests/docs.
2. Read current roadmap/task state.
3. Identify architecture boundary and exact task scope.
4. For multi-file/architecture/storage/migration work use Plan Mode.
5. Do not invent missing APIs when repository evidence can answer the question.

While editing:

1. Make the smallest coherent change.
2. Reuse accepted abstractions.
3. Add dependencies only when necessary/justified.
4. Keep public contracts typed and explicit.
5. Add/update tests with production behavior changes.
6. Preserve fail-closed handling at untrusted structured boundaries.
7. Do not silently broaden task/stage scope.

## Repository-edit rule

Repository text files must be mutated through built-in GigaCode/IDE file tools.

A JSON parsing error, oversized payload, timeout or transport failure is not permission to automatically switch to shell/PowerShell/Python file generation.

Explicitly prohibited without prior user approval:

```text
python -c with open(...).write(...)
python -c with Path.write_text()/Path.open()
temporary Python/PowerShell/Bash generator/append scripts
PowerShell Set-Content/Add-Content/Out-File
shell redirection
base64/heredoc/generated-file workarounds
```

Canonical rule:

```text
.gigacode/rules/06-tool-usage.md
```

### Large-file recovery

```text
inspect current file/partial state
→ preserve correct work
→ split by logical sections
→ use small anchored IDE edits
→ re-read changed regions
→ inspect per-file diff
```

See `.gigacode/rules/07-incremental-file-editing.md` and ADR-0002.

## Adaptive quality gates

Select gates from the **actual final Git diff**, not task title.

Canonical rule:

```text
.gigacode/rules/31-adaptive-quality-gates.md
```

### Documentation-only Markdown

Required by default:

- complete diff review;
- documentation/status consistency;
- exact changed-file inventory;
- `git diff --check`;
- final Git checks.

Do not run full pytest/Ruff solely for evidence on ordinary docs-only changes unless the Markdown is machine-consumed or another concrete technical reason exists.

### Code/test/runtime/dependency changes

Run focused and broader gates appropriate to actual changed responsibilities/risks. Python changes require relevant Ruff checks. Full suite is used where task/stage risk requires it, not mechanically for every change.

For PAIM provider/runtime gates, real Ollama tests remain explicit opt-in smoke tests; default suite must not require Ollama.

Reclassify gates after all edits using final changed-file inventory.

## Maintainability

Cohesion before file size.

Pointers:

```text
.gigacode/rules/15-module-decomposition.md
.gigacode/rules/35-test-decomposition.md
.gigacode/rules/36-maintainability-ratchets.md
```

Current soft/hard guidance remains:

- production ~500 lines triggers review; new production hard max 700;
- tests ~700 lines triggers review; new test hard max 1000;
- >600 production / >850 test triggers headroom/decomposition review;
- existing oversized files are legacy exceptions and may not silently grow;
- tests are topic/capability oriented, not correction-number files;
- preserve stable facades during decomposition where practical.

## Untrusted-boundary reliability

Use `.gigacode/rules/09-untrusted-boundary-validation.md`.

Review structural equivalence classes explicitly. Do not use truthiness for provider/framework structural validation. Remember Python numeric traps such as bool-as-int, non-finite floats and conversion overflow.

Pydantic AI/provider responses remain untrusted even from localhost.

## Test harness isolation

Protected harness changes require explicit scope. Do not edit global fixtures/conftest/harness behavior merely to make a local task pass.

See `.gigacode/rules/37-test-harness-isolation.md`.

## Safety for agent actions

Never perform automatically:

- destructive Git history operations;
- deletion/rewrite of a real campaign Vault;
- secret/.env/token changes;
- unrestricted runtime filesystem/shell exposure;
- database/schema migration outside explicit task scope;
- publishing releases/artifacts;
- force-push/history rewriting;
- architecture changes merely to simplify implementation.

If an operation is destructive/irreversible/credential-related or touches real Vault data, require explicit user approval.

## Useful commands

Code-bearing tasks commonly use:

```text
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run dnd --help
```

Documentation-only tasks use documentation/diff checks plus Git finalization unless a concrete exception applies.

## Git commit and push policy

After successful completion of each task:

1. Run relevant quality gates according to final diff/risk.
2. Inspect `git status` and complete diff.
3. Exclude secrets/temp/generated/unrelated files.
4. Stage only task files.
5. Create one coherent commit (prefer Conventional Commits where appropriate).
6. Push current branch normally to `origin`.
7. Verify local `HEAD` equals upstream/remote commit.
8. Report branch, commit SHA, message and push result.

Do not ask separate confirmation for ordinary commit/push after successful required gates.

Do not automatically use:

```text
git push --force
git push --force-with-lease
git reset --hard
published-history rebase
remote branch deletion
```

If push fails due to auth/conflict/protection/remote changes, stop and report exact reason. Do not bypass safeguards.

### Single-task-commit finalization

Complete docs/status edits before task commit. Do not amend/create a second docs-only commit merely to insert the just-created task SHA into the same task documentation. Report that SHA in Final Report instead.
