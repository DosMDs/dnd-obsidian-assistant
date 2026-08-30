"""AuditService — append-only audit logging for Vault operations.

Responsibility
──────────────
Owns: audit log storage and query.
Must not own: entity data, validation, business rules.
Called by: storage layer, application layer.
Failure boundary: raises StorageError on write failure.

Stage 3 ownership
─────────────────
The typed AuditService API and AuditRecord schema are owned by Stage 3
(Vault Repository).  The concrete implementation belongs to S3-04.

Stage 1 and S3-00 inventory the responsibility boundary only — no
executable signatures are defined here.
"""
