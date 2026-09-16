"""S11-06 durable post-session processing orchestrator.

Composes the accepted S11-01..S11-05 stages and the S11-06 persistence/claim/
integrity layers into one crash-aware workflow.  The service is bounded and
injected: it is not an agent, owns no filesystem/CLI/concrete-storage
dependency and never calls ``ToolExecutor``.

Safety-critical ordering:

    structural eligibility (no terminal gate)
    -> deterministic prepared-input assembly + fingerprint
    -> structural fold of the attempt's ledger history
    -> terminal/interrupted routing (no model work)
    -> atomic per-attempt claim
    -> durable AttemptStarted + re-fold verification
    -> first model call (extraction, then rendering)
    -> immutable artifact persistence + ledger events
    -> Stage-10 proposal persistence (if produced)
    -> terminal AttemptCompleted / AttemptFailed

A caught post-start failure records exactly one bounded ``AttemptFailed``.  If
that recording itself fails (:class:`PostSessionFailureRecordingError`) the
processor never claims a durable terminal failure.  A same-attempt terminal
retry returns idempotently with zero model calls after current-input and
durable-evidence verification.

Result contracts and durable-state helpers live in
``application.post_session_processor_support``.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, or a
    concrete storage implementation (storage protocols are referenced only
    under ``TYPE_CHECKING``).
"""

from __future__ import annotations

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application.changeset_review import compute_changeset_fingerprint
from dnd_assistant.application.changeset_store import (
    load_proposal,
    persist_proposal,
)
from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    AttemptStateConflictError,
    fold_attempt_state,
)
from dnd_assistant.application.post_session_changeset import (
    PostSessionChangeError,
    PostSessionChangeOutcome,
    produce_post_session_changeset,
)
from dnd_assistant.application.post_session_clock import PostSessionClock, system_utc_now
from dnd_assistant.application.post_session_context import (
    PostSessionContextError,
    build_post_session_input,
)
from dnd_assistant.application.post_session_eligibility import (
    evaluate_processing_eligibility,
)
from dnd_assistant.application.post_session_extraction import (
    ModelExecutionIdentity,
    PostSessionExtractionError,
    run_post_session_extraction,
)
from dnd_assistant.application.post_session_integrity import (
    verify_terminal_integrity,
)
from dnd_assistant.application.post_session_ledger import (
    load_ledger_events,
    new_ledger_event_id,
    record_ledger_event,
)
from dnd_assistant.application.post_session_persistence import (
    PostSessionPersistenceError,
    artifact_content_hash,
    build_workflow_evidence,
    persist_immutable_artifact,
    recap_artifact_text,
    serialize_workflow_evidence,
    summary_artifact_text,
)
from dnd_assistant.application.post_session_processor_support import (
    PostSessionFailureRecordingError,
    PostSessionProcessorDeps,
    PostSessionProcessorResult,
    PostSessionProcessorStatus,
    append_artifact_event,
    append_terminal,
    failed_result,
    interrupted_result,
    record_failure,
    result_from_terminal,
)
from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    generate_recap,
    generate_summary,
)
from dnd_assistant.domain.post_session import (
    AttemptCompleted,
    AttemptStarted,
    FailureCategory,
    PersistedArtifactKind,
    PostSessionAttemptId,
    ProcessingOutcome,
    ProcessingPhase,
    ProposalPersisted,
    Sha256Fingerprint,
)
from dnd_assistant.errors import ConflictError, StorageError

__all__ = [
    "PostSessionFailureRecordingError",
    "PostSessionProcessorDeps",
    "PostSessionProcessorResult",
    "PostSessionProcessorStatus",
    "run_post_session_processing",
]

_ATTEMPT_ID_ADAPTER: TypeAdapter[PostSessionAttemptId] = TypeAdapter(PostSessionAttemptId)


def run_post_session_processing(
    deps: PostSessionProcessorDeps,
    session_id: str,
    attempt_id: str,
    *,
    model_identity: ModelExecutionIdentity | None = None,
    clock: PostSessionClock = system_utc_now,
) -> PostSessionProcessorResult:
    """Run the durable post-session processing workflow for one attempt."""
    try:
        validated_attempt_id = _ATTEMPT_ID_ADAPTER.validate_python(attempt_id)
    except PydanticValidationError:
        return failed_result(session_id, attempt_id, "invalid_attempt_id")

    # 1. Structural eligibility (never gated on terminal attempt state).
    try:
        eligibility = evaluate_processing_eligibility(
            deps.metadata_repo, deps.event_repo, deps.processing_store, session_id
        )
    except StorageError:
        return failed_result(session_id, validated_attempt_id, "ledger_unreadable")
    if not eligibility.eligible:
        return PostSessionProcessorResult(
            status=PostSessionProcessorStatus.INELIGIBLE,
            session_id=session_id,
            attempt_id=validated_attempt_id,
            reason=eligibility.reason.value,
        )

    # 2. Deterministic prepared-input assembly.
    try:
        prepared = build_post_session_input(
            metadata_repo=deps.metadata_repo,
            event_repo=deps.event_repo,
            vault_repo=deps.vault_repo,
            session_id=session_id,
            eligibility=eligibility,
        )
    except PostSessionContextError as exc:
        return failed_result(session_id, validated_attempt_id, exc.reason.value)
    except StorageError:
        return failed_result(session_id, validated_attempt_id, "storage_error")

    # 3. Structural fold (terminal/interrupted routing, no model work).
    try:
        events = load_ledger_events(deps.processing_store, session_id)
        fold = fold_attempt_state(events, validated_attempt_id)
    except AttemptStateConflictError as exc:
        return failed_result(
            session_id, validated_attempt_id, f"ledger_conflict:{exc.reason.value}"
        )
    except StorageError:
        return failed_result(session_id, validated_attempt_id, "ledger_unreadable")

    current_fingerprint = prepared.fingerprint

    if fold.state is AttemptState.COMPLETED:
        if (
            fold.started is None
            or fold.started.input_fingerprint.digest != current_fingerprint.digest
        ):
            return failed_result(session_id, validated_attempt_id, "fingerprint_mismatch")
        integrity = verify_terminal_integrity(
            fold,
            session_id,
            artifact_store=deps.artifact_store,
            changeset_store=deps.changeset_store,
        )
        if not integrity.ok:
            return failed_result(
                session_id,
                validated_attempt_id,
                f"terminal_evidence:{integrity.reason.value if integrity.reason else 'unknown'}",
                input_fingerprint=current_fingerprint,
            )
        return result_from_terminal(
            fold,
            session_id,
            PostSessionProcessorStatus.ALREADY_TERMINAL,
            artifact_store=deps.artifact_store,
        )

    if fold.state is AttemptState.FAILED:
        if (
            fold.started is None
            or fold.started.input_fingerprint.digest != current_fingerprint.digest
        ):
            return failed_result(session_id, validated_attempt_id, "fingerprint_mismatch")
        return result_from_terminal(
            fold,
            session_id,
            PostSessionProcessorStatus.FAILED,
            artifact_store=deps.artifact_store,
        )

    if fold.state is AttemptState.SUPERSEDED:
        return interrupted_result(session_id, validated_attempt_id, "attempt_superseded")

    if fold.state is AttemptState.STARTED:
        return interrupted_result(
            session_id, validated_attempt_id, "attempt_interrupted", current_fingerprint
        )

    # 4. NOT_STARTED: atomic per-attempt claim before any start/model work.
    try:
        claimed = deps.artifact_store.claim_attempt(session_id, validated_attempt_id)
    except StorageError:
        return failed_result(session_id, validated_attempt_id, "claim_failed")
    if not claimed:
        return interrupted_result(
            session_id, validated_attempt_id, "attempt_claim_exists", current_fingerprint
        )

    started_event = AttemptStarted(
        event_id=new_ledger_event_id(),
        attempt_id=validated_attempt_id,
        session_ref=session_id,
        real_time=clock(),
        input_fingerprint=current_fingerprint,
        processor_version=prepared.identity.processor_version,
        prompt_version=prepared.identity.prompt_version,
        model_profile=model_identity.profile if model_identity is not None else None,
    )
    try:
        record_ledger_event(deps.processing_store, session_id, started_event)
        events = load_ledger_events(deps.processing_store, session_id)
        fold = fold_attempt_state(events, validated_attempt_id)
    except (StorageError, AttemptStateConflictError):
        return interrupted_result(
            session_id, validated_attempt_id, "attempt_start_uncertain", current_fingerprint
        )
    if (
        fold.state is not AttemptState.STARTED
        or fold.started is None
        or fold.started.event_id != started_event.event_id
    ):
        return interrupted_result(
            session_id, validated_attempt_id, "attempt_claim_race", current_fingerprint
        )

    # 5. Extraction.
    try:
        accepted = run_post_session_extraction(
            deps.extraction_model, prepared, model_identity=model_identity
        )
    except PostSessionExtractionError as exc:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.EXTRACTION,
            exc.to_failure_category(),
            f"Post-session extraction failed: {exc.reason.value}",
            clock,
        )
    except Exception:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.EXTRACTION,
            FailureCategory.INTERNAL_ERROR,
            "Internal processing error",
            clock,
        )

    # 6. ChangeSet production.
    try:
        plan = produce_post_session_changeset(
            prepared, accepted, attempt_id=validated_attempt_id, repository=deps.vault_repo
        )
    except PostSessionChangeError as exc:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.VALIDATION,
            exc.to_failure_category(),
            f"Post-session ChangeSet production failed: {exc.reason.value}",
            clock,
        )
    except StorageError:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.VALIDATION,
            FailureCategory.STORAGE_ERROR,
            "Processing storage failure",
            clock,
        )
    except Exception:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.VALIDATION,
            FailureCategory.INTERNAL_ERROR,
            "Internal processing error",
            clock,
        )

    # 7. Rendering.
    try:
        summary = generate_summary(
            deps.rendering_model, prepared, accepted, model_identity=model_identity
        )
        recap = generate_recap(
            deps.rendering_model, prepared, accepted, model_identity=model_identity
        )
    except PostSessionRenderingError as exc:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.RENDERING,
            exc.to_failure_category(),
            f"Post-session rendering failed: {exc.reason.value}",
            clock,
        )
    except Exception:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.RENDERING,
            FailureCategory.INTERNAL_ERROR,
            "Internal processing error",
            clock,
        )

    # 8. Immutable artifact persistence.
    try:
        summary_text = summary_artifact_text(summary)
        _, summary_path = persist_immutable_artifact(
            deps.artifact_store,
            session_id,
            validated_attempt_id,
            PersistedArtifactKind.SUMMARY,
            summary_text,
        )
        append_artifact_event(
            deps,
            session_id,
            validated_attempt_id,
            PersistedArtifactKind.SUMMARY,
            summary_path,
            artifact_content_hash(summary_text),
            clock,
        )

        recap_text = recap_artifact_text(recap)
        _, recap_path = persist_immutable_artifact(
            deps.artifact_store,
            session_id,
            validated_attempt_id,
            PersistedArtifactKind.RECAP,
            recap_text,
        )
        append_artifact_event(
            deps,
            session_id,
            validated_attempt_id,
            PersistedArtifactKind.RECAP,
            recap_path,
            artifact_content_hash(recap_text),
            clock,
        )

        evidence = build_workflow_evidence(prepared, accepted, summary, recap, plan)
        workflow_text = serialize_workflow_evidence(evidence)
        _, workflow_path = persist_immutable_artifact(
            deps.artifact_store,
            session_id,
            validated_attempt_id,
            PersistedArtifactKind.WORKFLOW,
            workflow_text,
        )
        append_artifact_event(
            deps,
            session_id,
            validated_attempt_id,
            PersistedArtifactKind.WORKFLOW,
            workflow_path,
            artifact_content_hash(workflow_text),
            clock,
        )
    except ConflictError:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.PERSISTENCE,
            FailureCategory.ARTIFACT_CONFLICT,
            "Artifact persistence failed",
            clock,
        )
    except PostSessionPersistenceError as exc:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.PERSISTENCE,
            FailureCategory.INTERNAL_ERROR,
            f"Workflow evidence invalid: {exc.reason.value}",
            clock,
        )
    except StorageError:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.PERSISTENCE,
            FailureCategory.STORAGE_ERROR,
            "Processing storage failure",
            clock,
        )
    except Exception:
        return record_failure(
            deps,
            session_id,
            validated_attempt_id,
            ProcessingPhase.PERSISTENCE,
            FailureCategory.INTERNAL_ERROR,
            "Internal processing error",
            clock,
        )

    # 9. Stage-10 proposal persistence (if produced).
    if plan.outcome is PostSessionChangeOutcome.PROPOSAL:
        if plan.changeset is None or plan.changeset_fingerprint is None:
            return record_failure(
                deps,
                session_id,
                validated_attempt_id,
                ProcessingPhase.PERSISTENCE,
                FailureCategory.INTERNAL_ERROR,
                "Internal processing error",
                clock,
            )
        try:
            persist_proposal(deps.changeset_store, plan.changeset)
            loaded = load_proposal(deps.changeset_store, plan.changeset.changeset_id)
            if (
                loaded.changeset_id != plan.changeset.changeset_id
                or compute_changeset_fingerprint(loaded).digest != plan.changeset_fingerprint.digest
            ):
                return record_failure(
                    deps,
                    session_id,
                    validated_attempt_id,
                    ProcessingPhase.PERSISTENCE,
                    FailureCategory.PROPOSAL_CONFLICT,
                    "ChangeSet proposal conflict",
                    clock,
                )
            record_ledger_event(
                deps.processing_store,
                session_id,
                ProposalPersisted(
                    event_id=new_ledger_event_id(),
                    attempt_id=validated_attempt_id,
                    session_ref=session_id,
                    real_time=clock(),
                    changeset_id=plan.changeset.changeset_id,
                    changeset_fingerprint=Sha256Fingerprint(
                        digest=plan.changeset_fingerprint.digest
                    ),
                ),
            )
        except ConflictError:
            return record_failure(
                deps,
                session_id,
                validated_attempt_id,
                ProcessingPhase.PERSISTENCE,
                FailureCategory.PROPOSAL_CONFLICT,
                "ChangeSet proposal conflict",
                clock,
            )
        except StorageError:
            return record_failure(
                deps,
                session_id,
                validated_attempt_id,
                ProcessingPhase.PERSISTENCE,
                FailureCategory.STORAGE_ERROR,
                "Processing storage failure",
                clock,
            )
        except Exception:
            return record_failure(
                deps,
                session_id,
                validated_attempt_id,
                ProcessingPhase.PERSISTENCE,
                FailureCategory.INTERNAL_ERROR,
                "Internal processing error",
                clock,
            )

    # 10. Terminal success — only after every required durable output verifies.
    outcome = (
        ProcessingOutcome.PRODUCED
        if plan.outcome is PostSessionChangeOutcome.PROPOSAL
        else ProcessingOutcome.NO_CHANGES
    )
    completed_event = AttemptCompleted(
        event_id=new_ledger_event_id(),
        attempt_id=validated_attempt_id,
        session_ref=session_id,
        real_time=clock(),
        outcome=outcome,
    )
    if not append_terminal(deps, session_id, completed_event):
        return failed_result(
            session_id,
            validated_attempt_id,
            "terminal_append_uncertain",
            input_fingerprint=current_fingerprint,
        )

    try:
        events = load_ledger_events(deps.processing_store, session_id)
        fold = fold_attempt_state(events, validated_attempt_id)
    except (StorageError, AttemptStateConflictError):
        return interrupted_result(session_id, validated_attempt_id, "terminal_reload_failed")

    return result_from_terminal(
        fold,
        session_id,
        PostSessionProcessorStatus.COMPLETED,
        artifact_store=deps.artifact_store,
    )
