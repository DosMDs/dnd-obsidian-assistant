"""Unit tests for the S10-05 ``dnd changeset`` CLI workflow.

Uses real temporary Vaults (canonical entity directories + ``_system``),
``CliRunner`` and the real storage/application stack, except where a crafted
apply result is injected to exercise FAILED/PARTIAL rendering.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnd_assistant.application.changeset_apply import (
    ApplyFailure,
    ApplyFailureCategory,
    ChangeSetApplyOutcome,
    ChangeSetApplyResult,
)
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import (
    load_approval,
    persist_approval,
    persist_proposal,
    serialize_proposal,
)
from dnd_assistant.cli.main import app
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
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.paths import entity_directory
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

runner = CliRunner()

MUTATION_TIME = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


# ── Vault / stack helpers ──────────────────────────────────────────────────


def _create_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "_system" / "audit").mkdir(parents=True)
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "Sessions").mkdir()
    for entity_type in EntityType:
        entity_directory(root, entity_type).mkdir(parents=True)
    return root


def _repo(root: Path) -> ObsidianVaultRepository:
    audit = AuditService(str(root / "_system" / "audit" / "audit.jsonl"))
    return ObsidianVaultRepository(vault_root=str(root), audit_service=audit)


def _store(root: Path) -> ObsidianChangeSetStore:
    return ObsidianChangeSetStore(root)


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


def _append_op(entity_id: str, revision: int, fact: str) -> AppendFactOperation:
    return AppendFactOperation(entity_id=entity_id, expected_revision=revision, fact=fact)


def _update_op(entity_id: str, revision: int, **fields: object) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        entity_id=entity_id,
        expected_revision=revision,
        update=EntityFieldUpdate(**fields),  # type: ignore[arg-type]
    )


def _changeset(
    changeset_id: str = "cs-1",
    operations: tuple[object, ...] | None = None,
    *,
    fact: str = "Found a key",
) -> ChangeSet:
    ops = operations if operations is not None else (_create_op("npc-new"),)
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        operations=ops,  # type: ignore[arg-type]
    )


def _approval(changeset: ChangeSet, *, decision: ReviewDecision = ReviewDecision.APPROVED):
    return ChangeSetApproval(
        changeset_id=changeset.changeset_id,
        fingerprint=compute_changeset_fingerprint(changeset),
        decision=decision,
        reviewer="dm",
    )


def _seed_entity(root: Path, entity_id: str) -> None:
    from tests.integration.helpers import make_audit_context, make_document

    _repo(root).create_entity(make_document(entity_id), audit=make_audit_context("setup"))


# ── Help ───────────────────────────────────────────────────────────────────


class TestHelp:
    def test_subgroup_help_lists_commands(self) -> None:
        result = runner.invoke(app, ["changeset", "--help"])
        assert result.exit_code == 0
        for command in ("save", "review", "approve", "reject", "apply"):
            assert command in result.stdout

    def test_root_help_lists_changeset(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "changeset" in result.stdout


# ── save ───────────────────────────────────────────────────────────────────


class TestSave:
    def _write_document(self, tmp_path: Path, changeset: ChangeSet, name: str) -> Path:
        document = tmp_path / name
        document.write_text(serialize_proposal(changeset), encoding="utf-8")
        return document

    def test_save_valid(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        document = self._write_document(tmp_path, _changeset(), "proposal.json")

        result = runner.invoke(app, ["changeset", "save", str(document), "--vault", str(root)])

        assert result.exit_code == 0
        assert "сохранён" in result.stdout
        assert _store(root).read_proposal("cs-1")

    def test_save_identical_is_idempotent(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        document = self._write_document(tmp_path, _changeset(), "proposal.json")

        runner.invoke(app, ["changeset", "save", str(document), "--vault", str(root)])
        result = runner.invoke(app, ["changeset", "save", str(document), "--vault", str(root)])

        assert result.exit_code == 0
        assert "уже сохранён" in result.stdout

    def test_save_same_id_different_content_conflicts(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        first = self._write_document(
            tmp_path, _changeset("cs-1", (_create_op("npc-a"),)), "first.json"
        )
        second = self._write_document(
            tmp_path, _changeset("cs-1", (_create_op("npc-b"),)), "second.json"
        )

        runner.invoke(app, ["changeset", "save", str(first), "--vault", str(root)])
        result = runner.invoke(app, ["changeset", "save", str(second), "--vault", str(root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr

    def test_save_malformed_input(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        document = tmp_path / "broken.json"
        document.write_text("{not json", encoding="utf-8")

        result = runner.invoke(app, ["changeset", "save", str(document), "--vault", str(root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr


# ── review ─────────────────────────────────────────────────────────────────


class TestReview:
    def test_review_valid(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        store = _store(root)
        persist_proposal(store, _changeset())

        result = runner.invoke(app, ["changeset", "review", "cs-1", "--vault", str(root)])

        assert result.exit_code == 0
        assert "cs-1" in result.stdout
        assert "Отпечаток" in result.stdout
        assert "create_entity" in result.stdout

    def test_review_does_not_create_approval(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())

        runner.invoke(app, ["changeset", "review", "cs-1", "--vault", str(root)])

        assert _store(root).read_approval_if_present("cs-1") is None

    def test_review_invalid_preflight(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        # Append to a non-existent entity -> preflight failure.
        invalid = _changeset("cs-1", (_append_op("npc-missing", 1, "fact"),))
        persist_proposal(_store(root), invalid)

        result = runner.invoke(app, ["changeset", "review", "cs-1", "--vault", str(root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr
        assert _store(root).read_approval_if_present("cs-1") is None

    def test_review_missing_proposal(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        result = runner.invoke(app, ["changeset", "review", "cs-missing", "--vault", str(root)])
        assert result.exit_code == 1
        assert "Ошибка" in result.stderr


# ── approve / reject ───────────────────────────────────────────────────────


class TestApproveReject:
    def test_approve_exact_proposal(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())

        result = runner.invoke(
            app,
            ["changeset", "approve", "cs-1", "--vault", str(root), "--reviewer", "dm"],
        )

        assert result.exit_code == 0
        assert "одобрен" in result.stdout
        approval = load_approval(_store(root), "cs-1")
        assert approval.is_approved
        assert approval.reviewer == "dm"

    def test_reject_exact_proposal(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())

        result = runner.invoke(
            app,
            ["changeset", "reject", "cs-1", "--vault", str(root), "--reviewer", "dm"],
        )

        assert result.exit_code == 0
        assert "отклонён" in result.stdout
        approval = load_approval(_store(root), "cs-1")
        assert not approval.is_approved

    def test_approve_reason_present(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())

        result = runner.invoke(
            app,
            [
                "changeset",
                "approve",
                "cs-1",
                "--vault",
                str(root),
                "--reviewer",
                "dm",
                "--reason",
                "проверено",
            ],
        )

        assert result.exit_code == 0
        assert "проверено" in result.stdout
        assert load_approval(_store(root), "cs-1").reason == "проверено"

    def test_reviewer_required(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())

        result = runner.invoke(app, ["changeset", "approve", "cs-1", "--vault", str(root)])

        assert result.exit_code != 0
        assert _store(root).read_approval_if_present("cs-1") is None

    def test_approve_requires_existing_proposal(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)

        result = runner.invoke(
            app,
            ["changeset", "approve", "cs-missing", "--vault", str(root), "--reviewer", "dm"],
        )

        assert result.exit_code == 1
        assert _store(root).read_approval_if_present("cs-missing") is None

    def test_second_differing_decision_conflicts(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())
        runner.invoke(
            app,
            ["changeset", "approve", "cs-1", "--vault", str(root), "--reviewer", "dm"],
        )

        result = runner.invoke(
            app,
            ["changeset", "reject", "cs-1", "--vault", str(root), "--reviewer", "dm"],
        )

        assert result.exit_code == 1
        assert load_approval(_store(root), "cs-1").is_approved


# ── apply ──────────────────────────────────────────────────────────────────


class TestApply:
    def test_apply_approved_persists_entity(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        changeset = _changeset("cs-1", (_create_op("npc-new"),))
        persist_proposal(_store(root), changeset)
        persist_approval(_store(root), _approval(changeset))

        result = runner.invoke(app, ["changeset", "apply", "cs-1", "--vault", str(root)])

        assert result.exit_code == 0
        assert "применён" in result.stdout
        assert _repo(root).get_entity("npc-new").entity.revision == 1

    def test_apply_rejected_is_zero_mutation(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        changeset = _changeset("cs-1", (_create_op("npc-new"),))
        persist_proposal(_store(root), changeset)
        persist_approval(_store(root), _approval(changeset, decision=ReviewDecision.REJECTED))

        before = _snapshot(root)
        result = runner.invoke(app, ["changeset", "apply", "cs-1", "--vault", str(root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr
        assert _snapshot(root) == before

    def test_apply_fingerprint_mismatch_is_zero_mutation(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        original = _changeset("cs-1", (_create_op("npc-new"),))
        store = _store(root)
        persist_proposal(store, original)
        persist_approval(store, _approval(original))

        # Tamper: same id, different valid content.
        tampered = _changeset("cs-1", (_create_op("npc-other"),))
        (store.changesets_dir / "cs-1.proposal.json").write_text(
            serialize_proposal(tampered), encoding="utf-8"
        )

        before = _snapshot(root)
        result = runner.invoke(app, ["changeset", "apply", "cs-1", "--vault", str(root)])

        assert result.exit_code == 1
        assert _snapshot(root) == before

    def test_apply_stale_revision_is_zero_apply_mutation(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _seed_entity(root, "npc-1")
        changeset = _changeset("cs-1", (_update_op("npc-1", 1, status="dead"),))
        store = _store(root)
        persist_proposal(store, changeset)
        persist_approval(store, _approval(changeset))

        # Another writer advances the revision after approval.
        from tests.integration.helpers import make_audit_context

        _repo(root).patch_entity(
            "npc-1",
            EntityPatch(status="wounded"),
            expected_revision=1,
            audit=make_audit_context("other-writer"),
        )

        before = _snapshot(root)
        result = runner.invoke(app, ["changeset", "apply", "cs-1", "--vault", str(root)])

        assert result.exit_code == 1
        assert _snapshot(root) == before

    def test_apply_missing_approval(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        persist_proposal(_store(root), _changeset())

        result = runner.invoke(app, ["changeset", "apply", "cs-1", "--vault", str(root)])

        assert result.exit_code == 1
        assert "Ошибка" in result.stderr


# ── Apply rendering ────────────────────────────────────────────────────────


class TestApplyRendering:
    def test_applied_rendering(self) -> None:
        from dnd_assistant.cli.changeset import _render_apply_result

        result = ChangeSetApplyResult(
            changeset_id="cs-1",
            outcome=ChangeSetApplyOutcome.APPLIED,
            applied_operation_indices=(0, 1),
            remaining_operation_indices=(),
            failure=None,
        )
        text = _render_apply_result(result)
        assert "применён" in text
        assert "0, 1" in text

    def test_failed_rendering(self) -> None:
        from dnd_assistant.cli.changeset import _render_apply_result

        result = ChangeSetApplyResult(
            changeset_id="cs-1",
            outcome=ChangeSetApplyOutcome.FAILED,
            applied_operation_indices=(),
            remaining_operation_indices=(1, 2),
            failure=ApplyFailure(
                operation_index=0,
                category=ApplyFailureCategory.CONFLICT,
                message="revision mismatch",
                entity_id="npc-1",
            ),
        )
        text = _render_apply_result(result)
        assert "ни одна операция не выполнена" in text
        assert "conflict" in text
        assert "1, 2" in text

    def test_partial_rendering_does_not_imply_rollback(self) -> None:
        from dnd_assistant.cli.changeset import _render_apply_result

        result = ChangeSetApplyResult(
            changeset_id="cs-1",
            outcome=ChangeSetApplyOutcome.PARTIAL,
            applied_operation_indices=(0,),
            remaining_operation_indices=(2,),
            failure=ApplyFailure(
                operation_index=1,
                category=ApplyFailureCategory.STORAGE,
                message="disk full",
                entity_id="npc-2",
            ),
        )
        text = _render_apply_result(result)
        assert "частично" in text
        assert "откат не выполнялся" in text
        assert "0" in text
        assert "2" in text

    def test_partial_cli_exit_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = _create_vault(tmp_path)
        changeset = _changeset("cs-1", (_create_op("npc-new"), _create_op("npc-new-2")))
        store = _store(root)
        persist_proposal(store, changeset)
        persist_approval(store, _approval(changeset))

        def fake_apply(*args: object, **kwargs: object) -> ChangeSetApplyResult:
            return ChangeSetApplyResult(
                changeset_id="cs-1",
                outcome=ChangeSetApplyOutcome.PARTIAL,
                applied_operation_indices=(0,),
                remaining_operation_indices=(),
                failure=ApplyFailure(
                    operation_index=1,
                    category=ApplyFailureCategory.STORAGE,
                    message="disk full",
                    entity_id="npc-new-2",
                ),
            )

        monkeypatch.setattr("dnd_assistant.cli.changeset.apply_changeset", fake_apply)
        result = runner.invoke(app, ["changeset", "apply", "cs-1", "--vault", str(root)])

        assert result.exit_code == 1
        assert "откат не выполнялся" in result.stdout
