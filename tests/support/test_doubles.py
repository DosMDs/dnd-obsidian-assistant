"""Test-only deterministic model doubles for offline testing.

All offline-safe: no network, no model, no framework imports beyond
``pydantic_ai.models.Model`` and project DTOs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import CompletedStreamedResponse, Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings


class FakeModel(Model):
    """Minimal deterministic Pydantic AI ``Model`` for offline testing.

    Returns a fixed ``ModelResponse`` with text ``"ok"`` on every
    ``request()`` call.  Tracks invocation count for test assertions.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        settings: ModelSettings | None = None,
        profile: Any | None = None,
    ) -> None:
        super().__init__(settings=settings, profile=profile)
        self._invocation_count = 0
        self._base_url = base_url

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def system(self) -> str:
        return "test-system"

    @property
    def base_url(self) -> str | None:
        return self._base_url

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    def customize_request_parameters(
        self, model_request_parameters: ModelRequestParameters
    ) -> ModelRequestParameters:
        """Customize request parameters (delegates to default behavior)."""
        return model_request_parameters

    def prepare_request(
        self,
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> tuple[ModelSettings | None, ModelRequestParameters]:
        return model_settings, model_request_parameters

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self._invocation_count += 1
        return ModelResponse(parts=[TextPart(content="ok")])

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncIterator[Any]:
        self._invocation_count += 1
        response = ModelResponse(parts=[TextPart(content="ok")])
        yield CompletedStreamedResponse(response, model_request_parameters=model_request_parameters)


class RaisingFakeModel(Model):
    """Minimal deterministic Pydantic AI ``Model`` that raises on request.

    Useful for testing error-propagation paths.
    """

    def __init__(self) -> None:
        super().__init__()

    @property
    def model_name(self) -> str:
        return "raising-model"

    @property
    def system(self) -> str:
        return "test-system"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        msg = "Simulated model failure"
        raise RuntimeError(msg)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncIterator[Any]:
        msg = "Simulated model failure"
        raise RuntimeError(msg)
        yield  # pragma: no cover - makes this an async generator for typing


# ── Warm-up deterministic fakes (PAIM-C32) ──────────────────────────────────────


_WARMUP_OUTCOME_JSON = '{"kind": "respond", "message": "warm-up ok"}'


class WarmupFakeModel(FakeModel):
    """FakeModel variant that returns valid AgentTextOutcome JSON.

    Used for offline warm-up preflight tests where the model response
    must be parseable by ``parse_agent_outcome``.
    """

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self._invocation_count += 1
        return ModelResponse(parts=[TextPart(content=_WARMUP_OUTCOME_JSON)])
