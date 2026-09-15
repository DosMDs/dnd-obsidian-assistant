"""R1 CLI tests: ChangeSet-owned intents narrow blocking, not detection.

Exercises ``dnd changeset``/mutating-command recovery preflight on real
temporary Vaults: a conclusively ChangeSet-owned intent-only audit record no
longer wedges unrelated mutations, while the affected ChangeSet stays blocked,
genuine session issues still block globally, and the raw audit log is untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import persist_approval, persist_proposal
from dnd_assistant.cli.main import app
from dnd_assistant.domain.changeset import (
    ChangeSet,
    CreateEntityOperation,
    ProposalProvenance,
)
from dnd_assistant.domain.session import Session
from dnd_assistant.domain.types import (
    EntityType,
    KnowledgeStatus,
    Provenance,
    Visibility,
)
from dnd_assistant.storage.audit import AuditContext, AuditRecord, AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.paths import entity_directory
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository

runner = CliRunner()

_T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def _audit(root: Path) -> AuditService:
    return AuditService(str(root / "_system" / "audit" / "audit.jsonl"))


def _create_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "_system" / "audit").mkdir(parents=True)
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "Sessions").mkdir()
    for entity_type in EntityType:
        entity_directory(root, entity_type).mkdir(parents=True)
    return root


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


def _changeset(
    changeset_id: str,
    entity_id: str,
    *,
    session_ref: str | None = None,
) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        provenance=ProposalProvenance(provenance=Provenance.MANUAL),
        session_ref=session_ref,
        operations=(_create_op(entity_id),),
    )


def _approve(root: Path, changeset: ChangeSet) -> None:
    store = _store(root)
    persist_proposal(store, changeset)
    persist_approval(
        store,
        ChangeSetApproval(
            changeset_id=changeset.changeset_id,
            fingerprint=compute_changeset_fingerprint(changeset),
            decision=ReviewDecision.APPROVED,
            reviewer="dm",
        ),
    )


def _start_session(root: Path, session_id: str = "S003") -> None:
    session = Session.model_validate(
        {
            "id": session_id,
            "type": "session",
            "status": "active",
            "revision": 1,
            "real_started_at": "2026-08-30T10:00:00+00:00",
            "world_tick_start": 100,
        }
    )
    ObsidianSessionMetadataRepository(root, _audit(root)).create_session(
        session,
        audit=AuditContext(
            operation_id=f"start-{session_id}",
            real_time=_T0,
            source="test",
        ),
    )


def _seed_intent(
    root: Path,
    operation_id: str,
    *,
    session: str | None,
    entity_id: str,
) -> None:
    _audit(root).append(
        AuditRecord(
            operation_id=operation_id,
            real_time=_T0,
            session=session,
            operation="create_entity",
            entity_id=entity_id,
            source="test",
            phase="intent",
        )
    )


def _seed_entity(root: Path, entity_id: str) -> None:
    from tests.integration.helpers import make_audit_context, make_document

    _repo(root).create_entity(
        make_document(entity_id), audit=make_audit_context(f"setup-{entity_id}")
    )


def _repo(root: Path):
    from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

    return ObsidianVaultRepository(vault_root=str(root), audit_service=_audit(root))


class TestR1RecoveryOwnership:
    def test_owned_intent_does_not_block_unrelated_apply(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _start_session(root, "S003")
        owned = _changeset("cs-r1", "npc-r1", session_ref="S003")
        _approve(root, owned)
        other = _changeset("cs-other", "npc-other")
        _approve(root, other)

        # Window A: intent persisted, entity mutation not persisted.
        _seed_intent(root, "cs-r1:0", session="S003", entity_id="npc-r1")

        result = runner.invoke(app, ["changeset", "apply", "cs-other", "--vault", str(root)])

        assert result.exit_code == 0
        assert "применён" in result.stdout
        assert _repo(root).get_entity("npc-other").entity.revision == 1

    def test_owned_intent_after_entity_mutation_still_delegated(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _start_session(root, "S003")
        owned = _changeset("cs-r1b", "npc-r1b", session_ref="S003")
        _approve(root, owned)
        other = _changeset("cs-other", "npc-other")
        _approve(root, other)

        # Window B: entity present, committed audit absent for the op.
        _seed_entity(root, "npc-r1b")
        _seed_intent(root, "cs-r1b:0", session="S003", entity_id="npc-r1b")

        result = runner.invoke(app, ["changeset", "apply", "cs-other", "--vault", str(root)])

        assert result.exit_code == 0

    def test_affected_changeset_apply_still_blocked(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _start_session(root, "S003")
        owned = _changeset("cs-r1", "npc-r1", session_ref="S003")
        _approve(root, owned)
        _seed_intent(root, "cs-r1:0", session="S003", entity_id="npc-r1")

        before = _snapshot(root)
        result = runner.invoke(app, ["changeset", "apply", "cs-r1", "--vault", str(root)])

        assert result.exit_code == 1
        assert _snapshot(root) == before

    def test_status_remains_available(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _start_session(root, "S003")
        owned = _changeset("cs-r1", "npc-r1", session_ref="S003")
        _approve(root, owned)
        _seed_intent(root, "cs-r1:0", session="S003", entity_id="npc-r1")

        result = runner.invoke(app, ["changeset", "status", "cs-r1", "--vault", str(root)])

        assert result.exit_code == 0
        assert "не подтверждено" in result.stdout
        assert "Повторное применение: запрещено" in result.stdout

    def test_genuine_unresolved_intent_still_blocks_globally(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _start_session(root, "S003")
        other = _changeset("cs-other", "npc-other")
        _approve(root, other)

        # A non-ChangeSet operation id with the same session must stay blocking.
        _seed_intent(root, "genuine-op", session="S003", entity_id="npc-other")

        before = _snapshot(root)
        result = runner.invoke(app, ["changeset", "apply", "cs-other", "--vault", str(root)])

        assert result.exit_code == 1
        assert "Обнаружено" in result.stderr
        assert _snapshot(root) == before

    def test_preflight_does_not_rewrite_audit(self, tmp_path: Path) -> None:
        root = _create_vault(tmp_path)
        _start_session(root, "S003")
        owned = _changeset("cs-r1", "npc-r1", session_ref="S003")
        _approve(root, owned)
        other = _changeset("cs-other", "npc-other")
        _approve(root, other)
        _seed_intent(root, "cs-r1:0", session="S003", entity_id="npc-r1")

        audit_path = root / "_system" / "audit" / "audit.jsonl"
        before = audit_path.read_bytes()

        runner.invoke(app, ["changeset", "apply", "cs-other", "--vault", str(root)])

        # cs-other apply appends its own records; the pre-existing bytes are a
        # strict prefix and nothing was rewritten or truncated.
        after = audit_path.read_bytes()
        assert after.startswith(before)
        assert len(after) >= len(before)
