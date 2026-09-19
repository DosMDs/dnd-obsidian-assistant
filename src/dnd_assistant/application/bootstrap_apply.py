"""S13-04 bootstrap apply orchestration over existing Stage-10 services.

Composes the trusted bootstrap readiness gate with the unmodified Stage-10
applier, applicability gate and append-only apply-attempt ledger.  It contains
no second entity applier and no bootstrap-specific retry path: once the bootstrap
gates pass, the canonical mutation is performed entirely by
``apply_changeset`` through the ``VaultRepository``.

Audit semantics: the trusted apply actor is the distinct string
``bootstrap_apply``; the proposal's ``Provenance.BOOTSTRAP`` is unrelated and is
preserved verbatim on the ChangeSet.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, a concrete
    storage implementation (only protocols under ``TYPE_CHECKING``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from dnd_assistant.application.bootstrap_canonical import (
    CanonicalCoverage,
    CanonicalStateSnapshot,
)
from dnd_assistant.application.bootstrap_evidence import BootstrapEvidenceRecord
from dnd_assistant.application.bootstrap_evidence_validation import BootstrapEvidenceIssue
from dnd_assistant.application.bootstrap_input import BootstrapInputProjection
from dnd_assistant.application.bootstrap_readiness import (
    BootstrapApplyReadiness,
    BootstrapReadinessResult,
    StrictRepositoryProbe,
    assess_bootstrap_apply_readiness,
)
from dnd_assistant.application.changeset_apply import (
    ChangeSetApplyContext,
    ChangeSetApplyResult,
    apply_changeset,
)
from dnd_assistant.application.changeset_review import ChangeSetApproval
from dnd_assistant.application.changeset_status import (
    assert_changeset_applicable,
    load_apply_attempts,
    record_apply_attempt,
)
from dnd_assistant.domain.changeset import ChangeSet
from dnd_assistant.errors import ConflictError, StorageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dnd_assistant.storage.audit import AuditRecord
    from dnd_assistant.storage.changeset_store import ChangeSetStore
    from dnd_assistant.storage.types import VaultRepository

BOOTSTRAP_APPLY_SOURCE: str = "bootstrap_apply"
"""Trusted audit source for a canonical bootstrap apply."""


@dataclass(frozen=True, slots=True)
class BootstrapApplyResult:
    """Outcome of one bootstrap apply attempt.

    ``apply_result`` is present only when the readiness gate passed and the
    Stage-10 applier was invoked; otherwise the typed ``readiness`` explains why
    the proposal was not applied and no canonical mutation occurred.
    """

    readiness: BootstrapApplyReadiness
    detail: str | None = None
    issues: tuple[BootstrapEvidenceIssue, ...] = ()
    apply_result: ChangeSetApplyResult | None = None
    attempt_recorded: bool = False
    attempt_error: str | None = None


def apply_bootstrap_changeset(
    changeset: ChangeSet,
    *,
    store: ChangeSetStore,
    approval: ChangeSetApproval | None,
    evidence_record: BootstrapEvidenceRecord | None,
    evidence_present: bool,
    projection: BootstrapInputProjection,
    coverage: CanonicalCoverage,
    snapshot: CanonicalStateSnapshot,
    strict_probe: StrictRepositoryProbe,
    acknowledge_unresolved: bool,
    audit_records: Sequence[AuditRecord],
    context: ChangeSetApplyContext,
) -> BootstrapApplyResult:
    """Run the bootstrap gates and, when ready, the existing Stage-10 applier.

    The bootstrap-specific checks and the Stage-10 applicability gate all run
    before ``apply_changeset`` performs its own fresh strict preflight and the
    first write.  A readiness failure returns a typed result with zero writes; a
    refused applicability gate returns ``NOT_APPLICABLE`` with zero writes.
    """
    readiness: BootstrapReadinessResult = assess_bootstrap_apply_readiness(
        changeset,
        evidence_record=evidence_record,
        evidence_present=evidence_present,
        projection=projection,
        coverage=coverage,
        snapshot=snapshot,
        strict_probe=strict_probe,
        approval=approval,
        acknowledge_unresolved=acknowledge_unresolved,
    )
    if readiness.readiness is not BootstrapApplyReadiness.READY:
        return BootstrapApplyResult(
            readiness=readiness.readiness,
            detail=readiness.detail,
            issues=readiness.issues,
        )

    assert approval is not None  # guaranteed by the readiness gate
    repository = strict_probe.repository
    assert repository is not None  # guaranteed by the readiness gate

    attempts = load_apply_attempts(store, changeset.changeset_id)
    try:
        assert_changeset_applicable(changeset, attempts, audit_records)
    except ConflictError as exc:
        return BootstrapApplyResult(
            readiness=BootstrapApplyReadiness.NOT_APPLICABLE,
            detail=str(exc),
        )

    result = apply_changeset(
        changeset,
        approval,
        cast("VaultRepository", repository),
        context=context,
    )

    attempt_error: str | None = None
    attempt_recorded = False
    try:
        record_apply_attempt(
            store,
            changeset,
            result,
            source=context.source,
            real_time=context.real_time,
        )
        attempt_recorded = True
    except (StorageError, ConflictError) as exc:
        attempt_error = str(exc)

    return BootstrapApplyResult(
        readiness=BootstrapApplyReadiness.READY,
        apply_result=result,
        attempt_recorded=attempt_recorded,
        attempt_error=attempt_error,
    )


__all__ = [
    "BOOTSTRAP_APPLY_SOURCE",
    "BootstrapApplyResult",
    "apply_bootstrap_changeset",
]
