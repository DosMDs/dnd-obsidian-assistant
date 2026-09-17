# ADR-0008: Textual TUI as a presentation-only front-end

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

After Stage 12 (Campaign State) the project accepted a post-Stage-12 product
direction:

```text
Stage 12 Campaign State
→ Textual TUI architecture track
→ Stage 13 Bootstrap
→ Stage 14 Evals / Hardening
```

The application currently exposes a single interactive surface, the Typer CLI
(`src/dnd_assistant/cli/`). Typer must remain supported for scripting,
administration, bootstrap, recovery, diagnostics and evals. The project wants a
first-class interactive terminal UI without creating a second Source of Truth,
without duplicating trusted behavior, and without moving business or write
policy into presentation code.

The actual current composition lives in the CLI layer:
`cli/agent_runtime.py` (`compose_ask_runtime`, `AskRuntime`), `cli/session.py`
(`_compose_runtime`, `_compose_recovery`), `cli/changeset.py`
(`_compose_store`, `_compose_repository`), `cli/post_session_runtime.py`
(`compose_post_session_runtime`), and the index-rebuild composition in
`cli/main.py`. Trusted behavior already lives in `application/`, `domain/`,
`storage/`, `retrieval/` and `tools/`; the CLI modules own a mixture of
presentation, composition and error mapping.

A review question arose: how should a Textual TUI be introduced so that Typer
and Textual invoke the same trusted behavior, without redefining the trust
boundary or forcing a large speculative refactor?

## Decision

Textual is adopted as a **presentation-only** front-end, introduced through a
dependency-ordered architecture track (`TUI-00` … `TUI-06`) that precedes
Stage 13.

1. **Presentation-only.** Textual, its screens, widgets, controllers, key
   handlers, command-palette handlers and ephemeral UI state must contain no
   canonical semantics and no write policy. A UI handler may only select and
   invoke an already-trusted capability.

2. **Dependency direction is one-way.**

   ```text
   domain      -> textual     FORBIDDEN
   storage     -> textual     FORBIDDEN
   tools       -> textual     FORBIDDEN
   models      -> textual     FORBIDDEN
   application -> textual     FORBIDDEN
   ```

   `domain`, `storage`, `tools`, `models` and `application` must not import
   Textual, the TUI package, or any presentation/composition host. New
   presentation/composition code sits above `application`, as a peer of `cli/`.

   ```text
   Typer CLI ───────┐
                    ├──> shared composition + application-service boundary
   Textual TUI ─────┘
   ```

3. **Typer coexists; no second custom REPL.** Typer remains the supported
   surface for scripting, administration, bootstrap, recovery, diagnostics and
   evals. The TUI track must not build a second custom interactive REPL
   alongside it.

4. **Smallest capability-oriented composition seams.** Presentation
   front-ends share trusted behavior through a UI-agnostic composition
   boundary. That boundary is extracted incrementally in TUI-02 as the
   **smallest set of capability-oriented seams actually required by both Typer
   and Textual**. A monolithic composition root/facade that eagerly consolidates
   all current CLI wiring is explicitly rejected as a TUI-00/TUI-02 design.

5. **Semantic command authority.** Important operations are identified by stable
   semantic command IDs. A single centralized semantic command registry/dispatch
   surface is the one source that feeds hotkeys/bindings, the command palette,
   context actions, footer hints and help/discoverability; these surfaces must
   not reimplement the same command independently. Physical key bindings are
   replaceable aliases for semantic commands, never canonical. Global commands
   are separated from context/screen commands. Ordinary bindings plus the
   semantic command registry and command palette are the required foundation.
   Leader/chord bindings are **optional** and may be qualified/adopted only if a
   concrete UX need justifies it and cross-platform evidence supports it.

6. **UI state is not authorization.** `enabled` / `visible` / focus / screen
   state is presentation guidance only and is never an authorization boundary.
   Every write-capable TUI action must still flow through the existing trusted
   path: `ToolExecutor`, ChangeSet review/apply, revision checks,
   permission/session checks, audit, and `VaultRepository`. UI filtering,
   hiding or confirmation is not authorization.

7. **Focus safety.** Focused text/multiline input must not leak ordinary typing
   into single-key global commands. This is a deterministic headless
   requirement, not later polish.

8. **Async/worker boundary.** The trusted synchronous runtime/services must not
   be rewritten async to satisfy UI aesthetics. Textual workers/async facilities
   host existing synchronous application/runtime calls while preserving a
   responsive UI, exactly-once invocation, no implicit side-effect retry,
   explicit cancellation semantics, usable recovery after exception, and all
   existing ToolExecutor/runtime safety invariants. Cancellation is a UI
   decision; it must never be documented or implemented as rollback or retry of
   a started write. The adapter belongs in the presentation/composition host
   layer, not in domain/application/storage/tools.

9. **Test-integration strategy is qualified, not presumed.** TUI-01 qualifies
   Textual's test-integration strategy on the supported matrix. `pytest-asyncio`
   (or any other new async-test dependency) is **not presumed mandatory** and is
   added only if qualification demonstrates a concrete need. Headless
   `App.run_test()` / `Pilot` evidence is required for semantic command
   behavior, focus safety, screen transitions and worker/cancellation recovery;
   screenshots are not the primary semantic-correctness strategy. A small
   real-terminal smoke matrix (Windows Terminal primary; macOS terminal/iTerm
   first-class; Unicode/Cyrillic; paste/multiline; resize) supplements headless
   evidence.

10. **Dependency qualification precedes pinning.** An exact candidate Textual
    release is qualified against Python 3.12+, `uv` resolution/lock, Windows and
    macOS, Unicode/Cyrillic, startup/shutdown, widget composition, multiline
    input, focus, resize, workers, command palette, bindings, `App.run_test()`
    and `Pilot`. Textual is pinned only after qualification succeeds. No
    Node/Bun/TypeScript/Electron is introduced.

11. **Campaign State semantics unchanged.** The TUI track introduces no new
    Campaign State semantics. In particular, recently touched entities must not
    be reinterpreted as current location, active quests, important NPCs, party
    goals, unresolved threads or deadlines.

12. **Maintainability.** The track respects the existing hard limits
    (production ≤ 700 physical lines; test ≤ 1000 physical lines) and applies
    decomposition pressure before those limits. New presentation boundary
    coverage goes in focused new test modules:
    `tests/contract/test_boundaries.py` is at its ceiling and must not grow.

13. **Stage-13 gate.** Stage 13 Bootstrap must not begin until the TUI track has
    completed normal implementation, review, repository integration/status
    reconciliation and independent acceptance. Stage 13/14 are `NOT STARTED`,
    not `BLOCKED`.

The alternative — no TUI, CLI only — is rejected because the accepted product
direction requires a first-class interactive terminal surface. The alternative
of a monolithic application facade introduced up front is rejected in favor of
incremental capability-oriented seams.

## Consequences

### Positive

- One trusted behavior surface (`ToolExecutor` / application services / Vault)
  serves both Typer and Textual; no duplicated write paths.
- The trust boundary and Source of Truth are unchanged.
- Presentation can evolve without touching domain/storage/application.
- Semantic command metadata gives consistent discoverability across palette,
  bindings, footer and help.

### Trade-offs

- Requires an incremental composition extraction (TUI-02) before broad UI work.
- Adds a Textual dependency and a headless/real-terminal test strategy.
- The TUI track delays Stage 13 until its completion/integration gate passes.

## Supersedes

Nothing. This ADR adds the accepted TUI direction; it does not change the
Stage-12 Campaign State decision (`docs/adr/0007-…`).

## References

- `docs/stages/TUI_TEXTUAL_PRESENTATION_TRACK.md` — dependency-ordered track
  plan/history/evidence (`TUI-00` … `TUI-06`).
- `docs/development/project-invariants.md` — durable presentation-layer
  invariants.
- `AGENTS.md` — always-on trust boundary and development discipline.
