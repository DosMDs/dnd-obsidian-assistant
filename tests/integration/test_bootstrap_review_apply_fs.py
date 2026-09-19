"""S13-04 bootstrap review/approve/apply filesystem integration tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from typer.testing import CliRunner

from dnd_assistant.application.bootstrap_evidence import build_bootstrap_evidence
from dnd_assistant.application.bootstrap_input import source_ref
from dnd_assistant.application.bootstrap_mapping import run_bootstrap_mapping
from dnd_assistant.application.bootstrap_readiness import BootstrapApplyReadiness
from dnd_assistant.application.bootstrap_review import (
    BootstrapReviewState,
)
from dnd_assistant.application.changeset_apply import ChangeSetApplyOutcome
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import persist_approval, persist_proposal
from dnd_assistant.cli.changeset import changeset_app
from dnd_assistant.composition.bootstrap import canonical_candidates_from_report
from dnd_assistant.composition.bootstrap_review_apply import (
    compose_bootstrap_apply,
    compose_bootstrap_approval,
    compose_bootstrap_review,
)
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.bootstrap_evidence import ObsidianBootstrapEvidenceStore
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.vault_discovery import ObsidianVaultSourceReader
from tests.unit.bootstrap.helpers import (
    FakeBootstrapModel,
    canonical_text,
    make_candidate,
    make_claim,
    make_reference,
)

_CAMP = "camp-s13-04"
_NPC_PATH = "Characters/NPCs/varos.md"
_MALFORMED_PATH = "Characters/NPCs/old-note.md"
_NOTE_PATH = "Campaign/Overview.md"
_REF_NEW = source_ref(_CAMP, _NOTE_PATH)
_REF_VAROS = source_ref(_CAMP, _NPC_PATH)

runner = CliRunner()


def _write_vault(root: Path, *, malformed: bool = False) -> None:
    (root / "_system" / "audit").mkdir(parents=True)
    (root / "_system" / "campaign.yaml").write_text(
        f"schema_version: 1\ncampaign_id: {_CAMP}\n", encoding="utf-8"
    )
    (root / "_system" / "audit" / "audit.jsonl").write_text("", encoding="utf-8")
    (root / "_system" / "raw" / "sessions").mkdir(parents=True)
    (root / "Sessions").mkdir()
    (root / "Characters" / "NPCs").mkdir(parents=True)
    (root / _NPC_PATH).write_text(
        canonical_text("npc-1", EntityType.NPC, "Варос"), encoding="utf-8", newline=""
    )
    (root / "Campaign").mkdir()
    (root / _NOTE_PATH).write_text(
        "# Обзор\nНовый герой присоединился к партии.\n", encoding="utf-8"
    )
    if malformed:
        (root / _MALFORMED_PATH).write_text("# историческая заметка\n", encoding="utf-8")


def _discover(root: Path):
    reader = ObsidianVaultSourceReader(root)
    from dnd_assistant.application.vault_discovery import VaultDiscoveryService

    return VaultDiscoveryService(reader).run()


def _extraction() -> BootstrapExtraction:
    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(make_candidate("c1", "Новый Герой", EntityType.NPC, [_REF_NEW]),),
        claims=(
            make_claim(
                "cl1",
                "Варос — союзник партии.",
                [_REF_VAROS],
                references=(make_reference("r1", "Варос", EntityType.NPC, [_REF_VAROS]),),
            ),
        ),
    )


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            result[str(path.relative_to(root)).replace("\\", "/")] = (
                len(data),
                hashlib.sha256(data).hexdigest(),
            )
    return result


def _audit_count(root: Path) -> int:
    service = AuditService(str(root / "_system" / "audit" / "audit.jsonl"))
    return len(service.read_all())


def _produce(root: Path, *, extra_unresolved_ref: str | None = None) -> str:
    """Run the real mapping pipeline and persist proposal + evidence."""
    report = _discover(root)
    run = run_bootstrap_mapping(
        report, canonical_candidates_from_report(report), FakeBootstrapModel(_extraction())
    )
    changeset = run.result.changeset
    assert changeset is not None
    record = build_bootstrap_evidence(
        run.projection,
        run.result,
        producer_version=run.processor_version,
        prompt_version=run.prompt_version,
        extraction_schema_version=run.extraction_schema_version,
        model_profile="heavy",
        model="m",
        provider="ollama",
    )
    if extra_unresolved_ref is not None:
        from dnd_assistant.application.bootstrap_evidence import EvidenceUnresolved

        record = record.model_copy(
            update={
                "unresolved": (
                    *record.unresolved,
                    EvidenceUnresolved(
                        reason="source_skipped",
                        detail="тест",
                        source_refs=(extra_unresolved_ref,),
                    ),
                )
            }
        )
    persist_proposal(ObsidianChangeSetStore(root), changeset)
    ObsidianBootstrapEvidenceStore(root).create_evidence(changeset.changeset_id, _serialize(record))
    return changeset.changeset_id


def _serialize(record) -> str:
    from dnd_assistant.application.bootstrap_evidence import serialize_bootstrap_evidence

    return serialize_bootstrap_evidence(record)


def _approve(root: Path, changeset_id: str, *, acknowledge: bool = True) -> None:
    approval_run = compose_bootstrap_approval(
        root, changeset_id, acknowledge_unresolved=acknowledge
    )
    assert approval_run.readiness.readiness is BootstrapApplyReadiness.READY
    changeset = approval_run.bundle.changeset
    persist_approval(
        ObsidianChangeSetStore(root),
        ChangeSetApproval(
            changeset_id=changeset_id,
            fingerprint=compute_changeset_fingerprint(changeset),
            decision=ReviewDecision.APPROVED,
            reviewer="dm",
        ),
    )


# ── Strict Vault happy path ───────────────────────────────────────────────


def test_strict_vault_review_approve_apply(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path)
    assert _discover(tmp_path).campaign_id == _CAMP

    review = compose_bootstrap_review(tmp_path, changeset_id)
    assert review.bundle.review_state is BootstrapReviewState.REVIEWABLE
    assert review.bundle.changeset_review is not None
    assert review.readiness.readiness is BootstrapApplyReadiness.READY

    _approve(tmp_path, changeset_id)
    before = _snapshot(tmp_path)
    apply_result = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert apply_result.readiness is BootstrapApplyReadiness.READY
    assert apply_result.apply_result is not None
    assert apply_result.apply_result.outcome is ChangeSetApplyOutcome.APPLIED
    assert apply_result.attempt_recorded is True
    assert apply_result.attempt_error is None

    after = _snapshot(tmp_path)
    assert after != before
    assert any(path.endswith(".apply.jsonl") for path in after)
    sources = [
        r.source
        for r in AuditService(str(tmp_path / "_system" / "audit" / "audit.jsonl")).read_all()
    ]
    assert "bootstrap_apply" in sources


def test_second_apply_is_blocked(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path)
    _approve(tmp_path, changeset_id)
    first = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert first.apply_result is not None
    assert first.apply_result.outcome is ChangeSetApplyOutcome.APPLIED

    second = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert second.readiness in (
        BootstrapApplyReadiness.NOT_APPLICABLE,
        BootstrapApplyReadiness.STALE_SOURCE,
    )
    assert second.apply_result is None


# ── Mixed Vault ───────────────────────────────────────────────────────────


def test_mixed_vault_review_works_but_apply_blocked_zero_writes(tmp_path: Path) -> None:
    _write_vault(tmp_path, malformed=True)
    changeset_id = _produce(tmp_path)

    review = compose_bootstrap_review(tmp_path, changeset_id)
    assert review.bundle.review_state is BootstrapReviewState.REVIEWABLE
    assert review.bundle.changeset_review is not None
    assert review.readiness.readiness is BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY

    _approve(tmp_path, changeset_id)
    before = _snapshot(tmp_path)
    audit_before = _audit_count(tmp_path)
    result = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert result.readiness is BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY
    assert result.apply_result is None
    assert _snapshot(tmp_path) == before
    assert _audit_count(tmp_path) == audit_before


def test_duplicate_canonical_ids_block_apply(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    duplicate = canonical_text("npc-1", EntityType.NPC, "Варос-дубль")
    (tmp_path / "Characters" / "NPCs" / "varos-copy.md").write_text(duplicate, encoding="utf-8")
    changeset_id = _produce(tmp_path)
    review = compose_bootstrap_review(tmp_path, changeset_id)
    assert review.readiness.readiness in (
        BootstrapApplyReadiness.STRICT_REPOSITORY_NOT_READY,
        BootstrapApplyReadiness.CHANGESET_PREFLIGHT_FAILED,
    )
    _approve(tmp_path, changeset_id)
    before = _snapshot(tmp_path)
    result = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert result.apply_result is None
    assert _snapshot(tmp_path) == before


def test_generic_approval_with_stale_source_blocks_apply(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path)
    # Approval bound while the source was fresh, then the source changes: the
    # persisted approval must not authorize a stale bootstrap apply.
    _approve(tmp_path, changeset_id)
    (tmp_path / _NOTE_PATH).write_text("# Другое\nИзменено.\n", encoding="utf-8")
    before = _snapshot(tmp_path)
    result = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert result.readiness is BootstrapApplyReadiness.STALE_SOURCE
    assert result.apply_result is None
    assert _snapshot(tmp_path) == before


def test_missing_evidence_blocks_review_and_apply(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path)
    evidence_path = tmp_path / "_system" / "bootstrap" / f"{changeset_id}.mapping.json"
    evidence_path.unlink()
    before = _snapshot(tmp_path)

    review = compose_bootstrap_review(tmp_path, changeset_id)
    assert review.bundle.review_state is BootstrapReviewState.NOT_REVIEWABLE
    assert review.bundle.changeset_review is None

    result = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert result.readiness is BootstrapApplyReadiness.MISSING_EVIDENCE
    assert result.apply_result is None
    assert _snapshot(tmp_path) == before


def test_unresolved_requires_acknowledgement(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path, extra_unresolved_ref=_REF_NEW)

    approval_run = compose_bootstrap_approval(tmp_path, changeset_id, acknowledge_unresolved=False)
    assert approval_run.readiness.readiness is BootstrapApplyReadiness.UNRESOLVED_NOT_ACKNOWLEDGED

    _approve(tmp_path, changeset_id)
    before = _snapshot(tmp_path)
    result = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=False)
    assert result.readiness is BootstrapApplyReadiness.UNRESOLVED_NOT_ACKNOWLEDGED
    assert _snapshot(tmp_path) == before

    ok = compose_bootstrap_apply(tmp_path, changeset_id, acknowledge_unresolved=True)
    assert ok.readiness is BootstrapApplyReadiness.READY


# ── Generic bypass guard ──────────────────────────────────────────────────


def test_generic_changeset_apply_refuses_bootstrap_proposal(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path)
    _approve(tmp_path, changeset_id)
    before = _snapshot(tmp_path)
    audit_before = _audit_count(tmp_path)

    invocation = runner.invoke(changeset_app, ["apply", changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 1
    assert "bootstrap" in invocation.output.lower()
    assert _snapshot(tmp_path) == before
    assert _audit_count(tmp_path) == audit_before


def test_generic_status_warns_bootstrap_scoped(tmp_path: Path) -> None:
    _write_vault(tmp_path)
    changeset_id = _produce(tmp_path)
    invocation = runner.invoke(changeset_app, ["status", changeset_id, "--vault", str(tmp_path)])
    assert invocation.exit_code == 0, invocation.output
    assert "bootstrap" in invocation.output.lower()
    assert "Stage-10" in invocation.output
