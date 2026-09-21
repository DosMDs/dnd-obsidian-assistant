# TUI real-terminal smoke protocol

Repeatable **manual** protocol for the Textual TUI real-terminal matrix. This is
supplementary manual evidence for platform/terminal behavior that headless
`App.run_test()` / `Pilot` tests cannot prove (bracketed paste, real key
delivery, emulator rendering). Headless tests remain the semantic-correctness
strategy; this protocol never substitutes for them, and headless/synthetic-paste
results are never reported as real-terminal evidence.

## Classification

```text
Windows Terminal actually executed by a human           MANUAL
Windows Terminal not executed                           SKIPPED_CAPABILITY
macOS terminal / iTerm actually executed by a human     MANUAL
macOS not available                                     SKIPPED_CAPABILITY
```

A skipped platform is a capability skip, never verified coverage.
`py3-none-any`, headless Windows tests, documentation and CI without an
interactive terminal do **not** verify macOS.

## Fixture (never use a personal Vault)

1. Copy the canonical fixture to a disposable location:

   ```text
   tests/fixtures/golden_test_vault/  ->  <temp>/tui-smoke-vault/
   ```

2. Create a disposable model config `<temp>/tui-smoke-config.toml` with a local
   profile of role `agent` (`AGENT`). A real successful Ollama inference is not
   required: the assistant submit checks may terminate through the expected
   model-error path (a Russian categorized message), because this protocol
   validates terminal/UI behavior, not model quality.
3. Run against the copy only:

   ```text
   uv run dnd tui --vault <temp>/tui-smoke-vault --config <temp>/tui-smoke-config.toml --profile <name>
   ```

4. Discard the copy and config afterward. Do not modify the canonical fixture.

## Protocol

Record each item literally (pass/fail + observation).

```text
Environment
  OS + version
  terminal emulator + version
  Python version
  Textual version

Startup / shutdown
  app starts, header/sidebar/footer render
  idle quit via ctrl+q exits cleanly, terminal restored

Layout
  assistant transcript + composer on the left, campaign sidebar on the right
  composer sits at the bottom of the assistant pane (not under the sidebar)

Ctrl+Enter (critical)
  Enter inserts a newline (does not submit)
  Ctrl+Enter submits assistant.submit exactly once and leaves no newline
  Send button submits assistant.submit exactly once
  f5 submits assistant.submit exactly once (portable fallback)
  record explicitly whether the terminal delivers ctrl+enter distinctly from enter;
  if not, this is a terminal capability limitation, not an app defect

Unicode / Cyrillic
  type Cyrillic into the assistant composer
  type Cyrillic into the session note field (session screen)
  Cyrillic renders in the sidebar Campaign-State content

Paste
  paste a single-line Cyrillic string into the session note (accepted)
  paste a multiline string into the session note (rejected with Russian warning, value unchanged)
  paste a multiline literal ID list into touched IDs (normalized to spaces)
  paste multiline Cyrillic into the assistant composer (preserved)
  paste a string containing "?" into the assistant composer (no help dispatch)

Assistant
  explicit submit via the button, the command palette, Ctrl+Enter and the f5 alias (each exactly once)
  Tab moves focus out of the composer
  a draft typed while a submission is running survives completion

Navigation / focus
  F3 opens the session screen; F2 (or Escape) returns to the assistant workspace
  the sidebar "Открыть сессию…" button opens the session screen
  repeated F3 does not stack duplicate session screens
  ctrl+p opens the command palette; closing it restores the previous focus
  ? opens help; closing it restores the previous focus

Resize
  wide -> narrow -> wide; no crash
  transcript content retained, focus retained, active screen retained
  sidebar stays visible down to the 60x20 minimum, hidden below it (degraded)
  action rows stack at narrow widths; all controls reachable

Deterministic write path (on the disposable copy)
  session start, note, end (session screen)
  sidebar session summary converges after start/end
  Campaign-State reload/rebuild (sidebar)

Error presentation (without a real model where practical)
  expected error shows a Russian categorized message; input retained
  busy-operation quit is refused
```

## Result template

```text
status:            MANUAL | SKIPPED_CAPABILITY
platform:          <OS / terminal / version>
python/textual:    <versions>
items:             <pass/fail per group with observations>
notes:             <terminal-specific caveats, e.g. f5 interception>
```

## Known limitations

- The program cannot prevent terminal-window kill, OS process kill,
  SIGKILL-equivalent termination or machine shutdown; only normal in-app
  shutdown paths are hardened.
- `f5` submission is a convenience alias, not a cross-platform guarantee; the
  authoritative submit surfaces are Ctrl+Enter, the button and the command
  palette, with F5 as the portable fallback.
- `Ctrl+Enter` is a hard product requirement. Pinned Textual 8.2.8 requests the
  Kitty keyboard-protocol disambiguation flag on start on both the Windows
  driver (`\x1b[>1u`) and the POSIX/linux driver, so a protocol-honoring
  terminal delivers it distinctly. Headless tests prove the app dispatch; the
  terminal **delivery** must be observed here and is never inferred from
  headless tests. If a terminal cannot distinguish it, report the limitation
  explicitly instead of claiming the criterion PASS via F5/the button.
