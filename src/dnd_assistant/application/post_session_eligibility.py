"""S11-01 deterministic, model-free post-session processing eligibility.

Decides, before any model call, whether a completed session is structurally
eligible for Stage-11 processing.  It reads only the evidence required for
that decision and performs **zero** writes.

The decision is Python-owned and fail-closed for uncertain durable state.  The
legacy ``Session.processed`` / ``processed_model_profile`` and the
string-only ``processing_status`` extra are deliberately never read (C5).

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, or a concrete storage
    implementation (the storage read protocols are referenced only under
    ``TYPE_CHECKING``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, TypeAdapter

from dnd_assistant.application.post_session_ledger import (
    attempt_has_terminal_event,
    load_ledger_events,
)
from dnd_assistant.domain.post_session import PostSessionAttemptId
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import ConflictError, NotFoundError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.storage.post_session_processing import (
        PostSessionProcessingStore,
    )
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
    )

_ENTITY_ID_ADAPTER: TypeAdapter[EntityId] = TypeAdapter(EntityId)


# ── Result types ──────────────────────────────────────────────────────────


class EligibilityReason(StrEnum):
    """Deterministic structural eligibility outcome."""

    ELIGIBLE = "eligible"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_MALFORMED = "session_malformed"
    SESSION_NOT_COMPLETED = "session_not_completed"
    MISSING_FINISH_TIME = "missing_finish_time"
    MISSING_END_TICK = "missing_end_tick"
    INVALID_TICK_ORDER = "invalid_tick_order"
    INVALID_REAL_TIME_ORDER = "invalid_real_time_order"
    EVENTS_MISSING = "events_missing"
    EVENTS_UNREADABLE = "events_unreadable"
    EVENTS_MALFORMED = "events_malformed"
    ACTIVE_SESSION_CONTRADICTION = "active_session_contradiction"
    INVALID_TOUCHED_ENTITIES = "invalid_touched_entities"
    ATTEMPT_ALREADY_TERMINAL = "attempt_already_terminal"


class EligibilityResult(BaseModel):
    """Immutable, read-only eligibility decision.

    ``eligible`` is the decision; ``reason`` is the deterministic explanation.
    ``touched_entity_ids`` is populated only for an eligible completed session
    and is a convenience projection of already-validated canonical evidence.
    """

    eligible: bool
    reason: EligibilityReason
    session_id: str
    touched_entity_ids: tuple[str, ...] = ()

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


def _ineligible(session_id: str, reason: EligibilityReason) -> EligibilityResult:
    return EligibilityResult(eligible=False, reason=reason, session_id=session_id)


def _eligible(session_id: str, touched_entity_ids: tuple[str, ...]) -> EligibilityResult:
    return EligibilityResult(
        eligible=True,
        reason=EligibilityReason.ELIGIBLE,
        session_id=session_id,
        touched_entity_ids=touched_entity_ids,
    )


# ── Touched-entity validation ─────────────────────────────────────────────


def _validate_touched_entities(
    raw: object,
) -> tuple[str, ...] | None:
    """Validate the ``touched_entities`` extra field.

    Returns the validated ids, or ``None`` when the value is malformed.  An
    absent field is a valid empty set.
    """
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, list):
        return None

    validated: list[str] = []
    for item in raw:
        try:
            validated.append(_ENTITY_ID_ADAPTER.validate_python(item))
        except Exception:
            return None
    return tuple(validated)


# ── Eligibility ───────────────────────────────────────────────────────────


def evaluate_processing_eligibility(
    metadata_repo: SessionMetadataRepository,
    event_repo: SessionEventRepository,
    store: PostSessionProcessingStore,
    session_id: str,
    *,
    attempt_id: PostSessionAttemptId | None = None,
) -> EligibilityResult:
    """Evaluate structural processing eligibility deterministically.

    Read-only and model-free.  Expected missing/corrupt/contradictory evidence
    yields an ``eligible=False`` result; a corrupt ledger read (uncertain
    durable state) raises ``StorageError`` (fail closed) rather than producing
    an ineligibility verdict.

    Raises:
        StorageError: The durable processing ledger is unsafe or malformed.
    """
    try:
        metadata = metadata_repo.get_session_metadata(session_id)
    except NotFoundError:
        return _ineligible(session_id, EligibilityReason.SESSION_NOT_FOUND)
    except StorageError:
        return _ineligible(session_id, EligibilityReason.SESSION_MALFORMED)

    session = metadata.session

    if session.status != "completed":
        return _ineligible(session_id, EligibilityReason.SESSION_NOT_COMPLETED)

    if session.real_finished_at is None:
        return _ineligible(session_id, EligibilityReason.MISSING_FINISH_TIME)

    if session.world_tick_end is None:
        return _ineligible(session_id, EligibilityReason.MISSING_END_TICK)

    if session.world_tick_end < session.world_tick_start:
        return _ineligible(session_id, EligibilityReason.INVALID_TICK_ORDER)

    if session.real_finished_at < session.real_started_at:
        return _ineligible(session_id, EligibilityReason.INVALID_REAL_TIME_ORDER)

    touched = _validate_touched_entities(metadata.extra_fields.get("touched_entities"))
    if touched is None:
        return _ineligible(session_id, EligibilityReason.INVALID_TOUCHED_ENTITIES)

    try:
        event_repo.list_events(session_id)
    except NotFoundError:
        return _ineligible(session_id, EligibilityReason.EVENTS_MISSING)
    except StorageError:
        return _ineligible(session_id, EligibilityReason.EVENTS_MALFORMED)

    try:
        active = metadata_repo.get_active_session()
    except ConflictError:
        return _ineligible(session_id, EligibilityReason.ACTIVE_SESSION_CONTRADICTION)
    except StorageError:
        return _ineligible(session_id, EligibilityReason.SESSION_MALFORMED)

    if active is not None and active.session.id == session_id:
        return _ineligible(session_id, EligibilityReason.ACTIVE_SESSION_CONTRADICTION)

    if attempt_id is not None:
        # A corrupt ledger is uncertain durable state: fail closed (raise).
        ledger_events = load_ledger_events(store, session_id)
        if attempt_has_terminal_event(ledger_events, attempt_id):
            return _ineligible(session_id, EligibilityReason.ATTEMPT_ALREADY_TERMINAL)

    return _eligible(session_id, touched)


__all__ = [
    "EligibilityReason",
    "EligibilityResult",
    "evaluate_processing_eligibility",
]
