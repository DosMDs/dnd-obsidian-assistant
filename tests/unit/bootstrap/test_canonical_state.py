"""S13-03 application canonical projection and read-only preflight tests."""

from __future__ import annotations

from dnd_assistant.application.bootstrap_canonical import build_canonical_snapshot
from dnd_assistant.application.changeset_validation import (
    ValidationIssueCode,
    validate_changeset,
)
from dnd_assistant.domain.changeset import ChangeSet, CreateEntityOperation, ProposalProvenance
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.storage.bootstrap_canonical import parse_canonical_candidate
from dnd_assistant.storage.bootstrap_types import CanonicalCandidateOutcome
from tests.unit.bootstrap.helpers import canonical_text


def _candidate(path: str, entity_id: str, name: str, **kwargs):
    return parse_canonical_candidate(
        path, canonical_text(entity_id, kwargs.pop("type", EntityType.NPC), name, **kwargs)
    )


def test_bindable_and_malformed_sources_are_separated() -> None:
    snapshot = build_canonical_snapshot(
        (
            _candidate("Characters/NPCs/varos.md", "npc-1", "Варос"),
            parse_canonical_candidate("Characters/NPCs/old.md", "plain historical note"),
        )
    )
    assert [view.entity_id for view in snapshot.bindable] == ["npc-1"]
    assert snapshot.issues and snapshot.issues[0].outcome is CanonicalCandidateOutcome.MALFORMED


def test_duplicate_id_is_conflicting_not_bindable() -> None:
    snapshot = build_canonical_snapshot(
        (
            _candidate("Characters/NPCs/a.md", "npc-1", "Варос"),
            _candidate("Characters/NPCs/b.md", "npc-1", "Варос Дубликат"),
        )
    )
    assert snapshot.bindable == ()
    assert {conflict.entity_id for conflict in snapshot.conflicts} == {"npc-1"}


def test_directory_type_mismatch_is_conflicting_not_bindable() -> None:
    mismatch = parse_canonical_candidate(
        "Characters/NPCs/misplaced.md",
        canonical_text("loc-1", EntityType.LOCATION, "Грейфорд"),
    )
    snapshot = build_canonical_snapshot((mismatch,))
    assert snapshot.bindable == ()
    assert snapshot.conflicts[0].entity_id == "loc-1"


def test_snapshot_list_entities_is_read_only_and_has_no_mutation_surface() -> None:
    snapshot = build_canonical_snapshot((_candidate("Characters/NPCs/v.md", "npc-1", "Варос"),))
    assert [doc.entity.id for doc in snapshot.list_entities()] == ["npc-1"]
    assert not hasattr(snapshot, "create_entity")
    assert not hasattr(snapshot, "patch_entity")


def test_snapshot_satisfies_validate_changeset_read_surface() -> None:
    snapshot = build_canonical_snapshot((_candidate("Characters/NPCs/v.md", "npc-1", "Варос"),))
    changeset = ChangeSet(
        changeset_id="cs_test",
        provenance=ProposalProvenance(provenance=Provenance.BOOTSTRAP),
        operations=(
            CreateEntityOperation(
                entity_id="npc-1",
                type=EntityType.NPC,
                name="Варос",
                status="unknown",
                visibility=Visibility.DM,
                knowledge_status=KnowledgeStatus.INFERRED,
            ),
        ),
    )
    result = validate_changeset(changeset, snapshot)
    assert not result.valid
    assert result.issues[0].code is ValidationIssueCode.CREATE_TARGET_EXISTS
