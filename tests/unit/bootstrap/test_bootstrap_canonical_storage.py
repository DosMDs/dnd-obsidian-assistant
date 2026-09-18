"""S13-03 filesystem-free canonical recognition + parse tests."""

from __future__ import annotations

from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.bootstrap_canonical import parse_canonical_candidate
from dnd_assistant.storage.bootstrap_types import CanonicalCandidateOutcome
from tests.unit.bootstrap.helpers import canonical_text


def test_canonical_document_is_recognized() -> None:
    text = canonical_text("npc-1", EntityType.NPC, "Варос", aliases=["Магистр Варос"])
    result = parse_canonical_candidate("Characters/NPCs/varos.md", text)
    assert result.outcome is CanonicalCandidateOutcome.CANONICAL
    assert result.entity_id == "npc-1"
    assert result.entity_type is EntityType.NPC
    assert result.display_name == "Варос"
    assert result.revision == 1
    assert result.document is not None


def test_historical_malformed_note_is_not_canonical_and_has_no_identity() -> None:
    result = parse_canonical_candidate("Characters/NPCs/old.md", "# just a note\nno frontmatter")
    assert result.outcome is CanonicalCandidateOutcome.MALFORMED
    assert result.document is None
    assert result.entity_id is None
    assert result.display_name is None


def test_directory_type_mismatch_keeps_reliable_identity() -> None:
    text = canonical_text("loc-1", EntityType.LOCATION, "Грейфорд")
    result = parse_canonical_candidate("Characters/NPCs/misplaced.md", text)
    assert result.outcome is CanonicalCandidateOutcome.TYPE_DIRECTORY_MISMATCH
    assert result.entity_id == "loc-1"
    assert result.entity_type is EntityType.LOCATION


def test_path_outside_entity_directory_is_not_recognized() -> None:
    text = canonical_text("npc-1", EntityType.NPC, "Варос")
    result = parse_canonical_candidate("Campaign/Notes.md", text)
    assert result.outcome is CanonicalCandidateOutcome.NOT_IN_ENTITY_DIRECTORY
    assert result.entity_id is None


def test_casefold_directory_namespace_is_recognized() -> None:
    text = canonical_text("npc-1", EntityType.NPC, "Варос")
    result = parse_canonical_candidate("characters/npcs/varos.md", text)
    assert result.outcome is CanonicalCandidateOutcome.CANONICAL
