"""Unit tests for the S12-01 CampaignState v2 derived-projection schema.

Covers v2 construction and strict validation, rejection of legacy Stage-2
semantic fields, the recently-touched entity reference contract, honest
"recently touched" semantics, and serialisation round-trips.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import (
    CampaignEntityReference,
    CampaignState,
)
from dnd_assistant.domain.calendar import GameDate
from dnd_assistant.domain.types import (
    EntityType,
    Sha256Fingerprint,
    Visibility,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

_FINGERPRINT = Sha256Fingerprint(digest="a" * 64)


def _ref(
    entity_id: str = "npc_varos",
    *,
    entity_type: EntityType = EntityType.NPC,
    name: str = "Магистр Варос",
    visibility: Visibility = Visibility.PLAYER,
    revision: int = 2,
    source_session_ids: object = ("S001",),
) -> CampaignEntityReference:
    return CampaignEntityReference(
        entity_id=entity_id,
        entity_type=entity_type,
        name=name,
        visibility=visibility,
        revision=revision,
        source_session_ids=source_session_ids,  # type: ignore[arg-type]
    )


def _state(**overrides: object) -> CampaignState:
    kwargs: dict[str, object] = {
        "input_fingerprint": _FINGERPRINT,
        "current_world_tick": 13800,
    }
    kwargs.update(overrides)
    return CampaignState(**kwargs)  # type: ignore[arg-type]


# ── Valid construction ──────────────────────────────────────────────────────


class TestValidConstruction:
    def test_minimal_state(self) -> None:
        state = _state()
        assert state.schema_version == 2
        assert state.type == "campaign_state"
        assert state.input_fingerprint == _FINGERPRINT
        assert state.current_world_tick == 13800
        assert state.current_game_date is None
        assert state.recently_touched == ()

    def test_state_with_game_date_and_references(self) -> None:
        date = GameDate(year=1492, month="Hammer", day=1, hour=12, minute=30)
        state = _state(current_game_date=date, recently_touched=[_ref()])
        assert state.current_game_date == date
        assert state.recently_touched == (_ref(),)

    def test_unicode_name_preserved(self) -> None:
        assert _ref(name="Магистр Варос").name == "Магистр Варос"

    def test_reference_defaults_free_of_extra_data(self) -> None:
        ref = _ref()
        assert ref.entity_type == EntityType.NPC
        assert ref.visibility == Visibility.PLAYER
        assert ref.revision == 2


# ── schema_version / type discriminator ─────────────────────────────────────


class TestDiscriminators:
    def test_schema_version_is_two(self) -> None:
        assert _state().schema_version == 2

    @pytest.mark.parametrize("version", [1, 0, 3])
    def test_rejects_other_schema_versions(self, version: int) -> None:
        with pytest.raises(ValidationError):
            _state(schema_version=version)

    def test_type_is_campaign_state(self) -> None:
        assert _state().type == "campaign_state"

    def test_rejects_other_type(self) -> None:
        with pytest.raises(ValidationError):
            _state(type="session")


# ── Legacy v1 fields must be rejected ───────────────────────────────────────


class TestLegacyFieldsRejected:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("current_location", "loc_grayford"),
            ("active_quests", ["quest_a"]),
            ("important_npcs", ["npc_a"]),
            ("party_goals", ["Find the dragon"]),
            ("unresolved_threads", ["The missing caravan"]),
            ("upcoming_deadlines", ["event_a"]),
            ("revision", 1),
        ],
    )
    def test_rejects_legacy_field(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CampaignState.model_validate(
                {**_state().model_dump(), field: value},
            )

    def test_rejects_whole_v1_payload(self) -> None:
        v1_payload = {
            "schema_version": 1,
            "type": "campaign_state",
            "current_location": "loc_grayford",
            "active_quests": ["quest_missing_caravan"],
            "party_goals": ["Найти караван"],
            "important_npcs": ["npc_varos"],
            "upcoming_deadlines": ["event_x"],
            "unresolved_threads": ["Древний символ"],
            "revision": 1,
        }
        with pytest.raises(ValidationError):
            CampaignState.model_validate(v1_payload)

    def test_has_no_revision_attribute(self) -> None:
        assert not hasattr(_state(), "revision")


# ── Strictness ──────────────────────────────────────────────────────────────


class TestStrictness:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CampaignState.model_validate({**_state().model_dump(), "world_tick": 1})

    def test_frozen(self) -> None:
        state = _state()
        with pytest.raises(ValidationError):
            state.current_world_tick = 1  # type: ignore[misc]

    def test_requires_input_fingerprint(self) -> None:
        with pytest.raises(ValidationError):
            CampaignState(current_world_tick=0)  # type: ignore[call-arg]

    def test_requires_world_tick(self) -> None:
        with pytest.raises(ValidationError):
            CampaignState(input_fingerprint=_FINGERPRINT)  # type: ignore[call-arg]

    def test_input_fingerprint_digest_is_validated(self) -> None:
        with pytest.raises(ValidationError):
            _state(input_fingerprint={"algorithm": "sha256", "digest": "Z" * 64})


# ── Recently-touched reference contract ─────────────────────────────────────


class TestRecentlyTouchedReference:
    def test_source_session_ids_required(self) -> None:
        with pytest.raises(ValidationError):
            _ref(source_session_ids=())

    def test_source_session_ids_duplicates_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not contain duplicates"):
            _ref(source_session_ids=["S002", "S001", "S002"])

    def test_source_session_ids_canonical_order(self) -> None:
        ref = _ref(source_session_ids=["S003", "S001", "S002"])
        assert ref.source_session_ids == ("S001", "S002", "S003")

    def test_source_session_ids_set_input_is_canonicalized(self) -> None:
        ref = _ref(source_session_ids={"S002", "S001"})
        assert ref.source_session_ids == ("S001", "S002")

    def test_source_session_ids_empty_set_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ref(source_session_ids=set())

    def test_source_session_ids_invalid_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ref(source_session_ids=["  S001"])

    def test_recently_touched_normalized_and_deduplicated(self) -> None:
        state = _state(
            recently_touched=[
                _ref("npc_zeta", source_session_ids=["S002"]),
                _ref("npc_alpha", source_session_ids=["S001"]),
            ]
        )
        assert [r.entity_id for r in state.recently_touched] == ["npc_alpha", "npc_zeta"]

    def test_recently_touched_duplicate_entity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _state(recently_touched=[_ref("npc_a"), _ref("npc_a")])

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("entity_id", ""),
            ("entity_id", " leading"),
            ("revision", 0),
            ("revision", True),
            ("visibility", "everyone"),
            ("entity_type", "timeline_event"),
            ("name", ""),
            ("name", " trailing "),
        ],
    )
    def test_reference_field_validation(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            _ref(**{field: value})  # type: ignore[arg-type]

    def test_reference_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CampaignEntityReference.model_validate(
                {
                    "entity_id": "npc_a",
                    "entity_type": "npc",
                    "name": "Aria",
                    "visibility": "player",
                    "revision": 1,
                    "source_session_ids": ["S001"],
                    "knowledge_status": "confirmed",
                }
            )


# ── Serialisation ───────────────────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_json(self) -> None:
        dumped = _state(recently_touched=[_ref()]).model_dump(mode="json")
        assert dumped["schema_version"] == 2
        assert dumped["type"] == "campaign_state"
        assert dumped["current_world_tick"] == 13800
        assert dumped["current_game_date"] is None
        assert dumped["recently_touched"][0]["entity_id"] == "npc_varos"

    def test_round_trip(self) -> None:
        state = _state(
            current_game_date=GameDate(year=1492, month="Hammer", day=1),
            recently_touched=[_ref()],
        )
        restored = CampaignState.model_validate(state.model_dump(mode="json"))
        assert restored == state

    def test_minimal_round_trip(self) -> None:
        state = _state()
        restored = CampaignState.model_validate(state.model_dump(mode="json"))
        assert restored == state


# ── Import smoke test ───────────────────────────────────────────────────────


def test_campaign_state_module_importable() -> None:
    import dnd_assistant.domain.campaign_state  # noqa: F401
