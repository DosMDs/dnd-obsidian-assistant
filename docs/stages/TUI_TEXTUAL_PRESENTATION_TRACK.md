# Textual TUI Architecture Track

## Objective

Introduce a first-class interactive terminal UI built with Textual, as a
**presentation-only** front-end that shares trusted behavior with the existing
Typer CLI, without changing the Obsidian Vault Source of Truth, the
`ToolExecutor` authorization boundary, or any domain/storage/application
contract.

This document is the dependency-ordered plan, constraint record and history for
the track. Current roadmap state lives in `DEVELOPMENT_STATUS.md`; the
architecture decision lives in
`docs/adr/0008-textual-tui-presentation-architecture.md`. This document does not
duplicate mutable status.

## Architectural position

```text
Typer CLI ───────┐
                 ├──> shared composition + application-service boundary
Textual TUI ─────┘
                     ↓
     application services → ToolExecutor / ChangeSet → domain / storage / Vault
```

- Textual is presentation-only. Screens, widgets, controllers, key handlers,
  command-palette handlers and ephemeral UI state own no canonical semantics and
  no write policy.
- Typer remains the supported surface for scripting, administration, bootstrap,
  recovery, diagnostics and evals. No second custom interactive REPL is planned.
- Trusted behavior is already owned by `application/`, `domain/`, `storage/`,
  `retrieval/` and `tools/`. The track adds a shared UI-agnostic composition
  boundary above them.

## Hard constraints

```text
Obsidian Vault = only canonical campaign Source of Truth
Python         = trusted domain/application/storage logic
ToolExecutor   = trusted side-effect authorization boundary
LLM/framework  = replaceable untrusted mechanism
Textual        = replaceable presentation mechanism
```

Forbidden dependency direction:

```text
domain      -> textual   FORBIDDEN
storage     -> textual   FORBIDDEN
tools       -> textual   FORBIDDEN
models      -> textual   FORBIDDEN
application -> textual   FORBIDDEN
```

- UI `enabled` / `visible` / focus / screen state is presentation guidance only
  and is **never** authorization.
- All write-capable paths preserve `ToolExecutor`, ChangeSet review/apply,
  revision checks, permission/session checks, audit and `VaultRepository`.
- Stage-12 Campaign State semantics are unchanged. Recently touched entities are
  never reinterpreted as current location, active quests, important NPCs, party
  goals, unresolved threads or deadlines.

## Semantic command architecture

Command/hotkey architecture is a foundation requirement, not later polish.

- Important operations use stable **semantic command IDs**.
- One centralized semantic command registry/dispatch surface feeds:
  ```text
  hotkeys / key bindings
  command palette
  context actions
  footer hints
  help / discoverability
  ```
  These surfaces must not implement the same command independently.
- Conceptual per-command metadata (final field set may evolve in TUI-03):
  ```text
  id            stable semantic command ID
  title/help    Russian user-facing label + description
  scope         global | screen/context
  applicable    context predicate (screen/selection present?)
  enabled       enabled predicate (presentation guidance only)
  handler       invokes an application/composition capability
  default_keys  physical-key aliases (replaceable, never canonical)
  palette       visible in command palette yet/no
  ```
- Physical key bindings are replaceable aliases for semantic commands.
- Global commands are separated from context/screen commands.
- Ordinary bindings plus the semantic command registry and command palette are
  the required foundation. Leader/chord bindings are **optional**: only
  qualified/adopted if a concrete UX need justifies it and cross-platform
  evidence supports it.
- Every semantic command resolves to exactly one handler; exactly-once
  invocation must be provable in headless tests.

## Focus safety

Focused text/multiline input must not leak ordinary typing into single-key
global commands. This requires deterministic Textual headless evidence in a
later task; it is not deferred to polish.

## Async/worker boundary

- The trusted synchronous runtime/services are not rewritten async.
- Textual workers/async facilities host existing synchronous calls while
  preserving:
  ```text
  responsive UI
  exactly-once invocation
  no implicit side-effect retry
  explicit cancellation semantics
  usable recovery after exception
  existing ToolExecutor/runtime safety invariants
  ```
- Cancellation is a UI decision; it is never rollback or retry of a started
  write.
- The adapter lives in the presentation/composition host layer, not in
  domain/application/storage/tools.

## Testing and cross-platform evidence strategy

Deterministic headless evidence uses Textual `App.run_test()` / `Pilot`.
Screenshots are not the primary semantic-correctness strategy. The track must
eventually prove, with literal assertions/counters:

```text
semantic command -> intended action
hotkey exactly once
palette and hotkey reach the same semantic action
disabled/context-inapplicable command does not execute
focused input does not leak global single-key commands
screen transitions
resize/narrow layout remains usable
worker responsiveness
completion/error/cancel recovery
write-capable UI action reaches the existing trusted authorization path
no Textual dependency leak into trusted lower layers
```

The "no dependency leak" proof belongs in a focused new boundary test module,
because `tests/contract/test_boundaries.py` is at its 1000-line ceiling.

Real-terminal smoke matrix (manual; recorded honestly as manual):

```text
Windows Terminal — primary
macOS terminal/iTerm-class — first-class
Unicode/Cyrillic
paste/multiline
resize
```

A skipped platform is reported as a capability skip, never as verified coverage.

## Maintainability constraints

- Production modules: hard 700 physical lines; Test modules: hard 1000 physical
  lines (`tests/contract/test_maintainability.py`).
- Apply decomposition pressure before the limits.
- `tests/contract/test_boundaries.py` must not grow; add focused new TUI
  boundary tests instead.
- `cli/changeset.py` (666) and `cli/agent_runtime.py` (498) are near the soft
  review threshold; TUI-02 extraction must not grow them past the hard limit.

## Task map

```text
TUI-00  repository presentation architecture / ADR / track alignment        docs-only
TUI-01  Textual dependency qualification + minimal spike (pin only on pass)
TUI-02  smallest capability-oriented shared composition seams (UI-agnostic)
TUI-03  app shell + semantic command registry + palette + bindings + focus safety
TUI-04  primary assistant/session/Campaign-State integration (read + write paths)
TUI-05  interaction / cross-platform / error-recovery hardening + selected screens
TUI-06  full track review / status cleanup / Stage-13 handoff
```

Dependency order is `TUI-00 → TUI-01 → TUI-02 → TUI-03 → TUI-04 → TUI-05 →
TUI-06`. TUI-02 is Textual-independent and could run in parallel with TUI-01,
but sequential execution is preferred to avoid pre-committing to a pin. No task
may collapse the track.

### TUI-00 — repository presentation architecture / ADR / track alignment

Docs-only. Records the accepted direction, the presentation/application
boundary, dependency rules, semantic command/focus/async/testing constraints and
the Stage-13 gate. No dependency, production code, composition refactor or
Stage-13 work.

### TUI-01 — Textual dependency qualification + minimal spike

Qualify an **exact candidate Textual release** against at least:

```text
Python 3.12+
uv resolution + lockfile determinism
Windows primary environment (Windows Terminal)
macOS first-class environment (terminal/iTerm-class)
Unicode / Cyrillic
App startup / shutdown
reactive / widget composition
multiline input
focus behavior
resize / narrow terminal
workers / background operations
command palette
bindings
App.run_test()
Pilot
```

Also qualify Textual's **test-integration strategy**. `pytest-asyncio` or any
other new async-test dependency is **not presumed mandatory**; add one later
only if qualification demonstrates a concrete need. Pin Textual only after
qualification succeeds. No Node/Bun/TypeScript/Electron.

### TUI-02 — smallest capability-oriented shared composition seams

Extract the **smallest set of capability-oriented composition seams actually
required by both Typer and Textual** from `cli/`, and rewire Typer with no
behavior change. A monolithic composition root/facade that eagerly consolidates
all current CLI wiring is rejected. Current candidate composition sites:
`cli/agent_runtime.py`, `cli/session.py`, `cli/changeset.py`,
`cli/post_session_runtime.py`, `cli/main.py`. Textual is not required in the
core for this task.

### TUI-03 — app shell + semantic command registry + palette + bindings + focus safety

Textual app shell, centralized semantic command registry/dispatch, command
palette, bindings and headless focus-safety tests.

### TUI-04 — primary assistant / session / Campaign-State integration

Wire assistant, session and Campaign-State views. Write-capable actions only
through the existing trusted authorization path.

### TUI-05 — interaction / cross-platform / error-recovery hardening

Resize/narrow layout, Unicode/Cyrillic, paste/multiline, cancel/error recovery,
and the real-terminal smoke matrix.

### TUI-06 — full track review / status cleanup / Stage-13 handoff

Full track review, documentation/status reconciliation, independent acceptance,
and Stage-13 unblock.

## Durable record — TUI-00 (2026-09-17)

- Status: `DONE`.
- Branch: `feat/textual-tui`.
- Docs-only BUILD. Changed files:
  ```text
  DEVELOPMENT_STATUS.md
  docs/adr/0008-textual-tui-presentation-architecture.md
  docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md
  docs/stages/README.md
  docs/development/project-invariants.md
  ```
- No dependency change, no production code, no composition refactor, no Stage-13
  work.
- Stage 13/14 remain `NOT STARTED`; Stage 13 is gated on TUI-track completion
  and independent acceptance.

## Durable record — TUI-01 (2026-09-17)

- Status: `DONE`.
- Branch: `feat/textual-tui`.
- **Qualification result: `PASS`.** Exact pin: `textual==8.2.8` (latest stable,
  released 2026-06-30). No additional test-runner dependency was added.
- Changed files:
  ```text
  pyproject.toml
  uv.lock
  tests/integration/test_textual_qualification.py
  tests/contract/test_textual_boundaries.py
  docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md
  DEVELOPMENT_STATUS.md
  ```
- No production `src/dnd_assistant/tui/**`, no composition extraction, no command
  registry, no real screens, no assistant/session/Campaign-State integration, no
  Stage-13 work.

### External metadata evidence (`EXTERNALLY_VERIFIED`)

- Textual `8.2.8`, MIT license, `requires_python = "<4.0,>=3.9"`, classifiers
  Python 3.9–3.14 (incl. 3.12), Operating System macOS/Windows 10/Windows 11/
  Linux.
- Wheel `textual-8.2.8-py3-none-any.whl` (platform-independent packaging).
- Resolved runtime additions are all `py3-none-any`: `textual` 8.2.8,
  `linkify-it-py` 2.2.0, `mdit-py-plugins` 0.6.1, `platformdirs` 4.11.9 (plus
  already-present `markdown-it-py`, `pygments`, `rich`, `typing-extensions`).
  No `tree-sitter` entry, no `[syntax]` extra, no Node/Bun/TypeScript/Electron.

### Local runtime evidence (`LOCAL_VERIFIED`, Windows host, Python 3.12.11)

- Lock determinism: first `uv lock` produced `uv.lock` SHA-256
  `35ACA7102A288BD44EBD7928409125C014470C61CBBDD883E6FAA6658AF066A3`
  (size 264213); a second `uv lock` left the same bytes/hash unchanged;
  `uv lock --check` exit 0.
- `uv run python` reports Python 3.12.11 and `textual.__version__ == "8.2.8"`.
- Headless qualification tests
  (`tests/integration/test_textual_qualification.py`, 10 tests) prove:
  construct/mount/start/shutdown; Cyrillic round-trip in `Input` and `TextArea`
  multiline; deterministic `run_test(size=...)` and `pilot.resize_terminal`;
  ordinary binding exactly-once; full command-palette selection reaches the same
  shared semantic counter; thread worker `RUNNING → SUCCESS` with loop
  responsiveness while blocked; error worker (`exit_on_error=False`) raising
  `WorkerFailed` then `ERROR` with `ValueError` and app recovery; cancellation
  raising `WorkerCancelled` → `CANCELLED` with a separate cooperative
  thread-termination signal and `calls == 1` (no framework retry). `app.workers`
  was empty after shutdown (additional evidence).
- `tests/contract/test_textual_boundaries.py` (static AST) proves no
  domain/storage/tools/models/application module imports Textual, with
  non-vacuous detector self-tests.
- No async pytest plugin is used: `run_test()` is driven synchronously via
  `asyncio.run`, matching the existing repository idiom. `pytest-asyncio` was not
  added.
- Gates: focused tests 14 passed; full suite `6657 passed, 131 skipped`; Ruff
  check/format clean; Pyright 0 errors; `git diff --check` clean.

### Platform evidence classification

```text
Windows local headless qualification        LOCAL_VERIFIED
Textual/package/compatibility metadata      EXTERNALLY_VERIFIED
macOS local real-terminal execution         SKIPPED_CAPABILITY (deferred to TUI-05)
```

macOS is not claimed as locally verified. No new CI system was introduced.

### Framework findings carried forward to TUI-03

- Focus safety holds for ordinary (non-priority) bindings: a focused text input
  consumes printable keys and does not trigger app-level single-key bindings.
  A `priority=True` single-key binding would bypass the focused widget, so
  production single-key bindings must not be priority.
- The command palette already shares one callback with the binding, which fits
  the planned single semantic-command registry; TUI-01 does not build it.
- Synchronous trusted calls are hosted with thread workers (`thread=True`);
  cancellation is cooperative and is neither rollback nor retry.
- 8.2.7–8.2.8 extended/Kitty key changes are risk-discovery only; no
  Kitty/leader/chord behavior was adopted and no production hotkeys were frozen.

### Limitations / deferrals

- Local macOS real-terminal execution `SKIPPED_CAPABILITY`; real-terminal
  cross-platform smoke matrix remains TUI-05.
- TUI-02 (composition seams), TUI-03 (shell/registry/palette/bindings), TUI-04
  (integration) not started.

## Durable record — TUI-02 (2026-09-17)

- Status: `DONE`.
- Branch: `feat/textual-tui`.
- Extracted the smallest capability-oriented shared composition seams required
  by both Typer and the future Textual TUI. New UI-agnostic package
  `src/dnd_assistant/composition/` (peer of `cli/`):
  ```text
  composition/__init__.py         package marker (no eager internal imports)
  composition/agent_model.py      model/profile resolution + lifetime + model_tool AuditContext
  composition/agent_runtime.py    AskRuntime + compose_ask_runtime + run graph
  composition/session_runtime.py  compose_session_runtime + compose_recovery_service
  ```
- `cli/agent_runtime.py` is now a thin compatibility re-export shim (no
  composition logic). `cli/session.py` keeps Russian rendering, `typer.echo`,
  `typer.Exit`, CLI `AuditContext` identity and recovery presentation; concrete
  session/recovery dependency construction moved to
  `composition/session_runtime.py`.
- Monkeypatch targets that need the concrete owner now patch
  `dnd_assistant.composition.agent_runtime` rather than names rebound in the shim.
- Explicitly deferred (no demonstrated shared need): `cli/changeset.py`,
  `cli/post_session_runtime.py`, `cli/main.py` index composition, and a
  standalone Campaign State composition seam.
- Added `tests/contract/test_composition_boundaries.py` (static AST):
  composition imports neither `typer`/`textual`/`cli`; `domain`, `application`,
  `storage`, `retrieval`, `tools`, `models` do not import composition; the
  package `__init__` has no eager internal imports.
- Added `tests/unit/test_composition_session_runtime.py`, including a literal
  filesystem byte-snapshot proof that recovery inspection is read-only.
- Changed files:
  ```text
  src/dnd_assistant/composition/__init__.py
  src/dnd_assistant/composition/agent_model.py
  src/dnd_assistant/composition/agent_runtime.py
  src/dnd_assistant/composition/session_runtime.py
  src/dnd_assistant/cli/agent_runtime.py
  src/dnd_assistant/cli/session.py
  tests/unit/test_composition_session_runtime.py
  tests/contract/test_composition_boundaries.py
  tests/unit/test_cli_agent_runtime.py
  tests/integration/test_cli_ask_mocked.py
  docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md
  DEVELOPMENT_STATUS.md
  ```
- No `src/dnd_assistant/tui/**`, no ChangeSet/post-session/index composition,
  no standalone Campaign State composition, no Stage-13 work.

## Stage-13 gate

Stage 13 Bootstrap must not begin until the TUI track has completed normal
implementation, review, repository integration/status reconciliation and
independent acceptance (TUI-06). Stage 13 is `NOT STARTED`, not `BLOCKED`.
