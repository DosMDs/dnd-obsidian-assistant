---
apply: ALWAYS
mode: AGENT
---
# Storage and data integrity

For any code that can modify campaign data:

- Stable entity IDs must not depend on filenames.
- Preserve user-authored Markdown body when changing YAML/frontmatter.
- Normalize and validate paths; reject traversal outside the allowed Vault root.
- Use atomic write semantics: temporary file, validation, then atomic replacement.
- Use optimistic concurrency through entity/session revisions where required.
- Record provenance for automatically extracted knowledge.
- Respect visibility and knowledge status in repository/query paths.
- Record application writes in audit logs.
- Raw session JSONL is append-only; after session end it is immutable.
- Never make post-session model output write directly to canonical entity files; use ChangeSet.
- Never silently resolve ambiguous entities for write operations.
