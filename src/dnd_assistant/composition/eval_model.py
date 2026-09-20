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

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from dnd_assistant.composition.eval_failure_diagnostics import bounded_cause_chain
from dnd_assistant.composition.eval_trace import (
    EVENT_REQUEST_COMPLETED,
    EVENT_REQUEST_FAILED,
    EVENT_REQUEST_STARTED,
)
from dnd_assistant.evals.contracts import (
    EvalExpectation,
    ScenarioExpectationKind,
    sanitize_type_token,
)

TERMINAL_RESPOND = '{"kind":"respond","message":"Готово."}'
TERMINAL_CLARIFY = '{"kind":"clarify","message":"Уточните цель, пожалуйста."}'


@dataclass(frozen=True, slots=True)
class ModelCallFailure:
    """Bounded structured evidence of one failed semantic model request."""

    request_index: int
    exception_type: str
    cause_chain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelRequestTraceEvent:
    """Bounded, non-sensitive observation of one semantic request lifecycle step.

    Carries only sanitized type names, response *part types*, tool *names* and a
    public integer HTTP status.  Never carries messages, prompts, arguments or
    raw exception text.
    """

    request_index: int
    outcome: str
    duration_seconds: float | None = None
    response_part_types: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    exception_type: str | None = None
    cause_chain: tuple[str, ...] = ()
    provider_http_status: int | None = None


RequestTraceObserver = Callable[[ModelRequestTraceEvent], None]


@dataclass(slots=True)
class ModelCallRecorder:
    """Mutable literal record of semantic model requests for one sample."""

    request_count: int = 0
    responses: list[ModelResponse] = field(default_factory=list)
    request_durations: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    failure_records: list[ModelCallFailure] = field(default_factory=list)
    request_observer: RequestTraceObserver | None = None

    @property
    def first_response(self) -> ModelResponse | None:
        """The first recorded model response, if any."""
        return self.responses[0] if self.responses else None

    def observe(self, event: ModelRequestTraceEvent) -> None:
        """Forward a bounded trace event; any observer failure is non-fatal."""
        observer = self.request_observer
        if observer is None:
            return
        try:
            observer(event)
        except Exception:  # noqa: BLE001 - trace must never alter model semantics
            pass


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
        request_index = self.recorder.request_count - 1

        # Persist request_started *before* the wrapped call so a process kill
        # inside framework/provider/HTTP still leaves a diagnostic boundary.
        self.recorder.observe(
            ModelRequestTraceEvent(request_index=request_index, outcome=EVENT_REQUEST_STARTED)
        )

        start = self._clock()
        try:
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
        except Exception as exc:  # noqa: BLE001 - failure evidence is the point
            duration = self._clock() - start
            self.recorder.request_durations.append(duration)
            self.recorder.failures.append(f"{type(exc).__name__}: {exc}")
            failure = ModelCallFailure(
                request_index=request_index,
                exception_type=sanitize_type_token(type(exc).__name__),
                cause_chain=bounded_cause_chain(exc),
            )
            self.recorder.failure_records.append(failure)
            self.recorder.observe(
                ModelRequestTraceEvent(
                    request_index=request_index,
                    outcome=EVENT_REQUEST_FAILED,
                    duration_seconds=duration,
                    exception_type=failure.exception_type,
                    cause_chain=failure.cause_chain,
                    provider_http_status=_provider_http_status(exc),
                )
            )
            raise
        duration = self._clock() - start
        self.recorder.request_durations.append(duration)
        self.recorder.responses.append(response)
        self.recorder.observe(
            ModelRequestTraceEvent(
                request_index=request_index,
                outcome=EVENT_REQUEST_COMPLETED,
                duration_seconds=duration,
                response_part_types=tuple(type(part).__name__ for part in response.parts),
                tool_names=tuple(
                    part.tool_name for part in response.parts if isinstance(part, ToolCallPart)
                ),
            )
        )
        return response


def _provider_http_status(exc: BaseException) -> int | None:
    """Return the public HTTP status from a Pydantic AI ``ModelHTTPError``.

    Only the public integer ``status_code`` is read; response bodies and headers
    are never inspected or persisted.
    """
    if isinstance(exc, ModelHTTPError):
        return exc.status_code
    return None


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
