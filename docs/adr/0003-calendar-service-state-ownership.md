# ADR-0003: CalendarService state ownership

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Stage 4 introduces `CalendarService` as the deterministic fantasy calendar
arithmetic component.  A design question arises: should `CalendarService`
own an in-memory `current_world_tick` representing the campaign's current
game time?

The Obsidian Vault is the only canonical Source of Truth for campaign state
(per ADR-0001 and GIGACODE.md).  Introducing a second in-memory clock would
create a potential divergence between the Vault and runtime state.

## Decision

`CalendarService` is **deterministic and stateless** with respect to
persisted current world time.

- `CalendarService` owns interpretation and arithmetic only:
  - `world_tick` ↔ `GameDate` conversion
  - time advancement (`advance_world_time`)
  - duration calculation (`time_until`)
- `CalendarService` does **not** own:
  - a mutable `current_world_tick` field
  - `set_world_time` / `get_world_time` methods
  - any in-memory campaign clock

`world_tick` persistence belongs to trusted campaign/application state.
The tool/application layer will later compose:

```
canonical persisted state (Vault)
+
CalendarService arithmetic
```

rather than introducing a second in-memory source of truth.

## Consequences

### Positive

- No hidden mutable clock that could diverge from the Vault
- No conflict with Vault Source of Truth principle
- Tool/application layer later owns `set`/`get` operations explicitly
- Tests remain deterministic — no mutable state to reset between cases
- `CalendarService` instances are reusable and composable

### Trade-offs

- Application code must explicitly pass the current tick to
  `advance_world_time` rather than calling a parameterless `advance` that
  reads an internal clock
- Slightly more verbose call sites in the tool/application layer

## Supersedes

Nothing.