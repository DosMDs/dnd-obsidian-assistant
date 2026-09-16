"""Stage-11 durable workflow-evidence schema (S11-06).

Defines the immutable, strict, machine-readable attempt-local evidence artifact
persisted next to the per-attempt Summary/Recap Markdown files.  It is
**derived workflow evidence**, never campaign truth, never a parallel ChangeSet
and never a processing-state authority:

- it retains the rendering provenance exposed by S11-04 (Summary/Recap
  model/provider/version binding and RENDERED/EMPTY outcome);
- it retains the extraction provenance and the deterministic S11-05
  change-plan result (outcome, unresolved diagnostics, operation provenance,
  produced proposal identity);
- it is referenced by an ``artifact_persisted`` ledger event, so restart
  reconstruction verifies it by exact content hash like any other artifact.

It contains no model prose (bodies live in the Markdown artifacts), no
chain-of-thought, no filesystem path and no provider/framework type.  All
model/provider fields are plain bounded strings.

This module belongs to the domain layer and must not import from:
    storage, application, models, tools, retrieval, cli, ollama, pydantic_ai,
    pathlib, os, hashlib
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, BeforeValidator, Field

from dnd_assistant.domain.post_session import (
    ArtifactKind,
    NonEmptyStr,
    OptionalNonEmptyStr,
    Sha256Fingerprint,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome

# ── Schema version and bounds ─────────────────────────────────────────────

POST_SESSION_WORKFLOW_SCHEMA_VERSION: Final = 1
"""Explicit workflow-evidence schema contract version.

Only this exact version is accepted.  A persisted artifact carrying any other
integer (including an older ``0`` or an unknown future ``2``) is not
deserializable workflow evidence and is treated as ``WORKFLOW_EVIDENCE_INVALID``
by terminal integrity verification.  No migration is performed.
"""

MAX_WORKFLOW_ARTIFACT_BYTES: Final[int] = 2_000_000
"""Hard fail-closed byte ceiling for the persisted workflow artifact.

S11-03 bounds the whole accepted extraction at ``MAX_EXTRACTION_TOTAL_CHARS =
500_000`` characters, so its worst-case UTF-8 form is at most 2 MB.  The
workflow artifact embeds only provenance, identifiers, bounded diagnostics and
operation provenance, so 2 MB is an explicit ceiling above the already-bounded
inputs.  Validation is performed over the exact canonical UTF-8 bytes that
would be persisted; exceeding the ceiling fails the attempt closed rather than
writing a truncated artifact.
"""

MAX_WORKFLOW_DIAGNOSTIC_CHARS: Final[int] = 2000
"""Per-diagnostic ``detail`` ceiling.

A ``PostSessionChangeUnresolved.detail`` is derived text that can embed
model-supplied mention text.  It is deterministically truncated (on a Unicode
character boundary) before persistence so the artifact stays bounded; canonical
campaign evidence is never truncated.
"""


def _validate_diagnostic_detail(value: str) -> str:
    """Validate a bounded, printable, possibly-empty diagnostic detail."""
    if not isinstance(value, str):
        raise ValueError("diagnostic detail must be a string")
    if len(value) > MAX_WORKFLOW_DIAGNOSTIC_CHARS:
        raise ValueError(
            f"diagnostic detail must be at most {MAX_WORKFLOW_DIAGNOSTIC_CHARS} characters"
        )
    if not value.isprintable():
        raise ValueError("diagnostic detail must not contain non-printable characters")
    return value


BoundedDiagnosticDetail = Annotated[
    str,
    BeforeValidator(_validate_diagnostic_detail),
    Field(description="Bounded single-line diagnostic detail"),
]

# ── Nested provenance blocks ──────────────────────────────────────────────


class ExtractionWorkflowProvenance(BaseModel):
    """Durable extraction execution provenance (S11-03)."""

    model_profile: OptionalNonEmptyStr = None
    model: OptionalNonEmptyStr = None
    provider: OptionalNonEmptyStr = None
    extraction_schema_version: int = Field(ge=0)

    model_config = {"frozen": True, "extra": "forbid"}


class RenderingWorkflowProvenance(BaseModel):
    """Durable rendering provenance/outcome for one artifact (S11-04)."""

    artifact_kind: ArtifactKind
    render_prompt_version: NonEmptyStr
    render_schema_version: int = Field(ge=0)
    outcome: RenderOutcome
    model_profile: OptionalNonEmptyStr = None
    model: OptionalNonEmptyStr = None
    provider: OptionalNonEmptyStr = None

    model_config = {"frozen": True, "extra": "forbid"}


class WorkflowUnresolvedDiagnostic(BaseModel):
    """Durable copy of one S11-05 deterministic omission/diagnostic."""

    reason: NonEmptyStr
    detail: BoundedDiagnosticDetail = ""
    claim_id: OptionalNonEmptyStr = None
    mention_id: OptionalNonEmptyStr = None
    candidate_id: OptionalNonEmptyStr = None
    candidate_entity_ids: tuple[NonEmptyStr, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


class WorkflowOperationProvenance(BaseModel):
    """Durable claim/candidate/evidence linkage for one emitted operation."""

    operation_index: int = Field(ge=0)
    operation_kind: NonEmptyStr
    claim_ids: tuple[NonEmptyStr, ...] = ()
    candidate_ids: tuple[NonEmptyStr, ...] = ()
    evidence_event_ids: tuple[NonEmptyStr, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


class WorkflowChangePlan(BaseModel):
    """Durable S11-05 change-plan outcome and provenance.

    ``PROPOSAL`` carries the produced ``changeset_id``/fingerprint;
    ``NO_CHANGES`` carries neither.
    """

    produced: bool
    changeset_id: OptionalNonEmptyStr = None
    changeset_fingerprint: Sha256Fingerprint | None = None
    unresolved: tuple[WorkflowUnresolvedDiagnostic, ...] = ()
    operation_provenance: tuple[WorkflowOperationProvenance, ...] = ()

    model_config = {"frozen": True, "extra": "forbid"}


class AttemptWorkflowEvidence(BaseModel):
    """Complete immutable workflow evidence for one processing attempt."""

    schema_version: Literal[1] = POST_SESSION_WORKFLOW_SCHEMA_VERSION
    session_ref: NonEmptyStr
    attempt_id: NonEmptyStr
    input_fingerprint: Sha256Fingerprint
    processor_version: NonEmptyStr
    prompt_version: NonEmptyStr
    extraction: ExtractionWorkflowProvenance
    summary: RenderingWorkflowProvenance
    recap: RenderingWorkflowProvenance
    change_plan: WorkflowChangePlan

    model_config = {"frozen": True, "extra": "forbid"}


__all__ = [
    "BoundedDiagnosticDetail",
    "ExtractionWorkflowProvenance",
    "MAX_WORKFLOW_ARTIFACT_BYTES",
    "MAX_WORKFLOW_DIAGNOSTIC_CHARS",
    "POST_SESSION_WORKFLOW_SCHEMA_VERSION",
    "AttemptWorkflowEvidence",
    "RenderingWorkflowProvenance",
    "WorkflowChangePlan",
    "WorkflowOperationProvenance",
    "WorkflowUnresolvedDiagnostic",
]
