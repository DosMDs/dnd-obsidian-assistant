# ADR-0011: Machine-local configuration boundary (dotenv + `models.toml`)

- **Status:** Accepted
- **Date:** 2026-10-01
- **Task:** `CFG-00` (dotenv default discovery corrected by `CFG-01`; Vault-path default added by `CFG-02`)

This ADR records the accepted machine-local configuration architecture. It is the
durable decision/official context for the `DND_MODEL_CONFIG_PATH` / dotenv
boundary introduced by `CFG-00`; current roadmap state remains authoritative in
`DEVELOPMENT_STATUS.md`.

## Context

Before `CFG-00`, machine configuration was split and partly implicit:

- the model-profile TOML path was supplied only through an explicit CLI
  `--config` option, required on most commands and re-declared by each command;
- provider credentials were read directly from the process environment
  (`DEEPSEEK_API_KEY`) by a provider-adjacent module (`models/credentials.py`);
- there was no dotenv support, so credentials had to be exported per shell;
- there was no single typed machine-settings object and no canonical
  machine-local configuration location.

The Obsidian Vault is the only campaign Source of Truth and must stay separate
from machine configuration. Secrets must never enter the Vault, reports, traces,
audit records, diagnostics, TUI output or error text.

## Decision

Introduce one typed machine-local settings boundary in
`src/dnd_assistant/config/` built on `pydantic-settings.BaseSettings`
(`MachineSettings`), plus a deterministic dotenv discovery/bootstrap selector.

### Contract

```text
MachineSettings
    model_config_path: Path | None      # DND_MODEL_CONFIG_PATH (absolute)
    vault_path:        Path | None      # DND_VAULT_PATH (absolute)
    deepseek_api_key:  SecretStr | None # DEEPSEEK_API_KEY (provider-standard)
```

`MachineSettings` owns only machine-setting parsing/typing and the absolute-path
semantics of `model_config_path` and `vault_path`. It does **not** validate or
parse the model-profile TOML file: `models/profiles.py::load_model_profiles`
remains the sole owner of file existence/read/TOML/profile validation errors.
It likewise does **not** validate the Vault: `vault_path` is only a machine-local
**pointer** to the campaign Vault, and Vault existence, directory layout,
campaign structure and storage validity remain owned by the existing
Vault/application/storage boundaries. The provider → external credential name
mapping and the fail-closed credential check live here
(`require_provider_api_key`, `provider_credential_env_var`).

### Vault path

`DND_VAULT_PATH` provides the default Vault root for every Vault-using CLI/TUI
command (`--vault`). It is a pointer only: campaign data never enters the
dotenv. The presentation-layer helper `cli/vault_path.py::resolve_vault_root`
merges the explicit option with the setting and applies the same
directory-existence check the CLI previously relied on for explicit
(Typer-validated) paths. The setting is consulted lazily, so an explicit
`--vault` never depends on dotenv/project-root discovery. Invalidation of an
env/dotenv-provided path does not bypass validation: a nonexistent or non-
directory path fails with the existing project error.

### Source precedence

```text
explicit construction argument / explicit --vault / explicit --config
  > real process environment
  > selected machine-local dotenv file
  > safe defaults
```

Pydantic-Settings supplies environment > dotenv > default natively; the entry
points merge the explicit `--vault`/`--config` above the settings value. An
explicit `None` is never injected into the settings constructor, so it cannot
shadow an environment value.

### Dotenv discovery

- `DND_ENV_FILE` is a **bootstrap selector** and has highest discovery
  precedence: read only from the real process environment, must be an absolute
  path when provided, and cannot redirect itself (it is not a settings field and
  is rejected as an unknown key). When set, it is the selected dotenv regardless
  of the invocation directory.
- Default path (when `DND_ENV_FILE` is unset): the `.env` at the nearest
  enclosing **D&D Assistant project root** — the first directory at or above the
  current working directory whose `pyproject.toml` parses and declares
  `[project].name = "dnd-assistant"`.
  - Running from the repository root or from any nested subdirectory selects the
    same `<project_root>/.env`.
  - An installed invocation outside a project checkout has no default dotenv;
    it must set `DND_ENV_FILE` to load a dotenv.
  - If no qualifying project root is found, discovery fails with a deterministic
    project `ValidationError` that points at `DND_ENV_FILE`.
- Resolution never falls back to the installed package location, the user home
  directory, a `platformdirs` user-config directory, or an unrelated parent
  `.env`. Malformed, unreadable or non-matching `pyproject.toml` markers are
  skipped rather than accepted.

### Dedicated-dotenv strictness

The dedicated dotenv uses `extra="forbid"` with `hide_input_in_errors=True`:

- an unknown/typo dedicated-dotenv key fails fast;
- the (possibly secret) unknown value is never echoed in the error;
- unrelated process-environment variables are never rejected (only declared
  fields are read from the environment).

### Secrets policy

- `deepseek_api_key` is a `pydantic.SecretStr`; repr/str are redacted and error
  text never contains the value.
- Missing/empty/whitespace credentials fail closed as `CredentialError` naming
  `DEEPSEEK_API_KEY`, at the AGENT model-construction seam
  (`composition/agent_model._build_agent_model`).
- Local Ollama-only usage never requires a DeepSeek credential.
- Secrets never enter `models.toml`, the Vault, reports, traces, audit records,
  diagnostics or the TUI.
- No import-time mutation of `os.environ`; the dotenv is read into settings
  sources, not the process environment.

### Dependencies

- **`pydantic-settings`** (with `python-dotenv`) is adopted for typed parsing,
  `SecretStr` redaction, explicit source precedence, case-insensitivity,
  isolated test injection (`_env_file`) and no `os.environ` mutation.
- Project-root discovery for the default dotenv uses the standard-library
  `tomllib` only; it introduces **no additional dependency**. `platformdirs` is
  no longer a direct project dependency (it remains transitively required by
  `Textual`).

### Ownership and dependency direction

`config/` depends only on the standard library, `pydantic`, `pydantic-settings`
and neutral `errors.py`. Domain and storage never import it.
`models/` providers remain credential-source-neutral: the DeepSeek factory
receives an explicit secret/provider and never reads the environment.
Composition resolves machine configuration at the composition boundary and
passes ordinary typed values (`Path`, `SecretStr`) inward. Presentation (Typer
CLI, Textual TUI) builds the settings object once per invocation.

### Model profile configuration is unchanged

Structured, non-secret model profiles remain in `models.toml` (`[profiles.*]`).
The dotenv does not become a second serialization format for model profiles.

## Consequences

Positive:

- one typed, testable machine-settings boundary;
- credentials, the model-config path and the Vault path can be configured once
  per machine;
- `--config` and `--vault` remain supported and keep highest precedence;
- secrets are typed, redacted and kept out of campaign data and evidence;
- deterministic project-root configuration location derived from the invocation
  context (repository root or any nested directory).

Costs/risks:

- new direct dependency (`pydantic-settings`);
- the dedicated dotenv is strict, so unknown keys fail fast (intended);
- the default dotenv requires an enclosing `dnd-assistant` project; an installed
  invocation outside a checkout must set `DND_ENV_FILE`;
- machine configuration can affect command behavior, so config tests use
  explicit isolated dotenv sources rather than the developer's real file.

### Model-profile defaults are deferred

`DND_MODEL_PROFILE` (and role-specific variants) are deliberately **not**
machine defaults. Profile selection is role-specific (`AGENT`, `POST_SESSION`,
`BOOTSTRAP`) and current consumers reject a profile whose role does not match
the command, so a single generic key is not semantically valid across roles.
This is deferred to a separate task; `--profile` keeps its current
required/default behavior.

## Compatibility

- `--config` remains on every command and keeps highest precedence; it becomes
  optional on `ask`/`tui`/`session process`/`bootstrap map`/`bootstrap finalize`.
- `--vault` remains available on every Vault-using command and keeps highest
  precedence; it becomes optional and falls back to `DND_VAULT_PATH`. An
  explicit invalid `--vault` keeps its Typer usage error (exit 2); an
  env/dotenv-provided invalid path fails with one deterministic project error
  (exit 1).
- When neither `--vault`/`--config` nor a machine-local path resolves, the
  command fails with one deterministic project error (not a Typer
  missing-option crash).
- `DEEPSEEK_API_KEY` keeps its external name and fail-closed semantics.
- Safety/behavioral invocation options (`--allow-write`, `--acknowledge-unresolved`,
  `--reviewer`, `--runtime`, `--overwrite`, TUI write toggles, apply/approve/reject
  decisions, session/entity/operation IDs) are never machine defaults.
- Historical stage/migration evidence and ADR-0010 are not rewritten.

## References

- `src/dnd_assistant/config/settings.py`
- `src/dnd_assistant/cli/vault_path.py`
- `src/dnd_assistant/models/profiles.py`
- `src/dnd_assistant/models/pydantic_ai_deepseek.py`
- `src/dnd_assistant/composition/agent_model.py`
- `src/dnd_assistant/cli/ask.py`
- `docs/adr/0010-remote-deepseek-provider-architecture.md`
- `.env.example`
