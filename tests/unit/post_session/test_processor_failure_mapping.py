"""S11-06 typed failure-category mapping tests (pure)."""

from __future__ import annotations

from dnd_assistant.application.post_session_changeset import (
    PostSessionChangeError,
    PostSessionChangeFailureReason,
)
from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    PostSessionExtractionError,
)
from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RenderingFailureReason,
)
from dnd_assistant.domain.post_session import FailureCategory


def test_extraction_reason_mapping() -> None:
    assert (
        PostSessionExtractionError(
            ExtractionFailureReason.MODEL_UNAVAILABLE, "x"
        ).to_failure_category()
        is FailureCategory.MODEL_UNAVAILABLE
    )
    assert (
        PostSessionExtractionError(ExtractionFailureReason.MODEL_TIMEOUT, "x").to_failure_category()
        is FailureCategory.MODEL_TIMEOUT
    )
    assert (
        PostSessionExtractionError(
            ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT, "x"
        ).to_failure_category()
        is FailureCategory.INVALID_OUTPUT
    )


def test_rendering_reason_mapping() -> None:
    assert (
        PostSessionRenderingError(
            RenderingFailureReason.MODEL_UNAVAILABLE, "x"
        ).to_failure_category()
        is FailureCategory.MODEL_UNAVAILABLE
    )
    assert (
        PostSessionRenderingError(RenderingFailureReason.MODEL_TIMEOUT, "x").to_failure_category()
        is FailureCategory.MODEL_TIMEOUT
    )
    assert (
        PostSessionRenderingError(
            RenderingFailureReason.PROVENANCE_MISMATCH, "x"
        ).to_failure_category()
        is FailureCategory.FINGERPRINT_MISMATCH
    )
    assert (
        PostSessionRenderingError(RenderingFailureReason.EMPTY_OUTPUT, "x").to_failure_category()
        is FailureCategory.INVALID_OUTPUT
    )


def test_changeset_reason_mapping() -> None:
    assert (
        PostSessionChangeError(
            PostSessionChangeFailureReason.PROVENANCE_MISMATCH, "x"
        ).to_failure_category()
        is FailureCategory.FINGERPRINT_MISMATCH
    )
    assert (
        PostSessionChangeError(
            PostSessionChangeFailureReason.CHANGESET_PREFLIGHT_FAILED, "x"
        ).to_failure_category()
        is FailureCategory.INTERNAL_ERROR
    )
    assert (
        PostSessionChangeError(
            PostSessionChangeFailureReason.INVALID_REQUEST, "x"
        ).to_failure_category()
        is FailureCategory.INVALID_OUTPUT
    )
