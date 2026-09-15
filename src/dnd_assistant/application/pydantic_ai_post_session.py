"""Pydantic AI adapter for the Stage-11 structured extraction boundary (S11-03).

This is a narrowly isolated transport/framework adapter implementing the
application-owned ``PostSessionExtractionModel`` protocol.  It performs exactly
one bounded Pydantic AI structured-output request with:

- zero **project/action** tools, toolsets or deps;
- output retries = 0 and tool retries = 0;
- ``UsageLimits(request_limit=1)`` (one visible model invocation);
- stable mapping of confirmed framework/provider failures to application
  errors.

Framework-internal structured-output machinery is allowed, because it exists
only to produce the declared ``PostSessionExtraction`` output schema; it is not
a project action-tool surface.

This module must not import from::
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
    dnd_assistant.tools
    dnd_assistant.tools.executor
"""

from __future__ import annotations

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import (
    AgentRunError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.models import Model

from dnd_assistant.application.post_session_extraction import (
    ExtractionFailureReason,
    PostSessionExtractionError,
    PostSessionExtractionRequest,
)
from dnd_assistant.application.pydantic_ai_model_errors import (
    ModelFailureKind,
    classify_model_api_error,
)
from dnd_assistant.domain.post_session_extraction import PostSessionExtraction
from dnd_assistant.prompts.post_session_extraction_v1 import (
    POST_SESSION_EXTRACTION_SYSTEM_PROMPT,
)

_MODEL_API_FAILURE_REASON: dict[ModelFailureKind, ExtractionFailureReason] = {
    ModelFailureKind.TIMEOUT: ExtractionFailureReason.MODEL_TIMEOUT,
    ModelFailureKind.UNAVAILABLE: ExtractionFailureReason.MODEL_UNAVAILABLE,
    ModelFailureKind.INVOCATION_FAILED: ExtractionFailureReason.MODEL_INVOCATION_FAILED,
}


def _classify_model_api_error(exc: ModelAPIError) -> ExtractionFailureReason:
    """Map a provider ``ModelAPIError`` to a stable extraction reason.

    Delegates the observed-cause classification to the shared
    ``application.pydantic_ai_model_errors`` neutral classifier so extraction
    and rendering adapters cannot drift apart.
    """
    return _MODEL_API_FAILURE_REASON[classify_model_api_error(exc)]


class PydanticAIPostSessionExtractionModel:
    """Pydantic AI structured-extraction adapter (zero project tools)."""

    def __init__(self, *, model: Model) -> None:
        if not isinstance(model, Model):
            raise TypeError(
                f"model must be a Pydantic AI Model instance, got {type(model).__name__}"
            )
        self._model = model

    def extract(self, request: PostSessionExtractionRequest) -> PostSessionExtraction:
        """Perform exactly one bounded structured-extraction model request.

        Raises:
            PostSessionExtractionError: On structured-output validation
                failure, provider/framework failure, or timeout.  The
                underlying framework exception is preserved as ``__cause__``.
        """
        if not isinstance(request, PostSessionExtractionRequest):
            raise TypeError(
                "request must be a PostSessionExtractionRequest instance, "
                f"got {type(request).__name__}"
            )

        agent: Agent[None, PostSessionExtraction] = Agent(
            self._model,
            instructions=POST_SESSION_EXTRACTION_SYSTEM_PROMPT,
            output_type=PostSessionExtraction,
            retries={"tools": 0, "output": 0},
        )

        try:
            result = agent.run_sync(
                request.context_text,
                usage_limits=UsageLimits(request_limit=1),
            )
        except UnexpectedModelBehavior as exc:
            raise PostSessionExtractionError(
                ExtractionFailureReason.INVALID_STRUCTURED_OUTPUT,
                "Structured extraction output failed validation",
                cause=exc,
            ) from exc
        except ModelHTTPError as exc:
            raise PostSessionExtractionError(
                ExtractionFailureReason.MODEL_INVOCATION_FAILED,
                f"Model provider returned HTTP status {exc.status_code}",
                cause=exc,
            ) from exc
        except ModelAPIError as exc:
            raise PostSessionExtractionError(
                _classify_model_api_error(exc),
                "Model provider request failed",
                cause=exc,
            ) from exc
        except AgentRunError as exc:
            raise PostSessionExtractionError(
                ExtractionFailureReason.MODEL_INVOCATION_FAILED,
                "Model invocation failed",
                cause=exc,
            ) from exc

        return result.output


__all__ = ["PydanticAIPostSessionExtractionModel"]
