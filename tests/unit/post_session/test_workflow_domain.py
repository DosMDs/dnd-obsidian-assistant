"""S11-06 workflow-evidence schema, bounds and serialization tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.application import post_session_persistence as persistence
from dnd_assistant.application.post_session_persistence import (
    EMPTY_RECAP_ARTIFACT_TEXT,
    PersistenceFailureReason,
    PostSessionPersistenceError,
    _truncate_detail,
    serialize_workflow_evidence,
)
from dnd_assistant.domain.post_session import (
    ArtifactKind,
    Sha256Fingerprint,
)
from dnd_assistant.domain.post_session_artifacts import RenderOutcome
from dnd_assistant.domain.post_session_workflow import (
    MAX_WORKFLOW_DIAGNOSTIC_CHARS,
    POST_SESSION_WORKFLOW_SCHEMA_VERSION,
    AttemptWorkflowEvidence,
    ExtractionWorkflowProvenance,
    RenderingWorkflowProvenance,
    WorkflowChangePlan,
    WorkflowUnresolvedDiagnostic,
)

_ATT = "att_" + "a" * 32
_FP = Sha256Fingerprint(digest="c" * 64)


def _evidence(*, detail: str = "ok") -> AttemptWorkflowEvidence:
    return AttemptWorkflowEvidence(
        schema_version=POST_SESSION_WORKFLOW_SCHEMA_VERSION,
        session_ref="S001",
        attempt_id=_ATT,
        input_fingerprint=_FP,
        processor_version="2",
        prompt_version="post-session-extraction-v1",
        extraction=ExtractionWorkflowProvenance(
            model_profile="heavy", model="qwen3", provider="ollama", extraction_schema_version=1
        ),
        summary=RenderingWorkflowProvenance(
            artifact_kind=ArtifactKind.SUMMARY,
            render_prompt_version="post-session-summary-v1",
            render_schema_version=1,
            outcome=RenderOutcome.RENDERED,
        ),
        recap=RenderingWorkflowProvenance(
            artifact_kind=ArtifactKind.RECAP,
            render_prompt_version="post-session-recap-v1",
            render_schema_version=1,
            outcome=RenderOutcome.EMPTY,
        ),
        change_plan=WorkflowChangePlan(
            produced=False,
            unresolved=(WorkflowUnresolvedDiagnostic(reason="no_canonical_target", detail=detail),),
        ),
    )


def test_workflow_serialization_is_deterministic() -> None:
    first = serialize_workflow_evidence(_evidence())
    second = serialize_workflow_evidence(_evidence())
    assert first == second
    assert first.endswith("\n")


def test_workflow_boundary_is_checked_over_exact_utf8_bytes(monkeypatch) -> None:
    # Multibyte content proves the ceiling is measured in bytes, not characters.
    evidence = _evidence(detail="café ☕")
    text = serialize_workflow_evidence(evidence)
    byte_len = len(text.encode("utf-8"))
    assert byte_len > len(text)

    monkeypatch.setattr(persistence, "MAX_WORKFLOW_ARTIFACT_BYTES", byte_len)
    assert serialize_workflow_evidence(evidence) == text

    monkeypatch.setattr(persistence, "MAX_WORKFLOW_ARTIFACT_BYTES", byte_len - 1)
    with pytest.raises(PostSessionPersistenceError) as exc:
        serialize_workflow_evidence(evidence)
    assert exc.value.reason is PersistenceFailureReason.WORKFLOW_TOO_LARGE


def test_workflow_over_hard_ceiling_fails_closed() -> None:
    big = WorkflowUnresolvedDiagnostic(
        reason="no_canonical_target",
        detail="x" * MAX_WORKFLOW_DIAGNOSTIC_CHARS,
    )
    evidence = _evidence()
    evidence = evidence.model_copy(
        update={
            "change_plan": evidence.change_plan.model_copy(update={"unresolved": (big,) * 1200})
        }
    )
    with pytest.raises(PostSessionPersistenceError) as exc:
        serialize_workflow_evidence(evidence)
    assert exc.value.reason is PersistenceFailureReason.WORKFLOW_TOO_LARGE


def test_diagnostic_detail_is_bounded_on_character_boundary() -> None:
    assert _truncate_detail("short") == "short"
    truncated = _truncate_detail("☕" * (MAX_WORKFLOW_DIAGNOSTIC_CHARS + 500))
    assert len(truncated) <= MAX_WORKFLOW_DIAGNOSTIC_CHARS
    assert truncated.endswith("[truncated]")
    # No lone surrogate / broken character.
    truncated.encode("utf-8")


def test_diagnostic_schema_rejects_overlong_detail() -> None:
    with pytest.raises(PydanticValidationError):
        WorkflowUnresolvedDiagnostic(
            reason="no_canonical_target", detail="x" * (MAX_WORKFLOW_DIAGNOSTIC_CHARS + 1)
        )


def test_empty_recap_placeholder_is_deterministic_and_textless() -> None:
    assert EMPTY_RECAP_ARTIFACT_TEXT
    assert EMPTY_RECAP_ARTIFACT_TEXT == persistence.EMPTY_RECAP_ARTIFACT_TEXT
    assert "No player-visible recap" in EMPTY_RECAP_ARTIFACT_TEXT
