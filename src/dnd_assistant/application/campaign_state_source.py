"""S12-02 deterministic Campaign State source collection / evidence binding.

Collects and binds the canonical evidence required by the accepted S12-01
Campaign State contracts and returns a fully validated ``CampaignState`` plus
the exact ``CampaignStateInputIdentity`` and its source-snapshot fingerprint.

The collector is **read-only**, deterministic and model-free.  It performs no
write, no materialization and no rendering; derived-state persistence and
pre-publication verification belong to S12-03.

Accepted S12-02 policy (authoritative):

- selection is **application-owned**: eligible sources are completed sessions
  only; recency is ``real_finished_at`` descending with ``session_id``
  ascending used *only* as a deterministic tie-break.  Repository listing
  order, lexical id order, ``revision`` and world tick are never chronology.
- the requested ``recent_session_limit`` is an explicit, required caller
  parameter and is bound into the projection identity; the safety ceiling
  ``MAX_RECENT_SESSIONS`` is application-owned and fail-closed.
- malformed completed metadata, unknown statuses and malformed
  ``touched_entities`` fail closed; active sessions are ignored as non-sources.
- touched references resolve by exact stable ``EntityId`` through the trusted
  all-visibility ``VaultRepository`` boundary; a missing entity fails closed.
  PLAYER/DM/SYSTEM references are all admitted internally (S12-04 owns the
  player-safe projection).  No ``SearchService`` / ``EntityResolver`` is used.
- raw session events are never consulted.
- reads form a **mixed-time source snapshot**: each source read is internally
  atomic, and the fingerprint binds the exact values actually read.  S12-03
  must re-derive and compare the fingerprint immediately before publication.
- canonical current world time is required; the game date is derived only
  through ``CalendarService`` and only when a complete ``CalendarDefinition``
  is supplied.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, hashlib,
    json, or a concrete storage implementation (storage read protocols are
    referenced only under ``TYPE_CHECKING``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from dnd_assistant.application.campaign_state_identity import (
    CAMPAIGN_STATE_DERIVATION_VERSION,
    compute_calendar_definition_fingerprint,
    compute_input_fingerprint,
)
from dnd_assistant.domain.calendar import (
    CalendarDefinition,
    CalendarService,
    DeterministicCalendarService,
    GameDate,
    WorldTick,
)
from dnd_assistant.domain.campaign_state import (
    CampaignEntityReference,
    CampaignSessionSource,
    CampaignState,
    CampaignStateInputIdentity,
    CampaignWorldTimeSource,
    SelectionLimit,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityId, Sha256Fingerprint
from dnd_assistant.errors import DndAssistantError, NotFoundError

if TYPE_CHECKING:
    from dnd_assistant.storage.types import (
        SessionMetadataRepository,
        VaultDocument,
        VaultRepository,
        WorldTimeRepository,
    )

# ── Application-owned fail-closed safety ceilings ─────────────────────────
#
# These are *safety limits*, not semantic truncation and not product defaults.
# They exist only to bound deterministic work and memory; canonical evidence is
# never silently dropped or truncated.  Exceeding a ceiling fails closed.

MAX_RECENT_SESSIONS = 100
"""Maximum caller-requested recent-session limit accepted by this collector."""

MAX_TOUCHED_ENTITIES = 500
"""Maximum unique touched entities bound into one projection."""

_SELECTION_LIMIT_ADAPTER: TypeAdapter[int] = TypeAdapter(SelectionLimit)
_ENTITY_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(EntityId)


# ── Errors ────────────────────────────────────────────────────────────────


class CampaignStateSourceReason(StrEnum):
    """Bounded, stable classification of a Campaign State collection failure."""

    WORLD_TIME_UNAVAILABLE = "world_time_unavailable"
    INVALID_COMPLETED_SESSION = "invalid_completed_session"
    INVALID_TOUCHED_ENTITIES = "invalid_touched_entities"
    MISSING_TOUCHED_ENTITY = "missing_touched_entity"
    INVALID_CALENDAR_INPUT = "invalid_calendar_input"
    INVALID_SELECTION_LIMIT = "invalid_selection_limit"
    INPUT_TOO_LARGE = "input_too_large"


class CampaignStateSourceError(DndAssistantError):
    """Raised when deterministic Campaign State source collection fails closed.

    Repository ``StorageError`` corruption is deliberately **not** wrapped: it
    propagates unchanged so storage corruption stays distinguishable from a
    bounded collection-policy failure.
    """

    def __init__(
        self,
        reason: CampaignStateSourceReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason


# ── Result ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CampaignStateBuildResult:
    """Accepted Campaign State projection plus its complete source binding.

    ``identity`` carries the complete reproducible derivation input (including
    the selection limit) so S12-03 can persist and re-verify the exact source
    binding without reconstructing hidden state.  ``state.input_fingerprint``
    equals ``compute_input_fingerprint(identity)``.
    """

    state: CampaignState
    identity: CampaignStateInputIdentity


# ── Selection limit ───────────────────────────────────────────────────────


def _validate_selection_limit(limit: object) -> int:
    """Validate the caller-supplied recent-session limit (fail closed)."""
    try:
        validated = _SELECTION_LIMIT_ADAPTER.validate_python(limit)
    except Exception as exc:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INVALID_SELECTION_LIMIT,
            f"recent_session_limit must be a strict integer >= 1, got {limit!r}",
            cause=exc,
        ) from exc
    if validated > MAX_RECENT_SESSIONS:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INPUT_TOO_LARGE,
            f"recent_session_limit {validated} exceeds safety ceiling {MAX_RECENT_SESSIONS}",
        )
    return validated


# ── Session evidence ──────────────────────────────────────────────────────


def _validate_touched_entities(raw: object) -> tuple[str, ...]:
    """Validate a session's raw ``touched_entities`` extra field.

    Absent (``None``) is a valid empty set.  A non-list scalar or any invalid
    item fails closed.  Duplicates are preserved here (collapsed semantically
    during the cross-session union).
    """
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, list):
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INVALID_TOUCHED_ENTITIES,
            "Persisted touched_entities is not a list",
        )
    validated: list[str] = []
    for item in raw:
        try:
            validated.append(_ENTITY_ID_ADAPTER.validate_python(item))
        except Exception as exc:
            raise CampaignStateSourceError(
                CampaignStateSourceReason.INVALID_TOUCHED_ENTITIES,
                f"Persisted touched_entities contains an invalid EntityId: {item!r}",
                cause=exc,
            ) from exc
    return tuple(validated)


def _validate_completed_lifecycle(session: Session) -> None:
    """Fail closed on a completed session with a malformed lifecycle.

    Only real-time ordering is enforced.  ``WorldTick`` is a signed value and
    the canonical Session / world-time contracts do not establish monotonic
    session-world-time progression, so a decreasing in-session tick is **not**
    corruption and must not be rejected here.
    """
    if session.real_finished_at is None:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INVALID_COMPLETED_SESSION,
            f"Session {session.id!r} is completed but has no real_finished_at",
        )
    if session.world_tick_end is None:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INVALID_COMPLETED_SESSION,
            f"Session {session.id!r} is completed but has no world_tick_end",
        )
    if session.real_finished_at < session.real_started_at:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INVALID_COMPLETED_SESSION,
            f"Session {session.id!r} has real_finished_at before real_started_at",
        )


def _collect_completed_sessions(
    session_repository: SessionMetadataRepository,
) -> list[tuple[Session, tuple[str, ...]]]:
    """Collect validated completed-session sources in a deterministic order.

    Repository listing order is deliberately ignored.  Active sessions are
    ignored as non-sources; completed sessions must be well-formed; any other
    status is unclassifiable and fails closed.
    """
    collected: list[tuple[Session, tuple[str, ...]]] = []
    for metadata in session_repository.list_session_metadata():
        session = metadata.session
        if session.status == "completed":
            _validate_completed_lifecycle(session)
            touched = _validate_touched_entities(metadata.extra_fields.get("touched_entities"))
            collected.append((session, touched))
        elif session.status == "active":
            continue
        else:
            raise CampaignStateSourceError(
                CampaignStateSourceReason.INVALID_COMPLETED_SESSION,
                f"Session {session.id!r} has unknown status {session.status!r}",
            )
    return collected


def _finished_at(session: Session) -> datetime:
    """Return a completed session's mandatory finish time (validated upstream)."""
    finished = session.real_finished_at
    assert finished is not None  # guaranteed by _validate_completed_lifecycle
    return finished


def _select_recent(
    completed: list[tuple[Session, tuple[str, ...]]],
    limit: int,
) -> list[tuple[Session, tuple[str, ...]]]:
    """Select the latest ``limit`` completed sessions deterministically.

    Recency: ``real_finished_at`` descending.  Tie-break: ``session_id``
    ascending (deterministic only; never treated as chronology).  Fewer than
    ``limit`` candidates select all.
    """
    ordered = sorted(completed, key=lambda pair: pair[0].id)
    ordered.sort(key=lambda pair: _finished_at(pair[0]), reverse=True)
    return ordered[:limit]


def _union_touched(
    selected: list[tuple[Session, tuple[str, ...]]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Union touched ids across selected sessions with sorted provenance.

    One entity touched in several sessions becomes exactly one binding whose
    ``source_session_ids`` is the ascending, duplicate-free tuple of those
    sessions.
    """
    provenance: dict[str, set[str]] = {}
    order: list[str] = []
    for session, touched in sorted(selected, key=lambda pair: pair[0].id):
        for entity_id in touched:
            if entity_id not in provenance:
                provenance[entity_id] = set()
                order.append(entity_id)
            provenance[entity_id].add(session.id)

    if len(order) > MAX_TOUCHED_ENTITIES:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INPUT_TOO_LARGE,
            f"Touched entity count {len(order)} exceeds safety ceiling {MAX_TOUCHED_ENTITIES}",
        )

    return tuple((entity_id, tuple(sorted(provenance[entity_id]))) for entity_id in order)


# ── Entity binding ────────────────────────────────────────────────────────


def _read_entity_snapshot(
    vault_repository: VaultRepository,
) -> dict[str, VaultDocument]:
    """Read one consistent all-visibility entity snapshot keyed by exact id."""
    return {document.entity.id: document for document in vault_repository.list_entities()}


def _bind_entities(
    touched: tuple[tuple[str, tuple[str, ...]], ...],
    entity_map: dict[str, VaultDocument],
) -> tuple[CampaignEntityReference, ...]:
    """Bind touched ids to current canonical entity projections (fail closed)."""
    references: list[CampaignEntityReference] = []
    for entity_id, source_session_ids in touched:
        document = entity_map.get(entity_id)
        if document is None:
            raise CampaignStateSourceError(
                CampaignStateSourceReason.MISSING_TOUCHED_ENTITY,
                f"Touched entity {entity_id!r} does not exist in the Vault",
            )
        entity = document.entity
        references.append(
            CampaignEntityReference(
                entity_id=entity.id,
                entity_type=entity.type,
                name=entity.name,
                visibility=entity.visibility,
                revision=entity.revision,
                source_session_ids=source_session_ids,
            )
        )
    return tuple(references)


# ── World time / calendar ─────────────────────────────────────────────────


def _read_world_time(
    world_time_repository: WorldTimeRepository,
) -> CampaignWorldTimeSource:
    """Read the canonical current world time (required; never defaulted)."""
    try:
        current = world_time_repository.get_current_world_time()
    except NotFoundError as exc:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.WORLD_TIME_UNAVAILABLE,
            "Canonical current world time is unavailable; Campaign State cannot be built",
            cause=exc,
        ) from exc
    return CampaignWorldTimeSource(
        current_world_tick=current.current_world_tick,
        revision=current.revision,
    )


def _resolve_calendar(
    definition: CalendarDefinition | None,
    current_tick: WorldTick,
) -> tuple[Sha256Fingerprint | None, GameDate | None]:
    """Bind the optional calendar definition and derive the game date.

    Uses only the deterministic ``CalendarService``; no independent date
    arithmetic.  An absent definition yields ``(None, None)``.
    """
    if definition is None:
        return None, None
    try:
        validated = TypeAdapter(CalendarDefinition).validate_python(definition)
        fingerprint = compute_calendar_definition_fingerprint(validated)
        service: CalendarService = DeterministicCalendarService(validated)
        game_date = service.tick_to_date(current_tick)
    except (DndAssistantError, ValueError) as exc:
        raise CampaignStateSourceError(
            CampaignStateSourceReason.INVALID_CALENDAR_INPUT,
            "Supplied CalendarDefinition or its conversion is invalid",
            cause=exc,
        ) from exc
    return fingerprint, game_date


# ── Builder ───────────────────────────────────────────────────────────────


def build_campaign_state(
    *,
    vault_repository: VaultRepository,
    session_repository: SessionMetadataRepository,
    world_time_repository: WorldTimeRepository,
    recent_session_limit: int,
    calendar_definition: CalendarDefinition | None = None,
) -> CampaignStateBuildResult:
    """Collect and bind canonical evidence into a validated ``CampaignState``.

    Read-only, deterministic and model-free.  ``recent_session_limit`` is an
    explicit required input (no hidden default) and is bound into the identity.

    Raises:
        CampaignStateSourceError: A bounded collection-policy failure.
        StorageError: Repository-level corruption (fail closed, unwrapped).
    """
    limit = _validate_selection_limit(recent_session_limit)
    world_time = _read_world_time(world_time_repository)

    completed = _collect_completed_sessions(session_repository)
    selected = _select_recent(completed, limit)
    touched = _union_touched(selected)
    entity_map = _read_entity_snapshot(vault_repository)
    references = _bind_entities(touched, entity_map)

    calendar_fingerprint, game_date = _resolve_calendar(
        calendar_definition, world_time.current_world_tick
    )

    identity = CampaignStateInputIdentity(
        derivation_version=CAMPAIGN_STATE_DERIVATION_VERSION,
        recent_session_limit=limit,
        world_time=world_time,
        sessions=tuple(
            CampaignSessionSource(session_id=session.id, revision=session.revision)
            for session, _touched in selected
        ),
        entities=references,
        calendar_definition_fingerprint=calendar_fingerprint,
    )
    state = CampaignState(
        input_fingerprint=compute_input_fingerprint(identity),
        current_world_tick=world_time.current_world_tick,
        current_game_date=game_date,
        recently_touched=identity.entities,
    )
    return CampaignStateBuildResult(state=state, identity=identity)


__all__ = [
    "MAX_RECENT_SESSIONS",
    "MAX_TOUCHED_ENTITIES",
    "CampaignStateBuildResult",
    "CampaignStateSourceError",
    "CampaignStateSourceReason",
    "build_campaign_state",
]
