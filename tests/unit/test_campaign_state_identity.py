"""S12-01 Campaign State source-snapshot identity and fingerprint tests.

Covers canonical serialization determinism, collection-order normalization,
source-revision sensitivity (source-snapshot identity), calendar-definition
identity, provenance-subset enforcement, Unicode canonicalization and
fingerprint format validation.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dnd_assistant.application.campaign_state_identity import (
    CAMPAIGN_STATE_DERIVATION_VERSION,
    canonical_calendar_definition_bytes,
    canonical_campaign_state_input_bytes,
    compute_calendar_definition_fingerprint,
    compute_input_fingerprint,
)
from dnd_assistant.domain import (
    CampaignEntityReference,
    CampaignSessionSource,
    CampaignStateInputIdentity,
    CampaignWorldTimeSource,
)
from dnd_assistant.domain.calendar import CalendarDefinition, CalendarMonth, GameDate
from dnd_assistant.domain.types import (
    EntityType,
    Sha256Fingerprint,
    Visibility,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _ref(
    entity_id: str = "npc_varos",
    *,
    revision: int = 2,
    name: str = "Магистр Варос",
    visibility: Visibility = Visibility.PLAYER,
    entity_type: EntityType = EntityType.NPC,
    sessions: tuple[str, ...] = ("S001",),
) -> CampaignEntityReference:
    return CampaignEntityReference(
        entity_id=entity_id,
        entity_type=entity_type,
        name=name,
        visibility=visibility,
        revision=revision,
        source_session_ids=sessions,
    )


def _identity(**overrides: Any) -> CampaignStateInputIdentity:
    kwargs: dict[str, Any] = {
        "derivation_version": CAMPAIGN_STATE_DERIVATION_VERSION,
        "world_time": CampaignWorldTimeSource(current_world_tick=13800, revision=1),
        "sessions": (CampaignSessionSource(session_id="S001", revision=5),),
        "entities": (_ref(),),
        "calendar_definition_fingerprint": None,
    }
    kwargs.update(overrides)
    return CampaignStateInputIdentity(**kwargs)


def _calendar(calendar_id: str = "forgotten_realms", *, month_days: int = 30) -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id=calendar_id,
        epoch=GameDate(year=1490, month="Hammer", day=1),
        months=(
            CalendarMonth(name="Hammer", days=month_days),
            CalendarMonth(name="Alturiak", days=30),
        ),
    )


# ── Determinism and ordering ────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_bytes_and_fingerprint(self) -> None:
        assert canonical_campaign_state_input_bytes(_identity()) == (
            canonical_campaign_state_input_bytes(_identity())
        )
        assert compute_input_fingerprint(_identity()) == compute_input_fingerprint(_identity())

    def test_entity_order_is_normalized(self) -> None:
        a = _identity(entities=(_ref("npc_zeta"), _ref("npc_alpha")))
        b = _identity(entities=(_ref("npc_alpha"), _ref("npc_zeta")))
        assert canonical_campaign_state_input_bytes(a) == canonical_campaign_state_input_bytes(b)
        assert compute_input_fingerprint(a) == compute_input_fingerprint(b)

    def test_session_order_is_normalized(self) -> None:
        def sessions(order: tuple[str, ...]) -> tuple[CampaignSessionSource, ...]:
            return tuple(CampaignSessionSource(session_id=s, revision=1) for s in order)

        a = _identity(sessions=sessions(("S003", "S001", "S002")))
        b = _identity(sessions=sessions(("S001", "S002", "S003")))
        assert compute_input_fingerprint(a) == compute_input_fingerprint(b)

    def test_repeated_serialization_is_stable(self) -> None:
        identity = _identity()
        assert canonical_campaign_state_input_bytes(identity) == (
            canonical_campaign_state_input_bytes(identity)
        )

    def test_identity_has_no_wall_clock_or_event_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CampaignStateInputIdentity.model_validate(
                {**_identity().model_dump(), "generated_at": "2026-09-16T00:00:00Z"}
            )
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CampaignStateInputIdentity.model_validate(
                {**_identity().model_dump(), "raw_events": []}
            )


# ── Source-snapshot sensitivity ─────────────────────────────────────────────


class TestSourceSnapshotSensitivity:
    def test_world_tick_change_changes_fingerprint(self) -> None:
        base = _identity()
        changed = _identity(
            world_time=CampaignWorldTimeSource(current_world_tick=13801, revision=1)
        )
        assert compute_input_fingerprint(base) != compute_input_fingerprint(changed)

    def test_world_time_revision_change_changes_fingerprint(self) -> None:
        base = _identity()
        changed = _identity(
            world_time=CampaignWorldTimeSource(current_world_tick=13800, revision=2)
        )
        assert compute_input_fingerprint(base) != compute_input_fingerprint(changed)

    def test_session_revision_change_changes_fingerprint(self) -> None:
        base = _identity()
        changed = _identity(
            sessions=(CampaignSessionSource(session_id="S001", revision=6),),
        )
        assert compute_input_fingerprint(base) != compute_input_fingerprint(changed)

    def test_entity_revision_change_changes_fingerprint(self) -> None:
        base = _identity()
        changed = _identity(entities=(_ref(revision=3),))
        assert compute_input_fingerprint(base) != compute_input_fingerprint(changed)

    @pytest.mark.parametrize(
        "ref",
        [
            _ref(name="Лорд Варос"),
            _ref(visibility=Visibility.DM),
            _ref(entity_type=EntityType.LOCATION),
            _ref(sessions=("S001", "S002")),
        ],
    )
    def test_entity_projection_change_changes_fingerprint(
        self, ref: CampaignEntityReference
    ) -> None:
        base = _identity()
        if ref.source_session_ids == ("S001", "S002"):
            # Keep the provenance subset valid for the changed identity.
            base = _identity(
                sessions=(
                    CampaignSessionSource(session_id="S001", revision=5),
                    CampaignSessionSource(session_id="S002", revision=7),
                )
            )
        assert compute_input_fingerprint(base) != compute_input_fingerprint(
            _identity(
                entities=(ref,),
                sessions=base.sessions,
            )
        )

    def test_entity_added_changes_fingerprint(self) -> None:
        base = _identity()
        changed = _identity(entities=(_ref("npc_alpha"), _ref("npc_varos")))
        assert compute_input_fingerprint(base) != compute_input_fingerprint(changed)


# ── Provenance subset ───────────────────────────────────────────────────────


class TestProvenanceSubset:
    def test_unknown_source_session_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be a subset"):
            _identity(entities=(_ref(sessions=("S999",)),))

    def test_valid_subset_accepted(self) -> None:
        identity = _identity(
            sessions=(
                CampaignSessionSource(session_id="S001", revision=1),
                CampaignSessionSource(session_id="S002", revision=1),
            ),
            entities=(_ref(sessions=("S001", "S002")),),
        )
        assert identity.entities[0].source_session_ids == ("S001", "S002")


# ── Duplicates / invalid values ─────────────────────────────────────────────


class TestInvalidInputs:
    def test_duplicate_session_source_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _identity(
                sessions=(
                    CampaignSessionSource(session_id="S001", revision=1),
                    CampaignSessionSource(session_id="S001", revision=1),
                )
            )

    def test_duplicate_entity_source_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _identity(entities=(_ref("npc_a"), _ref("npc_a")))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("entity_id", ""),
            ("entity_id", " bad"),
            ("revision", 0),
            ("revision", True),
        ],
    )
    def test_invalid_reference_values_rejected(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            _ref(**{field: value})  # type: ignore[arg-type]

    def test_empty_derivation_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _identity(derivation_version="")

    def test_bad_fingerprint_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Sha256Fingerprint(digest="A" * 64)
        with pytest.raises(ValidationError):
            Sha256Fingerprint(digest="abc")


# ── Calendar-definition identity ────────────────────────────────────────────


class TestCalendarDefinitionIdentity:
    def test_same_definition_same_fingerprint(self) -> None:
        assert compute_calendar_definition_fingerprint(_calendar()) == (
            compute_calendar_definition_fingerprint(_calendar())
        )

    def test_same_calendar_id_different_structure_differs(self) -> None:
        a = _calendar(month_days=30)
        b = _calendar(month_days=31)
        assert a.calendar_id == b.calendar_id
        assert canonical_calendar_definition_bytes(a) != canonical_calendar_definition_bytes(b)
        assert compute_calendar_definition_fingerprint(a) != (
            compute_calendar_definition_fingerprint(b)
        )

    def test_calendar_fingerprint_participates_in_input_fingerprint(self) -> None:
        without = _identity(calendar_definition_fingerprint=None)
        with_definition = _identity(
            calendar_definition_fingerprint=compute_calendar_definition_fingerprint(_calendar())
        )
        assert compute_input_fingerprint(without) != compute_input_fingerprint(with_definition)

    def test_different_calendar_definitions_differ_in_input_fingerprint(self) -> None:
        a = _identity(
            calendar_definition_fingerprint=compute_calendar_definition_fingerprint(
                _calendar(month_days=30)
            )
        )
        b = _identity(
            calendar_definition_fingerprint=compute_calendar_definition_fingerprint(
                _calendar(month_days=31)
            )
        )
        assert compute_input_fingerprint(a) != compute_input_fingerprint(b)


# ── Unicode canonicalization ────────────────────────────────────────────────


def test_unicode_canonicalization_golden_value() -> None:
    identity = _identity(
        entities=(_ref("npc_varos", name="Магистр Варос"), _ref("npc_endrin", name="Эндрин")),
    )
    assert compute_input_fingerprint(identity).digest == (
        "53e044a7d1b90f647e6bb9eb987de684529c9fa6a4cdc55f5974f59dcb4771ef"
    )
