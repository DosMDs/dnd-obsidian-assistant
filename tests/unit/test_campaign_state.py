"""Unit tests for S2-05 CampaignState domain schema.

Covers CampaignState model construction, field-level validation,
discriminator fields, EntityId references, text list validation,
Revision behaviour, extra-field rejection, serialisation and
round-trip behaviour.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import CampaignState

# ── Helpers ─────────────────────────────────────────────────────────────────

_CANONICAL_KWARGS = {
    "current_location": "loc_neverwinter",
    "active_quests": ["quest_dragon", "quest_artifact"],
    "party_goals": ["Find the dragon", "Secure the artifact"],
    "important_npcs": ["npc_elira", "npc_theron"],
    "upcoming_deadlines": ["event_full_moon", "event_ritual"],
    "unresolved_threads": ["The missing caravan", "The ancient symbol"],
    "revision": 1,
}


def _make(**overrides: object) -> CampaignState:
    """Build a CampaignState from canonical kwargs with optional overrides."""
    return CampaignState(**{**_CANONICAL_KWARGS, **overrides})  # type: ignore[arg-type]


# ── Valid construction ──────────────────────────────────────────────────────


class TestValidConstruction:
    def test_minimal_valid_state(self) -> None:
        """Build a minimal valid state with only required fields."""
        state = CampaignState(revision=1)
        assert state.schema_version == 1
        assert state.type == "campaign_state"
        assert state.current_location is None
        assert state.active_quests == []
        assert state.party_goals == []
        assert state.important_npcs == []
        assert state.upcoming_deadlines == []
        assert state.unresolved_threads == []
        assert state.revision == 1

    def test_populated_canonical_state(self) -> None:
        """Build the canonical populated example."""
        state = _make()
        assert state.current_location == "loc_neverwinter"
        assert state.active_quests == ["quest_dragon", "quest_artifact"]
        assert state.party_goals == ["Find the dragon", "Secure the artifact"]
        assert state.important_npcs == ["npc_elira", "npc_theron"]
        assert state.upcoming_deadlines == ["event_full_moon", "event_ritual"]
        assert state.unresolved_threads == ["The missing caravan", "The ancient symbol"]
        assert state.revision == 1

    def test_default_empty_lists(self) -> None:
        """All list fields default to empty lists."""
        state = CampaignState(revision=1)
        assert state.active_quests == []
        assert state.party_goals == []
        assert state.important_npcs == []
        assert state.upcoming_deadlines == []
        assert state.unresolved_threads == []

    def test_list_defaults_are_independent(self) -> None:
        """List defaults are independent between instances."""
        state_a = CampaignState(revision=1)
        state_b = CampaignState(revision=1)
        state_a.active_quests.append("quest_test")
        assert len(state_a.active_quests) == 1
        assert len(state_b.active_quests) == 0

    def test_unicode_party_goals(self) -> None:
        """Accept printable Cyrillic party goals."""
        state = _make(party_goals=["Найти дракона"])
        assert state.party_goals == ["Найти дракона"]

    def test_unicode_unresolved_threads(self) -> None:
        """Accept printable Cyrillic unresolved threads."""
        state = _make(unresolved_threads=["Древний символ"])
        assert state.unresolved_threads == ["Древний символ"]

    def test_current_location_none(self) -> None:
        """current_location is optional and defaults to None."""
        state = CampaignState(revision=1)
        assert state.current_location is None

    def test_current_location_explicit_none(self) -> None:
        state = _make(current_location=None)
        assert state.current_location is None


# ── schema_version ──────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_default_is_one(self) -> None:
        state = _make()
        assert state.schema_version == 1

    def test_accepts_one(self) -> None:
        state = _make(schema_version=1)
        assert state.schema_version == 1

    def test_rejects_two(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=2)

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version=0)

    def test_rejects_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(schema_version="1")  # type: ignore[arg-type]


# ── type discriminator ──────────────────────────────────────────────────────


class TestType:
    def test_accepts_campaign_state(self) -> None:
        state = _make(type="campaign_state")
        assert state.type == "campaign_state"

    def test_default_is_campaign_state(self) -> None:
        state = _make()
        assert state.type == "campaign_state"

    def test_rejects_other_values(self) -> None:
        with pytest.raises(ValidationError):
            _make(type="session")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make(type="")  # type: ignore[arg-type]

    def test_rejects_none(self) -> None:
        with pytest.raises(ValidationError):
            _make(type=None)  # type: ignore[arg-type]


# ── current_location (EntityId) ─────────────────────────────────────────────


class TestCurrentLocation:
    def test_accepts_valid_entity_id(self) -> None:
        state = _make(current_location="loc_waterdeep")
        assert state.current_location == "loc_waterdeep"

    def test_accepts_unicode_id(self) -> None:
        state = _make(current_location="локация_01")
        assert state.current_location == "локация_01"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make(current_location="")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError):
            _make(current_location=" ")

    def test_rejects_leading_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(current_location=" leading")

    def test_rejects_trailing_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(current_location="trailing ")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(current_location=123)  # type: ignore[arg-type]


# ── active_quests (list[EntityId]) ──────────────────────────────────────────


class TestActiveQuests:
    def test_accepts_valid_entity_ids(self) -> None:
        state = _make(active_quests=["quest_a", "quest_b"])
        assert state.active_quests == ["quest_a", "quest_b"]

    def test_accepts_empty_list(self) -> None:
        state = _make(active_quests=[])
        assert state.active_quests == []

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(active_quests=[""])

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError):
            _make(active_quests=[" "])

    def test_rejects_leading_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(active_quests=[" quest"])

    def test_rejects_trailing_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(active_quests=["quest "])

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(active_quests=[123])  # type: ignore[list-item]


# ── important_npcs (list[EntityId]) ─────────────────────────────────────────


class TestImportantNpcs:
    def test_accepts_valid_entity_ids(self) -> None:
        state = _make(important_npcs=["npc_a", "npc_b"])
        assert state.important_npcs == ["npc_a", "npc_b"]

    def test_accepts_empty_list(self) -> None:
        state = _make(important_npcs=[])
        assert state.important_npcs == []

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(important_npcs=[""])

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError):
            _make(important_npcs=[" "])

    def test_rejects_leading_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(important_npcs=[" npc"])

    def test_rejects_trailing_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(important_npcs=["npc "])

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(important_npcs=[123])  # type: ignore[list-item]


# ── upcoming_deadlines (list[EntityId]) ─────────────────────────────────────


class TestUpcomingDeadlines:
    def test_accepts_valid_entity_ids(self) -> None:
        state = _make(upcoming_deadlines=["event_a", "event_b"])
        assert state.upcoming_deadlines == ["event_a", "event_b"]

    def test_accepts_empty_list(self) -> None:
        state = _make(upcoming_deadlines=[])
        assert state.upcoming_deadlines == []

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(upcoming_deadlines=[""])

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError):
            _make(upcoming_deadlines=[" "])

    def test_rejects_leading_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(upcoming_deadlines=[" event"])

    def test_rejects_trailing_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            _make(upcoming_deadlines=["event "])

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(upcoming_deadlines=[123])  # type: ignore[list-item]


# ── party_goals (list[PrintableNonEmptyStr]) ────────────────────────────────


class TestPartyGoals:
    @pytest.mark.parametrize(
        "invalid_goal",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            " goal",
            "goal ",
            " goal ",
            "\tleading",
            "trailing\n",
        ],
    )
    def test_rejects_invalid_goals(self, invalid_goal: str) -> None:
        with pytest.raises(ValidationError):
            _make(party_goals=[invalid_goal])

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(party_goals=["Find the\x00dragon"])

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(party_goals=[123])  # type: ignore[list-item]

    def test_accepts_unicode(self) -> None:
        state = _make(party_goals=["Найти дракона"])
        assert state.party_goals == ["Найти дракона"]


# ── unresolved_threads (list[PrintableNonEmptyStr]) ─────────────────────────


class TestUnresolvedThreads:
    @pytest.mark.parametrize(
        "invalid_thread",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            " thread",
            "thread ",
            " thread ",
            "\tleading",
            "trailing\n",
        ],
    )
    def test_rejects_invalid_threads(self, invalid_thread: str) -> None:
        with pytest.raises(ValidationError):
            _make(unresolved_threads=[invalid_thread])

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(ValidationError):
            _make(unresolved_threads=["The ancient\x00symbol"])

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            _make(unresolved_threads=[123])  # type: ignore[list-item]

    def test_accepts_unicode(self) -> None:
        state = _make(unresolved_threads=["Древний символ"])
        assert state.unresolved_threads == ["Древний символ"]


# ── revision ────────────────────────────────────────────────────────────────


class TestRevision:
    @pytest.mark.parametrize("valid_revision", [1, 2, 100, 999])
    def test_accepts_valid_revisions(self, valid_revision: int) -> None:
        state = _make(revision=valid_revision)
        assert state.revision == valid_revision

    @pytest.mark.parametrize("invalid_revision", [0, -1, -100])
    def test_rejects_non_positive_integers(self, invalid_revision: int) -> None:
        with pytest.raises(ValidationError):
            _make(revision=invalid_revision)

    @pytest.mark.parametrize("bool_value", [True, False])
    def test_rejects_bool(self, bool_value: bool) -> None:
        with pytest.raises(ValidationError):
            _make(revision=bool_value)

    def test_rejects_string_coercion(self) -> None:
        with pytest.raises(ValidationError):
            _make(revision="1")  # type: ignore[arg-type]

    def test_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            _make(revision=1.0)  # type: ignore[arg-type]


# ── extra fields ────────────────────────────────────────────────────────────


class TestExtraFields:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CampaignState(  # type: ignore[call-arg]
                **_CANONICAL_KWARGS,
                world_tick=100,
            )


# ── serialisation ───────────────────────────────────────────────────────────


class TestSerialization:
    def test_model_dump_python(self) -> None:
        state = _make()
        dumped = state.model_dump()
        assert dumped["schema_version"] == 1
        assert dumped["type"] == "campaign_state"
        assert dumped["current_location"] == "loc_neverwinter"
        assert dumped["active_quests"] == ["quest_dragon", "quest_artifact"]
        assert dumped["party_goals"] == ["Find the dragon", "Secure the artifact"]
        assert dumped["important_npcs"] == ["npc_elira", "npc_theron"]
        assert dumped["upcoming_deadlines"] == ["event_full_moon", "event_ritual"]
        assert dumped["unresolved_threads"] == ["The missing caravan", "The ancient symbol"]
        assert dumped["revision"] == 1

    def test_model_dump_json(self) -> None:
        state = _make()
        dumped = state.model_dump(mode="json")
        assert dumped["schema_version"] == 1
        assert dumped["type"] == "campaign_state"
        assert dumped["current_location"] == "loc_neverwinter"
        assert dumped["active_quests"] == ["quest_dragon", "quest_artifact"]
        assert dumped["party_goals"] == ["Find the dragon", "Secure the artifact"]
        assert dumped["important_npcs"] == ["npc_elira", "npc_theron"]
        assert dumped["upcoming_deadlines"] == ["event_full_moon", "event_ritual"]
        assert dumped["unresolved_threads"] == ["The missing caravan", "The ancient symbol"]
        assert dumped["revision"] == 1

    def test_round_trip(self) -> None:
        state = _make()
        data = state.model_dump(mode="json")
        restored = CampaignState.model_validate(data)
        assert restored.schema_version == state.schema_version
        assert restored.type == state.type
        assert restored.current_location == state.current_location
        assert restored.active_quests == state.active_quests
        assert restored.party_goals == state.party_goals
        assert restored.important_npcs == state.important_npcs
        assert restored.upcoming_deadlines == state.upcoming_deadlines
        assert restored.unresolved_threads == state.unresolved_threads
        assert restored.revision == state.revision

    def test_minimal_round_trip(self) -> None:
        state = CampaignState(revision=1)
        data = state.model_dump(mode="json")
        restored = CampaignState.model_validate(data)
        assert restored.revision == 1
        assert restored.current_location is None
        assert restored.active_quests == []
        assert restored.party_goals == []
        assert restored.important_npcs == []
        assert restored.upcoming_deadlines == []
        assert restored.unresolved_threads == []


# ── domain import smoke test ────────────────────────────────────────────────


def test_campaign_state_module_importable() -> None:
    """Verify the campaign_state module can be imported without pulling in upper layers."""
    import dnd_assistant.domain.campaign_state  # noqa: F401
