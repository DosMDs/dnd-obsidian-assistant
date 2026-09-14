---
name: calendar-service
description: Implement or review deterministic fantasy calendar conversion, world_tick arithmetic, relative time and timeline-event proximity.
---
# Calendar service

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 4](../../../docs/stages/04_CALENDAR.md), [state ownership ADR](../../../docs/adr/0003-calendar-service-state-ownership.md), [persistence ADR](../../../docs/adr/0004-current-world-time-persistence.md) and current calendar contracts/tests.

CalendarService owns arithmetic and interpretation, not mutable current-time storage. Keep world_tick canonical; compose persisted Vault time at the application layer. Separate real timestamps, session IDs and game time. Use the generic CalendarDefinition, not hard-coded Forgotten Realms/Gregorian assumptions.

Derive behavior for varying month lengths, named intercalary days, custom years, epochs and negative ticks from the accepted definition. Keep exact/approximate/range/unknown date uncertainty explicit; never invent precision. Implement deterministic conversion/query operations in the owning domain service.

Verify boundaries and invalid definitions with unit tests; use Hypothesis for conversion round-trips and reversible advances where applicable. Common failures include counting holidays as elapsed days, omitting intercalary days, mixing real/game time and hiding a second mutable clock. Stop if a request needs a new persistence format or calendar policy outside scope; report rather than changing campaign state or delegating arithmetic to a model. Apply [quality gates](../../../docs/development/quality-and-evidence.md).
