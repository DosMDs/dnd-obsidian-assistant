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
- `build` (`default_agent`) is the default primary agent under adaptive task
  routing. `plan` remains an explicit read-only primary agent reserved for
  PLAN_REQUIRED work and never mutates repository state.
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

## Permission model

OpenCode agent permissions are developer-tooling policy, not application
authorization. They do not change runtime, Vault, `ToolExecutor`, domain, storage
or model permissions.

Permission actions are `allow`, `ask` and `deny`. For object-valued permissions
(`bash`, `read`, ...) rules are evaluated in declaration order and the **last
matching rule wins**. Each object therefore places its catch-all `*` first, then
the specific exceptions, with any `deny` override trailing the `allow` rules it
constrains. JSON insertion order is load-bearing: reordering keys silently
changes behavior.

The `bash` permission matches each **parsed sub-command** of a shell string.
OpenCode parses the command with tree-sitter (PowerShell for `pwsh` on Windows)
and evaluates every sub-command independently: one `deny` sub-command denies the
whole call, and a call runs without prompting only if every sub-command resolves
to `allow`. Patterns are simple globs (`*` matches zero or more characters, `?`
one); on Windows matching is case-insensitive. There is no alias or
executable-path normalization, so `git.exe status`, `Remove-Item` aliases and
`bash -c ...` payloads match only as written.

`build` uses an explicit routine-development ALLOW set over an `ask` default:
ordinary `git add`/`commit`/`push` stay automatic; state-changing operations
(`checkout`/`switch`/`restore`/`stash`/non-ff `merge`/`rebase`) remain `ask`;
force/history-rewriting forms spelled `--force`, `--force-with-lease`, `-f`,
`--mirror`, `--prune`, refspec `+`/`:` deletes, `reset --hard`, `clean`,
`filter-branch`, explicit branch/tag delete (`-d`/`-D`/`--delete`) and
recursive/forced delete are `deny`. Branch list forms are allowed only without
trailing arguments (`git branch`, `git branch -l`/`-a`/`-r`/`-v`,
`git branch --list`/`--show-current`/`--merged`/`--no-merged`); any filtered or
mutating form (including create, rename, copy and upstream) falls through to
`ask` in `build`. `plan` and the three review subagents remain read-only: they use
the same exact, argument-free `git branch` list set, and everything else is
denied by their default `deny`; their read-only `git log`/`diff`/`show` allows
carry an explicit `deny` for `--output` so those options cannot write
working-tree files (shell redirection and external diff drivers are separate,
inherent to permitting `bash`, and are not covered). A trailing wildcard was
deliberately not used on the branch allows, because a deny-by-default agent can
never be made truly read-only by adding denies to an extendable allow.

The `bash` ALLOW set intentionally excludes `cat`, `type` and `Get-Content`,
which stay `ask`.

### Permission validation

`opencode debug agent build` (and `plan`) prints the resolved agent ruleset in
evaluation order. It is a safe, non-interactive way to confirm ordering, that
`.env` read rules resolve to `ask`, and that `deny` overrides trail the `allow`
rules they constrain. `opencode debug config` validates that the config parses.

### Secrets limitation

Do not rely on shell permission globs to protect secret paths. The built-in
`read` protection (`*.env`, `*.env.*` -> `ask`, `*.env.example` -> `allow`)
applies only to the `read` tool and only for the agents that do not override it:
`build` and `plan` deliberately do not, while the three review subagents still
set an explicit `read: allow` and therefore do not inherit it. Shell commands
are matched by command text and are path-blind: `rg`,
`git show`, `git log -p`, `bash -c "..."` and similar can expose `.env`,
credential or key files regardless of `bash` patterns. The project rule "do not
read `.env`/credential files unless explicitly authorized" therefore remains a
policy, not an enforced shell boundary.

### `git fetch`

`git fetch` and its argument forms are allowed for normal synchronization;
forced refspecs (`+...`), `--force`, `-f` and `--update-head-ok` are `deny`, and
other short-option clusters containing `f` are downgraded to `ask`. Globs cannot
distinguish a remote URL (`https://...`, `git@host:...`) from an explicit
destination refspec, so an unforced destination refspec such as
`git fetch origin main:main` remains allowed: it can only fast-forward local refs
and is recoverable, the same class as the allowed `git pull --ff-only`.

### Residual limitations

The matcher is best-effort and fail-safe by default; it is not a security
boundary:

- `deny` patterns cannot see through wrappers or aliases. `sudo rm -rf`,
  `/bin/rm -rf`, the PowerShell `ri`/`rd` aliases and `bash -c "..."` payloads do
  not match the prefix-anchored rules and fall back to `ask` (or, for the
  read-only agents whose default is `deny`, to `deny`). Combining CMD flags
  (`del */s*`, `erase */s*`, `rd */s*`, `rmdir */s*`) is covered, but arbitrary
  wrappers are not.
- Glob patterns cannot distinguish a short-option cluster containing `f` from a
  long option, so bundled force flags are handled heuristically: `git push` /
  `git fetch` commands matching `*-?*f*` are downgraded to `ask` (e.g.
  `git push -qf`, `git push -nqf`), at the cost of also asking for
  `git push --follow-tags` and `git fetch --filter=...`. Plain `-f` is still
  caught by the explicit `deny` rules. A short cluster where the only `f` is the
  first flag, e.g. `-fq`, is caught by `git push -f*`.
- `git commit --amend` is allowed and `git rebase` is `ask`; both rewrite local
  history, which only matters once published. Publishing a rewrite is caught by
  the push `deny` rules.
- There is no path-aware shell protection (see Secrets limitation).

## Tooling roles and evidence

```text
LSP (agent tool)  -> semantic inspection / navigation
Pyright command   -> canonical mandatory type gate
pytest            -> executable behavioral correctness
Ruff              -> lint / format
contract/eval tests -> architecture/runtime evidence
```

- The agent LSP tool is read-only **semantic inspection**; it is not itself a
  gate and a successful query proves nothing about runtime correctness. A
  successful LSP query is not equivalent to `uv run pyright`.
- `uv run pyright` is the canonical **repository-wide type gate** for Python
  code and test changes; it must complete with 0 errors. Configuration lives in
  `pyrightconfig.json`.
- `uv run pytest` provides behavioral evidence; `uv run ruff check` /
  `uv run ruff format --check` provide lint/format evidence.
- Pytest green does not override Pyright failure; Pyright green does not replace
  pytest or Ruff. Relevant type errors cannot be ignored merely because pytest
  is green; pytest proves behavior, not type correctness.
- Repository-wide Pyright is a mandatory gate (finalized by PYR-01E); it is not
  informational-only and its diagnostics are release blockers for Python changes.
