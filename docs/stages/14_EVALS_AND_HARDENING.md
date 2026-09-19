# Stage 14 — Evals / Hardening

**Status:** `IN PROGRESS` (S14-01 … S14-09)
**Accepted baseline:** `main` @ `09fa5690b39bc1b4aeedea4fb98e26fc58c461f3`
**S14-01:** `DONE`
**S14-02:** `DONE`
**Next task:** `S14-03 — Offline Scripted-Model Full-Sequence Regression` (`NOT STARTED`)

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

## 7. S14-01 implementation record (`DONE`)

`S14-01` was a documentation-only contract/status/qualification task. It is
`DONE`: it created this durable record, reconciled the status surface after the
Stage-13 fast-forward integration, and recorded the golden-campaign
qualification. It performed no production, test, fixture, config or dependency
change. The overall Stage 14 remains `IN PROGRESS`; `S14-02` is the next task
and has not started.

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

## 10. S14-02 implementation record (`DONE`)

`S14-02 — Deterministic Eval Contract & Scoring Foundation` is `DONE`.  It moved
the genuinely reusable deterministic eval contract/scoring out of historical
PAIM test-only infrastructure into the provider-neutral
`src/dnd_assistant/evals/` package and removed the obsolete generic test-only
implementation.  It added no CLI, composition wiring, dataset, live-model run,
report writer, threshold or dependency.

Public production modules (all `< 700` physical lines):

```text
src/dnd_assistant/evals/__init__.py          61   facade + __all__
src/dnd_assistant/evals/contracts.py        193   expectation/observation DTOs (explicit is_write)
src/dnd_assistant/evals/scoring.py          266   strict JSON + decision/full-turn scoring (multiset)
src/dnd_assistant/evals/metrics.py          316   MetricId/MetricSummary/summarize_metrics/percentile
src/dnd_assistant/evals/write_accounting.py  68   unauthorized WRITE execution accounting
```

Public API (`__all__`): `DecisionObservation`, `EvalExpectation`, `EvalScenario`,
`ExpectedToolCall`, `ExposedToolInfo`, `FullTurnObservation`, `MetricId`,
`MetricSummary`, `ScenarioExpectationKind`, `ToolCallObservation`,
`count_unauthorized_write_handler_executions`, `json_args_equal`,
`nearest_rank_percentile`, `score_arguments`, `score_decision`, `score_full_turn`,
`score_tool_name`, `summarize_metrics`.

Stable metric identities (`MetricId`) and semantics — unit / error treatment:

```text
TOOL_NAME_ACCURACY            sample  correct tool-name scores / EXACT obs; errored counts incorrect
ARGUMENT_EXACT_MATCH          sample  exact-argument passes / EXACT obs; errored counts incorrect
SCHEMA_VALID_RATE             call    schema-valid emitted calls / emitted calls (incl. errored obs)
FALSE_TOOL_CALL_RATE          sample  no-tool obs with calls / no-tool obs
MISSED_TOOL_CALL_RATE         sample  EXACT obs missing expected (multiset) / EXACT obs; error state alone is not "missed"
CORRECT_ABSTENTION_RATE       sample  no error + zero calls + matching terminal / no-tool obs
CLARIFICATION_ACCURACY        sample  correct clarify outcomes / clarify obs
FALSE_WRITE_TOOL_CALL_RATE    run     runs with false is_write call / write-visible runs
HIDDEN_WRITE_ATTEMPT_RATE     run     hidden scenarios with is_write call / hidden scenarios
UNNECESSARY_TOOL_CALL_COUNT   count   extra emitted calls; denominator None, value == numerator
```

Semantics fixed by S14-02:

- no fixed repetition count and no majority/vote policy; only actually frozen
  observations are summarized (expected-sample completeness belongs to S14-06);
- duplicate `(scenario_id, repetition)` raises `ValueError`; absent observations
  contribute to neither numerator nor denominator; a ratio metric with zero
  applicable observations has `value is None`; a count metric has
  `denominator is None`;
- runtime/model errors are never a successful decision, abstention or
  clarification, but an already-emitted call still counts for call-level
  `SCHEMA_VALID_RATE` per its literal `schema_valid`;
- `MISSED_TOOL_CALL_RATE` is multiset-based: a sample is missed exactly when the
  expected tool-name multiset is not fully contained in the observed tool-name
  multiset; an errored observation is **not** automatically missed when the
  expected tool calls were already emitted before the error;
- `NO_TOOL_ANY_TERMINAL` with zero calls and `terminal_kind is None` is not a
  success;
- WRITE classification uses explicit `is_write` metadata only (no tool-name
  prefix anywhere under `src/dnd_assistant/evals/`); `write_handler_count` stays
  literal execution evidence and an error after a side effect does not erase it;
- `nearest_rank_percentile` accepts unsorted input, sorts a copy and does not
  mutate caller input.

Migration: the four literal consumers of `tests/support/pydantic_ai_eval.py`
(`test_pydantic_ai_eval.py`, `test_pydantic_ai_eval_unauthorized_write.py`,
`paim13_scenarios.py`, `paim13_live_harness.py`) were migrated to
`dnd_assistant.evals`; `tests/support/pydantic_ai_eval.py` and the two
superseded unit modules were deleted.  PAIM `CountingPydanticModel`,
synthetic registries/handlers, context-builder doubles and the Ollama probe
remain test-only.  Unique context-builder coverage moved into
`test_pydantic_ai_eval_live_harness.py`.

Expected changed files:

```text
src/dnd_assistant/evals/__init__.py                 modified (facade)
src/dnd_assistant/evals/contracts.py                new
src/dnd_assistant/evals/scoring.py                  new
src/dnd_assistant/evals/metrics.py                  new
src/dnd_assistant/evals/write_accounting.py         new
tests/contract/test_evals_boundaries.py             new
tests/unit/test_evals_scoring.py                    new
tests/unit/test_evals_metrics.py                    new
tests/unit/test_evals_write_accounting.py           new
tests/support/paim13_scenarios.py                   modified (imports + is_write)
tests/support/paim13_live_harness.py                modified (imports)
tests/unit/test_pydantic_ai_eval_live_harness.py    modified (context-builder tests)
tests/support/pydantic_ai_eval.py                   deleted
tests/unit/test_pydantic_ai_eval.py                 deleted
tests/unit/test_pydantic_ai_eval_unauthorized_write.py deleted
DEVELOPMENT_STATUS.md                               status reconciliation
docs/stages/14_EVALS_AND_HARDENING.md               this record
```

Acceptance → evidence for S14-02:

| Criterion | Evidence |
|---|---|
| Provider-neutral deterministic eval package owns the contract/scoring | `src/dnd_assistant/evals/` modules; all four consumers import `dnd_assistant.evals` |
| No forbidden dependency in evals | `tests/contract/test_evals_boundaries.py` (AST: no other `dnd_assistant` layer, no provider/HTTP, no env, non-vacuous detector self-tests) |
| No WRITE name-prefix inference in production evals | boundary test `test_evals_never_infers_write_from_name_prefix` |
| No fixed repetition / majority in the primitive | `test_evals_metrics.py` observation-derived denominators; no scenario/majority metric |
| Missing/duplicate/zero-denominator semantics | `test_evals_metrics.py` completeness and `value is None` tests |
| Error never success/abstention/valid; emitted call still schema-scored | `test_evals_scoring.py`, `test_evals_metrics.py` |
| Unordered duplicate multiset correctness | `test_evals_scoring.py` `A,A,B` vs `A,B,B` / `B,A,A` |
| Unauthorized WRITE accounting incl. error-after-side-effect | `test_evals_write_accounting.py` |
| Unordered percentile input without mutation | `test_evals_scoring.py` percentile tests |
| Maintainability | `tests/contract/test_maintainability.py` green; all new modules `< 700`; no allowlist change |

Final gate evidence recorded in Git: focused new eval suites + boundary +
maintainability, PAIM offline suites, canonical full `uv run pytest`
(7476 passed, 141 skipped, 0 failed/errors), `uv run pyright` (0 errors),
`uv run ruff check .`, `uv run ruff format --check .`, `uv lock --check`,
`git diff --check`.
