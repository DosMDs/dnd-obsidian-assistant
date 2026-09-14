---
name: retrieval-entity-resolution
description: Implement or review exact, alias, fuzzy and FTS search and deterministic resolved/ambiguous/not-found entity resolution.
---
# Retrieval and entity resolution

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 5](../../../docs/stages/05_RETRIEVAL_AND_ENTITY_RESOLUTION.md), actual search/resolver contracts and golden-Vault tests. Existing contract precedence overrides a generic proposed pipeline.

Default precedence: exact stable ID → exact alias/name → fuzzy name → entity type/filter → lexical SQLite FTS5. Semantic search requires future explicit approval. SQLite remains derived/rebuildable; canonical entity and visibility data come from Vault repositories.

Return explicit resolved/ambiguous/not-found results. Recent context may rank candidates but cannot bypass deterministic safety or player-knowledge filtering. Low-confidence candidates must not become speculative write targets. Keep retrieval policy in retrieval/application ownership, not in model prompts or storage shortcuts.

Test successful resolution plus aliases, collisions, ambiguity, missing entities, filters/visibility, index rebuilds and negative write consequences. Common failures are stale indexes gaining authority, fuzzy matches silently authorizing mutation and hidden data leaking in results. Stop for an unresolved write target, a new semantic-search feature outside scope or a changed resolution contract needing architecture review. Apply [quality policy](../../../docs/development/quality-and-evidence.md).
