"""Unit tests: model recording seam and scripted oracle scripts (S14-06)."""

from __future__ import annotations

import asyncio

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters

from dnd_assistant.composition.eval_model import (
    ModelCallRecorder,
    RecordingPydanticModel,
    build_failing_model,
    build_model_from_responses,
    script_responses,
)
from dnd_assistant.evals.contracts import (
    EvalExpectation,
    ExpectedToolCall,
    ScenarioExpectationKind,
)


def _run(model: Model, messages: list[object] | None = None) -> object:
    async def _go() -> object:
        return await model.request(
            messages=messages or [],  # type: ignore[arg-type]
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
        )

    return asyncio.run(_go())


def test_no_tool_script_is_single_terminal() -> None:
    expectation = EvalExpectation(ScenarioExpectationKind.RESPOND_NO_TOOL)
    responses = script_responses(expectation)
    assert len(responses) == 1
    assert any(isinstance(part, TextPart) for part in responses[0].parts)


def test_tool_script_is_batch_then_terminal() -> None:
    expectation = EvalExpectation(
        ScenarioExpectationKind.EXACT_TOOL_CALLS,
        tool_calls=(ExpectedToolCall("get_entity", {"entity_id": "npc-x"}),),
    )
    responses = script_responses(expectation)
    assert len(responses) == 2
    assert any(isinstance(part, ToolCallPart) for part in responses[0].parts)
    assert any(isinstance(part, TextPart) for part in responses[1].parts)


def test_recorder_counts_successful_request() -> None:
    recorder = ModelCallRecorder()
    model = build_model_from_responses(
        [ModelResponse(parts=[TextPart(content="x")])], recorder=recorder
    )
    assert isinstance(model, RecordingPydanticModel)
    _run(model)
    assert recorder.request_count == 1
    assert len(recorder.responses) == 1
    assert recorder.failures == []


def test_recorder_counts_failed_request() -> None:
    recorder = ModelCallRecorder()
    model = build_failing_model(RuntimeError("boom"), recorder=recorder)
    try:
        _run(model)
    except RuntimeError:
        pass
    assert recorder.request_count == 1
    assert recorder.failures == ["RuntimeError: boom"]


def test_extra_request_fails_loudly() -> None:
    recorder = ModelCallRecorder()
    model = build_model_from_responses(
        [ModelResponse(parts=[TextPart(content="x")])], recorder=recorder
    )
    _run(model)
    try:
        _run(model)
    except AssertionError as exc:
        assert "unexpected extra request" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected a fail-loud error on the extra request")
