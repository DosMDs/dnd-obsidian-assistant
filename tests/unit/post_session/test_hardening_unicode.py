"""S11-08 Unicode normalization hardening for candidate identity.

Proves the accepted ``strip -> NFC -> casefold`` policy is consistently applied
to deterministic candidate ``EntityId`` allocation and to the shared exact-text
helper, without expanding matching beyond that contract.
"""

from __future__ import annotations

import unicodedata

from dnd_assistant.application.entity_id_allocator import (
    allocate_candidate_entity_id,
    candidate_identity_material,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.retrieval.exact_matching import normalize_exact_text

_SESSION = "S001"


def test_nfc_and_nfd_names_allocate_same_entity_id() -> None:
    nfc = unicodedata.normalize("NFC", "Café")
    nfd = unicodedata.normalize("NFD", "Café")
    assert nfc != nfd  # distinct code-point sequences

    assert allocate_candidate_entity_id(_SESSION, EntityType.LOCATION, nfc) == (
        allocate_candidate_entity_id(_SESSION, EntityType.LOCATION, nfd)
    )


def test_casefold_equivalent_names_allocate_same_entity_id() -> None:
    assert allocate_candidate_entity_id(_SESSION, EntityType.NPC, "ARIA") == (
        allocate_candidate_entity_id(_SESSION, EntityType.NPC, "aria")
    )
    assert allocate_candidate_entity_id(_SESSION, EntityType.NPC, "Straße") == (
        allocate_candidate_entity_id(_SESSION, EntityType.NPC, "STRASSE")
    )


def test_surrounding_whitespace_does_not_change_identity() -> None:
    assert allocate_candidate_entity_id(_SESSION, EntityType.ITEM, "  Excalibur  ") == (
        allocate_candidate_entity_id(_SESSION, EntityType.ITEM, "Excalibur")
    )


def test_non_ascii_name_is_deterministic_and_distinct() -> None:
    first = allocate_candidate_entity_id(_SESSION, EntityType.NPC, "Ægir")
    second = allocate_candidate_entity_id(_SESSION, EntityType.NPC, "Ægir")
    other = allocate_candidate_entity_id(_SESSION, EntityType.NPC, "Aegir")

    assert first == second
    assert first != other
    assert first.startswith("ent_") and len(first) == len("ent_") + 32


def test_entity_type_is_part_of_candidate_identity() -> None:
    npc = allocate_candidate_entity_id(_SESSION, EntityType.NPC, "Grayford")
    location = allocate_candidate_entity_id(_SESSION, EntityType.LOCATION, "Grayford")
    assert npc != location


def test_normalize_exact_text_contract_is_strip_nfc_casefold() -> None:
    assert normalize_exact_text("  Café  ") == "café"
    assert normalize_exact_text("STRASSE") == normalize_exact_text("Straße")
    # No accent stripping / punctuation normalization beyond the accepted policy.
    assert normalize_exact_text("café") != normalize_exact_text("cafe")


def test_candidate_identity_material_uses_normalized_name() -> None:
    material = candidate_identity_material(_SESSION, EntityType.NPC, "  ARIA ")
    assert material["name"] == "aria"
    assert material["entity_type"] == "npc"
    assert material["session_ref"] == _SESSION
