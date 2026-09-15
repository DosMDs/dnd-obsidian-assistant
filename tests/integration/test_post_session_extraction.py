"""S11-03 end-to-end extraction integration tests against a real Vault.

Uses the accepted completed-session Vault fixture, S11-01 eligibility, S11-02
context assembly and the deterministic fake extraction model.  Proves that
success and failure both leave the Vault byte-identical with no audit, ledger
or ChangeSet artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    ModelExecutionIdentity,
    PostSessionExtractionError,
    run_post_session_extraction,
)
from dnd_assistant.domain.types import EntityType
from tests.integration.test_post_session_context import (
    _build,
    _build_vault,
    _snapshot,
)
from tests.unit.post_session.extraction_helpers import (
    FakePostSessionExtractionModel,
    make_claim,
    make_extraction,
    make_mention,
)


def test_extraction_binds_real_prepared_input_and_writes_nothing(tmp_path: Path) -> None:
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
                evidence_event_ids=(event_ids[0],),
                entity_mentions=(
                    make_mention(
                        candidate_entity_id=entity_ids[0],
                        entity_type=EntityType.NPC,
                    ),
                ),
            ),
        )
    )
    fake = FakePostSessionExtractionModel(extraction)

    accepted = run_post_session_extraction(
        fake,
        prepared,
        model_identity=ModelExecutionIdentity(profile="heavy", model="qwen3"),
    )

    assert accepted.provenance.input_fingerprint == prepared.fingerprint
    assert accepted.provenance.model_profile == "heavy"
    assert accepted.validated.resolved_mentions[0].entity_id == entity_ids[0]

    assert _snapshot(root) == before
    assert audit.read_all() == audit_before
    ledger = root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.jsonl"
    assert not ledger.exists()
    assert not (root / "_system" / "changesets").exists()


def test_extraction_failure_writes_nothing(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    prepared = _build(root, audit)

    before = _snapshot(root)
    audit_before = audit.read_all()

    fake = FakePostSessionExtractionModel(
        error=PostSessionExtractionError(ExtractionFailureReason.MODEL_TIMEOUT, "model timed out")
    )
    with pytest.raises(PostSessionExtractionError):
        run_post_session_extraction(fake, prepared)

    assert _snapshot(root) == before
    assert audit.read_all() == audit_before
    assert not (root / "_system" / "changesets").exists()
