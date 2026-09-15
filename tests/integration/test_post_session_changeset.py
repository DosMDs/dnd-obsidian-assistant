"""S11-05 end-to-end ChangeSet producer integration tests against a real Vault.

Builds the chain completed session -> S11-01 eligibility -> S11-02 prepared
input -> S11-03 accepted extraction (deterministic fake model) -> S11-05
producer, and proves the proposal binds real canonical state while leaving the
Vault byte-identical with no audit, ledger, ChangeSet or approval artifact.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.changeset_review import (
    canonical_changeset_bytes,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import (
    deserialize_proposal,
    serialize_proposal,
)
from dnd_assistant.application.changeset_validation import validate_changeset
from dnd_assistant.application.post_session_changeset import (
    PostSessionChangeOutcome,
    produce_post_session_changeset,
)
from dnd_assistant.application.post_session_extraction import (
    run_post_session_extraction,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    CreateEntityOperation,
)
from dnd_assistant.domain.types import EntityType, Provenance
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from tests.integration.test_post_session_context import (
    _build,
    _build_vault,
    _services,
    _snapshot,
)
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.helpers import BASE_END

_ATTEMPT = "att_" + "c" * 32


def test_producer_builds_real_proposal_and_writes_nothing(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    prepared = _build(root, audit)
    event_ids = tuple(event.event_id for event in prepared.identity.raw_events)
    entity_ids = tuple(entity.id for entity in prepared.identity.entities)
    assert event_ids and entity_ids

    before = _snapshot(root)
    audit_before = audit.read_all()

    extraction = make_extraction(
        claims=(
            make_claim(
                text="Aria guided the party safely.",
                evidence_event_ids=(event_ids[0],),
                entity_mentions=(
                    make_mention(
                        candidate_entity_id="npc-aria",
                        entity_type=EntityType.NPC,
                        evidence_event_ids=(event_ids[0],),
                    ),
                ),
            ),
        ),
        entity_candidates=(
            make_candidate(
                candidate_id="cand-1",
                display_name="The Rusty Anchor",
                entity_type=EntityType.LOCATION,
                evidence_event_ids=(event_ids[0],),
            ),
        ),
    )
    fake = FakePostSessionExtractionModel(extraction)
    accepted = run_post_session_extraction(fake, prepared)

    _metadata, _events, vault, _store = _services(root, audit)
    result = produce_post_session_changeset(
        prepared, accepted, attempt_id=_ATTEMPT, repository=vault
    )

    assert result.outcome is PostSessionChangeOutcome.PROPOSAL
    assert result.changeset is not None
    assert result.changeset.session_ref == "S001"
    assert result.changeset.changeset_id == f"cs_S001_{_ATTEMPT}"
    assert result.changeset.provenance.provenance is Provenance.MODEL_INFERENCE

    kinds = [operation.kind for operation in result.changeset.operations]
    assert kinds == ["create_entity", "append_fact"]
    create = result.changeset.operations[0]
    append = result.changeset.operations[1]
    assert isinstance(create, CreateEntityOperation)
    assert isinstance(append, AppendFactOperation)
    assert append.entity_id == "npc-aria"
    assert append.expected_revision == 1  # matches prepared canonical revision

    assert validate_changeset(result.changeset, vault).valid is True

    # Existing Stage-10 canonical serializer round-trips.
    reloaded = deserialize_proposal(serialize_proposal(result.changeset))
    assert canonical_changeset_bytes(reloaded) == canonical_changeset_bytes(result.changeset)
    assert compute_changeset_fingerprint(reloaded) == result.changeset_fingerprint

    assert _snapshot(root) == before
    assert audit.read_all() == audit_before
    assert not (root / "_system" / "changesets").exists()


def test_stale_target_revision_blocks_mutation(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    prepared = _build(root, audit)
    event_ids = tuple(event.event_id for event in prepared.identity.raw_events)

    extraction = make_extraction(
        claims=(
            make_claim(
                evidence_event_ids=(event_ids[0],),
                entity_mentions=(
                    make_mention(
                        candidate_entity_id="npc-aria",
                        entity_type=EntityType.NPC,
                        evidence_event_ids=(event_ids[0],),
                    ),
                ),
            ),
        ),
    )
    accepted = run_post_session_extraction(FakePostSessionExtractionModel(extraction), prepared)

    _metadata, _events, vault, _store = _services(root, audit)

    vault.patch_entity(
        "npc-aria",
        EntityPatch(status="dead"),
        expected_revision=1,
        audit=AuditContext(operation_id="external-edit", real_time=BASE_END, source="test"),
    )

    result = produce_post_session_changeset(
        prepared, accepted, attempt_id=_ATTEMPT, repository=vault
    )

    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert result.changeset is None


def test_ambiguous_mention_is_never_guessed(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    prepared = _build(root, audit)
    event_ids = tuple(event.event_id for event in prepared.identity.raw_events)

    extraction = make_extraction(
        claims=(
            make_claim(
                text="Someone unknown appeared.",
                evidence_event_ids=(event_ids[0],),
                entity_mentions=(
                    make_mention(
                        text="Totally Unknown Figure",
                        entity_type=EntityType.NPC,
                        evidence_event_ids=(event_ids[0],),
                    ),
                ),
            ),
        ),
    )
    accepted = run_post_session_extraction(FakePostSessionExtractionModel(extraction), prepared)

    _metadata, _events, vault, _store = _services(root, audit)
    result = produce_post_session_changeset(
        prepared, accepted, attempt_id=_ATTEMPT, repository=vault
    )

    assert result.outcome is PostSessionChangeOutcome.NO_CHANGES
    assert result.changeset is None
