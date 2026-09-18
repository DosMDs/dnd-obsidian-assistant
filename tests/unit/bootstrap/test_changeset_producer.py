"""S13-03 deterministic bootstrap ChangeSet producer tests."""

from __future__ import annotations

from dnd_assistant.application.bootstrap_canonical import build_canonical_snapshot
from dnd_assistant.application.bootstrap_changeset import (
    BootstrapMappingOutcome,
    BootstrapUnresolvedReason,
    produce_bootstrap_changeset,
)
from dnd_assistant.application.bootstrap_entity_id import allocate_bootstrap_entity_id
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    CreateEntityOperation,
    UpdateEntityOperation,
)
from dnd_assistant.domain.types import (
    EntityType,
    Provenance,
    Sha256Fingerprint,
)
from dnd_assistant.storage.bootstrap_canonical import parse_canonical_candidate
from tests.unit.bootstrap.helpers import canonical_text, make_candidate, make_claim, make_reference

_REF = "src_" + "a" * 32
_FP = Sha256Fingerprint(digest="b" * 64)


def _snapshot(*candidates):
    return build_canonical_snapshot(candidates)


def _cand(path: str, entity_id: str, entity_type: EntityType, name: str, **kwargs):
    return parse_canonical_candidate(path, canonical_text(entity_id, entity_type, name, **kwargs))


def _produce(snapshot, extraction):
    return produce_bootstrap_changeset(
        snapshot,
        extraction,
        campaign_id="camp-1",
        input_fingerprint=_FP,
        model_profile="heavy",
        prompt_version="bootstrap-extraction-v1",
    )


def test_single_candidate_creates_proposal_with_bootstrap_provenance() -> None:
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Варос", EntityType.NPC, [_REF]),),
    )
    result = _produce(_snapshot(), extraction)
    assert result.outcome is BootstrapMappingOutcome.PROPOSAL
    assert result.changeset is not None
    assert result.changeset.provenance.provenance is Provenance.BOOTSTRAP
    assert result.changeset.provenance.model_profile == "heavy"
    assert result.changeset.session_ref is None
    operation = result.changeset.operations[0]
    assert isinstance(operation, CreateEntityOperation)
    assert operation.entity_id == allocate_bootstrap_entity_id("camp-1", EntityType.NPC, "Варос")
    assert operation.created_session is None
    assert operation.last_seen_session is None
    assert operation.tags == ()


def test_proposal_id_is_deterministic() -> None:
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Варос", EntityType.NPC, [_REF]),),
    )
    first = _produce(_snapshot(), extraction)
    second = _produce(_snapshot(), extraction)
    assert first.changeset is not None and second.changeset is not None
    assert first.changeset.changeset_id == second.changeset.changeset_id
    assert first.changeset_fingerprint == second.changeset_fingerprint


def test_append_fact_targets_bindable_entity_with_its_revision() -> None:
    snapshot = _snapshot(
        _cand("Characters/NPCs/v.md", "npc-1", EntityType.NPC, "Варос", revision=3)
    )
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(
            make_claim(
                "k1",
                "Варос скрывает культ",
                [_REF],
                references=[make_reference("r1", "Варос", EntityType.NPC, [_REF])],
            ),
        ),
    )
    result = _produce(snapshot, extraction)
    assert result.outcome is BootstrapMappingOutcome.PROPOSAL
    assert result.changeset is not None
    operation = result.changeset.operations[0]
    assert isinstance(operation, AppendFactOperation)
    assert operation.entity_id == "npc-1"
    assert operation.expected_revision == 3
    assert operation.fact == "Варос скрывает культ"


def test_update_entity_is_never_emitted() -> None:
    snapshot = _snapshot(_cand("Characters/NPCs/v.md", "npc-1", EntityType.NPC, "Варос"))
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(
            make_claim(
                "k1",
                "факт",
                [_REF],
                references=[make_reference("r1", "Варос", EntityType.NPC, [_REF])],
            ),
        ),
    )
    result = _produce(snapshot, extraction)
    assert result.changeset is not None
    assert not any(isinstance(op, UpdateEntityOperation) for op in result.changeset.operations)


def test_cross_type_same_new_name_is_ambiguous_unresolved() -> None:
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(
            make_candidate("c1", "Серебряный ключ", EntityType.ITEM, [_REF]),
            make_candidate("c2", "Серебряный ключ", EntityType.QUEST, [_REF]),
        ),
    )
    result = _produce(_snapshot(), extraction)
    assert result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert all(
        item.reason is BootstrapUnresolvedReason.CANDIDATE_NAME_CONFLICT
        for item in result.unresolved
        if item.candidate_id is not None
    )
    assert {item.candidate_id for item in result.unresolved} == {"c1", "c2"}


def test_duplicate_existing_name_blocks_creation() -> None:
    snapshot = _snapshot(_cand("Characters/NPCs/v.md", "npc-1", EntityType.NPC, "Варос"))
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Варос", EntityType.NPC, [_REF]),),
    )
    result = _produce(snapshot, extraction)
    assert result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert result.unresolved[0].reason is BootstrapUnresolvedReason.DUPLICATE_EXISTING_ENTITY


def test_conflicting_canonical_identity_blocks_duplicate_creation() -> None:
    snapshot = _snapshot(
        _cand("Characters/NPCs/a.md", "npc-1", EntityType.NPC, "Варос"),
        _cand("Characters/NPCs/b.md", "npc-1", EntityType.NPC, "Варос"),
    )
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Варос", EntityType.NPC, [_REF]),),
    )
    result = _produce(snapshot, extraction)
    assert result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert result.unresolved[0].reason is BootstrapUnresolvedReason.DUPLICATE_EXISTING_ENTITY


def test_conflicting_source_claims_are_unresolved() -> None:
    snapshot = _snapshot(_cand("Characters/NPCs/v.md", "npc-1", EntityType.NPC, "Варос"))
    reference = make_reference("r1", "Варос", EntityType.NPC, [_REF])
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(
            make_claim("k1", "Варос жив", [_REF], references=[reference], conflict_group="g1"),
            make_claim("k2", "Варос мёртв", [_REF], references=[reference], conflict_group="g1"),
        ),
    )
    # Reference ids must be unique; give the second claim its own reference.
    extraction = extraction.model_copy(
        update={
            "claims": (
                extraction.claims[0],
                extraction.claims[1].model_copy(
                    update={"references": (make_reference("r2", "Варос", EntityType.NPC, [_REF]),)}
                ),
            )
        }
    )
    result = _produce(snapshot, extraction)
    assert result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert BootstrapUnresolvedReason.CONFLICTING_SOURCE_CLAIMS in {
        item.reason for item in result.unresolved
    }


def test_system_entity_is_not_an_append_target() -> None:
    snapshot = _snapshot(
        _cand("Characters/NPCs/sys.md", "npc-sys", EntityType.NPC, "Правила", visibility="system")
    )
    extraction = BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        claims=(
            make_claim(
                "k1",
                "факт",
                [_REF],
                references=[make_reference("r1", "Правила", EntityType.NPC, [_REF])],
            ),
        ),
    )
    result = _produce(snapshot, extraction)
    assert result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert result.unresolved[0].reason is BootstrapUnresolvedReason.SYSTEM_ENTITY_EXCLUDED


def test_empty_extraction_yields_no_changes() -> None:
    extraction = BootstrapExtraction(schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION)
    result = _produce(_snapshot(), extraction)
    assert result.outcome is BootstrapMappingOutcome.NO_CHANGES
    assert result.changeset is None
    assert result.changeset_fingerprint is None
