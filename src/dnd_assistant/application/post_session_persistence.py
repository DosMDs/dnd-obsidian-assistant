"""S11-06 durable post-session artifact persistence policy.

Owns the *meaning* of the bytes persisted for one attempt (everything the
storage layer treats as opaque UTF-8):

- deterministic artifact serialization for Summary/Recap and the machine-readable
  workflow-evidence artifact;
- exact-byte SHA-256 content hashing;
- the durable EMPTY-Recap placeholder;
- the workflow-evidence hard byte ceiling and diagnostic-detail bounding;
- idempotent immutable persistence mapped onto the storage
  ``PostSessionArtifactStore`` protocol.

Artifacts are immutable and per-attempt.  Summary is always a rendered body;
Recap is either a rendered body or the deterministic Python-owned EMPTY
placeholder.  Nothing here performs model work.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, or a
    concrete storage implementation (the storage protocol is referenced only
    under ``TYPE_CHECKING``).
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from dnd_assistant.application.post_session_changeset import (
    PostSessionChangePlanResult,
    PostSessionChangeUnresolved,
    PostSessionOperationProvenance,
)
from dnd_assistant.application.post_session_context import PreparedPostSessionInput
from dnd_assistant.application.post_session_extraction import (
    AcceptedPostSessionExtraction,
)
from dnd_assistant.application.post_session_rendering import (
    RenderedPostSessionArtifact,
)
from dnd_assistant.domain.post_session import (
    PersistedArtifactKind,
    Sha256Fingerprint,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome
from dnd_assistant.domain.post_session_workflow import (
    MAX_WORKFLOW_ARTIFACT_BYTES,
    MAX_WORKFLOW_DIAGNOSTIC_CHARS,
    POST_SESSION_WORKFLOW_SCHEMA_VERSION,
    AttemptWorkflowEvidence,
    ExtractionWorkflowProvenance,
    RenderingWorkflowProvenance,
    WorkflowChangePlan,
    WorkflowOperationProvenance,
    WorkflowUnresolvedDiagnostic,
)

if TYPE_CHECKING:
    from dnd_assistant.storage.post_session_artifacts import PostSessionArtifactStore

EMPTY_RECAP_ARTIFACT_TEXT: Final[str] = (
    "*(No player-visible recap was produced for this session.)*\n"
)
"""Deterministic Python-owned placeholder for a durably EMPTY Recap.

Contains no model text and no hidden data.  Its presence makes EMPTY
unambiguous: a completed attempt always has a verifiable Recap artifact, so
"empty" is never inferred from file absence.
"""

_TRUNCATION_MARKER: Final[str] = " [truncated]"


# ── Errors ────────────────────────────────────────────────────────────────


class PersistenceFailureReason(StrEnum):
    """Bounded, stable classification of an artifact persistence-policy failure."""

    WORKFLOW_TOO_LARGE = "workflow_too_large"
    INVALID_SUMMARY_ARTIFACT = "invalid_summary_artifact"
    INVALID_RECAP_ARTIFACT = "invalid_recap_artifact"


class PostSessionPersistenceError(Exception):
    """Raised when durable artifact construction fails closed."""

    def __init__(
        self,
        reason: PersistenceFailureReason,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause
        self.reason = reason


class ArtifactPersistOutcome(StrEnum):
    """Application-level result of persisting one immutable artifact."""

    CREATED = "created"
    ALREADY_PRESENT = "already_present"


# ── Artifact content ──────────────────────────────────────────────────────


def summary_artifact_text(rendered: RenderedPostSessionArtifact) -> str:
    """Return the exact Summary artifact text (always a rendered body)."""
    if rendered.outcome is not RenderOutcome.RENDERED or rendered.content is None:
        raise PostSessionPersistenceError(
            PersistenceFailureReason.INVALID_SUMMARY_ARTIFACT,
            "Summary artifact requires a RENDERED outcome with non-empty content",
        )
    return rendered.content


def recap_artifact_text(rendered: RenderedPostSessionArtifact) -> str:
    """Return the exact Recap artifact text (rendered body or EMPTY placeholder)."""
    if rendered.outcome is RenderOutcome.EMPTY:
        return EMPTY_RECAP_ARTIFACT_TEXT
    if rendered.content is None:
        raise PostSessionPersistenceError(
            PersistenceFailureReason.INVALID_RECAP_ARTIFACT,
            "Recap artifact requires either RENDERED content or an EMPTY outcome",
        )
    return rendered.content


def artifact_content_hash(text: str) -> Sha256Fingerprint:
    """SHA-256 of the exact UTF-8 bytes that will be persisted."""
    return Sha256Fingerprint(digest=hashlib.sha256(text.encode("utf-8")).hexdigest())


# ── Workflow evidence ─────────────────────────────────────────────────────


def _truncate_detail(detail: str) -> str:
    """Deterministically bound a diagnostic detail on a character boundary."""
    if len(detail) <= MAX_WORKFLOW_DIAGNOSTIC_CHARS:
        return detail
    keep = MAX_WORKFLOW_DIAGNOSTIC_CHARS - len(_TRUNCATION_MARKER)
    return detail[:keep] + _TRUNCATION_MARKER


def _workflow_unresolved(
    unresolved: PostSessionChangeUnresolved,
) -> WorkflowUnresolvedDiagnostic:
    return WorkflowUnresolvedDiagnostic(
        reason=unresolved.reason.value,
        detail=_truncate_detail(unresolved.detail),
        claim_id=unresolved.claim_id,
        mention_id=unresolved.mention_id,
        candidate_id=unresolved.candidate_id,
        candidate_entity_ids=tuple(unresolved.candidate_entity_ids),
    )


def _workflow_operation(
    operation: PostSessionOperationProvenance,
) -> WorkflowOperationProvenance:
    return WorkflowOperationProvenance(
        operation_index=operation.operation_index,
        operation_kind=operation.operation_kind,
        claim_ids=tuple(operation.claim_ids),
        candidate_ids=tuple(operation.candidate_ids),
        evidence_event_ids=tuple(operation.evidence_event_ids),
    )


def _rendering_provenance(
    rendered: RenderedPostSessionArtifact,
) -> RenderingWorkflowProvenance:
    provenance = rendered.provenance
    return RenderingWorkflowProvenance(
        artifact_kind=provenance.artifact_kind,
        render_prompt_version=provenance.render_prompt_version,
        render_schema_version=provenance.render_schema_version,
        outcome=rendered.outcome,
        model_profile=provenance.model_profile,
        model=provenance.model,
        provider=provenance.provider,
    )


def build_workflow_evidence(
    prepared: PreparedPostSessionInput,
    accepted: AcceptedPostSessionExtraction,
    summary: RenderedPostSessionArtifact,
    recap: RenderedPostSessionArtifact,
    plan: PostSessionChangePlanResult,
) -> AttemptWorkflowEvidence:
    """Build the complete machine-readable workflow evidence for one attempt."""
    identity = prepared.identity
    extraction = accepted.provenance
    produced = plan.changeset is not None and plan.changeset_fingerprint is not None
    changeset_fingerprint = (
        Sha256Fingerprint(digest=plan.changeset_fingerprint.digest)
        if plan.changeset_fingerprint is not None
        else None
    )
    return AttemptWorkflowEvidence(
        schema_version=POST_SESSION_WORKFLOW_SCHEMA_VERSION,
        session_ref=identity.session.id,
        attempt_id=plan.attempt_id,
        input_fingerprint=prepared.fingerprint,
        processor_version=identity.processor_version,
        prompt_version=identity.prompt_version,
        extraction=ExtractionWorkflowProvenance(
            model_profile=extraction.model_profile,
            model=extraction.model,
            provider=extraction.provider,
            extraction_schema_version=extraction.extraction_schema_version,
        ),
        summary=_rendering_provenance(summary),
        recap=_rendering_provenance(recap),
        change_plan=WorkflowChangePlan(
            produced=produced,
            changeset_id=plan.changeset.changeset_id if plan.changeset is not None else None,
            changeset_fingerprint=changeset_fingerprint,
            unresolved=tuple(_workflow_unresolved(item) for item in plan.unresolved),
            operation_provenance=tuple(
                _workflow_operation(item) for item in plan.operation_provenance
            ),
        ),
    )


def serialize_workflow_evidence(evidence: AttemptWorkflowEvidence) -> str:
    """Serialize workflow evidence and enforce the hard byte ceiling.

    The canonical form is compact key-sorted UTF-8 JSON plus one trailing
    newline; the ceiling is checked over the exact bytes that would be
    persisted.  Exceeding it fails closed before any write.
    """
    payload = evidence.model_dump(mode="json", exclude_unset=False)
    text = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    if len(text.encode("utf-8")) > MAX_WORKFLOW_ARTIFACT_BYTES:
        raise PostSessionPersistenceError(
            PersistenceFailureReason.WORKFLOW_TOO_LARGE,
            f"Workflow evidence exceeds {MAX_WORKFLOW_ARTIFACT_BYTES} bytes",
        )
    return text


# ── Immutable persistence ─────────────────────────────────────────────────


def persist_immutable_artifact(
    store: PostSessionArtifactStore,
    session_id: str,
    attempt_id: str,
    artifact_kind: PersistedArtifactKind,
    text: str,
) -> tuple[ArtifactPersistOutcome, str]:
    """Persist one immutable artifact and return ``(outcome, relative_path)``.

    The storage layer performs exclusive create, idempotent identical-content
    acceptance, read-back verification and immutable conflict rejection.  The
    returned logical relative path is recorded in the ledger.
    """
    result = store.persist_artifact(session_id, attempt_id, artifact_kind, text)
    outcome = (
        ArtifactPersistOutcome.CREATED if result.created else ArtifactPersistOutcome.ALREADY_PRESENT
    )
    return outcome, result.relative_path


__all__ = [
    "EMPTY_RECAP_ARTIFACT_TEXT",
    "ArtifactPersistOutcome",
    "PersistenceFailureReason",
    "PostSessionPersistenceError",
    "artifact_content_hash",
    "build_workflow_evidence",
    "persist_immutable_artifact",
    "recap_artifact_text",
    "serialize_workflow_evidence",
    "summary_artifact_text",
]
