"""S12-04 player-safe Campaign State projection tests.

Proves the projection boundary admits only ``Visibility.PLAYER`` references,
carries only the player-safe minimum, is deterministic and never mutates the
trusted internal ``CampaignState``.
"""

from __future__ import annotations

import dataclasses

from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignEntityReference,
    PlayerCampaignState,
    project_player_campaign_state,
)
from dnd_assistant.domain.types import EntityType, Visibility
from tests.unit.campaign_state.helpers import make_reference, make_state

_FP = "a" * 64


def _state(*references: object):
    return make_state(_FP, references=tuple(references))  # type: ignore[arg-type]


class TestVisibilityFiltering:
    def test_player_reference_retained(self) -> None:
        state = _state(make_reference("npc-player", name="Aria"))
        projection = project_player_campaign_state(state)
        assert projection.recently_touched == (
            PlayerCampaignEntityReference(
                entity_id="npc-player", entity_type=EntityType.NPC, name="Aria"
            ),
        )

    def test_dm_reference_excluded(self) -> None:
        state = _state(
            make_reference("npc-dm", name="Тайный Лорд", visibility=Visibility.DM),
        )
        assert project_player_campaign_state(state).recently_touched == ()

    def test_system_reference_excluded(self) -> None:
        state = _state(
            make_reference("npc-sys", name="Система", visibility=Visibility.SYSTEM),
        )
        assert project_player_campaign_state(state).recently_touched == ()

    def test_mixed_visibility_keeps_only_player(self) -> None:
        state = _state(
            make_reference("npc-player", name="Aria"),
            make_reference("npc-dm", name="Тайный Лорд", visibility=Visibility.DM),
            make_reference("npc-sys", name="Система", visibility=Visibility.SYSTEM),
        )
        projection = project_player_campaign_state(state)
        assert [ref.entity_id for ref in projection.recently_touched] == ["npc-player"]

    def test_zero_references(self) -> None:
        projection = project_player_campaign_state(make_state(_FP))
        assert projection.recently_touched == ()


class TestDeterminism:
    def test_order_is_entity_id_ascending(self) -> None:
        state = _state(
            make_reference("npc-z", name="Zeta"),
            make_reference("npc-a", name="Alpha"),
            make_reference("npc-m", name="Mu"),
        )
        projection = project_player_campaign_state(state)
        assert [ref.entity_id for ref in projection.recently_touched] == [
            "npc-a",
            "npc-m",
            "npc-z",
        ]

    def test_repeated_projection_is_equal(self) -> None:
        state = _state(make_reference("npc-a"), make_reference("npc-b"))
        assert project_player_campaign_state(state) == project_player_campaign_state(state)


class TestDataMinimization:
    def test_reference_fields_are_exact_minimum(self) -> None:
        names = {field.name for field in dataclasses.fields(PlayerCampaignEntityReference)}
        assert names == {"entity_id", "entity_type", "name"}

    def test_projection_carries_only_recently_touched(self) -> None:
        field_names = {field.name for field in dataclasses.fields(PlayerCampaignState)}
        assert field_names == {"recently_touched"}

    def test_no_internal_fields_exposed(self) -> None:
        state = _state(
            make_reference(
                "npc-a",
                name="Aria",
                visibility=Visibility.PLAYER,
                revision=7,
                source_session_ids=("S001", "S002"),
            )
        )
        projection = project_player_campaign_state(state)
        ref = projection.recently_touched[0]
        assert ref.entity_id == "npc-a"
        assert ref.name == "Aria"
        assert not hasattr(ref, "visibility")
        assert not hasattr(ref, "revision")
        assert not hasattr(ref, "source_session_ids")
        assert not hasattr(projection, "input_fingerprint")
        assert not hasattr(projection, "current_world_tick")
        assert not hasattr(projection, "current_game_date")


class TestNoMutation:
    def test_internal_state_unchanged(self) -> None:
        state = _state(
            make_reference("npc-z", name="Zeta"),
            make_reference("npc-a", name="Alpha"),
        )
        before = state.model_dump()
        project_player_campaign_state(state)
        assert state.model_dump() == before
        assert [ref.entity_id for ref in state.recently_touched] == ["npc-a", "npc-z"]
