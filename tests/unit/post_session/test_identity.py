"""S11-01 prepared-input identity and canonical fingerprint tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from dnd_assistant.application.post_session_identity import (
    POST_SESSION_PROCESSOR_VERSION,
    POST_SESSION_PROMPT_VERSION,
    canonical_prepared_input_bytes,
    compute_input_fingerprint,
    new_attempt_id,
)
from dnd_assistant.domain.post_session import (
    AttemptStarted,
    PreparedCalendarProjection,
    PreparedContextProjection,
    PreparedEntityProjection,
    PreparedInputIdentity,
    PreparedRawEvent,
    PreparedSessionProjection,
)
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.errors import ValidationError

_START = datetime(2026, 8, 31, 14, 0, 0, tzinfo=UTC)
_END = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)


def _session() -> PreparedSessionProjection:
    return PreparedSessionProjection(
        id="S001",
        status="completed",
        real_started_at=_START,
        real_finished_at=_END,
        world_tick_start=100,
        world_tick_end=200,
        revision=2,
        touched_entities=("npc-a",),
    )


def _event(event_id: str = "evt_001", tick: int = 150, text: str = "note") -> PreparedRawEvent:
    return PreparedRawEvent(
        event_id=event_id,
        real_time=_START,
        world_tick=tick,
        type="note",
        extra_fields={"text": text},
    )


def _entity(
    entity_id: str = "npc-a",
    revision: int = 3,
    visibility: Visibility = Visibility.PLAYER,
) -> PreparedEntityProjection:
    return PreparedEntityProjection(
        id=entity_id,
        type=EntityType.NPC,
        revision=revision,
        name="Aria",
        status="alive",
        visibility=visibility,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        tags=("hero",),
        body_projection="Aria is a ranger.",
    )


def _identity(**overrides: Any) -> PreparedInputIdentity:
    kwargs: dict[str, Any] = {
        "processor_version": POST_SESSION_PROCESSOR_VERSION,
        "prompt_version": POST_SESSION_PROMPT_VERSION,
        "session": _session(),
        "raw_events": (_event("evt_001", 150, "one"), _event("evt_002", 160, "two")),
        "entities": (_entity(),),
        "context": PreparedContextProjection(text="context-v1"),
        "calendar": PreparedCalendarProjection(world_tick_start=100, world_tick_end=200),
    }
    kwargs.update(overrides)
    return PreparedInputIdentity(**kwargs)


def test_same_input_same_bytes_and_fingerprint() -> None:
    a = _identity()
    b = _identity()
    assert canonical_prepared_input_bytes(a) == canonical_prepared_input_bytes(b)
    assert compute_input_fingerprint(a) == compute_input_fingerprint(b)


def test_dict_key_construction_order_cannot_change_fingerprint() -> None:
    e1 = PreparedRawEvent(
        event_id="evt_001",
        real_time=_START,
        world_tick=150,
        type="note",
        extra_fields={"b": 2, "a": 1},
    )
    e2 = PreparedRawEvent(
        event_id="evt_001",
        real_time=_START,
        world_tick=150,
        type="note",
        extra_fields={"a": 1, "b": 2},
    )
    assert compute_input_fingerprint(_identity(raw_events=(e1,))) == compute_input_fingerprint(
        _identity(raw_events=(e2,))
    )


def test_raw_event_order_changes_fingerprint() -> None:
    e1 = _event("evt_001", 150, "one")
    e2 = _event("evt_002", 160, "two")
    assert compute_input_fingerprint(_identity(raw_events=(e1, e2))) != compute_input_fingerprint(
        _identity(raw_events=(e2, e1))
    )


def test_entity_revision_only_change_changes_fingerprint() -> None:
    assert compute_input_fingerprint(
        _identity(entities=(_entity(revision=3),))
    ) != compute_input_fingerprint(_identity(entities=(_entity(revision=4),)))


def test_entity_visibility_only_change_changes_fingerprint() -> None:
    assert compute_input_fingerprint(
        _identity(entities=(_entity(visibility=Visibility.PLAYER),))
    ) != compute_input_fingerprint(_identity(entities=(_entity(visibility=Visibility.DM),)))


def test_context_projection_change_changes_fingerprint() -> None:
    assert compute_input_fingerprint(
        _identity(context=PreparedContextProjection(text="context-v1"))
    ) != compute_input_fingerprint(_identity(context=PreparedContextProjection(text="context-v2")))


def test_processor_and_prompt_version_changes_change_fingerprint() -> None:
    assert compute_input_fingerprint(_identity(processor_version="1")) != compute_input_fingerprint(
        _identity(processor_version="2")
    )
    assert compute_input_fingerprint(_identity(prompt_version="1")) != compute_input_fingerprint(
        _identity(prompt_version="2")
    )


def test_attempt_id_does_not_change_fingerprint() -> None:
    identity = _identity()
    fp = compute_input_fingerprint(identity)
    first = AttemptStarted(
        event_id="le_" + "a" * 32,
        attempt_id=new_attempt_id(),
        session_ref="S001",
        real_time=_START,
        input_fingerprint=fp,
        processor_version="1",
        prompt_version="1",
    )
    second = AttemptStarted(
        event_id="le_" + "b" * 32,
        attempt_id=new_attempt_id(),
        session_ref="S001",
        real_time=_START,
        input_fingerprint=fp,
        processor_version="1",
        prompt_version="1",
    )
    assert first.attempt_id != second.attempt_id
    assert first.input_fingerprint == second.input_fingerprint == fp


def test_wall_clock_attempt_time_does_not_change_fingerprint() -> None:
    identity = _identity()
    fp = compute_input_fingerprint(identity)
    a = AttemptStarted(
        event_id="le_" + "a" * 32,
        attempt_id="att_" + "a" * 32,
        session_ref="S001",
        real_time=_START,
        input_fingerprint=fp,
        processor_version="1",
        prompt_version="1",
    )
    b = AttemptStarted(
        event_id="le_" + "b" * 32,
        attempt_id="att_" + "b" * 32,
        session_ref="S001",
        real_time=_END,
        input_fingerprint=fp,
        processor_version="1",
        prompt_version="1",
    )
    assert a.input_fingerprint == b.input_fingerprint


def test_unicode_canonicalization_golden_value() -> None:
    identity = _identity(
        context=PreparedContextProjection(text="Éowyn — naïve"),
        entities=(_entity(entity_id="npc-Éowyn"),),
    )
    assert compute_input_fingerprint(identity).digest == (
        "ebd9110efb2aa2dac4e9c8a394d6c952a20eb306b130ee2300de5a3b8af8574e"
    )


def test_nan_is_rejected() -> None:
    event = PreparedRawEvent(
        event_id="evt_001",
        real_time=_START,
        world_tick=150,
        type="note",
        extra_fields={"x": float("nan")},
    )
    with pytest.raises(ValidationError):
        compute_input_fingerprint(_identity(raw_events=(event,)))


def test_infinity_is_rejected() -> None:
    event = PreparedRawEvent(
        event_id="evt_001",
        real_time=_START,
        world_tick=150,
        type="note",
        extra_fields={"x": float("inf")},
    )
    with pytest.raises(ValidationError):
        compute_input_fingerprint(_identity(raw_events=(event,)))


def test_new_attempt_id_shape() -> None:
    value = new_attempt_id()
    assert value.startswith("att_")
    assert len(value) == 4 + 32
    assert new_attempt_id() != value
