# D&D Session Assistant — Development Status

**Last updated:** 2026-08-31 (S5-C05)
**Current milestone:** `v0.1-dev — Vault Core`
**Current stage:** `Stage 5 — Retrieval + Entity Resolution`
**Status:** `IN PROGRESS`

## Status model

Use only:

- `NOT STARTED`
- `IN PROGRESS`
- `BLOCKED`
- `DONE`

A task is not `DONE` merely because code was generated. Completion requires the implementation, required tests, successful relevant checks, and final diff review.

## Stage progress

| Stage | Status | Started | Completed |
|---|---|---|---|
| 0. Environment | DONE | 2026-08-27 | 2026-08-27 |
| 1. Project skeleton + contracts | DONE | 2026-08-27 | 2026-08-30 |
| 2. Domain schemas | DONE | 2026-08-30 | 2026-08-30 |
| 3. Vault Repository | DONE | 2026-08-30 | 2026-08-30 |
| 4. Calendar | DONE | 2026-08-30 | 2026-08-31 |
| 5. Retrieval + Entity Resolution | IN PROGRESS | 2026-08-31 | — |
| 6. Session Runtime without LLM | NOT STARTED | — | — |
| 7. Tool Registry / Executor | NOT STARTED | — | — |
| 8. Model Gateway / Ollama | NOT STARTED | — | — |
| 9. Fast Agent | NOT STARTED | — | — |
| 10. ChangeSet | NOT STARTED | — | — |
| 11. Post-session Processor | NOT STARTED | — | — |
| 12. Campaign State | NOT STARTED | — | — |
| 13. Bootstrap | NOT STARTED | — | — |
| 14. Evals / Hardening | NOT STARTED | — | — |

## Stage 0 completion record

The user explicitly moved development to the next stage on 2026-08-27.

The environment stage is therefore recorded as `DONE`. Command output and machine-state evidence were not captured in the project chat. If any environment gate later fails, reopen the relevant `ENV-*` task instead of working around it in later layers.

Expected environment gates remain:

```text
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run dnd --help
```

## Stage 1 — Project skeleton + contracts

### Goal

Establish stable project boundaries and shared error contracts **without implementing application features or coupling any core layer to Ollama**.

### Scope

Primary interfaces/contracts to establish or inventory:

- `ModelGateway`
- `VaultRepository`
- `SearchService`
- `EntityResolver`
- `CalendarService`
- `SessionService`
- `ToolRegistry`
- `ToolExecutor`
- `PostSessionProcessor`
- `BootstrapService`
- `AuditService`

Shared error hierarchy:

```text
DndAssistantError
├── ValidationError
├── NotFoundError
├── ConflictError
├── AmbiguousEntityError
├── StorageError
├── ModelError
└── LockError
```

### Tasks

- [x] `CTR-001` Verify/create the package skeleton and importable modules.
- [x] `CTR-002` Add the shared project error hierarchy.
- [x] `CTR-003` Define boundary protocols/interfaces where signatures can be expressed without inventing premature domain models.
- [x] `CTR-004` Document responsibilities and dependency direction for every core interface.
- [x] `CTR-005` Add smoke/contract tests for imports and boundary assumptions.
- [x] `CTR-006` Verify that domain/storage modules do not depend on Ollama/provider implementations.
- [x] `CTR-007` Run targeted tests and project quality gates.
- [x] `CTR-008` Review the diff and update this status file.

### Important constraint

Do **not** use `dict[str, Any]` or placeholder provider-specific types merely to force every future method signature into Stage 1.

If a contract requires a domain type whose semantics belong to Stage 2, define the interface responsibility now and finalize that typed method signature alongside the domain type in Stage 2.

### Definition of Done

- package skeleton imports successfully;
- shared error hierarchy exists and is tested;
- core boundaries are explicit and documented;
- no domain/storage dependency on Ollama or a concrete model;
- no Vault persistence implementation is pulled forward from Stage 3;
- no Calendar implementation is pulled forward from Stage 4;
- relevant tests pass;
- `uv run pytest` passes when feasible;
- `uv run ruff check .` passes;
- `uv run ruff format --check .` passes;
- final diff is reviewed;
- `DEVELOPMENT_STATUS.md` is updated.

### S2-07 Stage 2 completion record

**Review range:** `5a38ea0..HEAD` (pre-Stage-2 boundary through S2-06)

**Implemented domain types/models:**
- `EntityId` — validated printable-Unicode string identifier
- `EntityType` — MVP-only: npc, location, quest, item
- `KnowledgeStatus` — epistemic: confirmed, reported, rumor, inferred, unknown
- `Visibility` — player, dm, system
- `Provenance` — manual, session, bootstrap, import, model_inference
- `Revision` — strict int >= 1, no bool/string coercion
- `Entity` — base schema with schema_version, id, type, name, status, visibility, knowledge_status, session refs, timestamps, revision, tags; `extra="forbid"`
- `Session` — schema with id, type discriminator, status, real timestamps, world_tick range, processed flag, model profile, revision; `extra="forbid"`
- `TemporalCertainty` — exact, approximate, range, unknown (separate from KnowledgeStatus)
- `TimelineEvent` — schema with id, type discriminator, name, status, certainty, importance, world_tick fields with model-level temporal consistency validation, location, visibility, revision; `extra="forbid"`
- `CampaignState` — compact snapshot with EntityId references (current_location, active_quests, important_npcs, upcoming_deadlines) and printable-string lists (party_goals, unresolved_threads); `extra="forbid"`

**Architectural boundaries confirmed:**
- `EntityType` is MVP-only (no timeline_event, campaign_state, session added)
- `TemporalCertainty` is separate from `KnowledgeStatus`
- No Stage 4 calendar implementation (no WorldTick value object, GameDate, CalendarDefinition, CalendarService)
- No storage implementation (no VaultRepository, AuditService, atomic writes)
- No retrieval implementation (no SearchService, EntityResolver)
- No session runtime implementation (no SessionService)
- No tool-layer implementation (no ToolRegistry, ToolExecutor)
- No ModelGateway implementation/provider coupling
- No CampaignState processing implementation (no state generation, ChangeSet application)
- All deferred contracts remain correctly assigned to later stages
- Domain dependency direction is clean (no imports from storage, models, retrieval, tools, application, cli)

**Final quality-gate results:**
- `uv run pytest tests/unit/test_domain_types.py` — 53 passed
- `uv run pytest tests/unit/test_entity.py` — 119 passed
- `uv run pytest tests/unit/test_session.py` — 103 passed
- `uv run pytest tests/unit/test_timeline_event.py` — 137 passed
- `uv run pytest tests/unit/test_campaign_state.py` — 89 passed
- `uv run pytest tests/unit/test_imports.py tests/unit/test_gateway_protocol.py tests/unit/test_audit_protocol.py tests/unit/test_tool_registry_protocol.py` — 13 passed
- `uv run pytest` (full suite) — 551 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 66 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S2-07:** None

**Code/test changes during S2-07:** None (only DEVELOPMENT_STATUS.md updated)

**Stage 3 status:** DONE.

## Stage 4 — Calendar

### Goal

Implement the deterministic fantasy calendar system: `WorldTick` canonical scalar, `CalendarDefinition` schema, `GameDate` display model, and `CalendarService` protocol for world_tick ↔ date conversion, date arithmetic, and relative-time operations.

### Tasks

- [x] `S4-00` Calendar kickoff + canonical domain contracts
- [x] `S4-01` Deterministic date ↔ world_tick conversion
- [x] `S4-02` World-time arithmetic + relative-time operations
- [x] `S4-03` TimelineEvent calendar queries
- [x] `S4-04` Custom-calendar/intercalary hardening + property tests
- [x] `S4-05` Full Stage 4 verification/diff/status

### Definition of Done

- `WorldTick` is the canonical strict signed integer minute scalar
- `GameDate` supports regular and named intercalary dates
- `CalendarDefinition` is generic and Gregorian-independent
- holidays are labels, not elapsed-time units
- intercalary days are explicit named calendar days
- `CalendarService` core is stateless
- current-world-time persistence is NOT CalendarService-owned
- date conversion implemented in S4-01 (``DeterministicCalendarService``)
- time arithmetic implemented in S4-02
- TimelineEvent calendar queries implemented in S4-03
- custom-calendar/intercalary property hardening complete (S4-04)
- full Stage 4 verification complete (S4-05)
- no Stage-5 work

### S4-01 completion record

**Review range:** S4-00 completion through S4-01

**Implementation:**
- `_CalendarLayout` — immutable precomputed lookup structure derived from `CalendarDefinition`:
  - `minutes_per_day`, `days_per_year` — derived constants
  - Chronological day index: month days + intercalary days in correct interleaved order
  - `validate_date()` — definition-dependent `GameDate` validation (month, day, intercalary name, hour, minute)
  - `_day_index_offset()` — zero-based day offset within a year
- `DeterministicCalendarService` — concrete `CalendarService` implementation:
  - `date_to_tick(date)` — direct ordinal arithmetic: absolute-minute(date) − absolute-minute(epoch)
  - `tick_to_date(tick)` — divmod-based inverse: absolute-minute = epoch + tick, then floor-divide into year/day/time components
  - Complexity proportional to calendar-definition size only (not year or tick magnitude)
- Public export from `dnd_assistant.domain`

**Conversion semantics:**
- `world_tick == 0` ↔ `CalendarDefinition.epoch` exactly (including non-midnight epochs)
- Signed proleptic years: `... -1, 0, 1, 2, ...` with no missing year zero
- Negative ticks for dates before epoch
- `divmod` floor-division for correct negative-tick/year handling
- Intercalary days occupy exactly one elapsed calendar day
- Multiple intercalary days after the same month preserve declaration order
- Intercalary days are interleaved chronologically: month days → IC days → next month days
- Holidays are labels only and do not affect elapsed time

**Epoch behavior:**
- `date_to_tick(definition.epoch) == 0`
- `tick_to_date(0) == definition.epoch`
- Arbitrary epoch time-of-day: e.g. `13:17` works correctly (not silently normalized to midnight)

**Calendar-name matching semantics:**
- Exact declared names for month and intercalary day matching
- No fuzzy search, aliases, or case-insensitive runtime matching
- Case-folding used only for CalendarDefinition duplicate-name validation

**S4-00 defect corrected:**
- `_validate_date_against_definition()` had a bare `pass` for intercalary dates, skipping intercalary day name validation
- An intercalary `GameDate` referencing a non-existent intercalary day was accepted without error
- Fixed: added `intercalary_names: set[str] | None` parameter; intercalary day name is now validated against declared intercalary days
- Regression test: `TestInvalidIntercalaryEpochRegression.test_invalid_intercalary_epoch_rejected` in `test_calendar_conversion.py`

**Tests added (65 tests in `tests/unit/test_calendar_conversion.py`):**
1. Epoch → zero (2 tests: regular, intercalary)
2. Zero → epoch (2 tests: regular, intercalary)
3. Non-midnight epoch (3 tests: round trip, one minute before/after)
4. Minute offsets (3 tests)
5. Hour boundary (1 test)
6. Day boundary (1 test)
7. Month boundary (1 test)
8. Variable month lengths (4 tests)
9-10. Intercalary conversion (7 tests: single IC, multiple IC ordering, boundaries, full day consumption)
11-12. Year boundaries (3 tests: year boundary, -1→0, 0→1)
13. Negative years (3 tests: regular, intercalary, round trip)
14-15. Negative/positive tick round trips (8 parametrized tests)
16-17. Custom time units (3 tests: adjacent minutes, day boundary, hour boundary)
18-23. Validation rejection (7 tests: unknown month, day overflow, hour overflow, minute overflow, custom hour, custom minute, unknown intercalary)
24. Invalid intercalary epoch regression (1 test — S4-00 defect)
25. Holidays do not affect ticks (1 test)
26. Date round trips (7 parametrized tests: regular, intercalary, negative year, year zero, large year)
27. Large signed year/tick regression (4 tests: ±100000 year, ±10^12 tick)
28. Import boundaries (4 tests: module importable, exported, no storage/models imports)

**Targeted quality-gate results:**
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py` — 167 passed
- `uv run pytest` (full suite) — 1289 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 162 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- S4-02 not started (no advance_world_time, time_until, relative-time parsing)
- S4-03 not started (no TimelineEvent calendar queries)
- Stage 5 not started (no retrieval/entity resolution)
- No session-runtime work
- No ToolRegistry/ToolExecutor work
- No ModelGateway/Ollama work

**ADR assessment:** No ADR required. All architectural decisions follow established patterns (Protocol for contracts, immutable derived layout data per ADR-0003, direct ordinal arithmetic).

### S4-02 completion record

**Review range:** S4-01 completion through S4-02

**Implementation:**
- `advance_world_time(current_tick, *, minutes)` — elapsed-minute arithmetic on canonical `WorldTick`:
  - `result = current_tick + minutes` with no clamping, no date round-trip, no calendar-boundary awareness
  - Signed arithmetic: negative/zero/positive ticks and minutes all supported
  - Crossing tick zero is natural (`-1 + 1 == 0`, `0 - 1 == -1`)
  - Large Python integers supported without overflow/clamping
- `time_until(start_tick, end_tick)` — signed difference:
  - `end_tick - start_tick` (not absolute value)
  - Positive result: end_tick is after start_tick
  - Negative result: end_tick is before start_tick (meaningful for overdue/past-time semantics)
  - Zero when ticks are equal
- `_validate_minutes(value)` — static helper matching `_validate_world_tick` pattern:
  - negative/zero/positive `int` accepted
  - `bool`, `str`, `float`, `None` rejected with clear error messages
- Input validation reuses existing `_validate_world_tick` for tick parameters
- Both operations are calendar-independent: no `tick_to_date`/`date_to_tick` round-trip in production arithmetic
- Service remains stateless: no mutable `current_world_tick`, no Vault/filesystem persistence

**Arithmetic semantics:**
- `advance_world_time(100, minutes=10) == 110`
- `advance_world_time(100, minutes=0) == 100`
- `advance_world_time(100, minutes=-10) == 90`
- `advance_world_time(-100, minutes=10) == -90`
- `advance_world_time(-100, minutes=-10) == -110`
- `advance_world_time(-1, minutes=1) == 0`
- `advance_world_time(0, minutes=-1) == -1`
- `time_until(100, 110) == 10`
- `time_until(100, 100) == 0`
- `time_until(110, 100) == -10`
- Inverse property: `time_until(tick, advance_world_time(tick, delta)) == delta`
- Reverse property: `advance_world_time(advance_world_time(tick, delta), -delta) == tick`

**Relative-time scope resolution:**
- Repository inspection confirmed no typed/executable relative-time contract beyond `advance_world_time` and `time_until`
- No `resolve_relative_time(text: str)`, `parse_duration(...)`, `RelativeTimeExpression`, or `Duration` DTO was invented
- The phrase "relative-time operations" in the S4-02 status title was interpreted as the signed arithmetic contract only

**Tests added (54 tests in `tests/unit/test_calendar_arithmetic.py`):**

1. **Calendar-boundary integration (8 tests)** — uses S4-01 conversion to verify arithmetic through:
   - Hour boundary (24×60 clock)
   - Day boundary
   - Month boundary
   - Intercalary entry (regular day → intercalary day)
   - Intercalary exit (intercalary day → next month)
   - Year boundary
   - Custom clock hour boundary (10h×100m clock)
   - Custom clock day boundary

2. **Invalid-input rejection (12 tests):**
   - `advance_world_time`: current_tick bool/str/float rejected (3 tests)
   - `advance_world_time`: minutes bool/str/float/None rejected (4 tests)
   - `time_until`: start_tick bool/str rejected (2 tests)
   - `time_until`: end_tick bool/str/float rejected (3 tests)

3. **Protocol compatibility (1 test):**
   - `isinstance(DeterministicCalendarService(definition), CalendarService)` is now `True`

4. **Advance positive/zero/negative (3 tests):**
   - `100 + 10 == 110`, `100 + 0 == 100`, `100 + (-10) == 90`

5. **Negative current tick (2 tests):**
   - `-100 + 10 == -90`, `-100 - 10 == -110`

6. **Cross zero (2 tests):**
   - `-1 + 1 == 0`, `0 - 1 == -1`

7. **Large signed values (3 tests):**
   - `10^12 + 10^12 == 2*10^12`, `-10^12 - 10^12 == -2*10^12`, `10^12 - 10^12 == 0`

8. **time_until future/same/past (3 tests):**
   - `100 → 110 == 10`, `100 → 100 == 0`, `110 → 100 == -10`

9. **time_until with negative ticks (4 tests):**
   - Both negative future/past, cross zero positive/negative

10. **Inverse arithmetic property (16 parametrized tests):**
    - `time_until(tick, advance(tick, delta)) == delta` (8 cases)
    - `advance(advance(tick, delta), -delta) == tick` (8 cases)

**Targeted quality-gate results:**
- `uv run pytest tests/unit/test_calendar_arithmetic.py` — 54 passed
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py` — 221 passed
- `uv run pytest` (full suite) — 1343 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 163 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- S4-03 not started (no TimelineEvent calendar queries)
- S4-04 not started (no broad property-based hardening beyond focused S4-02 parametrized tests)
- Stage 5 not started (no retrieval/entity resolution)
- No session-runtime work
- No ToolRegistry/ToolExecutor work
- No ModelGateway/Ollama work
- No natural-language relative-time parser invented
- No new duration DTO invented
- No mutable current-world-time state added
- No CLI world-time persistence commands

**ADR assessment:** No ADR required. All architectural decisions follow established patterns (signed integer arithmetic, strict input validation via static helpers, stateless service per ADR-0003, calendar-independent tick arithmetic).

### S4-C01 correction record

**Acceptance-review defect:**
- `tick_to_date()` accepted `tick: WorldTick` as a type hint but did not call `_validate_world_tick(tick)` before arithmetic.
- `bool` (`True`/`False`) is a Python subclass of `int` and could silently participate in tick arithmetic as `1`/`0`, violating the strict `WorldTick` contract.
- `advance_world_time()` and `time_until()` already validated their `WorldTick` inputs correctly — only `tick_to_date()` was missing the guard.

**Production change:**
- Added `_validate_world_tick(tick)` as the first statement in `tick_to_date()`, before any arithmetic.
- Reuses the existing canonical validator — no duplicate, no new DTO.

**Regression tests added (8 tests in `TestTickToDateValidation` in `test_calendar_conversion.py`):**
- `True` rejected, `False` rejected, `str` rejected, `float` rejected, `None` rejected
- Positive control: `0` → epoch, negative `-1440` → correct date, positive `1440` → correct date

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py tests/unit/test_calendar_contracts.py` — 229 passed
- `uv run pytest` (full suite) — 1351 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 163 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- S4-03 not started
- S4-04 not started
- Stage 5 not started

### S4-03 completion record

**Review range:** S4-C01 completion through S4-03

**Implementation:**

1. **`calendar.py` — CalendarService Protocol extended:**
   - `events_between(events, start_tick, end_tick)` — inclusive interval-overlap semantics
   - `events_near(events, event, *, radius)` — minimum interval-distance semantics
   - `upcoming(events, current_tick, *, days)` — stateless window query using `minutes_per_day`
   - `overdue_events(events, current_tick)` — conservative latest-possible-tick semantics
   - `time_until_event(current_tick, event)` — signed delta interval preserving uncertainty

2. **`calendar.py` — DeterministicCalendarService implementation:**
   - `_event_interval(event)` — canonical helper: exact→[T,T], approximate→[min,max], range→[min,max], unknown→None
   - `_interval_overlaps(a, b)` — inclusive interval overlap predicate
   - `_interval_distance(a, b)` — minimum temporal distance (0 for overlapping)
   - `_validate_nonnegative_int(value, label)` — strict non-negative integer validation
   - `_event_sort_key(event)` — deterministic sort key: (interval_start, interval_end, event_id)
   - No midpoint arithmetic, no mutation, no repository/Vault dependency

3. **`calendar.py` — Circular import avoidance:**
   - `TimelineEvent` imported under `TYPE_CHECKING` only
   - No runtime circular import (`events.py` imports `WorldTick` from `calendar.py`)

4. **`test_calendar_contracts.py` — Protocol test updated:**
   - `test_required_methods_exist` now includes all 5 S4-03 methods
   - `test_event_query_methods_exist` replaces `test_no_event_query_methods_yet`

5. **`tests/unit/test_calendar_event_queries.py` (new) — 96 tests:**

   **Event interval normalization (4 tests):**
   - exact→[T,T], approximate→[min,max], range→[min,max], unknown→None

   **events_between — exact (5 tests):** inside, before, after, exactly start, exactly end

   **events_between — approximate/range overlap (9 tests):** fully inside, overlap left, overlap right, contains whole query, touch start/end boundary, fully before/after, range same as approx

   **events_between — unknown (1 test):** excluded

   **events_between — invalid query (7 tests):** start>end rejected, bool/str/float/None rejected

   **events_between deterministic ordering (1 test):** interval start → interval end → event id

   **events_near (8 tests):** exact-exact, exact-range, range-range, overlap→0, touching, exactly radius, radius+1 excluded, both before/after

   **events_near target exclusion (2 tests):** same ID excluded, different ID same tick included

   **events_near unknown (2 tests):** unknown candidate excluded, unknown target raises

   **events_near radius validation (7 tests):** 0/positive accepted, negative/bool/str/float/None rejected

   **events_near ordering (1 test):** distance → interval start → interval end → event id

   **upcoming (8 tests):** at current, inside window, exactly at end, immediately after, before current, straddling current, overlapping window end, unknown excluded

   **custom calendar upcoming (2 tests):** 10h×100m day conversion, boundary

   **upcoming days validation (7 tests):** 0/positive accepted, negative/bool/str/float/None rejected

   **overdue exact (3 tests):** before=overdue, at=not, after=not

   **overdue approximate/range (5 tests):** max<current=overdue, straddling=not, min==current=not, min>current=not, unknown excluded

   **overdue ordering (1 test):** interval end → interval start → event id

   **time_until_event exact (3 tests):** future→(+n,+n), now→(0,0), past→(-n,-n)

   **time_until_event approximate/range (4 tests):** entirely future, entirely past, straddles current, degenerate min==max

   **time_until_event unknown (1 test):** returns None

   **Strict current tick validation (9 tests):** upcoming/overdue/time_until_event reject bool/str/float/None

   **Status independence (1 test):** temporal queries do not interpret status strings

   **Input immutability (1 test):** event models not modified by queries

   **Protocol compatibility (1 test):** `isinstance(svc, CalendarService)` remains True

**Query API signatures:**

```python
def events_between(
    self, events: Sequence[TimelineEvent], start_tick: WorldTick, end_tick: WorldTick
) -> tuple[TimelineEvent, ...]: ...


def events_near(
    self, events: Sequence[TimelineEvent], event: TimelineEvent, *, radius: int
) -> tuple[TimelineEvent, ...]: ...


def upcoming(
    self, events: Sequence[TimelineEvent], current_tick: WorldTick, *, days: int
) -> tuple[TimelineEvent, ...]: ...


def overdue_events(
    self, events: Sequence[TimelineEvent], current_tick: WorldTick
) -> tuple[TimelineEvent, ...]: ...


def time_until_event(
    self, current_tick: WorldTick, event: TimelineEvent
) -> tuple[int, int] | None: ...
```

**Temporal interval semantics:**

| Certainty | Interval | Notes |
|---|---|---|
| EXACT | [world_tick, world_tick] | Degenerate point interval |
| APPROXIMATE | [world_tick_min, world_tick_max] | Inclusive, A ≤ B |
| RANGE | [world_tick_min, world_tick_max] | Inclusive, A ≤ B |
| UNKNOWN | None | No computable interval |

All boundaries are inclusive. Interval-overlap semantics for `events_between`, `events_near`, and `upcoming`. Conservative overdue: only when `latest_tick < current_tick`. `time_until_event` returns signed `(min_delta, max_delta)` preserving uncertainty.

**Circular-import handling:**
- `TimelineEvent` is imported in `calendar.py` under `TYPE_CHECKING` only
- No runtime circular dependency (`events.py` → `WorldTick` from `calendar.py` is safe)
- No module restructuring was required

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_event_queries.py` — 96 passed
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py tests/unit/test_calendar_event_queries.py tests/unit/test_timeline_event.py` — 462 passed
- `uv run pytest` (full suite) — 1447 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 164 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- S4-04 not started (no property-based hardening)
- S4-05 not started (no Stage 4 final verification)
- Stage 5 not started (no retrieval/entity resolution)
- No storage/Vault query implementation
- No ToolRegistry/ToolExecutor work
- No ModelGateway/Ollama work
- No TimelineEvent schema broadening
- No midpoint arithmetic
- No status-based lifecycle assumptions

**ADR assessment:** No ADR required. All architectural decisions follow established patterns (TYPE_CHECKING for circular imports, stateless service per ADR-0003, interval-overlap semantics consistent with existing domain contracts).

### S4-C02 correction record

**Acceptance-review defect:**
- `overdue_events()` sorted by `_event_sort_key` which uses `(interval_start, interval_end, event_id)`.
- The documented S4-03 contract requires `(interval_end, interval_start, event_id)` — end-first ordering.
- Overdue detection uses the event's latest possible tick (`interval[1] < current_tick`), so chronological overdue ordering should prioritise the same temporal boundary.

**Root cause:**
- `_event_sort_key` was reused for `overdue_events()` without considering that the overdue query's natural ordering is end-first.
- `_event_sort_key` is correct for `events_between` and `events_near` (which use start-first semantics) and remains unchanged.
- The existing `TestOverdueOrdering.test_ordering_by_end_then_start_then_id` did not actually distinguish end-first from start-first ordering because the test data happened to produce the same result under both orderings.

**Production change:**
- Added `_overdue_sort_key(event)` static method returning `(interval_end, interval_start, event_id)`.
- `overdue_events()` now calls `overdue.sort(key=self._overdue_sort_key)` instead of `overdue.sort(key=self._event_sort_key)`.
- `_event_sort_key` is preserved unchanged for `events_between` and `events_near`.

**Regression tests added (4 tests in `TestOverdueOrdering` in `test_calendar_event_queries.py`):**
- `test_ordering_by_end_then_start_then_id` — combined test using `a=[30,30]` and `d=[10,50]`; end-first expects `a` before `d` (start-first would give `d` before `a`). This test fails under the old `_event_sort_key`.
- `test_end_primary` — `a=[30,30]` vs `b=[10,50]`; end-first expects `a, b`.
- `test_start_secondary` — `a=[10,50]` vs `b=[20,50]`; same end, tie-break on start: `a, b`.
- `test_id_tertiary` — `a=[10,50]` vs `b=[10,50]`; identical interval, tie-break on id: `a, b`.

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_event_queries.py` — 99 passed (was 96, +3 new tests)
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py tests/unit/test_calendar_event_queries.py tests/unit/test_timeline_event.py` — 462 passed
- `uv run pytest` (full suite) — 1450 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 164 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- `_event_sort_key` unchanged (still start-first for `events_between`, `events_near`)
- `_event_interval`, `_interval_overlaps`, `_interval_distance` unchanged
- `events_between`, `events_near`, `upcoming`, `time_until_event` unchanged
- Conservative overdue predicate (`interval[1] < current_tick`) unchanged
- Unknown handling unchanged
- S4-04 remains NOT STARTED (at S4-C02 time)
- S4-05 remains NOT STARTED
- Stage 5 remains NOT STARTED

### S4-04 completion record

**Review range:** S4-C02 completion through S4-04

**Intercalary hardening investigation:**

The suspected cross-month declaration-order defect was **confirmed** and corrected.

**Root cause:**
- `_CalendarLayout._ic_names_ordered` stored intercalary names in declaration order.
- `_CalendarLayout._intercalary_offsets` stored chronological offsets (built by iterating months in order).
- `_day_index_offset()` used `_ic_names_ordered.index(name)` to get a declaration-order index, then used that same index into `_intercalary_offsets`, assuming both arrays were in the same order.
- When intercalary days were declared in non-chronological month order (e.g. "Late Festival" after "Second" declared before "Early Festival" after "First"), the name index and offset index did not correspond, producing swapped offsets and incorrect tick values.

**Production correction:**
- Replaced `_intercalary_offsets: tuple[int, ...]` (parallel array) with `_intercalary_offsets_by_name: dict[str, int]` (direct name-to-offset mapping).
- Removed `_ic_names_ordered` slot as it is no longer needed.
- `_day_index_offset()` now looks up `_intercalary_offsets_by_name[date.intercalary_day]` directly instead of the two-step `_ic_names_ordered.index(name) -> _intercalary_offsets[idx]`.
- Same-month IC ordering (multiple ICs after the same month) remains correct because the dict is populated in the same iteration order as before.

**Regression tests added (31 tests in `tests/unit/test_calendar_intercalary_hardening.py`):**
- `TestCrossMonthDeclarationOrder` (10 tests): early-before-late, adjacency checks, round trips, negative-year round trips
- `TestSameMonthIntercalaryOrder` (4 tests): declaration order preserved, adjacency, round trips
- `TestFinalMonthIntercalary` (5 tests): after-final-month adjacency, before-next-year, round trip, year-boundary adjacent ticks
- `TestMinimalCalendar` (7 tests): 1-month/1-day/1-hour/1-minute with 0, 1, and multiple IC days
- `TestExtremeCalendars` (5 tests): very short months, large hours/day, large minutes/hour, 10 IC days ordering, negative-year with many ICs

**Hypothesis strategy design:**
- `calendar_strategy()` — valid-by-construction `CalendarDefinition` generator:
  - 1-6 months with machine-friendly names (M0, M1, ...)
  - 1-40 days per month
  - 0-6 intercalary days with random `after_month` references (explicitly allowing cross-month ordering)
  - 1-30 hours/day, 1-120 minutes/hour
  - Epoch always in first month day 1
- `draw_valid_date(draw, cal)` — definition-aware `GameDate` generator:
  - Signed year range -10000 to +10000
  - Random regular or intercalary date (when ICs exist)
  - Valid hour/minute within calendar bounds
- Tick/delta ranges: -10^9 to +10^9 for ticks, -10^6 to +10^6 for deltas
- All strategies use bounded small ranges for effective shrinking
- No `filter()` — valid-by-construction throughout

**Properties implemented (15 tests):**

| Property | Invariant | File |
|---|---|---|
| P1 | date -> tick -> date round trip | test_calendar_properties.py |
| P2 | tick -> date -> tick round trip | test_calendar_properties.py |
| P3 | epoch identity (date_to_tick(epoch)==0, tick_to_date(0)==epoch) | test_calendar_properties.py |
| P4 | advance(advance(tick, delta), -delta) == tick | test_calendar_properties.py |
| P5 | time_until(t, advance(t, d)) == d | test_calendar_properties.py |
| P5b | time_until(advance(t, d), t) == -d | test_calendar_properties.py |
| P5c | time_until(t, t) == 0 | test_calendar_properties.py |
| P6 | adjacent ticks map to adjacent elapsed minutes | test_calendar_properties.py |
| P7 | one-year translation = days_per_year * minutes_per_day | test_calendar_properties.py |
| P8 | holidays do not affect tick_to_date | test_calendar_properties.py |
| P8b | holidays do not affect date_to_tick | test_calendar_properties.py |
| P9 | intercalary declaration order semantics (same-month + cross-month) | test_calendar_properties_p2.py |
| P10 | events_between matches naive reference | test_calendar_properties_p2.py |
| P11 | events_near matches naive distance | test_calendar_properties_p2.py |
| P12 | overdue conservative semantics (end < current) | test_calendar_properties_p2.py |

**Defects discovered by property testing:**
- Beyond the targeted intercalary cross-month ordering defect (confirmed and fixed), no additional defects were discovered by property testing. All properties passed on the first successful run after the production fix.

**Hypothesis configuration:**
- Default settings used throughout (no custom `max_examples`, no deadline suppression).
- `st.data()` pattern used instead of nested `@given` to avoid `HealthCheck.nested_given`.
- No random seeds hard-coded.
- No health checks suppressed.

**Production changes:**
- `src/dnd_assistant/domain/calendar.py` — `_CalendarLayout`:
  - Replaced `_intercalary_offsets: tuple[int, ...]` with `_intercalary_offsets_by_name: dict[str, int]`
  - Removed `_ic_names_ordered` slot
  - Updated `_day_index_offset()` to use direct name-to-offset dict lookup

**Test results:**
- `uv run pytest tests/unit/test_calendar_intercalary_hardening.py` — 31 passed
- `uv run pytest tests/property/test_calendar_properties.py tests/property/test_calendar_properties_p2.py` — 15 passed
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py tests/unit/test_calendar_event_queries.py tests/unit/test_timeline_event.py tests/unit/test_calendar_intercalary_hardening.py tests/property/test_calendar_properties.py tests/property/test_calendar_properties_p2.py` — 511 passed
- `uv run pytest` (full suite) — 1496 passed, 34 skipped

**Quality gates:**
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 168 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope confirmation:**
- S4-05 not started
- Stage 5 not started
- No retrieval work
- No session-runtime work
- No Tool Layer work
- No ModelGateway/Ollama work
- No leap-year functionality added
- No new unrelated CalendarService API added
- No storage/Vault imports

**Tool-usage compliance:**
All repository files were read and edited only through built-in GigaCode/IDE file tools (Read, Write, Edit). No PowerShell, Bash, or Python scripts were used for repository file mutation.

**ADR assessment:** No ADR required. The production correction replaces a fragile parallel-array lookup with a direct name-keyed dict, which is a local implementation detail of `_CalendarLayout` and does not change any public API or architectural boundary.

### S4-C03 correction record

**Acceptance-review defects:**

1. **DEVELOPMENT_STATUS.md hierarchy corruption** — The S4-04 commit replaced the existing `## Stage 3 — Vault Repository` heading with `## Stage 4 — S4-04 completion record`, leaving historical Stage-3 content structurally nested under the S4-04 section. The heading has been restored to `### S4-04 completion record` (correctly nested under `## Stage 4 — Calendar`) and `## Stage 3 — Vault Repository` has been restored before the Stage-3 `### Goal` section.

2. **Incomplete epoch property coverage** — The `calendar_strategy()` in `test_calendar_properties.py` always used a fixed epoch of `GameDate(year=1, month=month_names[0], day=1)`. This meant Hypothesis varied month lengths, intercalary layout, clock units, test dates, and ticks, but never varied the actual epoch shape. Properties P1-P12 exercised calendars whose tick zero was always the same trivial shape.

**Strategy correction:**

- `calendar_strategy()` now generates a valid-by-construction epoch from the calendar being built:
  - **Epoch year**: signed integer from -10000 to +10000 (negative, zero, positive)
  - **Regular epoch**: any declared month, any valid day within that month
  - **Intercalary epoch**: any declared intercalary day (when ICs exist), with 50% probability
  - **Epoch time**: non-midnight hour/minute within the calendar's custom clock bounds
  - No `filter()` — valid-by-construction throughout

**Deterministic epoch regressions added (3 tests in `TestEpochRegressions` in `test_calendar_intercalary_hardening.py`):**

- `test_signed_non_midnight_regular_epoch` — year=-5, month="B", day=2, hour=13, minute=17
- `test_year_zero_epoch` — year=0, month="A", day=3
- `test_intercalary_non_midnight_epoch` — cross-month IC declaration ordering, year=42, hour=7, minute=31

**Property coverage after correction:**

All 15 properties (P1-P12) now automatically run over calendars with genuinely varying epochs:
- P1 (date round trip) — varied epoch dates
- P2 (tick round trip) — varied epoch dates
- P3 (epoch identity) — now genuinely varies: regular/intercalary, signed years, non-midnight
- P4/P5 (arithmetic) — varied-epoch calendars
- P6 (adjacent ticks) — varied-epoch calendars
- P7 (year translation) — varied-epoch calendars
- P8 (holiday neutrality) — varied-epoch calendars
- P9-P12 (event queries) — varied-epoch calendars

**Additional defects discovered:** None.

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_intercalary_hardening.py` — 34 passed (was 31, +3 epoch regressions)
- `uv run pytest tests/property/test_calendar_properties.py tests/property/test_calendar_properties_p2.py` — 15 passed
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py tests/unit/test_calendar_event_queries.py tests/unit/test_timeline_event.py tests/unit/test_calendar_intercalary_hardening.py tests/property/test_calendar_properties.py tests/property/test_calendar_properties_p2.py` — 514 passed
- `uv run pytest` (full suite) — 1499 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 168 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope confirmation:**
- S4-04 DONE (unchanged)
- S4-05 NOT STARTED
- Stage 5 NOT STARTED
- No retrieval work
- No session-runtime work
- No Tool Layer work
- No ModelGateway/Ollama work
- No production calendar.py changes (no new defects discovered)
- S4-04 intercalary offset fix (`_intercalary_offsets_by_name`) preserved unchanged

**Tool-usage compliance:**
All repository files were read and edited only through built-in GigaCode/IDE file tools (Read, Write, Edit). No PowerShell, Bash, or Python scripts were used for repository file mutation.

**ADR assessment:** No ADR required. The epoch strategy correction is a local implementation detail of the Hypothesis test strategy and does not change any public API or architectural boundary.

### S4-05 Stage 4 completion record

**Review base (pre-Stage-4):** `a8e81773f939c4b4b6963b68930df43a72bd896d`

**Captured implementation review head:** `1ff7907fbdf7318e5ed774fce4dd5745ddaefeee`

**Historical review range:** `a8e81773..1ff7907`

**Commit inventory (9 commits):**

| SHA | Classification |
|---|---|
| `2de1fb3` feat: define calendar domain contracts (S4-00) | implementation |
| `6675a15` docs: add S4-00 completion record to development status | documentation/status |
| `7bedc1d` feat: implement calendar date conversion (S4-01) | implementation |
| `764d753` feat: implement calendar time arithmetic (S4-02) | implementation |
| `4adaacb` fix: enforce tick_to_date WorldTick validation (S4-C01) | correction |
| `b9ad278` feat: implement timeline event calendar queries (S4-03) | implementation |
| `443700f` fix: correct overdue event ordering (S4-C02) | correction |
| `5cc2a1d` test: harden calendar properties and fix intercalary offset ordering (S4-04) | correction |
| `1ff7907` test: complete calendar epoch property coverage (S4-C03) | correction |

**Production files reviewed:**
- `src/dnd_assistant/domain/calendar.py`
- `src/dnd_assistant/domain/events.py`
- `src/dnd_assistant/domain/session.py`
- `src/dnd_assistant/domain/__init__.py`
- `docs/adr/0003-calendar-service-state-ownership.md`

**Test files reviewed:**
- `tests/unit/test_calendar_contracts.py`
- `tests/unit/test_calendar_conversion.py`
- `tests/unit/test_calendar_arithmetic.py`
- `tests/unit/test_calendar_event_queries.py`
- `tests/unit/test_calendar_intercalary_hardening.py`
- `tests/unit/test_timeline_event.py`
- `tests/property/test_calendar_properties.py`
- `tests/property/test_calendar_properties_p2.py`

**Architectural boundaries verified:**

| Assertion | Status |
|---|---|
| Vault remains Source of Truth | ✓ |
| CalendarService is deterministic | ✓ |
| CalendarService is stateless regarding current campaign time | ✓ |
| WorldTick is canonical elapsed-minute representation | ✓ |
| calendar arithmetic is Python-only | ✓ |
| calendar domain has no Ollama dependency | ✓ |
| custom clocks supported | ✓ |
| custom month lengths supported | ✓ |
| intercalary days supported | ✓ |
| negative years supported | ✓ |
| year zero supported | ✓ |
| negative ticks supported | ✓ |
| holidays do not alter elapsed time | ✓ |
| TimelineEvent uncertainty preserved | ✓ |
| unknown-time events are not assigned fabricated ticks | ✓ |
| Stage 5 remains untouched | ✓ |

**Historical defect verification:**

| Defect | Fix | Status |
|---|---|---|
| S4-00: invalid intercalary epoch name not validated | `_validate_date_against_definition` with `intercalary_names` param | ✓ preserved |
| S4-C01: tick_to_date lacked strict WorldTick runtime validation | `_validate_world_tick(tick)` as first statement | ✓ preserved |
| S4-C02: overdue_events used wrong start-first sort key | `_overdue_sort_key` with end-first ordering | ✓ preserved |
| S4-04: intercalary name/offset parallel arrays broke cross-month ordering | `_intercalary_offsets_by_name` dict lookup | ✓ preserved |
| S4-C03: epoch strategy was trivial; DEVELOPMENT_STATUS hierarchy damaged | Varied epoch generation; heading restored | ✓ preserved |

**Defects discovered during S4-05:** None.

**Code/test changes during S4-05:**
- Production: fixed stale docstring in `calendar.py` (S4-04/S4-05 deferred → implemented/completed)
- Test: None
- Documentation/status: `DEVELOPMENT_STATUS.md` updated with completion record, DoD finalised, Stage 4 marked DONE

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py tests/unit/test_calendar_arithmetic.py tests/unit/test_calendar_event_queries.py tests/unit/test_timeline_event.py tests/unit/test_calendar_intercalary_hardening.py tests/property/test_calendar_properties.py tests/property/test_calendar_properties_p2.py` — 514 passed
- `uv run pytest` (full suite) — 1499 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 168 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**ADR assessment:** No new ADR required. All architectural decisions follow established patterns (Protocol for contracts, immutable derived layout data per ADR-0003, direct ordinal arithmetic, TYPE_CHECKING for circular imports, stateless service).

**Final Stage status:**
- Stage 4 — DONE
- S4-05 — DONE
- Stage 5 — NOT STARTED

**Tool-usage compliance:**
All repository files were read and edited only through built-in GigaCode/IDE file tools (Read, Write, Edit). Shell was used only for permitted development commands (git, pytest, ruff, dnd --help).

## Stage 5 — Retrieval + Entity Resolution

### Goal

Establish the retrieval and entity-resolution layer with canonical typed contracts, then implement exact, fuzzy, and FTS-based search with explicit resolved/ambiguous/not-found resolution outcomes.

### Tasks

- [x] `S5-00` Retrieval kickoff + canonical contracts
- [x] `S5-01` Exact ID/name/alias retrieval + player-visibility enforcement
- [ ] `S5-02` Fuzzy name retrieval + entity-type filtering/ranking
- [ ] `S5-03` SQLite FTS5 derived index + rebuild path
- [ ] `S5-04` EntityResolver resolved/ambiguous/not-found behavior
- [ ] `S5-05` Golden-Vault integration + retrieval/resolver hardening
- [ ] `S5-06` Full Stage 5 historical review / verification / status

### Definition of Done

- retrieval-layer public types/contracts are explicit and tested (S5-00)
- exact ID/name/alias retrieval works with player-visibility filtering (S5-01)
- fuzzy name retrieval works with entity-type filtering (S5-02)
- SQLite FTS5 index is rebuildable from Vault (S5-03)
- EntityResolver produces explicit resolved/ambiguous/not-found outcomes (S5-04)
- golden Vault integration tests exist (S5-05)
- full Stage 5 verification complete (S5-06)
- no Stage-6+ work pulled forward

### S5-00 completion record

**Review range:** `06adf01..0f3b986` (S4-05 completion through S5-00)

**Implementation:**

1. **`src/dnd_assistant/retrieval/types.py`** — Canonical retrieval-layer types:
   - `MatchKind` — StrEnum with 5 values ordered by retrieval precedence: `EXACT_ID`, `EXACT_NAME`, `EXACT_ALIAS`, `FUZZY_NAME`, `FTS`
   - `SearchQuery` — Pydantic model with validated `text` field and optional `entity_types` filter; `extra="forbid"`
   - `SearchHit` — Pydantic model with `entity_id`, `match_kind`, optional `score`; `extra="forbid"`
   - `Resolved` — Pydantic model with `entity_id` and `match_kind`; `extra="forbid"`
   - `Ambiguous` — Pydantic model with `candidates: Sequence[SearchHit]`; `extra="forbid"`
   - `NotFound` — Pydantic model with `query` string; `extra="forbid"`
   - `ResolutionOutcome = Resolved | Ambiguous | NotFound` — explicit union type
   - `_validate_search_query()` — strict validation: empty/whitespace/control rejected, printable Unicode allowed
   - `SearchQueryStr` — annotated validated string type

2. **`src/dnd_assistant/retrieval/service.py`** — Retrieval service protocols:
    - `SearchService` — runtime-checkable Protocol with `search()` and `get_by_id()`; read-only, player-visibility safety documented, no Ollama/ModelGateway dependency
    - `EntityResolver` — runtime-checkable Protocol with `resolve()` returning `ResolutionOutcome`; deterministic, no LLM dependency, ambiguity is a normal outcome

3. **`src/dnd_assistant/retrieval/__init__.py`** — Public API exports via `__all__`

4. **`tests/unit/test_retrieval_contracts.py`** — 57 tests:
   - Import smoke tests (10 tests)
   - Public exports verification (1 test)
   - MatchKind values, members, precedence order, str representation (4 tests)
   - SearchQuery construction, entity-type filtering, Unicode, extra-forbidden, validation (empty/whitespace/control/type coercion — 17 tests)
   - SearchHit construction, exact/fuzzy/FTS scores, zero score, extra-forbidden (6 tests)
   - Resolved/Ambiguous/NotFound construction and extra-forbidden (7 tests)
   - ResolutionOutcome union semantics, mutual exclusivity, type args (5 tests)
   - SearchService protocol: runtime-checkable, methods, concrete class satisfaction (3 tests)
   - EntityResolver protocol: runtime-checkable, resolve method, concrete class satisfaction (3 tests)
   - Architectural boundaries: no storage/models/tools/session/sqlite/rapidfuzz imports (6 tests)

**Aliases policy confirmed:** Aliases remain extra-frontmatter metadata read from `VaultDocument.extra_frontmatter["aliases"]`. No `aliases` field was added to the base `Entity` model. `Entity.extra="forbid"` is preserved.

**Player-visibility policy confirmed:** `SearchService` and `EntityResolver` docstrings explicitly state that non-player-visible entities (`Visibility.DM`, `Visibility.SYSTEM`) must not appear in results. No unrestricted visibility override is exposed.

**Match-provenance semantics:** `MatchKind` enum values are ordered by retrieval precedence. Scores from different `MatchKind` values are not directly comparable. `EXACT_ID`/`EXACT_NAME`/`EXACT_ALIAS` have `score=None`; `FUZZY_NAME` has RapidFuzz ratio (0.0–100.0); `FTS` score is source-specific and finalized by the concrete S5-03 FTS implementation (when present it must be finite).

**Validation rules introduced:**
- `SearchQuery.text`: non-empty after stripping, printable Unicode, no control characters, strict string type
- `SearchQuery`, `SearchHit`, `Resolved`, `Ambiguous`, `NotFound`: `extra="forbid"`

**Quality-gate results:**
- `uv run pytest tests/unit/test_retrieval_contracts.py` — 57 passed
- `uv run pytest` (full suite) — 1556 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 171 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- S5-01 not started (no exact ID/name/alias search implementation)
- S5-02 not started (no RapidFuzz, no fuzzy matching)
- S5-03 not started (no SQLite database, no FTS schema)
- S5-04 not started (no EntityResolver implementation)
- S5-05 not started (no golden Vault integration)
- S5-06 not started (no Stage 5 final verification)
- Stage 6+ not started (no session runtime, tools, model, agent, changeset work)
- No RapidFuzz called anywhere in retrieval contracts
- No SQLite database or FTS tables created
- No actual search/resolution implementation
- No storage/domain reverse dependencies
- No model/Ollama/tool/session-runtime dependency
- No `dict[str, Any]` placeholders
- No aliases added to base Entity model
- No ADR required (all architectural decisions follow established patterns: Protocol for contracts, Pydantic with `extra="forbid"`, StrEnum for typed enums, separate types/service modules)

### S5-C00 correction record

**Independent review found 6 defects in the S5-00 implementation.**
**Correction range:** `ee086a3` (S5-00 completion) through S5-C00

**Defects confirmed and fixed:**

| Defect | Description | Fix |
|---|---|---|
| C00-1 | Boundary tests used `module.__name__` string checks that did not inspect actual imports | Replaced with real `sys.modules`-based import analysis (matching `tests/contract/test_boundaries.py` pattern) + AST-based source inspection. Added reverse-boundary checks: `domain !→ retrieval`, `storage !→ retrieval`. |
| C00-2 | `Ambiguous(candidates=[])` was allowed, overlapping semantically with `NotFound` | Added `@model_validator` rejecting empty candidates. `Ambiguous` now requires at least one candidate. Also added `NotFound.query` validation (non-empty, printable). |
| C00-3 | `SearchHit` score rules were documented but not enforced by the model | Added `@model_validator` enforcing: exact matches → `score=None`; `FUZZY_NAME` → finite `[0.0, 100.0]`; `FTS` → `None` or finite numeric. `BeforeValidator` rejects `bool` before Pydantic coercion. |
| C00-4 | `search_by_type` returned `SearchHit` without a valid `MatchKind` | Removed from `SearchService` protocol. `SearchQuery.entity_types` already provides type filtering. `list_entities(entity_type=...)` remains available in VaultRepository. |
| C00-5 | Player-visibility wording implied a privileged escape hatch that does not exist | Reworded to state unambiguously: only `Visibility.PLAYER` may be returned; `Visibility.DM`/`SYSTEM` must never be returned; no visibility override is exposed. |
| C00-6 | S5-00 was `[ ]` in task list despite having a completion record | Changed to `[x]`. S5-01 remains `[ ]`. |

**Production changes:**
- `src/dnd_assistant/retrieval/types.py` — added `math` import, `_validate_score` BeforeValidator, `SearchHit._validate_score_by_match_kind` model validator, `Ambiguous._validate_candidates_not_empty` model validator, `NotFound._validate_query` model validator; removed `Field` import (replaced by `Annotated` usage)
- `src/dnd_assistant/retrieval/service.py` — removed `search_by_type` method from `SearchService` protocol; tightened player-visibility docstrings in both `SearchService` and `EntityResolver`

**Test changes:**
- `tests/unit/test_retrieval_contracts.py` — rewrote `TestBoundaries` with real `sys.modules` cleanup + AST source inspection (12 tests, was 6); added reverse-boundary checks (2 tests); replaced `Ambiguous(candidates=[])` with valid single-candidate usage; added `NotFound` validation tests (5 tests); added `SearchHit` score validation tests (20 parametrized tests); removed `search_by_type` from protocol tests

**Test count:** 100 tests (was 57), all passed

**Scope exclusions confirmed:**
- S5-01 not started (no exact ID/name/alias search implementation)
- S5-02 not started (no RapidFuzz, no fuzzy matching)
- S5-03 not started (no SQLite database, no FTS schema)
- S5-04 not started (no EntityResolver implementation)
- S5-05 not started (no golden Vault integration)
- S5-06 not started (no Stage 5 final verification)
- Stage 6+ not started (no session runtime, tools, model, agent, changeset work)
- No RapidFuzz called anywhere in retrieval contracts
- No SQLite database or FTS tables created
- No actual search/resolution implementation
- No storage/domain reverse dependencies
- No model/Ollama/tool/session-runtime dependency
- No `dict[str, Any]` placeholders
- No aliases added to base Entity model
- No ADR required (all corrections are local to existing contracts/tests; no architectural boundary changed)

### S5-C01 correction record

**AST dependency-boundary verification fix.**

**Defect confirmed:**
- `_ast_imports()` used `alias.name.split(".")[0]` and `node.module.split(".")[0]`, collapsing all dotted import paths to their first segment.
- A forbidden import such as `from dnd_assistant.storage import VaultRepository` was represented as `dnd_assistant` (not `dnd_assistant.storage`), while the boundary test compared against short names like `storage`, `models`, etc.
- Therefore the AST check did **not** detect forbidden internal `dnd_assistant.*` imports.
- The runtime `sys.modules` checks are useful but cannot replace AST verification because imports under `TYPE_CHECKING`, conditional branches, or otherwise non-executed code may not appear in `sys.modules`.

**Production fix (test file only — no production source changed):**
1. **`_ast_imports()`** — removed `.split(".")[0]` from both `alias.name` and `node.module` collection. Full dotted paths are now preserved (e.g. `dnd_assistant.storage`, `dnd_assistant.models.gateway`, `rapidfuzz.fuzz`).
2. **`_has_forbidden_prefix()`** — new static helper with prefix-aware matching: `module == prefix or module.startswith(prefix + ".")`.
3. **Forbidden-prefix sets** — changed from short names (`{"storage", "models", ...}`) to full prefixes (`{"dnd_assistant.storage", "dnd_assistant.models", ...}`) using the new prefix-aware matcher.
4. **`TestAstImportChecker`** — new test class (17 tests) proving:
   - Full dotted paths are preserved (6 tests: `sqlite3`, `dnd_assistant.storage.types`, `from dnd_assistant.storage import ...`, `from dnd_assistant.models.gateway import ...`, `rapidfuzz.fuzz`, `dnd_assistant.tools.registry`)
   - Forbidden-prefix detection works correctly (8 tests: storage from-import, storage subpackage, models gateway, tools registry, sqlite3, rapidfuzz, allowed domain import, allowed retrieval import)
   - Regression proof: `split(".")[0]` would miss `dnd_assistant.storage.*`, `dnd_assistant.models.*`, `dnd_assistant.tools.*` (3 tests that would fail under the old buggy behaviour)

**Architectural nuance preserved:**
- The S5-00 boundary test does NOT encode a permanent rule that the entire future `dnd_assistant.retrieval` package can never import storage. Stage 5 comes after VaultRepository in dependency order, and later concrete retrieval implementations may legitimately consume read-only `VaultRepository` / `VaultDocument` contracts. The invariant is: retrieval contract/types modules remain provider/storage-implementation independent; domain/storage never depend upward on retrieval.

**Quality-gate results:**
- `uv run pytest tests/unit/test_retrieval_contracts.py` — 117 passed (was 100)
- `uv run pytest` (full suite) — 1616 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 171 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- No production source files changed (only test file `tests/unit/test_retrieval_contracts.py`)
- S5-00 = [x] (unchanged)
- S5-01 = [ ] (unchanged)
- No S5-01 implementation started
- No exact ID/name/alias search implementation
- No RapidFuzz search
- No SQLite/FTS
- No EntityResolver implementation
- No confidence thresholds
- No session context
- No CLI commands
- No tool layer
- No ModelGateway/Ollama
- No embeddings/vector DB

**Commit SHA:** `bf68b45`

**Historical test-count correction:**
- S5-C01 originally documented 25 tests for `TestAstImportChecker`.
- That metadata was incorrect. The actual S5-C01 increase was **17 targeted test cases** (100 → 117), and the S5-C01 record has now been corrected in place without rewriting Git history.

### S5-C02 correction record

**Acceptance-review defect — relative imports not resolved:**

The S5-C01 AST import checker preserved full dotted paths for absolute imports but did **not** handle relative `ImportFrom` nodes.  `node.level` was ignored, so inside `dnd_assistant.retrieval.service` an import such as:

```python
from ..storage import VaultRepository
```

was represented as `"storage"` instead of `"dnd_assistant.storage"` and therefore bypassed forbidden-prefix matching against `"dnd_assistant.storage"`.

**Production fix (test file only — no production source changed):**

1. **`_get_package_name(module_path)`** — new module-level helper that determines whether a module path refers to a package (has `__path__`) or a submodule, returning the appropriate package name.

2. **`_resolve_relative_import(module_path, level, relative_module)`** — new module-level helper that resolves a relative `ImportFrom` (using `node.level` and `node.module`) to an absolute module path using deterministic Python-native logic (not `importlib.util.resolve_name`).

3. **`_parse_imports_from_source(source, *, module_path=None)`** — new shared module-level helper that replaces both `TestBoundaries._ast_imports()` and `TestAstImportChecker._parse_imports()`.  When `module_path` is provided, relative imports are resolved to absolute paths.  When `module_path` is `None`, relative imports are collected as-is (for regression testing).

4. **`_has_forbidden_prefix()`** — extracted to a module-level function shared by both `TestBoundaries` and `TestAstImportChecker`.

5. **`TestBoundaries._ast_imports()`** — refactored to delegate to `_parse_imports_from_source(source, module_path=module_path)`.

6. **`TestAstImportChecker._parse_imports()`** — refactored to delegate to `_parse_imports_from_source(source)`.

7. **`TestAstImportChecker._has_forbidden_prefix()`** — refactored to delegate to the module-level `_has_forbidden_prefix`.

8. **AST documentation corrected** — `_ast_imports()` and `_parse_imports_from_source()` docstrings now accurately state that `ast.walk()` inspects all syntactically present import nodes (including `TYPE_CHECKING` blocks, functions, classes, and conditional branches), not only top-level imports.

**Relative-import regression tests added (7 tests in `TestAstImportChecker`):**

| Test | Source | Context | Resolved | Expected |
|---|---|---|---|---|
| `test_relative_retrieval_types_allowed` | `from .types import SearchHit` | `retrieval.service` | `dnd_assistant.retrieval.types` | NOT rejected |
| `test_relative_domain_import_allowed` | `from ..domain.types import EntityId` | `retrieval.service` | `dnd_assistant.domain.types` | NOT rejected |
| `test_relative_storage_import_detected` | `from ..storage import VaultRepository` | `retrieval.service` | `dnd_assistant.storage` | DETECTED |
| `test_relative_models_import_detected` | `from ..models.gateway import ModelGateway` | `retrieval.service` | `dnd_assistant.models.gateway` | DETECTED |
| `test_relative_tools_import_detected` | `from ..tools.registry import ToolRegistry` | `retrieval.service` | `dnd_assistant.tools.registry` | DETECTED |
| `test_regression_old_code_missed_relative_storage` | `from ..storage import VaultRepository` | old vs new | old: `"storage"`, new: `"dnd_assistant.storage"` | Regression proof |
| `test_regression_old_code_missed_relative_models` | `from ..models.gateway import ModelGateway` | old vs new | old: `"models.gateway"`, new: `"dnd_assistant.models.gateway"` | Regression proof |

**Quality-gate results:**
- `uv run pytest tests/unit/test_retrieval_contracts.py` — 124 passed (was 117)
- `uv run pytest` (full suite) — 1623 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 171 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- No production source files changed (only test file `tests/unit/test_retrieval_contracts.py`)
- S5-00 = [x] (unchanged)
- S5-01 = [ ] (unchanged)
- No S5-01 implementation started
- No exact ID/name/alias search implementation
- No RapidFuzz search
- No SQLite/FTS
- No EntityResolver implementation
- No confidence thresholds
- No session context
- No CLI commands
- No tool layer
- No ModelGateway/Ollama
- No embeddings/vector DB

### S5-C03 correction record

**ImportFrom alias gap — bare ``from pkg import sub`` not detectable.**

**Defect confirmed:**
- `_parse_imports_from_source()` recorded the resolved `ImportFrom.module` (e.g. `dnd_assistant`) but did not qualify alias names.
- `from dnd_assistant import storage` produced only `{"dnd_assistant"}`, not `{"dnd_assistant", "dnd_assistant.storage"}`.
- The same issue applied to bare relative imports: `from .. import storage` inside `dnd_assistant.retrieval.service` resolved to `dnd_assistant` but did not produce `dnd_assistant.storage`.
- `from package import *` was not affected (no meaningful `package.*` candidate).

**Production fix (test file only — no production source changed):**

1. **`_add_qualified_aliases(result, base_module, node)`** — new module-level helper that adds `base_module.alias_name` for each named alias in an `ImportFrom` node. `from package import *` is silently skipped.
2. **`_parse_imports_from_source()`** — calls `_add_qualified_aliases` after adding the resolved base module for both absolute and resolved-relative `ImportFrom` nodes. Relative imports without `module_path` are unchanged (collected as-is).

**Alias-gap regression tests added (9 tests in `TestAstImportChecker`):**

| Test | Source | Context | Verifies |
|---|---|---|---|
| `test_absolute_alias_storage_detected` | `from dnd_assistant import storage` | — | `dnd_assistant.storage` detectable |
| `test_absolute_alias_models_detected` | `from dnd_assistant import models` | — | `dnd_assistant.models` detectable |
| `test_absolute_alias_tools_detected` | `from dnd_assistant import tools` | — | `dnd_assistant.tools` detectable |
| `test_relative_alias_storage_detected` | `from .. import storage` | `retrieval.service` | `dnd_assistant.storage` detectable |
| `test_relative_alias_models_detected` | `from .. import models` | `retrieval.service` | `dnd_assistant.models` detectable |
| `test_relative_alias_tools_detected` | `from .. import tools` | `retrieval.service` | `dnd_assistant.tools` detectable |
| `test_absolute_alias_domain_allowed` | `from dnd_assistant import domain` | — | NOT rejected |
| `test_relative_dot_types_allowed` | `from . import types` | `retrieval.service` | NOT rejected |
| `test_star_import_no_alias_candidate` | `from dnd_assistant import *` | — | No `dnd_assistant.*` produced |

**Existing tests preserved:**
- All C01/C02 regression tests pass unchanged (expected sets updated for new alias candidates).

**Historical S5-C01 metadata corrected:**
- S5-C01 originally documented 25 tests for `TestAstImportChecker`. That metadata was incorrect. The actual S5-C01 increase was 17 targeted test cases (100 → 117), and the S5-C01 record has now been corrected in place without rewriting Git history.
- The false explanation `"The 25 figure was the count within TestAstImportChecker alone"` has been removed.

**Quality-gate results:**
- `uv run pytest tests/unit/test_retrieval_contracts.py` — 133 passed (was 124; +9 alias-gap regression tests)
- `uv run pytest` (full suite) — 1632 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 171 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- No production source files changed (only test file `tests/unit/test_retrieval_contracts.py`)
- S5-00 = [x] (unchanged)
- S5-01 = [ ] (unchanged)
- No S5-01 implementation started
- No exact ID/name/alias search implementation
- No RapidFuzz search
- No SQLite/FTS
- No EntityResolver implementation
- No confidence thresholds
- No session context
- No CLI commands
- No tool layer
- No ModelGateway/Ollama
- No embeddings/vector DB

### S5-C04 correction record

**Contract-documentation consistency cleanup discovered during S5-01 preparation.**

**Review range:** S5-C03 completion through S5-C04

**Defects confirmed and corrected:**

| Defect | Description | Fix |
|---|---|---|
| C04-1 | `SearchHit` docstring and `score` field docstring stated FTS score is "negative float, closer to 0 means better match". This is premature — S5-03 has not yet implemented the concrete FTS5 ranking policy. | Replaced with source-agnostic wording: FTS score is source-specific and finalized by the concrete FTS implementation; when present it must be finite. |
| C04-2 | `Ambiguous` class docstring said "Multiple candidates could match". `ResolutionOutcome` docstring said "multiple candidates matched; clarification needed". `EntityResolver` docstring and `resolve()` return docs used similar phrasing. The accepted invariant allows `Ambiguous(candidates=[single_low_confidence_candidate])`, so documentation must distinguish candidate count from confidence/uniqueness. | Updated all relevant docstrings to use consistent semantics: `Resolved` = confidently identifies one unique entity; `Ambiguous` = one or more plausible candidates exist, but unique confident resolution cannot be made; `NotFound` = no candidate exists. |
| C04-3 | S5-00 canonical summary still described `SearchService` as having `search_by_type()`. FTS score semantics still stated "negative float". Ambiguous semantics still said "multiple candidates". | Corrected to: `SearchService` has only `search()` and `get_by_id()`. FTS score semantics deferred to S5-03. Ambiguous described as 1+ candidates requiring clarification. |

**Production changes:**
- `src/dnd_assistant/retrieval/types.py` — corrected `MatchKind.FTS` docstring, `SearchHit` class docstring, `SearchHit.score` field docstring, `Ambiguous` class docstring, `ResolutionOutcome` docstring
- `src/dnd_assistant/retrieval/service.py` — corrected `EntityResolver` class docstring, `EntityResolver.resolve()` return documentation

**Test changes:**
- `tests/unit/test_retrieval_contracts.py` — added `TestFtsScoreContract` (11 cases: 6 accepted scores, 5 rejected scores) verifying FTS accepts `None`, negative, zero, and positive finite scores; rejects NaN, inf, -inf, bool. Added `TestAmbiguousSemantics` (3 cases) verifying single-candidate and multi-candidate `Ambiguous` are accepted, zero candidates rejected. Added `TestSearchServiceSurface` (3 cases) verifying `search` and `get_by_id` present and `search_by_type` absent.
- **Total: 17 new targeted pytest cases** (was stale `7/2/2` in earlier records)

**Scope exclusions confirmed:**
- No runtime retrieval implementation changed
- No S5-01 production implementation started
- S5-00 = [x] (unchanged)
- S5-01 = [ ] (unchanged)
- No exact ID/name/alias search implementation
- No RapidFuzz search
- No SQLite/FTS
- No EntityResolver implementation
- No confidence thresholds
- No session context
- No CLI commands
- No tool layer
- No ModelGateway/Ollama
- No embeddings/vector DB


### S5-01 completion record

**Starting branch:** `main`
**Starting local SHA:** `fa7b48cde28486cd2fb737b8c5f1a0b534327a1b`
**Starting upstream SHA:** `fa7b48cde28486cd2fb737b8c5f1a0b534327a1b`

**Scope implemented:**
Exact stable-ID, exact canonical name, and exact alias retrieval with player-visibility enforcement, entity-type filtering, deterministic ordering, strict limit validation, and repository error propagation.

**Concrete SearchService implementation:**
`dnd_assistant.retrieval.search.VaultSearchService` — depends on `VaultRepository` (injected), reads `VaultDocument` for entity data and alias extra-frontmatter.

**Exact-ID semantics:**
Literal string comparison (no case folding, no normalisation). `EntityId` comparison is exact.

**Exact-name normalisation semantics:**
`strip → NFC normalise → casefold()` then equality comparison. No substring, prefix, token, fuzzy, or transliteration matching.

**Exact-alias normalisation semantics:**
Same `strip → NFC → casefold()` policy as name matching.

**Alias extra-frontmatter parsing policy:**
Fail-closed: list/tuple of strings accepted (non-string entries ignored, duplicates collapsed). Scalar string treated as malformed → no aliases. Missing/None → no aliases.

**Match-tier precedence:**
`EXACT_ID > EXACT_NAME > EXACT_ALIAS`. Only the highest-precedence non-empty tier is returned.

**Duplicate/collision behaviour:**
Multiple entities with same canonical name → multiple `EXACT_NAME` hits. Multiple entities sharing an alias → multiple `EXACT_ALIAS` hits. Same entity name+alias → one hit (name tier wins).

**Deterministic ordering:**
Within a tier, sorted by `EntityId` ascending. Then `limit` applied.

**Entity-type filter behaviour:**
`None` or empty set → all types. Non-empty → only matching types. Applied before tier selection.

**Player visibility behaviour:**
Only `Visibility.PLAYER` entities are eligible. `Visibility.DM` and `Visibility.SYSTEM` are excluded before any matching. No visibility override exists.

**Hidden-ID behaviour:**
A hidden entity matching by exact ID is excluded before tier evaluation. A visible lower-tier match (e.g. alias) may still be returned. Hidden entities are observationally equivalent to missing entities.

**`get_by_id` behaviour:**
Returns `SearchHit(EXACT_ID)` for visible existing entity. Returns `None` for missing, DM, or SYSTEM entities. Repository `StorageError` propagates unchanged.

**Limit validation behaviour:**
Strict positive integer >= 1. `0`, negative, `bool`, `float`, `str`, `None` → `ValidationError`.

**Repository error propagation behaviour:**
`StorageError` from repository methods propagates unchanged. `NotFoundError` from `get_entity` → `None` (normal not-found). Other repository integrity failures are not swallowed.

**Public API/export changes:**
- `dnd_assistant.retrieval.search` — new module, exports `VaultSearchService`
- `dnd_assistant.retrieval.__init__` — added `VaultSearchService` to `__all__`

**Dependency-boundary changes:**
- `retrieval.search` imports `storage.types` (narrow read contracts: `VaultRepository`, `VaultDocument`)
- `retrieval.types` and `retrieval.service` remain storage-independent
- Boundary tests updated: contract modules verified via AST (not sys.modules), search module verified for no models/tools/application/session/ollama imports and only storage read-contract imports
- No `storage.atomic`, `storage.audit`, `storage.markdown`, `storage.paths`, `storage.patch`, `storage.vault_repository` imported

**S5-C04 bookkeeping correction:**
Corrected stale `7/2/2` test counts to actual `11/3/3` (17 total) in the S5-C04 record.

**Tests added/changed:**
- `tests/unit/test_exact_search.py` (new) — 58 tests covering protocol conformance, get_by_id, exact-ID/name/alias tiers, tier precedence, visibility, entity-type filters, ordering, limit validation, alias metadata edge cases, and repository error propagation
- `tests/unit/test_retrieval_contracts.py` — updated boundary tests: storage-contract independence verified via AST, added `test_retrieval_search_no_forbidden_imports`, `test_retrieval_search_storage_only_read_contracts`, updated SQLite/RapidFuzz checks to include `retrieval.search`, updated public exports test

**Targeted test result:**
`uv run pytest tests/unit/test_exact_search.py` — 58 passed

**Full pytest result:**
`uv run pytest` — 1709 passed, 34 skipped

**Ruff check result:**
All checks passed

**Ruff format result:**
173 files already formatted

**`dnd --help` result:**
CLI smoke test OK (Russian UI)

**`git diff --check` result:**
No whitespace errors

**Architecture review:**
- `VaultSearchService` satisfies `SearchService` protocol
- Repository injected, not constructed internally
- No direct filesystem access from `retrieval.search`
- No Vault writes
- No golden-Vault modifications
- No RapidFuzz, SQLite, FTS, or EntityResolver implementation
- Domain/storage do not depend on retrieval
- Contract modules remain storage-independent

**Out-of-scope review:**
No RapidFuzz, no fuzzy matching, no SQLite, no FTS5, no EntityResolver, no CLI search commands, no session runtime, no ToolRegistry, no ModelGateway/Ollama, no embeddings, no vector DB. S5-02 remains NOT STARTED.

**Defects discovered/corrections made:**
- `search.py` initially imported `SearchService` (unused) — removed
- `test_exact_search.py` initially imported `SearchHit` (unused) — removed
- `FakeRepository.get_entity` raised `NotFoundError` without `from None` — fixed
- `test_retrieval_contracts_no_storage` used `sys.modules` check which caught transitive imports via `__init__` — changed to AST-based check

**ADR assessment:**
No ADR required. All architectural decisions follow established patterns (Protocol for contracts, injected repository dependency, deterministic matching, strict input validation).

**Resulting Stage-5 status:**
- S5-00 = [x]
- S5-01 = [x]
- S5-02 = [ ]
- S5-03 = [ ]
- S5-04 = [ ]
- S5-05 = [ ]
- S5-06 = [ ]
- Stage 5 = IN PROGRESS

**Explicit confirmation:**
Fuzzy/RapidFuzz/SQLite/FTS/EntityResolver work has NOT started. S5-02 = [ ].


### S5-C05 correction record

**Acceptance-review defects:**

1. **Malformed alias control-character defect (C05-1):**
   - `_extract_aliases()` in `search.py` called `entry.strip()` before `entry.isprintable()`.
   - Control characters such as `\t`, `\n`, `\r` were stripped first, after which the remaining printable text passed `isprintable()` and became a valid searchable alias.
   - This turned malformed Vault metadata (e.g. `"\tВарос"`, `"Варос\n"`, `"\rВарос"`) into legitimate alias matches.

2. **Stale top-level status header (C05-2):**
   - The canonical header said `Stage 4 — Calendar / DONE` while the Stage Progress table correctly said `Stage 5 — Retrieval + Entity Resolution / IN PROGRESS`.
   - S5-00 and S5-01 were already marked `[x]`.

**Production fix (C05-1):**
- Reordered validation in `_extract_aliases()`:
  - **Old order:** `isinstance(str)` → `strip()` → `non-empty` → `isprintable()`
  - **Corrected order:** `isinstance(str)` → `isprintable()` → `strip()` → `non-empty`
- The original value is now checked for printability before any stripping occurs.
- Ordinary printable spaces around a valid alias (e.g. `"  Варос  "`) are still correctly stripped because space is printable.
- Docstring updated to reflect the corrected order.

**Status-header fix (C05-2):**
- `Current stage:` changed from `Stage 4 — Calendar` to `Stage 5 — Retrieval + Entity Resolution`
- `Status:` changed from `DONE` to `IN PROGRESS`
- `Last updated:` changed from `2026-08-31 (S5-01)` to `2026-08-31 (S5-C05)`
- Stage Progress table was already correct and is preserved unchanged.

**Regression tests added (5 tests in `TestAliasMetadata` in `test_exact_search.py`):**

| Test | Aliases | Query | Expected |
|---|---|---|---|
| `test_leading_tab_alias_rejected` | `["\tВарос"]` | `"Варос"` | No alias hit |
| `test_trailing_newline_alias_rejected` | `["Варос\n"]` | `"Варос"` | No alias hit |
| `test_carriage_return_alias_rejected` | `["\rВарос"]` | `"Варос"` | No alias hit |
| `test_printable_space_alias_accepted` | `["  Варос  "]` | `"Варос"` | EXACT_ALIAS hit |
| `test_mixed_alias_list_control_chars_rejected` | `["\tBad Alias", "Good Alias", "Bad Alias\n"]` | `"Good Alias"` → 1 hit; `"Bad Alias"` → 0 hits | Only printable eligible |

**Preserved behavior:**
- Existing malformed scalar/non-string/null/duplicate tests unchanged.
- All S5-01 alias metadata edge cases preserved.
- No changes to `VaultRepository`, `VaultDocument.extra_frontmatter["aliases"]` policy, `Entity` schema, player-only visibility, visibility filtering before tier selection, entity-type filtering before tier selection, `EXACT_ID > EXACT_NAME > EXACT_ALIAS`, literal stable-ID comparison, name/alias `strip → NFC → casefold` comparison, deterministic EntityId ordering, strict positive integer `limit`, repository error propagation, `SearchService` signatures, or public `VaultSearchService` export.

**Quality-gate results:**
- `uv run pytest tests/unit/test_exact_search.py` — 63 passed (was 58; +5 regression tests)
- `uv run pytest` (full suite) — 1714 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 173 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Scope exclusions confirmed:**
- S5-01 = [x] (unchanged)
- S5-02 = [ ] (unchanged)
- No fuzzy matching, RapidFuzz, SQLite, FTS5, EntityResolver, session runtime, ToolRegistry, ModelGateway/Ollama, embeddings, or vector DB implementation.
- S5-02 remains NOT STARTED.


---
## Stage 3 — Vault Repository

### Goal

Implement the trusted Vault persistence layer for Obsidian Markdown/YAML entities, providing create, read, update, and append operations with atomic writes, optimistic concurrency, path safety, Markdown body preservation, and audit logging.

### Tasks

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

### S3-00 completion record

**Review range:** `22a21d3..HEAD` (Stage 2 completion through S3-00)

**Changes:**

1. **DEVELOPMENT_STATUS.md** — transitioned to Stage 3 IN PROGRESS, added S3-00 task inventory
2. **storage/types.py** (new) — storage-level types:
   - `VaultDocument` — wraps validated domain `Entity` + `extra_frontmatter` dict + Markdown `body`
   - `EntityDirectory` — StrEnum mapping EntityType to Vault subdirectories (Characters/NPCs, Locations, Quests, Items)
   - `VaultRepository` — runtime-checkable Protocol with create/get/list/patch/append signatures
3. **storage/__init__.py** — exports EntityDirectory, VaultDocument, VaultRepository
4. **storage/audit.py** — updated docstring to reflect Stage 3 ownership (implementation deferred to S3-04)
5. **tests/unit/test_storage_types.py** (new) — 27 tests covering VaultDocument construction/properties, EntityDirectory mapping, VaultRepository protocol structure, import smoke tests, and boundary checks

**Decisions made:**
- `VaultDocument` lives in `storage/` (not `domain/`) — persistence concern, not a domain concept
- Extra frontmatter preserved as `dict[str, object]` — no weakening of `Entity.extra="forbid"`
- `VaultRepository` is a `Protocol` (not ABC) — follows Stage 1 deferred-contract pattern
- `EntityDirectory` is a `StrEnum` — simple, serializable, no premature path abstraction
- Patch/fact DTOs explicitly deferred to S3-06/S3-07 — no placeholder APIs invented

**Decisions intentionally deferred to later S3 tasks:**
- Markdown/YAML parser/serializer (S3-01)
- Filesystem entity scanning and path safety (S3-02)
- Atomic write primitive (S3-03)
- AuditRecord + AuditService (S3-04)
- create/get/list persistence (S3-05)
- patch_entity semantics and revision ownership (S3-06)
- append_entity_fact semantics (S3-07)
- Integration/failure tests (S3-08)
- Full Stage 3 verification (S3-09)

**ADR assessment:** No ADR required. All architectural decisions follow established project patterns (Protocol for deferred contracts, storage-level wrapper for persistence concerns, StrEnum for typed mappings).

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_types.py` — 27 passed
- `uv run pytest` (full suite) — 578 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 68 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S3-00:** None

**Code/test changes during S3-00:** 5 files (3 modified, 2 new), focused on storage contracts only.

### S3-01 completion record

**Review range:** S3-00 completion through S3-01

**Changes:**

1. **storage/markdown.py** (new) — pure-text Markdown/YAML document codec:
   - `parse(text: str) -> VaultDocument` — parses Obsidian Markdown with YAML frontmatter
   - `serialize(document: VaultDocument) -> str` — serializes back to Obsidian Markdown
   - Frontmatter delimiter: standalone `---` at start of document, closing `---` as standalone line
   - CRLF/LF delimiter support; body preservation character-for-character
   - Canonical Entity fields extracted via `Entity.model_validate()`; extras stored in `extra_frontmatter`
   - Collision detection: extra keys overlapping canonical Entity fields rejected with `ValidationError`
   - Non-string YAML keys rejected
   - Uses `ruamel.yaml` with `typ="safe"`, `default_flow_style=False`, `allow_unicode=True`
   - All errors translated to `dnd_assistant.errors.ValidationError` with original cause preserved
2. **storage/__init__.py** — exports `parse`, `serialize`
3. **tests/unit/test_storage_markdown.py** (new) — 71 tests covering:
   - Frontmatter boundary detection (7 tests)
   - Canonical parse (6 tests: minimal, all EntityTypes, tags, session refs, empty body, import)
   - Extra frontmatter (9 tests: scalar, list, nested, boolean, number, null, multiple keys, semantic round trip)
   - Body preservation (11 tests: empty, heading, blank lines, trailing newline, no trailing newline, CRLF source, `---` in body, code fences, wikilinks, Unicode, round trip, only newlines)
   - Invalid documents (15 tests: not a string, missing opener/closer, malformed YAML, sequence/scalar root, missing required fields, invalid type/revision/datetime, non-string keys, empty document, only opener, empty frontmatter)
   - Serialization (9 tests: round trips, collision rejection, canonical-first order, delimiter structure, import)
   - Round-trip integration (9 parametrized cases)
   - Import/boundary tests (5 tests: module importable, re-exported, no model/retrieval/tool imports)

**Codec API established:**
- `parse(text: str) -> VaultDocument`
- `serialize(document: VaultDocument) -> str`

**Frontmatter delimiter rules:**
- Opening `---` must be at position 0 of the document
- Closing `---` must be a standalone line (only whitespace allowed after `---`)
- A `---` inside YAML content (e.g. block scalars) does not terminate frontmatter
- A `---` inside Markdown body is not confused with frontmatter

**Canonical vs extra field split:**
- Canonical fields: `Entity.model_fields.keys()` (derived dynamically from Pydantic model)
- Extra fields: all other YAML mapping keys stored in `VaultDocument.extra_frontmatter`
- Collision during serialization: raises `ValidationError`

**YAML preservation guarantee:**
- Guaranteed: key/value semantic preservation through parse/serialize
- NOT guaranteed: YAML comments, anchors/aliases, scalar quote style, flow/block formatting, exact whitespace, key ordering, byte-identical output

**Markdown body preservation invariant:**
- `VaultDocument.body` is preserved character-for-character through `parse → serialize`
- No `.strip()`, `.rstrip()`, or whitespace normalisation applied

**Validation/error behaviour:**
- All parse/serialize failures produce `dnd_assistant.errors.ValidationError`
- Original parser/Pydantic exception preserved as `cause`
- Malformed documents never produce partially-valid Entity

**Round-trip guarantees:**
- `parse(serialize(document))` preserves: `entity` equality, `extra_frontmatter` semantic equality, `body` exact equality
- `serialize(parse(source))` preserves: semantic frontmatter equivalence, exact body

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_markdown.py` — 71 passed
- `uv run pytest tests/unit/test_storage_types.py` — 27 passed
- `uv run pytest` (full suite) — 652 passed
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 70 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Defects discovered during S3-01:** None

**Code/test changes during S3-01:** 3 files (1 modified, 2 new), focused on Markdown/YAML codec only.

**Scope exclusions confirmed:**
- No filesystem access, path validation, atomic writes, audit, repository CRUD, patch, append, locks, migrations, Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet.

### S3-02 completion record

**Review range:** S3-01 completion through S3-02 (including S3-02 correction)

**Changes (original S3-02):**

1. **storage/paths.py** (new) — Vault path safety and entity-file discovery:
   - `DiscoveredEntityFile` — immutable result type with `entity_type` and `path` properties; supports equality, hashing, repr; no EntityId or file contents
   - `entity_directory(vault_root, entity_type)` — resolves canonical entity directory path under vault root
   - `resolve_entity_path(vault_root, entity_type, relative_path)` — safe relative-path resolution with:
     - `..` traversal rejection (structural check, not resolved-path)
     - absolute path rejection
     - containment checks via `pathlib.relative_to` (inside entity directory AND inside vault root)
     - Markdown-only suffix enforcement (case-insensitive)
   - `discover_entity_files(vault_root, entity_type=None)` — recursive Markdown discovery:
     - scans only approved MVP entity directories (Characters/NPCs, Locations, Quests, Items)
     - ignores non-Markdown files, symlinked files, symlinked directories
     - missing entity directory yields zero candidates (no directory creation)
     - canonical entity path that exists as a file raises `StorageError`
     - deterministic ordering by Vault-relative POSIX path (casefold)
     - filesystem `OSError` translated to `StorageError` with cause preserved
   - Internal `_resolve_vault_root` — normalises to canonical absolute resolved path; rejects missing/non-directory roots
   - Internal `_has_traversal` — structural check for `..` components and absolute paths
   - No Markdown parsing, no EntityId inference from filenames, no file reading
2. **storage/__init__.py** — exports `DiscoveredEntityFile`, `discover_entity_files`, `entity_directory`, `resolve_entity_path`
3. **tests/unit/test_storage_paths.py** (new) — 58 tests (55 pass, 3 symlink tests skipped on Windows without symlink privileges)

**S3-02 correction (canonical-directory symlink hardening):**

1. **storage/paths.py** — added `_resolve_entity_directory(root, entity_type)` internal helper that:
   - inspects each existing path component beneath the vault root for symlinks before resolving
   - rejects any symlinked canonical path component with `StorageError`
   - verifies the resolved path remains inside the vault root
   - is reused by `entity_directory()`, `resolve_entity_path()`, and `discover_entity_files()`
   - also fixed stale `entity_dir` variable reference in `resolve_entity_path` error message
2. **storage/paths.py** — strengthened discovery sort key to `(casefolded_path, exact_path)` tuple for deterministic tie-breaking on case-sensitive filesystems
3. **tests/unit/test_storage_paths.py** — added 8 new tests (7 symlink-dependent, 1 source-inspection):
   - `TestCanonicalDirectorySymlinkRejection` class with 7 tests:
     - `test_entity_directory_rejects_direct_symlink_to_outside`
     - `test_discovery_rejects_direct_symlink_to_outside`
     - `test_entity_directory_rejects_symlink_to_another_entity_dir`
     - `test_discovery_rejects_symlink_to_another_entity_dir`
     - `test_parent_symlink_rejected_for_npc`
     - `test_parent_symlink_rejected_for_npc_discovery`
     - `test_parent_symlink_to_another_vault_dir_rejected`
   - `test_deterministic_ordering_tie_breaker` — verifies sort-key tuple contract via source inspection

**Path safety invariants established:**
- Vault root must exist and be a directory; normalised to canonical absolute resolved path
- `..` traversal is rejected structurally (not after resolution) — presence of `..` in any path component is sufficient for rejection
- Absolute paths are rejected at the structural check level
- Every accepted path is contained within its canonical entity directory AND within the vault root (verified via `pathlib.relative_to`)
- Entity paths must have `.md` suffix (case-insensitive)

**Discovery policy established:**
- Only four MVP entity directories are scanned: Characters/NPCs, Locations, Quests, Items
- Other Vault directories (Campaign, Sessions, Lore, etc.) are NOT scanned
- Discovery is recursive within each entity directory
- Symlinked directories are NOT traversed
- Symlinked files are NOT returned
- Missing entity directories yield zero candidates (no directory creation)
- Canonical entity path that exists as a non-directory raises `StorageError`
- Results are deterministically ordered by Vault-relative POSIX path (casefold primary, exact path secondary)

**Symlink policy established:**
- Discovery does NOT follow symlinked directories
- Symlinked files are NOT treated as entity-file candidates
- A symlink must never allow discovery to escape the vault root or an approved entity directory
- **Canonical entity-directory path components beneath the vault root must not be symlinks** — any symlink in the canonical path (e.g. `Vault/Locations` → outside, `Vault/Characters` → outside/NPCs, `Vault/Locations` → `Vault/Quests`) is rejected with `StorageError` before any resolution or discovery occurs
- Tests use `_can_symlink()` runtime check to skip when OS/environment cannot create symlinks

**Filesystem error behaviour:**
- `OSError` during directory iteration is translated to `StorageError` with original cause preserved
- `_resolve_vault_root` translates `OSError`/`RuntimeError` to `StorageError`
- `resolve_entity_path` uses `from None` for containment-check `ValueError` (programmer errors, not filesystem)

**Confirmed: discovery does NOT read/parse Markdown or infer EntityId from filename:**
- `DiscoveredEntityFile` has no `entity_id` attribute
- `paths.py` does not import from `storage.markdown`
- No file contents are read during discovery
- Test `test_filename_not_entity_id` explicitly verifies the absence of `entity_id`

**Quality-gate results (after S3-02 correction):**
- `uv run pytest tests/unit/test_storage_paths.py` — 56 passed, 10 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 163 passed, 10 skipped
- `uv run pytest` (full suite) — 714 passed, 10 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 72 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-02:** Canonical entity-directory resolution (`entity_directory`, `resolve_entity_path`, `discover_entity_files`) did not check whether the canonical directory path itself contained symlinks before calling `.resolve()`, which could allow symlink-based escape or cross-type redirection. Fixed by introducing `_resolve_entity_directory()` with pre-resolution symlink inspection of each existing path component beneath the vault root.

**Code/test changes during S3-02 (original):** 4 files (2 modified, 2 new), focused on path safety and entity discovery only.

**Code/test changes during S3-02 correction:** 2 files modified (storage/paths.py, tests/unit/test_storage_paths.py), focused on canonical-directory symlink hardening and deterministic sort tie-breaker.

**Scope exclusions confirmed:**
- No Markdown parsing changes
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No duplicate EntityId checks, repository ID index/cache, SQLite
- No filename generation or directory creation for entity persistence
- No atomic write, fsync, audit JSONL, revision increments, locks, migrations
- No Calendar, Retrieval/EntityResolver, Session runtime, Tool layer, ModelGateway, or ChangeSet

**Stage 3 status:** IN PROGRESS — S3-04 complete.

### S3-03 completion record

**Review range:** S3-02 correction through S3-03

**Changes:**

1. **storage/atomic.py** (new) — atomic text-write primitive:
   - `atomic_write_text(target, content, *, validator)` — single public function
   - Temporary sibling file created via `tempfile.mkstemp` in the same parent directory as target
   - Temporary naming pattern: `.<target-name>.<random>.tmp`
   - UTF-8 writing with `newline=""` to prevent Windows `\n` → `\r\n` translation
   - Flush + `os.fsync` before validation
   - Required `validator(content)` callback runs after fsync, before `os.replace`
   - `os.replace(temp_path, target_path)` for atomic replacement
   - Target must be absolute; relative paths rejected with `StorageError`
   - Existing target symlink rejected with `StorageError`
   - Existing target directory rejected with `StorageError`
   - Missing parent directory rejected with `StorageError` (no directory creation)
   - Filesystem `OSError` translated to `StorageError` with cause preserved
   - `ValidationError` from validator propagates unchanged (not translated to `StorageError`)
   - Temporary file cleaned up on failure (best-effort, does not mask primary error)
   - No domain Entity import, no Markdown codec import, no audit import

2. **storage/__init__.py** — exports `atomic_write_text`

3. **tests/unit/test_storage_atomic.py** (new) — 36 tests + 1 skipped:

   **Success (11 tests):**
   - Create missing target, replace existing target
   - Unicode preservation (Cyrillic, CJK, Arabic)
   - LF preservation (no `\r\n` translation)
   - CRLF preservation (exact bytes via `read_bytes()`)
   - No trailing-newline modification
   - Trailing newline preserved
   - Mixed newlines preserved
   - Validator called with content
   - No temp files remain after success
   - Validator return value ignored

   **Operation ordering (1 test):**
   - Behavioural verification: `fsync < validator < replace` via monkeypatched `os.fsync`/`os.replace`

   **Validation failure (4 tests):**
   - Existing target unchanged after validator raises `ValidationError`
   - Missing target remains absent
   - Validator exception propagates unchanged (not translated to `StorageError`)
   - Temporary file removed after validation failure

   **fsync failure (3 tests):**
   - `StorageError` raised with `OSError` cause preserved
   - Original target unchanged
   - Temporary file cleaned

   **os.replace failure (3 tests):**
   - `StorageError` raised with `OSError` cause preserved
   - Original target unchanged
   - Temporary file cleaned

   **Temp creation failure (2 tests):**
   - `tempfile.mkstemp` patched to raise `OSError` → `StorageError` with cause
   - Original target unchanged

   **Path state (5 tests):**
   - Missing parent rejected
   - Parent regular file rejected
   - Target directory rejected
   - Target symlink rejected (skipped on Windows without symlink privileges)
   - Relative path rejected

   **Same-directory temp invariant (1 test):**
   - Temp file parent == target parent (verified via `os.replace` interception)

   **Public boundaries (7 tests):**
   - Module importable
   - `atomic_write_text` re-exported from `storage`
   - No `domain.entity` import
   - No `storage.markdown` import
   - No `models` import
   - No `retrieval` import
   - No `tools` import

**Atomic-write API established:**
- `atomic_write_text(target, content, *, validator)` — single function, no classes
- Target must be absolute; parent must exist; target must not be a directory or symlink
- Temporary file created beside target (same filesystem for `os.replace`)
- UTF-8 with `newline=""` — exact newline preservation
- Lifecycle: `write → flush → fsync → validator → close → os.replace`
- `ValidationError` propagates unchanged; `OSError` → `StorageError` with cause
- Best-effort temp cleanup on failure; does not mask primary error

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_atomic.py` — 36 passed, 1 skipped
- `uv run pytest tests/unit/test_storage_atomic.py tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 199 passed, 11 skipped
- `uv run pytest` (full suite) — 750 passed, 11 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 74 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-03:**
- Initial `except Exception` block in `atomic_write_text` re-raised `OSError` directly instead of translating to `StorageError`. Fixed by adding explicit `except OSError` → `StorageError` translation.
- `ValidationError` was not imported in `atomic.py`. Fixed by adding the import.
- CRLF preservation tests used `read_text()` which translates `\r\n` to `\n` on Windows. Fixed by using `read_bytes().decode("utf-8")`.
- Module-level monkeypatches (`atomic_mod._create_temp`, `atomic_mod._write_content`) failed when running in the full test suite due to module identity issues. Fixed by patching `tempfile.mkstemp` via `unittest.mock.patch`.

**Code/test changes during S3-03:** 4 files (2 modified, 2 new), focused on atomic write primitive only.

**Scope exclusions confirmed:**
- No VaultRepository concrete class
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No revision increment or optimistic concurrency
- No audit JSONL or AuditService
- No locks, migrations, directory creation
- No filename generation or stable-ID lookup
- No Markdown codec changes
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet
- S3-04 was NOT started

### S3-03 correction (exception and symlink handling)

**Review range:** S3-03 original through S3-03 correction

**Changes:**

1. **storage/atomic.py** — four corrections:

   **1a. Dangling/broken symlink rejection (Correction 1):**
   - `_validate_target()` now checks `target_path.is_symlink()` **before** `target_path.exists()`.
   - `Path.exists()` follows symlinks and returns `False` for dangling/broken destinations, so the old ordering allowed dangling symlinks to pass through undetected.
   - A dangling symlink is now correctly rejected with `StorageError` (same as any other symlink).

   **1b. `BaseException` removed (Correction 2):**
   - The old `except BaseException: cleanup; raise` block is removed.
   - Cleanup is now structured via `finally:` which runs for all exit paths including `KeyboardInterrupt` and `SystemExit`.
   - `except StorageError: raise` (re-raise without cleanup duplication) + `except Exception: cleanup; raise` + `finally: cleanup` — the `finally` call to `_cleanup_temp` is safe because `_cleanup_temp` already performs best-effort cleanup without masking the active exception.
   - `KeyboardInterrupt` and `SystemExit` now propagate immediately while still getting best-effort temp cleanup from `finally`.

   **1c. Validator exception transparency (Correction 3):**
   - `validator(content)` runs **outside** any `OSError`-translation boundary.
   - Implementation-owned filesystem operations (`_write_and_fsync`, `_os_replace`) each have their own narrow `OSError → StorageError` translation.
   - The validator is called between these operations, so any exception it raises (including `OSError`) propagates unchanged — never translated to `StorageError`.
   - `ValidationError` import removed from `atomic.py` since the module no longer needs to reference it for exception handling.

   **1d. Simplified lifecycle (Correction 4):**
   - `_write_content` + `_flush_and_fsync` + `_close_temp` replaced by single `_write_and_fsync(temp_path, content)` helper.
   - New helper: `open → write → flush → fsync → close` in one context manager — no reopening for fsync, no ceremonial `_close_temp`.
   - `_os_replace(src, dst)` added as a narrow `OSError → StorageError` wrapper for `os.replace`.
   - Final lifecycle: `create temp → write+flush+fsync+close → validate → os.replace`.
   - File descriptor is closed before validation and replacement (Windows-safe).

2. **tests/unit/test_storage_atomic.py** — new tests:

   **TestDanglingSymlink (4 tests, skipped on Windows without symlink privileges):**
   - `test_dangling_symlink_rejected` — dangling symlink raises `StorageError`
   - `test_dangling_symlink_remains_unmodified` — symlink still exists, still dangling after rejection
   - `test_dangling_symlink_no_temp_left` — no temp files remain
   - `test_dangling_symlink_dest_not_created` — nonexistent destination is not created

   **TestValidatorExceptionTransparency (8 tests):**
   - `test_custom_validator_exception_propagates` — `CustomValidationError` escapes unchanged
   - `test_custom_validator_exception_target_unchanged` — existing target preserved
   - `test_custom_validator_exception_temp_cleaned` — temp cleaned after custom exception
   - `test_validator_oserror_propagates_unchanged` — `OSError` from validator is NOT `StorageError`
   - `test_validator_oserror_target_unchanged` — target preserved after validator `OSError`
   - `test_validator_oserror_temp_cleaned` — temp cleaned after validator `OSError`
   - `test_validator_keyboardinterrupt_propagates` — `KeyboardInterrupt` propagates (no `BaseException` catch)
   - `test_validator_keyboardinterrupt_temp_cleaned` — temp cleaned after `KeyboardInterrupt`

**Final exact atomic lifecycle:**

```
create temp
    ↓
open for UTF-8 text writing (newline="")
    ↓
write content
    ↓
flush
    ↓
os.fsync(fd)
    ↓
close (context-manager exit)
    ↓
validator(content)
    ↓
os.replace(temp, target)
```

**Invariant:** `fsync < validate < replace` — file descriptor closed before validate and replace.

**Validator exception semantics:**
- ANY exception from validator propagates unchanged (not translated to `StorageError`)
- This includes `ValidationError`, `OSError`, `KeyboardInterrupt`, `SystemExit`, custom exceptions
- Temp cleanup occurs via `finally` for all paths

**Filesystem OSError translation boundaries:**
- `_create_temp()` — own `OSError → StorageError`
- `_write_and_fsync()` — own `OSError → StorageError`
- `_os_replace()` — own `OSError → StorageError`
- `validator(content)` — NO translation boundary

**`BaseException` confirmation:**
- No `except BaseException` in the codebase
- `KeyboardInterrupt` and `SystemExit` propagate through `finally` cleanup

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_atomic.py` — 44 passed, 5 skipped
- `uv run pytest tests/unit/test_storage_atomic.py tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py` — 207 passed, 15 skipped
- `uv run pytest` (full suite) — 758 passed, 15 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 74 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-03 correction:** Three defects in the original S3-03 implementation:
1. Dangling/broken symlinks were not rejected (symlink check after `exists()` which follows links)
2. `except BaseException` caught `KeyboardInterrupt`/`SystemExit`
3. Validator exceptions (including `OSError`) could be caught by broad `except OSError` and translated to `StorageError`

**Code/test changes during S3-03 correction:** 2 files modified (storage/atomic.py, tests/unit/test_storage_atomic.py), focused on exception and symlink correctness only.

**Scope exclusions confirmed:**
- No VaultRepository concrete class
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No revision increment or optimistic concurrency
- No audit JSONL or AuditService
- No locks, migrations, directory creation
- No filename generation or stable-ID lookup
- No Markdown codec changes
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet
- S3-04 was NOT started

### S3-04 completion record

**Review range:** S3-03 correction through S3-04

**Changes:**

1. **storage/audit.py** (rewritten) — `AuditRecord` schema + `AuditService` implementation:

   **AuditRecord schema:**
   - `schema_version: Literal[1] = 1` — fixed at 1
   - `operation_id: str` — required, validated non-empty printable string
   - `real_time: AwareDatetime` — required, timezone-aware (naive rejected)
   - `session: str | None = None` — optional, validated when present
   - `operation: str` — required, validated non-empty printable string
   - `entity_id: EntityId | None = None` — optional, validated as domain EntityId
   - `before_hash: str | None = None` — optional, validated when present
   - `after_hash: str | None = None` — optional, validated when present
   - `source: str` — required, validated non-empty printable string (NOT domain Provenance)
   - `model_profile: str | None = None` — optional, validated when present
   - `prompt_version: str | None = None` — optional, validated when present
   - `model_config = {"extra": "forbid", "frozen": True}`

   **AuditService public API:**
   - `AuditService(log_path)` — constructor validates path preconditions
   - `.append(record)` — serializes record as JSONL, appends with flush+fsync
   - `.read_all()` — reads all persisted records in append order
   - `.log_path` — property returning the absolute log path

   **JSONL format:**
   - One JSON object per line, followed by `\n`
   - UTF-8 encoding, Unicode preserved, no pretty printing
   - Deterministic serialization via `model_dump(mode="json")` + `json.dumps(ensure_ascii=False, separators=(",", ":"))`

   **Append lifecycle:**
   ```
   open (append mode) → write → flush → fsync → close
   ```

   **Append-only guarantees:**
   - Never truncates or rewrites existing bytes
   - Existing bytes remain exact prefix after append
   - Does NOT use `atomic_write_text` for JSONL append

   **Explicit partial-failure limitation:**
   - Once bytes reach the filesystem, a later failure (e.g. fsync) may leave a complete or partial line
   - No rollback/truncation of uncertain appends
   - Corrupted tails detected during `read_all()`

   **read_all corruption behaviour:**
   - Missing file → empty list
   - Malformed JSON → `StorageError` with line number and cause
   - Invalid AuditRecord → `StorageError` with line number and cause
   - Blank line → `StorageError` with line number
   - Unknown fields in persisted record → `StorageError`
   - No silent skipping of bad records

   **Filesystem error translation:**
   - `OSError` during open/write/flush/fsync → `StorageError` with cause preserved
   - No `except BaseException`
   - `KeyboardInterrupt`/`SystemExit` propagate unchanged

   **Path preconditions:**
   - Must be absolute
   - Parent must exist and be a directory
   - Must not be an existing directory
   - Must not be a symlink (including dangling/broken)
   - No parent directory creation (caller responsibility)
   - Documented: path validation != Vault authorization

   **Architectural boundaries confirmed:**
   - AuditService does NOT touch entity files
   - Does NOT compute entity hashes
   - Does NOT use `atomic_write_text`
   - Does NOT implement repository write/audit orchestration
   - Does NOT import from `models`, `retrieval`, `tools`, `storage.markdown`, `domain.entity`
   - `source` is a validated string, NOT domain `Provenance`

2. **storage/__init__.py** — exports `AuditRecord`, `AuditService`

3. **tests/unit/test_storage_audit.py** (new) — 66 tests (64 passed, 2 skipped):

   **AuditRecord schema (30 tests):**
   - Minimal valid record (1 test)
   - schema_version default and fixed (2 tests)
   - Timezone-aware accepted, naive rejected (2 tests)
   - Full record with all optional fields (1 test)
   - EntityId validation and Unicode (2 tests)
   - Required string validation: empty, whitespace, non-printable for operation_id/operation/source (9 tests)
   - Optional string validation: empty, whitespace, None for session/hash/metadata (9 tests)
   - Unicode allowed in all string fields (1 test)
   - Unknown fields rejected (1 test)
   - Source not restricted to Provenance values (1 test)
   - Frozen immutability (1 test)

   **Service path validation (8 tests):**
   - Absolute accepted, relative rejected, missing parent, parent file, directory, symlink, dangling symlink, log_path property

   **Append (10 tests):**
   - Missing file created, one JSON line, exactly one `\n`, Unicode round-trip, multiple appends preserve order, existing bytes remain prefix, no truncation, fsync called, file closed

   **read_all (8 tests):**
   - Missing file → [], one record, multiple records preserve order, malformed JSON, schema-invalid record, blank line, unknown fields, no silent skip

   **Failure injection (3 tests):**
   - Open/write failure → StorageError with cause
   - fsync failure → StorageError with cause
   - fsync failure does not rewrite history

   **Boundary tests (7 tests):**
   - Module importable, re-exported, no entity/model/retrieval/tools/markdown import, no atomic_write_text usage

**Decisions made:**
- `source` is a validated string (NOT domain `Provenance`) — describes the actor/mechanism that performed the Vault operation, not how campaign knowledge entered the system
- `real_time` is caller-supplied `AwareDatetime` — AuditService does not own the system clock
- JSONL format: one record per line, UTF-8, no pretty printing
- Log path is injected by caller — no hardcoded audit filename
- Append-only: never truncate/rewrite, no rollback on partial failure
- `fsync` after every append
- Corruption detected on read, no automatic repair

**Decisions intentionally deferred to S3-05/S3-06:**
- Entity write + audit consistency semantics must be explicitly designed before repository write operations are accepted. The ordering between `entity atomic write` and `audit append` (and the consequences of one succeeding while the other fails) is not solved by this task.

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_audit.py` — 64 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_audit.py tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py` — 271 passed, 17 skipped
- `uv run pytest` (full suite) — 822 passed, 17 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 75 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-04:** None

**Code/test changes during S3-04:** 4 files (2 modified, 2 new), focused on AuditRecord schema and AuditService only.

**Scope exclusions confirmed:**
- No VaultRepository concrete class
- No create_entity, get_entity, list_entities, patch_entity, append_entity_fact
- No revision increment or optimistic concurrency
- No entity hash computation
- No locks, migrations, directory creation
- No filename generation or stable-ID lookup
- No Markdown codec changes
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, or ChangeSet
- S3-05 was NOT started

### S3-05 completion record

**Review range:** S3-04 completion through S3-05

**Changes:**

1. **storage/audit.py** — two extensions:

   **AuditRecord.phase field:**
   - Added `phase: Literal["intent", "committed"] = "committed"` — backward-compatible default
   - Old persisted JSON without `phase` loads as `"committed"` (default behavior)
   - `schema_version` not incremented (same unreleased Stage-3 cycle)

   **AuditContext model:**
   - New strict Pydantic model: `operation_id`, `real_time` (AwareDatetime), `source` — required
   - Optional: `session`, `model_profile`, `prompt_version`
   - `extra="forbid"`, `frozen=True`
   - Same validation semantics as corresponding AuditRecord fields
   - Exported from `dnd_assistant.storage`

2. **storage/types.py** — `VaultRepository` Protocol refinement:
   - `create_entity` signature changed from `create_entity(document)` to `create_entity(document, *, audit: AuditContext)`
   - Audit metadata is now required (not optional) for every mutation
   - Read signatures (`get_entity`, `list_entities`) unchanged

3. **storage/vault_repository.py** (new) — `ObsidianVaultRepository` concrete class:
   - Constructor: `ObsidianVaultRepository(vault_root, audit_service)`
   - Validates audit path belongs beneath `<vault_root>/_system/audit/`
   - Rejects symlinked audit path components
   - Requires `_system/audit/` directory to exist

   **get_entity(entity_id):**
   - Scans all entity directories, parses all candidates
   - Detects global duplicate EntityIds (raises ConflictError)
   - Detects directory/type mismatch (raises StorageError)
   - Detects malformed persisted files (raises StorageError)
   - Exact YAML ID lookup only (no filename, no fuzzy, no name)
   - Runtime entity_id validation (invalid input → ValidationError, not NotFoundError)

   **list_entities(entity_type=None):**
   - Same global scan/validation as get_entity
   - Optional type filter
   - Deterministic discovery ordering (from S3-02 paths)
   - Empty list when nothing matches

   **create_entity(document, *, audit):**
   - Full write-ahead audit lifecycle:
     1. Validate audit log readable + operation_id unique
     2. Global snapshot (duplicate EntityId check)
     3. Serialize document
     4. Compute SHA-256 after_hash
     5. Generate opaque UUID filename (`entity-<uuid4hex>.md`)
     6. Append audit `intent` record
     7. `atomic_write_text` with parse validator
     8. Re-read persisted bytes, verify hash
     9. Append audit `committed` record
     10. Return persisted VaultDocument

   **Filename policy:**
   - Opaque UUID-based: `entity-<uuid4hex>.md`
   - ASCII-only, Windows/macOS safe
   - NOT derived from EntityId or display name
   - Collision detection with up to 32 retry attempts
   - Manual user rename does not break get_entity

   **Exact text read policy:**
   - Uses `open(path, encoding="utf-8", newline="")` — no newline translation
   - Invalid UTF-8 → StorageError

   **Persisted corruption policy:**
   - Malformed frontmatter → StorageError (not silently skipped)
   - Invalid Entity schema → StorageError
   - Directory/YAML type mismatch → StorageError
   - Invalid UTF-8 → StorageError

   **Global duplicate-ID policy:**
   - All entity types scanned before any read/list/create
   - Two files with same EntityId → ConflictError
   - Applies even when list_entities has a type filter

   **SHA-256 hash policy:**
   - `hashlib.sha256(exact_text.encode("utf-8")).hexdigest()`
   - Hashes exact serialized UTF-8 content
   - `before_hash = None` for create

   **Audit consistency strategy:**
   - `intent` → atomic write → verified read-back → `committed`
   - Same `operation_id` for both records
   - operation_id reuse rejected with ConflictError

   **Failure matrix:**
   - Corrupt audit preflight → StorageError, no entity mutation
   - Intent append failure → StorageError propagates, no entity mutation
   - Entity write failure → StorageError propagates, intent remains, no entity file
   - Read-back/hash failure → StorageError (entity may be committed), no committed audit
   - Committed-audit failure → StorageError with explicit diagnostic, entity NOT rolled back

   **No rollback/delete after committed mutation:**
   - If entity write succeeds but committed audit fails, entity remains
   - Intent record provides deterministic recoverability

4. **storage/__init__.py** — exports `AuditContext`, `ObsidianVaultRepository`

5. **tests/unit/test_storage_audit.py** — added:
   - `TestAuditRecordPhase` — 6 tests (default, intent, committed, invalid, backward compat, round trip)
   - `TestAuditContext` — 8 tests (minimal, full, naive rejected, empty/whitespace/extra/frozen/unicode)

6. **tests/unit/test_storage_vault_repository.py** (new) — 51 tests:

   **Repository construction (5 tests):**
   - Valid vault + audit, missing vault root, audit outside vault, audit outside _system/audit/, missing _system/audit/

   **Read/list success (12 tests):**
   - Empty vault, empty by type, one NPC, all four types, type-filtered list, Unicode entity/body, extra frontmatter preserved, exact ID lookup, renamed file still found, not found, invalid ID rejected, no filename lookup

   **Corruption handling (6 tests):**
   - Malformed frontmatter, invalid entity schema, directory/type mismatch, duplicate ID across types, duplicate ID same type, type-filtered list still detects global duplicate

   **Create duplicate (3 tests):**
   - Duplicate YAML ID → ConflictError, no target overwritten, audit intent not written

   **Filename policy (7 tests):**
   - `.md` suffix, safe ASCII, not entity ID, not display name, starts with `entity-`, manual rename OK, collision regenerates

   **Audit lifecycle (8 tests):**
   - Exactly 2 records, same operation_id, operation is create_entity, intent then committed, same entity_id, before_hash is None, same after_hash, same context metadata

   **Failure semantics (6 tests):**
   - operation_id reuse rejected, corrupt audit preflight aborts, intent append failure aborts, entity write failure leaves intent, committed audit failure entity still exists

   **Boundary tests (5 tests):**
   - Module importable, re-exported, no models/retrieval/tools imports

7. **DEVELOPMENT_STATUS.md** — updated task status, added S3-05 completion record

**Decisions made:**
- `ObsidianVaultRepository` — explicit concrete name, not `VaultRepository`
- Full `VaultRepository` structural conformance deferred to S3-07 (append_entity_fact)
- Filename: opaque UUID (`entity-<uuid4hex>.md`), not EntityId-derived
- Exact text read: `open(path, encoding="utf-8", newline="")` — no newline translation
- Persisted corruption: always StorageError, never silently skipped
- Directory/type mismatch: StorageError, never silently accepted
- Global duplicate ID: ConflictError, never first-win
- SHA-256 of exact UTF-8 content for audit hashes
- Write-ahead audit: intent before mutation, committed after verified read-back
- No rollback after committed entity write
- No cross-process duplicate-create guarantee (no file locks)
- No patch/revision/append scope creep

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 51 passed
- `uv run pytest tests/unit/test_storage_audit.py` — 78 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py tests/unit/test_storage_audit.py tests/unit/test_storage_vault_repository.py` — 353 passed, 17 skipped
- `uv run pytest` (full suite) — 887 passed, 17 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 77 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-05:** None at original implementation.

**S3-05 correction (audit-path hardening, EntityId validation, filename symlinks, cause preservation):**

1. **storage/vault_repository.py** — six corrections:

   **1a. Audit-path structural traversal rejection (Corrections 1-3):**
   - `_validate_audit_path()` now rejects ANY raw relative component equal to `..` before resolution (structural check, not resolved-path).
   - After symlink inspection of existing components, the audit log path is resolved with `strict=False`.
   - Resolved path is verified to be inside the resolved Vault root (via `relative_to`).
   - Resolved path is verified to be inside the resolved canonical `_system/audit/` directory.
   - No string-prefix containment checks (`str(path).startswith(...)` is never used).
   - The `_system/audit/` directory itself must exist and be a real directory (unchanged).

   **1b. Canonical EntityId runtime validation (Corrections 5-6):**
   - `_validate_entity_id_input()` now delegates to `pydantic.TypeAdapter(EntityId)` instead of duplicating the domain grammar.
   - Invalid input raises `dnd_assistant.errors.ValidationError` with the Pydantic validation failure preserved as `__cause__`.
   - The helper returns the validated value; `get_entity()` compares using that validated result.
   - `EntityId` import added to the module; `TypeAdapter` import added from pydantic.

   **1c. Filename symlink collision (Corrections 7-8):**
   - `_generate_unique_path()` now checks `not candidate.exists() and not candidate.is_symlink()`.
   - A dangling/broken symlink (where `exists()` returns `False`) is correctly treated as occupied.
   - A live symlink to an existing file is also treated as occupied.
   - The symlink is never unlinked or replaced.

   **1d. Committed-audit cause preservation (Correction 9):**
   - The `except StorageError` branch now uses `from exc` and passes `cause=exc` to the new `StorageError`.
   - The original audit `StorageError` is preserved as `__cause__`.

   **1e. Redundant try/except removed (Correction 12):**
   - The `try: atomic_write_text(...) except Exception: raise` wrapper removed — exceptions from `atomic_write_text` propagate naturally.

2. **tests/unit/test_storage_vault_repository.py** — 13 new tests:

   **Audit-path traversal (4 tests):**
   - `test_audit_path_traversal_inside_vault_rejected` — `..` from `_system/audit/` to `_system/other/` rejected
   - `test_audit_path_escape_from_vault_rejected` — `../../../outside/` rejected
   - `test_audit_path_normal_canonical_accepted` — normal path still accepted
   - `test_audit_path_nested_real_directory_accepted` — nested subdirectory under `_system/audit/` accepted

   **Canonical EntityId validation (6 tests):**
   - `test_get_entity_empty_rejected` — empty string rejected
   - `test_get_entity_whitespace_rejected` — leading/trailing whitespace rejected
   - `test_get_entity_non_printable_rejected` — control characters rejected
   - `test_get_entity_unicode_accepted` — printable Unicode accepted
   - `test_get_entity_validation_error_has_cause` — Pydantic cause preserved
   - (Existing `test_get_entity_invalid_id_rejected` unchanged — validates empty via new path)

   **Filename symlink collision (3 tests):**
   - `test_dangling_symlink_skipped` — dangling symlink skipped, entity created with different filename
   - `test_live_symlink_skipped` — live symlink skipped, entity created with different filename
   - `test_exhausted_attempts_raises_storage_error` — all 32 attempts exhausted raises `StorageError`

   **Committed-audit cause preservation (1 test):**
   - `test_committed_audit_failure_preserves_cause` — `exc_info.value.__cause__ is original audit StorageError`

**Quality-gate results (after S3-05 correction):**
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_audit.py` — 78 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py tests/unit/test_storage_audit.py tests/unit/test_storage_vault_repository.py` — 347 passed, 19 skipped
- `uv run pytest` (full suite) — 898 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 77 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-05 correction:** 2 files modified (storage/vault_repository.py, tests/unit/test_storage_vault_repository.py), focused on audit-path safety, canonical EntityId validation, filename symlink handling, and cause preservation.

**Scope exclusions confirmed:**
- No patch_entity, Patch DTO, expected_revision, revision increment, timestamp mutation (S3-06)
- No append_entity_fact (S3-07)
- No locks, rollback/delete transaction, automatic intent reconciliation, audit repair
- No fuzzy search, name/alias lookup, SQLite, FTS, indexes, embeddings, migrations
- No directory/bootstrap initialization, Calendar, Retrieval/EntityResolver, Session runtime, Tool layer, ModelGateway, ChangeSet
- S3-06 was NOT started

**Stage 3 status:** IN PROGRESS — S3-05 complete after correction.

### S3-06 completion record

**Review range:** S3-05 correction through S3-06

**Changes:**

1. **storage/patch.py** (new) — `EntityPatch` DTO:
   - Editable fields: `name`, `status`, `visibility`, `knowledge_status`, `created_session`, `last_seen_session`, `tags`
   - Immutable fields rejected: `schema_version`, `id`, `type`, `created_at`, `updated_at`, `revision`, `body`, `extra_frontmatter`
   - Empty patch rejected (at least one field required)
   - Explicit `None` allowed for nullable fields (`created_session`, `last_seen_session`)
   - Explicit `None` rejected for non-nullable fields (`name`, `status`, `visibility`, `knowledge_status`, `tags`)
   - Unknown fields rejected (`extra="forbid"`)
   - Frozen immutability
   - Canonical domain field validation reused (`NameStr`, `StatusStr`, `SessionRef`, `TagStr`, `Visibility`, `KnowledgeStatus`)

2. **storage/types.py** — `VaultRepository` Protocol:
   - Added `patch_entity(entity_id, patch, *, expected_revision, audit) -> VaultDocument` typed signature
   - Removed deferred-comment placeholder

3. **storage/vault_repository.py** — `ObsidianVaultRepository.patch_entity`:
   - `_StoredEntity` extended with `exact_text` and `content_hash` properties for before-hash computation without re-reading
   - `_REVISION_ADAPTER` TypeAdapter for canonical `Revision` runtime validation
   - `_validate_revision_input()` helper with Pydantic cause preservation
   - Full patch lifecycle:
     1. Validate inputs (EntityId, Revision, EntityPatch)
     2. Validate audit health + operation_id uniqueness
     3. Build clean global snapshot
     4. Find target entity by exact EntityId
     5. Check `expected_revision` against stored revision → `ConflictError` on mismatch
     6. Construct patched Entity through `Entity.model_validate()` (full validation)
     7. Serialize patched document
     8. Compute `before_hash` (from snapshot) and `after_hash`
     9. Append audit `intent` record
     10. Second optimistic check: re-read target file, verify revision + hash unchanged
     11. `atomic_write_text` with parse validator
     12. Re-read and verify persisted content (hash, id, type, revision, updated_at, body)
     13. Append audit `committed` record
     14. Return persisted `VaultDocument`

4. **storage/__init__.py** — exports `EntityPatch`

5. **tests/unit/test_storage_patch.py** (new) — 40 EntityPatch DTO tests:
   - Allowed fields (8 tests)
   - Empty patch rejection (2 tests)
   - Forbidden/immutable fields (9 tests)
   - Explicit None semantics (7 tests)
   - Canonical validation (9 tests)
   - Frozen behaviour (2 tests)
   - model_fields_set introspection (3 tests)

6. **tests/unit/test_storage_patch_repository.py** (new) — 56 repository-level patch tests:
   - Optimistic concurrency (10 tests: 1→2, N→N+1, stale, zero audit, bool/string/zero/negative rejection, cause preservation)
   - Field changes (10 tests: name, status, visibility, knowledge_status, created_session, clear created, last_seen_session, clear last_seen, tags, tags replace)
   - Immutable fields unchanged (4 tests: id, type, created_at, schema_version)
   - Body preservation (6 tests: LF, CRLF, mixed, Unicode, no trailing, trailing)
   - Extra frontmatter preservation (2 tests)
   - Filename/path preservation (3 tests)
   - updated_at/revision metadata (3 tests)
   - Audit lifecycle (8 tests: 2 records, operation, operation_id, entity_id, before_hash, after_hash, hash differs, context metadata)
   - Failure semantics (7 tests: invalid id, not found, operation_id reuse, corrupt audit, intent failure, write failure, committed-audit failure with cause)
   - Concurrent/manual edit detection (2 tests: content change, revision change)
   - Integration cycle (1 test: create → get → patch → get)

7. **tests/unit/test_storage_types.py** — updated protocol test to include `patch_entity` in expected methods, removed deferred-assertion test

**Decisions made:**
- `EntityPatch` — strict Pydantic DTO, `extra="forbid"`, `frozen=True`
- Editable fields: name, status, visibility, knowledge_status, created_session, last_seen_session, tags
- Immutable fields: schema_version, id, type, created_at, updated_at, revision, body, extra_frontmatter
- Omitted vs explicit None: `model_fields_set` determines supplied fields; nullable fields accept explicit None (clear); non-nullable fields reject explicit None
- Empty patch rejected at model-validation level
- Repository owns revision increment: `new_revision = stored_revision + 1`
- Repository owns `updated_at`: set to `audit.real_time`
- First concurrency check: before audit intent (no intent on stale)
- Second pre-write check: after durable intent, re-read target, verify revision + hash
- Body preserved character-for-character through patch
- Extra frontmatter preserved semantically through patch
- Same file/path preserved (no rename, no move)
- Audit: `operation="patch_entity"`, two phases (intent, committed), same operation_id
- Before/after hash: SHA-256 of exact UTF-8 persisted text
- No rollback after committed atomic write
- No cross-process CAS/lock guarantee

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_patch.py` — 40 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest` (full suite) — 993 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 80 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-06:** None

**Code/test changes during S3-06:** 8 files (4 modified, 4 new), focused on EntityPatch DTO and patch_entity implementation only.

**Scope exclusions confirmed:**
- No append_entity_fact (S3-07)
- No arbitrary Markdown replacement
- No arbitrary extra-frontmatter patching
- No entity type migration, ID change, file rename, file move, delete
- No locks, compare-and-swap filesystem primitive, transaction framework
- No automatic intent reconciliation, audit repair
- No FTS, fuzzy lookup, SQLite, indexes, embeddings, migrations
- No Calendar, Retrieval, Session runtime, Tool layer, ModelGateway, ChangeSet
- S3-07 was NOT started

### S3-07 completion record

**Review range:** S3-06 completion through S3-07

**Changes:**

1. **storage/vault_repository.py** — three additions and one refactor:

   **1a. Fact validation (`_validate_fact`):**
   - New private function validating fact contract: must be `str`, non-empty, no leading/trailing whitespace, printable Unicode, no embedded newline/control characters
   - Invalid input raises `ValidationError` with descriptive message

   **1b. Body fact appender (`_append_fact_to_body`):**
   - New private function appending one Markdown bullet (`"- <fact>"`) to existing body
   - Existing body remains exact character-for-character prefix
   - Line-ending policy: empty body → LF; trailing CRLF → CRLF; trailing LF → LF; lone CR → CR; no trailing newline → infer separator from most recent line ending (CRLF wins)
   - No extra blank paragraph unless already present
   - No platform-default newline conversion

   **1c. Shared mutation commit helper (`_commit_entity_mutation`):**
   - New private function owning the common mutation core: serialization, before/after hashes, audit intent, second optimistic check (re-read target, verify revision + hash), `atomic_write_text` with parse validator, verified read-back (hash, id, type, revision, updated_at), committed audit, common failure semantics
   - Used by both `patch_entity` and `append_entity_fact`

   **1d. `patch_entity` refactored to use shared helper:**
   - Steps 7-14 (serialize → committed audit) replaced by single call to `_commit_entity_mutation`
   - All existing patch behaviour preserved (verified by 56 existing patch tests passing unchanged)
   - No change to EntityPatch semantics, revision ownership, updated_at ownership, patch allowed fields, hashes, operation name, audit ordering, second conflict check, filename/path, return semantics

   **1e. `append_entity_fact` implementation:**
   - Full lifecycle: validate inputs → audit health → snapshot → find target → revision check → construct new body → construct candidate Entity → delegate to `_commit_entity_mutation`
   - Same audit two-phase strategy as `patch_entity` with `operation="append_entity_fact"`
   - Same second pre-write revision/hash check
   - Same atomic replacement (no direct file append for entity Markdown)
   - Same failure semantics (no audit intent for invalid input/not found/stale; intent remains on write failure; no rollback after successful atomic write; committed-audit failure preserves cause)

2. **storage/types.py** — `VaultRepository` Protocol:
   - `append_entity_fact` signature updated to require `audit: AuditContext` parameter
   - Docstring updated to describe fact validation contract, Markdown bullet rendering, revision increment, and `updated_at` ownership

3. **tests/unit/test_storage_types.py** — updated protocol test:
   - `test_append_entity_fact_revision_deferred_to_s3_07` replaced by `test_append_entity_fact_revision_semantics` verifying docstring now claims revision increment

4. **tests/unit/test_storage_append_fact.py** (new) — 67 tests:

   **Fact validation (11 tests):**
   - Normal ASCII, Unicode, special characters accepted
   - Empty, whitespace-only, leading whitespace, trailing whitespace, newline, CRLF, tab, non-string rejected

   **Body rendering (8 tests):**
   - Empty body → `"- Fact\n"`, LF trailing, CRLF trailing, no trailing newline, existing blank line, Unicode body/fact, old body exact prefix, fact appears exactly once

   **Entity metadata preservation (13 tests):**
   - id, type, name, status, visibility, knowledge_status, created_session, last_seen_session, created_at, schema_version, tags unchanged
   - revision incremented by 1, updated_at = audit.real_time, updated_at differs from created_at

   **Extra frontmatter preservation (2 tests):**
   - Simple extra keys survive, nested extra keys survive

   **File/path preservation (3 tests):**
   - Same path remains, custom filename preserved, no new file created

   **Audit lifecycle (8 tests):**
   - Exactly 2 records, operation is `append_entity_fact`, same operation_id, same entity_id, same before_hash, same after_hash, before_hash != after_hash, same context metadata

   **Optimistic concurrency (9 tests):**
   - Revision 1→2, N→N+1, stale raises ConflictError, stale produces zero audit records, bool/string/zero/negative revision rejected, repeated append with new revision

   **Failure semantics (7 tests):**
   - Invalid entity_id, not found, operation_id reuse, corrupt audit preflight, intent append failure, entity write failure leaves intent, committed-audit failure entity still has fact, committed-audit failure preserves cause

   **Concurrent/manual edit detection (2 tests):**
   - Manual edit without revision change detected, manual edit with revision change detected

   **Cross-operation integration (1 test):**
   - create → append → patch → append cycle verifies revision compatibility and body content

   **Protocol conformance (1 test):**
   - `isinstance(repo, VaultRepository)` — runtime structural conformance

5. **DEVELOPMENT_STATUS.md** — updated task status, added S3-07 completion record

**Decisions made:**
- `append_entity_fact` requires `audit: AuditContext` (no unaudited overload)
- Fact validation: non-empty, printable, no leading/trailing whitespace, no embedded newlines/controls
- Markdown rendering: `"- <fact>"` bullet, no `## Facts` heading, no timestamps/source labels/operation IDs in body
- Line-ending policy: deterministic, never modifies old body, CRLF-aware
- Existing body remains exact character-for-character prefix
- Entity metadata: only revision (+1) and updated_at (= audit.real_time) change
- Extra frontmatter preserved semantically unchanged
- Same file/path preserved (atomic replacement, not direct file append)
- Shared mutation core (`_commit_entity_mutation`) used by both `patch_entity` and `append_entity_fact`
- `patch_entity` behaviour unchanged by refactoring
- No generic body patch DTO, no fact removal/deduplication/IDs/timestamps, no Provenance blocks
- No S3-08 scope creep

**Quality-gate results:**
- `uv run pytest tests/unit/test_storage_append_fact.py` — 67 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest` (full suite) — 1060 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 81 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Defects discovered during S3-07:** None

**S3-07 correction (CRLF inference defect):**

**Review range:** S3-07 original through S3-07 correction

**Root cause:** `_append_fact_to_body()` compared `last_crlf = body.rfind("\r\n")` (start index of `\r\n`) with `last_lf = body.rfind("\n")` (start index of `\n`). For a CRLF sequence, `\n` is at index `last_crlf + 1`, so `last_lf > last_crlf` was always true, causing the code to incorrectly select LF instead of CRLF when the body had no trailing newline but the most recent line ending was CRLF.

**Corrected no-trailing-newline inference algorithm:**
- Find the rightmost `\n` via `body.rfind("\n")`.
- If none exists → default LF.
- If the `\n` is immediately preceded by `\r` → CRLF.
- Otherwise → LF.
- This correctly handles: CRLF history, LF history, mixed history where the most recent actual newline is CRLF, mixed history where the most recent actual newline is LF, and no prior newline at all.

**Changes:**

1. **storage/vault_repository.py** — `_append_fact_to_body()`:
   - Replaced `last_crlf > last_lf` comparison with correct `body[last_lf - 1] == "\r"` check.
   - Added explicit `last_lf == -1` guard for bodies with no prior newline.
   - Removed unused `expected_revision` parameter from `_commit_entity_mutation()` (optional cleanup — the parameter was accepted but never referenced in the body; the helper uses the snapshot's stored revision for its second check).

2. **tests/unit/test_storage_append_fact.py** — 13 new tests:
   - `test_crlf_history_no_trailing_newline` — CRLF body → CRLF separator (exact equality)
   - `test_lf_history_no_trailing_newline` — LF body → LF separator (exact equality)
   - `test_mixed_history_most_recent_crlf` — `"A\nB\r\nC"` → CRLF separator (exact equality)
   - `test_mixed_history_most_recent_lf` — `"A\r\nB\nC"` → LF separator (exact equality)
   - `test_no_previous_newline_fallback_lf` — `"Single line"` → LF fallback (exact equality)
   - `test_old_body_exact_prefix_for_crlf_no_trailing` — prefix invariant for CRLF history
   - `test_old_body_exact_prefix_for_lf_no_trailing` — prefix invariant for LF history
   - `test_old_body_exact_prefix_for_mixed_crlf_last` — prefix invariant for mixed CRLF-last
   - `test_old_body_exact_prefix_for_mixed_lf_last` — prefix invariant for mixed LF-last
   - `test_crlf_body_no_trailing_persisted_crlf` — repository-level CRLF persistence regression (verifies persisted body uses CRLF, original body is exact prefix, revision increments)

**Preserved semantics confirmed:**
- Empty body → `"- Fact\n"`
- Trailing CRLF → CRLF append
- Trailing LF → LF append
- Trailing lone CR → CR append
- No prior newline → LF fallback
- Old body remains exact prefix in every case
- No platform newline conversion
- All other S3-07 semantics unchanged (fact validation, bullet rendering, one fact per call, repository-owned revision +1, updated_at = audit.real_time, extra-frontmatter preservation, exact Entity metadata preservation, same-file atomic replacement, shared `_commit_entity_mutation`, audit intent → second check → atomic write → verified read-back → committed)

**Quality-gate results (after S3-07 correction):**
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_types.py tests/unit/test_storage_markdown.py tests/unit/test_storage_paths.py tests/unit/test_storage_atomic.py tests/unit/test_storage_audit.py tests/unit/test_storage_vault_repository.py tests/unit/test_storage_patch_repository.py tests/unit/test_storage_append_fact.py` — 479 passed, 19 skipped
- `uv run pytest` (full suite) — 1070 passed, 19 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 81 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-07 correction:** 2 files modified (storage/vault_repository.py, tests/unit/test_storage_append_fact.py), focused on CRLF inference correction and regression tests only.

**Scope exclusions confirmed:**
- No S3-08 integration hardening
- No S3-09 Stage-3 completion
- No new CRUD operations, delete, generic body editing, fact deduplication, provenance body syntax, locks, filesystem CAS, audit reconciliation, migrations
- No Retrieval, Calendar, Session runtime, Tool layer, ModelGateway, ChangeSet
- S3-08 was NOT started

**Code/test changes during S3-07:** 5 files (3 modified, 2 new), focused on append_entity_fact implementation and shared mutation-core refactoring only.

**Scope exclusions confirmed:**
- No generic body patch DTO, body delete/edit, fact removal, fact deduplication, fact IDs, fact timestamps in Markdown, Provenance blocks, Markdown heading management, arbitrary extra-frontmatter update, entity deletion, file rename/move, locks, filesystem CAS, automatic audit reconciliation
- No S3-08 broad hardening
- No S3-09 Stage-3 completion
- No Retrieval, Calendar, Session runtime, Tool Registry, ModelGateway, ChangeSet
- S3-08 was NOT started

### S3-08 correction (race safety + mutation-time path reauthorization)

**Review range:** S3-07 correction through S3-08 correction

**Commit:** `8b7671cee7a95f6bc62476b3b696abcb1fd8ecf0` (original S3-08), corrected in this task.

**Defects discovered during S3-08 review (production code):**

1. **Create target-occupancy race after durable intent.** The create lifecycle had no second pre-write check between audit intent and `atomic_write_text`. An external actor could create a regular file at the generated target path after intent, and `atomic_write_text` would silently replace it.

2. **Create duplicate-EntityId race after initial snapshot.** The initial snapshot confirmed the EntityId was unique, but no fresh snapshot was taken after intent. An external actor could create another entity with the same ID before the atomic write.

3. **Mutation-time authorization gap for long-lived filesystem topology.** Audit path validation and entity path authorization were only performed at repository construction time. A long-lived repository could have its audit directory, entity directory, or target file replaced by symlinks after construction, allowing writes to escape the Vault.

4. **Windows symlink skips prevented path-race scenarios from being exercised.** The original S3-08 symlink tests were all skipped on Windows, so the mutation-time authorization gap was not detected.

**Production code changes (storage/vault_repository.py):**

1. **`_validate_mutation_environment()`** (new) — runtime audit path revalidation called before every mutation. Checks: audit log still beneath `<vault_root>/_system/audit/`, no parent path component became a symlink, audit log itself is not a symlink, canonical `_system/audit/` directory still exists.

2. **`_reauthorize_entity_path()`** (new) — reauthorizes a stored entity path against current filesystem topology using `storage.paths.resolve_entity_path`. Detects symlink redirects, traversal, and path escape.

3. **`_StoredEntity._relative_path`** — new property storing the entity-relative path within the canonical type directory, enabling mutation-time reauthorization.

4. **Create second pre-write check** — after durable intent but before `atomic_write_text`:
   - Mutation environment revalidated (`_validate_mutation_environment`)
   - Target path reauthorized via `resolve_entity_path`
   - Target path must still NOT exist (`ConflictError` if occupied)
   - Target path must NOT be a symlink (`ConflictError` if symlink)
   - Fresh snapshot taken — duplicate EntityId detected (`ConflictError`)
   - On failure: intent remains, no committed record, no entity file

5. **Patch/append mutation-time reauthorization** — `_commit_entity_mutation` now calls `_validate_mutation_environment` and `_reauthorize_entity_path` after intent, before the second read check.

6. **Entry-point mutation environment validation** — `_validate_mutation_environment` called at the start of `create_entity`, `patch_entity`, and `append_entity_fact` (before any work begins).

**No changes to `atomic_write_text` replacement semantics.** The create "must remain absent" invariant is enforced in repository orchestration, not in the atomic primitive.

**ConflictError vs StorageError semantics:**
- `ConflictError` — target became occupied, duplicate EntityId appeared, revision/content changed (state conflict from another valid actor)
- `StorageError` — unsafe filesystem topology (symlink redirect, path escape, corrupt Vault, unsafe audit path)

**Audit intent remains on post-intent conflicts.** No `phase="aborted"` introduced. No audit schema change.

**Residual race still documented:** After the final pre-write check and before `os.replace`, another process could theoretically modify state. No locks/CAS/transaction manager added.

**Test changes (tests/integration/test_vault_repository_path_races.py):**

| Test class | Tests | Status |
|---|---|---|
| TestAuditDirectorySymlinkAfterConstruction | 4 tests (2 existing + 2 new: patch/append variants) | 4 skipped (symlink) |
| TestEntityDirectorySymlinkAfterConstruction | 2 tests (existing, unchanged) | 2 skipped (symlink) |
| TestNestedParentRedirect | 2 tests (1 existing + 1 new: append variant) | 2 skipped (symlink) |
| TestTargetSymlinkAfterIntent | 2 tests (1 existing + 1 new: append variant) | 2 skipped (symlink) |
| TestCreateRaceOccupiedTarget | 2 tests (NEW) | 1 passed, 1 skipped (symlink) |
| TestCreateRaceDuplicateEntityId | 2 tests (1 NEW + 1 existing) | 2 passed |
| TestTempFileCleanup | 3 tests (existing, unchanged) | 3 passed |

**New regression tests:**

- `test_target_occupied_after_intent_rejected` — creates a regular file at the generated target after intent; expects `ConflictError`; verifies intruder file untouched, intent exists, committed absent, no losing entity
- `test_target_becomes_symlink_after_intent_rejected` — replaces generated target with symlink after intent; expects `ConflictError`; skipped on Windows without symlink privilege
- `test_duplicate_id_appears_after_intent` — creates a valid entity with the same EntityId under a different filename after intent; expects `ConflictError`; verifies external entity untouched, only one entity with that ID exists, intent present, committed absent
- `test_audit_dir_symlink_blocks_patch` — audit dir replaced by symlink blocks patch via mutation-time validation
- `test_audit_dir_symlink_blocks_append` — audit dir replaced by symlink blocks append via mutation-time validation
- `test_nested_parent_symlink_blocks_append` — nested entity parent symlink blocks append
- `test_target_symlink_after_intent_append` — target replaced by symlink after intent blocks append

**Mocking policy:** Race tests wrap `AuditService.append` at the instance boundary (real filesystem side effects after intent). No module-identity patching of internal repository functions. `os.replace` patching retained only for temp-file cleanup tests.

**Windows skip policy:** Core create-race tests (occupied target, duplicate EntityId) run on Windows. Symlink-specific tests skip when `can_symlink()` returns False. Production fix supports all platforms.

**Quality-gate results:**

- `uv run pytest tests/integration/test_vault_repository_path_races.py` — 6 passed, 11 skipped
- `uv run pytest tests/integration/` — 49 passed, 11 skipped
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest` (full suite) — 1119 passed, 30 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-08 correction:** 2 files modified (storage/vault_repository.py, tests/integration/test_vault_repository_path_races.py). Focused on race safety and mutation-time reauthorization only.

**Scope exclusions confirmed:**
- No Stage 4 Calendar implementation
- No Retrieval, EntityResolver, Session runtime, ToolRegistry, ToolExecutor, ModelGateway, ChangeSet
- No delete_entity, replace_body, repair_audit, reconcile_intents, lock/unlock API, transactions
- No automatic audit repair, filesystem CAS, multi-process transaction service
- No golden campaign, performance benchmarks, property-based tests
- No locks, CAS, transaction manager
- No audit schema change (no `phase="aborted"`)
- No change to `atomic_write_text` replacement semantics
- S3-09 was NOT started

### S3-08 final correction (stable-target identity)

**Review range:** `473981c` through HEAD

**Root cause of remaining target-identity defect:**

The mutation-time reauthorization helper `_reauthorize_entity_path()` used
`resolve_entity_path()` to verify the target path was still inside the
approved canonical entity directory (containment check).  This is necessary
but not sufficient — an external actor could replace a parent directory
with a symlink to another directory inside the same canonical entity type
directory.  The containment check would pass, but the mutation would
target a different physical file.

Additionally, `_StoredEntity._relative_path` had a silent basename fallback
when the entity-relative path could not be derived from the canonical
entity directory, which could hide failures for nested entities.

**Exact stable-target reauthorization invariant:**

```
current_authorized_path == original_snapshot_path
```

where `original_snapshot_path = target.path`.  Equality of canonical
`Path` values is enforced, not merely containment.

**Production code changes (storage/vault_repository.py):**

1. **`_reauthorize_entity_path()` strengthened:**
   - New `expected_path` parameter (the originally selected entity path
     from the clean snapshot).
   - After `resolve_entity_path()` confirms containment, the resolved
     current path is compared against `expected_path` with `==`.
   - Mismatch raises `StorageError` with both paths in the diagnostic.
   - Path comparison uses canonical `Path` equality (not string).

2. **`_commit_entity_mutation()` updated:**
   - Calls `_reauthorize_entity_path()` with `expected_path=target.path`.

3. **`_StoredEntity.relative_path` derivation hardened:**
   - Silent `Path(path.name)` basename fallback removed.
   - If `path.relative_to(canon_dir)` fails, a `StorageError` is raised
     with the canonical directory path and cause preserved.
   - Every `_StoredEntity` produced by a clean snapshot now has a
     correctly derived entity-relative path.

**Create stable-target check preserved unchanged:**
`create_entity` already performs `reauthorized != target` comparison
after intent.  No changes to create logic.

**Audit revalidation preserved unchanged:**
`_validate_mutation_environment()` and audit parent symlink protection
are unchanged.

**atomic_write_text unchanged:**
No changes to the atomic write primitive.

**No locks/CAS/transaction manager added.**

**Test changes (tests/integration/test_vault_repository_path_races.py):**

| Test class | Tests | Status |
|---|---|---|
| TestStableTargetIdentity | 3 tests (NEW) | 3 passed |
| TestNestedParentRedirectStableTarget | 2 tests (NEW) | 2 skipped (symlink) |
| TestTargetFileSymlinkRedirect | 2 tests (NEW) | 2 skipped (symlink) |

**TestStableTargetIdentity (cross-platform, no symlinks):**
- `test_different_file_under_same_directory_rejected` — two valid normal
  files under the same entity directory; `relative_path` resolves to a
  different file than `expected_path`; expects `StorageError`.
- `test_same_file_under_same_directory_accepted` — same file resolves to
  itself; must succeed.
- `test_nested_entity_relative_path_preserved` — nested path like
  `Allies/Subgroup/entity.md` is preserved exactly and works for
  reauthorization.

**TestNestedParentRedirectStableTarget (symlink-capable):**
- `test_nested_parent_redirect_to_same_type_dir_rejected` — parent
  `Allies/` replaced by symlink to `Other/` (same canonical type dir);
  `Other/entity.md` has identical bytes so revision/hash would match;
  expects `StorageError` from stable-target identity check (not
  `ConflictError`).  Verifies redirected target unchanged, no committed
  audit, intent remains.
- `test_nested_parent_redirect_blocks_append` — same scenario for
  `append_entity_fact`.

**TestTargetFileSymlinkRedirect (symlink-capable):**
- `test_target_file_symlink_redirect_after_intent` — target file replaced
  after intent by a symlink to another file inside the same canonical
  type directory; expects `StorageError` or `ConflictError`; verifies
  redirect target unchanged, no committed audit.
- `test_target_file_symlink_redirect_after_intent_append` — same scenario
  for `append_entity_fact`.

**Residual race statement:**
After target reauthorization + revision/hash second check, there remains
a small TOCTOU window before `os.replace`.  No cross-process lock,
filesystem CAS, or transaction manager is claimed.  Fully race-free
multiprocess writes are not within S3-08 scope.

**Quality-gate results:**

- `uv run pytest tests/integration/test_vault_repository_path_races.py` — 9 passed, 15 skipped
- `uv run pytest tests/integration/` — 52 passed, 15 skipped
- `uv run pytest tests/unit/test_storage_paths.py` — 56 passed, 10 skipped
- `uv run pytest tests/unit/test_storage_vault_repository.py` — 62 passed, 2 skipped
- `uv run pytest tests/unit/test_storage_patch_repository.py` — 56 passed
- `uv run pytest tests/unit/test_storage_append_fact.py` — 77 passed
- `uv run pytest` (full suite) — 1122 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Code/test changes during S3-08 final correction:**
3 files modified (storage/vault_repository.py, tests/integration/test_vault_repository_path_races.py, DEVELOPMENT_STATUS.md).
Focused on stable-target identity enforcement only.

**Scope exclusions confirmed:**
- No new public API
- No S3-09 changes
- No atomic primitive changes
- No locks/CAS/transaction manager
- No Stage 4 Calendar implementation
- No Retrieval, EntityResolver, Session runtime, ToolRegistry, ToolExecutor, ModelGateway, ChangeSet

### S3-09 Stage 3 completion record

**Review boundary:**
- base: `22a21d3f34e6d3d028c644e4fadc7c7e1dd393a8`
- implementation review head: `f4142483e16a06f0238384fbf103a7826d9881a4`
- range: `22a21d3..f414248`

**Historical classification:**
- 17 Stage-3 implementation/correction commits
- 1 concurrent auxiliary commit `a557386` (add golden test vault) inside range — auxiliary fixture content excluded from Stage-3 implementation accounting

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

**Final invariants confirmed:**
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

**Review findings:** None

**Code/test/doc corrections during S3-09:**
- Fixed trailing whitespace in DEVELOPMENT_STATUS.md line 5
- Updated DEVELOPMENT_STATUS.md to Stage 3 DONE state

**Quality gates:**
- `uv run pytest tests/contract/test_boundaries.py` — 26 passed
- `uv run pytest tests/unit/test_storage_*.py` — 519 passed, 19 skipped
- `uv run pytest tests/integration/` — 52 passed, 15 skipped
- `uv run pytest` (full suite) — 1122 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 159 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors (after trailing-whitespace fix)

**Known intentional limitations:**
- No cross-process lock/CAS — residual TOCTOU before final `os.replace`
- Uncertain audit append may leave detectable partial tail
- No automatic audit intent reconciliation/repair
- Symlink tests skipped on Windows without symlink privileges (19 of 34 skipped tests are symlink-dependent)

## Current blockers

None recorded.

## Stage 2 — Domain schemas

### Goal

Design and implement the core domain schemas and deterministic validation contracts for Entity, foundational domain types, Session, TimelineEvent, and CampaignState, without persistence, calendar arithmetic, model-provider, or tool-layer dependencies.

### Tasks

- [x] `S2-00` Fix CLI entrypoint, add `cli/main.py`, add smoke test, verify quality gates.
- [x] `S2-01` Core domain types:
    - EntityId
    - EntityType
    - KnowledgeStatus
    - Visibility
    - Provenance
    - Revision
- [x] `S2-02` Base Entity schema
- [x] `S2-03` Session schema
- [x] `S2-04` TimelineEvent schema
- [x] `S2-05` CampaignState schema
- [x] `S2-06` Review deferred Stage 1 contracts against real domain types
- [x] `S2-07` Full Stage 2 verification, diff review and status update

### S2-06 deferred contract review

Reviewed Stage 1 deferred contracts against completed Stage 2 domain schemas (EntityId, EntityType, KnowledgeStatus, Visibility, Provenance, Revision, Entity, Session, TimelineEvent, TemporalCertainty, CampaignState).

**Contracts with docstring-only files reviewed:**
- `CalendarService` (`domain/calendar.py`) — deferred to Stage 4
- `ModelGateway` (`models/gateway.py`) — deferred to Stage 8
- `AuditService` (`storage/audit.py`) — deferred to Stage 3
- `ToolRegistry` (`tools/registry.py`) — deferred to Stage 7

**Contracts with no source file (inventoried in Stage 1 scope only):**
- `VaultRepository` — deferred to Stage 3
- `SearchService` — deferred to Stage 5
- `EntityResolver` — deferred to Stage 5
- `SessionService` — deferred to Stage 6
- `ToolExecutor` — deferred to Stage 7
- `PostSessionProcessor` — deferred to Stage 11
- `BootstrapService` — deferred to Stage 13

**Result:**
- All current deferrals confirmed correct.
- No Stage 2 domain type provides sufficient semantics to finalize any deferred typed signature without inventing placeholder DTOs, persistence semantics, calendar types, tool metadata, provider types, or sync/async decisions that belong to later stages.
- `models/gateway.py` correctly avoids importing domain types; adding typed signatures with domain models would reverse the intended dependency direction.
- No production-code contract changes required.
- No placeholder DTOs or speculative APIs introduced.
- Existing deferred-contract documentation is accurate and not stale.

### S4-00 completion record

**Review range:** `a8e8177..2de1fb3`

**Changes:**

1. **domain/calendar.py** (rewritten) — canonical Stage 4 calendar domain module:

   **WorldTick:**
   - `Annotated[int, BeforeValidator, Field]` — strict signed integer minute scalar
   - Negative, zero, positive int accepted; bool/str/float rejected
   - No non-negative constraint (preserves Stage-2 signed tick semantics)

   **CalendarMonth:**
   - `name: str` — non-empty, printable, no surrounding whitespace
   - `days: int` — >= 1, bool/string rejected
   - `extra="forbid"`, `frozen=True`

   **IntercalaryDay:**
   - `name: str` — non-empty, printable, no surrounding whitespace
   - `after_month: str` — must reference a declared month (validated by CalendarDefinition)
   - `extra="forbid"`, `frozen=True`

   **CalendarHoliday:**
   - `name: str` — holiday label
   - Two mutually exclusive target forms: `month+day` (regular) or `intercalary_day` (intercalary)
   - Holidays are labels, NOT elapsed-time units
   - `extra="forbid"`, `frozen=True`

   **GameDate:**
   - `year: int` — signed (negative/zero/positive accepted)
   - `month: str | None`, `day: int | None` — regular date mode
   - `intercalary_day: str | None` — intercalary date mode
   - `hour: int = 0`, `minute: int = 0` — time-of-day (>= 0)
   - Shape validation: regular (month+day) vs intercalary (intercalary_day), mixed rejected
   - `extra="forbid"`, `frozen=True`

   **CalendarDefinition:**
   - `schema_version: Literal[1] = 1`
   - `calendar_id: str` — non-empty printable identifier
   - `epoch: GameDate` — campaign epoch (tick 0)
   - `months: tuple[CalendarMonth, ...]` — at least one required
   - `intercalary_days: tuple[IntercalaryDay, ...] = ()`
   - `holidays: tuple[CalendarHoliday, ...] = ()`
   - `hours_per_day: int = 24`, `minutes_per_hour: int = 60`
   - Validation: unique month names (case-insensitive), unique intercalary names, no name collision, after_month references existing month, epoch validated against definition (month/day + time-of-day), holiday references validated
   - `extra="forbid"`, `frozen=True`

   **CalendarService Protocol:**
   - `@runtime_checkable` Protocol with `definition` property and four method signatures
   - `date_to_tick`, `tick_to_date` — deferred to S4-01
   - `advance_world_time`, `time_until` — deferred to S4-02
   - No TimelineEvent query APIs (deferred to S4-03)
   - Stateless: no mutable `current_world_tick`, no `set_world_time`/`get_world_time`

2. **domain/session.py** — `world_tick_start` and `world_tick_end` now reference `WorldTick` instead of bare `int`

3. **domain/events.py** — `world_tick`, `world_tick_min`, `world_tick_max` now reference `WorldTick` instead of bare `int`

4. **domain/__init__.py** — exports `WorldTick`, `CalendarMonth`, `IntercalaryDay`, `CalendarHoliday`, `GameDate`, `CalendarDefinition`, `CalendarService`

5. **docs/adr/0003-calendar-service-state-ownership.md** (new) — documents the decision that CalendarService is deterministic/stateless and does not own campaign current-time persistence

6. **tests/unit/test_calendar_contracts.py** (new) — 102 tests covering:
   - WorldTick: int acceptance, bool/str/float rejection (9 tests)
   - CalendarMonth: valid, Unicode, edge days, validation, extra, frozen (14 tests)
   - IntercalaryDay: valid, Unicode, empty/whitespace rejection, extra, frozen (8 tests)
   - CalendarHoliday: regular, intercalary, shape validation, extra, frozen (9 tests)
   - GameDate: regular, intercalary, year bounds, shape validation, time validation, extra, frozen (20 tests)
   - CalendarDefinition: minimal, multi-month, Unicode, intercalary, holiday, custom time units, duplicate/collision names, after_month reference, epoch validation (month/day/time), holiday validation, empty months, bool/zero time units, extra, frozen (25 tests)
   - CalendarService Protocol: runtime_checkable, required methods, definition property, no event-query methods yet (6 tests)
   - Stage-2 compatibility: Session/TimelineEvent world_tick serialization as int, negative tick acceptance, bool/string rejection (11 tests)
   - Import boundaries: no storage/models imports (3 tests)

7. **DEVELOPMENT_STATUS.md** — transitioned to Stage 4 IN PROGRESS, added S4-00 task inventory

**Decisions made:**
- WorldTick is canonical strict signed integer minute scalar
- GameDate supports regular and named intercalary dates
- CalendarDefinition is generic and Gregorian-independent
- Holidays are labels, not elapsed-time units
- Intercalary days are explicit named calendar days
- CalendarService core is stateless
- Current-world-time persistence is NOT CalendarService-owned
- Date conversion deferred to S4-01
- Time arithmetic deferred to S4-02
- TimelineEvent queries deferred to S4-03
- No Stage-5 work

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_contracts.py` — 102 passed
- `uv run pytest tests/unit/test_session.py tests/unit/test_timeline_event.py tests/contract/test_boundaries.py` — 266 passed
- `uv run pytest` (full suite) — 1224 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 161 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)
- `git diff --check` — no whitespace errors

**Final diff review:**
- No Gregorian datetime leakage
- No stateful current_world_tick in CalendarService
- No filesystem/storage imports
- No LLM/model imports
- No calendar arithmetic implemented
- No event-query semantics invented prematurely
- WorldTick serialized as integer (not object)
- No new >=0 restriction breaking Stage-2 tick semantics
- No silent month-name normalization
- No mutable list leakage in frozen definitions
- No Stage-5 Retrieval scope creep
- No unrelated changes

**Branch:** `main`
**Commit SHA:** `2de1fb3a71375790a7dc78ae324ff8c52a331e4d`
**Commit message:** `feat: define calendar domain contracts (S4-00)`
**Push result:** Successful — `HEAD == origin/main`
**Stage 4 status:** IN PROGRESS
**S4-00:** Complete
**S4-01:** NOT started
**Stage 5:** NOT started
