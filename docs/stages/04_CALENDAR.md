# Stage 4 — Calendar

## Objective

Implement the deterministic fantasy calendar system: `WorldTick` canonical
scalar, `CalendarDefinition` schema, `GameDate` display model, and
`CalendarService` protocol for world_tick ↔ date conversion, date arithmetic,
and relative-time operations.

## Tasks

- [x] `S4-00` Calendar kickoff + canonical domain contracts
- [x] `S4-01` Deterministic date ↔ world_tick conversion
- [x] `S4-02` World-time arithmetic + relative-time operations
- [x] `S4-03` TimelineEvent calendar queries
- [x] `S4-04` Custom-calendar/intercalary hardening + property tests
- [x] `S4-05` Full Stage 4 verification/diff/status

## Definition of Done

- `WorldTick` is the canonical strict signed integer minute scalar
- `GameDate` supports regular and named intercalary dates
- `CalendarDefinition` is generic and Gregorian-independent
- holidays are labels, not elapsed-time units
- intercalary days are explicit named calendar days
- `CalendarService` core is stateless
- current-world-time persistence is NOT CalendarService-owned
- date conversion implemented (`DeterministicCalendarService`)
- time arithmetic implemented
- TimelineEvent calendar queries implemented
- custom-calendar/intercalary property hardening complete
- full Stage 4 verification complete
- no Stage-5 work

## Implementation history

### S4-00 — Calendar kickoff + canonical domain contracts

**Review range:** `a8e8177..2de1fb3`

**Changes:**
1. `domain/calendar.py` (rewritten) — `WorldTick`, `CalendarMonth`,
   `IntercalaryDay`, `CalendarHoliday`, `GameDate`, `CalendarDefinition`,
   `CalendarService` Protocol
2. `domain/session.py` — `world_tick_start`/`world_tick_end` reference `WorldTick`
3. `domain/events.py` — `world_tick` fields reference `WorldTick`
4. `domain/__init__.py` — exports all calendar types
5. `docs/adr/0003-calendar-service-state-ownership.md` (new)
6. `tests/unit/test_calendar_contracts.py` (new) — 102 tests

**Decisions made:**
- WorldTick is canonical strict signed integer minute scalar
- GameDate supports regular and named intercalary dates
- CalendarDefinition is generic and Gregorian-independent
- Holidays are labels, not elapsed-time units
- Intercalary days are explicit named calendar days
- CalendarService core is stateless
- Current-world-time persistence is NOT CalendarService-owned

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_contracts.py` — 102 passed
- `uv run pytest` (full suite) — 1224 passed, 34 skipped
- `uv run ruff check .` — All checks passed

---

### S4-01 — Deterministic date ↔ world_tick conversion

**Review range:** S4-00 completion through S4-01

**Implementation:**
- `_CalendarLayout` — immutable precomputed lookup structure
- `DeterministicCalendarService` — concrete `CalendarService` implementation
- `date_to_tick(date)` — direct ordinal arithmetic
- `tick_to_date(tick)` — divmod-based inverse

**Conversion semantics:**
- `world_tick == 0` ↔ `CalendarDefinition.epoch` exactly
- Signed proleptic years with no missing year zero
- Negative ticks for dates before epoch
- Intercalary days occupy exactly one elapsed calendar day
- Holidays are labels and do not affect elapsed time

**Defect corrected (S4-00):**
- `_validate_date_against_definition()` had bare `pass` for intercalary dates
- Fixed: added `intercalary_names: set[str] | None` parameter

**Tests added:** 65 tests in `tests/unit/test_calendar_conversion.py`

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_contracts.py tests/unit/test_calendar_conversion.py` — 167 passed
- `uv run pytest` (full suite) — 1289 passed, 34 skipped

---

### S4-02 — World-time arithmetic + relative-time operations

**Review range:** S4-01 completion through S4-02

**Implementation:**
- `advance_world_time(current_tick, *, minutes)` — elapsed-minute arithmetic
- `time_until(start_tick, end_tick)` — signed difference
- `_validate_minutes(value)` — static validation helper

**Arithmetic semantics:**
- Signed arithmetic: negative/zero/positive ticks and minutes
- Crossing tick zero is natural
- Large Python integers supported without overflow
- Both operations are calendar-independent

**Tests added:** 54 tests in `tests/unit/test_calendar_arithmetic.py`

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_arithmetic.py` — 54 passed
- `uv run pytest` (full suite) — 1343 passed, 34 skipped

---

### S4-C01 — tick_to_date WorldTick validation fix

**Defect:** `tick_to_date()` accepted `tick: WorldTick` as a type hint but did
not call `_validate_world_tick(tick)` before arithmetic. `bool` could silently
participate as `1`/`0`.

**Fix:** Added `_validate_world_tick(tick)` as first statement in `tick_to_date()`.

**Regression tests:** 8 tests added in `TestTickToDateValidation`.

**Quality-gate results:**
- `uv run pytest` (full suite) — 1351 passed, 34 skipped

---

### S4-03 — TimelineEvent calendar queries

**Review range:** S4-C01 completion through S4-03

**Implementation:**
- `events_between(events, start_tick, end_tick)` — inclusive interval-overlap
- `events_near(events, event, *, radius)` — minimum interval-distance
- `upcoming(events, current_tick, *, days)` — stateless window query
- `overdue_events(events, current_tick)` — conservative latest-possible-tick
- `time_until_event(current_tick, event)` — signed delta preserving uncertainty

**Temporal interval semantics:**
- EXACT → [T, T], APPROXIMATE → [min, max], RANGE → [min, max], UNKNOWN → None
- All boundaries inclusive
- Conservative overdue: only when `latest_tick < current_tick`

**Tests added:** 96 tests in `tests/unit/test_calendar_event_queries.py`

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_event_queries.py` — 96 passed
- `uv run pytest` (full suite) — 1447 passed, 34 skipped

---

### S4-C02 — Overdue event ordering fix

**Defect:** `overdue_events()` used `_event_sort_key` (start-first) instead of
end-first ordering required by overdue semantics.

**Fix:** Added `_overdue_sort_key(event)` returning `(interval_end, interval_start, event_id)`.

**Regression tests:** 4 tests added in `TestOverdueOrdering`.

**Quality-gate results:**
- `uv run pytest tests/unit/test_calendar_event_queries.py` — 99 passed
- `uv run pytest` (full suite) — 1450 passed, 34 skipped

---

### S4-04 — Custom-calendar/intercalary hardening + property tests

**Review range:** S4-C02 completion through S4-04

**Intercalary hardening investigation:**
The suspected cross-month declaration-order defect was **confirmed** and corrected.

**Root cause:** `_intercalary_offsets` (parallel array) and `_ic_names_ordered`
did not correspond when intercalary days were declared in non-chronological
month order.

**Fix:** Replaced `_intercalary_offsets: tuple[int, ...]` with
`_intercalary_offsets_by_name: dict[str, int]`.

**Hypothesis strategy design:**
- `calendar_strategy()` — valid-by-construction `CalendarDefinition` generator
- `draw_valid_date(draw, cal)` — definition-aware `GameDate` generator
- All strategies use bounded small ranges for effective shrinking
- No `filter()` — valid-by-construction throughout

**Properties implemented (15 tests):**

| Property | Invariant |
|---|---|
| P1 | date → tick → date round trip |
| P2 | tick → date → tick round trip |
| P3 | epoch identity |
| P4 | advance(advance(tick, delta), -delta) == tick |
| P5 | time_until(t, advance(t, d)) == d |
| P5b | time_until(advance(t, d), t) == -d |
| P5c | time_until(t, t) == 0 |
| P6 | adjacent ticks map to adjacent elapsed minutes |
| P7 | one-year translation = days_per_year * minutes_per_day |
| P8 | holidays do not affect tick_to_date |
| P8b | holidays do not affect date_to_tick |
| P9 | intercalary declaration order semantics |
| P10 | events_between matches naive reference |
| P11 | events_near matches naive distance |
| P12 | overdue conservative semantics |

**Tests added:** 31 tests in `tests/unit/test_calendar_intercalary_hardening.py`

**Quality-gate results:**
- `uv run pytest tests/property/test_calendar_properties.py tests/property/test_calendar_properties_p2.py` — 15 passed
- `uv run pytest` (full suite) — 1496 passed, 34 skipped

---

### S4-C03 — Epoch property coverage correction

**Defects:**
1. `DEVELOPMENT_STATUS.md` hierarchy corruption (heading nesting) — fixed
2. `calendar_strategy()` always used fixed epoch — fixed

**Strategy correction:**
- Epoch year: signed integer from -10000 to +10000
- Regular epoch: any month, any valid day
- Intercalary epoch: any declared intercalary day (50% probability)
- Epoch time: non-midnight hour/minute within calendar bounds

**Deterministic regressions:** 3 tests added.

**Quality-gate results:**
- `uv run pytest` (full suite) — 1499 passed, 34 skipped

---

### S4-05 — Stage 4 completion

**Review base:** `a8e81773f939c4b4b6963b68930df43a72bd896d`
**Implementation review head:** `1ff7907fbdf7318e5ed774fce4dd5745ddaefeee`
**Range:** `a8e81773..1ff7907`

**Commit inventory (9 commits):**

| SHA | Classification |
|---|---|
| `2de1fb3` feat: define calendar domain contracts (S4-00) | implementation |
| `6675a15` docs: add S4-00 completion record | documentation/status |
| `7bedc1d` feat: implement calendar date conversion (S4-01) | implementation |
| `764d753` feat: implement calendar time arithmetic (S4-02) | implementation |
| `4adaacb` fix: enforce tick_to_date WorldTick validation (S4-C01) | correction |
| `b9ad278` feat: implement timeline event calendar queries (S4-03) | implementation |
| `443700f` fix: correct overdue event ordering (S4-C02) | correction |
| `5cc2a1d` test: harden calendar properties and fix intercalary offset ordering (S4-04) | correction |
| `1ff7907` test: complete calendar epoch property coverage (S4-C03) | correction |

**Architectural boundaries verified:**

| Assertion | Status |
|---|---|
| Vault remains Source of Truth | ✓ |
| CalendarService is deterministic | ✓ |
| CalendarService is stateless | ✓ |
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

**Historical defects:**

| Defect | Fix | Status |
|---|---|---|
| S4-00: invalid intercalary epoch name not validated | `_validate_date_against_definition` with `intercalary_names` param | ✓ |
| S4-C01: tick_to_date lacked strict WorldTick runtime validation | `_validate_world_tick(tick)` as first statement | ✓ |
| S4-C02: overdue_events used wrong start-first sort key | `_overdue_sort_key` with end-first ordering | ✓ |
| S4-04: intercalary name/offset parallel arrays broke cross-month ordering | `_intercalary_offsets_by_name` dict lookup | ✓ |
| S4-C03: epoch strategy was trivial; DEVELOPMENT_STATUS hierarchy damaged | Varied epoch generation; heading restored | ✓ |

**Quality-gate results:**
- Calendar-focused tests — 514 passed
- `uv run pytest` (full suite) — 1499 passed, 34 skipped
- `uv run ruff check .` — All checks passed
- `uv run ruff format --check .` — 168 files already formatted
- `uv run dnd --help` — CLI smoke test OK (Russian UI)

**Stage 4 status:** DONE.