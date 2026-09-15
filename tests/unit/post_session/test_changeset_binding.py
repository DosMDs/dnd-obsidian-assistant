"""S11-05 type-aware exact binding and stale-projection tests."""

from __future__ import annotations

from dnd_assistant.application.post_session_binding import (
    any_type_exact_matches,
    build_exact_index,
    prepared_projection_matches,
    resolve_mention_targets,
)
from dnd_assistant.domain.types import EntityType, Visibility
from tests.unit.post_session.changeset_helpers import (
    make_document,
    projection_from_document,
)


def test_exact_name_resolution_is_type_constrained() -> None:
    index = build_exact_index([make_document("npc-aria", name="Aria")])
    assert resolve_mention_targets(index, "Aria", EntityType.NPC) == ("npc-aria",)
    assert resolve_mention_targets(index, "Aria", EntityType.LOCATION) == ()


def test_exact_alias_resolution_is_type_constrained() -> None:
    index = build_exact_index([make_document("npc-aria", name="Aria", aliases=["Лорд Ария"])])
    assert resolve_mention_targets(index, "Лорд Ария", EntityType.NPC) == ("npc-aria",)
    assert resolve_mention_targets(index, "Лорд Ария", EntityType.LOCATION) == ()


def test_exact_name_precedence_over_alias() -> None:
    index = build_exact_index(
        [
            make_document("npc-a", name="Aria"),
            make_document("npc-b", name="Borin", aliases=["Aria"]),
        ]
    )
    assert resolve_mention_targets(index, "Aria", EntityType.NPC) == ("npc-a",)


def test_any_type_matches_include_cross_type_and_system() -> None:
    index = build_exact_index(
        [
            make_document("npc-aria", name="Aria"),
            make_document("loc-aria", entity_type=EntityType.LOCATION, name="Aria"),
            make_document(
                "npc-hidden",
                name="Whisper",
                visibility=Visibility.SYSTEM,
                aliases=["The Whisper"],
            ),
        ]
    )
    assert any_type_exact_matches(index, "Aria") == ("npc-aria", "loc-aria")
    assert any_type_exact_matches(index, "The Whisper") == ("npc-hidden",)


def test_normalization_applies_to_resolution() -> None:
    index = build_exact_index([make_document("npc-aria", name="Aria")])
    assert resolve_mention_targets(index, "  ARIA  ", EntityType.NPC) == ("npc-aria",)


def test_prepared_projection_matches_all_compared_fields() -> None:
    document = make_document(
        "npc-aria",
        name="Aria",
        status="alive",
        tags=["ranger"],
        body="Aria is a ranger.\n",
    )
    projection = projection_from_document(document)
    assert prepared_projection_matches(document, projection) is True


def test_prepared_projection_mismatches_each_differing_field() -> None:
    document = make_document("npc-aria", name="Aria", body="body\n")
    projection = projection_from_document(document)

    changed_name = make_document("npc-aria", name="Aria the Bold", body="body\n")
    changed_status = make_document("npc-aria", name="Aria", status="dead", body="body\n")
    changed_tags = make_document("npc-aria", name="Aria", tags=["changed"], body="body\n")
    changed_body = make_document("npc-aria", name="Aria", body="different\n")
    changed_revision = make_document("npc-aria", name="Aria", revision=2, body="body\n")

    assert prepared_projection_matches(changed_name, projection) is False
    assert prepared_projection_matches(changed_status, projection) is False
    assert prepared_projection_matches(changed_tags, projection) is False
    assert prepared_projection_matches(changed_body, projection) is False
    assert prepared_projection_matches(changed_revision, projection) is False
