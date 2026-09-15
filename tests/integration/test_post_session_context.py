"""S11-02 end-to-end context assembly integration tests.

Exercises a real temporary Vault with the real metadata/event/Vault
repositories: completed session -> S11-01 eligibility -> deterministic context
assembly -> PreparedInputIdentity + fingerprint, then proves fingerprint
sensitivity to selected (but not unrelated) current entity mutation and that
assembly is byte-for-byte read-only.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from dnd_assistant.application.post_session_context import build_post_session_input
from dnd_assistant.application.post_session_eligibility import (
    evaluate_processing_eligibility,
)
from dnd_assistant.application.post_session_identity import (
    POST_SESSION_PROCESSOR_VERSION,
)
from dnd_assistant.domain.entity import Entity
from dnd_assistant.domain.post_session import PreparedEntityProjection
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.types import VaultDocument
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.unit.post_session.helpers import (
    BASE_END,
    BASE_START,
    make_audit_context,
    make_session,
    make_vault,
)

_ENTITY_DIRS = ("Characters/NPCs", "Locations", "Quests", "Items")


def _setup_vault(root: Path) -> None:
    for relative in _ENTITY_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def _entity(
    entity_id: str,
    entity_type: EntityType = EntityType.NPC,
    *,
    name: str = "Aria",
    visibility: Visibility = Visibility.PLAYER,
    knowledge_status: KnowledgeStatus = KnowledgeStatus.CONFIRMED,
    revision: int = 1,
) -> Entity:
    return Entity(
        id=entity_id,
        type=entity_type,
        name=name,
        status="alive",
        visibility=visibility,
        knowledge_status=knowledge_status,
        created_at=BASE_START,
        updated_at=BASE_START,
        revision=revision,
    )


def _audit(op_id: str, when: datetime = BASE_END) -> AuditContext:
    return AuditContext(operation_id=op_id, real_time=when, source="test")


def _create_entity(
    vault: ObsidianVaultRepository,
    entity: Entity,
    *,
    body: str,
    op_id: str,
) -> None:
    vault.create_entity(VaultDocument(entity=entity, body=body), audit=_audit(op_id))


def _build_vault(tmp_path: Path) -> tuple[Path, AuditService, tuple[str, ...]]:
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
        body="A DM-only fact.",
        op_id="create-hidden",
    )
    _create_entity(
        vault,
        _entity("loc-grayford", EntityType.LOCATION, name="Grayford"),
        body="A river town.",
        op_id="create-grayford",
    )
    # Unrelated entity, never referenced by the session.
    _create_entity(
        vault,
        _entity("npc-other", name="Unrelated"),
        body="Not part of the session.",
        op_id="create-other",
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
        touched_entity_ids=["npc-aria", "npc-hidden"],
        audit=make_audit_context(operation_id="s-end", real_time=BASE_END),
    )
    return root, audit, ("npc-aria", "npc-hidden")


def _services(root: Path, audit: AuditService):
    return (
        ObsidianSessionMetadataRepository(root, audit),
        ObsidianSessionEventRepository(root, audit),
        ObsidianVaultRepository(root, audit),
        ObsidianPostSessionProcessingStore(root),
    )


def _eligibility(root: Path, audit: AuditService):
    metadata_repo, event_repo, _vault, store = _services(root, audit)
    return evaluate_processing_eligibility(metadata_repo, event_repo, store, "S001")


def _build(root: Path, audit: AuditService):
    metadata_repo, event_repo, vault, _store = _services(root, audit)
    eligibility = _eligibility(root, audit)
    assert eligibility.eligible is True
    return build_post_session_input(
        metadata_repo=metadata_repo,
        event_repo=event_repo,
        vault_repo=vault,
        session_id="S001",
        eligibility=eligibility,
    )


def _snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root).as_posix())] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


# ── Tests ─────────────────────────────────────────────────────────────────


def test_completed_session_assembles_deterministic_input(tmp_path: Path) -> None:
    root, audit, touched = _build_vault(tmp_path)

    result = _build(root, audit)

    assert result.identity.schema_version == 2
    assert result.identity.processor_version == POST_SESSION_PROCESSOR_VERSION
    assert result.identity.session.id == "S001"
    assert result.identity.session.touched_entities == touched
    assert result.identity.calendar.world_tick_start == 100
    assert result.identity.calendar.world_tick_end == 200
    assert result.identity.context.text  # derived rendering is non-empty

    # Fresh repository instances on the same Vault yield the same fingerprint.
    fresh = _build(root, audit)
    assert fresh.identity == result.identity
    assert fresh.fingerprint == result.fingerprint


def test_selected_entity_projection_preserves_canonical_metadata(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    result = _build(root, audit)

    by_id = {entity.id: entity for entity in result.identity.entities}
    hidden = by_id["npc-hidden"]
    assert isinstance(hidden, PreparedEntityProjection)
    assert hidden.visibility is Visibility.DM
    assert hidden.knowledge_status is KnowledgeStatus.RUMOR
    assert hidden.type is EntityType.NPC
    assert by_id["npc-aria"].body_projection == "Aria is a ranger."
    assert "npc-other" not in by_id


def test_selected_entity_mutation_changes_fingerprint(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    before = _build(root, audit)
    events_before = (root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl").read_bytes()

    vault = ObsidianVaultRepository(root, audit)
    vault.append_entity_fact(
        "npc-aria",
        expected_revision=1,
        fact="Aria gained a new scar.",
        audit=_audit("mutate-aria"),
    )

    after = _build(root, audit)
    assert after.fingerprint != before.fingerprint
    # Raw session evidence is immutable and unchanged.
    assert (
        root / "_system" / "raw" / "sessions" / "S001" / "events.jsonl"
    ).read_bytes() == events_before


def test_unrelated_entity_mutation_does_not_change_fingerprint(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    before = _build(root, audit)

    vault = ObsidianVaultRepository(root, audit)
    vault.append_entity_fact(
        "npc-other",
        expected_revision=1,
        fact="Unrelated change.",
        audit=_audit("mutate-other"),
    )

    after = _build(root, audit)
    assert after.fingerprint == before.fingerprint


def test_context_assembly_leaves_vault_bytes_unchanged(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)

    before = _snapshot(root)
    eligibility = _eligibility(root, audit)
    _build(root, audit)
    after = _snapshot(root)

    assert after == before
    assert eligibility.session_revision == 2


def test_assembly_writes_no_audit_or_ledger(tmp_path: Path) -> None:
    root, audit, _touched = _build_vault(tmp_path)
    audit_before = audit.read_all()
    ledger = root / "_system" / "raw" / "sessions" / "S001" / "processing" / "ledger.jsonl"

    _build(root, audit)

    assert audit.read_all() == audit_before
    assert not ledger.exists()
