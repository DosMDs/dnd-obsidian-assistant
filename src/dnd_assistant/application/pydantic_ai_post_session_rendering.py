"""Pydantic AI adapter for the Stage-11 Summary/Recap rendering boundary (S11-04).

A narrowly isolated transport/framework adapter implementing the
application-owned ``PostSessionRenderingModel`` protocol.  It performs exactly
one bounded Pydantic AI structured-output request per artifact render with:

- zero **project/action** tools, toolsets or deps;
- output retries = 0 and tool retries = 0;
- ``UsageLimits(request_limit=1)`` (one visible model invocation);
- stable mapping of confirmed framework/provider failures to application
  rendering errors via the shared neutral classifier.

The artifact kind and system prompt are Python-owned: the adapter selects the
Summary or Recap prompt from the concrete request type, so a caller cannot
inject an arbitrary prompt or relabel the artifact.

Framework-internal structured-output machinery is allowed, because it exists
only to produce the declared ``PostSessionRenderOutput`` schema; it is not a
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

from dnd_assistant.application.post_session_rendering import (
    PostSessionRenderingError,
    RecapRenderRequest,
    RenderingFailureReason,
    SummaryRenderRequest,
    serialize_recap_request,
    serialize_summary_request,
)
from dnd_assistant.application.pydantic_ai_model_errors import (
    ModelFailureKind,
    classify_model_api_error,
)
from dnd_assistant.domain.post_session_artifacts import PostSessionRenderOutput
from dnd_assistant.prompts.post_session_recap_v1 import POST_SESSION_RECAP_SYSTEM_PROMPT
from dnd_assistant.prompts.post_session_summary_v1 import POST_SESSION_SUMMARY_SYSTEM_PROMPT

_MODEL_API_FAILURE_REASON: dict[ModelFailureKind, RenderingFailureReason] = {
    ModelFailureKind.TIMEOUT: RenderingFailureReason.MODEL_TIMEOUT,
    ModelFailureKind.UNAVAILABLE: RenderingFailureReason.MODEL_UNAVAILABLE,
    ModelFailureKind.INVOCATION_FAILED: RenderingFailureReason.MODEL_INVOCATION_FAILED,
}


class PydanticAIPostSessionRenderingModel:
    """Pydantic AI structured-rendering adapter (zero project tools)."""

    def __init__(self, *, model: Model) -> None:
        if not isinstance(model, Model):
            raise TypeError(
                f"model must be a Pydantic AI Model instance, got {type(model).__name__}"
            )
        self._model = model

    def render(
        self,
        request: SummaryRenderRequest | RecapRenderRequest,
    ) -> PostSessionRenderOutput:
        """Perform exactly one bounded structured render request.

        Raises:
            PostSessionRenderingError: On structured-output validation failure,
                provider/framework failure, or timeout.  The underlying
                framework exception is preserved as ``__cause__``.
        """
        instructions, prompt = self._select_prompt(request)

        agent: Agent[None, PostSessionRenderOutput] = Agent(
            self._model,
            instructions=instructions,
            output_type=PostSessionRenderOutput,
            retries={"tools": 0, "output": 0},
        )

        try:
            result = agent.run_sync(prompt, usage_limits=UsageLimits(request_limit=1))
        except UnexpectedModelBehavior as exc:
            raise PostSessionRenderingError(
                RenderingFailureReason.INVALID_STRUCTURED_OUTPUT,
                "Structured rendering output failed validation",
                cause=exc,
            ) from exc
        except ModelHTTPError as exc:
            raise PostSessionRenderingError(
                RenderingFailureReason.MODEL_INVOCATION_FAILED,
                f"Model provider returned HTTP status {exc.status_code}",
                cause=exc,
            ) from exc
        except ModelAPIError as exc:
            raise PostSessionRenderingError(
                _MODEL_API_FAILURE_REASON[classify_model_api_error(exc)],
                "Model provider request failed",
                cause=exc,
            ) from exc
        except AgentRunError as exc:
            raise PostSessionRenderingError(
                RenderingFailureReason.MODEL_INVOCATION_FAILED,
                "Model invocation failed",
                cause=exc,
            ) from exc

        return result.output

    @staticmethod
    def _select_prompt(
        request: SummaryRenderRequest | RecapRenderRequest,
    ) -> tuple[str, str]:
        """Select the Python-owned prompt and deterministic payload."""
        if isinstance(request, SummaryRenderRequest):
            return POST_SESSION_SUMMARY_SYSTEM_PROMPT, serialize_summary_request(request)
        if isinstance(request, RecapRenderRequest):
            return POST_SESSION_RECAP_SYSTEM_PROMPT, serialize_recap_request(request)
        raise TypeError(
            "request must be a SummaryRenderRequest or RecapRenderRequest instance, "
            f"got {type(request).__name__}"
        )


__all__ = ["PydanticAIPostSessionRenderingModel"]
