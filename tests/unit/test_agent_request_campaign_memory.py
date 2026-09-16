"""S12-04 deterministic USER request ``campaign_memory`` contract tests.

Proves the additive ``campaign_memory`` USER JSON field is explicit, stable
and player-safe, and that no hidden DM/SYSTEM material or internal Campaign
State identity can reach the model payload.
"""

from __future__ import annotations

import json

from dnd_assistant.application.agent_context import (
    AgentCampaignMemory,
    AgentContext,
    _read_campaign_memory,
)
from dnd_assistant.application.agent_contracts import build_agent_request
from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignEntityReference,
    PlayerCampaignState,
)
from dnd_assistant.domain.types import EntityType, Visibility
from tests.unit.campaign_state.helpers import make_reference, make_state

_FP = "f" * 64


class _FakeProvider:
    def __init__(self, state: PlayerCampaignState | None) -> None:
        self._state = state

    def get_player_campaign_state(self) -> PlayerCampaignState | None:
        return self._state


def _memory_from_state(state: object) -> AgentCampaignMemory:
    from dnd_assistant.application.campaign_state_projection import (
        project_player_campaign_state,
    )

    projection = project_player_campaign_state(state)  # type: ignore[arg-type]
    memory = _read_campaign_memory(_FakeProvider(projection))
    assert memory is not None
    return memory


def _context(memory: AgentCampaignMemory | None, tick: int | None = 13800) -> AgentContext:
    return AgentContext(
        user_input="Кто такая Ария?",
        current_world_tick=tick,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
        campaign_memory=memory,
    )


def _payload(context: AgentContext) -> tuple[str, dict[str, object]]:
    request = build_agent_request(context)
    raw = request.messages[1].content
    assert raw is not None
    return raw, json.loads(raw)


def _mixed_state():
    return make_state(
        _FP,
        references=(
            make_reference("npc-player", name="Aria", revision=3, source_session_ids=("S001",)),
            make_reference(
                "npc-dm",
                name="Тайный Лорд",
                visibility=Visibility.DM,
                revision=9,
                source_session_ids=("S777",),
            ),
            make_reference(
                "npc-sys",
                name="Система",
                visibility=Visibility.SYSTEM,
                revision=5,
                source_session_ids=("S888",),
            ),
        ),
    )


class TestShape:
    def test_campaign_memory_always_present_null_when_unavailable(self) -> None:
        _, parsed = _payload(_context(None))
        assert "campaign_memory" in parsed
        assert parsed["campaign_memory"] is None

    def test_available_memory_exact_shape(self) -> None:
        memory = _memory_from_state(_mixed_state())
        raw, parsed = _payload(_context(memory))
        assert parsed["campaign_memory"] == {
            "recently_touched": [{"entity_id": "npc-player", "entity_type": "npc", "name": "Aria"}],
            "total_recently_touched": 1,
            "truncated": False,
        }

    def test_campaign_memory_is_distinct_from_relevant_entities(self) -> None:
        memory = _memory_from_state(_mixed_state())
        _, parsed = _payload(_context(memory))
        assert parsed["relevant_entities"] == []
        assert parsed["campaign_memory"] is not None

    def test_world_tick_remains_the_only_world_time_field(self) -> None:
        memory = _memory_from_state(_mixed_state())
        _, parsed = _payload(_context(memory, tick=13800))
        assert parsed["current_world_tick"] == 13800
        assert set(parsed["campaign_memory"]) == {  # type: ignore[arg-type]
            "recently_touched",
            "total_recently_touched",
            "truncated",
        }

    def test_unicode_preserved(self) -> None:
        state = make_state(_FP, references=(make_reference("npc-a", name="Гэндальф"),))
        raw, _ = _payload(_context(_memory_from_state(state)))
        assert "Гэндальф" in raw


class TestHiddenDataNoninterference:
    def test_dm_system_material_absent_from_exact_user_json(self) -> None:
        raw, parsed = _payload(_context(_memory_from_state(_mixed_state())))

        for leaked in (
            "Тайный Лорд",
            "npc-dm",
            "Система",
            "npc-sys",
            "S777",
            "S888",
            _FP,
        ):
            assert leaked not in raw, f"hidden material leaked into USER JSON: {leaked}"

        for internal_key in (
            "visibility",
            "revision",
            "source_session_ids",
            "input_fingerprint",
            "fingerprint",
            "current_game_date",
            "current_world_tick",  # must not appear inside campaign_memory
        ):
            if internal_key == "current_world_tick":
                assert internal_key not in parsed["campaign_memory"]  # type: ignore[operator]
            else:
                assert internal_key not in raw

    def test_memory_entries_never_carry_hidden_fields(self) -> None:
        memory = _memory_from_state(_mixed_state())
        assert len(memory.recently_touched) == 1
        entry = memory.recently_touched[0]
        assert entry.entity_id == "npc-player"
        assert entry.name == "Aria"
        assert entry.entity_type is EntityType.NPC
        assert not hasattr(entry, "revision")
        assert not hasattr(entry, "visibility")
        assert not hasattr(entry, "source_session_ids")

    def test_player_only_projection_boundary(self) -> None:
        projection = PlayerCampaignState(
            recently_touched=(
                PlayerCampaignEntityReference(
                    entity_id="npc-a", entity_type=EntityType.NPC, name="Aria"
                ),
            )
        )
        memory = _read_campaign_memory(_FakeProvider(projection))
        assert memory is not None
        raw, _ = _payload(_context(memory))
        assert "Aria" in raw
