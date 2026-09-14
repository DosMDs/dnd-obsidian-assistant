---
name: session-runtime
description: Implement or review deterministic session lifecycle, raw JSONL notes/events, touched entities, end-state persistence and recovery.
---
# Session runtime

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 6](../../../docs/stages/06_SESSION_RUNTIME_WITHOUT_LLM.md), accepted session metadata/event/recovery contracts and repository tests. Keep the lifecycle deterministic and independent of a model.

Start through trusted services to create identity/metadata and raw log locations. Append events as JSON Lines without rewriting earlier events. End persists the accepted end tick/timestamp/touched-entity metadata and processing-pending state through the appropriate repository; do not add fields to unrelated domain schemas to mimic an obsolete plan.

Closed raw data is immutable input to later processing. Crashes and partial starts/closes must not corrupt existing data. Inspect accepted recovery ownership before changing repair behavior; recovery is not a license to rewrite canonical history for convenience.

Use temporary-Vault integration evidence for start → note/event → end, invalid transitions, restarts and interrupted operations. Verify revision/audit failure paths and immutable closed logs. Stop for unsafe repair, new post-session processing/ChangeSet implementation outside stage authorization or real Vault mutation. Use [vault-repository](../vault-repository/SKILL.md) and [quality policy](../../../docs/development/quality-and-evidence.md).
