"""S12-04 Fast-Agent Campaign State memory compactness tests.

Exercises ``AgentContextBuilder``'s campaign-memory compacting: the
deterministic entity-count bound and the UTF-8 text-byte budget, including
long ASCII and multibyte Cyrillic values.
"""

from __future__ import annotations

import dataclasses

from dnd_assistant.application.agent_context import (
    MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES,
    MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES,
    AgentCampaignMemory,
    AgentContextBuilder,
    _read_campaign_memory,
)
from dnd_assistant.application.campaign_state_projection import (
    PlayerCampaignEntityReference,
    PlayerCampaignState,
)
from dnd_assistant.domain.types import EntityType
from tests.support.context_builder_doubles import (
    MissingWorldTimeRepository,
    NullSearchService,
    NullSessionEventRepository,
    NullSessionMetadataRepository,
    UntouchedVaultRepository,
)


class _FakeProvider:
    def __init__(self, state: PlayerCampaignState | None) -> None:
        self._state = state
        self.calls = 0

    def get_player_campaign_state(self) -> PlayerCampaignState | None:
        self.calls += 1
        return self._state


def _ref(entity_id: str, name: str = "Aria") -> PlayerCampaignEntityReference:
    return PlayerCampaignEntityReference(entity_id=entity_id, entity_type=EntityType.NPC, name=name)


def _provider(refs: tuple[PlayerCampaignEntityReference, ...]) -> _FakeProvider:
    return _FakeProvider(PlayerCampaignState(recently_touched=refs))


class TestAvailability:
    def test_no_provider_is_none(self) -> None:
        assert _read_campaign_memory(None) is None

    def test_unavailable_provider_is_none(self) -> None:
        memory = _read_campaign_memory(_FakeProvider(None))
        assert memory is None

    def test_zero_entities_is_available_empty_memory(self) -> None:
        memory = _read_campaign_memory(_provider(()))
        assert memory == AgentCampaignMemory(
            recently_touched=(), total_recently_touched=0, truncated=False
        )

    def test_memory_has_no_tick_or_date_field(self) -> None:
        names = {field.name for field in dataclasses.fields(AgentCampaignMemory)}
        assert names == {"recently_touched", "total_recently_touched", "truncated"}


class TestCountBound:
    def test_below_limit(self) -> None:
        refs = tuple(_ref(f"npc-{i:03d}") for i in range(3))
        memory = _read_campaign_memory(_provider(refs))
        assert memory is not None
        assert len(memory.recently_touched) == 3
        assert memory.total_recently_touched == 3
        assert memory.truncated is False

    def test_exactly_at_limit(self) -> None:
        refs = tuple(_ref(f"npc-{i:03d}") for i in range(MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES))
        memory = _read_campaign_memory(_provider(refs))
        assert memory is not None
        assert len(memory.recently_touched) == MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES
        assert memory.total_recently_touched == MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES
        assert memory.truncated is False

    def test_above_limit_is_deterministically_truncated(self) -> None:
        refs = tuple(_ref(f"npc-{i:03d}") for i in range(15))
        first = _read_campaign_memory(_provider(refs))
        second = _read_campaign_memory(_provider(refs))
        assert first == second
        assert first is not None
        assert [e.entity_id for e in first.recently_touched] == [
            f"npc-{i:03d}" for i in range(MAX_AGENT_CAMPAIGN_MEMORY_ENTITIES)
        ]
        assert first.total_recently_touched == 15
        assert first.truncated is True


class TestByteBudget:
    def test_long_ascii_stops_before_first_non_fitting_entry(self) -> None:
        refs = (
            _ref("npc-000", "A" * 700),
            _ref("npc-001", "B" * 700),
            _ref("npc-002", "C" * 700),
        )
        memory = _read_campaign_memory(_provider(refs))
        assert memory is not None
        assert len(memory.recently_touched) == 2
        assert memory.total_recently_touched == 3
        assert memory.truncated is True

    def test_budget_is_utf8_bytes_not_characters(self) -> None:
        # 400 Cyrillic chars = 800 UTF-8 bytes each; a char-based budget would
        # admit all three, a byte budget admits only two.
        refs = (
            _ref("id", "Я" * 400),
            _ref("id", "Ю" * 400),
            _ref("id", "Ж" * 400),
        )
        memory = _read_campaign_memory(_provider(refs))
        assert memory is not None
        assert len(memory.recently_touched) == 2
        assert memory.truncated is True

    def test_first_entry_exceeding_budget_yields_empty_but_truncated(self) -> None:
        refs = (_ref("npc-huge", "A" * (MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES + 1)),)
        memory = _read_campaign_memory(_provider(refs))
        assert memory is not None
        assert memory.recently_touched == ()
        assert memory.total_recently_touched == 1
        assert memory.truncated is True

    def test_long_entity_id_is_never_partially_included(self) -> None:
        huge_id = "npc-" + "x" * (MAX_AGENT_CAMPAIGN_MEMORY_TEXT_BYTES + 1)
        refs = (_ref(huge_id, "A"),)
        memory = _read_campaign_memory(_provider(refs))
        assert memory is not None
        assert memory.recently_touched == ()
        assert memory.truncated is True


class TestBuilderIntegration:
    def _builder(self, provider: _FakeProvider) -> AgentContextBuilder:
        return AgentContextBuilder(
            search_service=NullSearchService(),
            vault_repository=UntouchedVaultRepository(),
            session_repository=NullSessionMetadataRepository(),
            event_repository=NullSessionEventRepository(),
            world_time_repository=MissingWorldTimeRepository(),
            campaign_state_provider=provider,
        )

    def test_campaign_memory_included_not_in_relevant_entities(self) -> None:
        provider = _provider((_ref("npc-aria", "Aria"),))
        ctx = self._builder(provider).build("hello")
        assert ctx.campaign_memory is not None
        assert [e.entity_id for e in ctx.campaign_memory.recently_touched] == ["npc-aria"]
        assert ctx.relevant_entities == ()
        assert provider.calls == 1

    def test_no_provider_leaves_memory_none(self) -> None:
        builder = AgentContextBuilder(
            search_service=NullSearchService(),
            vault_repository=UntouchedVaultRepository(),
            session_repository=NullSessionMetadataRepository(),
            event_repository=NullSessionEventRepository(),
            world_time_repository=MissingWorldTimeRepository(),
        )
        assert builder.build("hello").campaign_memory is None
