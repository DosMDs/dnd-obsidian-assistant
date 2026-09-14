---
name: domain-model
description: Design or review domain/Pydantic schemas for entities, sessions, events, stable IDs, provenance, visibility, knowledge status and revisions.
---
# Domain models

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 2](../../../docs/stages/02_DOMAIN_SCHEMAS.md), existing schemas and serialization/consumer tests. Confirm the concept belongs in the authorized stage/MVP.

Define deterministic typed contracts in domain with no provider/storage dependency. Keep identity independent from filename/display name. Model visibility, epistemic state, provenance and revisions explicitly when relevant; separate canonical fields from derived views/cache data. Validation belongs in Python rather than prompts.

Inspect accepted strictness, extra-field handling, enums and public errors before changing a schema. Test valid, invalid and boundary cases, including Cyrillic and the applicable structural/numeric classes from [quality policy](../../../docs/development/quality-and-evidence.md). Verify affected consumers and serialized compatibility.

Common failures are accidental coercion, bool accepted as an integer, renamed IDs and provider-specific types leaking inward. If persistence format changes, report migration implications; do not silently implement migrations. Stop for unrelated stage scope, unresolved contract ownership or required architecture weakening.
