"""S12-05 PLAYER hidden-data noninterference tests.

Constructs pairs of trusted internal ``CampaignState`` values whose
PLAYER-visible evidence is identical while DM/SYSTEM evidence differs (ids,
names, revisions, source-session provenance, count and ordering).  Asserts the
stronger property that every PLAYER-facing surface is *equal*, not merely that
known hidden sentinels are absent:

- rendered ``State/*.md`` artifact bytes;
- ``project_player_campaign_state``;
- ``AgentCampaignMemory`` via the Fast-Agent compactness layer;
- exact ``build_agent_request`` USER JSON.

Pure: no filesystem I/O, no model.
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
    PlayerCampaignState,
    project_player_campaign_state,
)
from dnd_assistant.application.campaign_state_render import (
    build_manifest,
    render_campaign_state_artifacts,
)
from dnd_assistant.domain.campaign_state import (
    CampaignEntityReference,
    CampaignState,
    CampaignStateArtifact,
)
from dnd_assistant.domain.types import EntityType, Visibility
from tests.unit.campaign_state.helpers import make_reference, make_state

_FP_A = "a" * 64
_FP_B = "b" * 64
_TICK = 13800


class _FakeProvider:
    def __init__(self, state: PlayerCampaignState | None) -> None:
        self._state = state

    def get_player_campaign_state(self) -> PlayerCampaignState | None:
        return self._state


def _player_refs() -> tuple[CampaignEntityReference, ...]:
    return (
        make_reference("npc-aria", name="Aria", revision=3, source_session_ids=("S001",)),
        make_reference("npc-bren", name="Брен", revision=7, source_session_ids=("S002",)),
        make_reference(
            "loc-tavern",
            name="Таверна",
            entity_type=EntityType.LOCATION,
            revision=1,
            source_session_ids=("S001", "S002"),
        ),
    )


def _state_a() -> CampaignState:
    # State A: no hidden evidence beyond the shared PLAYER references.
    return make_state(_FP_A, tick=_TICK, references=_player_refs())


def _state_b() -> CampaignState:
    # State B: identical PLAYER references plus hidden evidence differing in
    # id, name, revision, provenance, count (more entries) and input ordering.
    hidden = (
        make_reference(
            "npc-z-hidden",
            name="Тайный Лорд",
            visibility=Visibility.DM,
            revision=9,
            source_session_ids=("S900",),
        ),
        make_reference(
            "npc-a-system",
            name="Система",
            visibility=Visibility.SYSTEM,
            revision=5,
            source_session_ids=("S901",),
        ),
        make_reference(
            "npc-m-hidden",
            name="Ещё Тайна",
            visibility=Visibility.DM,
            revision=42,
            source_session_ids=("S902", "S903"),
        ),
    )
    # Interleave hidden and PLAYER refs so input ordering differs too.
    refs = (
        _player_refs()[1],
        hidden[0],
        _player_refs()[0],
        hidden[2],
        hidden[1],
        _player_refs()[2],
    )
    return make_state(_FP_B, tick=_TICK, references=refs)


def _memory(state: CampaignState) -> AgentCampaignMemory:
    memory = _read_campaign_memory(_FakeProvider(project_player_campaign_state(state)))
    assert memory is not None
    return memory


def _user_json(state: CampaignState) -> str:
    context = AgentContext(
        user_input="Кто такая Ария?",
        current_world_tick=_TICK,
        active_session=None,
        relevant_entities=(),
        recent_events=(),
        campaign_memory=_memory(state),
    )
    raw = build_agent_request(context).messages[1].content
    assert raw is not None
    return raw


class TestRenderedBytesNoninterference:
    def test_player_artifact_bytes_identical(self) -> None:
        assert render_campaign_state_artifacts(_state_a()) == render_campaign_state_artifacts(
            _state_b()
        )

    def test_world_state_has_no_hidden_dependent_identity(self) -> None:
        text = render_campaign_state_artifacts(_state_b())[CampaignStateArtifact.WORLD_STATE]
        assert _FP_A not in text
        assert _FP_B not in text
        assert "fingerprint" not in text
        for leaked in ("npc-z-hidden", "Тайный Лорд", "npc-a-system", "Система", "S900", "S902"):
            assert leaked not in text

    def test_manifest_artifact_hashes_identical_but_fingerprint_internal(self) -> None:
        # The internal manifest intentionally binds the all-visibility source
        # fingerprint and therefore differs; artifact hashes are identical
        # because PLAYER bytes are identical.  Manifest is internal metadata.
        texts_a = render_campaign_state_artifacts(_state_a())
        texts_b = render_campaign_state_artifacts(_state_b())
        manifest_a = build_manifest(_state_a(), texts_a)
        manifest_b = build_manifest(_state_b(), texts_b)
        assert manifest_a.input_fingerprint != manifest_b.input_fingerprint
        assert [a.content_hash for a in manifest_a.artifacts] == [
            a.content_hash for a in manifest_b.artifacts
        ]


class TestProjectionAndMemoryNoninterference:
    def test_projection_equal(self) -> None:
        assert project_player_campaign_state(_state_a()) == project_player_campaign_state(
            _state_b()
        )

    def test_agent_campaign_memory_equal(self) -> None:
        assert _memory(_state_a()) == _memory(_state_b())

    def test_user_json_equal(self) -> None:
        assert _user_json(_state_a()) == _user_json(_state_b())

    def test_user_json_has_no_hidden_material(self) -> None:
        raw = _user_json(_state_b())
        for leaked in (
            "npc-z-hidden",
            "Тайный Лорд",
            "npc-a-system",
            "Система",
            "S900",
            "S901",
            "S902",
            "S903",
        ):
            assert leaked not in raw


class TestHiddenCountDoesNotLeak:
    def _with_hidden(self, hidden_count: int) -> CampaignState:
        hidden = tuple(
            make_reference(
                f"hidden-{i:03d}",
                name=f"Hidden {i}",
                visibility=Visibility.DM,
                revision=i + 1,
                source_session_ids=(f"S{i:03d}",),
            )
            for i in range(hidden_count)
        )
        return make_state(_FP_B, tick=_TICK, references=_player_refs() + hidden)

    def test_hundred_hidden_refs_do_not_change_player_surfaces(self) -> None:
        baseline = self._with_hidden(0)
        heavy = self._with_hidden(100)

        assert render_campaign_state_artifacts(baseline) == render_campaign_state_artifacts(heavy)
        assert project_player_campaign_state(baseline) == project_player_campaign_state(heavy)

        baseline_memory = _memory(baseline)
        heavy_memory = _memory(heavy)
        assert heavy_memory == baseline_memory
        assert heavy_memory.total_recently_touched == baseline_memory.total_recently_touched
        assert heavy_memory.truncated is baseline_memory.truncated
        assert [e.entity_id for e in heavy_memory.recently_touched] == [
            e.entity_id for e in baseline_memory.recently_touched
        ]
        assert _user_json(baseline) == _user_json(heavy)

    def test_user_json_parsed_shape_is_player_only(self) -> None:
        parsed = json.loads(_user_json(_state_b()))
        assert parsed["campaign_memory"] == {
            "recently_touched": [
                {"entity_id": "loc-tavern", "entity_type": "location", "name": "Таверна"},
                {"entity_id": "npc-aria", "entity_type": "npc", "name": "Aria"},
                {"entity_id": "npc-bren", "entity_type": "npc", "name": "Брен"},
            ],
            "total_recently_touched": 3,
            "truncated": False,
        }
