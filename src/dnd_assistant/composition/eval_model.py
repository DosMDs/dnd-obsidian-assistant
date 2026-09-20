"""Eval model seam: request recording + deterministic scripted oracle.

``RecordingPydanticModel`` is a product-owned wrapper over any Pydantic AI
``Model`` (public ``WrapperModel`` API).  It records literal semantic request
counts, raw responses and durations at the request boundary *before* the agent
runtime maps or raises, so a failed sample still yields observation evidence.

S14-07 reuses ``RecordingPydanticModel`` unchanged around a real Ollama model.
S14-06 only supplies a deterministic offline ``FunctionModel`` script derived
from the dataset ground truth.  This is runner plumbing evidence, never a
real-model quality claim.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from dnd_assistant.evals.contracts import EvalExpectation, ScenarioExpectationKind

TERMINAL_RESPOND = '{"kind":"respond","message":"Готово."}'
TERMINAL_CLARIFY = '{"kind":"clarify","message":"Уточните цель, пожалуйста."}'


@dataclass(slots=True)
class ModelCallRecorder:
    """Mutable literal record of semantic model requests for one sample."""

    request_count: int = 0
    responses: list[ModelResponse] = field(default_factory=list)
    request_durations: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def first_response(self) -> ModelResponse | None:
        """The first recorded model response, if any."""
        return self.responses[0] if self.responses else None


class RecordingPydanticModel(WrapperModel):
    """Wrap any Pydantic AI ``Model`` and record semantic requests.

    Counts a request even when the wrapped model raises, preserving failure
    evidence.  All other behavior is inherited from ``WrapperModel``.
    """

    def __init__(self, delegate: Model, *, recorder: ModelCallRecorder | None = None) -> None:
        super().__init__(wrapped=delegate)
        self.recorder = recorder if recorder is not None else ModelCallRecorder()
        self._clock: Callable[[], float] = time.perf_counter

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.recorder.request_count += 1
        start = self._clock()
        try:
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
        except Exception as exc:  # noqa: BLE001 - failure evidence is the point
            self.recorder.request_durations.append(self._clock() - start)
            self.recorder.failures.append(f"{type(exc).__name__}: {exc}")
            raise
        self.recorder.request_durations.append(self._clock() - start)
        self.recorder.responses.append(response)
        return response


# ── Scripted oracle ────────────────────────────────────────────────────────


def script_responses(expectation: EvalExpectation) -> list[ModelResponse]:
    """Derive the deterministic oracle response sequence from ground truth.

    - no-tool expectation: exactly one terminal response;
    - ``EXACT_TOOL_CALLS``: one tool-call batch response, then one terminal.
    """
    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        parts = [
            ToolCallPart(
                tool_name=call.tool_name,
                args=call.arguments,
                tool_call_id=f"call_{index}",
            )
            for index, call in enumerate(expectation.tool_calls)
        ]
        return [ModelResponse(parts=parts), _terminal(TERMINAL_RESPOND)]

    if expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL:
        return [_terminal(TERMINAL_CLARIFY)]
    return [_terminal(TERMINAL_RESPOND)]


def _terminal(content: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=content)])


def build_model_from_responses(
    responses: Sequence[ModelResponse],
    *,
    recorder: ModelCallRecorder | None = None,
) -> Model:
    """Build a fail-loud ordered ``FunctionModel`` wrapped by a recorder."""
    ordered = list(responses)
    index = {"value": 0}

    def _respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        current = index["value"]
        index["value"] += 1
        if current >= len(ordered):
            raise AssertionError("scripted eval model received an unexpected extra request")
        return ordered[current]

    return RecordingPydanticModel(FunctionModel(_respond), recorder=recorder)


def build_scripted_model(
    expectation: EvalExpectation,
    *,
    recorder: ModelCallRecorder | None = None,
) -> Model:
    """Build the deterministic scripted-oracle model for one case."""
    return build_model_from_responses(script_responses(expectation), recorder=recorder)


def build_failing_model(error: Exception, *, recorder: ModelCallRecorder | None = None) -> Model:
    """Build a model that fails loudly on its first semantic request (tests)."""

    def _respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise error

    return RecordingPydanticModel(FunctionModel(_respond), recorder=recorder)


def tool_call_response(tool_name: str, arguments: dict[str, Any]) -> ModelResponse:
    """Helper for negative candidate tests: a single wrong tool call."""
    return ModelResponse(
        parts=[ToolCallPart(tool_name=tool_name, args=arguments, tool_call_id="call_0")]
    )


def terminal_response(kind: str, message: str = "Ок.") -> ModelResponse:
    """Helper for negative candidate tests: an explicit terminal response."""
    content = json.dumps({"kind": kind, "message": message}, ensure_ascii=False)
    return _terminal(content)
