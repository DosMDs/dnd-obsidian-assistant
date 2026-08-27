---
apply: ALWAYS
mode: ALL
---
# Windows and macOS portability

- Treat Windows and macOS as supported native environments.
- Use `pathlib.Path` instead of manual path concatenation.
- Never commit absolute developer-machine paths.
- Do not require WSL, Bash, GNU utilities or Make.
- Prefer `uv run ...` commands that work the same on both platforms.
- Avoid `shell=True`.
- Use UTF-8 explicitly for project-controlled text files.
- Avoid assumptions about path separators, executable suffixes, case sensitivity and file locking semantics.
- When filesystem behavior is relevant, add a test rather than relying on one OS.
