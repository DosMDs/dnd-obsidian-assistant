# OpenCode developer setup

Developer-tooling setup for OpenCode. This does not change application or runtime
behavior, and LSP is **not** a quality gate (see below).

## Qualified tooling baseline

```text
OpenCode 1.18.30 : currently qualified repository tooling baseline
```

OpenCode **1.18.30** is the currently qualified repository tooling baseline. The
repository's current LSP workflow depends on its narrow experimental LSP tool
behavior, so the baseline is pinned for reproducibility.

- OpenCode upgrades require **explicit qualification**, not incidental upgrade.
- OpenCode V2 is **not** currently qualified for this repository and must not be
  adopted until the repository workflow is revalidated, at minimum:
  - config compatibility;
  - PLAN read-only behavior;
  - BUILD permissions;
  - reviewer subagents;
  - skill discovery;
  - LSP / code-intelligence behavior;
  - DeepSeek integration;
  - Windows/macOS workflow.
- Developer-tooling tasks must capture the literal `opencode --version` in their
  baseline evidence:

  ```text
  opencode --version
  ```

- `deepseek/deepseek-flash` remains the canonical development model alias.
- The current reasoning effort remains `low`. This setup does not change it, and
  reasoning effort must not be raised preemptively without project-local evidence
  of benefit.

## Python language server (Pyright)

`pyright` is a reproducible project development dependency
(`pyproject.toml` `[dependency-groups].dev`, locked in `uv.lock`). It is not an
application/runtime dependency.

```text
uv run pyright --version
```

OpenCode's built-in `pyright` LSP server handles `.py` / `.pyi` when the
`pyright` dependency is present. Project config enables built-in LSP servers:

```json
"lsp": true
```

## Experimental LSP agent tool

OpenCode 1.18.30 exposes the agent LSP tool only under a narrow experimental
flag. Set it in the developer environment before starting OpenCode:

PowerShell (Windows):

```powershell
$env:OPENCODE_EXPERIMENTAL_LSP_TOOL = "true"
opencode
```

macOS / Linux (bash, zsh):

```bash
export OPENCODE_EXPERIMENTAL_LSP_TOOL=true
opencode
```

Do **not** set the umbrella `OPENCODE_EXPERIMENTAL=true`; the narrow flag is
sufficient. The tool is read-only semantic code intelligence and is allowed for
`plan`, `build` and the three review agents.

Supported operations: `goToDefinition`, `findReferences`, `hover`,
`documentSymbol`, `workspaceSymbol`, `goToImplementation`,
`prepareCallHierarchy`, `incomingCalls`, `outgoingCalls`.

## LSP is not a gate

```text
LSP    -> navigation / semantic code intelligence
Ruff   -> lint / formatting checks
pytest -> executable behavioral correctness
contract/eval tests -> architecture/runtime evidence
```

A successful LSP query does not prove runtime correctness, and a Pyright
diagnostic is not a release blocker unless a separate project decision says so.
