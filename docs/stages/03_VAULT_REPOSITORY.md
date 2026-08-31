# Stage 3 — Vault Repository

## Objective

Implement the trusted Vault persistence layer for Obsidian Markdown/YAML
entities, providing create, read, update, and append operations with atomic
writes, optimistic concurrency, path safety, Markdown body preservation, and
audit logging.

## Tasks

- [x] `S3-00` Stage kickoff + repository/storage contracts
- [x] `S3-01` Markdown/YAML document codec
- [x] `S3-02` Vault path safety + entity directory/discovery policy
- [x] `S3-03` Atomic write primitive (corrected: symlink, BaseException, validator transparency, lifecycle)
- [x] `S3-04` AuditRecord + AuditService
- [x] `S3-05` create_entity / get_entity / list_entities
- [x] `S3-06` patch_entity + optimistic concurrency
- [x] `S3-07` append_entity_fact
- [x] `S3-08` integration/failure tests (corrected: race safety + mutation-time reauthorization)
- [x] `S3-09` full Stage 3 verification/diff/status

## Definition of Done

- Storage contracts (`VaultDocument`, `EntityDirectory`, `VaultRepository` Protocol)
- Markdown/YAML codec (`parse`, `serialize`)
- Vault path safety and entity discovery (`paths.py`)
- Atomic write primitive (`atomic_write_text`)
- Append-only audit (`AuditRecord`, `AuditContext`, `AuditService`)
- Repository create/read/list (`ObsidianVaultRepository`)
- Optimistic entity patching (`EntityPatch`, `patch_entity`)
- Append entity fact (`append_entity_fact`)
- Integration/failure hardening (race safety, mutation-time reauthorization, stable-target identity)
- No Stage 4 Calendar implementation
- No Retrieval, EntityResolver, Session runtime, Tool layer, ModelGateway, ChangeSet
- Quality gates pass

## Implementation history

### S3-00 — Stage kickoff + storage contracts

**Review range:** `22a21d3..HEAD` (Stage 2 completion through S3-00)

**Changes:**
1. `storage/types.py` (new) — `VaultDocument`, `EntityDirectory`, `VaultRepository` Protocol
2. `storage/__init__.py` — exports EntityDirectory, VaultDocument, VaultRepository
3. `storage/audit.py` — updated docstring for Stage 3 ownership
4. `tests/unit/test_storage_types.py` (new) — 27 tests

**Decisions made:**
- `VaultDocument` lives in `storage/` (not `domain/`)
- Extra frontmatter preserved as `dict[str, object]`
- `VaultRepository` is a `Protocol` (not ABC)
- `EntityDirectory` is a `StrEnum`
- Patch/fact DTOs explicitly deferred

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_types.py` — 27 passed
- `uv run pytest` (full suite) — 578 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 68 files already formatted

---

### S3-01 — Markdown/YAML document codec

**Review range:** S3-00 completion through S3-01

**Changes:**
1. `storage/markdown.py` (new) — `parse()` and `serialize()` for Obsidian Markdown
2. `tests/unit/test_storage_markdown.py` (new) — 71 tests

**Codec API:** `parse(text: str) -> VaultDocument`, `serialize(document: VaultDocument) -> str`

**Key design:**
- Frontmatter delimiter: standalone `---`
- CRLF/LF support; body preservation character-for-character
- Canonical Entity fields via `Entity.model_validate()`
- Extra frontmatter keys stored in `extra_frontmatter`
- Uses `ruamel.yaml` with `typ="safe"`
- All errors translated to `ValidationError`

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_markdown.py` — 71 passed
- `uv run pytest` (full suite) — 652 passed

---

### S3-02 — Vault path safety + entity discovery

**Review range:** S3-01 completion through S3-02 (including correction)

**Changes:**
1. `storage/paths.py` (new) — `DiscoveredEntityFile`, `entity_directory()`, `resolve_entity_path()`, `discover_entity_files()`
2. Symlink hardening correction: `_resolve_entity_directory()` with pre-resolution symlink inspection
3. `tests/unit/test_storage_paths.py` (new) — 56 passed, 10 skipped

**Path safety invariants:**
- Vault root must exist and be a directory
- `..` traversal rejected structurally
- Absolute paths rejected
- Markdown-only suffix enforcement
- Symlinks rejected at canonical directory path components
- Discovery: only MVP entity directories, recursive, no symlink following
- Results deterministically ordered

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_paths.py` — 56 passed, 10 skipped
- `uv run pytest` (full suite) — 714 passed, 10 skipped

---

### S3-03 — Atomic write primitive

**Review range:** S3-02 correction through S3-03

**Changes:**
1. `storage/atomic.py` (new) — `atomic_write_text(target, content, *, validator)`
2. `tests/unit/test_storage_atomic.py` (new) — 36 tests + 1 skipped

**Lifecycle:** `write → flush → fsync → validator → close → os.replace`
**Validator exception semantics:** ANY exception propagates unchanged

**Correction (exception and symlink handling):**
- Dangling symlink rejection (check `is_symlink()` before `exists()`)
- `BaseException` removed, replaced with `finally` cleanup
- Validator exception transparency
- Simplified lifecycle: single `_write_and_fsync` helper

**Quality-gate results (after correction):**
- `uv run pytest tests/unit/test_storage_atomic.py` — 44 passed, 5 skipped
- `uv run pytest` (full suite) — 758 passed, 15 skipped

---

### S3-04 — AuditRecord + AuditService

**Review range:** S3-03 correction through S3-04

**Changes:**
1. `storage/audit.py` (rewritten) — `AuditRecord` schema + `AuditService`
2. `tests/unit/test_storage_audit.py` (new) — 64 passed, 2 skipped

**AuditRecord schema:** schema_version, operation_id, real_time (AwareDatetime),
session, operation, entity_id, before_hash, after_hash, source, model_profile,
prompt_version. `extra="forbid"`, `frozen=True`.

**AuditService API:** `.append(record)`, `.read_all()`, `.log_path`

**Append lifecycle:** `open (append) → write → flush → fsync → close`

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_audit.py` — 64 passed, 2 skipped
- `uv run pytest` (full suite) — 822 passed, 17 skipped

---

### S3-05 — create_entity / get_entity / list_entities

**Review range:** S3-04 completion through S3-05

**Changes:**
1. `storage/audit.py` — added `AuditRecord.phase` field, `AuditContext` model
2. `storage/types.py` — `VaultRepository` Protocol with `audit: AuditContext` parameter
3. `storage/vault_repository.py` (new) — `ObsidianVaultRepository`
4. `tests/unit/test_storage_vault_repository.py` (new) — 51 tests

**Correction (audit-path hardening, EntityId validation, filename symlinks, cause preservation):**
- Audit-path structural traversal rejection
- Canonical EntityId runtime validation via `TypeAdapter(EntityId)`
- Filename symlink collision detection
- Committed-audit cause preservation

**Quality-gate results (after correction):**
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest` (full suite) — 898 passed, 19 skipped

---

### S3-06 — patch_entity + optimistic concurrency

**Review range:** S3-05 correction through S3-06

**Changes:**
1. `storage/patch.py` (new) — `EntityPatch` DTO
2. `storage/types.py` — `patch_entity` signature added to Protocol
3. `storage/vault_repository.py` — `ObsidianVaultRepository.patch_entity`
4. `tests/unit/test_storage_patch.py` (new) — 40 tests
5. `tests/unit/test_storage_patch_repository.py` (new) — 56 tests

**Editable fields:** name, status, visibility, knowledge_status, created_session,
last_seen_session, tags

**Immutable fields:** schema_version, id, type, created_at, updated_at, revision,
body, extra_frontmatter

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_patch.py` — 40 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest` (full suite) — 993 passed, 19 skipped

---

### S3-07 — append_entity_fact

**Review range:** S3-06 completion through S3-07

**Changes:**
1. `storage/vault_repository.py` — fact validation, body fact appender, shared `_commit_entity_mutation`
2. `storage/types.py` — `append_entity_fact` signature with `audit`
3. `tests/unit/test_storage_append_fact.py` (new) — 67 tests

**Fact validation:** non-empty, printable, no leading/trailing whitespace, no embedded newlines/controls
**Markdown rendering:** `"- <fact>"` bullet
**Line-ending policy:** CRLF-aware, never modifies old body

**Correction (CRLF inference defect):**
- Replaced `last_crlf > last_lf` with correct `body[last_lf - 1] == "\\r"` check
- 13 new regression tests

**Quality-gate results (after correction):**
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest` (full suite) — 1070 passed, 19 skipped

---

### S3-08 — Race safety + mutation-time reauthorization

**Review range:** S3-07 correction through S3-08 correction

**Defects corrected:**
1. Create target-occupancy race after durable intent
2. Create duplicate-EntityId race after initial snapshot
3. Mutation-time authorization gap for long-lived filesystem topology
4. Windows symlink skips prevented path-race scenarios from being exercised

**Production changes:**
- `_validate_mutation_environment()` — runtime audit path revalidation
- `_reauthorize_entity_path()` — reauthorizes entity path via `resolve_entity_path`
- Create second pre-write check (after intent, before atomic_write_text)
- Patch/append mutation-time reauthorization

**Final correction (stable-target identity):**
- `_reauthorize_entity_path()` strengthened with `expected_path` parameter
- Exact `Path` equality enforced, not merely containment
- `_StoredEntity.relative_path` derivation hardened

**Quality-gate results:**
- `uv run pytest tests/integration/test_vault_repository_path_races.py` — 9 passed, 15 skipped
- `uv run pytest tests/integration/` — 52 passed, 15 skipped
- `uv run pytest` (full suite) — 1122 passed, 34 skipped

---

### S3-09 — Stage 3 completion

**Review boundary:**
- base: `22a21d3f34e6d3d028c644e4fadc7c7e1dd393a8`
- implementation review head: `f4142483e16a06f0238384fbf103a7826d9881a4`
- range: `22a21d3..f414248`

**Historical classification:**
- 17 Stage-3 implementation/correction commits
- 1 concurrent auxiliary commit (golden test vault)

**Final implemented components:**
- storage contracts (`VaultDocument`, `EntityDirectory`, `VaultRepository` Protocol)
- Markdown/YAML codec (`parse`, `serialize`)
- Vault path safety and entity discovery (`paths.py`)
- Atomic write primitive (`atomic_write_text`)
- Append-only audit (`AuditRecord`, `AuditContext`, `AuditService`)
- Repository create/read/list (`ObsidianVaultRepository`)
- Optimistic entity patching (`EntityPatch`, `patch_entity`)
- Append entity fact (`append_entity_fact`)
- Integration/failure hardening (race safety, mutation-time reauthorization, stable-target identity)

**Final invariants:**
- Source-of-Truth safe Vault persistence
- Stable IDs (EntityId, not filename)
- Revision-based optimistic concurrency
- Markdown body preservation character-for-character
- Extra-frontmatter semantic preservation
- Atomic replacement (temp sibling → fsync → validator → os.replace)
- Append-only audit with intent/committed two-phase lifecycle
- Write-ahead intent before any filesystem mutation
- SHA-256 exact content hashes (before/after)
- Mutation-time path reauthorization (environment + stable-target identity)
- Global duplicate EntityId detection
- Failure/recovery semantics (no mutation before intent, intent remains on failure, no rollback after committed write)

**Quality gates:**
- `uv run pytest tests/contract/test_boundaries.py` — 26 passed
- `uv run pytest tests/unit/test_storage_*.py` — 519 passed, 19 skipped
- `uv run pytest tests/integration/` — 52 passed, 15 skipped
- `uv run pytest` (full suite) — 1122 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Known intentional limitations:**
- No cross-process lock/CAS — residual TOCTOU before final `os.replace`
- Uncertain audit append may leave detectable partial tail
- No automatic audit intent reconciliation/repair
- Symlink tests skipped on Windows without symlink privileges

**Stage 3 status:** DONE.