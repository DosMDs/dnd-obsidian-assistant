"""S12-02 Campaign State source collection / evidence binding unit tests.

Covers the deterministic selection policy, completed-session eligibility,
touched-evidence normalization, exact entity binding, world-time/calendar
binding, identity/fingerprint sensitivity (including the selection limit) and
fail-closed evidence rules, using in-memory protocol conformant fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from dnd_assistant.application.campaign_state_identity import compute_input_fingerprint
from dnd_assistant.application.campaign_state_source import (
    MAX_RECENT_SESSIONS,
    MAX_TOUCHED_ENTITIES,
    CampaignStateSourceError,
    CampaignStateSourceReason,
    build_campaign_state,
)
from dnd_assistant.domain.calendar import CalendarDefinition, CalendarMonth, GameDate
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.domain.world_time import CurrentWorldTime
from dnd_assistant.errors import NotFoundError
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.types import VaultDocument
from tests.support.repository_doubles import VaultRepositoryWriteStubs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dnd_assistant.domain.calendar import WorldTick
    from dnd_assistant.domain.types import EntityId, Revision
    from dnd_assistant.storage.audit import AuditContext

BASE = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


# ── Builders ──────────────────────────────────────────────────────────────


def _session(
    session_id: str,
    *,
    status: str = "completed",
    finished: datetime | None = None,
    real_started: datetime = BASE,
    tick_start: int = 100,
    tick_end: int | None = 200,
    revision: int = 2,
) -> Session:
    if finished is None and status == "completed":
        finished = BASE + timedelta(hours=2)
    return Session(
        id=session_id,
        type="session",
        status=status,
        real_started_at=real_started,
        real_finished_at=finished,
        world_tick_start=tick_start,
        world_tick_end=tick_end,
        revision=revision,
    )


def _meta(session: Session, touched: object = None) -> RawSessionMetadata:
    extras: dict[str, object] = {}
    if touched is not None:
        extras["touched_entities"] = touched
    return RawSessionMetadata(session=session, extra_fields=extras)


def _entity(
    entity_id: str,
    *,
    name: str = "Aria",
    visibility: Visibility = Visibility.PLAYER,
    entity_type: EntityType = EntityType.NPC,
    revision: int = 1,
) -> Entity:
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status="alive",
        visibility=visibility,
        knowledge_status=KnowledgeStatus.CONFIRMED,
        created_at=BASE,
        updated_at=BASE,
        revision=revision,
    )


def _doc(entity: Entity) -> VaultDocument:
    return VaultDocument(entity=entity)


class FakeSessionRepository:
    """In-memory SessionMetadataRepository read double."""

    def __init__(self, metas: Sequence[RawSessionMetadata]) -> None:
        self._metas = list(metas)
        self.list_calls = 0

    def list_session_metadata(self) -> list[RawSessionMetadata]:
        self.list_calls += 1
        return list(self._metas)

    def allocate_next_session_id(self) -> str:
        raise NotImplementedError

    def create_session(self, session: Session, *, audit: AuditContext) -> RawSessionMetadata:
        raise NotImplementedError

    def get_session_metadata(self, session_id: str) -> RawSessionMetadata:
        raise NotImplementedError

    def get_active_session(self) -> RawSessionMetadata | None:
        raise NotImplementedError

    def close_session(
        self,
        session_id: str,
        *,
        expected_revision: Revision,
        world_tick_end: WorldTick,
        touched_entity_ids: Sequence[EntityId],
        audit: AuditContext,
    ) -> RawSessionMetadata:
        raise NotImplementedError


class FakeVaultRepository(VaultRepositoryWriteStubs):
    """In-memory all-visibility Vault read double."""

    def __init__(self, documents: Sequence[VaultDocument]) -> None:
        self._documents = list(documents)
        self.list_calls = 0

    def list_entities(self, entity_type: EntityType | None = None) -> list[VaultDocument]:
        self.list_calls += 1
        return list(self._documents)

    def get_entity(self, entity_id: str) -> VaultDocument:
        raise NotImplementedError


class FakeWorldTimeRepository:
    """In-memory WorldTimeRepository read double."""

    def __init__(self, current: CurrentWorldTime | None) -> None:
        self._current = current

    def get_current_world_time(self) -> CurrentWorldTime:
        if self._current is None:
            raise NotFoundError("World time not initialised")
        return self._current

    def initialize_current_world_time(
        self, world_tick: WorldTick, *, audit: AuditContext
    ) -> CurrentWorldTime:
        raise NotImplementedError

    def set_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        raise NotImplementedError


def _build(
    metas: Sequence[RawSessionMetadata] = (),
    documents: Sequence[VaultDocument] = (),
    *,
    limit: int = 5,
    world_tick: int | None = 150,
    world_revision: int = 1,
    calendar: CalendarDefinition | None = None,
):
    if world_tick is None:
        world = FakeWorldTimeRepository(None)
    else:
        world = FakeWorldTimeRepository(
            CurrentWorldTime(current_world_tick=world_tick, revision=world_revision)
        )
    return build_campaign_state(
        vault_repository=FakeVaultRepository(documents),
        session_repository=FakeSessionRepository(metas),
        world_time_repository=world,
        recent_session_limit=limit,
        calendar_definition=calendar,
    )


def _calendar(month_days: int = 30) -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id="forgotten_realms",
        epoch=GameDate(year=1490, month="Hammer", day=1),
        months=(
            CalendarMonth(name="Hammer", days=month_days),
            CalendarMonth(name="Alturiak", days=30),
        ),
    )


# ── Zero / fewer than N ───────────────────────────────────────────────────


def test_zero_completed_sessions_yields_valid_empty_state() -> None:
    result = _build(world_tick=13800)
    assert result.state.current_world_tick == 13800
    assert result.state.current_game_date is None
    assert result.state.recently_touched == ()
    assert result.identity.sessions == ()
    assert result.identity.entities == ()
    assert result.identity.recent_session_limit == 5
    assert result.state.input_fingerprint == compute_input_fingerprint(result.identity)


def test_fewer_than_limit_selects_all() -> None:
    metas = [
        _meta(_session("S001"), touched=["npc-a"]),
        _meta(_session("S002"), touched=["npc-b"]),
    ]
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    result = _build(metas, docs, limit=10)
    assert tuple(s.session_id for s in result.identity.sessions) == ("S001", "S002")
    assert tuple(r.entity_id for r in result.identity.entities) == ("npc-a", "npc-b")


def test_selection_independent_of_listing_order() -> None:
    a = _meta(_session("S001", finished=BASE + timedelta(hours=1)), touched=["npc-a"])
    b = _meta(_session("S002", finished=BASE + timedelta(hours=2)), touched=["npc-b"])
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    forward = _build([a, b], docs, limit=1)
    reverse = _build([b, a], docs, limit=1)
    assert tuple(s.session_id for s in forward.identity.sessions) == ("S002",)
    assert tuple(s.session_id for s in reverse.identity.sessions) == ("S002",)
    assert forward.state.input_fingerprint == reverse.state.input_fingerprint


def test_non_numeric_session_ids_selected() -> None:
    metas = [
        _meta(_session("Session Alpha", finished=BASE + timedelta(hours=3)), touched=["npc-a"]),
        _meta(_session("session-beta", finished=BASE + timedelta(hours=1)), touched=["npc-b"]),
    ]
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    result = _build(metas, docs, limit=1)
    assert tuple(s.session_id for s in result.identity.sessions) == ("Session Alpha",)


def test_tied_finish_times_deterministic_tiebreak() -> None:
    same = BASE + timedelta(hours=2)
    metas = [
        _meta(_session("S002", finished=same), touched=["npc-b"]),
        _meta(_session("S001", finished=same), touched=["npc-a"]),
    ]
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    result = _build(metas, docs, limit=1)
    assert tuple(s.session_id for s in result.identity.sessions) == ("S001",)


# ── Eligibility / fail-closed ─────────────────────────────────────────────


def test_active_sessions_never_selected() -> None:
    metas = [
        _meta(_session("S001", status="active"), touched=["npc-a"]),
        _meta(_session("S002"), touched=["npc-b"]),
    ]
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    result = _build(metas, docs, limit=5)
    assert tuple(s.session_id for s in result.identity.sessions) == ("S002",)
    assert tuple(r.entity_id for r in result.identity.entities) == ("npc-b",)


def test_unknown_status_fails_closed() -> None:
    metas = [_meta(_session("S001", status="abandoned"), touched=["npc-a"])]
    with pytest.raises(CampaignStateSourceError) as err:
        _build(metas, [], limit=5)
    assert err.value.reason is CampaignStateSourceReason.INVALID_COMPLETED_SESSION


@pytest.mark.parametrize(
    "overrides",
    [
        {"real_finished_at": None},
        {"world_tick_end": None},
        {"world_tick_start": 300, "world_tick_end": 200},
    ],
)
def test_malformed_completed_fails_closed(overrides: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "id": "S001",
        "type": "session",
        "status": "completed",
        "real_started_at": BASE,
        "real_finished_at": BASE + timedelta(hours=2),
        "world_tick_start": 100,
        "world_tick_end": 200,
        "revision": 2,
    }
    payload.update(overrides)
    session = Session.model_validate(payload)
    with pytest.raises(CampaignStateSourceError) as err:
        _build([_meta(session, touched=["npc-a"])], [], limit=5)
    assert err.value.reason is CampaignStateSourceReason.INVALID_COMPLETED_SESSION


def test_missing_touched_entities_is_empty() -> None:
    result = _build([_meta(_session("S001"))], [], limit=5)
    assert result.identity.entities == ()
    assert result.state.recently_touched == ()


@pytest.mark.parametrize(
    "touched",
    ["npc-a", 5, ["npc-a", 7], ["  spaced"]],
)
def test_malformed_touched_entities_fails_closed(touched: object) -> None:
    with pytest.raises(CampaignStateSourceError) as err:
        _build([_meta(_session("S001"), touched=touched)], [], limit=5)
    assert err.value.reason is CampaignStateSourceReason.INVALID_TOUCHED_ENTITIES


def test_duplicate_touched_ids_collapsed() -> None:
    docs = [_doc(_entity("npc-a"))]
    result = _build([_meta(_session("S001"), touched=["npc-a", "npc-a"])], docs, limit=5)
    assert tuple(r.entity_id for r in result.identity.entities) == ("npc-a",)
    assert result.identity.entities[0].source_session_ids == ("S001",)


def test_entity_provenance_union() -> None:
    metas = [
        _meta(_session("S001", finished=BASE + timedelta(hours=1)), touched=["npc-a", "npc-b"]),
        _meta(_session("S002", finished=BASE + timedelta(hours=2)), touched=["npc-a"]),
    ]
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    result = _build(metas, docs, limit=5)
    by_id = {r.entity_id: r for r in result.identity.entities}
    assert by_id["npc-a"].source_session_ids == ("S001", "S002")
    assert by_id["npc-b"].source_session_ids == ("S001",)


def test_missing_touched_entity_fails_closed() -> None:
    with pytest.raises(CampaignStateSourceError) as err:
        _build([_meta(_session("S001"), touched=["npc-missing"])], [], limit=5)
    assert err.value.reason is CampaignStateSourceReason.MISSING_TOUCHED_ENTITY


def test_all_visibilities_admitted_internally() -> None:
    docs = [
        _doc(_entity("npc-player", visibility=Visibility.PLAYER)),
        _doc(_entity("npc-dm", visibility=Visibility.DM)),
        _doc(_entity("npc-system", visibility=Visibility.SYSTEM)),
    ]
    metas = [_meta(_session("S001"), touched=["npc-player", "npc-dm", "npc-system"])]
    result = _build(metas, docs, limit=5)
    assert tuple(r.visibility.value for r in result.identity.entities) == (
        "dm",
        "player",
        "system",
    )


def test_reference_uses_current_entity_fields() -> None:
    docs = [_doc(_entity("npc-a", name="Магистр Варос", entity_type=EntityType.NPC, revision=4))]
    result = _build([_meta(_session("S001"), touched=["npc-a"])], docs, limit=5)
    ref = result.identity.entities[0]
    assert ref.name == "Магистр Варос"
    assert ref.revision == 4
    assert ref.entity_type is EntityType.NPC


# ── World time / calendar ─────────────────────────────────────────────────


def test_missing_world_time_is_bounded_failure() -> None:
    with pytest.raises(CampaignStateSourceError) as err:
        _build(world_tick=None)
    assert err.value.reason is CampaignStateSourceReason.WORLD_TIME_UNAVAILABLE


def test_calendar_absent_vs_supplied() -> None:
    absent = _build(world_tick=13800)
    assert absent.identity.calendar_definition_fingerprint is None
    assert absent.state.current_game_date is None

    supplied = _build(world_tick=13800, calendar=_calendar())
    assert supplied.identity.calendar_definition_fingerprint is not None
    assert supplied.state.current_game_date is not None
    assert supplied.state.current_world_tick == 13800


def test_calendar_definition_change_changes_fingerprint() -> None:
    a = _build(world_tick=13800, calendar=_calendar(month_days=30))
    b = _build(world_tick=13800, calendar=_calendar(month_days=31))
    assert a.state.input_fingerprint != b.state.input_fingerprint


# ── Fingerprint sensitivity / selection ───────────────────────────────────


def test_selection_limit_changes_fingerprint_with_identical_set() -> None:
    metas = [_meta(_session("S001"), touched=["npc-a"])]
    docs = [_doc(_entity("npc-a"))]
    a = _build(metas, docs, limit=3)
    b = _build(metas, docs, limit=4)
    assert a.identity.sessions == b.identity.sessions
    assert a.identity.entities == b.identity.entities
    assert a.state.input_fingerprint != b.state.input_fingerprint


def test_world_time_revision_change_changes_fingerprint() -> None:
    a = _build(world_tick=150, world_revision=1)
    b = _build(world_tick=150, world_revision=2)
    assert a.state.input_fingerprint != b.state.input_fingerprint


def test_session_revision_change_changes_fingerprint() -> None:
    docs = [_doc(_entity("npc-a"))]
    a = _build([_meta(_session("S001", revision=2), touched=["npc-a"])], docs, limit=5)
    b = _build([_meta(_session("S001", revision=3), touched=["npc-a"])], docs, limit=5)
    assert a.state.input_fingerprint != b.state.input_fingerprint


def test_entity_revision_change_changes_fingerprint() -> None:
    metas = [_meta(_session("S001"), touched=["npc-a"])]
    a = _build(metas, [_doc(_entity("npc-a", revision=1))], limit=5)
    b = _build(metas, [_doc(_entity("npc-a", revision=2))], limit=5)
    assert a.state.input_fingerprint != b.state.input_fingerprint


def test_unrelated_entity_change_does_not_change_fingerprint() -> None:
    metas = [_meta(_session("S001"), touched=["npc-a"])]
    a = _build(metas, [_doc(_entity("npc-a")), _doc(_entity("npc-other", revision=1))], limit=5)
    b = _build(metas, [_doc(_entity("npc-a")), _doc(_entity("npc-other", revision=9))], limit=5)
    assert a.state.input_fingerprint == b.state.input_fingerprint


def test_newer_completed_session_changes_selection() -> None:
    docs = [_doc(_entity("npc-a")), _doc(_entity("npc-b"))]
    only_old = [_meta(_session("S001", finished=BASE + timedelta(hours=1)), touched=["npc-a"])]
    with_new = [
        *only_old,
        _meta(_session("S002", finished=BASE + timedelta(hours=2)), touched=["npc-b"]),
    ]
    before = _build(only_old, docs, limit=1)
    after = _build(with_new, docs, limit=1)
    assert tuple(s.session_id for s in before.identity.sessions) == ("S001",)
    assert tuple(s.session_id for s in after.identity.sessions) == ("S002",)
    assert before.state.input_fingerprint != after.state.input_fingerprint


def test_result_identity_and_state_are_consistent() -> None:
    metas = [_meta(_session("S001"), touched=["npc-a"])]
    docs = [_doc(_entity("npc-a"))]
    result = _build(metas, docs, limit=5)
    assert result.state.recently_touched == result.identity.entities
    assert result.state.current_world_tick == result.identity.world_time.current_world_tick


# ── Bounds / limit validation ─────────────────────────────────────────────


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "3", None])
def test_invalid_selection_limit_fails_closed(limit: object) -> None:
    with pytest.raises(CampaignStateSourceError) as err:
        _build(limit=limit)  # type: ignore[arg-type]
    assert err.value.reason is CampaignStateSourceReason.INVALID_SELECTION_LIMIT


def test_selection_limit_above_ceiling_fails_closed() -> None:
    with pytest.raises(CampaignStateSourceError) as err:
        _build(limit=MAX_RECENT_SESSIONS + 1)
    assert err.value.reason is CampaignStateSourceReason.INPUT_TOO_LARGE


def test_touched_entity_count_above_ceiling_fails_closed() -> None:
    touched = [f"npc-{i}" for i in range(MAX_TOUCHED_ENTITIES + 1)]
    with pytest.raises(CampaignStateSourceError) as err:
        _build([_meta(_session("S001"), touched=touched)], [], limit=5)
    assert err.value.reason is CampaignStateSourceReason.INPUT_TOO_LARGE


def test_no_silent_entity_drop_at_ceiling() -> None:
    touched = [f"npc-{i}" for i in range(MAX_TOUCHED_ENTITIES)]
    docs = [_doc(_entity(entity_id)) for entity_id in touched]
    result = _build([_meta(_session("S001"), touched=touched)], docs, limit=5)
    assert len(result.identity.entities) == MAX_TOUCHED_ENTITIES
