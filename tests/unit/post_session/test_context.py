"""S11-02 deterministic post-session context assembly unit tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.post_session_context import (
    MAX_ENTITY_BODY_CHARS,
    MAX_ENTITY_PROJECTIONS,
    MAX_RAW_EVENTS,
    ContextFailureReason,
    PostSessionContextError,
    build_post_session_input,
    render_prepared_context,
)
from dnd_assistant.application.post_session_eligibility import (
    EligibilityReason,
    EligibilityResult,
)
from dnd_assistant.application.post_session_identity import (
    compute_input_fingerprint,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.post_session import (
    PreparedCalendarProjection,
    PreparedEntityProjection,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Visibility,
)
from dnd_assistant.errors import NotFoundError, StorageError
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.types import (
    SessionEventRepository,
    SessionMetadataRepository,
    VaultDocument,
    VaultRepository,
)

_START = datetime(2026, 8, 31, 14, 0, 0, tzinfo=UTC)
_END = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)


# ── Fixtures / fakes ──────────────────────────────────────────────────────


def _session(
    session_id: str = "S001",
    *,
    revision: int = 2,
    status: str = "completed",
) -> Session:
    return Session(
        id=session_id,
        type="session",
        status=status,
        real_started_at=_START,
        real_finished_at=_END,
        world_tick_start=100,
        world_tick_end=200,
        revision=revision,
    )


def _metadata(touched: tuple[str, ...] = ("npc-a",), **kwargs: object) -> RawSessionMetadata:
    return RawSessionMetadata(
        session=_session(**kwargs),  # type: ignore[arg-type]
        extra_fields={"touched_entities": list(touched)},
    )


def _entity(
    entity_id: str = "npc-a",
    *,
    entity_type: EntityType = EntityType.NPC,
    revision: int = 3,
    name: str = "Aria",
    status: str = "alive",
    visibility: Visibility = Visibility.PLAYER,
    knowledge_status: KnowledgeStatus = KnowledgeStatus.CONFIRMED,
    tags: list[str] | None = None,
) -> Entity:
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status=status,
        visibility=visibility,
        knowledge_status=knowledge_status,
        created_at=_START,
        updated_at=_START,
        revision=revision,
        tags=tags if tags is not None else ["hero"],
    )


def _document(
    entity_id: str = "npc-a",
    *,
    body: str = "Aria is a ranger.",
    **kwargs: object,
) -> VaultDocument:
    return VaultDocument(entity=_entity(entity_id, **kwargs), body=body)  # type: ignore[arg-type]


def _event(
    event_id: str = "evt_001",
    *,
    tick: int = 150,
    extra: dict[str, object] | None = None,
) -> RawSessionEvent:
    return RawSessionEvent(
        event_id=event_id,
        real_time=_START,
        world_tick=tick,
        type="note",
        extra_fields=extra if extra is not None else {"text": "hello"},
    )


def _eligibility(
    touched: tuple[str, ...] = ("npc-a",),
    *,
    session_id: str = "S001",
    revision: int | None = 2,
    eligible: bool = True,
) -> EligibilityResult:
    return EligibilityResult(
        eligible=eligible,
        reason=EligibilityReason.ELIGIBLE if eligible else EligibilityReason.SESSION_NOT_COMPLETED,
        session_id=session_id,
        session_revision=revision if eligible else None,
        touched_entity_ids=touched,
    )


class _MetadataRepo:
    def __init__(self, metadata: RawSessionMetadata) -> None:
        self._metadata = metadata

    def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
        return self._metadata


class _EventRepo:
    def __init__(self, events: list[RawSessionEvent]) -> None:
        self.events = events
        self.list_calls = 0

    def list_events(self, session_id: str) -> list[RawSessionEvent]:
        self.list_calls += 1
        return list(self.events)


class _VaultRepo:
    def __init__(
        self,
        documents: dict[str, VaultDocument],
        *,
        missing: frozenset[str] = frozenset(),
        corrupt: frozenset[str] = frozenset(),
    ) -> None:
        self._documents = documents
        self._missing = missing
        self._corrupt = corrupt
        self.get_calls: list[str] = []

    def get_entity(self, entity_id: str) -> VaultDocument:
        self.get_calls.append(entity_id)
        if entity_id in self._missing:
            raise NotFoundError(f"not found: {entity_id}")
        if entity_id in self._corrupt:
            raise StorageError(f"corrupt: {entity_id}")
        return self._documents[entity_id]


@dataclass
class _RawEventLike:
    """Duck-typed event allowing non-JSON-compatible extras in unit tests."""

    event_id: str
    real_time: datetime
    world_tick: int
    type: str
    extra_fields: dict[str, object]


def _build(
    *,
    metadata: RawSessionMetadata,
    events: list[RawSessionEvent],
    documents: dict[str, VaultDocument],
    eligibility: EligibilityResult,
    missing: frozenset[str] = frozenset(),
    corrupt: frozenset[str] = frozenset(),
):
    return build_post_session_input(
        metadata_repo=cast(SessionMetadataRepository, _MetadataRepo(metadata)),
        event_repo=cast(SessionEventRepository, _EventRepo(events)),
        vault_repo=cast(
            VaultRepository,
            _VaultRepo(documents, missing=missing, corrupt=corrupt),
        ),
        session_id="S001",
        eligibility=eligibility,
    )


# ── Selection ─────────────────────────────────────────────────────────────


def test_touched_entity_selected_and_projected() -> None:
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[_event()],
        documents={"npc-a": _document()},
        eligibility=_eligibility(("npc-a",)),
    )
    assert tuple(e.id for e in result.identity.entities) == ("npc-a",)
    assert result.identity.session.touched_entities == ("npc-a",)


def test_arbitrary_event_extra_is_never_an_entity_reference() -> None:
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[_event(extra={"entity_id": "npc-secret"})],
        documents={"npc-a": _document()},
        eligibility=_eligibility(("npc-a",)),
    )
    assert tuple(e.id for e in result.identity.entities) == ("npc-a",)


def test_duplicate_touched_ids_are_normalized_first_occurrence() -> None:
    result = _build(
        metadata=_metadata(("npc-b", "npc-a", "npc-b")),
        events=[],
        documents={"npc-a": _document("npc-a"), "npc-b": _document("npc-b")},
        eligibility=_eligibility(("npc-b", "npc-a", "npc-b")),
    )
    assert result.identity.session.touched_entities == ("npc-b", "npc-a")
    assert tuple(e.id for e in result.identity.entities) == ("npc-b", "npc-a")


def test_unrelated_entity_is_not_included() -> None:
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": _document(), "npc-other": _document("npc-other")},
        eligibility=_eligibility(("npc-a",)),
    )
    assert "npc-other" not in {e.id for e in result.identity.entities}


def test_selection_order_follows_touched_order_not_enumeration() -> None:
    result = _build(
        metadata=_metadata(("loc-b", "npc-a")),
        events=[],
        documents={"npc-a": _document("npc-a"), "loc-b": _document("loc-b")},
        eligibility=_eligibility(("loc-b", "npc-a")),
    )
    assert tuple(e.id for e in result.identity.entities) == ("loc-b", "npc-a")


# ── Missing / corrupt / ambiguity boundary ────────────────────────────────


def test_missing_touched_entity_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(("npc-a",)),
            events=[],
            documents={},
            eligibility=_eligibility(("npc-a",)),
            missing=frozenset({"npc-a"}),
        )
    assert exc.value.reason is ContextFailureReason.MISSING_TOUCHED_ENTITY


def test_corrupt_touched_entity_propagates_storage_error() -> None:
    with pytest.raises(StorageError):
        _build(
            metadata=_metadata(("npc-a",)),
            events=[],
            documents={},
            eligibility=_eligibility(("npc-a",)),
            corrupt=frozenset({"npc-a"}),
        )


def test_invalid_touched_entities_fail_closed() -> None:
    metadata = RawSessionMetadata(
        session=_session(),
        extra_fields={"touched_entities": [123]},
    )
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=metadata,
            events=[],
            documents={},
            eligibility=_eligibility(()),
        )
    assert exc.value.reason is ContextFailureReason.INVALID_TOUCHED_ENTITIES


# ── Eligibility revision binding (Correction 2) ───────────────────────────


def test_ineligible_result_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(),
            events=[],
            documents={"npc-a": _document()},
            eligibility=_eligibility(eligible=False),
        )
    assert exc.value.reason is ContextFailureReason.SESSION_INELIGIBLE


def test_session_id_mismatch_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(),
            events=[],
            documents={"npc-a": _document()},
            eligibility=_eligibility(session_id="S999"),
        )
    assert exc.value.reason is ContextFailureReason.ELIGIBILITY_MISMATCH


def test_missing_observed_revision_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(),
            events=[],
            documents={"npc-a": _document()},
            eligibility=_eligibility(revision=None),
        )
    assert exc.value.reason is ContextFailureReason.ELIGIBILITY_MISMATCH


def test_stale_revision_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(revision=3),
            events=[],
            documents={"npc-a": _document()},
            eligibility=_eligibility(revision=2),
        )
    assert exc.value.reason is ContextFailureReason.STALE_ELIGIBILITY_EVIDENCE


def test_changed_status_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(status="active"),
            events=[],
            documents={"npc-a": _document()},
            eligibility=_eligibility(revision=2),
        )
    assert exc.value.reason is ContextFailureReason.STALE_ELIGIBILITY_EVIDENCE


def test_changed_touched_entities_fail_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(("npc-a", "npc-b")),
            events=[],
            documents={"npc-a": _document(), "npc-b": _document("npc-b")},
            eligibility=_eligibility(("npc-a",)),
        )
    assert exc.value.reason is ContextFailureReason.STALE_ELIGIBILITY_EVIDENCE


# ── Projection ────────────────────────────────────────────────────────────


def test_all_canonical_entity_fields_are_projected() -> None:
    doc = _document(
        "npc-a",
        entity_type=EntityType.NPC,
        revision=7,
        name="Aria",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.RUMOR,
        tags=["hero", "ranger"],
        body="Body text.",
    )
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": doc},
        eligibility=_eligibility(("npc-a",)),
    )
    (projected,) = result.identity.entities
    assert projected.id == "npc-a"
    assert projected.type is EntityType.NPC
    assert projected.revision == 7
    assert projected.name == "Aria"
    assert projected.status == "alive"
    assert projected.visibility is Visibility.DM
    assert projected.knowledge_status is KnowledgeStatus.RUMOR
    assert projected.tags == ("hero", "ranger")
    assert projected.body_projection == "Body text."


@pytest.mark.parametrize("visibility", [Visibility.PLAYER, Visibility.DM, Visibility.SYSTEM])
def test_visibility_preserved_exactly(visibility: Visibility) -> None:
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": _document(visibility=visibility)},
        eligibility=_eligibility(("npc-a",)),
    )
    assert result.identity.entities[0].visibility is visibility


def test_knowledge_status_preserved_exactly() -> None:
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": _document(knowledge_status=KnowledgeStatus.INFERRED)},
        eligibility=_eligibility(("npc-a",)),
    )
    assert result.identity.entities[0].knowledge_status is KnowledgeStatus.INFERRED


def test_body_is_included_complete_without_truncation_marker() -> None:
    body = "x" * MAX_ENTITY_BODY_CHARS
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": _document(body=body)},
        eligibility=_eligibility(("npc-a",)),
    )
    assert result.identity.entities[0].body_projection == body
    assert "[...truncated" not in result.identity.context.text


def test_raw_event_extras_projected_deterministically() -> None:
    result = _build(
        metadata=_metadata(()),
        events=[_event(extra={"b": 2, "a": {"y": 1, "x": 2}})],
        documents={},
        eligibility=_eligibility(()),
    )
    (event,) = result.identity.raw_events
    assert event.event_id == "evt_001"
    assert event.extra_fields == {"a": {"x": 2, "y": 1}, "b": 2}


def test_rendered_context_is_pure_function_of_projections() -> None:
    result = _build(
        metadata=_metadata(("npc-a",)),
        events=[_event()],
        documents={"npc-a": _document()},
        eligibility=_eligibility(("npc-a",)),
    )
    expected = render_prepared_context(
        session=result.identity.session,
        raw_events=result.identity.raw_events,
        entities=result.identity.entities,
        calendar=result.identity.calendar,
    )
    assert result.identity.context.text == expected


# ── Fingerprint ───────────────────────────────────────────────────────────


def test_same_evidence_same_fingerprint() -> None:
    def build():
        return _build(
            metadata=_metadata(("npc-a",)),
            events=[_event()],
            documents={"npc-a": _document()},
            eligibility=_eligibility(("npc-a",)),
        )

    assert build().fingerprint == build().fingerprint


def test_selected_revision_change_changes_fingerprint() -> None:
    a = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(revision=3)},
        eligibility=_eligibility(),
    )
    b = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(revision=4)},
        eligibility=_eligibility(),
    )
    assert a.fingerprint != b.fingerprint


def test_body_only_change_changes_fingerprint() -> None:
    a = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(body="one")},
        eligibility=_eligibility(),
    )
    b = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(body="two")},
        eligibility=_eligibility(),
    )
    assert a.fingerprint != b.fingerprint


def test_visibility_only_change_changes_fingerprint() -> None:
    a = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(visibility=Visibility.PLAYER)},
        eligibility=_eligibility(),
    )
    b = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(visibility=Visibility.DM)},
        eligibility=_eligibility(),
    )
    assert a.fingerprint != b.fingerprint


def test_raw_event_order_changes_fingerprint() -> None:
    first = _event("evt_001", tick=150, extra={"text": "one"})
    second = _event("evt_002", tick=160, extra={"text": "two"})
    a = _build(
        metadata=_metadata(()),
        events=[first, second],
        documents={},
        eligibility=_eligibility(()),
    )
    b = _build(
        metadata=_metadata(()),
        events=[second, first],
        documents={},
        eligibility=_eligibility(()),
    )
    assert a.fingerprint != b.fingerprint


def test_unrelated_entity_change_does_not_change_fingerprint() -> None:
    a = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": _document(), "npc-other": _document("npc-other", revision=1)},
        eligibility=_eligibility(("npc-a",)),
    )
    b = _build(
        metadata=_metadata(("npc-a",)),
        events=[],
        documents={"npc-a": _document(), "npc-other": _document("npc-other", revision=99)},
        eligibility=_eligibility(("npc-a",)),
    )
    assert a.fingerprint == b.fingerprint


def test_fingerprint_contains_no_attempt_identity() -> None:
    result = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document()},
        eligibility=_eligibility(),
    )
    dumped = result.identity.model_dump(mode="json")
    assert "attempt" not in str(dumped).lower()


# ── Bounds ────────────────────────────────────────────────────────────────


def test_exactly_at_entity_body_limit_accepted() -> None:
    result = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document(body="x" * MAX_ENTITY_BODY_CHARS)},
        eligibility=_eligibility(),
    )
    assert len(result.identity.entities[0].body_projection) == MAX_ENTITY_BODY_CHARS


def test_one_over_entity_body_limit_fails_closed() -> None:
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(),
            events=[],
            documents={"npc-a": _document(body="x" * (MAX_ENTITY_BODY_CHARS + 1))},
            eligibility=_eligibility(),
        )
    assert exc.value.reason is ContextFailureReason.INPUT_TOO_LARGE


def test_entity_count_over_limit_fails_closed() -> None:
    touched = tuple(f"npc-{i}" for i in range(MAX_ENTITY_PROJECTIONS + 1))
    documents = {eid: _document(eid) for eid in touched}
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(touched),
            events=[],
            documents=documents,
            eligibility=_eligibility(touched),
        )
    assert exc.value.reason is ContextFailureReason.INPUT_TOO_LARGE


def test_raw_event_count_over_limit_fails_closed() -> None:
    events = [_event(f"evt_{i:03d}") for i in range(1, MAX_RAW_EVENTS + 2)]
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(()),
            events=events,
            documents={},
            eligibility=_eligibility(()),
        )
    assert exc.value.reason is ContextFailureReason.INPUT_TOO_LARGE


def test_non_json_extra_value_fails_closed() -> None:
    bad = cast(RawSessionEvent, _RawEventLike("evt_001", _START, 150, "note", {"x": float("nan")}))
    with pytest.raises(PostSessionContextError) as exc:
        _build(
            metadata=_metadata(()),
            events=[bad],
            documents={},
            eligibility=_eligibility(()),
        )
    assert exc.value.reason is ContextFailureReason.UNSUPPORTED_EXTRA_VALUE


# ── Safety / determinism ──────────────────────────────────────────────────


def test_builder_reads_only_selected_entities() -> None:
    vault = _VaultRepo({"npc-a": _document(), "npc-other": _document("npc-other")})
    build_post_session_input(
        metadata_repo=cast(SessionMetadataRepository, _MetadataRepo(_metadata(("npc-a",)))),
        event_repo=cast(SessionEventRepository, _EventRepo([])),
        vault_repo=cast(VaultRepository, vault),
        session_id="S001",
        eligibility=_eligibility(("npc-a",)),
    )
    assert vault.get_calls == ["npc-a"]


def test_calendar_uses_raw_ticks_without_fabricated_dates() -> None:
    result = _build(
        metadata=_metadata(),
        events=[],
        documents={"npc-a": _document()},
        eligibility=_eligibility(),
    )
    assert result.identity.calendar == PreparedCalendarProjection(
        world_tick_start=100, world_tick_end=200
    )


def test_identity_round_trips_through_fingerprint() -> None:
    result = _build(
        metadata=_metadata(),
        events=[_event()],
        documents={"npc-a": _document()},
        eligibility=_eligibility(),
    )
    assert result.fingerprint == compute_input_fingerprint(result.identity)


def test_entity_projection_type_is_required_by_schema() -> None:
    with pytest.raises(PydanticValidationError):
        PreparedEntityProjection(  # type: ignore[call-arg]
            id="npc-a",
            revision=1,
            name="Aria",
            status="alive",
            visibility=Visibility.PLAYER,
            knowledge_status=KnowledgeStatus.CONFIRMED,
        )
