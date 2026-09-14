---
name: changeset
description: Design, implement or review future post-session ChangeSet proposal, validation, human review, conflict detection and safe application.
---
# ChangeSet

Read [current status](../../../DEVELOPMENT_STATUS.md), the applicable stage/ADR and existing domain/repository revision contracts. Stage 10 authorization is required for implementation while it remains deferred. This skill does not make existing authorized session-time writes depend on ChangeSet.

Use proposal → validate → review → apply (legacy COMMIT means applying campaign changes, not Git commit). Model output creates proposals, never direct canonical mutations. Validate entity existence, expected revision, allowed transition, exact old/new values, duplicates and conflicting operations.

Keep review human-readable and explicit about risky changes. Apply through the same trusted domain/repository write paths as manual operations, preserving Vault validity on partial failure. Do not silently bypass stale revisions or infer approval from a generated proposal.

Evidence must include duplicates, conflicts, stale revisions, invalid transitions and partial/interrupted application using temporary data. Stop for ambiguous targets, unavailable review authorization, incompatible schema migration or out-of-stage implementation. Use [vault-repository](../vault-repository/SKILL.md) and [quality policy](../../../docs/development/quality-and-evidence.md) for persistence/failure evidence.
