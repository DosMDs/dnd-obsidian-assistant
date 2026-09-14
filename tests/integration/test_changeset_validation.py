"""Integration tests for S10-02 preflight against a real temporary Vault.

These tests wire :func:`validate_changeset` to a real ``ObsidianVaultRepository``
and prove the S10-02 hard invariant: validation reads repository state but
performs zero filesystem or audit writes.  After each validation the entire
Vault tree is compared byte-for-byte with the pre-validation snapshot.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.changeset_validation import (
    ValidationIssueCode,
    validate_changeset,
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
from dnd_assistant.storage.types import VaultRepository
from tests.integration.helpers import make_audit_context, make_document


def _snapshot_vault(vault_root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(vault_root)): path.read_bytes()
        for path in sorted(vault_root.rglob("*"))
        if path.is_file()
    }


def _changeset(*operations: object) -> ChangeSet:
    return ChangeSet(
        changeset_id="cs_integration",
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=operations,  # type: ignore[arg-type]
    )


def _create(entity_id: str) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=EntityType.NPC,
        name=f"Entity {entity_id}",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
    )


def _update(entity_id: str, expected_revision: int) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        update=EntityFieldUpdate(status="dead"),
    )


def _append(entity_id: str, expected_revision: int) -> AppendFactOperation:
    return AppendFactOperation(
        entity_id=entity_id,
        expected_revision=expected_revision,
        fact="Slain at the gate",
    )


class TestRealRepositoryReads:
    def test_valid_revision_detected_from_persisted_state(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        repo.create_entity(make_document("npc-repo"), audit=make_audit_context("setup-1"))
        before = _snapshot_vault(vault_root)

        result = validate_changeset(_changeset(_update("npc-repo", 1)), repo)

        assert result.valid is True
        assert _snapshot_vault(vault_root) == before

    def test_existing_create_conflict_from_persisted_state(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        repo.create_entity(make_document("npc-repo"), audit=make_audit_context("setup-2"))
        before = _snapshot_vault(vault_root)

        result = validate_changeset(_changeset(_create("npc-repo")), repo)

        assert [issue.code for issue in result.issues] == [ValidationIssueCode.CREATE_TARGET_EXISTS]
        assert _snapshot_vault(vault_root) == before

    def test_stale_revision_conflict_from_persisted_state(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        repo.create_entity(make_document("npc-repo"), audit=make_audit_context("setup-3"))
        before = _snapshot_vault(vault_root)

        result = validate_changeset(_changeset(_update("npc-repo", 9)), repo)

        assert [issue.code for issue in result.issues] == [ValidationIssueCode.REVISION_CONFLICT]
        assert _snapshot_vault(vault_root) == before

    def test_create_then_append_chain_validates_without_writing(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        before = _snapshot_vault(vault_root)

        changeset = _changeset(_create("npc-new"), _append("npc-new", 1))
        result = validate_changeset(changeset, repo)

        assert result.valid is True
        assert _snapshot_vault(vault_root) == before
        assert repo.list_entities() == []

    def test_missing_target_from_real_repository(
        self, repo: VaultRepository, vault_root: Path
    ) -> None:
        before = _snapshot_vault(vault_root)

        result = validate_changeset(_changeset(_append("npc-absent", 1)), repo)

        assert [issue.code for issue in result.issues] == [ValidationIssueCode.TARGET_NOT_FOUND]
        assert _snapshot_vault(vault_root) == before
