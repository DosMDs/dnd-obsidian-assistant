"""S14-03 offline scripted-model bootstrap full-sequence regression.

One deterministic, offline cross-stage regression over the already accepted
Stage-13 workflow, driven through real production boundaries::

    existing campaign material
    -> dnd init
    -> dnd time init
    -> first fresh bootstrap finalize        (PENDING_CHANGESET)
    -> review -> content-bound approval -> apply through the real ChangeSet path
    -> second fresh bootstrap finalize       (NO_CHANGES / COMPLETE)
    -> Campaign State CURRENT + FTS fresh/verified

The working Vault is derived from the immutable golden fixture: assistant-owned
``_system`` state (marker, world time, fixture manifest, audit seed, derived and
workflow directories) is excluded, while historical append-only raw session
material under ``_system/raw/sessions/**`` is preserved.  The tracked fixture is
only read; a recursive byte/hash snapshot proves it is unchanged.

Only the model/extraction operator is replaced with a deterministic, offline,
phase/batch-aware scripted double.  Discovery, canonical projection, binding,
ChangeSet production, proposal/evidence persistence, source fingerprinting,
completion classification, review readiness, approval and apply remain the real
production implementations.  No Ollama and no network access occur.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dnd_assistant.application.bootstrap_completion import BootstrapCompletionStatus
from dnd_assistant.application.bootstrap_extraction import BootstrapExtractionRequest
from dnd_assistant.application.bootstrap_input import prepare_bootstrap_input
from dnd_assistant.application.bootstrap_readiness import BootstrapApplyReadiness
from dnd_assistant.application.bootstrap_result import BootstrapMappingOutcome
from dnd_assistant.application.bootstrap_review import BootstrapReviewState
from dnd_assistant.application.campaign_state_materialization import CampaignStateStatus
from dnd_assistant.application.changeset_apply import ChangeSetApplyOutcome
from dnd_assistant.application.changeset_review import (
    ChangeSetApproval,
    ReviewDecision,
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import (
    ApprovalPersistOutcome,
    load_approval,
    persist_approval,
)
from dnd_assistant.cli.main import app as cli_app
from dnd_assistant.composition.bootstrap import compose_bootstrap_discovery
from dnd_assistant.composition.bootstrap_completion import finalize_bootstrap
from dnd_assistant.composition.bootstrap_review_apply import (
    compose_bootstrap_apply,
    compose_bootstrap_approval,
    compose_bootstrap_context,
    compose_bootstrap_review,
)
from dnd_assistant.composition.campaign_state import compose_campaign_state_capability
from dnd_assistant.composition.index_rebuild import verify_fts_index
from dnd_assistant.composition.session_runtime import compose_recovery_service
from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapEntityCandidate,
    BootstrapExtraction,
)
from dnd_assistant.domain.changeset import CreateEntityOperation
from dnd_assistant.domain.types import EntityType, KnowledgeStatus, Visibility
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

GOLDEN_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "golden_test_vault"
_ENTITY_DIRECTORIES = ("Characters", "Locations", "Quests", "Items")
_WORLD_TICK = 13_800
_PROPOSAL_NAME = "С14 Полносеквенсный Свидетель"

_runner = CliRunner()


# ── Scripted model double (local to this module) ──────────────────────────


class _ScriptedBootstrapModel:
    """Ordered, phase/batch-aware ``BootstrapExtractionModel`` test double.

    Responses are queued per production batch.  The double consumes exactly the
    queued responses in order and fails loudly if the production mapping runtime
    requests more batches than the deterministically derived expectation.
    """

    def __init__(self) -> None:
        self._pending: list[Callable[[BootstrapExtractionRequest], BootstrapExtraction]] = []
        self.requests: list[BootstrapExtractionRequest] = []

    def queue(
        self,
        responses: Sequence[Callable[[BootstrapExtractionRequest], BootstrapExtraction]],
    ) -> None:
        self._pending.extend(responses)

    def extract(self, request: BootstrapExtractionRequest) -> BootstrapExtraction:
        if not self._pending:
            raise AssertionError("unexpected extra bootstrap model request")
        self.requests.append(request)
        return self._pending.pop(0)(request)

    @property
    def request_count(self) -> int:
        return len(self.requests)


def _proposal_response(request: BootstrapExtractionRequest) -> BootstrapExtraction:
    """First-phase response introducing exactly one new NPC candidate."""
    return BootstrapExtraction(
        schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
        candidates=(
            BootstrapEntityCandidate(
                candidate_id="c1",
                display_name=_PROPOSAL_NAME,
                entity_type=EntityType.NPC,
                source_refs=(request.expected_source_refs[0],),
            ),
        ),
    )


def _empty_response(_request: BootstrapExtractionRequest) -> BootstrapExtraction:
    return BootstrapExtraction(schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION)


# ── Fixtures / filesystem helpers ─────────────────────────────────────────


def _prepare_golden_derived_vault(tmp_path: Path) -> Path:
    """Build a pre-init working Vault from the golden fixture.

    Assistant-owned ``_system`` state is excluded (initialization marker, world
    time, fixture manifest, audit seed, derived indexes/cache, workflow and
    migration placeholders), while historical raw session material under
    ``_system/raw`` is preserved verbatim.  Only production ``dnd init`` later
    creates the marker.
    """
    root = tmp_path / "vault"
    shutil.copytree(
        GOLDEN_VAULT,
        root,
        ignore=shutil.ignore_patterns("_system", "TEST_VAULT_README.md"),
    )
    shutil.copytree(GOLDEN_VAULT / "_system" / "raw", root / "_system" / "raw")
    return root


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        "[profiles]\n"
        "[profiles.heavy]\n"
        'provider = "ollama"\n'
        'model = "m"\n'
        'base_url = "http://localhost:11434"\n'
        'role = "bootstrap"\n',
        encoding="utf-8",
    )
    return config


def _hash_tree(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _entity_map(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for directory in _ENTITY_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _preserved_map(root: Path) -> dict[str, str]:
    """User campaign material plus preserved raw session material."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("_system/") and not rel.startswith("_system/raw/"):
            continue
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _batch_count(root: Path) -> int:
    """Literal production batch count for the current canonical source state."""
    return len(prepare_bootstrap_input(compose_bootstrap_discovery(root)).batches)


def _proposal_files(root: Path) -> list[Path]:
    changesets = root / "_system" / "changesets"
    return list(changesets.glob("*.proposal.json")) if changesets.exists() else []


def _repository(root: Path) -> ObsidianVaultRepository:
    audit_service = AuditService(str(root / "_system" / "audit" / "audit.jsonl"))
    return ObsidianVaultRepository(vault_root=str(root), audit_service=audit_service)


def _dummy_model_factory(_profile: object) -> Any:
    """Placeholder model; the extraction adapter is replaced by the double."""
    return object()


def _finalize_and_patch(
    root: Path,
    config: Path,
    scripted: _ScriptedBootstrapModel,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "dnd_assistant.application.pydantic_ai_bootstrap.PydanticAIBootstrapExtractionModel",
        lambda *, model: scripted,
    )
    return finalize_bootstrap(
        vault_root=root,
        config_path=config,
        profile_name="heavy",
        acknowledge_unresolved=False,
        model_factory=_dummy_model_factory,
    )


# ── Full-sequence regression ──────────────────────────────────────────────


def test_golden_derived_full_bootstrap_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden_before = _hash_tree(GOLDEN_VAULT)
    root = _prepare_golden_derived_vault(tmp_path)
    config = _write_config(tmp_path)
    scripted = _ScriptedBootstrapModel()

    # Precondition: the excluded assistant state is genuinely absent, raw
    # historical session material is preserved, and nothing has asked a model.
    assert not (root / "_system" / "campaign.yaml").exists()
    assert not (root / "_system" / "world_time.json").exists()
    assert (root / "_system" / "raw" / "sessions" / "S001" / "metadata.json").is_file()
    assert scripted.request_count == 0

    material_before = _preserved_map(root)

    # 1. Real dnd init on pre-existing campaign material.
    init_result = _runner.invoke(cli_app, ["init", "--vault", str(root)])
    assert init_result.exit_code == 0, init_result.output
    assert (root / "_system" / "campaign.yaml").is_file()
    assert _preserved_map(root) == material_before

    # 2. Real dnd time init (initialize-once admin path).
    time_result = _runner.invoke(
        cli_app,
        ["time", "init", "--vault", str(root), "--world-tick", str(_WORLD_TICK)],
    )
    assert time_result.exit_code == 0, time_result.output
    assert scripted.request_count == 0

    # 3. First fresh finalize -> PENDING_CHANGESET through the real runtime.
    canonical_pre_finalize = _entity_map(root)
    first_batch_count = _batch_count(root)
    assert first_batch_count >= 1
    scripted.queue([_proposal_response] + [_empty_response] * (first_batch_count - 1))
    first = _finalize_and_patch(root, config, scripted, monkeypatch)

    assert first.status is BootstrapCompletionStatus.PENDING_CHANGESET
    assert first.mapping_outcome is BootstrapMappingOutcome.PROPOSAL
    assert first.changeset_id is not None
    assert first.coverage_complete is True
    assert scripted.request_count == first_batch_count
    assert _entity_map(root) == canonical_pre_finalize
    assert len(_proposal_files(root)) == 1
    assert (root / "_system" / "bootstrap" / f"{first.changeset_id}.mapping.json").is_file()
    assert not (root / "State" / ".campaign-state-manifest.json").exists()
    assert not list((root / "_system" / "indexes").glob("*.sqlite*"))

    changeset_id = first.changeset_id

    # 4. Review of the persisted proposal + immutable evidence.
    review = compose_bootstrap_review(root, changeset_id)
    assert review.bundle.review_state is BootstrapReviewState.REVIEWABLE
    assert review.bundle.changeset_review is not None
    assert review.readiness.readiness is BootstrapApplyReadiness.READY
    assert review.bundle.fingerprint == compute_changeset_fingerprint(review.bundle.changeset)
    assert scripted.request_count == first_batch_count

    # 5. Explicit content-bound approval through the accepted persistence path.
    proposal = review.bundle.changeset
    proposal_fingerprint = compute_changeset_fingerprint(proposal)
    approval_run = compose_bootstrap_approval(root, changeset_id, acknowledge_unresolved=False)
    assert approval_run.readiness.readiness is BootstrapApplyReadiness.READY

    store = compose_bootstrap_context(root).changeset_store
    approval = ChangeSetApproval(
        changeset_id=changeset_id,
        fingerprint=proposal_fingerprint,
        decision=ReviewDecision.APPROVED,
        reviewer="dm",
    )
    assert approval.decision is ReviewDecision.APPROVED
    assert approval.fingerprint == proposal_fingerprint
    assert persist_approval(store, approval) is ApprovalPersistOutcome.CREATED
    loaded = load_approval(store, changeset_id)
    assert loaded == approval
    assert loaded.decision is ReviewDecision.APPROVED
    assert loaded.fingerprint == compute_changeset_fingerprint(proposal)
    assert scripted.request_count == first_batch_count

    # 6. Canonical apply through the real bootstrap/Stage-10 path.
    apply_run = compose_bootstrap_apply(root, changeset_id, acknowledge_unresolved=False)
    assert apply_run.readiness is BootstrapApplyReadiness.READY
    assert apply_run.apply_result is not None
    assert apply_run.apply_result.outcome is ChangeSetApplyOutcome.APPLIED
    assert apply_run.attempt_recorded is True
    assert apply_run.attempt_error is None
    assert scripted.request_count == first_batch_count

    operations = tuple(op for op in proposal.operations if isinstance(op, CreateEntityOperation))
    assert len(operations) == 1
    create_op = operations[0]

    # Primary apply proof: the resulting canonical entity through the real
    # VaultRepository read/list contract (not an assumed filename).
    repository = _repository(root)
    document = repository.get_entity(create_op.entity_id)
    assert document.entity.id == create_op.entity_id
    assert document.entity.type is create_op.type
    assert document.entity.name == create_op.name == _PROPOSAL_NAME
    assert document.entity.status == "unknown"
    assert document.entity.visibility is Visibility.DM
    assert document.entity.knowledge_status is KnowledgeStatus.INFERRED
    listed_ids = {doc.entity.id for doc in repository.list_entities(create_op.type)}
    assert create_op.entity_id in listed_ids

    audit_sources = [
        record.source
        for record in AuditService(str(root / "_system" / "audit" / "audit.jsonl")).read_all()
    ]
    assert "bootstrap_apply" in audit_sources
    assert (root / "_system" / "changesets" / f"{changeset_id}.apply.jsonl").is_file()

    canonical_after_apply = _entity_map(root)
    assert canonical_after_apply != canonical_pre_finalize

    # 7. Second fresh finalize -> NO_CHANGES / COMPLETE via a real rediscovery.
    second_batch_count = _batch_count(root)
    assert second_batch_count >= 1
    scripted.queue([_empty_response] * second_batch_count)
    second = _finalize_and_patch(root, config, scripted, monkeypatch)

    assert second.mapping_outcome is BootstrapMappingOutcome.NO_CHANGES
    assert second.status is BootstrapCompletionStatus.COMPLETE
    assert second.completed is True
    assert second.changeset_id is None
    assert scripted.request_count == first_batch_count + second_batch_count
    assert second.final_source_stable is True
    assert len(_proposal_files(root)) == 1
    assert _entity_map(root) == canonical_after_apply

    # 8. Derived readiness: Campaign State CURRENT and FTS fresh/verified.
    assert second.campaign_state_status is CampaignStateStatus.CURRENT
    assert compose_campaign_state_capability(root).inspect().status is CampaignStateStatus.CURRENT
    assert second.fts_verified is True
    verify_fts_index(root)

    # 9. Historical raw session material passes the real recovery preflight.
    assert compose_recovery_service(root).inspect_runtime_partition().blocking == ()

    # 10. The tracked golden fixture was never mutated.
    assert _hash_tree(GOLDEN_VAULT) == golden_before
