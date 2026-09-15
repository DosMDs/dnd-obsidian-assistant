"""Stage-11 generated-artifact domain schema (S11-04).

Defines the bounded, versioned structured output contract produced by a
Summary/Recap rendering model, plus the in-memory outcome classification of a
rendering attempt.

The output is **untrusted model output**: it is validated by the application
rendering policy before it can be reported as a rendered artifact.  This module
contains no storage/application/model/provider import and no persistence DTO.

Markdown bodies require multi-line text, so the body validator here is
deliberately distinct from the single-line bounded-message validator used for
durable failure messages (``domain.post_session``).

This module belongs to the domain layer and must not import from:
    storage, application, models, tools, retrieval, cli, ollama,
    pydantic_ai, pathlib, os, hashlib
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, BeforeValidator, Field

# ── Schema version and bounds ─────────────────────────────────────────────

POST_SESSION_RENDER_SCHEMA_VERSION: Final[int] = 1
"""Explicit render-output schema contract version.

Independent of the package version, the prepared-input schema and the
extraction schema.  A breaking contract change must introduce a new explicit
value; it is never implicitly tracked.
"""

MAX_RENDER_BODY_CHARS: Final[int] = 20_000
"""Maximum length of a rendered Markdown body (project-owned, fail-closed)."""


# ── Render outcome ────────────────────────────────────────────────────────


class RenderOutcome(StrEnum):
    """Terminal outcome of a non-persisted render attempt (S11-04).

    ``RENDERED`` always carries a non-empty body; ``EMPTY`` means Python
    determined there was nothing safe to render and **no** model call was
    made, so the body is ``None``.  The durable representation of an EMPTY
    artifact is deferred to S11-06.
    """

    RENDERED = "rendered"
    EMPTY = "empty"


# ── Body validator ────────────────────────────────────────────────────────


def _validate_markdown_body(value: str) -> str:
    """Validate a bounded, printable, multi-line Markdown body.

    Newlines and tabs are explicitly permitted.  NUL and other C0 control
    characters (and DEL) are rejected.  Leading/trailing whitespace is
    permitted because Markdown structure legitimately uses blank lines, but a
    body that is empty or whitespace-only is rejected: a model that returns no
    content is a failure, not a successful empty artifact.
    """
    if not isinstance(value, str):
        raise ValueError("render body must be a string")
    if not value.strip():
        raise ValueError("render body must not be empty")
    if len(value) > MAX_RENDER_BODY_CHARS:
        raise ValueError(f"render body must be at most {MAX_RENDER_BODY_CHARS} characters")
    for char in value:
        if char in ("\n", "\t"):
            continue
        if ord(char) < 0x20 or ord(char) == 0x7F:
            raise ValueError("render body must not contain NUL or control characters")
    return value


BoundedMarkdownBody = Annotated[
    str,
    BeforeValidator(_validate_markdown_body),
    Field(description="Bounded printable multi-line Markdown body"),
]


# ── Model-visible output schema ───────────────────────────────────────────


class PostSessionRenderOutput(BaseModel):
    """The bounded structured rendering output returned by the model.

    ``schema_version`` is echoed by the model and validated by the application
    against ``POST_SESSION_RENDER_SCHEMA_VERSION``.  The artifact kind is
    Python-owned and deliberately absent from this schema, so the model cannot
    relabel the artifact it is producing.
    """

    schema_version: int = Field(ge=0)
    body: BoundedMarkdownBody

    model_config = {"frozen": True, "extra": "forbid"}


__all__ = [
    "MAX_RENDER_BODY_CHARS",
    "POST_SESSION_RENDER_SCHEMA_VERSION",
    "BoundedMarkdownBody",
    "PostSessionRenderOutput",
    "RenderOutcome",
]
