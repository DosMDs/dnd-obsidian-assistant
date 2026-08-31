# Stage 5 — Retrieval + Entity Resolution

## Objective

Establish the retrieval and entity-resolution layer with canonical typed
contracts, then implement exact, fuzzy, and FTS-based search with explicit
resolved/ambiguous/not-found resolution outcomes.

## Tasks

- [x] `S5-00` Retrieval kickoff + canonical contracts
- [x] `S5-01` Exact ID/name/alias retrieval + player-visibility enforcement
- [x] `S5-02` Fuzzy name retrieval + entity-type filtering/ranking
- [x] `S5-03` SQLite FTS5 derived index + rebuild path
- [x] `S5-04` EntityResolver resolved/ambiguous/not-found behavior
- [x] `S5-05` Golden-Vault integration + retrieval/resolver hardening
- [x] `S5-06` Full Stage 5 historical review / verification / status

## Definition of Done

- retrieval-layer public types/contracts are explicit and tested (S5-00)
- exact ID/name/alias retrieval works with player-visibility filtering (S5-01)
- fuzzy name retrieval works with entity-type filtering (S5-02)
- SQLite FTS5 index is rebuildable from Vault (S5-03)
- EntityResolver produces explicit resolved/ambiguous/not-found outcomes (S5-04)
- golden Vault integration tests exist (S5-05)
- full Stage 5 verification complete (S5-06)
- no Stage-6+ work pulled forward

## Implementation history

### S5-00 — Retrieval kickoff + canonical contracts

**Review range:** `06adf01..0f3b986` (S4-05 completion through S5-00)

**Implementation:**
1. `src/dnd_assistant/retrieval/types.py` — `MatchKind`, `SearchQuery`,
   `SearchHit`, `Resolved`, `Ambiguous`, `NotFound`, `ResolutionOutcome`
2. `src/dnd_assistant/retrieval/service.py` — `SearchService` and
   `EntityResolver` Protocols
3. `tests/unit/test_retrieval_contracts.py` — 57 tests

**Quality-gate results:**
- `uv run pytest tests/unit/test_retrieval_contracts.py` — 57 passed
- `uv run pytest` (full suite) — 1556 passed, 34 skipped

---

### S5-C00 — Contract semantics/model validation/boundaries

**6 defects corrected:**

| Defect | Fix |
|---|---|
| C00-1 | Boundary tests replaced with real `sys.modules`-based + AST-based import analysis |
| C00-2 | `Ambiguous(candidates=[])` allowed — added `@model_validator` rejecting empty candidates |
| C00-3 | `SearchHit` score rules documented but not enforced — added `@model_validator` |
| C00-4 | `search_by_type` returned `SearchHit` without valid `MatchKind` — removed from Protocol |
| C00-5 | Player-visibility wording implied privileged escape hatch — reworded |
| C00-6 | S5-00 was `[ ]` despite having completion record — changed to `[x]` |

**Test count:** 100 tests (was 57), all passed

---

### S5-C01 — Dependency boundary verification fix

**Defect:** `_ast_imports()` used `.split(".")[0]`, collapsing dotted imports
to first segment. Forbidden imports like `from dnd_assistant.storage import X`
were represented as `dnd_assistant` and bypassed detection.

**Fix:** Removed `.split(".")[0]` from import collection. Added
`_has_forbidden_prefix()` with prefix-aware matching.

**Tests added:** 17 tests in `TestAstImportChecker`

**Test count:** 117 passed (was 100)

---

### S5-C02 — Relative-import boundary handling

**Defect:** AST import checker did not handle relative `ImportFrom` nodes
(`node.level` was ignored).

**Fix:** Added `_resolve_relative_import()` and `_parse_imports_from_source()`
shared helpers.

**Tests added:** 7 relative-import regression tests

**Test count:** 124 passed (was 117)

---

### S5-C03 — ImportFrom alias gap

**Defect:** `from dnd_assistant import storage` produced only `{"dnd_assistant"}`,
not `{"dnd_assistant", "dnd_assistant.storage"}`.

**Fix:** Added `_add_qualified_aliases()` helper.

**Tests added:** 9 alias-gap regression tests

**Test count:** 133 passed (was 124)

---

### S5-C04 — Retrieval semantic documentation cleanup

**3 defects corrected:**
- C04-1: FTS score docstring prematurely described negative-float ranking
- C04-2: Ambiguous docstring implied "multiple candidates" (single fuzzy is also ambiguous)
- C04-3: S5-00 canonical summary still described removed `search_by_type()`

**Tests added:** 17 targeted pytest cases

**Test count:** 160 passed

---

### S5-01 — Exact ID/name/alias retrieval

**Starting SHA:** `fa7b48cde28486cd2fb737b8c5f1a0b534327a1b`

**Scope implemented:**
Exact stable-ID, exact canonical name, and exact alias retrieval with
player-visibility enforcement, entity-type filtering, deterministic ordering,
strict limit validation, and repository error propagation.

**Concrete SearchService implementation:**
`VaultSearchService` in `dnd_assistant.retrieval.search` — depends on
`VaultRepository` (injected).

**Match-tier precedence:** `EXACT_ID > EXACT_NAME > EXACT_ALIAS`

**Exact-name normalisation:** `strip → NFC → casefold`

**Tests added:** 58 tests in `tests/unit/test_exact_search.py`

**Full pytest:** 1709 passed, 34 skipped

---

### S5-C05 — Alias parsing hardening

**2 defects:**
1. `_extract_aliases()` called `strip()` before `isprintable()` — control chars
   like `\t`, `\n`, `\r` were stripped first, then remaining printable text passed
2. Stale top-level status header said "Stage 4 — Calendar / DONE"

**Fix:** Reordered validation: `isinstance(str)` → `isprintable()` → `strip()` → non-empty

**Tests added:** 5 regression tests

**Full pytest:** 1714 passed, 34 skipped

---

### S5-02 — Fuzzy name retrieval

**Starting SHA:** `c8504f69779d3c05a590eaaa36ec0097612224b7`

**Scope implemented:**
Fuzzy canonical-name retrieval using RapidFuzz `fuzz.ratio` with entity-type
filtering, player-visibility enforcement, deterministic ranking, and strict
limit validation.

**Tier precedence:** `EXACT_ID > EXACT_NAME > EXACT_ALIAS > FUZZY_NAME`

**No resolver threshold:** All positive finite scores remain candidates

**Tests added:** 31 tests in `tests/unit/test_fuzzy_search.py`

**Full pytest:** 1746 passed, 34 skipped

---

### S5-03 — SQLite FTS5 derived index

**Starting SHA:** `c8504f69779d3c05a590eaaa36ec0097612224b7`

**Scope implemented:**
SQLite FTS5 derived lexical index with rebuild path, source-fingerprint
freshness protection, atomic rebuild, FTS query literalization, player-only
indexing, and integration into `VaultSearchService` tiered search.

**Key design:**
- `retrieval/lexical.py` — `LexicalIndex` protocol + `LexicalHit` dataclass
- `retrieval/index.py` — `SqliteFtsIndex` using stdlib `sqlite3` with FTS5
- Canonical index location: `<vault>/_system/indexes/entities.sqlite3`
- FTS5 tokenizer: `unicode61`
- Source fingerprint: SHA-256 over canonical JSON of player-visible snapshot
- Atomic rebuild: temp → validate → `os.replace`
- Literal FTS query policy: tokenise → quote → AND

**Tier precedence:** `EXACT_ID > EXACT_NAME > EXACT_ALIAS > FUZZY_NAME > FTS`

**CLI command:** `dnd index rebuild --vault <PATH>`

**Tests added:** 56 + 11 + 5 tests

**Full pytest:** 1822 passed, 34 skipped

---

### S5-C06 — FTS index contract/path safety

**7 defects corrected:**

| Defect | Fix |
|---|---|
| C06-1 | `LexicalIndex` Protocol missing `verify_freshness()` — added |
| C06-2 | Fingerprint included DM/SYSTEM documents — filtered to PLAYER only |
| C06-3 | FTS eligibility after SQLite LIMIT consumed result slots — request `max(player_count, limit)` |
| C06-4 | CLI used positional `vault` argument — changed to `--vault` option |
| C06-5 | Symlink checks missed dangling/broken symlinks — added `_reject_symlink()` |
| C06-6 | sqlite→StorageError used `from None` — fixed `from exc` with cause |
| C06-7 | `LexicalHit.score` docstring provider-specific — corrected to generic wording |

**Full pytest:** 1834 passed, 40 skipped

---

### S5-C07 — Runtime FTS path safety

**2 defects:**
1. Symlink/path validation only at construction time — added `_validate_current_index_path()`
2. `verify_freshness()` did not validate schema compatibility — added `_verify_index_fresh()` call

**Full pytest:** 1839 passed, 51 skipped

---

### S5-C08 — Late rebuild race

**2 defects:**
1. Late rebuild validation checked only final filename — replaced with full `_validate_current_index_path()`
2. Late validation outside temp-cleanup try/except — restructured for shared cleanup

**Full pytest:** 1839 passed, 56 skipped

---

### S5-C09 — Parent-race regression

**3 defects:**
1. Parent-directory tests used `rmdir()` on non-empty directory — replaced with `rename()`
2. Temp-cleanup assertion inspected symlink target instead of moved original — corrected
3. S5-C08 claimed guaranteed temp cleanup on parent relocation — corrected to best-effort

**Full pytest:** 1839 passed, 56 skipped

---

### S5-04 — Deterministic entity resolver

**Starting SHA:** `03f5bb7048064f81bb7eb744abfbda0fa3281716`

**Scope implemented:**
`SearchEntityResolver` in `src/dnd_assistant/retrieval/resolver.py` —
deterministic resolver converting free-text references into explicit outcomes.

**Resolution policy:**
- Single `EXACT_ID`/`EXACT_NAME`/`EXACT_ALIAS` → `Resolved`
- Duplicate exact-name/alias → `Ambiguous`
- Single or multiple fuzzy/FTS → `Ambiguous` (no numeric threshold)
- Zero candidates → `NotFound`

**Tests added:** 37 tests in `tests/unit/test_entity_resolver.py`

**Full pytest:** 1877 passed, 56 skipped

---

### S5-C10 — Resolver validation translation

**2 defects:**
1. `Resolved` docstring implied "one candidate = Resolved" — corrected
2. Input validation caught `(ValueError, ValidationError)` without explicit Pydantic type — fixed

**Tests added:** 5 parametrized validation-cause tests

**Full pytest:** 1882 passed, 56 skipped

---

### S5-05 — Golden-Vault integration

**Starting SHA:** `c640d73692989d323ab87afa3a56cf46409430a1`

**Golden fixture source:** `tests/fixtures/golden_test_vault/`
**MVP entity count:** 23 (10 NPC + 5 Location + 3 Quest + 5 Item)
**Player-visible:** 22 (1 DM entity: npc_archivist_kell)

**Real concrete stack composed:**
```
golden_vault_root (tmp_path copy)
    → AuditService
    → ObsidianVaultRepository
    → SqliteFtsIndex
    → VaultSearchService (with/without FTS)
    → SearchEntityResolver (with/without FTS)
```

**Key results:**
- Exact-ID: `npc_varos` → 1 EXACT_ID hit
- Alias-collision: `Варос` with `entity_types={NPC}` → 2 EXACT_ALIAS hits
- DM visibility: `npc_archivist_kell` never appears in player results
- FTS: `S005` → FTS hits, resolver returns `Ambiguous`
- Freshness: DM-only mutation does not stale player index

**Production code changed:** No
**Production defect discovered:** None

**Tests added:** 58 tests in `tests/integration/test_retrieval_golden_vault.py`

**Full pytest:** 1940 passed, 56 skipped

---

### S5-C11 — Golden retrieval regression strengthening

**2 defects:**
1. Resolver alias-collision test used set assertion, losing candidate order — fixed to exact sequence
2. Fuzzy no-threshold test only asserted `> 0.0` — replaced with exhaustive independent calculation

**Production code changed:** No

**Full pytest:** 1940 passed, 56 skipped (unchanged count)

---

### S5-06 — Stage 5 completion

**Review date:** 2026-08-31

**Pre-Stage-5 base SHA:** `06adf016bacb0103736b7ecc7f723df2224d8773`
**Implementation review-head SHA:** `a1247eb7dfa496ed6cab39ff9f08e9b8ddbe7ae4`
**Historical review range:** `06adf016..a1247eb`

**Commit count:** 22

**Full commit inventory:**

```
0f3b986  feat: establish retrieval-layer canonical contracts (S5-00)
ee086a3  docs: add S5-00 completion record to development status
7fde172  fix: correct retrieval contracts and boundary tests (S5-C00)
bf68b45  test: fix retrieval dependency boundary verification (S5-C01)
a933b90  docs: record S5-C01 commit SHA in development status
bb86a39  test: handle relative imports in retrieval boundary checks (S5-C02)
2dce8a0  test: close retrieval ImportFrom boundary gap (S5-C03)
fa7b48c  docs: align retrieval contract semantics (S5-C04)
09cc649  feat: implement exact entity retrieval (S5-01)
c75d77e  fix: harden exact alias parsing and stage status (S5-C05)
c8504f6  feat: add fuzzy entity name retrieval (S5-02)
f99fe05  feat: add rebuildable SQLite FTS5 derived index (S5-03)
c1a5ecb  fix: harden FTS index contracts and safety (S5-C06)
cf8e232  fix: finalize FTS runtime path safety (S5-C07)
26c6228  fix: close late FTS rebuild race (S5-C08)
03f5bb7  test: correct late FTS parent-race regression (S5-C09)
1ad2a38  feat: add deterministic entity resolver (S5-04)
052d36f  update gigacode rules
9e274a2  docs: harden GigaCode incremental edit policy
c640d73  fix: align entity resolver validation contract (S5-C10)
7a91159  test: harden retrieval with Golden Vault integration (S5-05)
a1247eb  test: strengthen Golden retrieval regressions (S5-C11)
```

**Commit classification:**
- 20 Stage-5 implementation/correction/test/documentation commits
- 2 concurrent development-workflow policy commits

**Production files reviewed:**
- `src/dnd_assistant/retrieval/__init__.py`
- `src/dnd_assistant/retrieval/types.py`
- `src/dnd_assistant/retrieval/service.py`
- `src/dnd_assistant/retrieval/search.py`
- `src/dnd_assistant/retrieval/lexical.py`
- `src/dnd_assistant/retrieval/index.py`
- `src/dnd_assistant/retrieval/resolver.py`
- `src/dnd_assistant/cli/main.py`

**Test files reviewed:**
- `tests/unit/test_retrieval_contracts.py` — 160 tests
- `tests/unit/test_exact_search.py` — 63 tests
- `tests/unit/test_fuzzy_search.py` — 31 tests
- `tests/unit/test_fts_index.py` — 70 passed, 22 skipped
- `tests/unit/test_fts_search.py` — 12 tests
- `tests/unit/test_entity_resolver.py` — 42 tests
- `tests/unit/test_cli_index.py` — 5 tests
- `tests/integration/test_retrieval_golden_vault.py` — 58 tests

**Correction mapping C00-C11:**

| Correction | Intent | Verified |
|---|---|---|
| S5-C00 | Contract semantics/model validation/boundaries | PASS |
| S5-C01 | Dependency boundary verification | PASS |
| S5-C02 | Relative-import boundary handling | PASS |
| S5-C03 | ImportFrom alias gap | PASS |
| S5-C04 | Retrieval semantic documentation | PASS |
| S5-C05 | Alias parsing hardening | PASS |
| S5-C06 | FTS index contract/path safety | PASS |
| S5-C07 | Runtime FTS path safety | PASS |
| S5-C08 | Late rebuild race | PASS |
| S5-C09 | Parent-race regression | PASS |
| S5-C10 | Resolver validation translation | PASS |
| S5-C11 | Golden resolver ordering + no-threshold proof | PASS |

**Architecture-boundary result:** PASS — domain/storage do not import retrieval;
retrieval contracts do not import models/tools/application/session/ollama.

**Source-of-truth result:** PASS — Obsidian Vault is the only canonical source;
SQLite FTS is derived storage only, fully disposable and rebuildable.

**Visibility result:** PASS — DM/SYSTEM entities excluded from all retrieval
tiers. Golden Vault confirms npc_archivist_kell never appears in player results.

**Exact search result:** PASS — EXACT_ID (literal), EXACT_NAME
(strip→NFC→casefold), EXACT_ALIAS. Tier precedence: EXACT_ID > EXACT_NAME >
EXACT_ALIAS.

**Fuzzy search result:** PASS — canonical name only, strip→NFC→casefold,
rapidfuzz.fuzz.ratio, score > 0.0, no arbitrary cutoff.

**FTS index/result:** PASS — SQLite FTS5, player-visible only, bm25 ranking,
source fingerprint, atomic rebuild, stale/missing/corrupt detection.

**FTS path/race-safety result:** PASS — symlink rejection, operation-time
revalidation, late pre-replace validation, temp cleanup.

**Resolver result:** PASS — deterministic, LLM-free. 0 candidates → NotFound,
1 exact → Resolved, 1 fuzzy/FTS → Ambiguous, 2+ → Ambiguous.

**Golden Vault result:** PASS — 58 integration tests pass against real stack.

**Stage-boundary result:** PASS — no Stage-6+ functionality pulled forward.

**Full gate results:**
- `uv run pytest` — 1940 passed, 56 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 183 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Golden fixture cleanliness:** PASS — `git diff -- tests/fixtures/golden_test_vault` empty.

**Stage 5 status:** DONE
**Stage 5 completion date:** 2026-08-31
**Stage 6 status:** NOT STARTED