"""S11-08 input-bound coverage tests for S11-02 context assembly.

S11-02 already pins raw-event count, entity count and entity-body limits.  This
module closes the remaining accepted ceilings (per-event extra chars, total raw
event chars, total rendered context chars) with exact limit / limit+1 evidence.
"""

from __future__ import annotations

import pytest

from dnd_assistant.application import post_session_context as psc
from dnd_assistant.application.post_session_context import (
    ContextFailureReason,
    PostSessionContextError,
)
from tests.unit.post_session.test_context import (
    _build,
    _document,
    _eligibility,
    _event,
    _metadata,
)


def _canonical_len(value: object) -> int:
    return len(psc._canonical_json(value))


def test_per_event_extra_char_limit_is_exact(monkeypatch) -> None:
    extra: dict[str, object] = {"text": "x" * 100}
    limit = _canonical_len(extra)
    metadata = _metadata(("npc-a",))
    documents = {"npc-a": _document()}
    eligibility = _eligibility(("npc-a",))

    monkeypatch.setattr(psc, "MAX_RAW_EVENT_EXTRA_CHARS", limit)
    _build(
        metadata=metadata,
        events=[_event(extra=extra)],
        documents=documents,
        eligibility=eligibility,
    )

    monkeypatch.setattr(psc, "MAX_RAW_EVENT_EXTRA_CHARS", limit - 1)
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=metadata,
            events=[_event(extra=extra)],
            documents=documents,
            eligibility=eligibility,
        )
    assert exc.value.reason is ContextFailureReason.INPUT_TOO_LARGE


def test_total_raw_event_char_limit_is_exact(monkeypatch) -> None:
    extra_a: dict[str, object] = {"text": "a" * 50}
    extra_b: dict[str, object] = {"text": "b" * 50}
    total = _canonical_len(extra_a) + _canonical_len(extra_b)
    metadata = _metadata(("npc-a",))
    documents = {"npc-a": _document()}
    eligibility = _eligibility(("npc-a",))
    events = [_event("evt_001", extra=extra_a), _event("evt_002", extra=extra_b)]

    monkeypatch.setattr(psc, "MAX_TOTAL_RAW_EVENT_CHARS", total)
    _build(metadata=metadata, events=events, documents=documents, eligibility=eligibility)

    monkeypatch.setattr(psc, "MAX_TOTAL_RAW_EVENT_CHARS", total - 1)
    with pytest.raises(PostSessionContextError) as exc:
        _build(metadata=metadata, events=events, documents=documents, eligibility=eligibility)
    assert exc.value.reason is ContextFailureReason.INPUT_TOO_LARGE


def test_total_context_char_limit_is_exact(monkeypatch) -> None:
    metadata = _metadata(("npc-a",))
    documents = {"npc-a": _document()}
    eligibility = _eligibility(("npc-a",))
    events = [_event()]

    baseline = _build(
        metadata=metadata, events=events, documents=documents, eligibility=eligibility
    )
    context_len = len(baseline.identity.context.text)

    monkeypatch.setattr(psc, "MAX_TOTAL_CONTEXT_CHARS", context_len)
    _build(metadata=metadata, events=events, documents=documents, eligibility=eligibility)

    monkeypatch.setattr(psc, "MAX_TOTAL_CONTEXT_CHARS", context_len - 1)
    with pytest.raises(PostSessionContextError) as exc:
        _build(metadata=metadata, events=events, documents=documents, eligibility=eligibility)
    assert exc.value.reason is ContextFailureReason.INPUT_TOO_LARGE
