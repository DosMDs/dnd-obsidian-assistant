"""S11-05 deterministic candidate EntityId allocator tests."""

from __future__ import annotations

import re

from dnd_assistant.application.entity_id_allocator import (
    CANDIDATE_ENTITY_ID_ALLOCATOR_VERSION,
    allocate_candidate_entity_id,
    candidate_identity_material,
)
from dnd_assistant.domain.types import EntityType

_ENTITY_ID_PATTERN = re.compile(r"^ent_[0-9a-f]{32}$")


def test_allocated_id_is_bounded_opaque_entity_id() -> None:
    entity_id = allocate_candidate_entity_id("S001", EntityType.NPC, "Aria")
    assert _ENTITY_ID_PATTERN.match(entity_id)


def test_allocator_is_deterministic() -> None:
    first = allocate_candidate_entity_id("S001", EntityType.NPC, "Aria")
    second = allocate_candidate_entity_id("S001", EntityType.NPC, "Aria")
    assert first == second


def test_allocator_does_not_use_display_name_or_candidate_id_directly() -> None:
    entity_id = allocate_candidate_entity_id("S001", EntityType.NPC, "Aria")
    assert entity_id != "Aria"
    assert "Aria" not in entity_id


def test_allocation_material_excludes_evidence_and_candidate_identity() -> None:
    material = candidate_identity_material("S001", EntityType.NPC, "Aria")
    assert material == {
        "allocator_version": CANDIDATE_ENTITY_ID_ALLOCATOR_VERSION,
        "session_ref": "S001",
        "entity_type": "npc",
        "name": "aria",
    }
    assert "evidence" not in material
    assert "candidate_id" not in material


def test_normalization_makes_name_variants_identical() -> None:
    canonical = allocate_candidate_entity_id("S001", EntityType.NPC, "Aria")
    variant = allocate_candidate_entity_id("S001", EntityType.NPC, "  ARIA  ")
    assert canonical == variant


def test_distinct_material_yields_distinct_ids() -> None:
    base = allocate_candidate_entity_id("S001", EntityType.NPC, "Aria")
    assert allocate_candidate_entity_id("S002", EntityType.NPC, "Aria") != base
    assert allocate_candidate_entity_id("S001", EntityType.LOCATION, "Aria") != base
    assert allocate_candidate_entity_id("S001", EntityType.NPC, "Borin") != base
