"""S11-04 end-to-end Summary/Recap integration tests against a real Vault.

Exercises the accepted completed-session Vault fixture, S11-01 eligibility,
S11-02 context assembly, S11-03 accepted extraction (fake extraction model) and
S11-04 Summary/Recap generation (capturing fake renderer).  Proves that success
and failure both leave the Vault byte-identical with no audit, ledger or
ChangeSet artifacts, and that the actual Recap renderer request never carries
hidden material.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RenderingFailureReason,
    generate_recap,
    generate_summary,
    serialize_recap_request,
    serialize_summary_request,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome
from dnd_assistant.domain.post_session_extraction import (
    ExtractionKnowledgeHint,
    ExtractionVisibilityHint,
)
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.integration.test_post_session_context import (
    _build,
    _create_entity,
    _entity,
    _setup_vault,
    _snapshot,
)
from tests.unit.post_session.extraction_helpers import (
    make_candidate,
    make_claim,
    make_extraction,
    make_mention,
)
from tests.unit.post_session.helpers import (
    BASE_END,
    BASE_START,
    make_audit_context,
    make_session,
    make_vault,
)
from tests.unit.post_session.rendering_helpers import (
    ALL_SECRET_CANARIES,
    DM_SECRET_CANARY_CANDIDATE,
    DM_SECRET_CANARY_CLAIM_TEXT,
    DM_SECRET_CANARY_ENTITY_BODY,
    SYSTEM_SECRET_CANARY_ENTITY_BODY,
    UNRESOLVED_SECRET_CANARY_MENTION,
    FakePostSessionRenderingModel,
    make_accepted,
    make_render_output,
)

_TOUCHED = ("npc-aria", "npc-hidden", "npc-system", "loc-grayford")


def _build_vault(tmp_path: Path) -> tuple[Path, AuditService]:
    root = make_vault(tmp_path)
    _setup_vault(root)
    audit = AuditService(root / "_system" / "audit" / "audit.jsonl")
    vault = ObsidianVaultRepository(root, audit)

    _create_entity(
        vault,
        _entity("npc-aria", name="Aria", visibility=Visibility.PLAYER),
        body="Aria is a ranger.",
        op_id="create-aria",
    )
    _create_entity(
        vault,
        _entity(
            "npc-hidden",
            name="The Hidden One",
            visibility=Visibility.DM,
            knowledge_status=KnowledgeStatus.RUMOR,
        ),
        body=DM_SECRET_CANARY_ENTITY_BODY,
        op_id="create-hidden",
    )
    _create_entity(
        vault,
        _entity("npc-system", name="System Entity", visibility=Visibility.SYSTEM),
        body=SYSTEM_SECRET_CANARY_ENTITY_BODY,
        op_id="create-system",
    )
    _create_entity(
        vault,
        _entity("loc-grayford", EntityType.LOCATION, name="Grayford"),
        body="A river town.",
        op_id="create-grayford",
    )

    metadata_repo = ObsidianSessionMetadataRepository(root, audit)
    event_repo = ObsidianSessionEventRepository(root, audit)
    metadata_repo.create_session(
        make_session(status="active"),
        audit=make_audit_context(operation_id="s-start", real_time=BASE_START),
    )
    event_repo.append_event(
        "S001",
        event_type="note",
        real_time=BASE_START,
        world_tick=150,
        extra_fields={"text": "The party met Aria."},
        audit=make_audit_context(operation_id="evt-1", real_time=BASE_START),
    )
    metadata_repo.close_session(
        "S001",
        expected_revision=1,
        world_tick_end=200,
        touched_entity_ids=list(_TOUCHED),
        audit=make_audit_context(operation_id="s-end", real_time=BASE_END),
    )
    return root, audit


def _extraction():
    return make_extraction(
        claims=(
            make_claim(
                claim_id="c_player",
                text="Aria arrived at the tavern.",
                entity_mentions=(make_mention(mention_id="m1", candidate_entity_id="npc-aria"),),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
                knowledge_hint=ExtractionKnowledgeHint.CONFIRMED,
            ),
            make_claim(
                claim_id="c_dm",
                text=DM_SECRET_CANARY_CLAIM_TEXT,
                entity_mentions=(make_mention(mention_id="m2", candidate_entity_id="npc-hidden"),),
                visibility_hint=ExtractionVisibilityHint.DM,
            ),
            make_claim(
                claim_id="c_system",
                text="System-level fact.",
                entity_mentions=(make_mention(mention_id="m3", candidate_entity_id="npc-system"),),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
            ),
            make_claim(
                claim_id="c_unresolved",
                entity_mentions=(
                    make_mention(
                        mention_id="m4",
                        candidate_entity_id=None,
                        text=UNRESOLVED_SECRET_CANARY_MENTION,
                    ),
                ),
                visibility_hint=ExtractionVisibilityHint.PLAYER,
            ),
            make_claim(
                claim_id="c_no_entity",
                text="Something happened.",
                visibility_hint=ExtractionVisibilityHint.PLAYER,
            ),
        ),
        entity_candidates=(
            make_candidate(candidate_id="cand1", display_name=DM_SECRET_CANARY_CANDIDATE),
        ),
    )


def _prepared_and_accepted(root: Path, audit: AuditService):
    prepared = _build(root, audit)
    accepted = make_accepted(prepared, _extraction())
    return prepared, accepted


# ── Tests ─────────────────────────────────────────────────────────────────


def test_rendering_success_leaves_vault_byte_identical(tmp_path: Path) -> None:
    root, audit = _build_vault(tmp_path)
    prepared, accepted = _prepared_and_accepted(root, audit)

    before = _snapshot(root)
    audit_before = audit.read_all()

    renderer = FakePostSessionRenderingModel(echo=True)
    summary = generate_summary(renderer, prepared, accepted)
    recap = generate_recap(renderer, prepared, accepted)

    assert summary.outcome is RenderOutcome.RENDERED
    assert recap.outcome is RenderOutcome.RENDERED
    assert len(renderer.requests) == 2

    # Summary may contain authorized DM material.
    summary_request = renderer.requests[0]
    summary_text = serialize_summary_request(summary_request)  # type: ignore[arg-type]
    assert DM_SECRET_CANARY_CLAIM_TEXT in summary_text
    assert SYSTEM_SECRET_CANARY_ENTITY_BODY not in summary_text
    assert "npc-system" not in summary_text

    # Recap request and echo-derived result carry no hidden canary.
    recap_request = renderer.requests[1]
    recap_text = serialize_recap_request(recap_request)  # type: ignore[arg-type]
    for canary in ALL_SECRET_CANARIES:
        assert canary not in recap_text
        assert canary not in (recap.content or "")
    assert recap.content is not None and "Aria" in recap.content

    assert _snapshot(root) == before
    assert audit.read_all() == audit_before
    assert not (
        root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.jsonl"
    ).exists()
    assert not (root / "_system" / "changesets").exists()


def test_rendering_failure_leaves_vault_byte_identical(tmp_path: Path) -> None:
    root, audit = _build_vault(tmp_path)
    prepared, accepted = _prepared_and_accepted(root, audit)

    before = _snapshot(root)
    audit_before = audit.read_all()

    renderer = FakePostSessionRenderingModel(
        error=PostSessionRenderingError(RenderingFailureReason.MODEL_UNAVAILABLE, "model down")
    )
    with pytest.raises(PostSessionRenderingError):
        generate_recap(renderer, prepared, accepted)

    assert _snapshot(root) == before
    assert audit.read_all() == audit_before
    assert not (root / "_system" / "changesets").exists()


def test_empty_recap_makes_no_model_call_and_writes_nothing(tmp_path: Path) -> None:
    root, audit = _build_vault(tmp_path)
    prepared, accepted = _prepared_and_accepted(root, audit)

    # Restrict the extraction so no claim is Recap-eligible.
    dm_only = make_accepted(
        prepared,
        make_extraction(
            claims=(
                make_claim(
                    claim_id="c_dm",
                    text=DM_SECRET_CANARY_CLAIM_TEXT,
                    entity_mentions=(
                        make_mention(mention_id="m2", candidate_entity_id="npc-hidden"),
                    ),
                    visibility_hint=ExtractionVisibilityHint.PLAYER,
                ),
            )
        ),
    )

    before = _snapshot(root)
    audit_before = audit.read_all()
    renderer = FakePostSessionRenderingModel(make_render_output())

    recap = generate_recap(renderer, prepared, dm_only)

    assert recap.outcome is RenderOutcome.EMPTY
    assert recap.content is None
    assert renderer.requests == []
    assert _snapshot(root) == before
    assert audit.read_all() == audit_before


def test_provenance_mismatch_fails_before_render_and_writes_nothing(tmp_path: Path) -> None:
    root, audit = _build_vault(tmp_path)
    prepared, accepted = _prepared_and_accepted(root, audit)

    before = _snapshot(root)
    renderer = FakePostSessionRenderingModel(make_render_output())
    tampered = replace(
        accepted,
        provenance=replace(accepted.provenance, processor_version="9"),
    )

    with pytest.raises(PostSessionRenderingError) as exc_info:
        generate_summary(renderer, prepared, tampered)

    assert exc_info.value.reason is RenderingFailureReason.PROVENANCE_MISMATCH
    assert renderer.requests == []
    assert _snapshot(root) == before
