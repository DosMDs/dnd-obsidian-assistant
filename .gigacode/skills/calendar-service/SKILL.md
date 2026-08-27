---
name: calendar-service
description: Implement, test or review the deterministic fantasy CalendarService, world_tick conversions, date arithmetic, relative time or timeline event proximity.
compatibility: Python 3.12+, pytest, Hypothesis.
metadata:
  version: "1"
---
# Calendar service development

1. Keep `world_tick` as the canonical game-time representation.
2. Never delegate date arithmetic to an LLM.
3. Keep real timestamps, session IDs and game time conceptually separate.
4. Support the generic calendar schema rather than hard-coding Forgotten Realms rules.
5. Handle varying month lengths, intercalary days and custom years through definitions.
6. Represent uncertain dates explicitly (`exact`, `approximate`, `range`, `unknown`) rather than inventing precision.
7. Add deterministic unit tests for boundaries.
8. Add Hypothesis properties where applicable, especially conversion round-trips and reversible advances.
