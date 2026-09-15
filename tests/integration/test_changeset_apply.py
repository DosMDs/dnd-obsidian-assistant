"""Integration tests for S10-04 ChangeSet apply against a real temporary Vault.

Wires :func:`apply_changeset` to a real ``ObsidianVaultRepository`` and proves
the apply contract end-to-end: approved create/update/append and same-batch
chains mutate only through the repository, revisions/timestamps follow the
repository rules, audit records carry deterministic per-operation IDs and
trusted/derived provenance, and preflight failures leave the Vault unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dnd_assistant.application.changeset_apply import (
    ChangeSetApplyContext,
    ChangeSetApplyOutcome,
    apply_changeset,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.domain.changeset import (
    AppendFactOperation,
    ChangeSet,
    CreateEntityOperation,
    EntityFieldUpdate,
    ProposalProvenance,
    UpdateEntityOperation,
)
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultRepository
from tests.integration.helpers import make_audit_context, make_document

APPLY_TIME = datetime(2026, 8, 30, 14, 0, 0, tzinfo=UTC)


def _snapshot_vault(vault_root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(vault_root)): path.read_bytes()
        for path in sorted(vault_root.rglob("*"))
        if path.is_file()
    }


def _create(entity_id: str) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=EntityType.NPC,
        name=f"Entity {entity_id}",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
    )


def _update(entity_id: str, expected_revision: int, **fields: object) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        update=EntityFieldUpdate(**fields),  # type: ignore[arg-type]
    )


def _append(
    entity_id: str, expected_revision: int, fact: str = "Slain at the gate"
) -> AppendFactOperation:
    return AppendFactOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        fact=fact,
    )


def _changeset(*operations: object) -> ChangeSet:
    return ChangeSet(
        changeset_id="cs_int",
        provenance=ProposalProvenance(
            provenance=Provenance.MODEL_INFERENCE,
            model_profile="llama3",
            prompt_version="prompt-v1",
        ),
        session_ref="S042",
        operations=operations,  # type: ignore[arg-type]
    )


def _approval(changeset: ChangeSet) -> ChangeSetApproval:
    return ChangeSetApproval(
        changeset_id=changeset.changeset_id,
        fingerprint=compute_changeset_fingerprint(changeset),
        decision=ReviewDecision.APPROVED,
        reviewer="dm",
    )


def _context() -> ChangeSetApplyContext:
    return ChangeSetApplyContext(source="changeset_apply", real_time=APPLY_TIME)


class TestApprovedApply:
    def test_approved_create(self, repo: VaultRepository) -> None:
        changeset = _changeset(_create("npc-created"))
        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        document = repo.get_entity("npc-created")
        assert document.entity.revision == 1
        assert document.entity.created_at == APPLY_TIME
        assert document.entity.updated_at == APPLY_TIME

    def test_approved_update(self, repo: VaultRepository) -> None:
        repo.create_entity(make_document("npc-updated"), audit=make_audit_context("setup-update"))
        changeset = _changeset(_update("npc-updated", 1, status="dead"))

        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        document = repo.get_entity("npc-updated")
        assert document.entity.revision == 2
        assert document.entity.updated_at == APPLY_TIME
        assert document.entity.status == "dead"

    def test_approved_append(self, repo: VaultRepository) -> None:
        repo.create_entity(make_document("npc-append"), audit=make_audit_context("setup-append"))
        changeset = _changeset(_append("npc-append", 1, fact="Found the key"))

        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        document = repo.get_entity("npc-append")
        assert document.entity.revision == 2
        assert document.body == "- Found the key\n"

    def test_create_append_update_chain(self, repo: VaultRepository) -> None:
        changeset = _changeset(
            _create("npc-chain"),
            _append("npc-chain", 1, fact="First fact"),
            _update("npc-chain", 2, status="dead"),
        )

        result = apply_changeset(changeset, _approval(changeset), repo, context=_context())

        assert result.outcome is ChangeSetApplyOutcome.APPLIED
        assert result.applied_operation_indices == (0, 1, 2)
        document = repo.get_entity("npc-chain")
        assert document.entity.revision == 3
        assert document.entity.status == "dead"
        assert document.body == "- First fact\n"


class TestAudit:
    def test_audit_records_carry_derived_provenance(
        self, repo: VaultRepository, audit_service: AuditService
    ) -> None:
        changeset = _changeset(_create("npc-audit"), _append("npc-audit", 1, fact="Noted"))
        apply_changeset(changeset, _approval(changeset), repo, context=_context())

        first = [r for r in audit_service.read_all() if r.operation_id == "cs_int:0"]
        second = [r for r in audit_service.read_all() if r.operation_id == "cs_int:1"]
        assert first and second
        for record in first + second:
            assert record.source == "changeset_apply"
            assert record.session == "S042"
            assert record.model_profile == "llama3"
            assert record.prompt_version == "prompt-v1"


class TestFailClosed:
    def test_stale_revision_after_review_leaves_vault_unchanged(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        repo.create_entity(make_document("npc-stale"), audit=make_audit_context("setup-stale"))
        changeset = _changeset(_update("npc-stale", 1, status="dead"))
        approval = _approval(changeset)

        # Another writer advances the Vault after review, before apply.
        repo.patch_entity(
            "npc-stale",
            EntityPatch(status="wounded"),
            expected_revision=1,
            audit=make_audit_context("other-writer"),
        )

        before = _snapshot_vault(vault_root)
        with pytest.raises(ValidationError):
            apply_changeset(changeset, approval, repo, context=_context())
        assert _snapshot_vault(vault_root) == before

    def test_later_invalid_operation_leaves_vault_unchanged(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        repo.create_entity(make_document("npc-ok"), audit=make_audit_context("setup-batch"))
        changeset = _changeset(
            _update("npc-ok", 1, status="dead"),
            _update("npc-absent", 1, status="dead"),
        )

        before = _snapshot_vault(vault_root)
        with pytest.raises(ValidationError):
            apply_changeset(changeset, _approval(changeset), repo, context=_context())
        assert _snapshot_vault(vault_root) == before
        assert repo.get_entity("npc-ok").entity.status == "alive"
