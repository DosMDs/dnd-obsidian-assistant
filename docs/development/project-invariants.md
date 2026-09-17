# Project invariants

Durable application-facing invariants. This is not a workflow procedure; read it
when a task touches architecture, product scope, the Vault, platform behavior or
the user interface. Workflow/gate discipline lives in
[task-workflow.md](task-workflow.md) and
[quality-and-evidence.md](quality-and-evidence.md).

## 1. Architecture boundaries

- The Obsidian Vault is the only canonical campaign Source of Truth.
- Python is the trusted layer for domain logic, validation, filesystem
  operations, calendar, retrieval and tool execution.
- LLMs are replaceable interpretation/reasoning components, not storage,
  trusted parsers or filesystem operators.
- Domain/storage code must not import or depend on Ollama, Pydantic AI or any
  concrete model/provider.
- Derived stores such as SQLite FTS, caches and embeddings must always be
  rebuildable from canonical Vault/raw data.
- Prefer the smallest implementation that preserves these boundaries.
- Presentation (Typer CLI, Textual TUI) is a replaceable mechanism layered
  above application/composition. Domain, storage, tools, models and application
  must never depend on Textual or on any presentation host. UI
  enabled/visible/focus state is presentation guidance only and is never an
  authorization boundary; every write-capable UI action still flows through
  `ToolExecutor` / ChangeSet / revision / permission / audit / `VaultRepository`.
- The always-on trust boundary (ToolExecutor authority, no arbitrary Vault
  filesystem/shell access) is defined in `AGENTS.md`.

## 2. Python and package boundaries

- Target Python 3.12+.
- Use explicit typing for public APIs and Pydantic schemas for external or
  model-facing structured data.
- Keep Typer/Rich concerns in `cli/`; do not put business logic in CLI
  callbacks.
- Keep Textual concerns in the presentation/composition host; do not put
  business or write policy in widgets, key handlers, command-palette handlers or
  ephemeral UI state. Typer and Textual must invoke the same shared
  application/composition capabilities. Important operations use stable semantic
  command IDs through one centralized dispatch surface (bindings, palette,
  context actions, footer hints and help must not reimplement a command
  independently).
- Keep orchestration in `application/`, deterministic business rules in
  `domain/`, Markdown/YAML persistence, audit and locking in `storage/`, and
  Ollama-specific behavior behind `ModelGateway` providers in `models/`.
- Avoid circular dependencies and provider-specific types leaking into
  domain/application contracts.
- Do not add abstractions that are not required by the current roadmap stage.
- Do not add dependencies casually.

## 3. Russian-only user interface

- The user-facing application interface is Russian-only for the MVP.
- All application-owned CLI/TUI help text, prompts, confirmations, status
  messages, warnings and user-facing error messages must be written in Russian.
- Do not add a language selector, locale setting, translation catalog or other
  i18n framework unless the user explicitly expands product scope later.
- Campaign-facing text must be stored and processed as UTF-8 and must fully
  support Cyrillic. Do not impose ASCII-only validation on human-readable
  campaign content or stable identifiers unless a separate canonical contract
  requires it.
- Internal Python identifiers, module/file names, enum member names and
  machine-readable enum values may remain English. Literal commands, flags,
  technical identifiers, provider/product names and standards may remain in
  canonical technical form.
- Runtime LLM output intended for the user must be requested in Russian unless
  a later explicit requirement overrides this rule.

## 4. MVP scope guard

MVP includes: Python 3.12+/uv; Typer + Rich CLI; NPC, location, quest and item
entities; sessions and raw JSONL logging; safe Vault read/write; exact/fuzzy/
SQLite FTS search; generic deterministic calendar; Ollama ModelGateway; a fast
agent with a limited Tool Registry; post-session processing; Summary and Recap;
ChangeSet review/apply; existing-campaign bootstrap; pytest and basic model
evals.

A Textual TUI is accepted as a post-Stage-12 presentation track (see
`docs/adr/0008-textual-tui-presentation-architecture.md`); it is
presentation-only and does not change MVP domain/scope, and Typer remains
supported for scripting, administration, bootstrap, recovery, diagnostics and
evals.

Do not add before demonstrated need:

```text
vector DB or embeddings
LoRA/fine-tuning infrastructure
voice/audio pipeline
web/mobile UI
graph DB
multi-user server
DM mode
combat/rules engine
threat clocks
complex RAG framework
```

## 5. Windows and macOS portability

- Treat Windows and macOS as supported native environments.
- Use `pathlib.Path` instead of manual path concatenation; never commit
  absolute developer-machine paths.
- Do not require WSL, Bash, GNU utilities or Make.
- Prefer `uv run ...` commands that work identically on both platforms.
- Avoid `shell=True`; use UTF-8 explicitly for project-controlled text files.
- Avoid assumptions about path separators, executable suffixes, case
  sensitivity and file locking semantics. When filesystem behavior matters, add
  a test rather than relying on one OS.

## 6. Storage and data integrity

For any code that can modify campaign data:

- Stable entity IDs must not depend on filenames.
- Preserve user-authored Markdown body when changing YAML/frontmatter.
- Normalize and validate paths; reject traversal outside the allowed Vault
  root.
- Use atomic write semantics: temporary file, validation, then atomic
  replacement.
- Use optimistic concurrency through entity/session revisions where required.
- Record provenance for automatically extracted knowledge.
- Respect visibility and knowledge status in repository/query paths.
- Record application writes in audit logs.
- Raw session JSONL is append-only; after session end it is immutable.
- Never make post-session model output write directly to canonical entity
  files; use ChangeSet.
- Never silently resolve ambiguous entities for write operations.
