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
  app starts, header/tabs/footer render
  idle quit via ctrl+q exits cleanly, terminal restored

Unicode / Cyrillic
  type Cyrillic into the assistant composer
  type Cyrillic into the session note field
  Cyrillic renders in Campaign-State content

Paste
  paste a single-line Cyrillic string into the session note (accepted)
  paste a multiline string into the session note (rejected with Russian warning, value unchanged)
  paste a multiline literal ID list into touched IDs (normalized to spaces)
  paste multiline Cyrillic into the assistant composer (preserved)
  paste a string containing "?" into the assistant composer (no help dispatch)

Assistant
  Enter inserts a newline (does not submit)
  explicit submit via the button, the command palette, and the f5 alias (each exactly once)
  Tab moves focus out of the composer

Navigation / focus
  F2/F3/F4 switch tabs and focus the primary control
  ctrl+p opens the command palette; closing it restores the previous focus
  ? opens help; closing it restores the previous focus

Resize
  wide -> narrow -> wide; no crash
  active tab retained, content retained, focus retained
  action rows stack at narrow widths; all controls reachable

Deterministic write path (on the disposable copy)
  session start, note, end
  Campaign-State inspect/rebuild

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
  authoritative submit surfaces are the button and the command palette.
