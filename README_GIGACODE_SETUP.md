# GigaCode setup for D&D Session Assistant

## Repository layout

```text
GIGACODE.md
.gigacode/
  rules/
  skills/
  GIGACODE.local.md.example
.gigacode_vsc/
  gigacode.jsonc
```

## Recommended VS Code / GigaCode behavior

Use these settings through the GigaCode UI rather than hard-coding undocumented VS Code setting keys:

- Keep tool/file auto-approval disabled by default.
- Keep checkpoints enabled.
- Use Ask mode for investigation/explanation.
- Use Plan mode before multi-file, architecture, migration or risky work.
- Switch to Agent mode only after the plan is acceptable.
- Do not configure MCP servers initially.
- Never enable unrestricted filesystem/shell MCP for this repository.
- If MCP is introduced later, use explicit allow-lists and keep trust/automatic approval off.

## Rules

Project rules live in `.gigacode/rules/` and are automatically applicable by GigaCode.

The rules separate concerns so architecture, storage safety, testing, portability and MVP scope can be maintained independently.

## Skills

Skills live in `.gigacode/skills/<skill-name>/SKILL.md`.

Included:
- `implement-feature`
- `domain-model`
- `vault-repository`
- `calendar-service`
- `retrieval-entity-resolution`
- `session-runtime`
- `tool-layer`
- `model-gateway`
- `changeset`
- `testing`
- `bug-fix`
- `code-review`

Descriptions are intentionally explicit so the agent can load a skill only when the task matches.

## Git

Commit:
- `GIGACODE.md`
- `.gigacode/rules/`
- `.gigacode/skills/`
- `.gigacode/GIGACODE.local.md.example`
- `.gigacode_vsc/gigacode.jsonc`

Ignore:
```gitignore
.gigacode/GIGACODE.local.md
```

## First validation prompts

Start a fresh GigaCode chat after adding/changing rules or skills.

Ask mode:
```text
Explain the architectural dependency direction of this project and list actions that are forbidden for an LLM.
```

Expected themes:
- Vault is Source of Truth.
- Python is the trusted layer.
- Domain/storage do not depend on Ollama.
- no direct LLM filesystem writes.
- ChangeSet for model-generated post-session writes.
- world_tick arithmetic only in CalendarService.

Then:
```text
Which skill would you use to implement VaultRepository atomic writes, and what tests are required?
```

Then in Plan mode:
```text
Plan the Environment / project skeleton stage only. Do not implement Domain schemas yet.
```

The plan should remain within the current roadmap stage.

## Suggested daily workflow

1. Ask mode: investigate existing implementation.
2. Plan mode: agree on a change with affected files/tests.
3. Agent mode: implement the approved slice.
4. Run targeted tests.
5. Run `uv run pytest`.
6. Run `uv run ruff check .`.
7. Run `uv run ruff format --check .`.
8. Review diff before committing.

## Local instructions

If needed:
1. copy `.gigacode/GIGACODE.local.md.example` to `.gigacode/GIGACODE.local.md`;
2. add local-only information;
3. never commit it;
4. never store secrets in it.

## MCP policy

Initial state: no MCP.

Later MCP may be useful for read-only documentation or issue tracking, but it must not become a back door around the project's architecture. In particular, an MCP filesystem writer or shell executor must never be used as a mechanism for the application's LLM to modify an Obsidian Vault.
