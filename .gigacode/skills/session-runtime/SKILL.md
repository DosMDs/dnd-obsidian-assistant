---
name: session-runtime
description: Implement or review session start/status/note/event/end behavior, raw JSONL logging, touched entities or session lifecycle.
compatibility: Python 3.12+, pytest.
metadata:
  version: "1"
---
# Session runtime

1. Keep the first useful runtime deterministic and independent of an LLM.
2. On start, create the session identity/metadata and raw log locations through safe services.
3. Append raw events as JSON Lines.
4. Never rewrite prior raw events to make processing easier.
5. On end, close the session, persist end world_tick/timestamp/touched entities and mark processing pending.
6. Treat closed raw session data as immutable input for later processing.
7. Ensure crashes or partial failures do not corrupt existing raw data.
8. Add integration tests for start -> note/event -> end and invalid lifecycle transitions.
