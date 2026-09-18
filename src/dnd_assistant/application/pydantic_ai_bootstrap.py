"""Pydantic AI adapter for the S13-03 bootstrap structured-extraction boundary.

This is a narrowly isolated transport/framework adapter implementing the
application-owned ``BootstrapExtractionModel`` protocol.  It performs exactly
one bounded Pydantic AI structured-output request per batch with:

- zero **project/action** tools, toolsets or deps;
- output retries = 0 and tool retries = 0;
- ``UsageLimits(request_limit=1)`` (one visible model invocation);
- stable mapping of confirmed framework/provider failures to application errors.

Framework-internal structured-output machinery is allowed, because it exists
only to produce the declared ``BootstrapExtraction`` output schema; it is not a
project action-tool surface.

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

from dnd_assistant.application.bootstrap_extraction import (
    BootstrapExtractionError,
    BootstrapExtractionFailureReason,
    BootstrapExtractionRequest,
)
from dnd_assistant.application.pydantic_ai_model_errors import (
    ModelFailureKind,
    classify_model_api_error,
)
from dnd_assistant.domain.bootstrap_extraction import BootstrapExtraction
from dnd_assistant.prompts.bootstrap_extraction_v1 import (
    BOOTSTRAP_EXTRACTION_SYSTEM_PROMPT,
)

_MODEL_API_FAILURE_REASON: dict[ModelFailureKind, BootstrapExtractionFailureReason] = {
    ModelFailureKind.TIMEOUT: BootstrapExtractionFailureReason.MODEL_TIMEOUT,
    ModelFailureKind.UNAVAILABLE: BootstrapExtractionFailureReason.MODEL_UNAVAILABLE,
    ModelFailureKind.INVOCATION_FAILED: BootstrapExtractionFailureReason.MODEL_INVOCATION_FAILED,
}


def _classify_model_api_error(exc: ModelAPIError) -> BootstrapExtractionFailureReason:
    """Map a provider ``ModelAPIError`` to a stable bootstrap reason."""
    return _MODEL_API_FAILURE_REASON[classify_model_api_error(exc)]


class PydanticAIBootstrapExtractionModel:
    """Pydantic AI structured-extraction adapter (zero project tools)."""

    def __init__(self, *, model: Model) -> None:
        if not isinstance(model, Model):
            raise TypeError(
                f"model must be a Pydantic AI Model instance, got {type(model).__name__}"
            )
        self._model = model

    def extract(self, request: BootstrapExtractionRequest) -> BootstrapExtraction:
        """Perform exactly one bounded structured-extraction model request.

        Raises:
            BootstrapExtractionError: On structured-output validation failure,
                provider/framework failure, or timeout.  The underlying
                framework exception is preserved as ``__cause__``.
        """
        if not isinstance(request, BootstrapExtractionRequest):
            raise TypeError(
                "request must be a BootstrapExtractionRequest instance, "
                f"got {type(request).__name__}"
            )

        agent: Agent[None, BootstrapExtraction] = Agent(
            self._model,
            instructions=BOOTSTRAP_EXTRACTION_SYSTEM_PROMPT,
            output_type=BootstrapExtraction,
            retries={"tools": 0, "output": 0},
        )

        try:
            result = agent.run_sync(
                request.context_text,
                usage_limits=UsageLimits(request_limit=1),
            )
        except UnexpectedModelBehavior as exc:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.INVALID_STRUCTURED_OUTPUT,
                "Structured bootstrap extraction output failed validation",
                cause=exc,
            ) from exc
        except ModelHTTPError as exc:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.MODEL_INVOCATION_FAILED,
                f"Model provider returned HTTP status {exc.status_code}",
                cause=exc,
            ) from exc
        except ModelAPIError as exc:
            raise BootstrapExtractionError(
                _classify_model_api_error(exc),
                "Model provider request failed",
                cause=exc,
            ) from exc
        except AgentRunError as exc:
            raise BootstrapExtractionError(
                BootstrapExtractionFailureReason.MODEL_INVOCATION_FAILED,
                "Model invocation failed",
                cause=exc,
            ) from exc

        return result.output


__all__ = ["PydanticAIBootstrapExtractionModel"]
