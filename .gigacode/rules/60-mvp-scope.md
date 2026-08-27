---
apply: ALWAYS
mode: ALL
---
# MVP scope guard

MVP includes:
- Python 3.12+ / uv;
- Typer + Rich CLI;
- NPC, location, quest and item entities;
- sessions and raw JSONL logging;
- safe Vault read/write;
- exact/fuzzy/SQLite FTS search;
- generic deterministic calendar;
- Ollama ModelGateway;
- fast agent with a limited Tool Registry;
- post-session processing;
- Summary and Recap;
- ChangeSet review/apply;
- existing-campaign bootstrap;
- pytest and basic model evals.

Do not add before demonstrated need:
- vector DB or embeddings;
- LoRA/fine-tuning infrastructure;
- voice/audio pipeline;
- web/mobile UI;
- graph DB;
- multi-user server;
- DM mode;
- combat/rules engine;
- threat clocks;
- complex RAG framework.
