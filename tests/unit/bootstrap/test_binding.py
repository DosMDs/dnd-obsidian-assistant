"""S13-03 exact binding and duplicate-prevention tests."""

from __future__ import annotations

from dnd_assistant.application.bootstrap_binding import (
    any_type_exact_matches,
    build_bootstrap_index,
    resolve_exact_target,
)
from dnd_assistant.application.bootstrap_canonical import build_canonical_snapshot
from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.bootstrap_canonical import parse_canonical_candidate
from tests.unit.bootstrap.helpers import canonical_text


def _index(*candidates):
    return build_bootstrap_index(build_canonical_snapshot(candidates))


def _cand(path: str, entity_id: str, entity_type: EntityType, name: str, aliases=None):
    return parse_canonical_candidate(
        path, canonical_text(entity_id, entity_type, name, aliases=aliases)
    )


def test_exact_name_and_alias_resolution() -> None:
    index = _index(
        _cand("Characters/NPCs/v.md", "npc-1", EntityType.NPC, "Варос", aliases=["Магистр"])
    )
    assert resolve_exact_target(index, "Варос", EntityType.NPC) == ("npc-1",)
    assert resolve_exact_target(index, "Магистр", EntityType.NPC) == ("npc-1",)


def test_type_constrained_resolution_does_not_cross_types() -> None:
    index = _index(_cand("Characters/NPCs/v.md", "npc-1", EntityType.NPC, "Ключ"))
    assert resolve_exact_target(index, "Ключ", EntityType.NPC) == ("npc-1",)
    assert resolve_exact_target(index, "Ключ", EntityType.ITEM) == ()


def test_ambiguous_exact_collision() -> None:
    index = _index(
        _cand("Characters/NPCs/a.md", "npc-1", EntityType.NPC, "Варос"),
        _cand("Characters/NPCs/b.md", "npc-2", EntityType.NPC, "варос"),
    )
    assert set(resolve_exact_target(index, "ВАРОС", EntityType.NPC)) == {"npc-1", "npc-2"}


def test_conflicting_identity_is_not_a_target_but_blocks_duplicates() -> None:
    duplicate_a = _cand("Characters/NPCs/a.md", "npc-1", EntityType.NPC, "Варос")
    duplicate_b = _cand("Characters/NPCs/b.md", "npc-1", EntityType.NPC, "Варос")
    index = _index(duplicate_a, duplicate_b)
    assert resolve_exact_target(index, "Варос", EntityType.NPC) == ()
    assert any_type_exact_matches(index, "Варос") == ("npc-1",)


def test_system_entity_participates_in_duplicate_prevention() -> None:
    system = parse_canonical_candidate(
        "Characters/NPCs/sys.md",
        canonical_text("npc-sys", EntityType.NPC, "Правила", visibility="system"),
    )
    index = _index(system)
    assert any_type_exact_matches(index, "Правила") == ("npc-sys",)
