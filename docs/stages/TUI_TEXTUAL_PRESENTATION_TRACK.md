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

Full track review, documentation/status reconciliation and independent
acceptance, plus the durable Stage-13 handoff. Repository integration is kept as
a separate bounded task (`TUI-M01`); Stage 13 remains gated until `TUI-M01` is
independently accepted.

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

## Durable record — TUI-03 (2026-09-17)

- Status: `DONE`.
- Branch: `feat/textual-tui`.
- Production Textual app shell, central semantic command registry/single
  dispatcher, registry-derived bindings and command palette, footer
  discoverability, global/context scope, `applicable`/`enabled` presentation
  predicates, focus safety and a lazy `dnd tui` launcher. New package
  `src/dnd_assistant/tui/`.
- Changed files:
  ```text
  src/dnd_assistant/tui/__init__.py
  src/dnd_assistant/tui/commands.py
  src/dnd_assistant/tui/dispatch.py
  src/dnd_assistant/tui/bindings.py
  src/dnd_assistant/tui/screens.py
  src/dnd_assistant/tui/app.py
  src/dnd_assistant/tui/launcher.py
  src/dnd_assistant/cli/main.py
  tests/unit/test_tui_commands.py
  tests/integration/test_tui_shell.py
  tests/contract/test_tui_boundaries.py
  tests/unit/test_cli_tui_launcher.py
  docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md
  DEVELOPMENT_STATUS.md
  ```
- No `pyproject.toml`/`uv.lock` change (Textual stays `8.2.8`, no new
  dependency), no composition change, no worker manager, no assistant/session/
  Campaign-State integration, no write path, no Stage-13 work.

### Production TUI module map (physical lines)

```text
tui/__init__.py       23   package marker; no eager internal imports
tui/commands.py      269   semantic model, scope/context, registry, validation, inventory (Textual-free)
tui/dispatch.py      125   single dispatcher + availability/result enums (Textual-free)
tui/bindings.py       84   registry -> Textual Binding adapter + effective-key guard
tui/screens.py        31   ShellScreen (Header/body/Footer)
tui/app.py           129   DndTuiApp lifecycle + palette/check_action integration
tui/launcher.py       16   run() entry point
cli/main.py          138   adds lazy `dnd tui` command
```

### Production semantic command inventory (initial)

| ID | title | description | scope | default keys | palette |
|---|---|---|---|---|---|
| `app.quit` | Выход | Закрыть приложение | global | `ctrl+q` | yes |
| `app.command-palette` | Палитра команд | Открыть палитру команд | global | `ctrl+p` | no |
| `app.help` | Справка | Показать справку и сочетания клавиш | global | `?`, `f1` | yes |

### Stable semantic ID grammar

```text
segment := [a-z][a-z0-9]*(?:-[a-z0-9]+)*
id      := segment(?:\.segment)+
```

Rejected: `-app.quit`, `app-.quit`, `app..quit`, `app.command--palette`,
`App.quit`, `app_quit`, `app`, `.app.quit`, `app.`, `app.9quit`.

### Registry validation (fail fast)

Duplicate ID, invalid ID grammar, empty title/description, missing/non-callable
handler, screen scope without a context, empty key alias, duplicate alias within
one command, and raw key-alias collision across commands with overlapping scopes
are all rejected before the app runs. The Textual binding adapter additionally
rejects collisions after Textual's own key normalization (e.g. `?` vs
`question_mark`) for overlapping scopes, using a framework `BindingsMap` rather
than a duplicated normalization table; non-overlapping screen contexts may reuse
an effective key.

### Dispatch path

```text
physical key -> semantic_dispatch('<id>') -> App.action_semantic_dispatch ─┐
palette item -> SystemCommand callback -> App.run_semantic_command ────────┤
                                                                          ↓
                                                    one SemanticDispatcher
                                                                          ↓
                                                    one registered handler
```

### Palette approach

`ENABLE_COMMAND_PALETTE=False`; `ctrl+p` is a registry-owned ordinary binding
for `app.command-palette`, whose handler pushes Textual's production
`CommandPalette`. `App.get_system_commands` yields registry-derived entries only.
`palette=False`, context-inapplicable, disabled and `applicable=False` commands
are omitted. No custom palette widget. No fallback was needed.

### Framework/evidence notes

- `textual==8.2.8`; no `pytest-asyncio`. Headless `App.run_test()` via
  `asyncio.run`.
- Focus safety: focused `Input`/`TextArea` consume printable keys
  (`isprintable()`), so the printable global `?` does not dispatch while typing;
  Cyrillic typing round-trips. All registry-generated bindings are
  `priority=False`.
- Scope machinery proven with test-only screens/registries; no fake production
  campaign screens.
- Lazy launch: `dnd tui`; importing `dnd_assistant.cli.main` does not load
  `dnd_assistant.tui`/`textual` (literal subprocess assertion + AST guard).
- Boundary: trusted layers/composition do not import TUI; TUI does not import
  CLI; `commands.py`/`dispatch.py` stay Textual-free.
- Presentation predicates documented as UX-only (`applicable`/`enabled`) and
  structurally guarded: `SemanticCommand` has no authorization/policy field and
  the dispatcher imports no write-capable layer.
- Gates: focused TUI suites 77 passed; TUI-01/TUI-02/TUI-03 regression suites
  692 passed; full suite 6769 passed, 131 skipped; Ruff check/format clean;
  Pyright 0 errors; `git diff --check` clean.

### Limitations / deferrals

- Real-terminal Windows/macOS smoke matrix remains TUI-05; macOS is not claimed.
- TUI-04 integration (assistant/session/Campaign-State, Vault, workers,
  write-capable actions) not started.

## Durable record — TUI-04 (2026-09-17)

- Status: `DONE`.
- Branch: `feat/textual-tui`.
- Primary assistant / session / Campaign-State integration with real read and
  write paths through the accepted trusted services. No Stage-13 work.
- Changed files:
  ```text
  src/dnd_assistant/composition/audit_context.py (new)
  src/dnd_assistant/composition/campaign_state.py (new)
  src/dnd_assistant/tui/services.py (new)
  src/dnd_assistant/tui/inflight.py (new)
  src/dnd_assistant/tui/view.py (new)
  src/dnd_assistant/tui/assistant.py (new)
  src/dnd_assistant/tui/session.py (new)
  src/dnd_assistant/tui/campaign_state.py (new)
  src/dnd_assistant/tui/screens.py
  src/dnd_assistant/tui/app.py
  src/dnd_assistant/tui/commands.py
  src/dnd_assistant/tui/launcher.py
  src/dnd_assistant/cli/main.py
  src/dnd_assistant/cli/session.py
  tests/unit/test_composition_audit_context.py (new)
  tests/unit/test_composition_campaign_state.py (new)
  tests/unit/test_tui_inflight.py (new)
  tests/unit/test_tui_services.py (new)
  tests/unit/test_tui_commands.py
  tests/unit/test_cli_tui_launcher.py
  tests/integration/test_tui_assistant.py (new)
  tests/integration/test_tui_session.py (new)
  tests/integration/test_tui_campaign_state.py (new)
  tests/integration/test_tui_shell.py
  tests/contract/test_tui_boundaries.py
  ```
- No `pyproject.toml`/`uv.lock`/`opencode.json`/`.opencode/**` change; Textual
  stays `8.2.8`; `tests/contract/test_boundaries.py` not grown.

### Production TUI module map (physical lines)

```text
tui/app.py             273   app lifecycle, launch-services wiring, hosts/dispatch
tui/commands.py        455   semantic registry + CommandHost/CommandContext (Textual-free)
tui/dispatch.py        125   single dispatcher (unchanged)
tui/bindings.py         84   registry → Binding adapter (unchanged)
tui/screens.py          53   MainScreen + TabbedContent
tui/view.py            166   CapabilityView worker/gate base + TuiHost protocol
tui/inflight.py         69   single-owner presentation in-flight gate (Textual-free)
tui/services.py        252   launch context, capability protocols/adapters (Textual-free)
tui/assistant.py       200   assistant view
tui/session.py         262   session view
tui/campaign_state.py  141   Campaign-State view (inspect + rebuild both gated)
tui/launcher.py         31   run() entry point
composition/audit_context.py     54   shared presentation-neutral AuditContext factory
composition/campaign_state.py   167   Campaign-State capability + PLAYER-safe view DTO
cli/main.py            185   `dnd tui` options (lazy)
cli/session.py         280   thin audit wrappers over the shared factory
```

### Architecture summary

- `dnd tui --vault --config --profile [--allow-write]` mirrors `dnd ask`
  option semantics; lazy import preserved (normal CLI import does not load
  TUI/Textual).
- `TuiLaunchContext` is immutable; `TuiServices` is a bounded, named
  three-capability bundle (`assistant`, `session`, `campaign_state`) with no
  service locator and no mapping surface. Each view receives only the
  capability it needs.
- Assistant runtime lifetime is **per submission**: one
  `compose_ask_runtime` → one `run` → one `close` (idempotent), and session
  mode/audit identity is refreshed each call. No cached app/screen runtime.
- `--allow-write` is the agent/model WRITE ceiling only. Explicit human session
  mutations always use their deterministic trusted paths; the UI write toggle
  is presentation intent and the immutable per-submission snapshot is the only
  `allow_write` input to composition.
- Assistant preflight uses `compose_recovery_service(...).inspect_runtime_partition()`:
  blocking issues prevent model composition/run; externally-owned issues are a
  non-blocking hint. Session mutations use the same trusted partition.
- A single-owner `InFlightGate` serializes the exclusive operations at the
  presentation level:
  ```text
  exclusive gate:
    assistant submission
    session start/note/end
    Campaign-State inspect/rebuild
  independent read:
    session status refresh
  ```
  Campaign-State inspect is gated because publication replaces managed
  artifacts individually and writes the manifest last; a concurrent inspect
  could transiently classify a valid in-progress publication as `CORRUPT`.
  Assistant execution may lazily rebuild Campaign State through its provider, so
  the shared gate also serializes inspect against assistant submission and
  session mutation (and against another inspect). The `campaign-state.reload`
  command carries the `_idle` presentation predicate so it is disabled while any
  exclusive operation is active. This is UX serialization, not the trusted
  consistency/authorization boundary.
- Synchronous trusted work runs in Textual thread workers
  (`exit_on_error=False`); worker callables return values only and never touch
  UI. Expected `DndAssistantError` becomes a Russian error DTO; unexpected
  exceptions are re-raised on the event loop and stay observable/test-failing.
  Quit while work is in flight is refused; TUI-04 exposes no cancellation.
- Campaign-State TUI renders only `PlayerCampaignStateView` (exact trusted
  status + PLAYER-projected recently-touched references). The view carries no
  internal `CampaignState`, manifest, fingerprint, provenance, cause or raw
  detail; non-CURRENT statuses show no semantic data. The interactive
  capability reuses `FAST_AGENT_RECENT_SESSION_LIMIT` (5); Stage-12 ownership
  unchanged.
- Navigation uses native `TabbedContent` (Ассистент/Сессия/Состояние кампании)
  in one `MainScreen`; the active pane id is the semantic command context.
- One class-level `SEMANTIC_REGISTRY`, one dispatcher, registry-derived
  `BINDINGS`; buttons and input submission converge on the same semantic
  command IDs.

### Production semantic command inventory (TUI-04 additions)

| ID | title | scope | default keys | palette |
|---|---|---|---|---|
| `view.assistant` | Ассистент | global | `f2` | yes |
| `view.session` | Сессия | global | `f3` | yes |
| `view.campaign-state` | Состояние кампании | global | `f4` | yes |
| `assistant.submit` | Отправить запрос | assistant | — | yes |
| `assistant.toggle-write` | Режим записи ассистента | assistant | — | yes |
| `session.refresh` | Обновить статус сессии | session | — | yes |
| `session.start` | Начать сессию | session | — | yes |
| `session.note` | Добавить заметку | session | — | yes |
| `session.end` | Завершить сессию | session | — | yes |
| `campaign-state.reload` | Обновить отображение | campaign-state | — | yes |
| `campaign-state.rebuild` | Перестроить состояние | campaign-state | — | yes |

Existing `app.quit` (now in-flight gated), `app.command-palette`, `app.help`
retained. All registry bindings remain non-priority.

### Framework/evidence notes

- Headless `App.run_test()` via `asyncio.run`; `textual==8.2.8`; no async pytest
  plugin. `TabbedContent` works directly (no fallback needed).
- Assistant integration (fakes at the capability boundary): READ default and
  one run; explicit WRITE snapshot; CLARIFY rendering; blocking recovery → zero
  model run; externally-owned hint; expected error keeps app usable; unexpected
  error observable; worker runs off-loop and UI applies on `MainThread`;
  duplicate submit starts one worker; assistant↔session↔Campaign-State mutual
  in-flight exclusion; focused input Cyrillic/`?` focus safety.
- Assistant lifetime unit evidence: close exactly once on success, expected
  error and unexpected post-composition error; composition failure propagates
  with no close; WRITE without ceiling rejected before compose.
- Session integration (real temporary Vault, production composition): full
  start/note/end write path, canonical `S001` metadata status `completed`,
  `touched_entities == ["npc-varos", "item-001"]` unchanged, note text
  persisted, audit `source="tui"` with `tui-session-start-`/`tui-note-`/
  `tui-session-end-` operation IDs; blocking recovery prevents `start`.
- Campaign-State integration (real temporary Vault): `rebuild`/`inspect` return
  `CURRENT` with only the PLAYER entity; DM/SYSTEM entities absent from the
  rendered body; all six statuses map to distinct Russian labels; non-CURRENT
  views expose no entity data; no invented categories.
- Campaign-State presentation concurrency contract (deterministic blocking fake
  capabilities, no timing-sensitive filesystem race): assistant in flight →
  `campaign-state.reload` not executed and inspect calls `0`; inspect in flight
  → `assistant.submit`, `session.start` and `campaign-state.rebuild` not
  executed; rebuild in flight → reload not executed; duplicate reload while
  inspect is running → exactly one inspect call; successful inspect releases the
  gate, renders and allows later assistant/rebuild to execute; expected
  `DndAssistantError` releases the gate with a Russian error and a usable app;
  unexpected inspect exception is released by normal worker-state handling and
  stays observable/test-failing. `tests/unit/test_tui_commands.py` additionally
  proves `campaign-state.reload` is `DISABLED` while the gate is held and that
  `session.refresh` remains available.
- CLI audit provenance preserved (`source="cli"`, `_now_utc`/
  `_new_operation_id` compatibility) and composition reuse of
  `FAST_AGENT_RECENT_SESSION_LIMIT` asserted literally.
- Boundary coverage extended in `tests/contract/test_tui_boundaries.py`:
  Campaign-State view imports no materialization/projection/storage/pathlib; TUI
  capability modules import no CLI; `commands/dispatch/inflight/services` stay
  Textual-free; `TuiServices` exposes no locator surface; player-safe view field
  set; in-flight gate has no queue.
- Gates: focused corrected TUI/assistant/session/Campaign-State/composition/
  boundary suites 126 passed; full suite `6869 passed, 131 skipped`; Ruff
  check/format clean; Pyright 0 errors; `git diff --check` clean. One transient
  full-suite failure in `test_campaign_state_materialization` (Windows
  `shutil.rmtree` timing) was observed once during initial TUI-04 development,
  then passed in isolation, in a unit+integration run and in subsequent
  canonical full runs.

### Limitations / deferrals

- Real-terminal Windows/macOS smoke matrix, resize/narrow layout, paste/
  multiline, cancellation UX and final error polish remain TUI-05.
- TUI-04 exposes no user cancellation affordance; quit is refused while trusted
  work is in flight.
- TUI-05 (hardening) and TUI-06 (review/Stage-13 handoff) not started as of
  TUI-04; both were completed in later tasks (see their durable records below).

## Durable record — TUI-05 (2026-09-17)

- Status: `DONE`.
- Branch: `feat/textual-tui`.
- Starting HEAD: `d245ef35a12351efa2238f7957babae4f2687f90`. Final commit SHA
  (reported in Final Report).
- Interaction / cross-platform / error-recovery hardening. No TUI-06 or
  Stage-13 work.
- Changed files:
  ```text
  src/dnd_assistant/tui/errors.py (new)
  src/dnd_assistant/tui/inputs.py (new)
  src/dnd_assistant/tui/styles.py (new)
  src/dnd_assistant/tui/app.py
  src/dnd_assistant/tui/assistant.py
  src/dnd_assistant/tui/campaign_state.py
  src/dnd_assistant/tui/commands.py
  src/dnd_assistant/tui/screens.py
  src/dnd_assistant/tui/session.py
  src/dnd_assistant/tui/view.py
  src/dnd_assistant/cli/main.py
  tests/unit/test_tui_errors.py (new)
  tests/integration/test_tui_resize.py (new)
  tests/integration/test_tui_paste.py (new)
  tests/integration/test_tui_interaction.py (new)
  tests/integration/test_tui_recovery.py (new)
  tests/integration/test_tui_assistant.py
  tests/integration/test_tui_campaign_state.py
  tests/integration/test_tui_shell.py
  tests/unit/test_tui_commands.py
  tests/unit/test_cli_tui_launcher.py
  tests/contract/test_tui_boundaries.py
  docs/development/tui-terminal-smoke.md (new)
  docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md
  DEVELOPMENT_STATUS.md
  ```
- No `pyproject.toml`/`uv.lock`/`opencode.json`/`.opencode/**` change; Textual
  stays `8.2.8`; no new dependency; no `pytest-asyncio`;
  `tests/contract/test_boundaries.py` not grown.

### Terminal-size contract

```text
reference          100x30
baseline            80x24
minimum usable      60x20  (width >= 60 AND height >= 20)
below minimum       degraded/scrollable, not claimed fully usable
```

Below the minimum the layout remains a degraded, scrollable form; no new
screen/modal is introduced and full usability is not claimed.

### Responsive strategy

Native Textual breakpoints only. `DndTuiApp.HORIZONTAL_BREAKPOINTS` /
`VERTICAL_BREAKPOINTS` are ascending minimum-size tables mapping to
`-w-tiny/-w-narrow/-w-baseline/-w-reference` and
`-h-tiny/-h-short/-h-baseline/-h-reference`; Textual's `Screen._on_resize`
applies exactly one class per axis. `tui/styles.py` owns one Textual-free
`RESPONSIVE_CSS` string assigned to `DndTuiApp.CSS` (packaged with the module;
no external `.tcss`, no packaging change, no layout abstraction).
At narrow/below-minimum widths the action rows stack vertically so no control
is horizontally clipped.

### Assistant multiline contract

`AssistantView` uses a native `TextArea` (`soft_wrap=True`,
`tab_behavior="focus"`). Enter inserts a newline and never submits; Tab moves
focus out. Emptiness is checked with `.strip()`, but the value passed to the
trusted assistant is the original `TextArea.text` with no stripping/trimming.
Outcomes: `RESPOND` clears the editor; `CLARIFY`, expected error and blocking
recovery retain it. No conversation persistence.

### Paste contract

`Input._on_paste` in pinned Textual silently keeps only the first pasted line;
TUI-05 intercepts the public `Paste` surface (`on_paste`, `event.prevent_default()`
+ `event.stop()`) in `tui/inputs.py`. The private `_on_paste` hook is not used.
`SingleLineInput` (session note) rejects multiline paste with a Russian warning
and leaves the value unchanged (zero capability/canonical mutation).
`TouchedEntitiesInput` normalizes line breaks to spaces, preserving literal ID
tokens and order with no entity inference. Accepted text is inserted through the
public `Input` editing API. Assistant `TextArea` paste preserves multiline text
and never dispatches a binding.

### Focus / tab order

`MainScreen.AUTO_FOCUS = "#assistant-query"`. F2/F3/F4 (and palette
navigation through `navigate_to`) focus the pane's primary control
(assistant editor / session note / Campaign-State reload) via
`call_after_refresh`; raw tab-bar arrow switching does not steal focus. Tab
traversal reaches buttons; resize/expected errors preserve focus and editor
content; palette/help close restores the previous focus.

### Semantic binding change

No new command IDs. A single ordinary non-priority alias `f5` is added to the
existing `assistant.submit`. The authoritative submit surfaces remain the button
and the command palette; `f5` is a best-effort convenience alias whose
terminal-level portability is `SKIPPED_CAPABILITY` (see platform evidence).

### CANCELLED fail-closed semantics

`CapabilityView.on_worker_state_changed` now fails closed on
`WorkerState.CANCELLED`: it does not clear busy, does not release the
`InFlightGate` and does not interpret cancellation as completion/rollback.
SUCCESS/ERROR retain the previous release-and-apply behavior. Pinned Textual
thread workers cannot be forcibly cancelled (`worker.py` documents that
cancelled work may still be running; `_run_threaded` uses an executor), so
cancellation is never proof of completion. Production TUI exposes no user
cancellation affordance and contains no `.cancel(...)` call (static guard).
The synthetic-cancellation headless test cancels a worker solely from the test
harness and proves the gate stays held; the test does not claim the app becomes
normally reusable after an unsupported cancellation path.

### Expected errors, input preservation, launch mapping

`tui/errors.py` (Textual-free) maps stable `DndAssistantError` classes to
Russian categories and renders `"{category}: {exc}"` plus an optional safe hint;
it never parses message strings. Only expected `DndAssistantError` becomes a
recoverable result; unexpected exceptions remain re-raised/observable.
Per-operation clearing replaces the previous blanket clear: assistant clears
only on RESPOND; session note clears only on a successful note; touched IDs
clear only on a successful end. Expected errors retain input and permit exactly
one manual retry with no automatic retry. `cli/main.py::_tui` maps an expected
`DndAssistantError` raised during lazy `run(...)` to a Russian stderr message
and `typer.Exit(1)`; unexpected exceptions propagate; normal CLI import does not
eagerly import Textual/TUI.

### Framework/evidence notes

- Headless `App.run_test()` via `asyncio.run`; `textual==8.2.8`; no async pytest
  plugin.
- Breakpoint threshold tests at 59/60, 79/80, 99/100 and 11/12, 19/20, 29/30.
- 60x20 proves: no crash, active context retained, editor reachable and
  focusable, primary controls present, action rows stacked, native vertical
  scrolling available.
- reference→narrow→reference retains editor content, focus and active tab.
- Paste is delivered to the `App` (the terminal driver path that
  `App.on_event` forwards to the focused widget exactly once); synthetic
  `Paste` is headless evidence only.
- F5 dispatches `assistant.submit` exactly once in headless tests.
- CANCELLED fail-closed: gate/busy remain held and a further exclusive
  `assistant.submit` is not executed.
- Busy semantic quit does not exit and the palette omits `Выход`; idle semantic
  quit exits. Runtime binding audit confirms `ctrl+q` maps to
  `semantic_dispatch('app.quit')` and no active binding resolves to the
  framework `quit`/`help_quit`/`suspend` actions.
- Gates: focused TUI-05 new suites 55 passed; TUI-01..TUI-04 TUI/composition/
  qualification/boundary regression suites 218 passed; full suite
  `6941 passed, 131 skipped`; Ruff check/format clean; Pyright 0 errors;
  `git diff --check` clean.

### Maintainability (physical lines)

```text
tui/app.py             321
tui/assistant.py       202
tui/campaign_state.py  142
tui/commands.py        456
tui/session.py         283
tui/view.py            171
tui/errors.py           64
tui/inputs.py           67
tui/styles.py           56
tui/screens.py          56
cli/main.py            189
```

All new/modified production modules are below the 700-line hard limit; all
new/modified test modules are below the 1000-line hard limit; no legacy
exception or global limit changed.

### Platform evidence classification

```text
Windows local headless TUI-05 tests            LOCAL_VERIFIED
Textual 8.2.8 API findings (source-inspected)  LOCAL_VERIFIED
Windows Terminal real-terminal smoke           SKIPPED_CAPABILITY (non-interactive agent)
macOS terminal / iTerm real-terminal smoke     SKIPPED_CAPABILITY (no macOS host)
f5 terminal-level portability                  SKIPPED_CAPABILITY (headless dispatch only)
```

Manual real-terminal smoke protocol:
`docs/development/tui-terminal-smoke.md` (disposable copy of
`tests/fixtures/golden_test_vault/`; never a personal Vault). No real-terminal
run was executed in this task; both platforms and f5 terminal portability are
recorded `SKIPPED_CAPABILITY`, never as verified.

### Limitations / deferrals

- Real-terminal Windows/macOS smoke and terminal-level `f5` portability remain
  `SKIPPED_CAPABILITY`, preserved for TUI-06.
- External terminal/OS kill (SIGKILL-equivalent, machine shutdown) cannot be
  prevented; only normal in-app shutdown paths are hardened.
- TUI-06 (full track review / status cleanup / Stage-13 handoff) not started as
  of TUI-05; completed in TUI-06 (see the record below).

## Durable record — TUI-06 (2026-09-18)

- Status: `DONE`.
- Branch: `feat/textual-tui`. Starting HEAD:
  `24c3896bd3888dc5d12a7d7d7cc49b66bac7e3b2` (TUI-05). Final commit SHA reported
  in the Final Report.
- Full track review / status cleanup / Stage-13 handoff / OpenCode
  inspection-permission hardening. No Stage-13 implementation, no production
  runtime behavior change, no merge to `main`.
- Changed files:
  ```text
  opencode.json
  DEVELOPMENT_STATUS.md
  docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md
  docs/stages/README.md
  docs/stages/13_BOOTSTRAP.md (new)
  src/dnd_assistant/tui/inflight.py (docstring only)
  ```
- No `pyproject.toml`/`uv.lock` change; Textual stays `8.2.8`;
  `tests/contract/test_boundaries.py` not grown; no `.opencode/**` change.

### Historical review range

```text
pre-track base (Stage-12 completion head)  f491411
branch point relative to main              4ae7e61
merge-base(main, feat/textual-tui)         4ae7e61
base-only (main ahead)                     0
head-only (feature ahead of main)          12
full-track review range                    f491411..24c3896 (14 commits)
```

Commit inventory: TUI-00 (2), TUI-01 (2), TUI-02 (2), TUI-03 (2, one
correction), TUI-04 (2, one correction), TUI-05 (1), plus three
OpenCode/settings-only commits inside/adjacent to the range (`8198fda`,
`71aa67f`, `4ae7e61`) touching only `opencode.json`. No unexpected auxiliary
commit.

### Final architecture verdict

The track is architecturally complete at the reviewed head. Obsidian Vault
remains the only canonical Source of Truth; Textual is presentation-only;
`ToolExecutor`/ChangeSet/`VaultRepository` remain the write boundaries; one
semantic command registry feeds one dispatcher, bindings and palette; the
TUI-04/TUI-05 in-flight contract is intact (exclusive: assistant submission,
session start/note/end, Campaign-State inspect/reload, Campaign-State rebuild;
independent read: session status refresh); `CANCELLED` stays fail-closed; no
production `.cancel(` call exists. No TUI-05 change weakened the TUI-00..TUI-04
boundaries.

### Closing documentation defect corrected

`src/dnd_assistant/tui/inflight.py` module docstring was stale after the TUI-04
correction `d245ef3`: it still claimed read-only inspection bypasses the gate
and omitted Campaign-State inspection from the exclusive-operation list. The
docstring was corrected to match the accepted contract (Campaign-State
inspect/reload is exclusive; session status refresh is the independent read).
Runtime behavior unchanged (comment-only diff).

### OpenCode inspection-permission hardening

`opencode.json` remains V1 syntax on the installed OpenCode `1.18.31` (no
version upgrade, no model/default-agent change, no V2 migration). Verified
matcher semantics from the installed tag source plus live probes:

```text
permission/index.ts evaluate() -> findLast   LAST MATCHING RULE WINS
fromConfig() preserves JSON key order
core/util/wildcard.ts -> anchored ^...$ with * -> .* (dotall)
tool/shell.ts -> tree-sitter bash/PowerShell; one permission pattern per
  command node; redirect text is folded into the command's pattern
```

Read-only Git surface expanded with precise subcommand forms (`git diff`,
`git diff *`, `git diff-tree`/`git diff-tree *`, `git diff-index`, `git
diff-files`, `git cat-file`, `git ls-tree`, `git for-each-ref`, `git show-ref`,
`git name-rev`, `git grep`, `git check-ignore`, `git check-attr`, `git
count-objects`, `git rev-list`, `git merge-base`, `git remote get-url`, safe
`git reflog show` forms and branch/tag/config/stash listing forms) in both the
plan and build agents. `git reflog*` is deliberately not used (would cover
`reflog expire`/`delete`). Output-write and shell-redirection guards are placed
**after** the broad read-only allows so they win by last-match:

```text
plan  agent: shell redirection > / >>            DENY
             git --output write forms            DENY
build agent: shell redirection > / >>            ASK
             git --output write forms            ASK
```

Destructive denies remain after the redirect guards, so e.g.
`git push --force > f` still resolves to `deny`. Verified probes (faithful port
of the 1.18.31 `findLast` + `Wildcard.match` evaluator over the edited rules):
plan `git diff-tree HEAD` → allow, `git diff-tree HEAD > out.txt` → deny,
`git log --output=out.txt` → deny; build `git diff-tree HEAD` → allow,
`git diff-tree HEAD > out.txt` → ask, `git log --output=out.txt` → ask.
Arbitrary `ForEach-Object { ... }` remains `ask`; nested non-command side
effects cannot be made safe by cmdlet-name checks. Pre-existing user-approved
`git checkout *` rules are preserved and classified as authorized mutation, not
read-only inspection.

### Maintainability (physical lines)

All production modules ≤ 700 and all test modules ≤ 1000; no ratchet exception
added or raised and no global limit changed. `tests/contract/test_boundaries.py`
remains exactly 1000 lines and unchanged across the track. `tui/commands.py`
(456), `tui/app.py` (321), `tui/session.py` (283) remain the largest TUI
production modules.

### Platform evidence classification (unchanged, honest)

```text
Windows local headless TUI-06 review           LOCAL_VERIFIED
Windows Terminal real-terminal smoke           SKIPPED_CAPABILITY (non-interactive agent)
macOS terminal / iTerm real-terminal smoke     SKIPPED_CAPABILITY (no macOS host)
f5 terminal-level portability                  SKIPPED_CAPABILITY (headless dispatch only)
```

No new real-terminal evidence was produced. These are supplementary manual
evidence and are **not** blocking for Stage 13; they carry forward as
release/hardening limitations (Stage-14 candidate).

### Gates (final state)

```text
uv run python -m json.tool opencode.json   JSON OK
uv run pytest                              6941 passed, 131 skipped, 1 warning
                                           (pre-existing pydantic deprecation)
uv run ruff check .                        All checks passed!
uv run ruff format --check .               541 files already formatted
uv run pyright                             0 errors, 0 warnings, 0 informations
uv lock --check                            Resolved 57 packages (exit 0)
git diff --check                           clean
```

### OpenCode matcher probe evidence (literal)

No stable built-in permission-evaluation command is available, and the running
OpenCode session had not reloaded the edited `opencode.json`, so
`opencode --version`/`opencode debug config` were not used. Verification used a
faithful Python port of the installed OpenCode `1.18.31` matcher
(`packages/opencode/src/permission/index.ts` `evaluate()` = `findLast`;
`packages/core/src/util/wildcard.ts` `Wildcard.match`, anchored `^...$` with
`* -> .*`) applied to the ordered `agent.<name>.permission.bash` key order.
Recorded literal results:

```text
plan  git diff-tree HEAD                     allow
plan  git diff-tree HEAD > out.txt           deny   (matched *>*)
plan  git log --output=out.txt               deny   (matched git log*--output*)
plan  git reflog expire --expire=now --all   deny   (no reflog allow; * deny)
plan  git hash-object -w foo                 deny
plan  git update-ref refs/heads/x HEAD       deny
build git diff-tree HEAD                     allow
build git diff-tree HEAD > out.txt           ask    (matched *>*)
build git log --output=out.txt               ask    (matched git log*--output*)
build git push --force                       deny
build git reset --hard                       deny
build Get-ChildItem src                      allow
build ForEach-Object { Remove-Item $_ }      ask
```

The evaluator was a throwaway dev-tooling script outside the repository; these
literal results and the source-verified matcher semantics are the durable record.

### Integration handoff

TUI-06 intentionally does not merge to `main`. Repository integration remains a
separate bounded task:

```text
TUI-M01 — ff-only integrate feat/textual-tui into main
```

After independent acceptance of `TUI-M01`, the next work becomes
`S13-01 — Vault Initialization Contract + dnd init`. No tag is created.

## Stage-13 gate

Stage 13 Bootstrap must not begin until the TUI track has completed normal
implementation, review, repository integration/status reconciliation and
independent acceptance. TUI-06 completed review, status cleanup and the Stage-13
handoff; ff-only integration remains `TUI-M01`. Stage 13 is `NOT STARTED` and
gated on independent acceptance of `TUI-M01`, not `BLOCKED`. The durable Stage-13
handoff contract (including the non-negotiable split between `dnd init` and
existing-campaign bootstrap) lives in `docs/stages/13_BOOTSTRAP.md`.
