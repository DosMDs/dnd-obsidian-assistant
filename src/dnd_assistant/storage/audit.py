"""AuditService — deferred contract for append-only audit logging.

Responsibility
──────────────
Owns: audit log storage and query.
Must not own: entity data, validation, business rules.
Called by: storage layer, application layer.
Failure boundary: raises StorageError on write failure.

Deferred to Stage 3
────────────────────
The typed AuditService API and audit record schema belong to Stage 3
(Vault Repository). Stage 1 inventories the responsibility boundary only
— no executable signatures are defined here.
"""
