"""S13-03 deterministic bootstrap EntityId allocator tests."""

from __future__ import annotations

from dnd_assistant.application.bootstrap_entity_id import (
    BOOTSTRAP_ENTITY_ID_ALLOCATOR_VERSION,
    allocate_bootstrap_entity_id,
    bootstrap_identity_material,
)
from dnd_assistant.domain.types import EntityType


def test_allocation_is_deterministic_and_retry_stable() -> None:
    first = allocate_bootstrap_entity_id("camp-1", EntityType.NPC, "Варос")
    second = allocate_bootstrap_entity_id("camp-1", EntityType.NPC, "Варос")
    assert first == second
    assert first.startswith("ent_")
    assert len(first) == len("ent_") + 32


def test_allocation_is_campaign_scoped() -> None:
    assert allocate_bootstrap_entity_id(
        "camp-1", EntityType.NPC, "Варос"
    ) != allocate_bootstrap_entity_id("camp-2", EntityType.NPC, "Варос")


def test_cross_type_same_name_is_hash_distinct() -> None:
    assert allocate_bootstrap_entity_id(
        "camp-1", EntityType.NPC, "Серебряный ключ"
    ) != allocate_bootstrap_entity_id("camp-1", EntityType.ITEM, "Серебряный ключ")


def test_unicode_normalization_is_applied() -> None:
    composed = allocate_bootstrap_entity_id("camp-1", EntityType.LOCATION, "Грейфорд")
    decomposed = allocate_bootstrap_entity_id("camp-1", EntityType.LOCATION, "Грейфорд")
    assert composed == decomposed
    assert (
        bootstrap_identity_material("camp-1", EntityType.LOCATION, "  Грейфорд  ")["name"]
        == "грейфорд"
    )


def test_allocator_version_is_explicit() -> None:
    assert BOOTSTRAP_ENTITY_ID_ALLOCATOR_VERSION == "bootstrap-entity-id-v1"
