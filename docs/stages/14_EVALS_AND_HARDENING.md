# Stage 14 — Evals / Hardening

**Status:** `IN PROGRESS` (S14-01 … S14-09)
**Accepted baseline:** `main` @ `09fa5690b39bc1b4aeedea4fb98e26fc58c461f3`
**Current task:** `S14-01 — Stage-14 Contract, Status Reconciliation & Golden-Campaign Qualification`

This document is the durable Stage-14 architecture/task/evidence record. Current
roadmap state lives in `DEVELOPMENT_STATUS.md`; this record stores the accepted
Stage-14 contract and per-task evidence, not a pasted plan report.

## 1. Purpose and non-goals

Stage 14 improves confidence in the **already accepted product**. It does not
add unrelated product scope and does not change domain, storage, application or
presentation contracts except where a demonstrated hardening gap requires it.

Non-goals (project scope guard):

```text
no vector DB / embeddings / RAG framework
no LoRA / fine-tuning / voice / web UI / graph DB
no Promptfoo / DeepEval or other heavy eval toolchain
no LLM-as-judge / argument semantic matching
no Node/Bun/TypeScript runtime
```

## 2. S14-00 — accepted planning / architecture investigation

`S14-00` was a read-only, evidence-driven investigation and task decomposition.
It independently verified the accepted `main` baseline, the current eval
surface, the golden fixture, failure-injection coverage, provider/runtime
gates, performance utilities, TUI/cross-platform coverage, Stage-13 regressions
and the documented reliability backlog. Its accepted output is the architecture
contract and decomposition recorded below.

Classification of the existing eval surface:

```text
A  generic reusable deterministic eval logic        tests/support/pydantic_ai_eval.py
B  PAIM migration-specific harness                  tests/support/paim13_*
C  test-only infrastructure (stays test-only)       counting model, in-memory registry, doubles
D  candidate application-owned eval contract        deterministic scoring/metrics/report
E  obsolete historical baggage                      reference-parity comparison (PAIM-RETIRE-01)
```

`PAIM-RETIRE-01` removed the reference Fast Agent runtime and the
`test_pydantic_ai_stage9_live_eval_*` / parity modules. The retired
reference-vs-candidate PAIM-13 comparison is **not** the product-wide eval
architecture; only the deterministic scoring core is reusable.

## 3. Architecture decisions (accepted)

### 3.1 `evals` package ownership

`src/dnd_assistant/evals/` is a dedicated **provider-neutral deterministic
evaluation package**, not campaign/domain/storage logic. Its deterministic
contracts and scoring must not depend on Ollama, Pydantic AI, Textual, Typer,
concrete model providers, or Vault storage. Concrete model/runtime wiring
belongs above it in `composition/` (with the Typer surface in `cli/`).

### 3.2 Artifact and Source-of-Truth classification

```text
eval datasets / expectations   versioned repository source (not campaign truth)
eval observations / reports    derived, disposable, rebuildable artifacts
eval artifact location         OUTSIDE the campaign Vault (no `_system/evals/`)
golden fixture                 read-only regression fixture
live eval data                 synthetic / in-memory only; never the Vault
```

Eval artifacts must never become campaign Source of Truth and must never be
written into the Obsidian Vault.

### 3.3 Offline / live separation

Offline deterministic eval logic, dataset/scoring tests and the scripted-model
runner never require Ollama and run in ordinary `uv run pytest`. Live model
execution is explicit opt-in: absent env/config self-skips **before** any
network access, while set-but-invalid config fails rather than skips. Live
availability must never block deterministic eval or software-test work.

### 3.4 One scoring implementation

There must be one deterministic scoring implementation. S14-02 migrates
consumers directly to `dnd_assistant.evals` and removes obsolete generic
test-only scoring code where clean. A permanent `tests/support` re-export shim
is **not** architecturally required; a temporary compatibility shim is allowed
only if concrete consumers make it necessary.

### 3.5 Component responsibilities

```text
evals/                 pure deterministic contract: dataset schema, observations,
                       scoring, metrics, report serialization (provider-neutral)
composition/evals.py   profile/model selection, candidate runtime, observation
                       collection, derived-artifact output (wiring only)
cli/eval.py            Typer presentation surface (Russian), exit/status semantics
tests                  offline determinism, layer-boundary contracts, opt-in live harness
```

### 3.6 Safety versus quality metrics

```text
SYSTEM SAFETY   unexpected / unauthorized WRITE execution or side effect must be zero
MODEL QUALITY   false_write_tool_call_rate is a critical metric, not an invariant
```

The exact live-baseline threshold and denominator semantics for
`false_write_tool_call_rate` are defined by S14-06/S14-07 together with the
final dataset, not frozen in S14-01.

### 3.7 Naming is provisional

Any `dnd eval dataset|run|report` spelling is provisional. S14-06 owns the exact
CLI contract, dataset loading, model/profile selection, offline vs live
behavior, observation schema, metrics, baseline comparison, report formats,
exit/status semantics and artifact location.

## 4. Golden Vault qualification

`tests/fixtures/golden_test_vault/` is an **immutable regression fixture with
mixed historical/current material**. It is read-only in tests (every consumer
copies to a temporary location). It is not modified in S14-01.

Literal qualification:

```text
103 tracked files
23 entities (10 NPC / 5 locations / 3 quests / 5 items)
5 completed sessions; 20 raw events; 20 timeline events
_system/world_time.json = tick 13800, revision 1
fixture-manifest.json schema_version 1
audit.jsonl empty seed
last functional content change 2026-09-02 (predates Stages 7–13)
```

Historical fixture material (`Campaign/Bootstrap.md`, `Campaign/Current State.md`,
legacy `State/Active Quests.md` / `Active Threads.md` / `Party.md`, and
`Events/*.md`) is **fixture material only**. In particular,
`Campaign/Bootstrap.md` is **not** the accepted Stage-13 bootstrap artifact
contract; Stage 13 deliberately excludes such a canonical document and routes
imported knowledge through reviewed/applied ChangeSets.

No second Vault fixture is created without later concrete evidence. Live evals
use synthetic/in-memory data, not the fixture.

## 5. Gap matrix (summary)

| # | Requirement / invariant | Existing evidence | Gap | Task |
|---|---|---|---|---|
| 1 | Product-owned deterministic eval contract | scoring is test-only (`tests/support`) | no application ownership | S14-02 |
| 2 | Scriptable eval execution surface | no `dnd eval`; `evals/__init__.py` empty | no runner/dataset/report | S14-06 |
| 3 | Product model-eval baseline | PAIM-13 comparison retired | no product-facing dataset/baseline | S14-06/S14-07 |
| 4 | `false_write_tool_call_rate` measured live | metric exists; historical Layer-A obs once invalid | not exercised on current runtime | S14-07 |
| 5 | Full offline scripted-model regression | S13 segments covered separately; runtime bypassed | no single full-sequence path | S14-03 |
| 6 | Golden campaign qualification | manifest/consumers | canonical-vs-historical not recorded | S14-01/S14-03 |
| 7 | Adversarial untrusted input through real tools/paths | ToolExecutor proven with doubles; repository/path safety broad | model-generated input through real registered tools unproven | S14-04 |
| 8 | Provider/runtime upgrade gate | version pin + qualification tests; policy only | no runbook/curated selection | S14-05 |
| 9 | Latency p50/p95 + measured-set ownership | `duration_seconds` unused in aggregation | no frozen observations/report | S14-07 |
| 10 | TUI regression completeness | strong headless suites | no automated focus-restore/cancel affordance | S14-08 |
| 11 | Cross-platform evidence classification | manual protocol; docs-only classification | Stage-14 MANUAL/SKIPPED record absent | S14-08 |
| 12 | Test-order / snapshot tooling | only module-restore fixture; no order deps | `pytest-randomly`/`syrupy` unproven | no action; qualify first if proposed |

## 6. Task decomposition (S14-01 … S14-09)

```text
S14-01  Stage-14 contract / status reconciliation / golden-campaign qualification
S14-02  deterministic eval contract and scoring foundation
S14-03  offline scripted-model full-sequence regression
S14-04  untrusted-input / path-safety gap closure (only where genuinely missing)
S14-05  provider/runtime upgrade regression gate
S14-06  scriptable eval runner + product dataset (offline mode) + reporting
S14-07  opt-in live Ollama model baseline + latency metrics + frozen report
S14-08  TUI / cross-platform hardening evidence
S14-09  final Stage-14 review / release-readiness closure
```

- **S14-01** — documentation-only contract/status/qualification task; smallest
  first BUILD increment.
- **S14-02** — promote deterministic eval logic into provider-neutral `evals/`
  with offline tests and a focused layer-boundary contract; one scoring
  implementation. No CLI, no model, no live network.
- **S14-03** — one **offline deterministic scripted-model** full-sequence
  workflow through the real `BootstrapRuntime` / ChangeSet path. Faithful flow:
  `init → time init → first fresh bootstrap finalize → PENDING_CHANGESET →
  review/approve/apply → second fresh bootstrap finalize → COMPLETE →
  Campaign State CURRENT → FTS verified`. No parallel mapping/finalization path;
  no fixture mutation; no real model.
- **S14-04** — inspect and, only where genuinely missing, prove adversarial
  **untrusted/model-generated inputs** through real registered production tools
  and repository/storage path-safety boundaries. `ToolExecutor` does not sandbox
  deliberately malicious trusted Python handlers; that invariant is removed. If
  a specific invariant is already literally covered, record "no action" rather
  than duplicate tests.
- **S14-05** — documented runbook + curated automated offline selection for
  Pydantic AI / Ollama / profile upgrades, reusing accepted qualification,
  blocker, sync-thread and eval offline suites; no parallel runtime contract, no
  version bump.
- **S14-06** — versioned Russian product-facing dataset (stable IDs, explicit
  Python ground truth) and a scriptable runner with offline scripted-model mode,
  observation schema, metrics, report format and disposable output location. Owns
  the exact CLI contract and the `false_write_tool_call_rate` threshold with the
  final dataset/denominator semantics.
- **S14-07** — single opt-in live Ollama run producing frozen observations and a
  baseline report (metrics incl. `false_write_tool_call_rate`, latency p50/p95,
  sample-count assertions). SYSTEM SAFETY remains a hard fail; no hardware SLA.
- **S14-08** — close remaining headless TUI gaps and record Stage-14
  `MANUAL` / `SKIPPED_CAPABILITY` cross-platform evidence via
  `docs/development/tui-terminal-smoke.md`; never fake real-terminal automation
  and never claim macOS from Windows/headless.
- **S14-09** — consolidate literal evidence, run the final audit, mark Stage 14
  `DONE`, state release readiness and remaining capability skips. No next-stage
  work.

## 7. S14-01 implementation record

`S14-01` is a documentation-only contract/status/qualification task. It creates
this durable record, reconciles the status surface after the Stage-13
fast-forward integration, and records the golden-campaign qualification. It
performs no production, test, fixture, config or dependency change.

Expected changed files:

```text
docs/stages/14_EVALS_AND_HARDENING.md   new
DEVELOPMENT_STATUS.md                   status reconciliation
docs/stages/README.md                   stage index
```

Acceptance → evidence for S14-01:

| Criterion | Evidence |
|---|---|
| durable Stage-14 record exists with accepted decomposition | this document |
| status no longer claims `feat/bootstrap` / unmerged Stage 13 | `DEVELOPMENT_STATUS.md` |
| Stage 14 status is `IN PROGRESS`, active work `S14-01` | `DEVELOPMENT_STATUS.md` header/table |
| stage index includes Stage 14 | `docs/stages/README.md` |
| golden campaign classified; not modified | §4 + unchanged fixture |
| final diff is Markdown-only | Git changed-file inventory + `git diff --check` |

## 8. Surfaces

Typer remains the scripting/administration/eval surface. A future TUI eval
progress surface is optional and not required. Textual stays presentation-only.
`ToolExecutor` remains the write authorization boundary; the Obsidian Vault
remains the only campaign Source of Truth.

## 9. References

- `DEVELOPMENT_STATUS.md` — canonical current roadmap state.
- `docs/development/quality-and-evidence.md` — evidence and gate discipline.
- `docs/development/project-invariants.md` — architecture/Vault/UI invariants.
- `docs/development/maintainability.md` — size thresholds and ratchets.
- `docs/stages/13_BOOTSTRAP.md` — accepted Stage-13 bootstrap contract.
- `.opencode/skills/eval-harness/SKILL.md` — deterministic harness methodology.
- `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` — PAIM migration and retirement.
