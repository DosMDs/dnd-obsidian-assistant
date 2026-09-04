# ADR-0001: VS Code + GigaCode development workflow

- **Status:** Accepted
- **Date:** 2026-08-27

## Context

D&D Session Assistant is developed primarily on Windows in VS Code and must also run natively on macOS.

A coding assistant is used during implementation. The project needs a clear distinction between:

1. the **development assistant** that edits source code; and
2. the **application LLM runtime** accessed through `ModelGateway` / Ollama.

Without this distinction, development tooling could accidentally be treated as part of runtime architecture or as a permitted path for campaign-data mutation.

The workflow also needs verification proportional to the actual change. Running the complete Python test/lint stack for a Markdown-only documentation edit adds cost and noise without validating the modified surface. Conversely, a task that unexpectedly changes code or machine-consumed files must not keep a documentation-only exemption.

## Decision

### IDE and supported development platforms

- VS Code is the primary IDE.
- Windows is the primary development machine.
- macOS is a first-class supported runtime/development target.
- WSL is not the canonical development environment.
- Cross-platform behavior must be implemented with portable Python APIs.

### Python toolchain

- Python 3.12+.
- `uv` manages project dependencies and Python environments.
- Ruff is the project linter/formatter and is run from the project environment.
- pytest is the default software test runner.

### Coding assistant

GigaCode for VS Code is the selected coding assistant.

Project-level behavior is stored in version control through:

```text
GIGACODE.md
.gigacode/rules/
.gigacode/skills/
```

VS Code-specific GigaCode/MCP configuration may live under:

```text
.gigacode_vsc/
```

### Architectural classification

GigaCode is **development tooling only**.

It is not:

- part of the D&D Session Assistant runtime;
- an implementation of `ModelGateway`;
- an application dependency;
- campaign memory;
- a canonical data source.

The runtime rule “LLM never gets arbitrary filesystem/shell access to the Vault” applies to the application's model architecture. GigaCode may edit the **source repository** as a development agent, but a real campaign Vault must not be exposed to it as an unrestricted writable workspace or through unrestricted filesystem/shell MCP.

### Agent operation policy

Default project policy:

- Ask mode for investigation;
- Plan mode before multi-file, architectural, migration, storage or risky changes;
- Agent mode after the plan is acceptable;
- checkpoints enabled;
- broad auto-approval disabled by default;
- no unrestricted filesystem/shell MCP;
- destructive Git, secrets, real Vault mutations, publishing and irreversible migrations require explicit user approval.

### Adaptive quality gates

Verification is selected from the **actual final Git diff**.

For ordinary documentation-only tasks where every changed file is Markdown documentation or agent/development instruction Markdown and no file is machine-consumed runtime/test/build data:

Required by default:

- full final-diff review;
- documentation/status consistency checks relevant to the task;
- exact changed-file inventory verification;
- `git diff --check`;
- normal Git scope/finalization checks.

Not required by default:

- full `uv run pytest`;
- targeted/contract pytest suites;
- `uv run ruff check .`;
- `uv run ruff format --check .`.

A Markdown file does not receive this exemption when it is a runtime/test fixture, golden/generated input, executable specification, schema-like machine-consumed artifact, or when a relevant project validator explicitly applies.

If a code/test/runtime/config/machine-consumed file appears during a task that started as documentation-only, the task must be reclassified from the final diff. The unintended file must either be restored or the corresponding quality gates must be run.

The canonical detailed rule is:

```text
.gigacode/rules/31-adaptive-quality-gates.md
```

Final Reports record the selected gate class, commands actually run, and gates intentionally skipped under this policy.

### Development status

The canonical current development state is:

```text
DEVELOPMENT_STATUS.md
```

Git commits record concrete completed changes.

ADRs record significant decisions.

Git tags record completed milestones/releases.

GigaCode must read `DEVELOPMENT_STATUS.md` before planning implementation and must not automatically advance the project to the next roadmap stage.

## Consequences

### Positive

- consistent agent behavior across sessions;
- fewer architecture boundary violations;
- development state survives chat history;
- Windows/macOS portability becomes an explicit quality requirement;
- GigaCode remains replaceable and does not leak into runtime code;
- documentation-only work avoids unnecessary full Python-suite execution;
- code-bearing scope expansion automatically restores the appropriate stronger verification.

### Trade-offs

- project rules/skills require maintenance;
- agent changes require explicit review discipline;
- stage progress requires updating `DEVELOPMENT_STATUS.md`;
- the agent must correctly classify the final diff before finalization instead of relying on a fixed command checklist.

## Supersedes

Nothing.
