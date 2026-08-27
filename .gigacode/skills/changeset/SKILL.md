---
name: changeset
description: Implement or review ChangeSet proposal, validation, review, conflict detection or apply logic for post-session model-generated campaign updates.
compatibility: Python 3.12+, Pydantic, pytest.
metadata:
  version: "1"
---
# ChangeSet development

Follow the lifecycle:

`PROPOSE -> VALIDATE -> REVIEW -> COMMIT`

1. Model-generated updates create proposals, not direct canonical writes.
2. Validate entity existence, expected revision, allowed transition, old/new values and duplicate/conflicting operations.
3. Use the same safe repository/domain write paths as manual operations.
4. Keep review human-readable and explicit about risky changes.
5. Apply operations in a way that preserves Vault validity on failure.
6. Never silently bypass revision conflicts.
7. Add tests for duplicates, conflicts, stale revisions, partial failures and invalid transitions.
