---
apply: ALWAYS
mode: ALL
---
# Core architecture

- Treat the Obsidian Vault as the only canonical campaign Source of Truth.
- Python is the trusted layer for domain logic, validation, filesystem operations, calendar, retrieval and tool execution.
- LLMs are replaceable interpretation/reasoning components, not storage, trusted parsers or filesystem operators.
- Domain/storage code must not import or depend on Ollama or concrete model implementations.
- Derived stores such as SQLite FTS, caches and embeddings must always be rebuildable from canonical Vault/raw data.
- Preserve the dependency order defined in `GIGACODE.md`.
- Prefer the smallest implementation that preserves these boundaries.
