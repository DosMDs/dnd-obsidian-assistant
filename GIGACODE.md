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

## Current development status

Before planning or editing code, read:

```text
DEVELOPMENT_STATUS.md
```

It is the canonical source for the **current roadmap stage and task progress**.

Current stage at the time these instructions were updated:

```text
Stage 2 — Domain schemas
```

Do not assume this line is newer than `DEVELOPMENT_STATUS.md`; the status file always wins.

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

### File-edit recovery policy

When a built-in file edit/write operation fails for a technical reason such as JSON parsing, payload size, timeout, or transport limits:

1. Treat it as a tooling failure, not an implementation failure.
2. Inspect `git status`/`git diff` or the relevant file before retrying so correct partial work is not overwritten.
3. Retry using smaller repository-edit operations: create a small initial file, then add or patch logical sections incrementally.
4. Prefer compact parametrized tests/helpers over duplicated test bodies when file size itself contributes to the problem, while preserving the task's acceptance criteria and regression coverage.
5. Do not use Bash, PowerShell, Python one-off scripts, base64, shell redirection, or equivalent source-file generation as an automatic fallback.
6. Shell-based file mutation is allowed only when built-in file tools are genuinely unavailable or objectively cannot support the required operation independently of payload size. Report the reason to the user and obtain explicit approval before using that fallback.
7. After recovery, inspect the final diff for truncation, partial writes, duplicated sections, or unrelated changes.

The detailed always-on rule is `.gigacode/rules/06-tool-usage.md`. The rationale is recorded in `docs/adr/0002-agent-file-edit-recovery-policy.md`.

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
