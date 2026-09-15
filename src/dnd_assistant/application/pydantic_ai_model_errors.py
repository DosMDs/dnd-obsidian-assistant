"""Shared Pydantic AI provider-error classification (S11-04 extraction).

Both post-session Pydantic AI adapters (structured extraction, S11-03, and
artifact rendering, S11-04) must map provider failures to stable application
failure reasons.  Keeping one neutral classifier here prevents the two
adapters from drifting apart.

This module is a provider-adjacent transport helper owned by the application
layer.  It imports ``pydantic_ai`` and (lazily) ``openai`` only; it must not
import storage, retrieval, tools, cli or any concrete project service.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic_ai.exceptions import ModelAPIError


class ModelFailureKind(StrEnum):
    """Provider-neutral failure classification of a ``ModelAPIError``."""

    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVOCATION_FAILED = "invocation_failed"


def classify_model_api_error(exc: ModelAPIError) -> ModelFailureKind:
    """Classify a confirmed ``ModelAPIError`` by its observed public cause.

    Pydantic AI 2.39 maps OpenAI-compatible ``APIConnectionError`` (which
    ``APITimeoutError`` subclasses) to ``ModelAPIError``.  We inspect the
    documented cause chain to distinguish timeout from plain connection
    failure; everything else stays conservatively ``INVOCATION_FAILED``.
    """
    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a required extra
        return ModelFailureKind.INVOCATION_FAILED

    cause: BaseException | None = exc.__cause__
    depth = 0
    while cause is not None and depth < 8:
        if isinstance(cause, openai.APITimeoutError):
            return ModelFailureKind.TIMEOUT
        if isinstance(cause, openai.APIConnectionError):
            return ModelFailureKind.UNAVAILABLE
        cause = cause.__cause__
        depth += 1
    return ModelFailureKind.INVOCATION_FAILED


__all__ = [
    "ModelFailureKind",
    "classify_model_api_error",
]
