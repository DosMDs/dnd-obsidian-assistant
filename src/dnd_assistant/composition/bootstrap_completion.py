"""S13-05 bootstrap finalization composition.

Owns the concrete, ordered finalization pipeline:

``recovery preflight -> initialized/strict canonical validation -> world-time and
active-session prerequisites -> fresh S13-02 discovery -> fresh S13-03 mapping +
persistence -> immediate source-stability recheck -> closure classification ->
Campaign State rebuild -> FTS rebuild -> post-rebuild verification -> final
source-stability check``.

It reuses the accepted S13-02 discovery, the accepted S13-03 mapping/persistence
runtime (with its single model call), the accepted Campaign State materializer and
the shared FTS composition unchanged.  It performs no canonical mutation: the
only canonical write in S13-05 is the separate ``dnd time init`` command.

It contains no Russian text and no ``typer``/``textual`` types.

This module is a composition layer and may import concrete storage.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from dnd_assistant.application.bootstrap_changeset import BootstrapChangeError
from dnd_assistant.application.bootstrap_completion import (
    BootstrapClosureInput,
    BootstrapCompletionResult,
    BootstrapCompletionStatus,
    classify_bootstrap_closure,
)
from dnd_assistant.application.bootstrap_extraction import BootstrapExtractionError
from dnd_assistant.application.bootstrap_input import prepare_bootstrap_input
from dnd_assistant.application.campaign_state_consumer import (
    FAST_AGENT_RECENT_SESSION_LIMIT,
)
from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateSourceChangedError,
    CampaignStateStatus,
    inspect_campaign_state,
    rebuild_campaign_state,
)
from dnd_assistant.application.vault_discovery import VaultDiscoveryReport
from dnd_assistant.composition.bootstrap import (
    BootstrapRuntimeResult,
    compose_bootstrap_discovery,
    compose_bootstrap_runtime,
)
from dnd_assistant.composition.index_rebuild import rebuild_fts_index, verify_fts_index
from dnd_assistant.composition.session_runtime import compose_recovery_service
from dnd_assistant.errors import ConflictError, DndAssistantError, StorageError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.derived_state import ObsidianDerivedStateStore
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from dnd_assistant.models.profiles import ModelProfile

__all__ = ["finalize_bootstrap"]

_CAMPAIGN_MARKER = Path("_system") / "campaign.yaml"


@dataclass(frozen=True, slots=True)
class _VaultContext:
    audit_service: AuditService
    repository: ObsidianVaultRepository
    session_repository: ObsidianSessionMetadataRepository
    world_time_repository: ObsidianWorldTimeRepository
    derived_state_store: ObsidianDerivedStateStore


def _result(
    status: BootstrapCompletionStatus,
    *,
    campaign_id: str | None = None,
    detail: str | None = None,
    current_world_tick: int | None = None,
    active_session_id: str | None = None,
    canonical_documents: int | None = None,
) -> BootstrapCompletionResult:
    return BootstrapCompletionResult(
        status=status,
        campaign_id=campaign_id,
        detail=detail,
        current_world_tick=current_world_tick,
        active_session_id=active_session_id,
        canonical_documents=canonical_documents,
    )


def _compose_context(vault_root: Path) -> _VaultContext:
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    repository = ObsidianVaultRepository(vault_root=str(vault_root), audit_service=audit_service)
    return _VaultContext(
        audit_service=audit_service,
        repository=repository,
        session_repository=ObsidianSessionMetadataRepository(vault_root, audit_service),
        world_time_repository=ObsidianWorldTimeRepository(vault_root, audit_service),
        derived_state_store=ObsidianDerivedStateStore(vault_root),
    )


def _fresh_fingerprint(vault_root: Path):
    report = compose_bootstrap_discovery(vault_root)
    return prepare_bootstrap_input(report).input_fingerprint


def _recovery_blocked(vault_root: Path) -> str | None:
    """Return a blocking detail, or ``None`` when the runtime is recoverable."""
    try:
        partition = compose_recovery_service(vault_root).inspect_runtime_partition()
    except DndAssistantError as exc:
        return f"Recovery inspection failed: {exc}"
    if partition.blocking:
        codes = "; ".join(
            f"[{issue.code}] {issue.detail or ''}".strip() for issue in partition.blocking
        )
        return f"Blocking recovery issues: {codes}"
    return None


def _base_result(
    *,
    campaign_id: str,
    closure_fingerprint,
    run,
    documents,
    current_world_tick: int,
) -> BootstrapCompletionResult:
    changeset_id = run.result.changeset.changeset_id if run.result.changeset else None
    return BootstrapCompletionResult(
        status=BootstrapCompletionStatus.COMPLETE,
        campaign_id=campaign_id,
        completion_fingerprint=closure_fingerprint,
        mapping_outcome=run.result.outcome,
        changeset_id=changeset_id,
        coverage_complete=run.coverage.complete,
        unresolved_count=len(run.result.unresolved),
        canonical_documents=len(documents),
        current_world_tick=current_world_tick,
    )


def _persistence_failure(runtime_result: BootstrapRuntimeResult) -> str | None:
    if runtime_result.evidence_error is None:
        return None
    return f"Bootstrap evidence persistence failed: {runtime_result.evidence_error}"


def finalize_bootstrap(
    *,
    vault_root: Path,
    config_path: Path,
    profile_name: str,
    acknowledge_unresolved: bool = False,
    model_factory: Callable[[ModelProfile], Model] | None = None,
) -> BootstrapCompletionResult:
    """Run the deterministic, fail-closed bootstrap finalization pipeline.

    No canonical campaign mutation occurs.  All derived writes are disposable;
    already-published derived artifacts are never rolled back.  A source-stability
    failure is reported as ``SOURCE_CHANGED_DURING_VALIDATION`` and tells the user
    to rerun finalization; no retry loop is performed.
    """
    if not vault_root.is_dir():
        return _result(
            BootstrapCompletionStatus.UNINITIALIZED_VAULT,
            detail="Vault root does not exist",
        )
    if not (vault_root / _CAMPAIGN_MARKER).is_file():
        return _result(
            BootstrapCompletionStatus.UNINITIALIZED_VAULT,
            detail="Vault is not initialized: _system/campaign.yaml is absent",
        )

    try:
        context = _compose_context(vault_root)
    except DndAssistantError as exc:
        return _result(BootstrapCompletionStatus.CANONICAL_NOT_READY, detail=str(exc))

    recovery_detail = _recovery_blocked(vault_root)
    if recovery_detail is not None:
        return _result(BootstrapCompletionStatus.RECOVERY_BLOCKED, detail=recovery_detail)

    try:
        report: VaultDiscoveryReport = compose_bootstrap_discovery(vault_root)
        documents = context.repository.list_entities()
    except (StorageError, ConflictError) as exc:
        return _result(BootstrapCompletionStatus.CANONICAL_NOT_READY, detail=str(exc))
    except DndAssistantError as exc:
        return _result(BootstrapCompletionStatus.CANONICAL_NOT_READY, detail=str(exc))

    campaign_id = report.campaign_id

    try:
        current_world_time = context.world_time_repository.get_current_world_time()
    except (ConflictError, StorageError) as exc:
        return _result(
            BootstrapCompletionStatus.WORLD_TIME_INVALID,
            campaign_id=campaign_id,
            detail=str(exc),
        )
    except DndAssistantError as exc:
        return _result(
            BootstrapCompletionStatus.WORLD_TIME_UNINITIALIZED,
            campaign_id=campaign_id,
            detail=str(exc),
        )

    try:
        active_session = context.session_repository.get_active_session()
    except ConflictError as exc:
        return _result(
            BootstrapCompletionStatus.RECOVERY_BLOCKED,
            campaign_id=campaign_id,
            detail=str(exc),
        )
    except (StorageError, DndAssistantError) as exc:
        return _result(
            BootstrapCompletionStatus.CANONICAL_NOT_READY,
            campaign_id=campaign_id,
            detail=str(exc),
        )

    if active_session is not None:
        return _result(
            BootstrapCompletionStatus.ACTIVE_SESSION_PRESENT,
            campaign_id=campaign_id,
            active_session_id=active_session.session.id,
            current_world_tick=current_world_time.current_world_tick,
            canonical_documents=len(documents),
        )

    runtime = None
    try:
        runtime = compose_bootstrap_runtime(
            vault_root=vault_root,
            config_path=config_path,
            profile_name=profile_name,
            model_factory=model_factory,
        )
    except DndAssistantError as exc:
        return _result(
            BootstrapCompletionStatus.MAPPING_FAILED, campaign_id=campaign_id, detail=str(exc)
        )

    try:
        try:
            runtime_result = runtime.run(report, persist=True)
        except (ConflictError, StorageError) as exc:
            return _result(
                BootstrapCompletionStatus.PROPOSAL_PERSISTENCE_FAILED,
                campaign_id=campaign_id,
                detail=str(exc),
            )
        except (BootstrapExtractionError, BootstrapChangeError) as exc:
            return _result(
                BootstrapCompletionStatus.MAPPING_FAILED,
                campaign_id=campaign_id,
                detail=str(exc),
            )
        except DndAssistantError as exc:
            return _result(
                BootstrapCompletionStatus.MAPPING_FAILED,
                campaign_id=campaign_id,
                detail=str(exc),
            )
    finally:
        runtime.close()

    run = runtime_result.run
    persistence_failure = _persistence_failure(runtime_result)
    base = _base_result(
        campaign_id=campaign_id,
        closure_fingerprint=run.projection.input_fingerprint,
        run=run,
        documents=documents,
        current_world_tick=current_world_time.current_world_tick,
    )

    # ── Immediate source-stability recheck (before any terminal mapping status) ──
    try:
        stable_fingerprint = _fresh_fingerprint(vault_root)
    except DndAssistantError as exc:
        issues = (persistence_failure,) if persistence_failure else ()
        return replace(
            base,
            status=BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION,
            detail=f"Source re-validation failed after the model call: {exc}",
            issues=issues,
        )
    if stable_fingerprint != base.completion_fingerprint:
        issues = (persistence_failure,) if persistence_failure else ()
        return replace(
            base,
            status=BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION,
            detail=(
                "Campaign source material changed during the semantic closure assessment; "
                "rerun mapping/finalize"
            ),
            issues=issues,
        )

    closure = BootstrapClosureInput(
        outcome=run.result.outcome,
        coverage_complete=run.coverage.complete,
        unresolved_count=len(run.result.unresolved),
        proposal_persisted=runtime_result.is_proposal,
        evidence_persistence_failed=runtime_result.partial_persistence,
        changeset_id=base.changeset_id,
    )
    blocking = classify_bootstrap_closure(closure, acknowledge_unresolved=acknowledge_unresolved)
    if blocking is not None:
        return replace(base, status=blocking)

    acknowledged = bool(run.result.unresolved) and acknowledge_unresolved
    return _run_derived_phase(
        vault_root=vault_root,
        context=context,
        base=base,
        acknowledged=acknowledged,
        persistence_failure=persistence_failure,
    )


def _run_derived_phase(
    *,
    vault_root: Path,
    context: _VaultContext,
    base: BootstrapCompletionResult,
    acknowledged: bool,
    persistence_failure: str | None,
) -> BootstrapCompletionResult:
    issues: list[str] = []
    if persistence_failure is not None:
        issues.append(persistence_failure)

    cs_failure: str | None = None
    try:
        rebuild_campaign_state(
            vault_repository=context.repository,
            session_repository=context.session_repository,
            world_time_repository=context.world_time_repository,
            derived_state_store=context.derived_state_store,
            recent_session_limit=FAST_AGENT_RECENT_SESSION_LIMIT,
        )
    except CampaignStateSourceChangedError as exc:
        issues.append(f"Campaign State source race: {exc}")
        return replace(
            base,
            status=BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION,
            detail="Canonical sources changed during Campaign State rebuild; FTS was not started",
            campaign_state_status=CampaignStateStatus.STALE,
            issues=tuple(issues),
        )
    except DndAssistantError as exc:
        cs_failure = str(exc)
        issues.append(f"Campaign State rebuild failed: {exc}")

    fts_failure: str | None = None
    fts_rebuilt = False
    try:
        rebuild_fts_index(vault_root)
        fts_rebuilt = True
    except DndAssistantError as exc:
        fts_failure = str(exc)
        issues.append(f"FTS rebuild failed: {exc}")

    cs_status: CampaignStateStatus | None = None
    cs_verify_failure: str | None = None
    if cs_failure is None:
        try:
            inspection = inspect_campaign_state(
                vault_repository=context.repository,
                session_repository=context.session_repository,
                world_time_repository=context.world_time_repository,
                derived_state_store=context.derived_state_store,
                recent_session_limit=FAST_AGENT_RECENT_SESSION_LIMIT,
            )
            cs_status = inspection.status
            if inspection.status is not CampaignStateStatus.CURRENT:
                cs_verify_failure = inspection.detail or f"status={inspection.status.value}"
        except DndAssistantError as exc:
            cs_verify_failure = str(exc)
        if cs_verify_failure is not None:
            issues.append(f"Campaign State verification failed: {cs_verify_failure}")

    fts_verified = False
    fts_verify_failure: str | None = None
    if fts_rebuilt:
        try:
            verify_fts_index(vault_root)
            fts_verified = True
        except DndAssistantError as exc:
            fts_verify_failure = str(exc)
            issues.append(f"FTS verification failed: {exc}")

    final_stable = False
    try:
        final_stable = _fresh_fingerprint(vault_root) == base.completion_fingerprint
    except DndAssistantError as exc:
        issues.append(f"Final source re-validation failed: {exc}")

    if not final_stable:
        issues.append("Semantic source fingerprint changed during finalization")
        status = BootstrapCompletionStatus.SOURCE_CHANGED_DURING_VALIDATION
        detail = "Source material changed after derived rebuild; derived data may be stale"
    elif cs_failure is not None:
        status = BootstrapCompletionStatus.CAMPAIGN_STATE_REBUILD_FAILED
        detail = "Campaign State rebuild did not complete; FTS outcome retained"
    elif fts_failure is not None:
        status = BootstrapCompletionStatus.FTS_REBUILD_FAILED
        detail = "FTS rebuild did not complete; Campaign State retained"
    elif cs_verify_failure is not None or fts_verify_failure is not None:
        status = BootstrapCompletionStatus.DERIVED_VERIFICATION_FAILED
        detail = "Derived projections did not verify as current/fresh"
    elif acknowledged:
        status = BootstrapCompletionStatus.COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED
        detail = "Operational readiness with explicitly acknowledged unresolved diagnostics"
    else:
        status = BootstrapCompletionStatus.COMPLETE
        detail = "Supported bootstrap workflow is cleanly closed and derived data is current"

    return replace(
        base,
        status=status,
        campaign_state_status=cs_status,
        fts_verified=fts_verified,
        final_source_stable=final_stable,
        unresolved_acknowledged=acknowledged,
        detail=detail,
        issues=tuple(issues),
    )
