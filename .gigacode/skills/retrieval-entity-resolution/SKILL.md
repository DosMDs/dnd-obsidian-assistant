---
name: retrieval-entity-resolution
description: Implement or review exact/fuzzy/FTS retrieval, aliases, SearchService or EntityResolver behavior, especially ambiguous entity handling.
compatibility: Python 3.12+, RapidFuzz, SQLite FTS5, pytest.
metadata:
  version: "1"
---
# Retrieval and entity resolution

Use this precedence unless the existing contract intentionally differs:

1. exact stable ID;
2. exact alias/name;
3. fuzzy name match;
4. entity type/filter;
5. lexical SQLite FTS5;
6. semantic search only after explicit future approval.

Rules:
- SQLite is derived and rebuildable.
- EntityResolver returns explicit resolved/ambiguous/not-found outcomes.
- A low-confidence candidate must not become a speculative write.
- Recent context may rank candidates but must not bypass deterministic safety checks.
- Add negative and ambiguity tests, not only successful-match tests.
