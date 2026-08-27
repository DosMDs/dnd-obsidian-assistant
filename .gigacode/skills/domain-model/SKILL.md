---
name: domain-model
description: Design or modify Pydantic/domain schemas, entity types, session/event models, IDs, provenance, visibility, knowledge status or revisions. Use for domain schema and validation tasks.
compatibility: Python 3.12+, Pydantic.
metadata:
  version: "1"
---
# Domain model development

1. Confirm the domain concept belongs in the current MVP/roadmap.
2. Prefer deterministic domain types with no provider/storage dependency.
3. Keep stable IDs independent from filenames and display names.
4. Model visibility, epistemic state, provenance and revision explicitly when relevant.
5. Separate canonical data from derived views/cache fields.
6. Define validation invariants in Python, not prompts.
7. Add unit tests for valid, invalid and boundary cases.
8. If persistence format changes, identify migration implications but do not silently implement migrations.
