"""Integration tests for the S10-05 ``dnd changeset`` CLI workflow.

Exercises the full CLI path against a real temporary Vault:
save -> review -> approve -> apply, approval-fingerprint staleness and
stale-revision fail-closed behavior.  Zero-mutation assertions snapshot the
entire Vault immediately before apply so setup-time proposal/approval artifacts
are not mistaken for apply writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnd_assistant.application.changeset_store import serialize_proposal
from dnd_assistant.cli.main import app
from dnd_assistant.domain.changeset import (
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
from dnd_assistant.storage.audit import AuditRecord, AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from tests.integration.helpers import BASE_TIME, make_audit_context, make_document

runner = CliRunner()


@pytest.fixture(autouse=True)
def _ensure_runtime_roots(vault_root: Path) -> None:
    """Ensure canonical session runtime roots exist for recovery preflight."""
    (vault_root / "Sessions").mkdir(exist_ok=True)
    (vault_root / "_system" / "raw" / "sessions").mkdir(parents=True, exist_ok=True)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _create_op(entity_id: str) -> CreateEntityOperation:
    return CreateEntityOperation(
        entity_id=entity_id,
        type=EntityType.NPC,
        name=f"Entity {entity_id}",
        status="alive",
        visibility=Visibility.DM,
        knowledge_status=KnowledgeStatus.CONFIRMED,
    )


def _changeset(changeset_id: str, operations: tuple[object, ...]) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=operations,  # type: ignore[arg-type]
    )


def _save_document(tmp_path: Path, changeset: ChangeSet, name: str) -> Path:
    document = tmp_path / name
    document.write_text(serialize_proposal(changeset), encoding="utf-8")
    return document


class TestCliWorkflow:
    def test_save_review_approve_apply(
        self, tmp_path: Path, vault_root: Path, repo: ObsidianVaultRepository
    ) -> None:
        changeset = _changeset("cs-flow", (_create_op("npc-flow"),))
        document = _save_document(tmp_path, changeset, "proposal.json")

        save = runner.invoke(app, ["changeset", "save", str(document), "--vault", str(vault_root)])
        assert save.exit_code == 0

        review = runner.invoke(app, ["changeset", "review", "cs-flow", "--vault", str(vault_root)])
        assert review.exit_code == 0
        assert "cs-flow" in review.stdout

        approve = runner.invoke(
            app,
            [
                "changeset",
                "approve",
                "cs-flow",
                "--vault",
                str(vault_root),
                "--reviewer",
                "dm",
            ],
        )
        assert approve.exit_code == 0

        apply_result = runner.invoke(
            app, ["changeset", "apply", "cs-flow", "--vault", str(vault_root)]
        )
        assert apply_result.exit_code == 0
        assert "применён" in apply_result.stdout

        persisted = repo.get_entity("npc-flow")
        assert persisted.entity.revision == 1

        approval_text = ObsidianChangeSetStore(vault_root).read_approval("cs-flow")
        assert "approved" in approval_text
        assert '"reviewer":"dm"' in approval_text

        # S10-06: the durable apply-attempt artifact exists and a fresh store
        # instance (the ``status`` invocation composes a new one) reports truth.
        attempt_artifact = vault_root / "_system" / "changesets" / "cs-flow.apply.jsonl"
        assert attempt_artifact.is_file()
        status = runner.invoke(app, ["changeset", "status", "cs-flow", "--vault", str(vault_root)])
        assert status.exit_code == 0
        assert "Записей о применении: 1" in status.stdout
        assert "Последний результат: применён" in status.stdout
        assert "Повторное применение: запрещено" in status.stdout

    def test_tampered_proposal_fails_fingerprint_and_mutates_nothing(
        self, tmp_path: Path, vault_root: Path
    ) -> None:
        original = _changeset("cs-tamper", (_create_op("npc-a"),))
        document = _save_document(tmp_path, original, "proposal.json")
        runner.invoke(app, ["changeset", "save", str(document), "--vault", str(vault_root)])
        runner.invoke(
            app,
            ["changeset", "approve", "cs-tamper", "--vault", str(vault_root), "--reviewer", "dm"],
        )

        store = ObsidianChangeSetStore(vault_root)
        tampered = _changeset("cs-tamper", (_create_op("npc-b"),))
        (store.changesets_dir / "cs-tamper.proposal.json").write_text(
            serialize_proposal(tampered), encoding="utf-8"
        )

        before = _snapshot(vault_root)
        result = runner.invoke(app, ["changeset", "apply", "cs-tamper", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert _snapshot(vault_root) == before
        assert not (vault_root / "_system" / "changesets" / "cs-tamper.apply.jsonl").exists()

    def test_stale_revision_fails_fresh_preflight_and_mutates_nothing(
        self, tmp_path: Path, vault_root: Path, repo: ObsidianVaultRepository
    ) -> None:
        repo.create_entity(make_document("npc-stale"), audit=make_audit_context("setup-stale"))
        changeset = _changeset(
            "cs-stale",
            (
                UpdateEntityOperation(
                    entity_id="npc-stale",
                    expected_revision=1,
                    update=EntityFieldUpdate(status="dead"),
                ),
            ),
        )
        document = _save_document(tmp_path, changeset, "proposal.json")
        runner.invoke(app, ["changeset", "save", str(document), "--vault", str(vault_root)])
        runner.invoke(
            app,
            ["changeset", "approve", "cs-stale", "--vault", str(vault_root), "--reviewer", "dm"],
        )

        # Another writer advances the revision after approval.
        repo.patch_entity(
            "npc-stale",
            EntityPatch(status="wounded"),
            expected_revision=1,
            audit=make_audit_context("other-writer"),
        )

        before = _snapshot(vault_root)
        result = runner.invoke(app, ["changeset", "apply", "cs-stale", "--vault", str(vault_root)])

        assert result.exit_code == 1
        assert _snapshot(vault_root) == before
        assert not (vault_root / "_system" / "changesets" / "cs-stale.apply.jsonl").exists()


class TestCrashWithoutAttemptArtifact:
    """Audit evidence without a workflow record must fail closed."""

    def _proposal(self, changeset_id: str, entity_id: str) -> ChangeSet:
        return _changeset(changeset_id, (_create_op(entity_id),))

    def test_committed_audit_without_artifact_blocks(
        self, tmp_path: Path, vault_root: Path, repo: ObsidianVaultRepository
    ) -> None:
        changeset = self._proposal("cs-commit", "npc-commit")
        document = _save_document(tmp_path, changeset, "proposal.json")
        runner.invoke(app, ["changeset", "save", str(document), "--vault", str(vault_root)])
        runner.invoke(
            app,
            ["changeset", "approve", "cs-commit", "--vault", str(vault_root), "--reviewer", "dm"],
        )

        # Crash-equivalent: the entity + committed audit exist, but the workflow
        # artifact was never written (operation id matches the apply scheme).
        repo.create_entity(make_document("npc-commit"), audit=make_audit_context("cs-commit:0"))

        status = runner.invoke(
            app, ["changeset", "status", "cs-commit", "--vault", str(vault_root)]
        )
        assert status.exit_code == 0
        assert "зафиксировано (intent + committed)" in status.stdout
        assert "Повторное применение: запрещено" in status.stdout

        before = _snapshot(vault_root)
        apply_result = runner.invoke(
            app, ["changeset", "apply", "cs-commit", "--vault", str(vault_root)]
        )
        assert apply_result.exit_code == 1
        assert _snapshot(vault_root) == before

    def test_intent_only_audit_without_artifact_blocks(
        self, tmp_path: Path, vault_root: Path
    ) -> None:
        changeset = self._proposal("cs-intent", "npc-intent")
        document = _save_document(tmp_path, changeset, "proposal.json")
        runner.invoke(app, ["changeset", "save", str(document), "--vault", str(vault_root)])
        runner.invoke(
            app,
            ["changeset", "approve", "cs-intent", "--vault", str(vault_root), "--reviewer", "dm"],
        )

        AuditService(str(vault_root / "_system" / "audit" / "audit.jsonl")).append(
            AuditRecord(
                operation_id="cs-intent:0",
                real_time=BASE_TIME,
                operation="create_entity",
                entity_id="npc-intent",
                source="test",
                phase="intent",
            )
        )

        status = runner.invoke(
            app, ["changeset", "status", "cs-intent", "--vault", str(vault_root)]
        )
        assert status.exit_code == 0
        assert "не подтверждено" in status.stdout
        assert "Повторное применение: запрещено" in status.stdout

        before = _snapshot(vault_root)
        apply_result = runner.invoke(
            app, ["changeset", "apply", "cs-intent", "--vault", str(vault_root)]
        )
        assert apply_result.exit_code == 1
        assert _snapshot(vault_root) == before
