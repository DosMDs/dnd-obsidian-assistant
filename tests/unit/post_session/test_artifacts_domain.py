"""S11-04 render-output domain schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain.post_session_artifacts import (
    MAX_RENDER_BODY_CHARS,
    POST_SESSION_RENDER_SCHEMA_VERSION,
    PostSessionRenderOutput,
)


def test_accepts_multiline_markdown_body() -> None:
    output = PostSessionRenderOutput(
        schema_version=POST_SESSION_RENDER_SCHEMA_VERSION,
        body="# Title\n\n- one\n- two\n\tindented",
    )
    assert "\n" in output.body
    assert output.schema_version == POST_SESSION_RENDER_SCHEMA_VERSION


def test_rejects_empty_and_whitespace_body() -> None:
    for body in ("", "   ", "\n\n\t"):
        with pytest.raises(ValidationError):
            PostSessionRenderOutput(schema_version=1, body=body)


def test_rejects_nul_and_control_characters() -> None:
    for body in ("bad\x00body", "bad\x07body", "bad\x7fbody"):
        with pytest.raises(ValidationError):
            PostSessionRenderOutput(schema_version=1, body=body)


def test_rejects_oversized_body() -> None:
    with pytest.raises(ValidationError):
        PostSessionRenderOutput(schema_version=1, body="x" * (MAX_RENDER_BODY_CHARS + 1))


def test_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PostSessionRenderOutput(
            schema_version=1,
            body="ok",
            artifact_kind="summary",  # type: ignore[call-arg]
        )


def test_is_frozen() -> None:
    output = PostSessionRenderOutput(schema_version=1, body="ok")
    with pytest.raises(ValidationError):
        output.body = "changed"  # type: ignore[misc]


def test_rejects_negative_schema_version() -> None:
    with pytest.raises(ValidationError):
        PostSessionRenderOutput(schema_version=-1, body="ok")
