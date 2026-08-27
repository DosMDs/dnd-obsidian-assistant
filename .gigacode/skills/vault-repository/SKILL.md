---
name: vault-repository
description: Implement or review VaultRepository, Markdown/YAML parsing, entity persistence, atomic writes, path safety, revisions, locking or audit behavior.
compatibility: Python 3.12+, pathlib, ruamel.yaml, pytest.
metadata:
  version: "1"
---
# Vault repository development

1. Treat Vault files as canonical human-editable data.
2. Inspect the exact Markdown/YAML round-trip behavior before changing serialization.
3. Enforce Vault-root containment and reject traversal.
4. Preserve user Markdown body and unrelated YAML where contractually required.
5. Use stable IDs and revision checks.
6. For writes, use temporary output, validation and atomic replacement.
7. Ensure failures leave the previous canonical file valid.
8. Emit audit data through the designated audit abstraction.
9. Add integration tests using a real temporary Vault.
10. Include regression tests for conflicts, malformed YAML, path traversal and interrupted/failed writes when relevant.
