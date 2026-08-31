# ADR-0004: Current-world-time persistence

- **Status:** Accepted
- **Date:** 2026-08-31

## Context

Stage 6 (Session Runtime without LLM) requires a canonical persisted
representation of the campaign's current game time.

The Obsidian Vault is the only canonical Source of Truth for campaign state
(per ADR-0001 and GIGACODE.md).

The following design constraints are already established:

1. **CalendarService** (ADR-0003) is deterministic and stateless.  It owns
   `world_tick` ↔ `GameDate` conversion and time arithmetic, but does NOT
   own a mutable `current_world_tick` field or any persistence.

2. **`_system/campaign.yaml`** is campaign **configuration** — campaign
   identity, `calendar_id`, assistant perspective, feature flags.  It must
   not become a mutable runtime-state file.

3. **CampaignState** (`State/World State.md`) is a different aggregate whose
   full persistence belongs to a later stage (Stage 12).  Adding current
   world tick there would pull Stage-12 work forward.

4. On the current baseline no persisted current-world-time facility exists.
   Session start (S6-02) requires a canonical current world tick.

## Decision

The canonical persisted representation of current game time is:

```text
_system/world_time.json
```

This is a machine-owned mutable canonical runtime-state file.

### Schema

The typed state has the following fields:

| Field | Type | Description |
|---|---|---|
| `schema_version` | `Literal[1]` | Schema version for migration detection |
| `type` | `Literal["world_time"]` | Fixed discriminator |
| `current_world_tick` | `WorldTick` | Canonical signed integer minute scalar |
| `revision` | `Revision` | Optimistic concurrency counter (integer >= 1) |

`GameDate` is never stored in this file — it is always derived through
`CalendarService` arithmetic.

### Write semantics

- Atomic: whole-file replacement via temporary file then `os.replace`.
- Validated: the candidate content is re-parsed and validated before
  replacement.
- Audited: every mutation records `intent` and `committed` audit records
  in the existing `_system/audit/audit.jsonl`.
- Optimistic-revision guarded: the stored revision must match the caller's
  `expected_revision` or the operation is rejected with `ConflictError`.

### Read semantics

- Returns validated `CurrentWorldTime` on success.
- Missing file raises `NotFoundError` — no silent default tick.
- Corrupt/malformed content raises `StorageError` with preserved cause.

### Initialization semantics

- `initialize_current_world_time(...)` creates revision 1.
- If state already exists, raises `ConflictError` — no silent overwrite.

### Update semantics

- `set_current_world_time(...)` increments revision by exactly 1.
- Stale `expected_revision` raises `ConflictError`.
- Backward tick updates are accepted — monotonicity is not enforced by
  this repository (gameplay policy belongs to the application layer).

### Calendar arithmetic

`CalendarService` performs all `WorldTick` ↔ `GameDate` conversion and
time arithmetic.  The repository stores only the already-computed
`WorldTick`.  The application layer composes:

```text
WorldTimeRepository (persisted canonical tick)
+
CalendarService (arithmetic)
```

## Consequences

### Positive

- Single Vault source of truth for current game time.
- No hidden mutable clock that could diverge from the Vault.
- Clear separation between campaign configuration (`campaign.yaml`),
  runtime state (`world_time.json`), and campaign aggregate state
  (`CampaignState`).
- Restart-safe: the canonical tick survives application restarts.
- Typed validation at the persistence boundary.
- Composable with future Session Runtime.

### Trade-offs

- One extra small machine-owned state file in the Vault.
- Application code must explicitly compose `WorldTimeRepository` +
  `CalendarService` rather than calling a parameterless `advance()` on
  a stateful service.
- Initialization is explicit — a newly bootstrapped campaign must set
  its starting tick before the first session.

## Supersedes

Nothing.