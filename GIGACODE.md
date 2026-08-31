# D&D Session Assistant — GigaCode Project Instructions

## Project purpose

D&D Session Assistant is a local, offline-first Python application for long-term D&D/RPG campaign memory.

The durable campaign state lives in an Obsidian Vault. Python owns trusted domain logic, validation, filesystem operations, search, calendar calculations and tool execution. Local LLMs accessed through Ollama are replaceable operators used for language understanding, tool selection, extraction, summaries and recaps.

## Non-negotiable architecture

1. Obsidian Vault is the only canonical Source of Truth.
2. LLM output is never trusted until validated by Python.
3. LLM code must never get arbitrary filesystem or shell access to the Vault.
4. Every Vault write must flow through ToolExecutor/domain services/VaultRepository.
5. Domain and storage layers must not depend on Ollama or any concrete model.
6. SQLite, FTS indexes, cache and embeddings are derived data and must be rebuildable from the Vault.
7. Game-time arithmetic is deterministic Python logic in CalendarService using canonical `world_tick`.
8. Raw session logs are append-only and immutable after session end.
9. Model-generated post-session changes use `ChangeSet -> validate -> review -> apply`.
10. Ambiguous entity resolution must prefer clarification over speculative writes.
11. Stable IDs, revisions, provenance, visibility, atomic writes and audit logging are core requirements.
12. Do not introduce vector DB, embeddings, LoRA, voice, Web UI, graph DB, combat automation or complex RAG before MVP need is demonstrated.
13. The application user interface is Russian-only for the MVP. All application-owned CLI/TUI help text, prompts, confirmations, status messages, warnings and user-facing error messages must be in Russian.
14. Do not introduce i18n, locale selection, translation catalogs or additional interface languages unless the user explicitly expands the product scope.
15. Campaign-facing text must use UTF-8 and fully support Cyrillic. Internal Python identifiers, module/file names, enum member names and serialized machine-readable enum values may remain English.
16. Runtime LLM output intended for the user must be requested in Russian unless a later explicit requirement overrides this rule.

## Dependency order

Develop in this order unless the user explicitly changes the roadmap:

`Environment -> Project contracts -> Domain schemas -> VaultRepository -> Calendar -> Retrieval/EntityResolver -> Session runtime -> Tool layer -> ModelGateway/Ollama -> Fast Agent -> ChangeSet -> Post-session processing -> Campaign State -> Bootstrap -> Evals/hardening`

Tests are implemented together with each stage.

## Development status and documentation

### Current status

Before planning or editing code, read:

```text
DEVELOPMENT_STATUS.md
```

It is the canonical source for the **current roadmap stage and task progress**.

Do not duplicate the current stage in `GIGACODE.md`. Always read `DEVELOPMENT_STATUS.md`.

### Documentation responsibility split

- `DEVELOPMENT_STATUS.md` = canonical **current** roadmap/status state.
- `docs/stages/NN_*.md` = canonical detailed plan/history/evidence for each stage.

Rules:

1. Do not append full Final Reports to `DEVELOPMENT_STATUS.md`.
2. Do not append detailed correction narratives there.
3. Task completion: update checkbox/current state in `DEVELOPMENT_STATUS.md`;
   record detailed completion evidence in the relevant stage document.
4. Correction task: keep current task state in status; append correction
   record to the stage document.
5. Stage final review: mark final state/date in status; write detailed
   historical review into the stage document.
6. Do not duplicate the same detailed report in both files.

### Stage discipline

- Work primarily inside the current stage.
- Do not pull later-stage implementation forward merely because it is convenient.
- Do not mark a task/stage `DONE` because code was generated.
- Completion requires implementation, required tests, successful relevant quality gates, and final diff review.
- Do not advance the roadmap stage automatically.
- If the user explicitly changes stage or scope, update `DEVELOPMENT_STATUS.md` as part of that change.
- Significant architecture/development-workflow decisions belong in `docs/adr/`.

### Development assistant vs runtime LLM

GigaCode is a **development coding assistant**, not part of the application runtime.

It may edit the source repository in the approved development workflow. It must not be treated as:
- a `ModelGateway`;
- campaign memory;
- a canonical data source;
- a permitted back door for real Vault mutation.

Do not expose a real campaign Vault to unrestricted agent filesystem/shell tooling.

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
- respx
- Ruff
- Ollama as the first ModelGateway provider

## Cross-platform requirements

The application must run natively on Windows and macOS.

- Use `pathlib.Path`.
- Use UTF-8 explicitly for project-controlled text files.
- Do not hard-code `C:\\...`, `/Users/...`, drive letters or shell-specific paths.
- Do not require Bash, Make, WSL or GNU-only utilities.
- Prefer Python implementations and `uv run ...` commands.
- Avoid `shell=True` and platform-specific shell syntax in application code.
- Tests that touch files must use temporary directories.
- Filesystem semantics that differ between Windows and macOS must be covered by tests when relevant.

## Package boundaries

Expected top-level package layout:

- `cli/`: Typer commands and presentation only.
- `application/`: orchestration/use cases.
- `domain/`: pure domain models and deterministic business rules.
- `storage/`: Vault Markdown/YAML persistence, atomic writes, audit, locks.
- `retrieval/`: exact/fuzzy/FTS search and entity resolution.
- `tools/`: ToolRegistry, ToolExecutor and safe read/write/calendar tools.
- `models/`: ModelGateway contracts and provider adapters.
- `prompts/`: versioned model prompts.
- `evals/`: deterministic model evaluation logic/data.

Dependency direction must point inward toward domain contracts, never from domain/storage to model providers.

## Development workflow for GigaCode

Before editing:
1. Inspect the relevant existing code and tests.
2. Identify the current roadmap stage and architectural boundary.
3. For multi-file or architectural changes, use Plan Mode and propose affected files, tests and risks.
4. Do not invent missing APIs if existing code can answer the question.

While editing:
1. Make the smallest coherent change.
2. Reuse existing abstractions.
3. Do not add a dependency unless it is necessary and justified.
4. Keep public contracts typed and explicit.
5. Add/update tests in the same change.
6. Use built-in GigaCode/IDE file-edit tools for repository text files. A JSON parsing error, oversized payload, timeout, or similar edit/write-tool failure is not permission to switch automatically to shell/PowerShell/Python file generation.
7. After an edit/write-tool failure, inspect the working tree first, preserve already-correct partial work, and retry with smaller atomic create/edit/patch operations. For oversized tests, reduce needless duplication with parametrization/helpers without weakening required coverage.

### Repository-edit rule

Repository text files must be mutated through built-in GigaCode/IDE file tools.

Shell-executed Python is still shell-based mutation. The following are explicitly prohibited without prior user approval:

```text
python -c "open(..., 'w').write(...)"
python -c "open(..., 'a').write(...)"
python -c "Path(...).write_text(...)"
python -c "Path(...).open(...).write(...)"
temporary Python/PowerShell/Bash generator or append scripts
PowerShell file-write commands (Set-Content, Add-Content, Out-File)
shell redirection (> / >>)
base64/heredoc/generated-file workarounds
```

The detailed always-on rule defining allowed and prohibited writing mechanisms is:

```text
.gigacode/rules/06-tool-usage.md
```

### Large-file incremental editing

When a built-in file edit/write operation fails or a file is too large for one reliable operation, the mandatory procedure is:

```text
inspect current file/partial state
→ preserve correct work
→ split by logical sections
→ use small anchored IDE edits
→ re-read each substantial changed region
→ inspect per-file diff
```

For a large new test/source file:

```text
imports/helpers/skeleton
→ one logical section at a time
→ parametrization/helpers where appropriate
→ focused validation
```

A failed large IDE payload does NOT authorize changing the writing mechanism.

The detailed always-on rule for the incremental-edit algorithm is:

```text
.gigacode/rules/07-incremental-file-editing.md
```

### File-edit recovery policy

When a built-in file edit/write operation fails for a technical reason such as JSON parsing, payload size, timeout, or transport limits:

1. Treat it as a tooling failure, not an implementation failure.
2. Inspect `git status`/`git diff` or the relevant file before retrying so correct partial work is not overwritten.
3. Retry using smaller repository-edit operations: create a small initial file, then add or patch logical sections incrementally.
4. Prefer compact parametrized tests/helpers over duplicated test bodies when file size itself contributes to the problem, while preserving the task's acceptance criteria and regression coverage.
5. Do not use Bash, PowerShell, Python one-off scripts, base64, shell redirection, or equivalent source-file generation as an automatic fallback.
6. Shell-based file mutation is allowed only when built-in file tools are genuinely unavailable or objectively cannot support the required operation independently of payload size. Report the reason to the user and obtain explicit approval before using that fallback.
7. After recovery, inspect the final diff for truncation, partial writes, duplicated sections, or unrelated changes.

The rationale for this policy is recorded in `docs/adr/0002-agent-file-edit-recovery-policy.md`.

### Prompt-level repository-edit constraint

Every implementation, correction, or review-fix task prompt prepared for GigaCode is expected to repeat a short mandatory repository-edit constraint directly in the task, even though the same policy exists in the always-on repository rules above.

The canonical prompt-level block is:

```text
## Mandatory repository-edit constraint

All repository text-file mutations must use built-in GigaCode/IDE file tools.

Explicitly prohibited without prior user approval:
- python -c with open(...).write(...)
- python -c with Path.write_text()/Path.open()
- temporary Python/PowerShell/Bash generator or append scripts
- PowerShell file-write commands
- shell redirection
- base64/heredoc/generated-file workarounds

If a file-tool operation is too large:
inspect current partial state
→ preserve correct edits
→ split by logical section
→ apply smaller anchored IDE edits
→ re-read changed region
→ inspect per-file diff.

Do not switch writing mechanisms because a payload is large.
```

The repository rules remain mandatory even if a particular task prompt accidentally omits this repeated block. This is defense in depth, not an alternative policy.

Before considering a task complete:
1. Run targeted tests first.
2. Run `uv run pytest` when feasible.
3. Run `uv run ruff check .`.
4. Run `uv run ruff format --check .`.
5. Review the diff for boundary violations, accidental generated files, secrets and unrelated edits.
6. State what was changed, tests executed and any remaining risk.

## Safety for agent actions

Never perform automatically:
- destructive Git history operations;
- deleting or rewriting a real campaign Vault;
- modifying `.env`, credentials, tokens or secret files;
- adding shell/filesystem MCP servers with unrestricted write access;
- database/schema migrations without explicit user request;
- publishing releases or uploading artifacts;
- force-pushing or rewriting published Git history;
- changing architecture merely to make implementation easier.

If an operation is destructive, irreversible, credential-related or touches a real Vault, stop and require explicit user approval.

## Useful commands

```text
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run dnd --help
```

## Git commit and push policy

После успешного завершения каждой задачи агент обязан самостоятельно:

1. Запустить требуемые quality gates.
2. Проверить `git status` и `git diff`.
3. Убедиться, что в commit не попали:
   - секреты;
   - `.env`;
   - временные файлы;
   - случайные/generated файлы;
   - изменения вне текущей задачи.
4. Выполнить `git add` только относящихся к задаче файлов.
5. Создать commit.
6. Сразу выполнить push текущей ветки в настроенный `origin`.

Не спрашивать отдельного подтверждения для обычного commit/push после успешно завершённой задачи.

Запрещено автоматически:

- `git push --force`;
- `git push --force-with-lease`;
- переписывать историю;
- `git reset --hard`;
- rebase опубликованной истории;
- удалять remote branches;
- пушить при проваленных тестах или quality gates.

Если push не удался из-за authentication, conflicts, branch protection или remote changes — остановиться и сообщить пользователю, не обходить защиту автоматически.

Commit должен содержать только изменения текущей задачи.

Prefer these commands over platform-specific wrappers.
