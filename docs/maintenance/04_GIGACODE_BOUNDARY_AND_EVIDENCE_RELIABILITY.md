# MNT-04 — GigaCode Boundary and Evidence Reliability

## Starting SHA

```
c73f7468ca4ac92c77ab6d9c18fe97437f270b20
```

## Why MNT-04 was introduced

Stages 7 and 8 showed several recurring agent failure classes even after the
earlier MNT-03 guardrails:

1. externally supplied structured values were sometimes validated by
   truthiness rather than by presence/type/cardinality;
2. Python numeric/type edge cases were missed:
   - `bool` being an `int` subclass;
   - NaN / ±Infinity;
   - oversized integers failing `int -> float` conversion;
3. incidental Python/library exceptions could escape public boundaries;
4. local test-isolation problems could expand into repository-level harness
   changes;
5. files were sometimes allowed to approach maintainability hard limits
   before decomposition;
6. correct command results were sometimes copied incorrectly into
   documentation:
   - physical-line counts;
   - historical verification values;
   - Git ahead/behind semantics;
7. a correct technical review could therefore require an additional
   evidence-only correction.

MNT-04 addresses these **recurring mechanisms**, not individual Stage-8
tickets as isolated anecdotes.

## Scope

MNT-04 is instruction/process hardening only.

- No `src/dnd_assistant/` changes.
- No `tests/` changes.
- No runtime architecture changes.
- No ModelGateway contract changes.
- No Tool Layer changes.
- No Fast Agent implementation.
- No dependency additions.
- No `uv.lock` modifications.
- No `.gigacode_vsc/` modifications.

## New rule

Created `.gigacode/rules/09-untrusted-boundary-validation.md` as a new
always-on rule covering:

- structural-field equivalence classes (missing, None, empty container,
  empty string, 0, False, True, valid, malformed);
- truthiness is not structural validation;
- presence, type, cardinality, semantic validity as separate dimensions;
- presence-vs-value invariant;
- Python numeric traps (bool is int, NaN, ±Inf, arbitrary precision,
  int->float overflow);
- bool-before-int rule;
- non-finite numeric value handling;
- oversized integer conversion;
- validate/coerce once;
- public exception containment;
- cross-reference to model-gateway, testing, and code-review skills.

## Updated rules

### `.gigacode/rules/08-task-scope-and-evidence.md`

Added sections:

- **5. Evidence transcription invariant** — machine-derived evidence must
  come from canonical commands, not mental reconstruction.
- **6. Git direction semantics** — explicit definitions for base-only,
  head-only, left/right symmetric difference, and ahead_by/behind_by.

Key requirements:

- `len(path.read_bytes().splitlines())` not arithmetic reconstruction;
- `run canonical commands → write → re-read → compare → commit`;
- `base_only = git rev-list --count head..base`;
- `head_only = git rev-list --count base..head`;
- `ahead_by = head-only`, `behind_by = base-only`.

### `.gigacode/rules/36-maintainability-ratchets.md`

Added sections:

- **6. Proactive headroom guidance** — ~600 production / ~850 test review
  thresholds.
- **7. No hard-limit gaming** — 699/700 is not automatically good
  decomposition.

### `.gigacode/rules/37-test-harness-isolation.md`

Added sections:

- **7. Protected harness infrastructure** — explicit protected scope
  (conftest.py, allowlists, global autouse fixtures).
- **8. Harness hard-stop rule** — STOP and report if a local task needs
  protected harness changes; separate into a correction/maintenance task.

## Updated skills

### `.gigacode/skills/model-gateway/SKILL.md` (v1 → v2)

Added:

- provider response field matrix;
- truthiness prohibition for structural validation;
- numeric provider boundaries;
- public exception containment;
- native provider metadata vs provider-neutral DTO semantics;
- normal mocked HTTP vs opt-in real-provider tests.

### `.gigacode/skills/testing/SKILL.md` (v2 → v3)

Added:

- boundary equivalence classes (default structural checklist);
- numeric test matrix (0, 1, -1, NaN, Inf, bool, large ints, wrong type);
- regression adequacy rule (one truthy malformed value is insufficient).

### `.gigacode/skills/pre-finalization-audit/SKILL.md` (v1 → v2)

Added:

- evidence reconciliation workflow (run commands → write → re-read → compare
  → scan placeholders → inspect diff → commit);
- placeholder/stale-evidence scan guidance.

### `.gigacode/skills/code-review/SKILL.md` (v2 → v3)

Added:

- boundary validation review checks (truthiness, missing/null/empty/falsy
  equivalence, bool-as-int, numeric overflow, non-finite values, exception
  leakage, evidence transcription, Git direction labels).

### `.gigacode/skills/stage-workflow/SKILL.md` (v2 → v3)

Added:

- historical Git comparison procedure with explicit definitions;
- stage-completion evidence reconciliation (re-read before completion
  commit).

## Boundary-equivalence policy

Defined in `.gigacode/rules/09-untrusted-boundary-validation.md`:

- structural-field equivalence classes;
- truthiness is not structural validation;
- presence/type/cardinality/semantic-validity as separate dimensions;
- presence-vs-value invariant.

## Numeric Python traps

Defined in `.gigacode/rules/09-untrusted-boundary-validation.md`:

- `bool` is a subclass of `int`;
- NaN / +Infinity / -Infinity are valid floats;
- Python integers have arbitrary precision;
- a finite Python int may overflow to Infinity as float;
- numeric conversion may raise `OverflowError`;
- bool-before-int rule;
- validate/coerce once.

## Public exception-containment policy

Defined in `.gigacode/rules/09-untrusted-boundary-validation.md`:

- review incidental exceptions from parsing, decoding, coercion, validation,
  mapping, indexing, attribute access, third-party libraries;
- owning boundary decides: project error, validated result, or documented
  programming error;
- prefer narrow failure boundaries.

## Evidence transcription/reconciliation policy

Defined in `.gigacode/rules/08-task-scope-and-evidence.md`:

- machine-derived evidence must come from canonical commands;
- no arithmetic reconstruction for current line counts;
- `run commands → write → re-read → compare → commit`;
- correct output followed by incorrect Markdown transcription is still a
  task failure.

## Historical Git direction semantics

Defined in `.gigacode/rules/08-task-scope-and-evidence.md` and
`.gigacode/skills/stage-workflow/SKILL.md`:

- `base_only = git rev-list --count head..base`;
- `head_only = git rev-list --count base..head`;
- `left = base-only`, `right = head-only` for `--left-right --count`;
- `ahead_by = head-only`, `behind_by = base-only` for GitHub compare;
- prefer `base-only` and `head-only` as primary evidence terms.

## Protected harness policy

Defined in `.gigacode/rules/37-test-harness-isolation.md`:

- protected scope: `tests/conftest.py`, `tests/integration/conftest.py`,
  `tests/contract/test_test_harness_policy.py`, module-restoration
  allowlists, test-harness allowlists, global autouse fixtures;
- normal task must not change them to make its own tests pass;
- hard-stop: report and separate into correction/maintenance task.

## Maintainability headroom policy

Defined in `.gigacode/rules/36-maintainability-ratchets.md`:

- ~600 production / ~850 test triggers decomposition review;
- finishing at 699/700 is not automatically good decomposition;
- file cohesion remains primary.

## GIGACODE.md changes

Added a concise `## Development reliability principles` subsection pointing
to the four key rules files with summaries of critical principles.

## Explicit deferrals

### Evidence automation deferred

A future helper such as `scripts/dev/evidence_snapshot.py` may be considered
**only if another evidence-transcription failure occurs after MNT-04**.

Reason: strengthen procedure first; introduce tooling only if the procedure
remains insufficient.

## Verification

- `uv run pytest tests/contract/test_test_harness_policy.py` — passed.
- `uv run pytest tests/contract/test_maintainability.py` — passed.
- `uv run pytest tests/contract/test_boundaries.py` — passed.
- `uv run pytest` — full suite passed.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed.
- `git diff --check` — clean.
- `src/` — zero changes.
- `tests/` — zero changes.
- `pyproject.toml` — unchanged.
- `uv.lock` — unchanged.
- `.gigacode_vsc/` — unchanged.
- Hard limits unchanged: `PRODUCTION_HARD_LIMIT = 700`, `TEST_HARD_LIMIT = 1000`.
- Legacy exceptions unchanged.
- Stage 8 remains `DONE`.
- MNT-04 `DONE`.
- Stage 9 remains `NOT STARTED`.