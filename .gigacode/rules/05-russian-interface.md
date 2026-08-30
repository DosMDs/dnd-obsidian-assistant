---
apply: ALWAYS
mode: ALL
---
# Russian-only user interface

- The user-facing application interface is Russian-only for the MVP.
- All application-owned CLI/TUI help text, prompts, confirmations, status messages, warnings and user-facing error messages must be written in Russian.
- Do not add a language selector, locale setting, translation catalog or other i18n framework unless the user explicitly expands the product scope later.
- Campaign-facing text must be stored and processed as UTF-8 and must fully support Cyrillic.
- Do not impose ASCII-only validation on human-readable campaign content or stable identifiers unless a separate canonical contract explicitly requires it.
- Internal Python identifiers, module/file names, enum member names and serialized machine-readable enum values may remain English.
- Literal commands, flags, technical identifiers, provider/product names and standards may remain in their canonical technical form when shown to the user.
- Runtime LLM output intended for the user must be requested in Russian unless a later explicit requirement overrides this rule.
