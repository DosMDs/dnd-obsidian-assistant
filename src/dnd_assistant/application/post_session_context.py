"""S11-02 deterministic, model-free post-session context assembly.

Builds the canonical, bounded ``PreparedInputIdentity`` (C1) for a completed,
already-eligible session and computes its ``input_fingerprint``.  The builder is
completely read-only and performs no model call, no ledger write and no Vault
mutation.

Accepted S11-02 policy (authoritative):

- selection is **trusted structured evidence only**: the validated
  ``touched_entities`` accepted by S11-01 eligibility.  There is no event-extra
  entity-reference inference and no free-text/name/alias resolution; the
  player-only ``SearchService`` / ``EntityResolver`` contracts are deliberately
  not reused for internal DM context.
- entity references are resolved by exact stable ``EntityId`` through the
  ``VaultRepository`` read protocol; a missing touched entity fails closed.
- entity projections are **current canonical Vault state at processing time**,
  not session-time history.  Mixed-time multi-entity reads are acceptable and
  the fingerprint binds the exact projections actually read.
- eligibility evidence is bound to the canonical session revision: the builder
  re-reads session metadata and fails closed if the revision/status/touched set
  changed since eligibility, without re-implementing eligibility.
- entity bodies are **never truncated**: a body above the configured limit
  fails closed with ``INPUT_TOO_LARGE``.  All other bounds are explicit
  fail-closed ceilings as well.
- only raw world ticks are projected; no current-world-tick dependency and no
  fabricated game dates.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, or a concrete storage
    implementation (storage read protocols are referenced only under
    ``TYPE_CHECKING``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from pydantic import JsonValue, TypeAdapter

from dnd_assistant.application.post_session_eligibility import EligibilityResult
from dnd_assistant.application.post_session_identity import (
    POST_SESSION_PROCESSOR_VERSION,
    POST_SESSION_PROMPT_VERSION,
    compute_input_fingerprint,
)
from dnd_assistant.domain.post_session import (
    PreparedCalendarProjection,
    PreparedContextProjection,
    PreparedEntityProjection,
    PreparedInputIdentity,
    PreparedRawEvent,
    PreparedSessionProjection,
    Sha256Fingerprint,
)
from dnd_assistant.domain.types import EntityId
from dnd_assistant.errors import DndAssistantError, NotFoundError

if TYPE_CHECKING:
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.types import (
        SessionEventRepository,
        SessionMetadataRepository,
        VaultDocument,
        VaultRepository,
    )

# ── Prepared-input schema ─────────────────────────────────────────────────

_PREPARED_INPUT_SCHEMA_VERSION = 2
"""Schema version produced by this assembler (must match the domain model)."""

_ENTITY_ID_ADAPTER: TypeAdapter[EntityId] = TypeAdapter(EntityId)

# ── Centralized Stage-11 context bounds ───────────────────────────────────
#
# These are project-owned, deterministic character/count ceilings.  No provider
# tokenizer is used.  Every ceiling is fail-closed: exceeding a bound raises
# ``PostSessionContextError(INPUT_TOO_LARGE)``; canonical evidence is never
# silently dropped or truncated.  Changing any value is processor semantics and
# must trigger a ``POST_SESSION_PROCESSOR_VERSION`` review/bump.

MAX_RAW_EVENTS = 2000
"""Maximum number of ordered raw events admitted into the prepared input."""

MAX_RAW_EVENT_EXTRA_CHARS = 8000
"""Maximum canonical-JSON length of a single event's extra fields."""

MAX_TOTAL_RAW_EVENT_CHARS = 2_000_000
"""Maximum summed canonical-JSON length of all event extra fields."""

MAX_ENTITY_PROJECTIONS = 200
"""Maximum number of selected entity projections."""

MAX_ENTITY_BODY_CHARS = 4000
"""Maximum complete entity body length; longer bodies fail closed (no truncation)."""

MAX_TOTAL_CONTEXT_CHARS = 4_000_000
"""Maximum length of the rendered deterministic prepared-context document."""


# ── Errors ────────────────────────────────────────────────────────────────


class ContextFailureReason(StrEnum):
    """Bounded, stable classification of a context-assembly failure."""

    SESSION_INELIGIBLE = "session_ineligible"
    ELIGIBILITY_MISMATCH = "eligibility_mismatch"
    STALE_ELIGIBILITY_EVIDENCE = "stale_eligibility_evidence"
    INVALID_TOUCHED_ENTITIES = "invalid_touched_entities"
    MISSING_TOUCHED_ENTITY = "missing_touched_entity"
    INPUT_TOO_LARGE = "input_too_large"
    UNSUPPORTED_EXTRA_VALUE = "unsupported_extra_value"
    SCHEMA_MISMATCH = "schema_mismatch"


class PostSessionContextError(DndAssistantError):
    """Raised when deterministic post-session context assembly fails closed."""

    def __init__(
        self,
        reason: ContextFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.reason = reason


# ── Result ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PreparedPostSessionInput:
    """Accepted, fingerprinted prepared input plus its eligibility evidence."""

    identity: PreparedInputIdentity
    fingerprint: Sha256Fingerprint
    eligibility: EligibilityResult


# ── Helpers ───────────────────────────────────────────────────────────────


def _normalize_ids(ids: Sequence[str]) -> tuple[str, ...]:
    """Order-preserving first-occurrence deduplication of entity ids."""
    seen: set[str] = set()
    result: list[str] = []
    for entity_id in ids:
        if entity_id not in seen:
            seen.add(entity_id)
            result.append(entity_id)
    return tuple(result)


def _canonical_json(value: object) -> str:
    """Serialize a JSON value deterministically, rejecting NaN/Infinity."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PostSessionContextError(
            ContextFailureReason.UNSUPPORTED_EXTRA_VALUE,
            "Raw event extras are not canonically serializable",
            cause=exc,
        ) from exc


def _validate_touched(raw: object) -> tuple[str, ...]:
    """Validate the persisted ``touched_entities`` extra as stable EntityIds."""
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, list):
        raise PostSessionContextError(
            ContextFailureReason.INVALID_TOUCHED_ENTITIES,
            "Persisted touched_entities is not a list",
        )
    validated: list[str] = []
    for item in raw:
        try:
            validated.append(_ENTITY_ID_ADAPTER.validate_python(item))
        except Exception as exc:
            raise PostSessionContextError(
                ContextFailureReason.INVALID_TOUCHED_ENTITIES,
                f"Persisted touched_entities contains an invalid EntityId: {item!r}",
                cause=exc,
            ) from exc
    return tuple(validated)


def _project_events(
    events: Sequence[RawSessionEvent],
) -> tuple[PreparedRawEvent, ...]:
    """Project ordered raw events and enforce raw-event bounds (fail closed)."""
    if len(events) > MAX_RAW_EVENTS:
        raise PostSessionContextError(
            ContextFailureReason.INPUT_TOO_LARGE,
            f"Raw event count {len(events)} exceeds limit {MAX_RAW_EVENTS}",
        )

    projected: list[PreparedRawEvent] = []
    total_chars = 0
    for event in events:
        extras = dict(event.extra_fields)
        canonical = _canonical_json(extras)
        if len(canonical) > MAX_RAW_EVENT_EXTRA_CHARS:
            raise PostSessionContextError(
                ContextFailureReason.INPUT_TOO_LARGE,
                f"Raw event {event.event_id} extras exceed limit {MAX_RAW_EVENT_EXTRA_CHARS}",
            )
        total_chars += len(canonical)
        if total_chars > MAX_TOTAL_RAW_EVENT_CHARS:
            raise PostSessionContextError(
                ContextFailureReason.INPUT_TOO_LARGE,
                f"Total raw event extras exceed limit {MAX_TOTAL_RAW_EVENT_CHARS}",
            )
        projected.append(
            PreparedRawEvent(
                event_id=event.event_id,
                real_time=event.real_time,
                world_tick=event.world_tick,
                type=event.type,
                extra_fields=cast("dict[str, JsonValue]", extras),
            )
        )
    return tuple(projected)


def _project_entity(document: VaultDocument) -> PreparedEntityProjection:
    """Project one current canonical entity snapshot (no body truncation)."""
    entity = document.entity
    body = document.body
    if len(body) > MAX_ENTITY_BODY_CHARS:
        raise PostSessionContextError(
            ContextFailureReason.INPUT_TOO_LARGE,
            f"Entity {entity.id!r} body exceeds limit {MAX_ENTITY_BODY_CHARS}",
        )
    return PreparedEntityProjection(
        id=entity.id,
        type=entity.type,
        revision=entity.revision,
        name=entity.name,
        status=entity.status,
        visibility=entity.visibility,
        knowledge_status=entity.knowledge_status,
        tags=tuple(entity.tags),
        body_projection=body,
    )


def render_prepared_context(
    *,
    session: PreparedSessionProjection,
    raw_events: Sequence[PreparedRawEvent],
    entities: Sequence[PreparedEntityProjection],
    calendar: PreparedCalendarProjection,
) -> str:
    """Render the exact deterministic prepared-context document.

    The rendering is a pure function of the structured projections, which
    remain authoritative.  Because the builder computes both from the same
    read values in the same pass, the rendered document can never diverge from
    the structured projections bound by the fingerprint.
    """
    lines: list[str] = [
        f"session.id={session.id}",
        f"session.status={session.status}",
        f"session.real_started_at={session.real_started_at.isoformat()}",
        f"session.real_finished_at={session.real_finished_at.isoformat()}",
        f"session.world_tick_start={session.world_tick_start}",
        f"session.world_tick_end={session.world_tick_end}",
        f"session.revision={session.revision}",
        "session.touched_entities=" + _canonical_json(list(session.touched_entities)),
        (
            f"calendar.world_tick_start={calendar.world_tick_start} "
            f"calendar.world_tick_end={calendar.world_tick_end}"
        ),
        f"raw_events.count={len(raw_events)}",
    ]

    for event in raw_events:
        lines.append(
            "event "
            f"id={event.event_id} "
            f"real_time={event.real_time.isoformat()} "
            f"world_tick={event.world_tick} "
            f"type={event.type} "
            f"extra={_canonical_json(dict(event.extra_fields))}"
        )

    lines.append(f"entities.count={len(entities)}")
    for entity in entities:
        lines.append(
            "entity "
            f"id={entity.id} "
            f"type={entity.type.value} "
            f"revision={entity.revision} "
            f"name={entity.name} "
            f"status={entity.status} "
            f"visibility={entity.visibility.value} "
            f"knowledge_status={entity.knowledge_status.value} "
            f"tags={_canonical_json(list(entity.tags))} "
            f"body={_canonical_json(entity.body_projection)}"
        )

    return "\n".join(lines) + "\n"


# ── Builder ───────────────────────────────────────────────────────────────


def build_post_session_input(
    *,
    metadata_repo: SessionMetadataRepository,
    event_repo: SessionEventRepository,
    vault_repo: VaultRepository,
    session_id: str,
    eligibility: EligibilityResult,
) -> PreparedPostSessionInput:
    """Assemble the bounded, fingerprinted prepared input for a session.

    Read-only and model-free.  Eligibility is composed from S11-01 (the caller
    supplies the accepted ``EligibilityResult``); this builder does not
    re-implement eligibility.  Session metadata is re-read and bound to the
    revision observed during eligibility; a mismatch fails closed.

    Raises:
        PostSessionContextError: Ineligible/stale evidence, invalid or missing
            touched entities, or a context bound exceeded.
        StorageError: Repository-level corruption (fail closed).
    """
    if not eligibility.eligible:
        raise PostSessionContextError(
            ContextFailureReason.SESSION_INELIGIBLE,
            f"Session {eligibility.session_id} is not eligible: {eligibility.reason}",
        )
    if eligibility.session_id != session_id:
        raise PostSessionContextError(
            ContextFailureReason.ELIGIBILITY_MISMATCH,
            f"Eligibility is for {eligibility.session_id!r}, not {session_id!r}",
        )
    if eligibility.session_revision is None:
        raise PostSessionContextError(
            ContextFailureReason.ELIGIBILITY_MISMATCH,
            "Eligible result is missing its observed session revision",
        )

    metadata = metadata_repo.get_session_metadata(session_id)
    session = metadata.session

    if session.id != session_id:
        raise PostSessionContextError(
            ContextFailureReason.ELIGIBILITY_MISMATCH,
            f"Session metadata id {session.id!r} does not match {session_id!r}",
        )
    if session.revision != eligibility.session_revision:
        raise PostSessionContextError(
            ContextFailureReason.STALE_ELIGIBILITY_EVIDENCE,
            f"Session {session_id} revision changed since eligibility: "
            f"{eligibility.session_revision} -> {session.revision}",
        )
    if session.status != "completed":
        raise PostSessionContextError(
            ContextFailureReason.STALE_ELIGIBILITY_EVIDENCE,
            f"Session {session_id} status changed since eligibility: {session.status!r}",
        )

    metadata_touched = _normalize_ids(
        _validate_touched(metadata.extra_fields.get("touched_entities"))
    )
    eligibility_touched = _normalize_ids(eligibility.touched_entity_ids)
    if metadata_touched != eligibility_touched:
        raise PostSessionContextError(
            ContextFailureReason.STALE_ELIGIBILITY_EVIDENCE,
            f"Session {session_id} touched_entities changed since eligibility",
        )

    if session.real_finished_at is None or session.world_tick_end is None:
        raise PostSessionContextError(
            ContextFailureReason.SESSION_INELIGIBLE,
            f"Session {session_id} is missing finish time or end tick",
        )

    events = event_repo.list_events(session_id)
    projected_events = _project_events(events)

    if len(metadata_touched) > MAX_ENTITY_PROJECTIONS:
        raise PostSessionContextError(
            ContextFailureReason.INPUT_TOO_LARGE,
            f"Selected entity count {len(metadata_touched)} exceeds limit {MAX_ENTITY_PROJECTIONS}",
        )

    projected_entities: list[PreparedEntityProjection] = []
    for entity_id in metadata_touched:
        try:
            document = vault_repo.get_entity(entity_id)
        except NotFoundError as exc:
            raise PostSessionContextError(
                ContextFailureReason.MISSING_TOUCHED_ENTITY,
                f"Touched entity {entity_id!r} does not exist in the Vault",
                cause=exc,
            ) from exc
        projected_entities.append(_project_entity(document))

    prepared_session = PreparedSessionProjection(
        id=session.id,
        status=session.status,
        real_started_at=session.real_started_at,
        real_finished_at=session.real_finished_at,
        world_tick_start=session.world_tick_start,
        world_tick_end=session.world_tick_end,
        revision=session.revision,
        touched_entities=metadata_touched,
    )
    calendar = PreparedCalendarProjection(
        world_tick_start=session.world_tick_start,
        world_tick_end=session.world_tick_end,
    )
    entities_tuple = tuple(projected_entities)
    context_text = render_prepared_context(
        session=prepared_session,
        raw_events=projected_events,
        entities=entities_tuple,
        calendar=calendar,
    )
    if len(context_text) > MAX_TOTAL_CONTEXT_CHARS:
        raise PostSessionContextError(
            ContextFailureReason.INPUT_TOO_LARGE,
            f"Rendered context exceeds limit {MAX_TOTAL_CONTEXT_CHARS}",
        )

    identity = PreparedInputIdentity(
        schema_version=_PREPARED_INPUT_SCHEMA_VERSION,
        processor_version=POST_SESSION_PROCESSOR_VERSION,
        prompt_version=POST_SESSION_PROMPT_VERSION,
        session=prepared_session,
        raw_events=projected_events,
        entities=entities_tuple,
        context=PreparedContextProjection(text=context_text),
        calendar=calendar,
    )
    if identity.schema_version != _PREPARED_INPUT_SCHEMA_VERSION:
        raise PostSessionContextError(
            ContextFailureReason.SCHEMA_MISMATCH,
            f"Prepared-input schema version {identity.schema_version} is unsupported",
        )

    return PreparedPostSessionInput(
        identity=identity,
        fingerprint=compute_input_fingerprint(identity),
        eligibility=eligibility,
    )


__all__ = [
    "MAX_ENTITY_BODY_CHARS",
    "MAX_ENTITY_PROJECTIONS",
    "MAX_RAW_EVENTS",
    "MAX_RAW_EVENT_EXTRA_CHARS",
    "MAX_TOTAL_CONTEXT_CHARS",
    "MAX_TOTAL_RAW_EVENT_CHARS",
    "ContextFailureReason",
    "PostSessionContextError",
    "PreparedPostSessionInput",
    "build_post_session_input",
    "render_prepared_context",
]
