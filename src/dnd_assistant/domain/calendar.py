"""CalendarService — deferred contract for deterministic fantasy calendar arithmetic.

Responsibility
──────────────
Owns: world_tick ↔ date conversions, date arithmetic, relative time.
Must not own: campaign-specific calendar configuration, session state.
Called by: application layer, tools.
Failure boundary: raises ValidationError on invalid dates/arithmetic.

Deferred to Stage 4
────────────────────
The typed CalendarService API, CalendarDefinition, WorldTick value object,
and GameDate model all belong to Stage 4 (Calendar).

Stage 1 inventories the responsibility boundary only — no executable
signatures are defined here.
"""
