"""S13-05 bootstrap completion policy unit tests (pure, no filesystem)."""

from __future__ import annotations

from dnd_assistant.application.bootstrap_completion import (
    BootstrapClosureInput,
    BootstrapCompletionResult,
    BootstrapCompletionStatus,
    classify_bootstrap_closure,
)
from dnd_assistant.application.bootstrap_result import BootstrapMappingOutcome


def _closure(
    *,
    outcome: BootstrapMappingOutcome = BootstrapMappingOutcome.NO_CHANGES,
    coverage_complete: bool = True,
    unresolved_count: int = 0,
    proposal_persisted: bool = False,
    evidence_persistence_failed: bool = False,
    changeset_id: str | None = None,
) -> BootstrapClosureInput:
    return BootstrapClosureInput(
        outcome=outcome,
        coverage_complete=coverage_complete,
        unresolved_count=unresolved_count,
        proposal_persisted=proposal_persisted,
        evidence_persistence_failed=evidence_persistence_failed,
        changeset_id=changeset_id,
    )


def test_incomplete_coverage_is_never_acknowledgeable() -> None:
    closure = _closure(
        coverage_complete=False,
        unresolved_count=3,
        outcome=BootstrapMappingOutcome.NO_CHANGES,
    )
    assert (
        classify_bootstrap_closure(closure, acknowledge_unresolved=True)
        is BootstrapCompletionStatus.CANONICAL_COVERAGE_INCOMPLETE
    )
    assert (
        classify_bootstrap_closure(closure, acknowledge_unresolved=False)
        is BootstrapCompletionStatus.CANONICAL_COVERAGE_INCOMPLETE
    )


def test_evidence_persistence_failure_blocks_after_stable_source() -> None:
    closure = _closure(evidence_persistence_failed=True)
    assert (
        classify_bootstrap_closure(closure, acknowledge_unresolved=True)
        is BootstrapCompletionStatus.EVIDENCE_PERSISTENCE_FAILED
    )


def test_proposal_requires_review_apply() -> None:
    closure = _closure(
        outcome=BootstrapMappingOutcome.PROPOSAL,
        proposal_persisted=True,
        changeset_id="cs_bootstrap_x",
    )
    assert (
        classify_bootstrap_closure(closure, acknowledge_unresolved=True)
        is BootstrapCompletionStatus.PENDING_CHANGESET
    )


def test_unresolved_requires_acknowledgement() -> None:
    closure = _closure(unresolved_count=2)
    assert (
        classify_bootstrap_closure(closure, acknowledge_unresolved=False)
        is BootstrapCompletionStatus.UNRESOLVED_NOT_ACKNOWLEDGED
    )
    assert classify_bootstrap_closure(closure, acknowledge_unresolved=True) is None


def test_clean_no_changes_proceeds() -> None:
    assert classify_bootstrap_closure(_closure(), acknowledge_unresolved=False) is None


def test_is_completed_only_for_two_outcomes() -> None:
    assert BootstrapCompletionStatus.COMPLETE.is_completed
    assert BootstrapCompletionStatus.COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED.is_completed
    for status in BootstrapCompletionStatus:
        if status not in (
            BootstrapCompletionStatus.COMPLETE,
            BootstrapCompletionStatus.COMPLETE_WITH_ACKNOWLEDGED_UNRESOLVED,
        ):
            assert not status.is_completed, status


def test_result_completed_property() -> None:
    assert BootstrapCompletionResult(BootstrapCompletionStatus.COMPLETE).completed
    assert not BootstrapCompletionResult(BootstrapCompletionStatus.PENDING_CHANGESET).completed
