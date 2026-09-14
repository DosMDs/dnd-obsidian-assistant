---
name: vault-repository
description: Implement or review Vault Markdown/YAML persistence, safe paths, atomic writes, revision conflicts, locking and audit behavior.
---
# Vault repository

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 3](../../../docs/stages/03_VAULT_REPOSITORY.md), actual codec/repository/path/atomic/audit contracts and failure tests. Inspect exact round-trip behavior before changing serialization.

Keep canonical files human-editable. Preserve user Markdown and unrelated YAML as required by the contract. Use stable IDs and optimistic revision checks; reject root escape/traversal and inspect symlink/race semantics at mutation time. Write validated temporary output then atomically replace; emit audit through the designated abstraction. Failure must leave prior canonical data valid.

Exercise real temporary filesystem integration for round trips, malformed YAML, stale revisions/conflicts, path traversal, races, interrupted/failed writes and relevant Windows/macOS locking semantics. Do not substitute mocks for the filesystem property being claimed.

Common failures are whole-document reserialization losing authored text, path validation detached from actual mutation, silent overwrite after a stale revision and audit claims without records. Stop for real Vault access without authorization, irreversible/schema migration outside scope or a safety contract that cannot be preserved. Use [quality policy](../../../docs/development/quality-and-evidence.md); future post-session apply also requires [changeset](../changeset/SKILL.md).
